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
from zeina.tools import tool_manager, set_memory_callback, set_ui_control_callback

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
        self._last_tools_used: list[str] = []

        # Cache for control_self args extracted during classification so
        # _plan_tool_calls doesn't repeat the work.
        self._pending_control_self_args: list[dict] | None = None

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
        runtime_state = self._prompt_runtime_state()
        system_prompt = self.settings.get_system_prompt(runtime_state)
        system_msg = {"role": "system", "content": system_prompt}

        # Get state banner
        banner = self.settings.get_system_state_banner(runtime_state)
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
            full_prompt = self.settings.get_system_prompt(runtime_state)
            self._obs("verbose", f"Updated system prompt ({len(full_prompt)} chars):\n{full_prompt}")

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

    def _check_control_self(self, message: str) -> bool:
        """Stage-1 binary classifier: is the user asking Zeina to change herself?

        Runs a short dedicated LLM call before the main classifier so that
        control_self never has to compete with execute_shell and similar tools
        in the same prompt.

        Fast-path: a few terms are unambiguously Zeina-internal and don't need
        LLM inference — skip straight to YES.
        """
        m = message.lower()
        # Fast-path: "setting"/"diagnostic"/"dashboard" almost always means
        # Zeina's own screens — unless the user qualifies it with an external
        # context (system settings, VS Code settings, etc.).
        _zeina_screens = ("setting", "diagnostic", "dashboard")
        _external = ("system", "computer", "mac", "windows", "phone", "iphone",
                     "browser", "chrome", "firefox", "safari", "brave", "vscode",
                     "vs code", "terminal", "finder", "iterm")
        if any(t in m for t in _zeina_screens) and not any(e in m for e in _external):
            return True

        classifier_model = getattr(config, 'INTENT_CLASSIFIER_MODEL', config.OLLAMA_MODEL)
        response = ollama.chat(
            model=classifier_model,
            messages=[{
                "role": "user",
                "content": (
                    f"You are classifying messages for Zeina, an AI assistant app.\n"
                    f"Zeina has built-in screens: a SETTINGS page and a DIAGNOSTICS dashboard.\n\n"
                    f"Answer YES if the message is a direct command to control Zeina's own interface.\n"
                    f"Answer NO for everything else.\n\n"
                    f"Examples:\n"
                    f"\"switch to midnight theme\" → YES\n"
                    f"\"change the theme to terminal\" → YES\n"
                    f"\"use ascii animation\" → YES\n"
                    f"\"hide the status bar\" → YES\n"
                    f"\"mute yourself\" → YES\n"
                    f"\"unmute your voice\" → YES\n"
                    f"\"clear the conversation history\" → YES\n"
                    f"\"clear your memories\" → YES\n"
                    f"\"change your name to Aria\" → YES\n"
                    f"\"switch to voice mode\" → YES\n"
                    f"\"switch to chat mode\" → YES\n"
                    f"\"open settings\" → YES\n"
                    f"\"open the settings page\" → YES\n"
                    f"\"show settings\" → YES\n"
                    f"\"pull up your settings\" → YES\n"
                    f"\"pull up your settings page\" → YES\n"
                    f"\"open your settings\" → YES\n"
                    f"\"open zeina's settings\" → YES\n"
                    f"\"open zeina's settings page\" → YES\n"
                    f"\"bring up the settings\" → YES\n"
                    f"\"open diagnostics\" → YES\n"
                    f"\"open the diagnostics dashboard\" → YES\n"
                    f"\"show me the diagnostics\" → YES\n"
                    f"\"pull up the diagnostics\" → YES\n"
                    f"\"open zeina's diagnostics\" → YES\n"
                    f"\"switch to work profile\" → YES\n"
                    f"\"switch profile to default\" → YES\n"
                    f"\"switch ur face style\" → YES\n"
                    f"\"change your face\" → YES\n"
                    f"\"hide the menu button\" → YES\n"
                    f"\"hide the three dot menu\" → YES\n"
                    f"\"show the dots menu button\" → YES\n"
                    f"\"open Safari\" → NO\n"
                    f"\"open brave's settings\" → NO\n"
                    f"\"open theverge.com\" → NO\n"
                    f"\"open Terminal\" → NO\n"
                    f"\"open my documents folder\" → NO\n"
                    f"\"what's the weather\" → NO\n"
                    f"\"search for flights\" → NO\n"
                    f"\"hi\" → NO\n"
                    f"\"thanks\" → NO\n"
                    f"\"what time is it\" → NO\n\n"
                    f"Message: \"{message}\"\n\nAnswer YES or NO:"
                )
            }],
            options={"temperature": 0}
        )
        result = response['message'].get('content', 'no').strip().upper()
        return result.startswith('Y')

    def _classify_tool_intent(self, message: str) -> list[str]:
        """Classify which tools are needed. Returns an ordered list of tool names
        (possibly empty = no tools; repeats allowed for multi-action tools).

        Three-stage approach:
          Stage 0 — Python extraction: _extract_ui_actions_multi collects ALL
                    control_self actions deterministically. Result is cached in
                    _pending_control_self_args so _plan_tool_calls reuses it.
          Stage 1 — LLM binary check for control_self: only runs if Stage 0
                    found nothing; catches natural-language phrasings Python misses.
          Stage 2 — multi-tool LLM classifier for all other tools (always runs).
                    Returns a comma-separated list so multiple tools can fire.
        """
        tools_needed: list[str] = []

        # Stage 0: Python-first — collect all control_self actions.
        if 'control_self' in tool_manager.tools:
            ui_actions = self._extract_ui_actions_multi(message)
            if ui_actions:
                self._pending_control_self_args = ui_actions
                # One slot per action so _plan_tool_calls can pop them in order.
                tools_needed.extend(['control_self'] * len(ui_actions))
                self._obs("lite", f"Intent: control_self ×{len(ui_actions)}")

        # Stage 1: LLM binary check — only when Python patterns found nothing.
        if not tools_needed and 'control_self' in tool_manager.tools:
            if self._check_control_self(message):
                self._pending_control_self_args = [{}]  # args extracted later
                tools_needed.append('control_self')
                self._obs("lite", "Intent: control_self")

        # Stage 2: multi-tool classifier — all tools except control_self.
        other_tool_names = [t for t in tool_manager.tools.keys() if t != 'control_self']
        tool_list = ", ".join(other_tool_names)

        prior_context = ""
        if self._last_turn_had_tool_call and self._last_tools_used:
            tools_str = ", ".join(f"'{t}'" for t in self._last_tools_used)
            prior_context = (
                f"CONTEXT: The previous turn already retrieved data using {tools_str} "
                f"and that data is already in the conversation history. "
                f"Only pick tools if the user is clearly asking for NEW or DIFFERENT information "
                f"not covered by the existing data. If this looks like a follow-up question "
                f"about the same topic, pick 'none'.\n\n"
            )

        # If control_self actions were already found, bias Stage 2 toward none
        # unless the message explicitly requests something else on top.
        cs_context = ""
        if tools_needed:
            cs_context = (
                f"NOTE: Zeina's own UI actions (theme, animation, visibility, etc.) have "
                f"already been identified for this message and are handled separately. "
                f"Only add tools here if the message ALSO explicitly requests a separate "
                f"operation such as opening an external app, searching the web, getting the "
                f"time, etc. If the whole message is about Zeina's own interface, reply 'none'.\n\n"
            )

        classifier_model = getattr(config, 'INTENT_CLASSIFIER_MODEL', config.OLLAMA_MODEL)
        response = ollama.chat(
            model=classifier_model,
            messages=[{
                "role": "user",
                "content": (
                    f"{prior_context}{cs_context}"
                    f"You are a router. Given the user message, list ALL tools needed "
                    f"as a comma-separated list, or 'none'. Available tools: {tool_list}\n\n"
                    f"If the user wants multiple things that need the same tool, repeat it "
                    f"(e.g. 'execute_shell, execute_shell' for two apps to open).\n\n"
                    f"Rules:\n"
                    f"- web_search: User asks to search/look something up online, or needs "
                    f"real-time data (live news, scores, prices, current events). "
                    f"NOT for greetings, opinions, or follow-up questions on known data. "
                    f"NEVER for weather (use get_weather).\n"
                    f"- get_weather: User asks about outdoor weather, temperature, or forecast "
                    f"for a city/location. NOT for computer temperature.\n"
                    f"- get_current_time: User asks for the current time or date.\n"
                    f"- calculate: User wants the answer to a math expression or calculation.\n"
                    f"- get_location: User asks where they are geographically "
                    f"('what city am I in', 'where am I'). NOT for file/directory location.\n"
                    f"- get_system_health: User asks about computer state: disk space, storage, "
                    f"battery, CPU/RAM usage, network status, operating system, uptime, "
                    f"current working directory, or where the app is located on disk.\n"
                    f"- read_file: User wants to read the contents of a specific file.\n"
                    f"- list_directory: User wants a list of files inside a folder.\n"
                    f"- remember: User explicitly asks to save/remember a fact about themselves "
                    f"('remember that', 'don't forget', 'keep in mind').\n"
                    f"- execute_shell: ONLY when the user gives a DIRECT, IMPERATIVE command to "
                    f"perform an OS action RIGHT NOW. The message must be a command, not a "
                    f"question, not hypothetical, not meta-discussion about capabilities. "
                    f"Trigger: imperative verb ('open', 'launch', 'run', 'start', 'kill', "
                    f"'close') + specific target app/URL/command. "
                    f"NOT for: 'I wonder if...', 'should I...', 'can you...', 'what if...', "
                    f"'give you the ability to...', discussions about what Zeina could do.\n"
                    f"- read_clipboard: User wants to read what is currently in the clipboard.\n"
                    f"- write_clipboard: User wants to copy specific text to the clipboard.\n"
                    f"- take_screenshot: User asks about something on their screen, wants you to "
                    f"look at / read / describe screen content "
                    f"('what do you see', 'look at this', 'what's on my screen').\n"
                    f"- none: Everything else. Use this for: greetings, casual chat, general "
                    f"knowledge questions, hypothetical/capability discussions ('I wonder if', "
                    f"'should I', 'can you', 'what if', 'what tools do you have'), "
                    f"meta-questions about what Zeina can do, follow-up on already-fetched data. "
                    f"When in doubt, pick none.\n\n"
                    f"User message: \"{message}\"\n\n"
                    f"Reply with ONLY a comma-separated list of tool names, or \"none\". "
                    f"Examples: \"execute_shell\" | \"execute_shell, execute_shell\" | \"web_search\" | \"none\""
                )
            }],
            options={"temperature": 0}
        )
        raw = response['message'].get('content', 'none').strip().lower()
        # Parse comma-separated list, cleaning each token
        stage2_tools = []
        for token in raw.split(','):
            t = token.strip().replace('.', '').replace('"', '').replace("'", '')
            if t and t != 'none' and t in other_tool_names:
                stage2_tools.append(t)
        if stage2_tools:
            self._obs("lite", f"Intent [{classifier_model}]: {', '.join(stage2_tools)}")
        else:
            self._obs("lite", f"Intent [{classifier_model}]: none")
        tools_needed.extend(stage2_tools)
        return tools_needed

    def _resolve_references(self, message: str) -> str:
        """Rewrite vague references ('that', 'it', 'the song', etc.) into
        concrete text using recent conversation history.  Returns the original
        message unchanged if there is nothing to resolve or no history."""
        # Quick check: only run if the message contains a likely vague reference
        _VAGUE = ("that", "it", "this", "those", "them", "the one", "the song",
                  "the file", "the app", "the thing", "what you said",
                  "what you mentioned", "the last one", "the previous")
        lower = message.lower()
        if not any(v in lower for v in _VAGUE):
            return message

        history = self.conversation_history
        if not history:
            return message

        recent = [m for m in history if m.get("role") in ("user", "assistant")][-6:]
        if not recent:
            return message

        lines = []
        for m in recent:
            role = "User" if m["role"] == "user" else "Assistant"
            lines.append(f"{role}: {m['content']}")
        context = "\n".join(lines)

        classifier_model = getattr(config, 'INTENT_CLASSIFIER_MODEL', config.OLLAMA_MODEL)
        response = ollama.chat(
            model=classifier_model,
            messages=[{
                "role": "user",
                "content": (
                    f"Recent conversation:\n{context}\n\n"
                    f"Rewrite the following message so that any vague references "
                    f"('that', 'it', 'the song', 'the file', 'the one', 'what you said', etc.) "
                    f"are replaced with the specific thing they refer to based on the conversation above.\n"
                    f"If the message is already explicit, return it unchanged.\n"
                    f"Return ONLY the rewritten message, nothing else.\n\n"
                    f"Message: \"{message}\""
                )
            }],
            options={"temperature": 0}
        )
        resolved = response['message'].get('content', '').strip().strip('"')
        if resolved:
            self._obs("verbose", f"Reference resolved: '{message}' → '{resolved}'")
            return resolved
        return message

    def _extract_ui_action(self, message: str) -> dict:
        """Parse action + value for control_self directly from the message text.

        Routing to control_self is the LLM's job (stage-1 classifier).
        Extracting structure from a known intent category is a parsing job —
        Python is faster and more reliable here than asking the small model
        to generate JSON.

        Falls back to an LLM call only for open-ended name extraction.
        """
        m = message.lower()

        def _show_hide(text):
            if any(w in text for w in ("show", "open", "on", "enable", "visible")):
                return "show"
            return "hide"

        # ── Theme ────────────────────────────────────────────────────────
        for theme in ("midnight", "terminal", "sunset", "default"):
            if theme in m:
                return {"action": "set_theme", "value": theme}

        # ── Animation ────────────────────────────────────────────────────
        if "ascii" in m:
            return {"action": "set_animation", "value": "ascii"}
        if "vector" in m or "bmo" in m:
            return {"action": "set_animation", "value": "vector"}
        # Toggle when the user says "switch/change face style" without specifying which
        if any(w in m for w in ("face style", "face animation", "animation style",
                                "switch animation", "change animation", "switch face",
                                "change face", "switch ur face", "change ur face")):
            return {"action": "set_animation", "value": "toggle"}

        # ── Mode ─────────────────────────────────────────────────────────
        # Require "mode" or an explicit imperative verb — bare "voice" is too broad
        # (e.g. "I love your voice" should NOT route here).
        if any(p in m for p in ("voice mode", "switch to voice", "go to voice",
                                "use voice", "activate voice", "voice input")):
            return {"action": "set_mode", "value": "voice"}
        if any(w in m for w in ("chat mode", "text mode", "chat input", "switch to chat",
                                "go to chat", "typing mode")):
            return {"action": "set_mode", "value": "chat"}

        # ── Pages ────────────────────────────────────────────────────────
        if "setting" in m:
            return {"action": "open_settings"}
        if "diagnostic" in m or "dashboard" in m:
            return {"action": "open_diagnostics"}

        # ── Clear ────────────────────────────────────────────────────────
        _clear_words = ("clear", "wipe", "reset", "delete", "erase", "forget")
        if any(w in m for w in _clear_words):
            if any(w in m for w in ("histor", "conversation", "chat", "messages")):
                return {"action": "clear_history"}
            if any(w in m for w in ("memor", "everything", "all")):
                return {"action": "clear_memories"}

        # ── Status bar ───────────────────────────────────────────────────
        if "status bar" in m or ("status" in m and "bar" in m):
            return {"action": "set_status_bar", "value": _show_hide(m)}

        # ── Chat feed / transcript ────────────────────────────────────────
        if any(w in m for w in ("chat feed", "chat window", "transcript",
                                "show chat", "hide chat", "open chat", "close chat")):
            return {"action": "set_chat_feed", "value": _show_hide(m)}

        # ── TTS mute ─────────────────────────────────────────────────────
        if "unmute" in m:
            return {"action": "set_tts_mute", "value": "unmute"}
        if "mute" in m:
            return {"action": "set_tts_mute", "value": "mute"}

        # ── Profile switching (open-ended name → LLM) ────────────────────
        # Require an imperative verb — "my LinkedIn profile" should not match.
        _profile_verbs = ("switch", "change", "go to", "use", "load",
                          "activate", "select", "swap")
        if "profile" in m and any(v in m for v in _profile_verbs):
            return {"action": "switch_profile", "value": self._extract_name(message)}

        # ── Menu button ───────────────────────────────────────────────────
        _menu_words = ("3 dot", "three dot", "dots menu", "menu button",
                       "dot menu", "3dot", "triple dot")
        if any(w in m for w in _menu_words) or ("menu" in m and "button" in m):
            return {"action": "set_menu_button", "value": _show_hide(m)}

        # ── Names (open-ended → LLM) ──────────────────────────────────────
        # Use imperative-only patterns — "what's your name?" should NOT match.
        if any(w in m for w in ("call you", "rename you", "your name to",
                                "change your name", "bot name")):
            return {"action": "set_bot_name", "value": self._extract_name(message)}
        if any(w in m for w in ("call me", "my name is", "user name is",
                                "set my name")):
            return {"action": "set_user_name", "value": self._extract_name(message)}

        self._obs("verbose", f"control_self: no action matched for: {message}")
        return {"action": "", "value": ""}

    def _extract_ui_actions_multi(self, message: str) -> list[dict]:
        """Collect ALL control_self actions from a single message.

        Unlike _extract_ui_action (which stops at the first match), this runs
        every pattern check and returns a list so multi-action requests like
        'hide the status bar and change theme to midnight' produce two entries.
        """
        m = message.lower()
        results: list[dict] = []

        def _show_hide(text: str) -> str:
            if any(w in text for w in ("show", "open", "on", "enable", "visible")):
                return "show"
            return "hide"

        # ── Theme ────────────────────────────────────────────────────────
        for theme in ("midnight", "terminal", "sunset", "default"):
            if theme in m:
                results.append({"action": "set_theme", "value": theme})
                break  # only one theme at a time

        # ── Animation ────────────────────────────────────────────────────
        if "ascii" in m:
            results.append({"action": "set_animation", "value": "ascii"})
        elif "vector" in m or "bmo" in m:
            results.append({"action": "set_animation", "value": "vector"})
        elif any(w in m for w in ("face style", "face animation", "animation style",
                                  "switch animation", "change animation", "switch face",
                                  "change face", "switch ur face", "change ur face")):
            results.append({"action": "set_animation", "value": "toggle"})

        # ── Mode ─────────────────────────────────────────────────────────
        if any(p in m for p in ("voice mode", "switch to voice", "go to voice",
                                "use voice", "activate voice", "voice input")):
            results.append({"action": "set_mode", "value": "voice"})
        elif any(w in m for w in ("chat mode", "text mode", "chat input", "switch to chat",
                                  "go to chat", "typing mode")):
            results.append({"action": "set_mode", "value": "chat"})

        # ── Pages ────────────────────────────────────────────────────────
        if "setting" in m:
            results.append({"action": "open_settings"})
        if "diagnostic" in m or "dashboard" in m:
            results.append({"action": "open_diagnostics"})

        # ── Clear ────────────────────────────────────────────────────────
        _clear_words = ("clear", "wipe", "reset", "delete", "erase", "forget")
        if any(w in m for w in _clear_words):
            if any(w in m for w in ("histor", "conversation", "chat", "messages")):
                results.append({"action": "clear_history"})
            if any(w in m for w in ("memor", "everything", "all")):
                results.append({"action": "clear_memories"})

        # ── Status bar ───────────────────────────────────────────────────
        if "status bar" in m or ("status" in m and "bar" in m):
            results.append({"action": "set_status_bar", "value": _show_hide(m)})

        # ── Chat feed / transcript ────────────────────────────────────────
        if any(w in m for w in ("chat feed", "chat window", "transcript",
                                "show chat", "hide chat", "open chat", "close chat")):
            results.append({"action": "set_chat_feed", "value": _show_hide(m)})

        # ── TTS mute ─────────────────────────────────────────────────────
        if "unmute" in m:
            results.append({"action": "set_tts_mute", "value": "unmute"})
        elif "mute" in m:
            results.append({"action": "set_tts_mute", "value": "mute"})

        # ── Profile ──────────────────────────────────────────────────────
        _profile_verbs = ("switch", "change", "go to", "use", "load",
                          "activate", "select", "swap")
        if "profile" in m and any(v in m for v in _profile_verbs):
            results.append({"action": "switch_profile", "value": self._extract_name(message)})

        # ── Menu button ──────────────────────────────────────────────────
        _menu_words = ("3 dot", "three dot", "dots menu", "menu button",
                       "dot menu", "3dot", "triple dot")
        if any(w in m for w in _menu_words) or ("menu" in m and "button" in m):
            results.append({"action": "set_menu_button", "value": _show_hide(m)})

        # ── Names ────────────────────────────────────────────────────────
        if any(w in m for w in ("call you", "rename you", "your name to",
                                "change your name", "bot name")):
            results.append({"action": "set_bot_name", "value": self._extract_name(message)})
        if any(w in m for w in ("call me", "my name is", "user name is",
                                "set my name")):
            results.append({"action": "set_user_name", "value": self._extract_name(message)})

        return results

    def _extract_name(self, message: str) -> str:
        """Use the classifier LLM to pull a proper name out of a message."""
        classifier_model = getattr(config, 'INTENT_CLASSIFIER_MODEL', config.OLLAMA_MODEL)
        response = ollama.chat(
            model=classifier_model,
            messages=[{
                "role": "user",
                "content": (
                    f"Extract the name from this message. Reply with ONLY the name, nothing else.\n"
                    f"Examples:\n"
                    f"  'change your name to Luna' → Luna\n"
                    f"  'call me Yusuf from now on' → Yusuf\n"
                    f"  'rename yourself Alex' → Alex\n\n"
                    f"Message: \"{message}\""
                )
            }],
            options={"temperature": 0}
        )
        return response['message'].get('content', '').strip()

    def _extract_clipboard_content(self, message: str) -> str:
        """Use the classifier LLM to extract what the user wants written to the clipboard.
        Vague references are already resolved by _resolve_references before this is called."""
        classifier_model = getattr(config, 'INTENT_CLASSIFIER_MODEL', config.OLLAMA_MODEL)
        response = ollama.chat(
            model=classifier_model,
            messages=[{
                "role": "user",
                "content": (
                    f"Extract exactly what the user wants copied to their clipboard.\n"
                    f"Return ONLY the text to copy, with no explanation or extra words.\n"
                    f"Examples:\n"
                    f"  'copy hello world to my clipboard' → hello world\n"
                    f"  'put my email address in the clipboard: test@example.com' → test@example.com\n"
                    f"  'add Bohemian Rhapsody to my clipboard' → Bohemian Rhapsody\n\n"
                    f"User message: \"{message}\""
                )
            }],
            options={"temperature": 0}
        )
        content = response['message'].get('content', '').strip()
        self._obs("verbose", f"Clipboard content: {content}")
        return content if content else message

    def _extract_shell_command(self, message: str) -> str:
        """Use the classifier LLM to extract a shell command from a natural language request.
        Vague references are already resolved by _resolve_references before this is called."""
        classifier_model = getattr(config, 'INTENT_CLASSIFIER_MODEL', config.OLLAMA_MODEL)
        response = ollama.chat(
            model=classifier_model,
            messages=[{
                "role": "user",
                "content": (
                    f"Extract the shell command the user wants to run from this message. "
                    f"Reply with ONLY the shell command, nothing else. "
                    f"Use macOS/Linux syntax. For opening apps use 'open -a \"AppName\"'. "
                    f"For opening a URL in a specific browser: open -a \"BrowserName\" \"https://url\"\n"
                    f"For opening a URL in the default browser: open \"https://url\"\n"
                    f"Default browser is Brave unless the user specifies Safari or another browser.\n"
                    f"Always add https:// to bare domains (e.g. theverge.com → https://theverge.com).\n"
                    f"Always quote the app name with double quotes.\n"
                    f"For YouTube searches: open -a \"Brave Browser\" \"https://www.youtube.com/results?search_query=<query+with+plus+for+spaces>\"\n"
                    f"For DuckDuckGo searches: open -a \"Brave Browser\" \"https://duckduckgo.com/?q=<query+with+plus+for+spaces>\"\n"
                    f"If the request is ambiguous, produce the most likely shell command.\n\n"
                    f"Examples:\n"
                    f"  'open theverge.com' → open -a \"Brave Browser\" \"https://theverge.com\"\n"
                    f"  'open gmail in safari' → open -a \"Safari\" \"https://gmail.com\"\n"
                    f"  'open gmail in brave' → open -a \"Brave Browser\" \"https://gmail.com\"\n"
                    f"  'search youtube for lo-fi music' → open -a \"Brave Browser\" \"https://www.youtube.com/results?search_query=lo-fi+music\"\n"
                    f"  'open youtube' → open -a \"Brave Browser\" \"https://www.youtube.com\"\n"
                    f"  'open Ichibanboshi Mitsuketa on youtube' → open -a \"Brave Browser\" \"https://www.youtube.com/results?search_query=Ichibanboshi+Mitsuketa\"\n"
                    f"  'launch calculator' → open -a \"Calculator\"\n\n"
                    f"Message: \"{message}\""
                )
            }],
            options={"temperature": 0}
        )
        command = response['message'].get('content', '').strip()
        self._obs("verbose", f"Shell command: {command}")
        return command

    def _extract_shell_commands_multi(self, message: str) -> list[str]:
        """Extract all shell commands from a multi-action request.

        Returns a list of command strings. Falls back to a single command if
        the LLM doesn't return valid JSON.
        """
        classifier_model = getattr(config, 'INTENT_CLASSIFIER_MODEL', config.OLLAMA_MODEL)
        response = ollama.chat(
            model=classifier_model,
            messages=[{
                "role": "user",
                "content": (
                    f"Extract ALL shell commands the user wants to run from this message. "
                    f"Return a JSON array of shell command strings, nothing else.\n"
                    f"Use macOS/Linux syntax. For opening apps use 'open -a \"AppName\"'.\n"
                    f"For opening a URL in a specific browser: open -a \"BrowserName\" \"https://url\"\n"
                    f"Default browser is Brave unless the user specifies another browser.\n"
                    f"Always add https:// to bare domains.\n"
                    f"Always quote app names with double quotes.\n"
                    f"For YouTube searches: open -a \"Brave Browser\" \"https://www.youtube.com/results?search_query=<query+with+plus>\"\n\n"
                    f"Examples:\n"
                    f"  'open safari and calculator' → [\"open -a \\\"Safari\\\"\", \"open -a \\\"Calculator\\\"\"]\n"
                    f"  'open youtube and spotify' → [\"open -a \\\"Brave Browser\\\" \\\"https://youtube.com\\\"\", \"open -a \\\"Spotify\\\"\"]\n"
                    f"  'launch finder' → [\"open -a \\\"Finder\\\"\"]\n\n"
                    f"Message: \"{message}\"\n\n"
                    f"Return ONLY a JSON array of strings:"
                )
            }],
            options={"temperature": 0}
        )
        raw = response['message'].get('content', '').strip()
        try:
            commands = json.loads(raw)
            if isinstance(commands, list) and commands:
                result = [str(c) for c in commands if c]
                self._obs("verbose", f"Shell commands: {result}")
                return result
        except (json.JSONDecodeError, ValueError):
            pass
        # Fallback to single-command extractor
        return [self._extract_shell_command(message)]

    def _plan_tool_calls(self, tools: list[str], message: str) -> list[tuple[str, dict]]:
        """Build an ordered list of (tool_name, args) pairs for all planned tools.

        Handles multi-instance tools (execute_shell, control_self) by extracting
        all their args in bulk, then distributing them across the slots.
        """
        msg = self._resolve_references(message)
        planned: list[tuple[str, dict]] = []

        # Pre-extract bulk args for multi-instance tools.
        cs_actions: list[dict] = list(self._pending_control_self_args or [])
        self._pending_control_self_args = None
        cs_idx = 0

        shell_tools_count = tools.count('execute_shell')
        shell_commands: list[str] = []
        if shell_tools_count > 1:
            shell_commands = self._extract_shell_commands_multi(msg)
        elif shell_tools_count == 1:
            shell_commands = [self._extract_shell_command(msg)]
        shell_idx = 0

        for tool_name in tools:
            if tool_name == 'control_self':
                if cs_idx < len(cs_actions) and cs_actions[cs_idx].get("action"):
                    planned.append(('control_self', cs_actions[cs_idx]))
                else:
                    planned.append(('control_self', self._extract_ui_action(msg)))
                cs_idx += 1
            elif tool_name == 'execute_shell':
                if shell_idx < len(shell_commands):
                    planned.append(('execute_shell', {'command': shell_commands[shell_idx]}))
                else:
                    planned.append(('execute_shell', {'command': self._extract_shell_command(msg)}))
                shell_idx += 1
            elif tool_name == 'web_search':
                planned.append((tool_name, {'query': msg}))
            elif tool_name == 'get_current_time':
                planned.append((tool_name, {}))
            elif tool_name == 'calculate':
                planned.append((tool_name, {'expression': msg}))
            elif tool_name == 'get_weather':
                planned.append((tool_name, {'location': self._extract_location(msg)}))
            elif tool_name == 'get_location':
                planned.append((tool_name, {}))
            elif tool_name == 'read_file':
                planned.append((tool_name, {'path': self._extract_path(msg)}))
            elif tool_name == 'list_directory':
                planned.append((tool_name, {'path': self._extract_path(msg)}))
            elif tool_name == 'get_system_health':
                planned.append((tool_name, {}))
            elif tool_name == 'remember':
                planned.append((tool_name, {'fact': self._extract_fact(msg)}))
            elif tool_name == 'read_clipboard':
                planned.append((tool_name, {}))
            elif tool_name == 'write_clipboard':
                planned.append((tool_name, {'content': self._extract_clipboard_content(msg)}))
            elif tool_name == 'take_screenshot':
                planned.append((tool_name, {}))
            else:
                planned.append((tool_name, {}))
        return planned

    def _extract_fact(self, message: str) -> str:
        """Extract the fact the user wants remembered from their message."""
        classifier_model = getattr(config, 'INTENT_CLASSIFIER_MODEL', config.OLLAMA_MODEL)

        # Build existing-memory context so the LLM can normalise consistently
        existing_block = ""
        if self.settings:
            existing = self.settings.load_memories(config.ACTIVE_PROFILE)
            if existing:
                existing_block = (
                    "Already known facts (do NOT return any of these):\n"
                    + "\n".join(f"- {f}" for f in existing)
                    + "\n\n"
                )

        response = ollama.chat(
            model=classifier_model,
            messages=[{
                "role": "user",
                "content": (
                    f"Extract the specific fact the user wants to be remembered from this message. "
                    f"Rephrase it as a short, clear statement starting with a verb or noun — "
                    f"NO subject pronoun (not 'she', 'he', 'they', 'the user', 'I'). "
                    f"Examples: 'prefers dark mode', 'has a dog named Max'. "
                    f"If the fact is already listed below as already known, reply with exactly: ALREADY_KNOWN\n"
                    f"Reply with ONLY the fact (or ALREADY_KNOWN), nothing else.\n\n"
                    f"{existing_block}"
                    f"Message: \"{message}\""
                )
            }],
            options={"temperature": 0}
        )
        fact = response['message'].get('content', message).strip()
        if fact.upper() == "ALREADY_KNOWN":
            self._obs("lite", "Memory extraction: fact already known, skipping")
            return ""
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

        # Step 1: Classify which tools (if any) are needed.
        tools_needed: list[str] = []
        if tool_manager.has_tools():
            tools_needed = self._classify_tool_intent(user_message)

        # Step 2: Execute all tools and collect results.
        if tools_needed:
            self.display.move_cursor_to_feed_bottom()
            label = ", ".join(dict.fromkeys(tools_needed))  # deduplicated for display
            self.display.show_info(f"Using tool: {label}")

            planned_calls = self._plan_tool_calls(tools_needed, user_message)
            tool_results: list[tuple[str, str]] = []

            for tool_name, tool_args in planned_calls:
                # Window hide/show around screenshot capture
                if tool_name == "take_screenshot" and hasattr(self.display, 'hide_window'):
                    self.display.hide_window()

                tool_result = tool_manager.execute_tool(tool_name, tool_args)

                if tool_name == "take_screenshot" and hasattr(self.display, 'show_window'):
                    self.display.show_window()
                if tool_name == "execute_shell" and hasattr(self.display, 'raise_window'):
                    self.display.raise_window(delay=0.2)

                self._obs("lite", f"Tool: {tool_name} → {len(tool_result)} chars")
                self._obs("verbose", f"Tool result:\n{tool_result}")
                tool_results.append((tool_name, tool_result))

            # Step 2b: Inject results into conversation history.
            _ACTION_TOOLS = {"control_self", "execute_shell", "computer_control", "remember", "write_clipboard"}

            # Handle take_screenshot specially (vision pipeline).
            screenshot_result = next(
                ((n, r) for n, r in tool_results if n == "take_screenshot"), None
            )
            if screenshot_result:
                vision_description = self._handle_vision_query(screenshot_result[1], user_message)
                if vision_description:
                    injection_content = (
                        f"[I am currently looking at the user's screen and this is what I can see]\n"
                        f"{vision_description}\n\n"
                        f"Using what I can see right now, respond to: {user_message}"
                    )
                else:
                    injection_content = (
                        f"You tried to look at the user's screen but the capture failed. "
                        f"Let them know you couldn't see the screen and ask them to try again."
                    )
                self.conversation_history.append({"role": "user", "content": injection_content})

            # Build combined injection for all non-screenshot tools.
            other_results = [(n, r) for n, r in tool_results if n != "take_screenshot"]
            if other_results:
                if len(other_results) == 1:
                    tool_name, tool_result = other_results[0]
                    if tool_name in _ACTION_TOOLS:
                        injection_content = (
                            f"[You just completed this action: {tool_result}] "
                            f"Acknowledge it briefly and naturally to the user. "
                            f"Their request was: {user_message}"
                        )
                    else:
                        injection_content = (
                            f"[Result]\n{tool_result}\n\n"
                            f"Using the result above, answer this naturally: {user_message}"
                        )
                else:
                    # Multiple tools — build a combined block.
                    action_lines: list[str] = []
                    info_sections: list[str] = []
                    for tool_name, tool_result in other_results:
                        if tool_name in _ACTION_TOOLS:
                            action_lines.append(f"- {tool_result}")
                        else:
                            info_sections.append(f"[{tool_name} result]\n{tool_result}")

                    parts: list[str] = []
                    if action_lines:
                        parts.append("[Actions completed:\n" + "\n".join(action_lines) + "]")
                    if info_sections:
                        parts.append("\n\n".join(info_sections))

                    combined = "\n\n".join(parts)
                    if action_lines and not info_sections:
                        injection_content = (
                            f"{combined}\n\n"
                            f"Acknowledge all completed actions briefly and naturally in one "
                            f"response. Their request was: {user_message}"
                        )
                    else:
                        injection_content = (
                            f"{combined}\n\n"
                            f"Using the above results, respond naturally to: {user_message}"
                        )

                self.conversation_history.append({"role": "user", "content": injection_content})

            self._last_turn_had_tool_call = True
            self._last_tools_used = tools_needed
        else:
            self._last_turn_had_tool_call = False
            self._last_tools_used = []

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

        if voice_streaming and hasattr(self, 'tts_engine') and self.tts_engine and "control_self" not in tools_needed:
            # Voice mode: stream tokens to display + speak each sentence as it arrives.
            # control_self is excluded — its actions (e.g. mute) take effect
            # asynchronously via Clock, so the toggle state is stale when
            # begin_stream runs. Force face_stream_mode so the response text
            # is always visible regardless of chat/TTS state.
            t0 = time.monotonic()
            content = self._stream_and_speak(messages_for_call)
            elapsed = time.monotonic() - t0
        else:
            # Force face stream for control_self only when TTS is muted —
            # that's when the user would otherwise get no visible feedback.
            # If TTS is on (e.g. unmute response), let normal streaming handle it.
            if "control_self" in tools_needed and hasattr(self.display, '_force_face_stream'):
                tts_muted = not self.display.toggles.get('speaking', True)
                chat_visible = self.display.toggles.get('chat', True)
                self.display._force_face_stream = tts_muted and not chat_visible
            content, elapsed = _do_llm_call(messages_for_call, start_bubble=True)

            # Guard against empty responses - retry once without tool context
            if not content and tools_needed:
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
        self._obs("lite", f"Response: {content}")
        if "take_screenshot" in self._last_tools_used:
            self._obs("verbose", f"Vision interpretation [{config.OLLAMA_MODEL}]: {content}")

        # Persist exchange to session file (incremental; survives crashes)
        if self.settings and self._session_path and config.SAVE_CONVERSATION_HISTORY:
            self.settings.append_to_session(self._session_path, user_message, content)

        # Extract user memories asynchronously (never blocks the response pipeline).
        # Skip when a tool was used — tool exchanges are task-oriented and rarely
        # contain personal facts worth remembering (and the injection framing can
        # confuse the extractor).
        # daemon=False so the thread survives app shutdown long enough to write;
        # _save_conversation joins it with a timeout as a safety net.
        if self.settings and self.settings.get("memory_enabled", True) and not self._last_turn_had_tool_call:
            t = threading.Thread(
                target=self._extract_memories,
                args=(user_message, content),
                daemon=False,
            )
            t.start()
            self._memory_thread = t

        return content

    def _handle_vision_query(self, screenshot_path: str, user_message: str = "") -> str:
        """Silently call the vision model and return its description of the screen.

        The description is injected as context for the main LLM, which then
        responds with Zeina's personality as if actively looking at the screen.
        """
        vision_model = (
            self.settings.get("vision_model", getattr(config, 'VISION_MODEL', 'llava'))
            if self.settings else getattr(config, 'VISION_MODEL', 'llava')
        )

        # Validate the screenshot file — a blank/black capture (e.g. macOS
        # Screen Recording permission denied) produces a tiny file that will
        # cause the vision model to hallucinate.
        try:
            file_size = os.path.getsize(screenshot_path)
        except OSError:
            self._obs("lite", "Vision: screenshot file missing — aborting")
            return ""

        if file_size < 10_000:  # < 10 KB almost certainly means a blank capture
            self._obs("lite", f"Vision: screenshot too small ({file_size} bytes) — likely blank; check macOS Screen Recording permission")
            try:
                os.remove(screenshot_path)
            except OSError:
                pass
            return ""

        # Resize to max 1280px wide to keep inference fast
        try:
            from PIL import Image
            img = Image.open(screenshot_path)
            if img.width > 1280:
                img = img.resize(
                    (1280, int(img.height * 1280 / img.width)), Image.LANCZOS
                )
                img.save(screenshot_path)
        except Exception:
            pass

        self._obs("lite", f"Vision: screenshot {file_size // 1024} KB → {screenshot_path}")

        # Pass the user's question directly as content — this grounds the model
        # and prevents hallucination. Wrapping it in a longer meta-prompt causes drift.
        messages = [
            {"role": "system", "content": (
                "You are a precise screen reader. Describe ONLY what is literally visible in the "
                "screenshot with as much detail as possible: every window title, app name, menu, "
                "button label, visible text (quote it verbatim), error messages, code snippets, "
                "URL in the address bar, file names, icons, and the overall layout. "
                "Do NOT invent, infer, or add anything not directly visible. "
                "If something is partially obscured or unclear, say so explicitly."
            )},
            {"role": "user", "content": user_message or "What do you see on the screen?", "images": [screenshot_path]},
        ]

        description = ""
        try:
            for chunk in ollama.chat(model=vision_model, messages=messages, stream=True):
                token = chunk['message'].get('content', '')
                if token:
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
