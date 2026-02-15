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
from typing import Optional
from datetime import datetime
import json
import torch
import readline  # Provides robust line editing
from collections import deque

from zeina import config
from zeina.enums import InteractionMode, RecordingState
from zeina.display import Display
from zeina.audio import AudioRecorder
from zeina.tts import TTSEngine
from zeina.tools import tool_manager


class ZeinaAssistant:
    """Main assistant orchestrator"""

    # Status message constants
    VOICE_MODE_READY_STATUS = "Press SPACE to talk"
    CHAT_MODE_READY_STATUS = "Type your message"
    PROCESSING_STATUS = "Processing..."
    SPEAKING_STATUS = "Speaking... (press SPACE to interrupt)"
    CHAT_SPEAKING_STATUS = "Speaking..."

    def __init__(self, display=None):
        # Initialize display first (but don't show anything yet)
        self.display = display or Display()

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

        # Initialize conversation memory
        self.conversation_history = [
            {"role": "system", "content": config.SYSTEM_PROMPT}
        ]

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
        self.display.show_menu_bar(self.mode, config.OLLAMA_MODEL)

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
        """Save conversation history to file"""
        if not config.SAVE_CONVERSATION_HISTORY:
            return

        # Create conversations directory if it doesn't exist
        os.makedirs(config.CONVERSATIONS_DIR, exist_ok=True)

        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(config.CONVERSATIONS_DIR, f"conversation_{timestamp}.json")

        # Save conversation history
        try:
            with open(filename, 'w') as f:
                json.dump({
                    "timestamp": datetime.now().isoformat(),
                    "model": config.OLLAMA_MODEL,
                    "messages": self.conversation_history
                }, f, indent=2)
            print(f"💾 Conversation saved to {filename}")
        except Exception as e:
            print(f"⚠️  Failed to save conversation: {e}")

    def _log_event(self, message: str):
        """Record a short event for observability"""
        timestamp = time.strftime("%H:%M:%S")
        self.event_log.append(f"{timestamp} {message}")

    def _log_api(self, message: str):
        """Log an API event to the display's tool log (not chat bubbles)."""
        self._log_event(message)
        if hasattr(self.display, 'show_log'):
            self.display.show_log(message)

    def _handle_auto_stop(self, reason: str):
        """Called when VAD detects silence or timeout"""
        if self.state == RecordingState.LISTENING:
            if reason == "silence":
                self._log_event("Auto-stop (silence)")
                # User stopped speaking - process the recording
                self.set_state(RecordingState.PROCESSING, "Auto-stopped", "green")
                threading.Thread(
                    target=self.process_audio_pipeline,
                    daemon=True
                ).start()
            elif reason == "timeout":
                self._log_event("Auto-stop (timeout)")
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
                self.display.show_menu_bar(self.mode, config.OLLAMA_MODEL)
                self.set_state(RecordingState.IDLE)
                self.display.start_face_display(clear_screen=False)
                time.sleep(0.2)
                self.chat_input_thread = threading.Thread(target=self._chat_input_loop, daemon=True)
                self.chat_input_thread.start()
            else:
                # Switch to VOICE mode
                self._cleanup_chat_mode()
                self.mode = InteractionMode.VOICE
                self.display.show_menu_bar(self.mode, config.OLLAMA_MODEL)
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
            self.display.show_menu_bar(self.mode, config.OLLAMA_MODEL)
            # Restart face animation and UI
            self.display.start_face_display()
            # Show appropriate prompt based on mode
            time.sleep(0.1)  # Let face render
            if was_chat_mode:
                self.mode = InteractionMode.CHAT
                self.display.show_menu_bar(self.mode, config.OLLAMA_MODEL)
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
            # Show what user said in a panel
            self.display.show_user_message(user_message)

            # Show processing status in chat mode
            self.set_state(RecordingState.PROCESSING, self.PROCESSING_STATUS, "magenta")

            # Get LLM response
            assistant_response = self._get_llm_response(user_message, show_detail=False)

            # Show assistant response in the feed
            self.display.show_assistant_message(assistant_response)

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

            self._log_event(f"Listening started ({mode})")
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
        """
        tool_names = list(tool_manager.tools.keys())
        tool_list = ", ".join(tool_names)

        classifier_model = getattr(config, 'INTENT_CLASSIFIER_MODEL', config.OLLAMA_MODEL)
        response = ollama.chat(
            model=classifier_model,
            messages=[{
                "role": "user",
                "content": (
                    f"You are a router. Given the user message below, decide which tool "
                    f"is needed. Available tools: {tool_list}\n"
                    f"Rules:\n"
                    f"- web_search: ONLY if the user explicitly asks to search/look something up, "
                    f"or needs real-time data (live news, scores, prices). "
                    f"Do NOT pick this for general knowledge, greetings, opinions, feelings, "
                    f"personal questions, weather, or conversation about prior messages.\n"
                    f"- get_weather: ONLY if the user asks about weather, temperature, or "
                    f"forecast for a specific location.\n"
                    f"- get_current_time: ONLY if the user asks for the current time or date.\n"
                    f"- calculate: ONLY if the user asks to compute a math expression.\n"
                    f"- get_location: ONLY if the user asks where they are or their current location.\n"
                    f"- none: For everything else. When in doubt, pick none.\n\n"
                    f"User message: \"{message}\"\n\n"
                    f"Reply with ONLY the tool name or \"none\". Nothing else."
                )
            }],
            options={"temperature": 0}
        )
        result = response['message'].get('content', 'none').strip().lower()
        self._log_event(f"Intent [{classifier_model}]: {result}")
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
        return {}

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
        self._log_event(f"Location: {location}")
        return location if location else message

    def _get_llm_response(self, user_message: str, show_detail: bool = True) -> str:
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

        # Trim conversation history if it exceeds max length
        if config.MAX_CONVERSATION_LENGTH > 0:
            # Keep system prompt + last N messages
            if len(self.conversation_history) > config.MAX_CONVERSATION_LENGTH + 1:
                self.conversation_history = [self.conversation_history[0]] + \
                    self.conversation_history[-(config.MAX_CONVERSATION_LENGTH):]

        # Step 1: Classify whether a tool is needed (separate fast LLM call)
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
            result_preview = tool_result[:80] + "..." if len(tool_result) > 80 else tool_result
            self._log_event(f"Tool result: {result_preview}")

            # Inject tool result as a follow-up user message so the LLM
            # treats it as context it must respond to directly.
            self.conversation_history.append({
                "role": "user",
                "content": f"[DATA] {tool_result}\n\nUsing the data above, answer my previous question naturally and concisely."
            })

        # Step 3: Get the final response (never pass tools schema to avoid leaking)
        msg_count = len(self.conversation_history)
        self._log_event(f"LLM [{config.OLLAMA_MODEL}] ({msg_count} msgs)")
        response = ollama.chat(
            model=config.OLLAMA_MODEL,
            messages=self.conversation_history
        )
        assistant_message = response['message']
        content = assistant_message.get('content', '').strip()

        # Guard against empty responses - retry once without tool context
        if not content and tool_needed != "none":
            self._log_event("Empty response after tool - retrying without tool context")
            # Remove the injected tool context and retry
            self.conversation_history = [
                m for m in self.conversation_history
                if not (m.get('role') == 'user'
                        and '[DATA]' in m.get('content', ''))
            ]
            response = ollama.chat(
                model=config.OLLAMA_MODEL,
                messages=self.conversation_history
            )
            assistant_message = response['message']
            content = assistant_message.get('content', '').strip()

        if not content:
            content = "Sorry, I didn't quite get that. Could you try again?"

        self.conversation_history.append(assistant_message)
        self._log_event(f"Response: {len(content)} chars")

        return content

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
            temp_audio_file = "temp_recording.wav"
            self._save_audio_to_file(audio_data, temp_audio_file)

            # Transcribe
            transcription = self._transcribe_audio(temp_audio_file)
            if not transcription:
                self.set_state(RecordingState.IDLE)
                return

            preview = transcription[:50] + "..." if len(transcription) > 50 else transcription
            self._log_event(f"Transcribed: {preview}")

            # Show what user said
            self.display.show_user_message(transcription)

            # Show processing status in voice mode
            self.set_state(RecordingState.PROCESSING, self.PROCESSING_STATUS, "magenta")

            # Get LLM response
            assistant_response = self._get_llm_response(transcription)

            # Show assistant response
            self.display.show_assistant_message(assistant_response)

            # Speak response if the speaking toggle is on (independent of mode)
            speaking_enabled = getattr(self.display, 'toggles', {}).get('speaking', True)
            if speaking_enabled and assistant_response.strip():
                # Speak response
                self.display.show_status_centered(self.SPEAKING_STATUS, "blue")
                self.is_speaking = True
                self.display.update_face_state(self.state, self.is_speaking)
                self.tts_engine.speak(assistant_response)
                self.is_speaking = False
                self.display.update_face_state(self.state, self.is_speaking)

            # Reset state after response (do not override active listening)
            # Check state without holding lock to avoid deadlock with set_state
            if self.state != RecordingState.LISTENING and not self.audio_recorder.is_recording:
                self.set_state(RecordingState.IDLE)

            # Auto-listen for follow-up question (only in voice mode)
            if self.mode == InteractionMode.VOICE and not self.audio_recorder.is_recording:
                print()  # Blank line
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
