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
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.popup import Popup
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.dropdown import DropDown
from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle

from zeina import config
from zeina.enums import InteractionMode, RecordingState
from zeina.settings import Settings

from ui.widgets.face_widget import FaceWidget
from ui.widgets.status_widget import StatusWidget
from ui.widgets.chat_widget import ChatWidget
from ui.widgets.settings_screen import SettingsScreen
from ui.widgets.diagnostics_widget import DiagnosticsWidget
from ui.kivy_display import KivyDisplay
from ui.themes import ThemeManager
from ui.icons import register_icon_font, register_mono_font, icon, ICONS


class ZeinaApp(App):
    """Main Kivy application for Zeina AI Assistant."""

    def build(self):
        self.title = "Zeina AI Assistant"
        self.icon = "assets/zeina_icon.png"
        Window.size = (600, 600)
        Window.clearcolor = (0.06, 0.06, 0.08, 1)

        self._assistant = None
        self._stream = None
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
        self._menu_btn.bind(on_release=self._open_menu)

        # Wrap in AnchorLayout with 20px padding
        self._menu_container = AnchorLayout(
            anchor_x='right',
            anchor_y='top',
            padding=[20, 20, 20, 20]
        )
        self._menu_container.add_widget(self._menu_btn)
        wrapper.add_widget(self._menu_container)

        # Build the dropdown menu
        self._build_menu()

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

    # ── Dropdown menu ─────────────────────────────────────────

    def _build_menu(self):
        """Build the icon-only dropdown menu."""
        self._dropdown = DropDown(auto_width=False, width=56)
        self._menu_items = {}
        self._menu_bg_colors = {}  # Color instruction per button for theme updates

        theme = self._theme_manager.current_theme
        bg = theme.get("chat_input_bg", (0.10, 0.11, 0.14, 0.98))
        on_color = theme.get("face_sparkle", (0.55, 0.85, 0.75, 1))

        # (key, icon_name, fallback, callback, icon_size)
        items = [
            ("tools",    "monitor",     "[T]", self._toggle_status_bar, '22sp'),
            ("chat",     "chat",        "[C]", self._toggle_chat_feed,  '22sp'),
            ("audio",    "volume_high", "[V]", self._toggle_mute,       '22sp'),
            ("settings", "cog",         "[S]", self._open_settings,     '26sp'),
        ]

        for key, icon_name, fallback, callback, icon_size in items:
            icon_char = icon(icon_name, fallback)
            btn = Button(
                text=icon_char,
                font_name="Icons" if self._has_icons else "Roboto",
                font_size=icon_size if self._has_icons else '13sp',
                size_hint_y=None,
                height=50,
                background_normal='',
                background_color=(0, 0, 0, 0),
                color=on_color,
                halign='center',
                valign='middle',
            )

            with btn.canvas.before:
                color_instr = Color(*bg)
                self._menu_bg_colors[key] = color_instr
                btn._bg_rect = RoundedRectangle(pos=btn.pos, size=btn.size, radius=[4])
            btn.bind(
                pos=lambda inst, v: setattr(inst._bg_rect, 'pos', v),
                size=lambda inst, v: setattr(inst._bg_rect, 'size', v),
            )

            def _on_press(instance, cb=callback, k=key):
                cb()
                # Update icon colors in place — do NOT dismiss the dropdown
                Clock.schedule_once(lambda dt: self._update_menu_status(), 0)

            btn.bind(on_release=_on_press)
            btn._menu_key = key
            btn._icon_name = icon_name
            self._menu_items[key] = btn
            self._dropdown.add_widget(btn)

    def _open_menu(self, trigger):
        """Open the dropdown menu, updating status indicators first."""
        self._update_menu_status()
        self._dropdown.open(trigger)

    def _update_menu_status(self):
        """Update icon colors to reflect current toggle states."""
        theme = self._theme_manager.current_theme
        ON_COLOR = theme.get("face_sparkle", (0.55, 0.85, 0.75, 1))
        OFF_COLOR = theme.get("toggle_off_text", (0.5, 0.4, 0.4, 0.6))
        MUTE_COLOR = (0.9, 0.4, 0.4, 0.9)

        for key, btn in self._menu_items.items():
            if key == "tools":
                btn.color = ON_COLOR if self._status_visible else OFF_COLOR
                if self._has_icons:
                    btn.text = icon("monitor")
            elif key == "chat":
                btn.color = ON_COLOR if self._chat_visible else OFF_COLOR
            elif key == "audio":
                muted = self._tts_muted
                btn.color = MUTE_COLOR if muted else ON_COLOR
                if self._has_icons:
                    btn.text = icon("volume_off") if muted else icon("volume_high")
            elif key == "settings":
                btn.color = ON_COLOR

    def apply_menu_theme(self, theme: dict):
        """Update dropdown menu backgrounds and icon colors to match the theme."""
        bg = theme.get("chat_input_bg", (0.10, 0.11, 0.14, 0.98))
        for color_instr in self._menu_bg_colors.values():
            color_instr.rgba = bg
        self._update_menu_status()

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
            self._assistant.tts_engine.stop()
            self._assistant.is_speaking = False
            self._assistant.set_state(RecordingState.IDLE)

    def _open_settings(self):
        """Open the settings screen overlay."""
        self._dropdown.dismiss()
        Clock.schedule_once(lambda dt: self._settings_screen.show(), 0.05)

    # ── Bot self-control callback ──────────────────────────────

    def _handle_ui_control(self, action: str, value: str = "") -> str:
        """Invoked by the control_self tool to change app UI/settings.

        Called from a background thread — all Kivy mutations are
        scheduled onto the main thread via Clock.schedule_once.
        Returns a human-readable result string for the LLM to relay.
        """
        value = (value or "").strip()
        v = value.lower()

        # ── Fuzzy value normalizers ───────────────────────────
        def _theme():
            for t in ("midnight", "terminal", "sunset", "default"):
                if t in v:
                    return t
            return None

        def _anim():
            if "ascii" in v:
                return "ascii"
            if "vector" in v or "bmo" in v:
                return "vector"
            if v == "toggle":
                current = self._settings.get("animation_theme", "vector")
                return "ascii" if current == "vector" else "vector"
            return None

        def _want_show():
            """Returns True=show, False=hide, None=unknown."""
            if any(w in v for w in ("show", "open", "on", "enable", "visible")):
                return True
            if any(w in v for w in ("hide", "close", "off", "disable", "hidden")):
                return False
            return None

        def _want_mute():
            """Returns True=mute, False=unmute, None=toggle."""
            if any(w in v for w in ("unmute", "enable", "on", "start")):
                return False
            if any(w in v for w in ("mute", "disable", "off", "stop", "silence")):
                return True
            return None

        def _want_mode():
            if "chat" in v or "text" in v or "type" in v:
                return "chat"
            if "voice" in v or "speak" in v or "talk" in v:
                return "voice"
            return None

        # ── Determine what actually changes ──────────────────
        theme     = _theme()
        anim      = _anim()
        mode      = _want_mode()
        show_bool = _want_show()
        mute_bool = _want_mute()

        # ── switch_profile: validate before scheduling ────────
        if action == "switch_profile":
            available = self._settings.list_profiles()
            target = value.lower().strip()
            match = next((p for p in available if p.lower() == target), None)
            if not match:
                match = next((p for p in available if target in p.lower()), None)
            if not match:
                return (f"Profile '{value}' not found. "
                        f"Available profiles: {', '.join(available)}.")

            def _do_switch(dt=None):
                self._settings.switch_profile(match)
                self._settings.apply_to_config()
                new = self._settings.get_all()
                self._theme_manager.apply(self, new.get("theme", "default"))
                bot = new.get("bot_name", "Zeina")
                self._bot_name = bot
                self._status.set_model(bot)
                if self._assistant:
                    self._kivy_display.show_menu_bar(self._assistant.mode, bot)

            Clock.schedule_once(_do_switch, 0)
            return f"Switched to profile '{match}'."

        def _run(dt=None):
            if action == "set_theme":
                if theme:
                    self._theme_manager.apply(self, theme)
                    self._settings.set("theme", theme)

            elif action == "set_animation":
                if anim:
                    self._face.set_animation_theme(anim)
                    self._adjust_face_size(anim)
                    self._settings.set("animation_theme", anim)

            elif action == "set_mode":
                target = mode
                if target and self._assistant:
                    if target == "voice" and self._assistant.mode == InteractionMode.CHAT:
                        self._toggle_mode()
                    elif target == "chat" and self._assistant.mode == InteractionMode.VOICE:
                        self._toggle_mode()

            elif action == "set_status_bar":
                want = show_bool
                if want is None:  # "toggle"
                    self._toggle_status_bar()
                elif want and not self._status_visible:
                    self._toggle_status_bar()
                elif not want and self._status_visible:
                    self._toggle_status_bar()

            elif action == "set_chat_feed":
                want = show_bool
                if want is None:
                    self._toggle_chat_feed()
                elif want and not self._chat_visible:
                    self._toggle_chat_feed()
                elif not want and self._chat_visible:
                    self._toggle_chat_feed()

            elif action == "set_tts_mute":
                want = mute_bool
                if want is None:
                    self._toggle_mute()
                elif want and not self._tts_muted:
                    self._toggle_mute()
                elif not want and self._tts_muted:
                    self._toggle_mute()

            elif action == "clear_history":
                if self._assistant:
                    self._assistant.conversation_history.clear()
                self._settings.clear_session_history(config.ACTIVE_PROFILE)

            elif action == "clear_memories":
                self._settings.clear_memories(self._settings.active_profile_name)

            elif action == "set_bot_name":
                if value:
                    self._settings.set("bot_name", value)
                    self._bot_name = value
                    self._status.set_model(value)
                    if self._assistant:
                        self._kivy_display.show_menu_bar(self._assistant.mode, value)

            elif action == "set_user_name":
                if value:
                    self._settings.set("user_name", value)
                    # Remove any memories that refer to a previous name so they
                    # don't conflict with the updated user_name in the system prompt.
                    _name_keywords = ("name is", "called ", "known as", "goes by")
                    for fact in self._settings.load_memories(config.ACTIVE_PROFILE):
                        if any(kw in fact.lower() for kw in _name_keywords):
                            self._settings.remove_memory(config.ACTIVE_PROFILE, fact)
                    if self._assistant:
                        self._assistant.conversation_history.append({
                            "role": "user",
                            "content": f"[My name is {value} — please use this name from now on, not any previous name]",
                        })

            elif action == "open_settings":
                self._settings_screen.show()

            elif action == "open_diagnostics":
                self._diagnostics.refresh(self._assistant)
                self._diagnostics.show()

            elif action == "set_menu_button":
                visible = show_bool if show_bool is not None else True
                self._menu_container.opacity = 1 if visible else 0
                self._menu_btn.disabled = not visible

        # Pre-update the toggle dict synchronously so begin_stream() sees the
        # correct future state before the Clock callback fires on the main thread.
        if action == "set_chat_feed":
            if show_bool is None:
                self._kivy_display.toggles['chat'] = not self._chat_visible
            elif show_bool and not self._chat_visible:
                self._kivy_display.toggles['chat'] = True
            elif not show_bool and self._chat_visible:
                self._kivy_display.toggles['chat'] = False
        elif action == "set_tts_mute":
            if mute_bool is None:
                self._kivy_display.toggles['speaking'] = self._tts_muted  # toggle: muted→speaking
            elif mute_bool and not self._tts_muted:
                self._kivy_display.toggles['speaking'] = False  # muting
            elif not mute_bool and self._tts_muted:
                self._kivy_display.toggles['speaking'] = True   # unmuting

        Clock.schedule_once(_run, 0)

        # Build a human-readable result for the LLM
        results = {
            "set_theme":        f"Theme changed to {theme or value}.",
            "set_animation":    f"Animation style changed to {anim or value}.",
            "set_mode":         f"Mode switched to {mode or value}.",
            "set_status_bar":   f"Status bar {'shown' if show_bool else 'hidden'}.",
            "set_chat_feed":    f"Chat feed {'opened' if show_bool else 'closed'}.",
            "set_tts_mute":     "TTS muted." if mute_bool else "TTS unmuted.",
            "clear_history":    "Conversation history cleared.",
            "clear_memories":   "Memories cleared.",
            "set_bot_name":     f"Bot name updated to {value}.",
            "set_user_name":    f"User name updated to {value}.",
            "open_settings":    "Settings page opened.",
            "open_diagnostics": "Diagnostics page opened.",
            "set_menu_button":  f"Menu button {'shown' if show_bool else 'hidden'}.",
        }
        return results.get(action, "Done.")

    # ── Settings screen ───────────────────────────────────────

    def _toggle_settings_screen(self, *args):
        """Show/hide the full settings screen overlay."""
        if self._settings_screen.is_visible:
            self._settings_screen.hide()
        else:
            self._settings_screen.show()

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
                set_ui_control_callback(self._handle_ui_control)

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
        if self._assistant.is_speaking:
            self._assistant.tts_engine.stop()
            self._assistant.is_speaking = False
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
            self._show_model_selector()
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
            except (RuntimeError, AttributeError) as e:
                # Mode switched or assistant was cleaned up
                break
            except Exception as e:
                # Log unexpected errors but keep the loop alive
                print(f"Error in chat input loop: {e}", file=sys.stderr)
                import traceback
                traceback.print_exc()
                break

    # ── Model selector ────────────────────────────────────────

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

        bot_name = self._settings.get("bot_name", "Zeina")

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
                self._settings.set("ollama_model", model_name)
                self._kivy_display.show_menu_bar(self._assistant.mode, bot_name)
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

    # ── Face size adjustment ──────────────────────────────────

    def _adjust_face_size(self, anim_name: str):
        """Give the face more vertical space for text-based animation styles."""
        if anim_name == "ascii":
            self._face.size_hint_y = 2.2
        else:
            self._face.size_hint_y = 1.0

    # ── Shutdown ──────────────────────────────────────────────

    def _quit(self):
        """Clean shutdown — stop TTS first to avoid pygame blocking."""
        self._stop_tts_gracefully()
        if self._assistant:
            try:
                self._assistant._save_conversation()
            except Exception:
                pass
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
        self.stop()

    def _stop_tts_gracefully(self):
        """Stop TTS playback if active."""
        if not self._assistant:
            return
        try:
            if getattr(self._assistant, 'is_speaking', False):
                self._assistant.tts_engine.stop()
                self._assistant.is_speaking = False
        except Exception:
            pass
        # Stop pygame mixer directly as a safety net
        try:
            import pygame
            pygame.mixer.music.stop()
        except Exception:
            pass

    def on_stop(self):
        """Called when the app is closing (window X button or stop())."""
        self._stop_tts_gracefully()
        if self._assistant:
            try:
                self._assistant._save_conversation()
            except Exception:
                pass
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
