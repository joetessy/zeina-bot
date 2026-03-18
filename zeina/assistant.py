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
import difflib
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
        self._speaking_lock = threading.Lock()  # Protect is_speaking across threads

        # Track modifier keys for shortcuts
        self.ctrl_pressed = False

        # Flag to prevent double-handling of keys in chat mode
        self.taking_chat_input = False

        # Event log
        self.event_log = deque(maxlen=50)

        # Multi-turn follow-up tracking
        self._last_turn_had_tool_call = False
        self._last_tools_used: list[str] = []

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

    def _set_speaking(self, value: bool) -> None:
        """Thread-safe setter for is_speaking."""
        with self._speaking_lock:
            self.is_speaking = value

    def _get_speaking(self) -> bool:
        """Thread-safe getter for is_speaking."""
        with self._speaking_lock:
            return self.is_speaking

    @property
    def _classifier_model(self) -> str:
        """Return the intent classifier model, falling back to the main model."""
        return getattr(config, 'INTENT_CLASSIFIER_MODEL', config.OLLAMA_MODEL)

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
        """Verify Ollama is running, auto-starting it if needed."""
        print("🧠 Checking Ollama connection...")
        try:
            ollama.list()
            print(f"✓ Connected to Ollama (model: {config.OLLAMA_MODEL})")
            return
        except Exception:
            pass

        # Ollama not running — try to start it
        print("⏳ Ollama not running, starting it...")
        try:
            import subprocess
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            # Wait for it to become available
            for _ in range(15):
                time.sleep(1)
                try:
                    ollama.list()
                    print(f"✓ Ollama started (model: {config.OLLAMA_MODEL})")
                    return
                except Exception:
                    continue
            print("❌ Ollama started but not responding after 15s")
            sys.exit(1)
        except FileNotFoundError:
            print("❌ Ollama is not installed. Install it from https://ollama.com")
            sys.exit(1)
        except Exception as e:
            print(f"❌ Failed to start Ollama: {e}")
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
        self.display.update_face_state(self.state, self._get_speaking())

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
                self._set_speaking(True)
                self.display.update_face_state(self.state, self._get_speaking())
                self.tts_engine.speak(assistant_response)
                self._set_speaking(False)
                self.display.update_face_state(self.state, self._get_speaking())
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
            self.display.update_face_state(self.state, self._get_speaking())

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

    def _classify_and_extract(self, message: str) -> list[tuple[str, dict]]:
        """Classify tools AND extract arguments in a single pass.

        Two-stage approach:
          Stage 0 — Python patterns: _extract_ui_actions_multi deterministically
                    collects all control_self actions (zero LLM cost).
          Stage 1 — Native tool calling: a single ollama.chat(tools=...) call
                    that returns both tool names AND structured arguments.
                    Replaces the old Stage 1 (binary LLM), Stage 1.5 (fast-paths),
                    Stage 2 (text classifier), and all _extract_* methods.

        Returns an ordered list of (tool_name, args_dict) pairs, or [] for no tools.
        """
        planned: list[tuple[str, dict]] = []

        # Stage 0: Python-first — collect all control_self actions.
        if 'control_self' in tool_manager.tools:
            ui_actions = self._extract_ui_actions_multi(message)
            if ui_actions:
                for action in ui_actions:
                    planned.append(('control_self', action))
                self._obs("lite", f"Intent: control_self ×{len(ui_actions)} (patterns)")

        # Stage 1: Native tool calling for everything else.
        control_self_handled = any(name == 'control_self' for name, _ in planned)
        tool_schemas = self._get_tool_schemas(exclude_control_self=control_self_handled)

        if not tool_schemas:
            return planned

        # Build messages with conversation context for reference resolution
        system_prompt = self._build_classifier_system_prompt(
            control_self_handled=control_self_handled
        )
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        # Include recent conversation turns so the model can resolve
        # vague references ("that", "it", "the song") without a separate LLM call.
        recent = [m for m in self.conversation_history
                  if m.get("role") in ("user", "assistant")][-4:]
        messages.extend(recent)
        messages.append({"role": "user", "content": message})

        try:
            response = ollama.chat(
                model=self._classifier_model,
                messages=messages,
                tools=tool_schemas,
                options={"temperature": 0},
            )
        except Exception as e:
            self._obs("lite", f"Tool calling error: {e}")
            return planned

        tool_calls = response.get('message', {}).get('tool_calls', [])

        if not tool_calls:
            self._obs("lite", f"Intent [{self._classifier_model}]: none")
            return planned

        seen_screenshot = any(name == 'take_screenshot' for name, _ in planned)
        for tc in tool_calls:
            fn = tc.get('function', {})
            name = fn.get('name', '')
            args = fn.get('arguments', {})

            # Validate tool exists
            if name not in tool_manager.tools:
                self._obs("verbose", f"Unknown tool from native call: {name}")
                continue

            # Deduplicate take_screenshot
            if name == 'take_screenshot' and seen_screenshot:
                continue
            if name == 'take_screenshot':
                seen_screenshot = True

            # Post-process remember: check for duplicate memories
            if name == 'remember':
                fact = args.get('fact', '')
                if self._is_duplicate_memory(fact):
                    self._obs("lite", "Memory: duplicate fact, skipping")
                    continue

            planned.append((name, args))
            self._obs("lite", f"Intent [{self._classifier_model}]: {name}")

        return planned

    def _get_tool_schemas(self, exclude_control_self: bool = False) -> list[dict]:
        """Return Ollama tool schemas, optionally excluding control_self."""
        schemas = []
        for name, tool in tool_manager.tools.items():
            if name == 'control_self' and exclude_control_self:
                continue
            schemas.append(tool.to_ollama_schema())
        return schemas

    def _build_classifier_system_prompt(self, control_self_handled: bool = False) -> str:
        """Build the system prompt for the native tool calling classifier."""
        parts = [
            "You are a tool router for Zeina, an AI voice assistant. "
            "Call the appropriate tool(s) if the user's request matches one. "
            "If no tool is needed (greetings, general knowledge, casual chat, "
            "follow-ups on already-fetched data, hypothetical questions, "
            "meta-questions about capabilities), respond with a short text message "
            "instead of calling any tool. When in doubt, do NOT call a tool."
        ]

        # Prior-tool context to avoid re-triggering
        if self._last_turn_had_tool_call and self._last_tools_used:
            tools_str = ", ".join(f"'{t}'" for t in self._last_tools_used)
            parts.append(
                f"\nCONTEXT: The previous turn already used {tools_str} and that data "
                f"is in the conversation. Only call tools for NEW or DIFFERENT information."
            )

        # Bias away from tools if control_self already handled
        if control_self_handled:
            parts.append(
                "\nNOTE: This message was already matched to Zeina's internal UI controls. "
                "Only call additional tools if the message ALSO explicitly requests "
                "something external (open an app, search the web, etc.)."
            )

        return "\n".join(parts)

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

    def _match_ui_patterns(self, m: str, message: str, multi: bool) -> list[dict]:
        """Shared pattern matching core for UI control actions.

        Args:
            m: pre-lowercased message text.
            message: original casing, used for LLM name/profile extraction.
            multi: True = collect all matches; False = return after first match.

        Routing to control_self is the LLM's job (stage-1 classifier).
        Extracting structure is a parsing job — Python is faster and more
        reliable than asking the small model to generate JSON.
        Falls back to LLM only for open-ended name extraction.
        """
        results: list[dict] = []

        def _emit(action_dict: dict) -> bool:
            """Append result. Returns True when caller should stop (single mode)."""
            results.append(action_dict)
            return not multi

        # ── Theme ────────────────────────────────────────────────────────
        for theme in ("midnight", "terminal", "sunset", "default"):
            if theme in m:
                if _emit({"action": "set_theme", "value": theme}):
                    return results
                break  # only one theme at a time

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
        # Require "mode" or an explicit imperative verb — bare "voice" is too broad
        # (e.g. "I love your voice" should NOT route here).
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
        # Require an imperative verb — "my LinkedIn profile" should not match.
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

        # ── Names (open-ended → LLM) ──────────────────────────────────────
        # Use imperative-only patterns — "what's your name?" should NOT match.
        if any(w in m for w in ("call you", "rename you", "your name to",
                                "change your name", "bot name")):
            if _emit({"action": "set_bot_name", "value": self._extract_name(message)}):
                return results
        if any(w in m for w in ("call me", "my name is", "user name is",
                                "set my name")):
            if _emit({"action": "set_user_name", "value": self._extract_name(message)}):
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
        """Collect ALL UI control actions from a single message.

        Runs every pattern check and returns a list so multi-action requests
        like 'hide the status bar and change theme to midnight' produce two
        entries.
        """
        return self._match_ui_patterns(message.lower(), message, multi=True)

    def _extract_name(self, message: str) -> str:
        """Use the classifier LLM to pull a proper name out of a message."""
        response = ollama.chat(
            model=self._classifier_model,
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
            resp = ollama.chat(
                model=self._classifier_model,
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

    def _inject_tool_results(
        self,
        tool_results: list,
        tools_needed: list,
        user_message: str,
    ) -> None:
        """Inject tool execution results into conversation_history as user messages.

        Handles the take_screenshot / vision pipeline separately from regular tools.
        After this call, conversation_history is ready for the main LLM step.
        """
        _ACTION_TOOLS = {"control_self", "execute_shell", "computer_control", "remember", "write_clipboard"}

        # ── Screenshot (vision pipeline) ─────────────────────────────────
        screenshot_result = next(
            ((n, r) for n, r in tool_results if n == "take_screenshot"), None
        )
        if screenshot_result:
            vision_description = self._handle_vision_query(screenshot_result[1], user_message)
            if vision_description:
                injection_content = (
                    f"[I looked at the user's screen. Here is what I see:]\n"
                    f"{vision_description}\n\n"
                    f"Describe what you see on the screen to the user in a natural, "
                    f"conversational way. Tell them what's actually on the screen — "
                    f"don't just say you took a screenshot. Their question: {user_message}"
                )
            else:
                injection_content = (
                    f"You tried to look at the user's screen but the capture failed. "
                    f"Let them know you couldn't see the screen and ask them to try again."
                )
            self.conversation_history.append({"role": "user", "content": injection_content})

        # ── All other tools ───────────────────────────────────────────────
        other_results = [(n, r) for n, r in tool_results if n != "take_screenshot"]
        if not other_results:
            return

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

        # Step 1+2: Classify tools AND extract args in one pass, then execute.
        planned_calls: list[tuple[str, dict]] = []
        if tool_manager.has_tools():
            planned_calls = self._classify_and_extract(user_message)

        if planned_calls:
            tools_needed = [name for name, _ in planned_calls]
            self.display.move_cursor_to_feed_bottom()
            label = ", ".join(dict.fromkeys(tools_needed))  # deduplicated for display
            self.display.show_info(f"Using tool: {label}")

            tool_results: list[tuple[str, str]] = []

            # Partition into parallel (stateless) and sequential (UI-dependent) tools
            _SEQUENTIAL_TOOLS = {"take_screenshot", "execute_shell", "control_self"}
            parallel_calls = [(n, a) for n, a in planned_calls if n not in _SEQUENTIAL_TOOLS]
            sequential_calls = [(n, a) for n, a in planned_calls if n in _SEQUENTIAL_TOOLS]

            # Run parallelisable tools concurrently
            if parallel_calls:
                from concurrent.futures import ThreadPoolExecutor, as_completed

                def _exec(name, args):
                    return (name, tool_manager.execute_tool(name, args))

                with ThreadPoolExecutor(max_workers=4) as pool:
                    futures = [pool.submit(_exec, n, a) for n, a in parallel_calls]
                    for f in as_completed(futures):
                        name, result = f.result()
                        self._obs("lite", f"Tool: {name} → {len(result)} chars")
                        self._obs("verbose", f"Tool result:\n{result}")
                        tool_results.append((name, result))

            # Run sequential tools in order (with UI guards)
            for tool_name, tool_args in sequential_calls:
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

            # Inject results into conversation history.
            self._inject_tool_results(tool_results, tools_needed, user_message)

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

        # Re-check the speaking toggle after tool execution — a control_self mute action
        # updates toggles['speaking'] synchronously in _handle_ui_control, so this
        # correctly reflects the new state before we decide whether to use TTS.
        speaking_after_tools = getattr(self.display, 'toggles', {}).get('speaking', True)
        if voice_streaming and hasattr(self, 'tts_engine') and self.tts_engine and speaking_after_tools:
            # Voice mode: stream tokens to display + speak each sentence as it arrives.
            t0 = time.monotonic()
            content = self._stream_and_speak(messages_for_call)
            elapsed = time.monotonic() - t0
        else:
            # TTS is off (muted or not in voice mode) — show text on face when
            # chat is also hidden so the user gets some visible feedback.
            if hasattr(self.display, '_force_face_stream') and not speaking_after_tools:
                chat_visible = self.display.toggles.get('chat', True)
                self.display._force_face_stream = not chat_visible
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
                        "- NEVER start with 'The user' or 'User'. Drop ALL subjects. "
                        "Examples: 'likes cheese' (correct), 'The user likes cheese' (WRONG), "
                        "'identifies as a marxist' (correct), 'The user identifies as a marxist' (WRONG).\n"
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
                        fact = entry.strip()
                        # Strip "The user" / "User" prefix if model ignores instructions
                        for prefix in ("The user ", "the user ", "User ", "user "):
                            if fact.startswith(prefix):
                                fact = fact[len(prefix):]
                                break
                        clean_facts.append(fact)
                if clean_facts:
                    self.settings.append_memories(profile, clean_facts)
                    self._obs("lite", f"Memories stored: {clean_facts}")
                    self.display.show_log("Memory saved")
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
        self._set_speaking(True)
        self.display.update_face_state(self.state, self._get_speaking())

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
        return not self._get_speaking()

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
                self._set_speaking(False)
                self.display.update_face_state(self.state, self._get_speaking())
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
                if self._get_speaking():
                    self.tts_engine.stop()
                    self._set_speaking(False)
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
