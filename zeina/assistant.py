"""
Main assistant orchestrator for Zeina AI Assistant.

Drives the audio → transcription → tool-calling → LLM → TTS pipeline. The LLM
backend is any OpenAI-compatible server (see zeina/llm.py); this module never
talks to a specific runtime directly.

The Kivy GUI (ui/app.py) owns the window, keyboard, and audio input stream and
calls into this orchestrator. There is no terminal mode.
"""
import sounddevice as sd
import soundfile as sf
import numpy as np
import whisper
import threading
import sys
import os
import re
import time
import difflib
import queue as _queue
from typing import Optional
import torch
from collections import deque

from zeina import config
from zeina import llm
from zeina import memory_extractor
from zeina.enums import InteractionMode, RecordingState
from zeina.audio import AudioRecorder
from zeina.tts import TTSEngine
from zeina.tools import tool_manager, set_memory_callback, set_ui_control_callback

# Observability rank map (higher = more verbose)
_OBS_RANK = {"off": 0, "lite": 1, "verbose": 2}


def _ui_show_hide(text: str) -> str:
    """Determine 'show' or 'hide' from natural-language phrasing."""
    if any(w in text for w in ("show", "open", "on", "enable", "visible")):
        return "show"
    return "hide"


class ZeinaAssistant:
    """Main assistant orchestrator"""

    # Status message constants
    VOICE_MODE_READY_STATUS = "Push to talk"
    CHAT_MODE_READY_STATUS = "Enter a message"
    PROCESSING_STATUS = "Processing..."
    SPEAKING_STATUS = "Speaking... (push to interrupt)"
    CHAT_SPEAKING_STATUS = "Speaking..."

    # Tools that must run sequentially with UI guards (window hide/raise).
    _SEQUENTIAL_TOOLS = {"take_screenshot", "execute_shell", "control_self"}

    def __init__(self, display=None, settings=None):
        # The display is always provided by the Kivy app; required.
        self.display = display
        self.settings = settings

        # Wire up memory callback so the `remember` tool writes to the active profile
        if self.settings:
            set_memory_callback(
                lambda fact: self.settings.append_memories(config.ACTIVE_PROFILE, [fact])
            )

        # Show temporary init message
        print("🤖 Initializing Zeina AI Assistant...")

        # Initialize interaction mode
        self.mode = InteractionMode.VOICE
        self.mode_lock = threading.Lock()
        self.chat_input_thread = None

        # Initialize state machine
        self.state = RecordingState.IDLE
        self.state_lock = threading.Lock()  # Protect state transitions
        self.is_speaking = False  # Track if TTS is currently speaking
        self._speaking_lock = threading.Lock()  # Protect is_speaking across threads

        # Event log
        self.event_log = deque(maxlen=50)

        # Multi-turn follow-up tracking
        self._last_turn_had_tool_call = False
        self._last_tools_used: list[str] = []

        # Background memory-extraction threads (joined on shutdown)
        self._memory_threads: list[threading.Thread] = []

        # Initialize conversation memory
        self.conversation_history = []
        if self.settings:
            self.refresh_system_prompt(reason="startup")
        else:
            self.conversation_history.append({"role": "system", "content": config.SYSTEM_PROMPT})

        # Session path for incremental writes (set once per app run)
        self._session_path: Optional[str] = None

        # Seed history from recent sessions and start a new session file
        if self.settings and config.SAVE_CONVERSATION_HISTORY:
            recent = self.settings.load_recent_messages(
                self.settings.active_profile_name, config.MAX_CONVERSATION_LENGTH
            )
            if recent:
                self.conversation_history.extend(recent)
            self._session_path = self.settings.start_session(
                self.settings.active_profile_name
            )
            banner = self.settings.get_system_state_banner(self._prompt_runtime_state())
            self._log_system_state_event(banner, "session start")

        # Initialize components
        self._load_models()
        self._load_vad_model()
        self._initialize_audio()
        self._initialize_tts()
        self._check_llm_connection()

        # Set initial status before starting face
        status, style = self._get_mode_ready_status()
        self.display.show_status_centered(status, style)

        # Set initial menu bar values
        self.display.show_menu_bar(self.mode, self.settings.get("bot_name", "Zeina") if self.settings else "Zeina")

        # Start face display (will clear screen and set up layout with menu bar at top)
        self.display.start_face_display()
        self.display.clear_feed()

    def _get_voice_ready_status(self) -> tuple[str, str]:
        """Get ready status message and style for voice mode"""
        return self.VOICE_MODE_READY_STATUS, "cyan"

    def _get_chat_ready_status(self) -> tuple[str, str]:
        """Get ready status message and style for chat mode"""
        return self.CHAT_MODE_READY_STATUS, "green"

    def _get_mode_ready_status(self) -> tuple[str, str]:
        """Get ready status message and style for current mode"""
        if self.mode == InteractionMode.VOICE:
            return self._get_voice_ready_status()
        else:
            return self._get_chat_ready_status()

    def _prompt_runtime_state(self) -> dict:
        """Values injected into the system prompt for configuration awareness."""
        if not self.settings:
            return {}
        return {
            "mode": self.mode.value,
        }

    def _log_system_state_event(self, banner: str, reason: Optional[str] = None) -> None:
        """Persist the latest runtime snapshot into the session log."""
        session_path = getattr(self, "_session_path", None)
        if not (self.settings and session_path and config.SAVE_CONVERSATION_HISTORY):
            return
        entry = reason or "state refresh"
        self.settings.append_session_event(session_path, entry)

    def _build_llm_messages(self) -> list[dict]:
        """Return system prompt + runtime state banner + conversation history.

        The state banner is front-loaded (right after the main system prompt)
        rather than spliced before the last user turn, so it never lands between
        an assistant tool-call message and its tool results (which would violate
        the OpenAI tool-calling message ordering).
        """
        if not self.conversation_history:
            return []
        if not self.settings:
            return list(self.conversation_history)

        runtime_state = self._prompt_runtime_state()
        system_msg = {"role": "system", "content": self.settings.get_system_prompt(runtime_state)}
        state_msg = {"role": "system", "content": self.settings.get_system_state_banner(runtime_state)}

        non_system_history = [m for m in self.conversation_history if m["role"] != "system"]
        return [system_msg, state_msg] + non_system_history

    def _set_speaking(self, value: bool) -> None:
        """Thread-safe setter for is_speaking."""
        with self._speaking_lock:
            self.is_speaking = value

    def _get_speaking(self) -> bool:
        """Thread-safe getter for is_speaking."""
        with self._speaking_lock:
            return self.is_speaking

    def refresh_system_prompt(self, reason: Optional[str] = None) -> None:
        """Rebuild the system prompt when runtime configuration changes."""
        if not self.settings:
            return
        runtime_state = self._prompt_runtime_state()
        banner = self.settings.get_system_state_banner(runtime_state)
        self._log_system_state_event(banner, reason)
        if reason:
            self._obs("lite", f"System prompt updated ({reason})")
            full_prompt = self.settings.get_system_prompt(runtime_state)
            self._obs("verbose", f"Updated system prompt ({len(full_prompt)} chars):\n{full_prompt}")

    def _cleanup_voice_mode(self):
        """Clean up voice mode state when switching away.
        Only stops TTS if the speaking toggle is off."""
        if self.state == RecordingState.LISTENING:
            self.audio_recorder.stop()
            self.state = RecordingState.IDLE
        speaking_enabled = getattr(self.display, 'toggles', {}).get('speaking', True)
        if self._get_speaking() and not speaking_enabled:
            self.tts_engine.stop()
            self._set_speaking(False)

    def _cleanup_chat_mode(self):
        """Clean up chat mode state when switching away"""
        # Chat mode cleanup is minimal - just reset audio state
        self.audio_recorder.stop()
        self.state = RecordingState.IDLE

    def _load_models(self):
        """Load all AI models once at startup"""
        print(f"📝 Loading Whisper model ({config.WHISPER_MODEL})...")
        self.whisper_model = whisper.load_model(
            config.WHISPER_MODEL,
            device=config.WHISPER_DEVICE
        )
        print("✓ Whisper model loaded")

    def _load_vad_model(self):
        """Load Silero VAD model for voice activity detection"""
        print("🎙️  Loading VAD model...")
        try:
            model, utils = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                force_reload=False,
                onnx=False
            )
            self.vad_model = model
            print("✓ VAD model loaded")
        except Exception as e:
            print(f"❌ Error loading VAD model: {e}")
            print("VAD model is required for auto-stop functionality.")
            sys.exit(1)

    def _initialize_audio(self):
        """Initialize audio recording system"""
        self.audio_recorder = AudioRecorder(
            sample_rate=config.SAMPLE_RATE,
            channels=config.CHANNELS,
            vad_model=self.vad_model,
            stop_callback=self._handle_auto_stop
        )

    def _initialize_tts(self):
        """Initialize text-to-speech engine"""
        print("🎙️  Setting up TTS...")
        self.tts_engine = TTSEngine(voice=config.TTS_VOICE)

    def _check_llm_connection(self):
        """Verify the OpenAI-compatible model server is reachable.

        Does not exit on failure — the client is lazy, so the server can come up
        later and calls will succeed. We just surface a clear, actionable warning.
        """
        print(f"🧠 Checking model server at {config.LLM_BASE_URL} ...")
        ok, detail = llm.health()
        if ok:
            print(f"✓ Connected to model server (models: {detail})")
            ids = llm.list_model_ids()
            if ids and config.CHAT_MODEL not in ids:
                print(
                    f"⚠️  Configured model '{config.CHAT_MODEL}' isn't in the served list. "
                    f"Pick one in Settings or set ZEINA_CHAT_MODEL. Served: {', '.join(ids[:8])}"
                )
            return
        print(f"❌ Can't reach the model server at {config.LLM_BASE_URL}")
        print(f"   {detail}")
        print("   Start your llama.cpp/llama-swap (or Ollama) server, or set ZEINA_LLM_BASE_URL.")

    def _save_conversation(self):
        """Wait for any in-flight memory extraction to finish before the app exits."""
        for t in list(self._memory_threads):
            if t.is_alive():
                t.join(timeout=8)

    def _log_event(self, message: str):
        """Record a short event for observability"""
        timestamp = time.strftime("%H:%M:%S")
        self.event_log.append(f"{timestamp} {message}")

    def _log_api(self, message: str):
        """Log an API event to the event log only (no GUI output)."""
        self._log_event(message)

    def _obs(self, level: str, message: str):
        """Gate-controlled terminal log. Always appends to event_log for diagnostics."""
        self._log_event(message)
        current = getattr(config, 'OBSERVABILITY_LEVEL', 'lite')
        if _OBS_RANK.get(current, 1) >= _OBS_RANK.get(level, 1):
            ts = time.strftime("%H:%M:%S")
            print(f"[{ts}] [{level.upper()}] {message}", flush=True)

    def _handle_auto_stop(self, reason: str):
        """Called when VAD detects silence or timeout"""
        if self.state == RecordingState.LISTENING:
            if reason == "silence":
                self._obs("verbose", "Auto-stop (silence)")
                self.set_state(RecordingState.PROCESSING, "Auto-stopped", "green")
                threading.Thread(
                    target=self.process_audio_pipeline,
                    daemon=True
                ).start()
            elif reason == "timeout":
                self._obs("verbose", "Auto-stop (timeout)")
                self.audio_recorder.stop()
                self.set_state(RecordingState.IDLE, "No speech detected", "red")
                time.sleep(1.5)
                self.set_state(RecordingState.IDLE)

    def set_state(self, new_state: RecordingState, status: str = "", status_style: str = "green"):
        """Update the assistant's state, face, and status message."""
        with self.state_lock:
            self.state = new_state
        self.display.update_face_state(self.state, self._get_speaking())

        if not status and new_state == RecordingState.IDLE:
            status, status_style = self._get_mode_ready_status()

        if status:
            self.display.show_status_centered(status, status_style)

    def handle_chat_input(self, user_message: str):
        """Handle text chat input"""
        if not user_message.strip():
            return
        try:
            self._obs("lite", f"User: {user_message}")
            self.display.show_user_message(user_message)

            self.set_state(RecordingState.PROCESSING, self.PROCESSING_STATUS, "magenta")

            assistant_response = self._get_llm_response(user_message, show_detail=False)

            # Speak if the speaking toggle is on (defaults to False in chat;
            # terminal Display has no toggles so this block is skipped)
            speaking_enabled = getattr(self.display, 'toggles', {}).get('speaking', False)
            if speaking_enabled:
                self.display.show_status_centered(self.CHAT_SPEAKING_STATUS, "blue")
                self._set_speaking(True)
                self.display.update_face_state(self.state, self._get_speaking())
                self.tts_engine.speak(assistant_response)
                self._set_speaking(False)
                self.display.update_face_state(self.state, self._get_speaking())
        finally:
            self.set_state(RecordingState.IDLE)
            time.sleep(0.3)

    def start_listening(self, mode: str = "manual"):
        """Start listening for user input.

        Modes: "manual" (spacebar), "auto" (after a response), "interrupt".
        """
        if self.state == RecordingState.IDLE or self.state == RecordingState.LISTENING:
            self.audio_recorder.stop()
            self.audio_recorder.start()

            self._obs("verbose", f"Listening started ({mode})")
            self.state = RecordingState.LISTENING
            self.display.update_face_state(self.state, self._get_speaking())
            self.display.show_status_centered("Listening...", "green")

    def _save_audio_to_file(self, audio_data: np.ndarray, filename: str):
        """Save audio data to a WAV file"""
        sf.write(filename, audio_data, config.SAMPLE_RATE)

    def _transcribe_audio(self, audio_file: str) -> Optional[str]:
        """Transcribe audio file to text using Whisper"""
        result = self.whisper_model.transcribe(
            audio_file,
            language="en",
            fp16=False
        )
        transcription = result['text'].strip()
        return transcription if transcription else None

    # ── Tool routing & execution ──────────────────────────────────────────────

    def _get_tool_schemas(self, exclude_control_self: bool = False) -> list[dict]:
        """Return OpenAI tool schemas, optionally excluding control_self."""
        schemas = []
        for name, tool in tool_manager.tools.items():
            if name == 'control_self' and exclude_control_self:
                continue
            schemas.append(tool.to_openai_schema())
        return schemas

    def _is_duplicate_memory(self, fact: str) -> bool:
        """Check if a fact is already stored using string similarity."""
        if not fact or not self.settings:
            return False
        existing = self.settings.load_memories(config.ACTIVE_PROFILE)
        if not existing:
            return False
        fact_lower = fact.lower().strip()
        for mem in existing:
            if difflib.SequenceMatcher(None, fact_lower, mem.lower()).ratio() > 0.8:
                return True
        return False

    def _sanitize_calls(self, calls: list[dict]) -> list[dict]:
        """Validate model tool calls: drop unknowns, dedupe screenshots, skip
        duplicate memories. ``calls`` are {"id", "name", "arguments"} dicts."""
        out: list[dict] = []
        seen_screenshot = False
        for c in calls:
            name, args = c["name"], c["arguments"]
            if name not in tool_manager.tools:
                self._obs("verbose", f"Unknown tool from model: {name}")
                continue
            if name == "take_screenshot":
                if seen_screenshot:
                    continue
                seen_screenshot = True
            if name == "remember":
                if self._is_duplicate_memory(args.get("fact", "")):
                    self._obs("lite", "Memory: duplicate fact, skipping")
                    continue
            out.append(c)
            self._obs("lite", f"Intent [{config.CHAT_MODEL}]: {name}")
        return out

    def _run_model_tool_calls(self, working: list[dict], router_msg, calls: list[dict],
                              user_message: str) -> None:
        """Execute model-issued tool calls and append the assistant(tool_calls)
        message plus matching tool-result messages to ``working``."""
        # Required by the protocol: the assistant tool-call message must precede
        # the tool results.
        working.append(llm.assistant_tool_call_msg(router_msg))

        results: dict[str, str] = {}

        parallel = [c for c in calls if c["name"] not in self._SEQUENTIAL_TOOLS]
        sequential = [c for c in calls if c["name"] in self._SEQUENTIAL_TOOLS]

        if parallel:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=4) as pool:
                futs = {
                    pool.submit(tool_manager.execute_tool, c["name"], c["arguments"]): c
                    for c in parallel
                }
                for fut in as_completed(futs):
                    c = futs[fut]
                    res = fut.result()
                    results[c["id"]] = res
                    self._obs("lite", f"Tool: {c['name']} → {len(res)} chars")
                    self._obs("verbose", f"Tool result:\n{res}")

        for c in sequential:
            name, args = c["name"], c["arguments"]
            if name == "take_screenshot":
                res = self._run_screenshot_tool(args, user_message)
            else:
                res = tool_manager.execute_tool(name, args)
                if name == "execute_shell" and hasattr(self.display, 'raise_window'):
                    self.display.raise_window(delay=0.2)
            results[c["id"]] = res
            self._obs("lite", f"Tool: {name} → {len(res)} chars")
            self._obs("verbose", f"Tool result:\n{res}")

        # Append tool results in the same order as the tool_calls.
        for c in calls:
            working.append({
                "role": "tool",
                "tool_call_id": c["id"],
                "content": results.get(c["id"], "(no result)"),
            })

    def _run_screenshot_tool(self, args: dict, user_message: str) -> str:
        """Capture the screen (with the window hidden) and return a vision read."""
        if hasattr(self.display, 'hide_window'):
            self.display.hide_window()
        path = tool_manager.execute_tool("take_screenshot", args)
        if hasattr(self.display, 'show_window'):
            self.display.show_window()

        description = self._handle_vision_query(path, user_message)
        if description:
            return f"Here is what is currently on the user's screen:\n{description}"
        return ("The screen capture failed — you could not see the screen. "
                "Let the user know and ask them to try again.")

    def _run_stage0_actions(self, working: list[dict], actions: list[dict],
                            user_message: str) -> None:
        """Execute regex-matched control_self actions and append an
        acknowledgement note (these have no tool_call_id, so they can't be
        tool-role messages)."""
        results = []
        for action in actions:
            res = tool_manager.execute_tool("control_self", action)
            self._obs("lite", f"Tool: control_self → {res}")
            results.append(res)
        note = "; ".join(r for r in results if r)
        working.append({
            "role": "user",
            "content": (f"[You just did this: {note}] Acknowledge it briefly and "
                        f"naturally to the user. Their request was: {user_message}"),
        })

    def _extract_name(self, message: str) -> str:
        """Use the router model to pull a proper name out of a message."""
        try:
            msg = llm.chat(
                [{
                    "role": "user",
                    "content": (
                        "Extract the name from this message. Reply with ONLY the name, nothing else.\n"
                        "Examples:\n"
                        "  'change your name to Luna' → Luna\n"
                        "  'call me Yusuf from now on' → Yusuf\n"
                        "  'rename yourself Alex' → Alex\n\n"
                        f"Message: \"{message}\""
                    ),
                }],
                model=config.ROUTER_MODEL,
                temperature=0,
            )
            return (msg.content or "").strip()
        except Exception:
            return ""

    def _maybe_summarize_history(self) -> None:
        """Summarize old conversation turns when history grows too long.

        Falls back to simple truncation if the summarization call fails.
        """
        if config.MAX_CONVERSATION_LENGTH <= 0:
            return
        if len(self.conversation_history) <= config.MAX_CONVERSATION_LENGTH + 4:
            return

        keep_recent = max(config.MAX_CONVERSATION_LENGTH // 2, 4)
        to_summarize = self.conversation_history[1:-keep_recent]
        recent = self.conversation_history[-keep_recent:]

        if not to_summarize:
            return

        text = "\n".join(
            f"{m['role'].upper()}: {str(m.get('content', ''))[:300]}"
            for m in to_summarize
        )
        try:
            msg = llm.chat(
                [{
                    "role": "user",
                    "content": (
                        "Summarize this conversation in 2-3 sentences, preserving key facts, "
                        f"names, and any decisions made:\n\n{text}"
                    ),
                }],
                model=config.ROUTER_MODEL,
                temperature=0,
            )
            summary = (msg.content or "").strip()
            if summary:
                summary_msg = {
                    "role": "assistant",
                    "content": f"[Earlier conversation summary: {summary}]",
                }
                self.conversation_history = [self.conversation_history[0], summary_msg] + recent
                self._obs("lite", f"History summarized: {len(to_summarize)} msgs → 1 summary")
                return
        except Exception as e:
            self._obs("lite", f"Summarization failed ({e}), falling back to truncation")

        self.conversation_history = [self.conversation_history[0]] + \
            self.conversation_history[-(config.MAX_CONVERSATION_LENGTH):]

    def _get_llm_response(self, user_message: str, show_detail: bool = True,
                          voice_streaming: bool = False) -> str:
        """Run one full turn: tool routing (unified loop) + final response.

        Pipeline:
          Stage 0  regex fast-path for control_self (zero LLM cost).
          Stage 1  one tool-calling pass on the main model. If it returns tool
                   calls, execute them and do a second call for the spoken answer.
                   If it returns no calls and there are no Stage-0 actions, reuse
                   its text directly — saving a round-trip on the common path.

        Tool-call/result messages live only in a turn-local ``working`` list; the
        persisted conversation_history stays clean user/assistant pairs.
        """
        self.conversation_history.append({"role": "user", "content": user_message})

        if getattr(config, 'DEBUG_CONVERSATION', False):
            print("\n🔍 Debug - Recent Conversation (last 5 messages):")
            recent_msgs = self.conversation_history[-5:]
            for msg in recent_msgs:
                role = msg.get('role', 'unknown')
                content = str(msg.get('content', ''))
                if len(content) > 80:
                    content = content[:80] + "..."
                print(f"  {role}: {content}")
            print()

        self._maybe_summarize_history()

        # Stage 0: deterministic control_self matching.
        stage0_actions = []
        if 'control_self' in tool_manager.tools:
            stage0_actions = self._extract_ui_actions_multi(user_message)
            if stage0_actions:
                self._obs("lite", f"Intent: control_self ×{len(stage0_actions)} (patterns)")

        # working = base context for this turn (system + history). Tool messages
        # are appended here only, never to the persisted history.
        working = self._build_llm_messages() or list(self.conversation_history)

        direct_answer: Optional[str] = None
        tools_used: list[str] = []

        if tool_manager.has_tools():
            schemas = self._get_tool_schemas(exclude_control_self=bool(stage0_actions))
            router_msg = None
            if schemas:
                try:
                    router_msg = llm.chat(
                        working, model=config.CHAT_MODEL, tools=schemas, temperature=0
                    )
                except Exception as e:
                    self._obs("lite", f"Tool routing error: {e}")

            calls = self._sanitize_calls(llm.parse_tool_calls(router_msg)) if router_msg else []

            if calls:
                self.display.move_cursor_to_feed_bottom()
                label = ", ".join(dict.fromkeys(c["name"] for c in calls))
                self.display.show_info(f"Using tool: {label}")
                self._run_model_tool_calls(working, router_msg, calls, user_message)
                tools_used.extend(c["name"] for c in calls)
            elif router_msg is not None and not stage0_actions:
                # No tools needed, nothing UI-side → reuse the model's answer.
                direct_answer = (router_msg.content or "").strip()
                self._obs("lite", f"Intent [{config.CHAT_MODEL}]: none")

        if stage0_actions:
            self._run_stage0_actions(working, stage0_actions, user_message)
            tools_used.append("control_self")

        self._last_turn_had_tool_call = bool(tools_used)
        self._last_tools_used = list(dict.fromkeys(tools_used))

        can_stream = getattr(self.display, 'has_streaming', False)
        speaking = getattr(self.display, 'toggles', {}).get('speaking', True)
        use_tts = voice_streaming and getattr(self, 'tts_engine', None) and speaking

        # ── Produce the final answer ──────────────────────────────────────────
        if direct_answer is not None:
            content = direct_answer or "Sorry, I didn't catch that. Could you say it again?"
            if can_stream:
                self.display.begin_stream()
                self.display.stream_token(content)
            else:
                self.display.show_assistant_message(content)
            if use_tts:
                self._speak_text(content)
        else:
            self._obs("lite", f"LLM [{config.CHAT_MODEL}] ({len(working)} msgs)")
            if use_tts:
                content = self._stream_and_speak(working)
            else:
                content = self._stream_to_display(working)
            if not content:
                content = "Sorry, I didn't quite get that. Could you try again?"
                if can_stream:
                    self.display.stream_token(content)
                else:
                    self.display.show_assistant_message(content)

        self.conversation_history.append({"role": "assistant", "content": content})
        self._obs("lite", f"Response: {content}")
        if "take_screenshot" in self._last_tools_used:
            self._obs("verbose", f"Vision interpretation [{config.CHAT_MODEL}]: {content}")

        # Persist exchange to session file (incremental; survives crashes)
        if self.settings and self._session_path and config.SAVE_CONVERSATION_HISTORY:
            self.settings.append_to_session(self._session_path, user_message, content)

        # Extract user memories asynchronously. Skip after tool turns — they're
        # task-oriented and rarely contain personal facts.
        if (self.settings and self.settings.get("memory_enabled", True)
                and not self._last_turn_had_tool_call):
            t = threading.Thread(
                target=memory_extractor.extract_memories,
                args=(self.settings, user_message),
                kwargs={"obs": self._obs, "on_saved": lambda: self.display.show_log("Memory saved")},
                daemon=False,
            )
            t.start()
            self._memory_threads = [x for x in self._memory_threads if x.is_alive()]
            self._memory_threads.append(t)

        return content

    def _stream_to_display(self, messages: list[dict]) -> str:
        """Run the final (no-tools) answer call, streaming to the display."""
        can_stream = getattr(self.display, 'has_streaming', False)
        if can_stream:
            # Render onto the face when chat is hidden AND TTS muted.
            if hasattr(self.display, '_force_face_stream'):
                if not self.display.toggles.get('speaking', True):
                    self.display._force_face_stream = not self.display.toggles.get('chat', True)
            self.display.begin_stream()
            acc = ""
            for token in llm.chat(messages, model=config.CHAT_MODEL, stream=True):
                acc += token
                self.display.stream_token(token)
            return acc.strip()
        msg = llm.chat(messages, model=config.CHAT_MODEL)
        content = (msg.content or "").strip()
        self.display.show_assistant_message(content)
        return content

    def _handle_vision_query(self, screenshot_path: str, user_message: str = "") -> str:
        """Call the vision model on a screenshot and return its description.

        The description is injected as context for the main LLM, which responds
        with Zeina's personality as if actively looking at the screen.
        """
        vision_model = (
            self.settings.get("vision_model", config.VISION_MODEL)
            if self.settings else config.VISION_MODEL
        )

        # Validate the capture — a blank/black capture (e.g. macOS Screen
        # Recording permission denied) is a tiny file that makes vision models
        # hallucinate.
        try:
            file_size = os.path.getsize(screenshot_path)
        except OSError:
            self._obs("lite", "Vision: screenshot file missing — aborting")
            return ""

        if file_size < 10_000:
            self._obs("lite", f"Vision: screenshot too small ({file_size} bytes) — likely blank; "
                              f"check macOS Screen Recording permission")
            try:
                os.remove(screenshot_path)
            except OSError:
                pass
            return ""

        # Resize to max 1280px wide to keep inference fast.
        try:
            from PIL import Image
            img = Image.open(screenshot_path)
            if img.width > 1280:
                img = img.resize((1280, int(img.height * 1280 / img.width)), Image.LANCZOS)
                img.save(screenshot_path)
        except Exception:
            pass

        self._obs("lite", f"Vision: screenshot {file_size // 1024} KB → {screenshot_path}")

        messages = [
            {"role": "system", "content": (
                "You are a precise screen reader. Describe ONLY what is literally visible in the "
                "screenshot with as much detail as possible: every window title, app name, menu, "
                "button label, visible text (quote it verbatim), error messages, code snippets, "
                "URL in the address bar, file names, icons, and the overall layout. "
                "Do NOT invent, infer, or add anything not directly visible. "
                "If something is partially obscured or unclear, say so explicitly."
            )},
            {"role": "user", "content": [
                {"type": "text", "text": user_message or "What do you see on the screen?"},
                {"type": "image_url", "image_url": {"url": llm.image_data_uri(screenshot_path)}},
            ]},
        ]

        description = ""
        try:
            for token in llm.chat(messages, model=vision_model, stream=True):
                description += token
        except Exception as e:
            self._obs("lite", f"Vision model error: {e}")

        description = description.strip()
        self._obs("lite", f"Vision [{vision_model}]: {description}")

        try:
            os.remove(screenshot_path)
        except OSError:
            pass

        return description

    # Sentence boundary: end punctuation + whitespace, or a paragraph break.
    _SENTENCE_END_RE = re.compile(r'(?<=[.!?])\s+|(?<=\n)\s*(?=\S)')

    def _stream_and_speak(self, messages: list) -> str:
        """Stream an LLM response and speak each sentence as it arrives.

        A daemon synthesis thread turns buffered sentences into WAV files while
        streaming continues, giving sentence-level TTS latency. Playback (with
        interrupt checks) runs on this thread after streaming ends.
        """
        sentence_q: _queue.Queue = _queue.Queue(maxsize=3)
        play_q: _queue.Queue = _queue.Queue()
        full_response: list[str] = []

        def _synth_worker():
            while True:
                try:
                    sentence = sentence_q.get(timeout=0.3)
                    if sentence is None:
                        break
                    try:
                        path = self.tts_engine.synthesize_to_file(sentence)
                        play_q.put(path)
                    except Exception as e:
                        self._obs("lite", f"TTS synthesis error: {e}")
                    finally:
                        sentence_q.task_done()
                except _queue.Empty:
                    continue

        synth_thread = threading.Thread(target=_synth_worker, daemon=True)
        synth_thread.start()

        buf = ""
        can_stream = getattr(self.display, 'has_streaming', False)
        if can_stream:
            self.display.begin_stream()

        try:
            for token in llm.chat(messages, model=config.CHAT_MODEL, stream=True):
                buf += token
                full_response.append(token)
                if can_stream:
                    self.display.stream_token(token)

                parts = self._SENTENCE_END_RE.split(buf, maxsplit=1)
                if len(parts) > 1 and len(parts[0].strip()) >= 8:
                    sentence_q.put(parts[0].strip())
                    buf = parts[1] if len(parts) > 1 else ""
        except Exception as e:
            self._obs("lite", f"Streaming LLM error: {e}")

        if buf.strip():
            sentence_q.put(buf.strip())

        sentence_q.put(None)
        synth_thread.join(timeout=60)

        # Audio is about to start — only NOW set is_speaking so PTT triggers an
        # interrupt during playback rather than during LLM computation.
        self._set_speaking(True)
        self.display.update_face_state(self.state, self._get_speaking())

        play_q.put(None)
        while True:
            path = play_q.get()
            if path is None:
                break
            if not self._check_interrupted():
                self.tts_engine.play_file(path)
            else:
                try:
                    os.remove(path)
                except OSError:
                    pass

        return "".join(full_response).strip()

    def _speak_text(self, text: str) -> None:
        """Speak a complete string sentence-by-sentence.

        Used for the direct-answer path (where the text wasn't token-streamed).
        Mirrors _stream_and_speak's playback + interrupt handling.
        """
        sentences = [s.strip() for s in self._SENTENCE_END_RE.split(text) if s.strip()]
        if not sentences:
            return

        self._set_speaking(True)
        self.display.update_face_state(self.state, self._get_speaking())

        for sentence in sentences:
            if self._check_interrupted():
                break
            try:
                path = self.tts_engine.synthesize_to_file(sentence)
            except Exception as e:
                self._obs("lite", f"TTS synthesis error: {e}")
                continue
            if not self._check_interrupted():
                self.tts_engine.play_file(path)
            else:
                try:
                    os.remove(path)
                except OSError:
                    pass

    def _check_interrupted(self) -> bool:
        """Return True if the user pressed spacebar to interrupt (is_speaking cleared)."""
        return not self._get_speaking()

    def process_audio_pipeline(self):
        """Audio → transcription → LLM → TTS → auto-listen."""
        temp_audio_file = None
        try:
            audio_data = self.audio_recorder.stop()
            if audio_data is None or len(audio_data) == 0:
                self.set_state(RecordingState.IDLE, "No audio recorded", "red")
                time.sleep(1.5)
                self.set_state(RecordingState.IDLE)
                return

            temp_audio_file = os.path.join(config.TMP_DIR, "temp_recording.wav")
            self._save_audio_to_file(audio_data, temp_audio_file)

            transcription = self._transcribe_audio(temp_audio_file)
            if not transcription:
                self.set_state(RecordingState.IDLE)
                return

            self._obs("lite", f"User: {transcription}")
            self.display.show_user_message(transcription)
            self.set_state(RecordingState.PROCESSING, self.PROCESSING_STATUS, "magenta")

            speaking_enabled = getattr(self.display, 'toggles', {}).get('speaking', True)
            if speaking_enabled and getattr(self, 'tts_engine', None):
                self.display.show_status_centered(self.SPEAKING_STATUS, "blue")
                assistant_response = self._get_llm_response(transcription, voice_streaming=True)
                self._set_speaking(False)
                self.display.update_face_state(self.state, self._get_speaking())
            else:
                assistant_response = self._get_llm_response(transcription)

            # Reset state after response (do not override active listening)
            if self.state != RecordingState.LISTENING and not self.audio_recorder.is_recording:
                self.set_state(RecordingState.IDLE)

            # Auto-listen for follow-up (voice mode only)
            if self.mode == InteractionMode.VOICE and not self.audio_recorder.is_recording:
                self.start_listening(mode="auto")

        except Exception as e:
            self.display.show_error(f"Error in audio pipeline: {e}")
            import traceback
            traceback.print_exc()
            self.set_state(RecordingState.IDLE)
        finally:
            if temp_audio_file and os.path.exists(temp_audio_file):
                os.remove(temp_audio_file)

    # ── UI-control regex fast-path (Stage 0) ───────────────────────────────────

    def _match_ui_patterns(self, m: str, message: str, multi: bool) -> list[dict]:
        """Shared pattern matching core for UI control actions.

        Args:
            m: pre-lowercased message text.
            message: original casing, used for LLM name/profile extraction.
            multi: True = collect all matches; False = return after first match.
        """
        results: list[dict] = []

        def _emit(action_dict: dict) -> bool:
            results.append(action_dict)
            return not multi

        # ── Theme ────────────────────────────────────────────────────────
        for theme in ("midnight", "terminal", "sunset", "default"):
            if theme in m:
                if _emit({"action": "set_theme", "value": theme}):
                    return results
                break

        # ── Animation (mutually exclusive) ───────────────────────────────
        if "ascii" in m:
            if _emit({"action": "set_animation", "value": "ascii"}):
                return results
        elif "vector" in m or "bmo" in m:
            if _emit({"action": "set_animation", "value": "vector"}):
                return results
        elif any(w in m for w in ("face style", "face animation", "animation style",
                                  "switch animation", "change animation", "switch face",
                                  "change face", "switch ur face", "change ur face")):
            if _emit({"action": "set_animation", "value": "toggle"}):
                return results

        # ── Mode (mutually exclusive) ─────────────────────────────────────
        if any(p in m for p in ("voice mode", "switch to voice", "go to voice",
                                "use voice", "activate voice", "voice input")):
            if _emit({"action": "set_mode", "value": "voice"}):
                return results
        elif any(w in m for w in ("chat mode", "text mode", "chat input", "switch to chat",
                                  "go to chat", "typing mode")):
            if _emit({"action": "set_mode", "value": "chat"}):
                return results

        # ── Pages ────────────────────────────────────────────────────────
        if "setting" in m:
            if _emit({"action": "open_settings"}):
                return results
        if "diagnostic" in m or "dashboard" in m:
            if _emit({"action": "open_diagnostics"}):
                return results

        # ── Clear ────────────────────────────────────────────────────────
        _clear_words = ("clear", "wipe", "reset", "delete", "erase", "forget")
        if any(w in m for w in _clear_words):
            if any(w in m for w in ("histor", "conversation", "chat", "messages")):
                if _emit({"action": "clear_history"}):
                    return results
            if any(w in m for w in ("memor", "everything", "all")):
                if _emit({"action": "clear_memories"}):
                    return results

        # ── Status bar ───────────────────────────────────────────────────
        if "status bar" in m or ("status" in m and "bar" in m):
            if _emit({"action": "set_status_bar", "value": _ui_show_hide(m)}):
                return results

        # ── Chat feed / transcript ────────────────────────────────────────
        if any(w in m for w in ("chat feed", "chat window", "transcript",
                                "show chat", "hide chat", "open chat", "close chat")):
            if _emit({"action": "set_chat_feed", "value": _ui_show_hide(m)}):
                return results

        # ── TTS mute (mutually exclusive) ─────────────────────────────────
        if "unmute" in m:
            if _emit({"action": "set_tts_mute", "value": "unmute"}):
                return results
        elif "mute" in m:
            if _emit({"action": "set_tts_mute", "value": "mute"}):
                return results

        # ── Profile switching (open-ended name → LLM) ────────────────────
        _profile_verbs = ("switch", "change", "go to", "use", "load",
                          "activate", "select", "swap")
        if "profile" in m and any(v in m for v in _profile_verbs):
            if _emit({"action": "switch_profile", "value": self._extract_name(message)}):
                return results

        # ── Menu button ───────────────────────────────────────────────────
        _menu_words = ("3 dot", "three dot", "dots menu", "menu button",
                       "dot menu", "3dot", "triple dot")
        if any(w in m for w in _menu_words) or ("menu" in m and "button" in m):
            if _emit({"action": "set_menu_button", "value": _ui_show_hide(m)}):
                return results

        return results

    def _extract_ui_action(self, message: str) -> dict:
        """Return the first matched UI control action for this message."""
        results = self._match_ui_patterns(message.lower(), message, multi=False)
        if results:
            return results[0]
        self._obs("verbose", f"control_self: no action matched for: {message}")
        return {"action": "", "value": ""}

    def _extract_ui_actions_multi(self, message: str) -> list[dict]:
        """Collect ALL UI control actions from a single message."""
        return self._match_ui_patterns(message.lower(), message, multi=True)
