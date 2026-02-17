"""
Main assistant orchestrator for Zeina AI Assistant
"""
import sounddevice as sd
import soundfile as sf
import numpy as np
import whisper
import ollama
from pynput import keyboard
import threading
import sys
import os
import time
import json
import re
import queue as _queue
from typing import Optional
from datetime import datetime
import torch
import readline  # Provides robust line editing
from collections import deque

from zeina import config
from zeina.enums import InteractionMode, RecordingState
from zeina.display import Display
from zeina.audio import AudioRecorder
from zeina.tts import TTSEngine
from zeina.tools import tool_manager, set_memory_callback

# Observability rank map (higher = more verbose)
_OBS_RANK = {"off": 0, "lite": 1, "verbose": 2}


class ZeinaAssistant:
    """Main assistant orchestrator"""

    # Status message constants
    VOICE_MODE_READY_STATUS = "Push to talk"
    CHAT_MODE_READY_STATUS = "Enter a message"
    PROCESSING_STATUS = "Processing..."
    SPEAKING_STATUS = "Speaking... (push to interrupt)"
    CHAT_SPEAKING_STATUS = "Speaking..."

    def __init__(self, display=None, settings=None):
        # Initialize display first (but don't show anything yet)
        self.display = display or Display()
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

        # Track terminal state
        self.terminal_fd = sys.stdin.fileno()
        self.original_terminal_settings = None
        try:
            import termios
            self.original_terminal_settings = termios.tcgetattr(self.terminal_fd)
        except (ImportError, OSError, AttributeError) as e:
            # termios not available on Windows, or not a TTY
            pass

        # Initialize state machine
        self.state = RecordingState.IDLE
        self.state_lock = threading.Lock()  # Protect state transitions
        self.last_key_press_time = 0
        self.key_debounce_delay = 0.3  # 300ms debounce to prevent accidental double-press
        self.is_speaking = False  # Track if TTS is currently speaking

        # Track modifier keys for shortcuts
        self.ctrl_pressed = False

        # Flag to prevent double-handling of keys in chat mode
        self.taking_chat_input = False

        # Event log
        self.event_log = deque(maxlen=50)

        # Multi-turn follow-up tracking
        self._last_turn_had_tool_call = False
        self._last_tool_used = None

        # Track the most recent memory extraction thread so shutdown can join it
        self._memory_thread = None  # type: threading.Thread

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
        self._check_ollama_connection()

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
        """Return history augmented with the latest runtime state banner."""
        if not self.conversation_history:
            return []
        # If we have no settings, just return the stored history directly
        if not self.settings:
            return list(self.conversation_history)

        # Get current system prompt
        system_prompt = self.settings.get_system_prompt(self._prompt_runtime_state())
        system_msg = {"role": "system", "content": system_prompt}

        # Get state banner
        banner = self.settings.get_system_state_banner(self._prompt_runtime_state())
        state_msg = {"role": "system", "content": banner}

        # Filter out any existing system messages from history
        non_system_history = [msg for msg in self.conversation_history if msg["role"] != "system"]

        if not non_system_history:
            # Should not happen, but handle gracefully
            return [system_msg, state_msg]

        # Insert the runtime state just before the most recent user turn
        history_prefix = non_system_history[:-1]
        latest_user = non_system_history[-1]
        return [system_msg] + history_prefix + [state_msg, latest_user]

    def refresh_system_prompt(self, reason: Optional[str] = None) -> None:
        """Rebuild the system prompt when runtime configuration changes."""
        if not self.settings:
            return
        runtime_state = self._prompt_runtime_state()
        banner = self.settings.get_system_state_banner(runtime_state)
        self._log_system_state_event(banner, reason)
        if reason:
            self._obs("lite", f"System prompt updated ({reason})")

    def _cleanup_voice_mode(self):
        """Clean up voice mode state when switching away.
        Only stops TTS if the speaking toggle is off."""
        if self.state == RecordingState.LISTENING:
            self.audio_recorder.stop()
            self.state = RecordingState.IDLE
        speaking_enabled = getattr(self.display, 'toggles', {}).get('speaking', True)
        if self.is_speaking and not speaking_enabled:
            self.tts_engine.stop()
            self.is_speaking = False

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
            # Load Silero VAD model
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

    def _check_ollama_connection(self):
        """Verify Ollama is running and accessible"""
        print(f"🧠 Checking Ollama connection...")
        try:
            ollama.list()
            print(f"✓ Connected to Ollama (model: {config.OLLAMA_MODEL})")
        except Exception as e:
            print(f"❌ Error connecting to Ollama: {e}")
            print("Please ensure Ollama is running: 'ollama serve'")
            sys.exit(1)

    def _cleanup_terminal(self):
        """Reset terminal to normal state"""
        try:
            import termios
            if self.original_terminal_settings:
                termios.tcsetattr(self.terminal_fd, termios.TCSADRAIN, self.original_terminal_settings)
        except (ImportError, OSError, ValueError) as e:
            # termios not available or terminal state invalid
            pass

        # Reset scrolling region
        sys.stdout.write("\033[r")
        # Show cursor
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()

    def _save_conversation(self):
        """Wait for any in-flight memory extraction to finish before the app exits."""
        t = self._memory_thread
        if t and t.is_alive():
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
                # User stopped speaking - process the recording
                self.set_state(RecordingState.PROCESSING, "Auto-stopped", "green")
                threading.Thread(
                    target=self.process_audio_pipeline,
                    daemon=True
                ).start()
            elif reason == "timeout":
                self._obs("verbose", "Auto-stop (timeout)")
                # No speech detected - return to idle
                self.audio_recorder.stop()
                self.set_state(RecordingState.IDLE, "No speech detected", "red")
                time.sleep(1.5)  # Show error message briefly
                self.set_state(RecordingState.IDLE)  # Reset to ready status

    def _get_chat_input(self, prompt: str) -> Optional[str]:
        """Get input in chat mode with proper line editing (avoiding pynput interference)"""
        import termios
        import tty
        import select

        # Set flag to prevent pynput from double-handling keys
        self.taking_chat_input = True

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)

        try:
            # Set raw mode with echo disabled
            # We'll manually handle all output to avoid double-echoing
            new_settings = termios.tcgetattr(fd)
            new_settings[3] = new_settings[3] & ~termios.ECHO  # Disable ECHO in lflag
            termios.tcsetattr(fd, termios.TCSADRAIN, new_settings)
            tty.setraw(fd)

            # Ensure prompt is written at the bottom of the feed
            self.display.move_cursor_to_feed_bottom()

            # Show prompt
            sys.stdout.write(prompt)
            sys.stdout.flush()

            buffer = []

            while True:
                # Check if data is available (with timeout to allow mode changes)
                if not select.select([sys.stdin], [], [], 0.1)[0]:
                    # Check if mode changed while waiting
                    if self.mode != InteractionMode.CHAT:
                        return None
                    continue

                # Pause face animation only when actually reading input
                self.display.pause_face_updates = True
                
                char = sys.stdin.read(1)
                
                # Resume animation immediately after reading character
                self.display.pause_face_updates = False

                # Handle Enter (both \r and \n)
                if char in ('\r', '\n'):
                    # Clear the prompt line so the feed stays clean
                    sys.stdout.write('\r\033[2K')
                    sys.stdout.flush()
                    return ''.join(buffer)

                # Handle backspace/delete (0x7F or 0x08)
                elif char in ('\x7f', '\x08'):
                    if buffer:
                        buffer.pop()
                        # Move back, write space, move back again (erase character)
                        sys.stdout.write('\b \b')
                        sys.stdout.flush()

                # Handle Ctrl+C
                elif char == '\x03':
                    sys.stdout.write('^C\n')
                    sys.stdout.flush()
                    return None

                # Handle TAB (switch modes) - return special marker
                elif char == '\t':
                    # Clear prompt before switching modes
                    sys.stdout.write('\r\033[2K')
                    sys.stdout.flush()
                    return '__TAB__'  # Special marker to switch modes

                # Handle printable characters
                elif ord(char) >= 32 and ord(char) < 127:
                    buffer.append(char)
                    sys.stdout.write(char)
                    sys.stdout.flush()

                # Ignore other control characters

        finally:
            # Always restore terminal settings
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

            # Fully restore display state
            if self.display.face_visible:
                # Restore scrolling region
                sys.stdout.write(f"\033[{self.display.face_lines + 1};r")
                sys.stdout.flush()

            # Resume face animation
            self.display.pause_face_updates = False

            # Clear flag
            self.taking_chat_input = False

    def set_state(self, new_state: RecordingState, status: str = "", status_style: str = "green"):
        """Update the assistant's state, face, and status message.

        Args:
            new_state: The new recording state
            status: Status message to display (if empty, uses mode-specific ready status)
            status_style: Style for the status message
        """
        with self.state_lock:
            self.state = new_state
        self.display.update_face_state(self.state, self.is_speaking)

        # Use mode-specific ready status if no status provided
        if not status and new_state == RecordingState.IDLE:
            status, status_style = self._get_mode_ready_status()

        if status:
            self.display.show_status_centered(status, status_style)

    def _chat_input_loop(self):
        """Loop for handling chat input in chat mode"""
        # Start on a new line
        self.display.move_cursor_to_feed_bottom()
        print()

        # Status already set by toggle_mode, just ensure state is correct
        self.set_state(RecordingState.IDLE)

        while self.mode == InteractionMode.CHAT:
            try:
                # Check if mode changed (user pressed TAB)
                if self.mode != InteractionMode.CHAT:
                    break

                # Get user input - delegate to display if it supports GUI input
                if hasattr(self.display, 'get_chat_input') and not isinstance(self.display, Display):
                    user_input = self.display.get_chat_input("💬 You: ")
                else:
                    user_input = self._get_chat_input("💬 You: ")

                # Handle special commands
                if user_input == '__TAB__':
                    # Switch modes (now that we're out of raw mode)
                    self.toggle_mode()
                    break

                if user_input is None:
                    # Interrupted (Ctrl+C) - exit chat mode gracefully
                    print("\n💬 Chat mode cancelled")
                    break

                if self.mode == InteractionMode.CHAT:  # Check mode again
                    # Check if user wants to exit (empty input after previous message)
                    if not user_input.strip():
                        continue
                    self.handle_chat_input(user_input)
                    # Status already restored by handle_chat_input's finally block

            except (EOFError, KeyboardInterrupt):
                # User pressed Ctrl+C or Ctrl+D
                break

    def toggle_mode(self):
        """Toggle between voice and chat mode"""
        with self.mode_lock:
            self.display.stop_face_display(clear_screen=False)

            if self.mode == InteractionMode.VOICE:
                # Switch to CHAT mode
                self._cleanup_voice_mode()
                self.mode = InteractionMode.CHAT
                self.refresh_system_prompt(reason="mode→chat")
                self.display.show_menu_bar(self.mode, self.settings.get("bot_name", "Zeina") if self.settings else "Zeina")
                self.set_state(RecordingState.IDLE)
                self.display.start_face_display(clear_screen=False)
                time.sleep(0.2)
                self.chat_input_thread = threading.Thread(target=self._chat_input_loop, daemon=True)
                self.chat_input_thread.start()
            else:
                # Switch to VOICE mode
                self._cleanup_chat_mode()
                self.mode = InteractionMode.VOICE
                self.refresh_system_prompt(reason="mode→voice")
                self.display.show_menu_bar(self.mode, self.settings.get("bot_name", "Zeina") if self.settings else "Zeina")
                self.set_state(RecordingState.IDLE)
                self.display.start_face_display(clear_screen=False)
                time.sleep(0.2)
                # Note: The chat input thread will exit when it detects mode change

    def _get_key(self):
        """Get a single keypress (raw mode)"""
        import sys
        import tty
        import termios

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.read(1)

            # Handle Ctrl+C
            if ch == '\x03':
                return '\x03'

            if ch == '\x1b':
                return 'ESC'

            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    def change_model(self):
        """Show model selection UI with arrow key navigation"""
        # Small delay to let the 'M' keypress finish processing
        time.sleep(0.1)

        was_chat_mode = self.mode == InteractionMode.CHAT
        if was_chat_mode:
            # Temporarily exit chat mode to avoid stdin contention
            self.mode = InteractionMode.VOICE
            self.refresh_system_prompt(reason="model-select exit chat")
            if self.chat_input_thread and self.chat_input_thread.is_alive():
                self.chat_input_thread.join(timeout=0.5)

        # Stop face animation to avoid interfering with model selection UI
        self.display.stop_face_display()

        # Clear screen for model selection
        print("\033[2J\033[H")

        try:
            # Flush any pending input
            import sys
            import termios
            try:
                termios.tcflush(sys.stdin, termios.TCIOFLUSH)
            except (ImportError, OSError, AttributeError) as e:
                # termios not available or not a TTY
                pass

            # Get list of models from Ollama
            models_response = ollama.list()
            models = models_response.models

            if not models:
                print("❌ No models found. Please pull a model first:")
                print("   ollama pull llama3.1:8b\n")
                return

            # Find current model index
            current_index = next((i for i, m in enumerate(models) if m.model == config.OLLAMA_MODEL), 0)
            selected = current_index

            # Display models (full redraw to avoid terminal corruption)
            def display_models():
                # Clear screen and redraw everything from the top
                print("\033[2J\033[H", end="")
                print("\n" + "=" * 80)
                print("📋 Available Ollama Models:\n")
                for i, model in enumerate(models):
                    model_name = model.model
                    current_marker = " ← current" if model_name == config.OLLAMA_MODEL else ""
                    selected_marker = "→ " if i == selected else "  "
                    print(f"{selected_marker}{i + 1}. {model_name}{current_marker}")
                print("\n  [1-9 to select, ENTER to confirm, ESC to cancel]")

            display_models()

            # Handle input
            while True:
                try:
                    key = self._get_key()

                    if key == '\r' or key == '\n':  # Enter
                        break

                    elif key == 'ESC' or key == '\x03':  # ESC or Ctrl+C
                        print("\n\n❌ Model selection cancelled\n")
                        return

                    elif key.isdigit() and 1 <= int(key) <= min(9, len(models)):
                        selected = int(key) - 1
                        break

                    # All other keys are ignored (suppressed)
                except KeyboardInterrupt:
                    print("\n\n❌ Model selection cancelled\n")
                    return

            # Apply selection
            new_model = models[selected].model
            if new_model != config.OLLAMA_MODEL:
                config.OLLAMA_MODEL = new_model
                print(f"\n\n⏳ Loading model: {new_model}...")

                # Test the model to trigger loading
                try:
                    # Make a simple test call to load the model
                    test_response = ollama.chat(
                        model=config.OLLAMA_MODEL,
                        messages=[{"role": "user", "content": "hi"}],
                        options={"num_predict": 1}  # Just generate 1 token to test
                    )
                    print(f"✓ Model loaded: {new_model}\n")
                except Exception as e:
                    print(f"⚠️  Model changed but loading test failed: {e}")
                    print(f"   The model will load on first use\n")
            else:
                print(f"\n\n✓ Keeping current model: {new_model}\n")

        except Exception as e:
            print(f"\n❌ Error listing models: {e}\n")
        finally:
            # Update menu bar with new model
            self.display.show_menu_bar(self.mode, self.settings.get("bot_name", "Zeina") if self.settings else "Zeina")
            # Restart face animation and UI
            self.display.start_face_display()
            # Show appropriate prompt based on mode
            time.sleep(0.1)  # Let face render
            if was_chat_mode:
                self.mode = InteractionMode.CHAT
                self.refresh_system_prompt(reason="model-select resume chat")
                self.display.show_menu_bar(self.mode, self.settings.get("bot_name", "Zeina") if self.settings else "Zeina")
                self.set_state(RecordingState.IDLE)
                print("─" * 80)
                self.chat_input_thread = threading.Thread(target=self._chat_input_loop, daemon=True)
                self.chat_input_thread.start()
            elif self.mode == InteractionMode.CHAT:
                print("─" * 80)

    def handle_chat_input(self, user_message: str):
        """Handle text chat input"""
        if not user_message.strip():
            return
        try:
            self._obs("lite", f"User: {user_message}")
            # Show what user said in a panel
            self.display.show_user_message(user_message)

            # Show processing status in chat mode
            self.set_state(RecordingState.PROCESSING, self.PROCESSING_STATUS, "magenta")

            # Get LLM response (display is handled inside _get_llm_response)
            assistant_response = self._get_llm_response(user_message, show_detail=False)

            # Speak if the speaking toggle is on (defaults to False in chat;
            # terminal Display has no toggles so this block is skipped)
            speaking_enabled = getattr(self.display, 'toggles', {}).get('speaking', False)
            if speaking_enabled:
                self.display.show_status_centered(self.CHAT_SPEAKING_STATUS, "blue")
                self.is_speaking = True
                self.display.update_face_state(self.state, self.is_speaking)
                self._obs("lite", f"Speaking: {assistant_response}")
                self.tts_engine.speak(assistant_response)
                self.is_speaking = False
                self.display.update_face_state(self.state, self.is_speaking)
        finally:
            self.set_state(RecordingState.IDLE)
            time.sleep(0.3)

    def start_listening(self, mode: str = "manual"):
        """
        Start listening for user input

        Modes:
        - "manual": User pressed spacebar
        - "auto": Auto-listen after response
        - "interrupt": After interrupting TTS
        """
        if self.state == RecordingState.IDLE or self.state == RecordingState.LISTENING:
            # Ensure audio recorder is in clean state before starting
            self.audio_recorder.stop()
            self.audio_recorder.start()

            self._obs("verbose", f"Listening started ({mode})")
            self.state = RecordingState.LISTENING

            # Update face
            self.display.update_face_state(self.state, self.is_speaking)

            # Show status centered below face
            self.display.show_status_centered("Listening...", "green")

    def _save_audio_to_file(self, audio_data: np.ndarray, filename: str):
        """Save audio data to a WAV file"""
        sf.write(filename, audio_data, config.SAMPLE_RATE)

    def _transcribe_audio(self, audio_file: str) -> Optional[str]:
        """Transcribe audio file to text using Whisper"""
        result = self.whisper_model.transcribe(
            audio_file,
            language="en",
            fp16=False  # Use FP32 for CPU compatibility
        )

        transcription = result['text'].strip()
        return transcription if transcription else None

    def _classify_tool_intent(self, message: str) -> str:
        """Ask the LLM whether the message needs tools. Returns the tool name or 'none'.

        Uses a fast, focused classification call separate from the main conversation
        so the model never leaks tool reasoning into its response.

        If the previous turn already retrieved data via a tool, that context is
        included so the classifier can judge whether the user is following up on
        existing data (→ none) or genuinely requesting something new (→ tool).
        """
        # Quick keyword-based overrides for common cases
        message_lower = message.lower()
        

        # Force get_system_health for working directory queries
        if any(keyword in message_lower for keyword in [
            'working directory', 'current directory', 'what directory', 'current path', 'pwd',
            'where is the app', 'application location', 'source code location',
            'program directory', 'app directory', 'system health', 'where are you located',
        ]):
            return 'get_system_health'
        

        tool_names = list(tool_manager.tools.keys())
        tool_list = ", ".join(tool_names)

        prior_context = ""
        if self._last_turn_had_tool_call and self._last_tool_used:
            prior_context = (
                f"CONTEXT: The previous turn already retrieved data using '{self._last_tool_used}' "
                f"and that data is already in the conversation history. "
                f"Only pick a tool if the user is clearly asking for NEW or DIFFERENT information "
                f"not covered by the existing data. If this looks like a follow-up question "
                f"about the same topic, pick 'none'.\n\n"
            )

        classifier_model = getattr(config, 'INTENT_CLASSIFIER_MODEL', config.OLLAMA_MODEL)
        response = ollama.chat(
            model=classifier_model,
            messages=[{
                "role": "user",
                "content": (
                    f"{prior_context}"
                    f"You are a router. Given the user message below, decide which tool "
                    f"is needed. User may refer to the computer as you/we/our. Available tools: {tool_list}\n"
                    f"Rules:\n"
                    f"- web_search: ONLY if the user explicitly asks to search/look something up, "
                    f"or needs real-time data (live news, scores, prices). "
                    f"Do NOT pick this for general knowledge, greetings, opinions, feelings, "
                    f"personal questions, or conversation about prior messages. "
                    f"NEVER use this for weather — always use get_weather instead.\n"
                    f"- get_system_health: ONLY and ALWAYS when customer asks about computer or system STATE: "
                    f"disk space, storage, network/wifi status, battery, CPU/RAM usage, memory, operating system info, "
                    f"current working directory, system uptime, or application location on disk. "
                    f"  'where am I in the file system?', 'show me the current path'.\n"
                    f"- get_weather: ONLY if the user asks about EXTERNAL weather conditions, temperature, or "
                    f"forecast for a specific location OUTSIDE (like city weather). Do NOT use for computer/system temperature.\n"
                    f"- get_current_time: ONLY if the user asks for the current time or date. (Priority over shell commands)\n"
                    f"- calculate: ONLY if the user is asking you the answer to a math problem. Do NOT use for questions about the computer.\n"
                    f"- get_location: ONLY if the user asks where they are or about their geographic locatoin, where they are in the WORLD/CITY. "
                    f"Keywords: 'where am I', 'what city am I in', 'where am I located'. "
                    f"Do NOT use for computer working directory or file locations.\n"
                    f"- read_file: ONLY to read the actual text or code INSIDE a specific file. "
                    f" Do NOT use this for checking disk space or storage capacity.\n"
                    f"- list_directory: ONLY to see a list of file names in a folder. "
                    f"Do NOT use this for checking hardware storage or disk space.\n"
                    f"- remember: ONLY when the user explicitly asks you to remember, save, or not forget "
                    f"a specific fact about themselves. Keywords: 'remember that', 'don't forget', 'keep in mind'.\n"
                    f"- execute_shell: ONLY when the user asks you to run a command, open an application, "
                    f"execute a script, or perform a system action. "
                    f"Keywords: 'open', 'run', 'launch', 'execute', 'start', 'kill', 'close the app'. "
                    f"Do NOT use for asking about the system state (use get_system_health for that).\n"
                    f"- query_knowledge_base: ONLY when the user explicitly asks to search or look up "
                    f"something in their saved files/documents/notes on disk. "
                    f"Keywords: 'my notes', 'what does my document say', 'in my files', 'look in my knowledge base'. "
                    f"Do NOT use when the user is sharing personal info ('I am X', 'did you know I am X'), "
                    f"asking general questions, or having a normal conversation.\n"
                    f"- read_clipboard: ONLY when the user asks to read, show, or check what is in their clipboard. "
                    f"Keywords: 'what's in my clipboard', 'read my clipboard', 'what did I copy', 'show clipboard'.\n"
                    f"- write_clipboard: ONLY when the user asks to copy specific text to their clipboard. "
                    f"Keywords: 'copy to clipboard', 'put X in my clipboard', 'copy that', 'save to clipboard'.\n"
                    f"- none: For everything else. When in doubt, pick none.\n\n"
                    f"User message: \"{message}\"\n\n"
                    f"Reply with ONLY the tool name or \"none\". Nothing else."
                )
            }],
            options={"temperature": 0}
        )
        result = response['message'].get('content', 'none').strip().lower().replace('.', '').replace('"', '')
        self._obs("lite", f"Intent [{classifier_model}]: {result}")
        # Validate the result is a known tool or none
        if result not in tool_names:
            return "none"
        return result

    def _build_tool_args(self, tool_name: str, user_message: str) -> dict:
        """Extract the right arguments for a tool from the user's message."""
        if tool_name == "web_search":
            return {"query": user_message}
        elif tool_name == "get_current_time":
            return {}
        elif tool_name == "calculate":
            return {"expression": user_message}
        elif tool_name == "get_weather":
            return {"location": self._extract_location(user_message)}
        elif tool_name == "get_location":
            return {}
        elif tool_name == "read_file":
            return {"path": self._extract_path(user_message)}
        elif tool_name == "list_directory":
            return {"path": self._extract_path(user_message)}
        elif tool_name == "get_system_health":
            return {}
        elif tool_name == "remember":
            return {"fact": self._extract_fact(user_message)}
        elif tool_name == "execute_shell":
            return {"command": self._extract_shell_command(user_message)}
        elif tool_name == "query_knowledge_base":
            return {"query": user_message}
        elif tool_name == "read_clipboard":
            return {}
        elif tool_name == "write_clipboard":
            return {"content": self._extract_clipboard_content(user_message)}
        return {}

    def _extract_clipboard_content(self, message: str) -> str:
        """Use the classifier LLM to extract what the user wants written to the clipboard."""
        classifier_model = getattr(config, 'INTENT_CLASSIFIER_MODEL', config.OLLAMA_MODEL)
        response = ollama.chat(
            model=classifier_model,
            messages=[{
                "role": "user",
                "content": (
                    f"Extract exactly what the user wants copied to their clipboard.\n"
                    f"Return ONLY the text to copy, with no explanation or extra words.\n"
                    f"Examples:\n"
                    f"  'copy hello world to my clipboard' → 'hello world'\n"
                    f"  'put my email address in the clipboard: test@example.com' → 'test@example.com'\n\n"
                    f"User message: \"{message}\""
                )
            }],
            options={"temperature": 0}
        )
        content = response['message'].get('content', '').strip()
        self._obs("verbose", f"Clipboard content: {content}")
        return content if content else message

    def _extract_shell_command(self, message: str) -> str:
        """Use the classifier LLM to extract a shell command from a natural language request."""
        classifier_model = getattr(config, 'INTENT_CLASSIFIER_MODEL', config.OLLAMA_MODEL)
        response = ollama.chat(
            model=classifier_model,
            messages=[{
                "role": "user",
                "content": (
                    f"Extract the shell command the user wants to run from this message. "
                    f"Reply with ONLY the shell command, nothing else. "
                    f"Use macOS/Linux syntax. For opening apps use 'open -a AppName'. "
                    f"If the request is ambiguous, produce the most likely shell command.\n\n"
                    f"Message: \"{message}\""
                )
            }],
            options={"temperature": 0}
        )
        command = response['message'].get('content', '').strip()
        self._obs("verbose", f"Shell command: {command}")
        return command

    def _extract_fact(self, message: str) -> str:
        """Extract the fact the user wants remembered from their message."""
        classifier_model = getattr(config, 'INTENT_CLASSIFIER_MODEL', config.OLLAMA_MODEL)
        response = ollama.chat(
            model=classifier_model,
            messages=[{
                "role": "user",
                "content": (
                    f"Extract the specific fact the user wants to be remembered from this message. "
                    f"Rephrase it as a short, clear statement starting with a verb or noun — "
                    f"NO subject pronoun (not 'she', 'he', 'they', 'the user', 'I'). "
                    f"Examples: 'prefers dark mode', 'has a dog named Max'. "
                    f"Reply with ONLY the fact, nothing else.\n\n"
                    f"Message: \"{message}\""
                )
            }],
            options={"temperature": 0}
        )
        fact = response['message'].get('content', message).strip()
        self._obs("verbose", f"Extracted fact: {fact}")
        return fact if fact else message

    def _extract_path(self, message: str) -> str:
        """Use the classifier LLM to extract a file or directory path from a natural language request."""
        classifier_model = getattr(config, 'INTENT_CLASSIFIER_MODEL', config.OLLAMA_MODEL)
        response = ollama.chat(
            model=classifier_model,
            messages=[{
                "role": "user",
                "content": (
                    f"Extract the file or directory path from this message. "
                    f"Use standard macOS/Linux path conventions (e.g. '~/Documents', '~/.zshrc'). "
                    f"Reply with ONLY the path, nothing else. "
                    f"If no specific file or folder is mentioned, reply with '~'.\n\n"
                    f"Message: \"{message}\""
                )
            }],
            options={"temperature": 0}
        )
        path = response['message'].get('content', '~').strip() or '~'
        self._obs("verbose", f"Path: {path}")
        return path

    def _extract_location(self, message: str) -> str:
        """Extract a location name from a user message for weather queries.
        Uses a fast LLM call to reliably pull out the city/location."""
        classifier_model = getattr(config, 'INTENT_CLASSIFIER_MODEL', config.OLLAMA_MODEL)
        response = ollama.chat(
            model=classifier_model,
            messages=[{
                "role": "user",
                "content": (
                    f"Extract the city or location name from this message. "
                    f"Reply with ONLY the location name, nothing else.\n\n"
                    f"Message: \"{message}\""
                )
            }],
            options={"temperature": 0}
        )
        location = response['message'].get('content', message).strip()
        self._obs("verbose", f"Location: {location}")
        return location if location else message

    def _maybe_summarize_history(self) -> None:
        """Summarize old conversation turns when history grows too long.

        When the history exceeds MAX_CONVERSATION_LENGTH + a small buffer, the
        oldest turns (excluding the system prompt and the most recent half) are
        collapsed into a single summary message using the fast classifier model.
        Falls back to simple truncation if the summarization call fails.
        """
        if config.MAX_CONVERSATION_LENGTH <= 0:
            return
        # Add a buffer of 4 before triggering so we don't summarize on every turn
        if len(self.conversation_history) <= config.MAX_CONVERSATION_LENGTH + 4:
            return

        keep_recent = max(config.MAX_CONVERSATION_LENGTH // 2, 4)
        # conversation_history[0] is always the system prompt
        to_summarize = self.conversation_history[1:-keep_recent]
        recent = self.conversation_history[-keep_recent:]

        if not to_summarize:
            return

        text = "\n".join(
            f"{m['role'].upper()}: {m['content'][:300]}"
            for m in to_summarize
        )
        try:
            classifier_model = getattr(config, 'INTENT_CLASSIFIER_MODEL', config.OLLAMA_MODEL)
            resp = ollama.chat(
                model=classifier_model,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Summarize this conversation in 2-3 sentences, preserving key facts, "
                        f"names, and any decisions made:\n\n{text}"
                    )
                }],
                options={"temperature": 0},
            )
            summary = resp['message'].get('content', '').strip()
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

        # Fallback: plain truncation
        self.conversation_history = [self.conversation_history[0]] + \
            self.conversation_history[-(config.MAX_CONVERSATION_LENGTH):]

    def _get_llm_response(self, user_message: str, show_detail: bool = True,
                          voice_streaming: bool = False) -> str:
        """Get response from Ollama LLM with conversation history and tool calling support"""
        # State is already set by caller (voice or chat mode)

        # Add user message to conversation history
        self.conversation_history.append({
            "role": "user",
            "content": user_message
        })

        # Debug: print recent conversation history (for troubleshooting)
        # Set DEBUG_CONVERSATION = True in config.py to enable
        if hasattr(config, 'DEBUG_CONVERSATION') and config.DEBUG_CONVERSATION:
            print("\n🔍 Debug - Recent Conversation (last 5 messages):")
            recent_msgs = self.conversation_history[-5:] if len(self.conversation_history) > 5 else self.conversation_history
            for i, msg in enumerate(recent_msgs):
                role = msg.get('role', 'unknown')
                content = msg.get('content', '')
                has_tools = 'tool_calls' in msg
                tool_info = " [+tool_calls]" if has_tools else ""
                if len(content) > 80:
                    content = content[:80] + "..."
                print(f"  {role}{tool_info}: {content}")
            print()

        # Summarize or trim conversation history if it exceeds max length
        self._maybe_summarize_history()

        # Step 1: Classify whether a tool is needed
        tool_needed = "none"
        if tool_manager.has_tools():
            tool_needed = self._classify_tool_intent(user_message)

        # Step 2: If a tool is needed, execute it and inject the result into context
        if tool_needed != "none":
            self.display.move_cursor_to_feed_bottom()
            self.display.show_info(f"Using tool: {tool_needed}")

            # Build tool arguments from the user message
            tool_args = self._build_tool_args(tool_needed, user_message)

            tool_result = tool_manager.execute_tool(tool_needed, tool_args)
            # verbose shows the full result; lite just confirms it ran
            self._obs("lite", f"Tool: {tool_needed} → {len(tool_result)} chars")
            self._obs("verbose", f"Tool result:\n{tool_result}")

            # Inject tool result as a follow-up user message so the LLM
            # treats it as context it must respond to directly.
            # Repeat the original question explicitly so the LLM doesn't lose
            # track of it when the tool result is long (e.g. ps aux output).
            injection_content = (
                f"Data from {tool_needed}:\n{tool_result}\n\n"
                f"Using the data above, answer this question naturally without mentioning any data source or tool usage: {user_message}"
            )
            
            self.conversation_history.append({
                "role": "user",
                "content": injection_content
            })
            self._last_turn_had_tool_call = True
            self._last_tool_used = tool_needed
        else:
            self._last_turn_had_tool_call = False

        # Step 3: Get the final response (never pass tools schema to avoid leaking)
        msg_count = len(self.conversation_history)
        self._obs("lite", f"LLM [{config.OLLAMA_MODEL}] ({msg_count} msgs)")
        can_stream = getattr(self.display, 'has_streaming', False)

        def _do_llm_call(messages: list[dict], start_bubble: bool = False) -> tuple:
            """Run one ollama call, streaming tokens to the display if supported.
            Returns (content_str, elapsed_seconds)."""
            t0 = time.monotonic()
            if can_stream:
                if start_bubble:
                    self.display.begin_stream()
                accumulated = ""
                for chunk in ollama.chat(
                    model=config.OLLAMA_MODEL,
                    messages=messages,
                    stream=True,
                ):
                    token = chunk['message'].get('content', '')
                    if token:
                        accumulated += token
                        self.display.stream_token(token)
                return accumulated.strip(), time.monotonic() - t0
            else:
                response = ollama.chat(
                    model=config.OLLAMA_MODEL,
                    messages=messages,
                )
                return response['message'].get('content', '').strip(), time.monotonic() - t0

        messages_for_call = self._build_llm_messages()
        if not messages_for_call:
            messages_for_call = list(self.conversation_history)

        if voice_streaming and hasattr(self, 'tts_engine') and self.tts_engine:
            # Voice mode: stream tokens to display + speak each sentence as it arrives
            t0 = time.monotonic()
            content = self._stream_and_speak(messages_for_call)
            elapsed = time.monotonic() - t0
        else:
            content, elapsed = _do_llm_call(messages_for_call, start_bubble=True)

            # Guard against empty responses - retry once without tool context
            if not content and tool_needed != "none":
                self._obs("lite", "Empty response after tool — retrying without tool context")
                self.conversation_history = [
                    m for m in self.conversation_history
                    if not (m.get('role') == 'user'
                            and '[DATA]' in m.get('content', ''))
                ]
                messages_for_call = self._build_llm_messages()
                if not messages_for_call:
                    messages_for_call = list(self.conversation_history)
                content, elapsed = _do_llm_call(messages_for_call, start_bubble=False)

        if not content:
            content = "Sorry, I didn't quite get that. Could you try again?"
            if can_stream:
                self.display.stream_token(content)

        # Non-streaming path: add the bubble now that we have the full response.
        if not can_stream:
            self.display.show_assistant_message(content)

        # Store only role+content — the ollama.Message object (or its model_dump() output)
        # may carry non-JSON-serializable fields like tool_calls/images. We already
        # have the clean string in `content`, so there's no need to keep anything else.
        self.conversation_history.append({"role": "assistant", "content": content})
        self._obs("lite", f"Response: {len(content)} chars in {elapsed:.1f}s")

        # Persist exchange to session file (incremental; survives crashes)
        if self.settings and self._session_path and config.SAVE_CONVERSATION_HISTORY:
            self.settings.append_to_session(self._session_path, user_message, content)

        # Extract user memories asynchronously (never blocks the response pipeline).
        # daemon=False so the thread survives app shutdown long enough to write;
        # _save_conversation joins it with a timeout as a safety net.
        if self.settings and self.settings.get("memory_enabled", True):
            t = threading.Thread(
                target=self._extract_memories,
                args=(user_message, content),
                daemon=False,
            )
            t.start()
            self._memory_thread = t

        return content

    def _extract_memories(self, user_message: str, assistant_response: str) -> None:
        """Background task: extract memorable personal facts from what the USER said."""
        _ = assistant_response  # kept for signature compatibility
        # Skip messages with no first-person markers — a pure question or command
        # with no "I/my/I'm/I've" cannot contain a self-disclosure.
        msg_lower = user_message.lower()
        _first_person = (" i ", " i'm ", " i've ", " i'd ", " i'll ", " my ", " mine ", " myself ")
        if not any(tok in f" {msg_lower} " for tok in _first_person):
            return

        try:
            profile = self.settings.active_profile_name
            self._obs("lite", f"Memory extraction [{config.OLLAMA_MODEL}]")
            existing = self.settings.load_memories(profile)
            existing_block = ""
            if existing:
                existing_block = (
                    "Already known facts:\n"
                    + "\n".join(f"- {f}" for f in existing)
                    + "\n\n"
                )

            response = ollama.chat(
                model=config.OLLAMA_MODEL,
                messages=[{
                    "role": "user",
                    "content": (
                        "Decide whether the user's message contains a durable self-disclosure, "
                        "then extract it.\n\n"
                        "STEP 1 — Guard. Did the user make a direct statement about themselves — "
                        "their preferences, life, identity, plans, or habits? "
                        "If the message is a question, a request, a task, or a command, return []. "
                        "If the content is about someone or something else rather than the user, return [].\n\n"
                        "STEP 2 — Extract (only if STEP 1 passed). Pull out durable facts:\n"
                        "  • Preferences & tastes (food, music, hobbies, activities)\n"
                        "  • Personal details (name, relationships, family, location)\n"
                        "  • Plans & intentions (trips, goals, purchases)\n"
                        "  • Routines, habits, lifestyle\n"
                        "  • Work & education (role, company, skills)\n"
                        "  • Beliefs, values, identity\n\n"
                        "Rules:\n"
                        "- Only extract what the user explicitly stated. No stereotypes or inferences.\n"
                        "- Rephrase in third person, dropping 'I': store 'likes cheese', not 'I like cheese'.\n"
                        "- Skip style inferences about how they communicate — extract content, not tone.\n"
                        "- Skip one-off requests, fleeting tasks, and facts about other people.\n"
                        "- Skip already-known facts listed below.\n\n"
                        f"{existing_block}"
                        f"USER MESSAGE: {user_message}\n\n"
                        "Respond with ONLY a JSON array of strings. Return [] if nothing qualifies."
                    )
                }],
                options={"temperature": 0},
            )
            raw = response['message'].get('content', '[]').strip()
            self._obs("verbose", f"Memory extraction raw: {raw[:120]}")
            start = raw.find('[')
            end = raw.rfind(']')
            if start == -1 or end == -1:
                self._obs("lite", "Memory extraction: no JSON array in response")
                return
            records = json.loads(raw[start:end + 1])
            if isinstance(records, list):
                clean_facts = []
                for entry in records:
                    if isinstance(entry, str) and entry.strip():
                        clean_facts.append(entry.strip())
                if clean_facts:
                    self.settings.append_memories(profile, clean_facts)
                    self._obs("lite", f"Memories stored: {clean_facts}")
                    # Flash a brief notification in the status bar
                    preview = clean_facts[0]
                    if len(preview) > 42:
                        preview = preview[:42] + "..."
                    suffix = f" (+{len(clean_facts) - 1} more)" if len(clean_facts) > 1 else ""
                    self.display.show_log(f"Memory saved: {preview}{suffix}")
        except Exception as e:
            self._obs("lite", f"Memory extraction error: {e}")


    # Regex that matches a sentence boundary: end of sentence punctuation followed by
    # whitespace (or newline), or a standalone newline paragraph break.
    _SENTENCE_END_RE = re.compile(r'(?<=[.!?])\s+|(?<=\n)\s*(?=\S)')

    def _stream_and_speak(self, messages: list) -> str:
        """Stream an LLM response and speak each sentence as it arrives.

        Architecture:
          - Main thread: streams tokens from Ollama, buffers until a sentence
            boundary is detected, then puts the sentence onto sentence_q.
          - Synthesis thread (daemon): picks sentences from sentence_q, calls
            tts_engine.synthesize_to_file(), puts the WAV path onto play_q.
          - Back in main thread (after streaming ends): drains play_q and calls
            tts_engine.play_file() for each WAV, giving sentence-level latency.

        The synthesis thread runs concurrently with streaming so that the next
        sentence's audio is ready (or nearly ready) when the current one finishes.
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
            stream = ollama.chat(
                model=config.OLLAMA_MODEL,
                messages=messages,
                stream=True,
            )
            for chunk in stream:
                token = chunk['message'].get('content', '')
                if not token:
                    continue
                buf += token
                full_response.append(token)
                if can_stream:
                    self.display.stream_token(token)

                # Split on sentence boundary; only flush if the sentence is long
                # enough to avoid fragmenting "e.g." or "Mr." abbreviations.
                parts = self._SENTENCE_END_RE.split(buf, maxsplit=1)
                if len(parts) > 1 and len(parts[0].strip()) >= 8:
                    sentence_q.put(parts[0].strip())
                    buf = parts[1] if len(parts) > 1 else ""
        except Exception as e:
            self._obs("lite", f"Streaming LLM error: {e}")

        # Flush remaining buffer
        if buf.strip():
            sentence_q.put(buf.strip())

        # Signal synthesis thread to stop
        sentence_q.put(None)
        synth_thread.join(timeout=60)

        # Audio is about to start — only NOW set is_speaking so PTT correctly
        # triggers an interrupt during playback rather than during LLM computation.
        self.is_speaking = True
        self.display.update_face_state(self.state, self.is_speaking)

        # Drain the play queue
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

    def _check_interrupted(self) -> bool:
        """Return True if the user has pressed spacebar to interrupt (is_speaking was cleared)."""
        # The TTS engine's stop() sets is_speaking=False on the engine; the pipeline
        # thread's self.is_speaking flag is used as the interrupt signal.
        return not self.is_speaking

    def process_audio_pipeline(self):
        """
        Process the complete audio pipeline:
        1. Get audio data from recorder
        2. Transcribe to text
        3. Get LLM response
        4. Speak response
        5. Auto-listen for follow-up
        """
        temp_audio_file = None
        try:
            # Get recorded audio
            audio_data = self.audio_recorder.stop()
            if audio_data is None or len(audio_data) == 0:
                self.set_state(RecordingState.IDLE, "No audio recorded", "red")
                time.sleep(1.5)  # Show error message briefly
                self.set_state(RecordingState.IDLE)  # Reset to ready status
                return

            # Save to temporary file
            temp_audio_file = os.path.join(config.TMP_DIR, "temp_recording.wav")
            self._save_audio_to_file(audio_data, temp_audio_file)

            # Transcribe
            transcription = self._transcribe_audio(temp_audio_file)
            if not transcription:
                self.set_state(RecordingState.IDLE)
                return

            self._obs("lite", f"User: {transcription}")

            # Show what user said
            self.display.show_user_message(transcription)

            # Show processing status in voice mode
            self.set_state(RecordingState.PROCESSING, self.PROCESSING_STATUS, "magenta")

            # Get LLM response, speaking each sentence as it arrives (streaming TTS)
            speaking_enabled = getattr(self.display, 'toggles', {}).get('speaking', True)
            if speaking_enabled and hasattr(self, 'tts_engine') and self.tts_engine:
                self.display.show_status_centered(self.SPEAKING_STATUS, "blue")
                assistant_response = self._get_llm_response(transcription, voice_streaming=True)
                self.is_speaking = False
                self.display.update_face_state(self.state, self.is_speaking)
            else:
                assistant_response = self._get_llm_response(transcription)

            # Reset state after response (do not override active listening)
            # Check state without holding lock to avoid deadlock with set_state
            if self.state != RecordingState.LISTENING and not self.audio_recorder.is_recording:
                self.set_state(RecordingState.IDLE)

            # Auto-listen for follow-up question (only in voice mode)
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

    def _handle_key_press(self, key):
        """Handle keyboard press events"""
        try:
            # Handle Ctrl+C to quit (works in both modes)
            if key == keyboard.KeyCode.from_char('\x03'):  # Ctrl+C
                self._save_conversation()
                print("\n\n👋 Goodbye!")
                return False

            if self.ctrl_pressed and hasattr(key, 'char') and key.char and key.char.lower() == 'c':
                self._save_conversation()
                print("\n\n👋 Goodbye!")
                return False

            # Track Ctrl key
            if key == keyboard.Key.ctrl_l or key == keyboard.Key.ctrl_r:
                self.ctrl_pressed = True
                return

            # Handle ESC to quit (works in both modes)
            if key == keyboard.Key.esc:
                self._save_conversation()
                return False

            # Handle TAB to toggle mode (works in both modes)
            # But skip if we're actively taking chat input (to avoid double-toggle)
            if key == keyboard.Key.tab:
                if not self.taking_chat_input:
                    self.toggle_mode()
                return

            # Handle Ctrl+M to change model (works in both modes)
            if self.ctrl_pressed and hasattr(key, 'char') and key.char and key.char.lower() == 'm':
                self.change_model()
                return

            # In CHAT mode, ignore voice controls
            if self.mode == InteractionMode.CHAT:
                return

            # VOICE MODE ONLY BELOW THIS POINT

            # Check for activation key press
            is_activation_key = False

            if hasattr(key, 'char') and key.char == config.PUSH_TO_TALK_KEY:
                    is_activation_key = True
            elif key == keyboard.Key.space and config.PUSH_TO_TALK_KEY == "space":
                is_activation_key = True

            if is_activation_key:
                # Debounce: ignore if key was pressed too recently
                current_time = time.time()
                if current_time - self.last_key_press_time < self.key_debounce_delay:
                    return
                self.last_key_press_time = current_time

                # Interrupt TTS if speaking
                if self.is_speaking:
                    self.tts_engine.stop()
                    self.is_speaking = False
                    self.set_state(RecordingState.IDLE)
                    self.start_listening(mode="interrupt")

                # Start listening if idle
                elif self.state == RecordingState.IDLE:
                    self.start_listening(mode="manual")

                # Stop and process if currently listening
                elif self.state == RecordingState.LISTENING:
                    self.set_state(RecordingState.PROCESSING)
                    threading.Thread(
                        target=self.process_audio_pipeline,
                        daemon=True
                    ).start()

        except AttributeError:
            pass

    def _handle_key_release(self, key):
        """Handle keyboard release events"""
        # Track Ctrl key release
        if key == keyboard.Key.ctrl_l or key == keyboard.Key.ctrl_r:
            self.ctrl_pressed = False
            return

        # Stop on ESC
        if key == keyboard.Key.esc:
            return False

    def run(self):
        """Start the assistant and listen for input"""
        try:
            # Start audio input stream
            with sd.InputStream(
                samplerate=config.SAMPLE_RATE,
                channels=config.CHANNELS,
                callback=self.audio_recorder.audio_callback
            ):
                # Listen for keyboard events
                with keyboard.Listener(
                    on_press=self._handle_key_press,
                    on_release=self._handle_key_release,
                    suppress=False  # Don't suppress system keys
                ) as listener:
                    listener.join()
        except KeyboardInterrupt:
            print("\n\n👋 Interrupted! Shutting down...")
            self._save_conversation()
        finally:
            # Cleanup face display
            self.display.stop_face_display()
            # Restore terminal state
            self._cleanup_terminal()
            print("\n")
