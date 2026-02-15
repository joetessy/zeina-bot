"""
Zeina Kivy Application - main window, keyboard handling, wires everything together.
"""
import sys
import threading
import time

import sounddevice as sd
from kivy.app import App
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.popup import Popup
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle

from zeina import config
from zeina.enums import InteractionMode, RecordingState

from ui.widgets.face_widget import FaceWidget
from ui.widgets.status_widget import StatusWidget
from ui.widgets.chat_widget import ChatWidget
from ui.widgets.toggle_panel import TogglePanel
from ui.kivy_display import KivyDisplay


class ZeinaApp(App):
    """Main Kivy application for Zeina AI Assistant."""

    def build(self):
        self.title = "Zeina AI Assistant"
        Window.size = (600, 600)
        Window.clearcolor = (0.06, 0.06, 0.08, 1)

        self._assistant = None
        self._stream = None
        self._panel_visible = True

        # Float layout so we can overlay the settings button
        wrapper = FloatLayout()

        # Root layout with generous padding
        root = BoxLayout(
            orientation='vertical',
            spacing=6,
            padding=[16, 12, 16, 16],
            size_hint=(1, 1),
        )

        # Face widget (top, takes available space)
        self._face = FaceWidget(size_hint_y=1)
        root.add_widget(self._face)

        # Status bar
        self._status = StatusWidget()
        root.add_widget(self._status)

        # Toggle panel (collapsible)
        self._toggle_panel = TogglePanel(on_toggle_changed=self._on_toggle_changed)
        root.add_widget(self._toggle_panel)

        # Chat widget (bottom)
        self._chat = ChatWidget(size_hint_y=1.2)
        root.add_widget(self._chat)

        wrapper.add_widget(root)

        # Small floating settings button (always visible, bottom-right corner)
        self._settings_btn = Button(
            text="...",
            font_size='20sp',
            size_hint=(None, None),
            size=(40, 40),
            pos_hint={'right': 0.98, 'top': 0.99},
            background_normal='atlas://data/images/defaulttheme/button',
            background_color=(0.2, 0.2, 0.24, 0.7),
            color=(0.7, 0.75, 0.8, 0.9),
        )
        self._settings_btn.bind(on_release=self._toggle_settings_panel)
        wrapper.add_widget(self._settings_btn)

        # Build the KivyDisplay bridge
        self._kivy_display = KivyDisplay(self._face, self._status, self._chat)

        # Boot into clean mode: face + status + tool log, no chat stream
        self._toggle_panel.apply_preset("clean")
        self._panel_visible = False
        self._toggle_panel.opacity = 0
        self._toggle_panel.height = 0
        self._toggle_panel.disabled = True
        self._chat.hide_input()

        # Keyboard handling
        Window.bind(on_key_down=self._on_key_down)

        # Wire up chat message callback for voice-mode inline chat
        self._chat.set_message_callback(self._on_chat_message)

        # Schedule assistant init after the window is ready
        Clock.schedule_once(self._init_assistant, 0.5)

        return wrapper

    def _toggle_settings_panel(self, *args):
        """Show/hide the toggle panel."""
        self._panel_visible = not self._panel_visible
        if self._panel_visible:
            self._toggle_panel.opacity = 1
            self._toggle_panel.height = 40
            self._toggle_panel.disabled = False
            self._settings_btn.color = (0.7, 0.75, 0.8, 0.9)
        else:
            self._toggle_panel.opacity = 0
            self._toggle_panel.height = 0
            self._toggle_panel.disabled = True
            self._settings_btn.color = (0.5, 0.5, 0.55, 0.6)

    def _on_toggle_changed(self, key, is_on):
        """Handle toggle button state changes."""
        self._kivy_display.toggles[key] = is_on

        if key == "speaking":
            if not is_on and self._assistant and self._assistant.is_speaking:
                self._assistant.tts_engine.stop()
                self._assistant.is_speaking = False
                self._assistant.set_state(RecordingState.IDLE)
        elif key == "face":
            Clock.schedule_once(lambda dt: self._set_face_visibility(is_on), 0)
        elif key == "status":
            Clock.schedule_once(lambda dt: self._set_status_visibility(is_on), 0)
        elif key == "chat":
            Clock.schedule_once(lambda dt: self._set_chat_visibility(is_on), 0)
            if is_on:
                Clock.schedule_once(lambda dt: self._chat.show_input(), 0)
            else:
                Clock.schedule_once(lambda dt: self._chat.hide_input(), 0)

    def _set_face_visibility(self, visible):
        if visible:
            self._face.opacity = 1
            self._face.size_hint_y = 1
        else:
            self._face.opacity = 0
            self._face.size_hint_y = 0.001

    def _set_status_visibility(self, visible):
        if visible:
            self._status.opacity = 1
            self._status.height = 52
        else:
            self._status.opacity = 0
            self._status.height = 0

    def _set_chat_visibility(self, visible):
        """Toggle only the message stream, not the text input."""
        self._chat.set_stream_visible(visible)

    def _init_assistant(self, dt):
        """Initialize ZeinaAssistant on a background thread to avoid blocking the UI."""
        self._status.set_status("Initializing...", "cyan")

        def _do_init():
            try:
                from zeina.assistant import ZeinaAssistant
                self._assistant = ZeinaAssistant(display=self._kivy_display)

                # Start audio input stream
                self._stream = sd.InputStream(
                    samplerate=config.SAMPLE_RATE,
                    channels=config.CHANNELS,
                    callback=self._assistant.audio_recorder.audio_callback,
                )
                self._stream.start()

                Clock.schedule_once(lambda dt: self._status.set_status(
                    "Press SPACE to talk", "green"
                ), 0)
            except Exception as e:
                err_msg = f"Init error: {e}"
                Clock.schedule_once(lambda dt: self._status.set_status(
                    err_msg, "red"
                ), 0)

        threading.Thread(target=_do_init, daemon=True).start()

    def _on_chat_message(self, text):
        """Handle a message submitted via chat input while in voice mode."""
        if not self._assistant:
            return
        # Stop TTS if currently speaking
        if self._assistant.is_speaking:
            self._assistant.tts_engine.stop()
            self._assistant.is_speaking = False
        self._assistant.set_state(RecordingState.IDLE)
        threading.Thread(
            target=self._assistant.handle_chat_input,
            args=(text,),
            daemon=True,
        ).start()

    def _on_key_down(self, window, key, scancode, codepoint, modifiers):
        """Handle keyboard events from Kivy."""
        if self._assistant is None:
            return False

        # ESC (key 27) - quit
        if key == 27:
            self._quit()
            return True

        # TAB (key 9) - toggle mode
        if key == 9:
            self._toggle_mode()
            return True

        # Ctrl+M - change model
        if codepoint == 'm' and 'ctrl' in modifiers:
            self._show_model_selector()
            return True

        # SPACEBAR (key 32) - voice controls
        if key == 32:
            self._handle_spacebar()
            return True

        return False

    def _handle_spacebar(self):
        """Handle spacebar press for voice mode controls."""
        if not self._assistant:
            return
        if self._assistant.mode != InteractionMode.VOICE:
            return

        # Interrupt TTS if speaking
        if self._assistant.is_speaking:
            self._assistant.tts_engine.stop()
            self._assistant.is_speaking = False
            self._assistant.set_state(RecordingState.IDLE)
            self._assistant.start_listening(mode="interrupt")
            return

        # Start listening if idle
        if self._assistant.state == RecordingState.IDLE:
            self._assistant.start_listening(mode="manual")
            return

        # Stop and process if currently listening
        if self._assistant.state == RecordingState.LISTENING:
            self._assistant.set_state(RecordingState.PROCESSING)
            threading.Thread(
                target=self._assistant.process_audio_pipeline,
                daemon=True,
            ).start()

    def _toggle_mode(self):
        """Toggle between voice and chat mode (only shows/hides chat input)."""
        if not self._assistant:
            return

        with self._assistant.mode_lock:
            if self._assistant.mode == InteractionMode.VOICE:
                self._assistant._cleanup_voice_mode()
                self._assistant.mode = InteractionMode.CHAT
                self._kivy_display.show_menu_bar(InteractionMode.CHAT, "Zeina")
                self._assistant.set_state(RecordingState.IDLE)
                def _enter_chat(dt):
                    self._chat.show_input()
                Clock.schedule_once(_enter_chat, 0)
                self._assistant.chat_input_thread = threading.Thread(
                    target=self._gui_chat_input_loop, daemon=True
                )
                self._assistant.chat_input_thread.start()
            else:
                self._chat.cancel_input()
                self._assistant._cleanup_chat_mode()
                self._assistant.mode = InteractionMode.VOICE
                self._kivy_display.show_menu_bar(InteractionMode.VOICE, "Zeina")
                self._assistant.set_state(RecordingState.IDLE)
                def _exit_chat(dt):
                    self._chat.hide_input()
                Clock.schedule_once(_exit_chat, 0)

    def _gui_chat_input_loop(self):
        """Chat input loop for GUI mode, using KivyDisplay.get_chat_input."""
        while self._assistant and self._assistant.mode == InteractionMode.CHAT:
            try:
                user_input = self._kivy_display.get_chat_input("Type a message...")
                if user_input is None:
                    break
                if not user_input.strip():
                    continue
                if self._assistant.mode != InteractionMode.CHAT:
                    break
                self._assistant.handle_chat_input(user_input)
            except (RuntimeError, AttributeError) as e:
                # Mode switched or assistant was cleaned up
                break
            except Exception as e:
                # Log unexpected errors but keep the loop alive
                print(f"Error in chat input loop: {e}", file=sys.stderr)
                import traceback
                traceback.print_exc()
                break

    def _show_model_selector(self):
        """Show a Kivy Popup for model selection."""
        try:
            import ollama
            models_response = ollama.list()
            models = models_response.models
        except Exception as e:
            self._status.set_status(f"Error listing models: {e}", "red")
            return

        if not models:
            self._status.set_status("No models found", "red")
            return

        content = BoxLayout(orientation='vertical', spacing=10, padding=[16, 12])

        # Title
        title_label = Label(
            text="Select Model",
            font_size='16sp',
            size_hint_y=None,
            height=30,
            color=(0.85, 0.88, 0.92, 1),
            bold=True,
        )
        content.add_widget(title_label)

        scroll = ScrollView(do_scroll_x=False)
        model_list = BoxLayout(
            orientation='vertical',
            size_hint_y=None,
            spacing=8,
            padding=[4, 4],
        )
        model_list.bind(minimum_height=model_list.setter('height'))

        popup = Popup(
            title="",
            separator_height=0,
            size_hint=(0.85, 0.65),
            background_color=(0.1, 0.1, 0.12, 0.98),
        )

        def select_model(model_name):
            if model_name != config.OLLAMA_MODEL:
                config.OLLAMA_MODEL = model_name
                self._kivy_display.show_menu_bar(self._assistant.mode, "Zeina")
            popup.dismiss()

        for model in models:
            name = model.model
            is_current = name == config.OLLAMA_MODEL
            btn = Button(
                text=f"> {name}" if is_current else f"  {name}",
                size_hint_y=None,
                height=48,
                font_size='14sp',
                background_normal='atlas://data/images/defaulttheme/button',
                background_color=(0.18, 0.52, 0.46, 1) if is_current else (0.15, 0.16, 0.2, 1),
                color=(1, 1, 1, 0.95),
            )
            btn.bind(on_release=lambda x, n=name: select_model(n))
            model_list.add_widget(btn)

        scroll.add_widget(model_list)
        content.add_widget(scroll)

        cancel_btn = Button(
            text="Cancel",
            size_hint_y=None,
            height=44,
            font_size='14sp',
            background_normal='atlas://data/images/defaulttheme/button',
            background_color=(0.22, 0.22, 0.26, 1),
            color=(0.7, 0.7, 0.75, 1),
        )
        cancel_btn.bind(on_release=lambda x: popup.dismiss())
        content.add_widget(cancel_btn)

        popup.content = content
        popup.open()

    def _quit(self):
        """Clean shutdown."""
        if self._assistant:
            self._assistant._save_conversation()
        if self._stream:
            self._stream.stop()
            self._stream.close()
        self.stop()

    def on_stop(self):
        """Called when the app is closing."""
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except (AttributeError, RuntimeError) as e:
                # Stream already closed or invalid
                pass
