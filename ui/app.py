"""
Zeina Kivy Application - main window, keyboard handling, wires everything together.

Split-out collaborators:
  ui/menu.py            floating "..." dropdown menu
  ui/model_selector.py  Ctrl+M model picker popup
  ui/ui_control.py      control_self action handler (bot drives its own UI)
"""
from __future__ import annotations

import os
import sys
import threading
from typing import Optional

import sounddevice as sd
from kivy.app import App
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.anchorlayout import AnchorLayout
from kivy.clock import Clock

from zeina import config
from zeina.enums import InteractionMode, RecordingState
from zeina.settings import Settings

from ui.widgets.face_widget import FaceWidget
from ui.widgets.status_widget import StatusWidget
from ui.widgets.chat_widget import ChatWidget
from ui.widgets.settings import SettingsScreen
from ui.widgets.diagnostics_widget import DiagnosticsWidget
from ui.kivy_display import KivyDisplay
from ui.menu import DropdownMenu
from ui.model_selector import show_model_selector
from ui.themes import ThemeManager
from ui.ui_control import UIControlHandler
from ui.icons import register_icon_font, register_mono_font, icon

from kivy.uix.button import Button


class ZeinaApp(App):
    """Main Kivy application for Zeina AI Assistant."""

    def build(self):
        self.title = "Zeina AI Assistant"
        self.icon = "assets/zeina_icon.png"
        Window.size = (600, 600)
        Window.clearcolor = (0.06, 0.06, 0.08, 1)

        self._assistant = None
        self._stream: Optional[sd.InputStream] = None
        self._tts_muted = False
        self._chat_visible = False
        self._status_visible = True   # Status bar visibility (toggled by eye button)
        self._chat_loop_id = 0        # Incremented each time a new chat loop starts
        self._quitting = False        # Guard against re-entrant shutdown

        # Register icon font
        self._has_icons = register_icon_font()
        register_mono_font()

        # Initialize settings and apply to config
        self._settings = Settings()
        self._settings.apply_to_config()
        self._theme_manager = ThemeManager()

        # Get bot name from settings
        self._bot_name = self._settings.get("bot_name", "Zeina")

        # Float layout so we can overlay floating buttons
        wrapper = FloatLayout()

        # Root layout with generous padding
        root = BoxLayout(
            orientation='vertical',
            spacing=10,
            padding=[16, 12, 16, 16],
            size_hint=(1, 1),
        )

        # Face widget (top, takes available space)
        self._face = FaceWidget(size_hint_y=1)
        root.add_widget(self._face)

        # Status bar
        self._status = StatusWidget()
        root.add_widget(self._status)

        # Chat widget (bottom)
        self._chat = ChatWidget(size_hint_y=1.2)
        root.add_widget(self._chat)

        wrapper.add_widget(root)

        # Floating "..." menu button (top-right)
        menu_icon = icon("dots_vertical", "...")
        self._menu_btn = Button(
            text=menu_icon,
            font_name="Icons" if self._has_icons else "Roboto",
            font_size='22sp' if self._has_icons else '20sp',
            size_hint=(None, None),
            size=(44, 44),
            background_normal='atlas://data/images/defaulttheme/button',
            background_color=(0.2, 0.2, 0.24, 0.7),
            color=(0.7, 0.75, 0.8, 0.9),
        )
        self._menu = DropdownMenu(self)
        self._menu_btn.bind(on_release=lambda trigger: self._menu.open(trigger))

        # Wrap in AnchorLayout with 20px padding
        self._menu_container = AnchorLayout(
            anchor_x='right',
            anchor_y='top',
            padding=[20, 20, 20, 20]
        )
        self._menu_container.add_widget(self._menu_btn)
        wrapper.add_widget(self._menu_container)

        # Settings screen overlay (hidden initially)
        self._settings_screen = SettingsScreen(
            settings=self._settings, app=self, face_widget=self._face,
            size_hint=(1, 1),
        )
        self._settings_screen.opacity = 0
        self._settings_screen.disabled = True
        wrapper.add_widget(self._settings_screen)

        # Diagnostics overlay (hidden initially)
        self._diagnostics = DiagnosticsWidget(size_hint=(1, 1))
        self._diagnostics.opacity = 0
        self._diagnostics.disabled = True
        wrapper.add_widget(self._diagnostics)

        # Build the KivyDisplay bridge
        self._kivy_display = KivyDisplay(self._face, self._status, self._chat)

        # Handler for the control_self tool (bot drives its own UI)
        self._ui_control = UIControlHandler(self)

        # Sync initial toggle state — KivyDisplay defaults don't match actual startup state
        self._kivy_display.toggles['chat'] = self._chat_visible      # False at start
        self._kivy_display.toggles['speaking'] = not self._tts_muted  # True at start

        # Boot into clean mode: face + status, no chat stream
        self._chat.hide_input()
        self._chat.set_stream_visible(False)

        # Apply theme from settings
        theme_name = self._settings.get("theme", "default")
        self._theme_manager.apply(self, theme_name)

        # Apply animation theme from settings
        anim_theme = self._settings.get("animation_theme", "vector")
        self._face.set_animation_theme(anim_theme)
        self._adjust_face_size(anim_theme)

        # Set bot name on status bar (right side shows bot name only)
        self._status.set_model(self._bot_name)

        # Apply saved status bar component visibility
        self._apply_status_bar_settings()

        # Restore persisted UI toggle states
        self._restore_ui_toggles()

        # Keyboard handling
        Window.bind(on_key_down=self._on_key_down)

        # Wire up chat message callback for voice-mode inline chat
        self._chat.set_message_callback(self._on_chat_message)

        # Schedule assistant init after the window is ready
        Clock.schedule_once(self._init_assistant, 0.5)

        return wrapper

    # ── Status bar settings ────────────────────────────────────

    def _apply_status_bar_settings(self):
        """Apply per-element status bar visibility from settings."""
        self._status.set_mode_visible(
            self._settings.get("status_show_mode", True))
        self._status.set_model_visible(
            self._settings.get("status_show_botname", True))
        self._status.set_tool_log_enabled(
            self._settings.get("status_show_toollog", True))

    def _restore_ui_toggles(self):
        """Restore persisted menu toggle states (TTS, chat feed, status bar)."""
        # TTS muted
        saved_muted = self._settings.get("tts_muted", False)
        if saved_muted:
            self._tts_muted = True
            self._kivy_display.toggles['speaking'] = False
            self._face.set_mouth_visible(False)

        # Chat feed
        saved_chat = self._settings.get("chat_feed_visible", False)
        if saved_chat:
            self._chat_visible = True
            self._kivy_display.toggles['chat'] = True
            self._chat.set_stream_visible(True)

        # Status bar overall visibility
        saved_status = self._settings.get("status_bar_visible", True)
        if not saved_status:
            self._status_visible = False
            self._status.opacity = 0
            self._status.height = 0
            self._kivy_display.toggles['tool_log'] = False

    # ── Menu theme bridge (called by ThemeManager) ─────────────

    def apply_menu_theme(self, theme: dict):
        """Update dropdown menu backgrounds and icon colors to match the theme."""
        self._menu.apply_theme(theme)

    # ── Menu action callbacks ─────────────────────────────────

    def _toggle_status_bar(self):
        """Toggle the entire status bar visibility."""
        self._status_visible = not self._status_visible
        if self._status_visible:
            self._status.opacity = 1
            self._status.height = 62
        else:
            self._status.opacity = 0
            self._status.height = 0
        # Keep tool_log toggle in sync
        self._kivy_display.toggles['tool_log'] = self._status_visible
        self._settings.set("status_bar_visible", self._status_visible)

    def _toggle_chat_feed(self):
        """Toggle the chat message transcript visibility (not the input)."""
        self._chat_visible = not self._chat_visible
        self._kivy_display.toggles['chat'] = self._chat_visible
        self._settings.set("chat_feed_visible", self._chat_visible)

        if self._chat_visible:
            self._chat.set_stream_visible(True)
            # Only show input if currently in CHAT mode
            if self._assistant and self._assistant.mode == InteractionMode.CHAT:
                self._chat.show_input()
        else:
            self._chat.set_stream_visible(False)
            # Only hide input if not in CHAT mode (chat mode manages its own input)
            if not (self._assistant and self._assistant.mode == InteractionMode.CHAT):
                self._chat.hide_input()

    def _toggle_mute(self):
        """Toggle TTS mute on/off."""
        self._tts_muted = not self._tts_muted
        self._kivy_display.toggles['speaking'] = not self._tts_muted
        self._face.set_mouth_visible(not self._tts_muted)
        self._settings.set("tts_muted", self._tts_muted)

        if self._tts_muted and self._assistant and self._assistant.is_speaking:
            self._assistant.interrupt_speech()
            self._assistant.set_state(RecordingState.IDLE)

    def _open_settings(self):
        """Open the settings screen overlay."""
        self._menu.dismiss()
        Clock.schedule_once(lambda dt: self._settings_screen.show(), 0.05)

    # ── Assistant init ────────────────────────────────────────

    def _init_assistant(self, dt):
        """Initialize ZeinaAssistant on a background thread to avoid blocking the UI."""
        self._status.set_status("Initializing...", "cyan")

        def _do_init():
            try:
                from zeina.assistant import ZeinaAssistant
                self._assistant = ZeinaAssistant(
                    display=self._kivy_display,
                    settings=self._settings,
                )

                # Wire up UI control callback so the bot can change its own settings
                from zeina.tools import set_ui_control_callback
                set_ui_control_callback(self._ui_control.handle)

                # Start audio input stream
                self._stream = sd.InputStream(
                    samplerate=config.SAMPLE_RATE,
                    channels=config.CHANNELS,
                    callback=self._assistant.audio_recorder.audio_callback,
                )
                self._stream.start()

                Clock.schedule_once(lambda dt: self._status.set_status(
                    "Push to talk", "green"
                ), 0)

                # Restore saved interaction mode
                if self._settings.get("interaction_mode", "voice") == "chat":
                    Clock.schedule_once(lambda dt: self._toggle_mode(), 0.1)
            except Exception as e:
                err_msg = f"Init error: {e}"
                Clock.schedule_once(lambda dt: self._status.set_status(
                    err_msg, "red"
                ), 0)

        threading.Thread(target=_do_init, daemon=True).start()

    # ── Chat message handling ─────────────────────────────────

    def _on_chat_message(self, text):
        """Handle a message submitted via chat input while in voice mode."""
        if not self._assistant:
            return
        # Stop TTS if currently speaking
        self._assistant.interrupt_speech()
        self._assistant.set_state(RecordingState.IDLE)
        threading.Thread(
            target=self._assistant.handle_chat_input,
            args=(text,),
            daemon=True,
        ).start()

    # ── Keyboard handling ─────────────────────────────────────

    def _on_key_down(self, window, key, scancode, codepoint, modifiers):
        """Handle keyboard events from Kivy."""
        # ESC closes diagnostics or settings if open, otherwise quits
        if key == 27:
            if self._diagnostics.is_visible:
                self._diagnostics.hide()
                return True
            if self._settings_screen.is_visible:
                self._settings_screen.hide()
                return True
            if self._assistant is not None:
                self._quit()
            return True

        if self._assistant is None:
            return False

        # Don't handle keys when settings screen is open
        if self._settings_screen.is_visible:
            return False

        # TAB (key 9) - toggle mode
        if key == 9:
            self._toggle_mode()
            return True

        # Ctrl+M - change model
        if codepoint == 'm' and 'ctrl' in modifiers:
            show_model_selector(self)
            return True

        # Ctrl+D - toggle diagnostics panel
        if codepoint == 'd' and 'ctrl' in modifiers:
            self._toggle_diagnostics()
            return True

        # PTT key — configurable (default: spacebar)
        ptt_key = config.PUSH_TO_TALK_KEY
        is_ptt = (
            (ptt_key == "space" and key == 32)
            or (len(ptt_key) == 1 and codepoint == ptt_key)
        )
        if is_ptt:
            self._handle_spacebar()
            return True

        return False

    def _toggle_diagnostics(self):
        """Toggle the diagnostics overlay (Ctrl+D)."""
        if self._diagnostics.is_visible:
            self._diagnostics.hide()
        else:
            self._diagnostics.refresh(self._assistant)
            self._diagnostics.show()

    def _handle_spacebar(self):
        """Handle spacebar press for voice mode controls."""
        if not self._assistant:
            return
        if self._assistant.mode != InteractionMode.VOICE:
            return

        # Interrupt TTS if speaking
        if self._assistant.is_speaking:
            self._assistant.interrupt_speech()
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
        """Toggle between voice and chat mode.
        Chat input only appears in CHAT mode; the transcript follows _chat_visible."""
        if not self._assistant:
            return

        bot_name = self._settings.get("bot_name", "Zeina")

        with self._assistant.mode_lock:
            if self._assistant.mode == InteractionMode.VOICE:
                self._assistant._cleanup_voice_mode()
                self._assistant.mode = InteractionMode.CHAT
                self._kivy_display.show_menu_bar(InteractionMode.CHAT, bot_name)
                self._assistant.set_state(RecordingState.IDLE)
                self._settings.set("interaction_mode", "chat")

                def _enter_chat(dt):
                    # Only show the input — transcript visibility follows _chat_visible
                    self._chat.show_input()

                Clock.schedule_once(_enter_chat, 0)
                self._chat_loop_id += 1
                loop_id = self._chat_loop_id
                self._assistant.chat_input_thread = threading.Thread(
                    target=self._gui_chat_input_loop, args=(loop_id,), daemon=True
                )
                self._assistant.chat_input_thread.start()
            else:
                self._chat.cancel_input()
                self._assistant._cleanup_chat_mode()
                self._assistant.mode = InteractionMode.VOICE
                self._kivy_display.show_menu_bar(InteractionMode.VOICE, bot_name)
                self._assistant.set_state(RecordingState.IDLE)
                self._settings.set("interaction_mode", "voice")

                def _exit_chat(dt):
                    # Hide input but keep transcript visible if _chat_visible is on
                    self._chat.hide_input()

                Clock.schedule_once(_exit_chat, 0)

    def _gui_chat_input_loop(self, loop_id: int):
        """Chat input loop for GUI mode, using KivyDisplay.get_chat_input.

        loop_id is a generation counter — if a newer loop has started (i.e.
        _chat_loop_id > loop_id) this loop exits rather than entering
        get_chat_input() again, preventing stale threads from competing for
        the same input event and causing double-sends.
        """
        while self._assistant and self._assistant.mode == InteractionMode.CHAT:
            # Bail out if a newer loop has taken over
            if loop_id != self._chat_loop_id:
                break
            try:
                user_input = self._kivy_display.get_chat_input("Enter message...")
                if user_input is None:
                    break
                if not user_input.strip():
                    continue
                if self._assistant.mode != InteractionMode.CHAT:
                    break
                self._assistant.handle_chat_input(user_input)
            except (RuntimeError, AttributeError):
                # Mode switched or assistant was cleaned up
                break
            except Exception as e:
                # Log unexpected errors but keep the loop alive
                print(f"Error in chat input loop: {e}", file=sys.stderr)
                import traceback
                traceback.print_exc()
                break

    # ── Face size adjustment ──────────────────────────────────

    def _adjust_face_size(self, anim_name: str):
        """Give the face more vertical space for text-based animation styles."""
        if anim_name == "ascii":
            self._face.size_hint_y = 2.2
        else:
            self._face.size_hint_y = 1.0

    # ── Shutdown ──────────────────────────────────────────────

    def _quit(self):
        """Clean shutdown — bounded cleanup, then stop the Kivy loop."""
        self._shutdown()
        self.stop()

    def _shutdown(self):
        """Run cleanup exactly once (guards against _quit → stop → on_stop re-entry).

        All audio teardown happens on a watchdog thread with a hard deadline.
        Stopping the sounddevice stream while pygame TTS output is still live
        on the same CoreAudio device can deadlock inside AudioOutputUnitStop —
        the old code did exactly that on the main thread and froze the app.
        Order matters: close TTS → quit the mixer → only then stop the mic
        stream. If native audio code wedges anyway, we force-exit rather than
        leave a zombie window.
        """
        if self._quitting:
            return
        self._quitting = True

        # Instant feedback: the window disappears even if cleanup takes a moment.
        try:
            Window.hide()
        except Exception:
            pass

        assistant, stream = self._assistant, self._stream
        done = threading.Event()

        def _cleanup():
            # 1. Stop speech and block any new TTS playback.
            if assistant:
                try:
                    assistant.prepare_shutdown()
                except Exception:
                    pass
            # 2. Close the pygame/SDL output device entirely.
            try:
                import pygame
                pygame.mixer.quit()
            except Exception:
                pass
            # 3. Mic stream is now the only audio client — safe to stop.
            if stream:
                try:
                    stream.abort()
                    stream.close()
                except Exception:
                    pass
            # 4. Bounded grace period for in-flight memory extraction writes.
            if assistant:
                try:
                    assistant.wait_for_background_work()
                except Exception:
                    pass
            done.set()

        threading.Thread(target=_cleanup, daemon=True, name="shutdown-cleanup").start()
        # prepare_shutdown (≤2s) + mixer/stream + memory join (≤8s) fit in 12s.
        if not done.wait(timeout=12.0):
            os._exit(0)

    def on_stop(self):
        """Called when the app is closing (window X button or stop())."""
        self._shutdown()
