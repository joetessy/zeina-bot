"""
Settings screen overlay for Zeina AI Assistant.

Full-screen overlay with sections for all configurable settings.
Respects the current theme colors.
"""
from __future__ import annotations

from kivy.clock import Clock
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput

from zeina import config
from ui.themes import THEMES, get_theme
from ui.animation_themes import ANIMATION_THEMES
from ui.widgets.settings.builders import SettingBuildersMixin
from ui.widgets.settings.dialogs import DANGER_COLOR, confirm_popup, info_popup
from ui.widgets.settings.rows import (
    SectionDivider,
    SectionHeader,
    SettingRow,
    StyledSpinnerOption,
    ThemeColors,
)

# Display names for animation themes
ANIM_DISPLAY_NAMES = {
    "vector": "Vector",
    "ascii": "ASCII",
}


class SettingsScreen(SettingBuildersMixin, FloatLayout):
    """Full-screen settings overlay."""

    def __init__(self, settings, app, face_widget=None, **kwargs):
        super().__init__(**kwargs)
        self._settings = settings
        self._app = app
        self.face_widget = face_widget
        self._visible = False

        # Semi-transparent background
        with self.canvas.before:
            Color(0.02, 0.02, 0.04, 0.92)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._update_bg, size=self._update_bg)

        # Content panel (centered, 92% width)
        self._content = BoxLayout(
            orientation='vertical',
            size_hint=(0.92, 0.94),
            pos_hint={'center_x': 0.5, 'center_y': 0.5},
            spacing=0,
            padding=[0, 0, 0, 0],
        )
        with self._content.canvas.before:
            self._content_bg_color = Color(0.08, 0.09, 0.12, 0.98)
            self._content_bg = RoundedRectangle(
                pos=self._content.pos, size=self._content.size, radius=[14]
            )
        self._content.bind(pos=self._update_content_bg, size=self._update_content_bg)

        # Header (with padding around it)
        header_outer = BoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=76,
            padding=[20, 18, 16, 14],
        )
        self._title_label = Label(
            text="Settings",
            font_size='20sp',
            color=(0.9, 0.93, 0.96, 1),
            bold=True,
            halign='left',
            valign='middle',
            size_hint_x=0.85,
        )
        self._title_label.bind(size=self._title_label.setter('text_size'))
        header_outer.add_widget(self._title_label)

        close_btn = Button(
            text="X",
            size_hint=(None, None),
            size=(38, 38),
            font_size='16sp',
            background_normal='',
            background_color=(0, 0, 0, 0),
            color=(1, 1, 1, 0.95),
            bold=True,
        )
        with close_btn.canvas.before:
            Color(0.70, 0.18, 0.18, 0.95)
            close_btn._bg = RoundedRectangle(pos=close_btn.pos, size=close_btn.size, radius=[8])
        close_btn.bind(
            pos=lambda i, v: setattr(i._bg, 'pos', v),
            size=lambda i, v: setattr(i._bg, 'size', v),
            on_release=lambda x: self.hide(),
        )
        header_outer.add_widget(close_btn)
        self._content.add_widget(header_outer)

        # Thin divider under header
        self._content.add_widget(SectionDivider())

        # Scrollable settings area — with inner padding
        scroll = ScrollView(do_scroll_x=False, bar_width=4,
                            bar_color=(0.35, 0.5, 0.45, 0.5),
                            bar_inactive_color=(0.25, 0.35, 0.32, 0.2))
        self._sections = BoxLayout(
            orientation='vertical',
            size_hint_y=None,
            spacing=6,
            padding=[20, 16, 20, 16],
        )
        self._sections.bind(minimum_height=self._sections.setter('height'))
        scroll.add_widget(self._sections)
        self._content.add_widget(scroll)

        # Thin divider above bottom bar
        self._content.add_widget(SectionDivider())

        # Fixed bottom bar for profile action buttons
        self._bottom_bar = BoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=78,
            spacing=10,
            padding=[20, 16, 20, 16],
        )
        self._save_profile_btn = Button(
            text="Save As New Profile",
            size_hint_x=1,
            font_size='13sp',
            background_normal='',
            background_color=(0, 0, 0, 0),
            color=(1, 1, 1, 0.9),
        )
        with self._save_profile_btn.canvas.before:
            self._save_btn_bg_color = Color(0.18, 0.52, 0.46, 0.9)
            self._save_btn_bg = RoundedRectangle(
                pos=self._save_profile_btn.pos,
                size=self._save_profile_btn.size,
                radius=[8],
            )
        self._save_profile_btn.bind(
            pos=lambda i, v: setattr(self._save_btn_bg, 'pos', v),
            size=lambda i, v: setattr(self._save_btn_bg, 'size', v),
        )
        self._save_profile_btn.bind(on_release=lambda x: self._on_save_profile())

        self._delete_profile_btn = Button(
            text="Delete Profile",
            size_hint_x=1,
            font_size='13sp',
            background_normal='',
            background_color=(0, 0, 0, 0),
            color=(1, 1, 1, 0.9),
        )
        with self._delete_profile_btn.canvas.before:
            Color(0.75, 0.15, 0.15, 0.95)
            self._del_btn_bg = RoundedRectangle(
                pos=self._delete_profile_btn.pos,
                size=self._delete_profile_btn.size,
                radius=[8],
            )
        self._delete_profile_btn.bind(
            pos=lambda i, v: setattr(self._del_btn_bg, 'pos', v),
            size=lambda i, v: setattr(self._del_btn_bg, 'size', v),
        )
        self._delete_profile_btn.bind(on_release=lambda x: self._on_delete_profile())

        self._bottom_bar.add_widget(self._save_profile_btn)
        self._bottom_bar.add_widget(self._delete_profile_btn)
        self._content.add_widget(self._bottom_bar)

        self.add_widget(self._content)

        self._build_sections()

    def _update_bg(self, *args):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def _update_content_bg(self, *args):
        self._content_bg.pos = self._content.pos
        self._content_bg.size = self._content.size

    # ── Theme colors ──────────────────────────────────────────

    def _get_theme_colors(self) -> ThemeColors:
        """Get active theme accent and background colors."""
        theme_name = self._settings.get("theme", "default")
        theme = get_theme(theme_name)
        accent = theme.get("accent", (0.18, 0.52, 0.46, 1))
        return ThemeColors(
            accent=accent,
            bg_off=theme.get("toggle_off", (0.15, 0.16, 0.20, 1)),
            text_on=theme.get("toggle_on_text", (1, 1, 1, 0.95)),
            text_off=theme.get("toggle_off_text", (0.55, 0.55, 0.6, 0.9)),
            section=(accent[0], accent[1], accent[2], 0.85),
            panel_bg=theme.get("status_bg", (0.08, 0.09, 0.12, 0.98)),
            font=theme.get("font_name", "Roboto"),
        )

    def _get_font(self) -> str:
        return self._get_theme_colors().font

    def _next_even(self) -> bool:
        """Return True for even-indexed rows (zero-based), then increment."""
        even = (self._row_idx % 2 == 0)
        self._row_idx += 1
        return even

    # ── Section assembly ──────────────────────────────────────

    def _build_sections(self):
        s = self._sections
        self._row_idx = 0
        profile = self._settings.get_all()
        colors = self._get_theme_colors()
        font = colors.font

        # Update panel background
        self._content_bg_color.rgba = colors.panel_bg
        self._title_label.font_name = font

        # Update bottom bar button colors
        self._save_btn_bg_color.rgba = colors.accent
        self._save_profile_btn.font_name = font
        self._delete_profile_btn.font_name = font

        def H(text):
            """Shorthand: section header with spacing."""
            s.add_widget(BoxLayout(size_hint_y=None, height=8))  # spacer
            s.add_widget(SectionHeader(text, color=colors.section, font_name=font))

        # ── General ──
        H("General")
        self.add_text_setting(s, "Bot Name", "bot_name",
                              profile.get("bot_name", "Zeina"), font=font)
        self.add_toggle_group(s, "Observability", "observability_level",
                              ["off", "lite", "verbose"],
                              profile.get("observability_level", "lite"), font=font)

        # ── AI Model ──
        H("AI Model")
        self.add_model_spinner(s, "Main Model", "chat_model",
                               profile.get("chat_model", "qwen2.5-7b"), font=font)
        self.add_model_spinner(s, "Vision Model", "vision_model",
                               profile.get("vision_model", config.VISION_MODEL), font=font)

        # ── Voice ──
        H("Voice")
        self.add_voice_spinner(s, "TTS Voice", "tts_voice",
                               profile.get("tts_voice", ""), font=font)
        self.add_slider(s, "Speech Rate", "tts_speed",
                        0.5, 2.0, 0.1, profile.get("tts_speed", 1.0), "x", font=font)
        self.add_text_setting(s, "PTT Key", "push_to_talk_key",
                              profile.get("push_to_talk_key", "space"), font=font)
        self.add_slider(s, "Silence Duration", "silence_duration",
                        1.0, 5.0, 0.5, profile.get("silence_duration", 2.0), "s", font=font,
                        post_callback=self._update_system_prompt_live)
        self.add_slider(s, "VAD Threshold", "vad_threshold",
                        0.1, 0.9, 0.1, profile.get("vad_threshold", 0.5), "", font=font)

        # ── Appearance ──
        H("Appearance")
        theme_names = list(THEMES.keys())
        self.add_choice_buttons(s, "Theme", "theme",
                                theme_names, profile.get("theme", "default"),
                                self._on_theme_changed, font=font, cols=3)
        anim_names = list(ANIMATION_THEMES.keys())
        self.add_choice_buttons(s, "Animation", "animation_theme",
                                anim_names, profile.get("animation_theme", "vector"),
                                self._on_animation_changed,
                                value_labels=ANIM_DISPLAY_NAMES, font=font)

        # ── Status Bar ──
        H("Status Bar")
        self.add_toggle_setting(s, "Mode Label", "status_show_mode",
                                profile.get("status_show_mode", True), font=font)
        self.add_toggle_setting(s, "Tool Log", "status_show_toollog",
                                profile.get("status_show_toollog", True), font=font)
        self.add_toggle_setting(s, "Bot Name", "status_show_botname",
                                profile.get("status_show_botname", True), font=font)

        # ── Personality ──
        H("Personality")
        self.add_text_setting(s, "User's Name", "user_name",
                              profile.get("user_name", ""), font=font)
        self.add_toggle_group(s, "Response Length", "response_length",
                              ["concise", "detailed"],
                              profile.get("response_length", "default"), font=font,
                              post_callback=self._update_system_prompt_live)
        self.add_toggle_group(s, "Language Style", "language_style",
                              ["casual", "professional", "wild"],
                              profile.get("language_style", "default"), font=font,
                              post_callback=self._update_system_prompt_live)
        self.add_multiline_setting(s, "Custom Instructions", "custom_instructions",
                                   profile.get("custom_instructions", ""), font=font)
        self.add_action_button(s, "Reset Personality", self._on_reset_personality_confirm,
                               color=DANGER_COLOR, font=font)

        # ── Memory ──
        H("Memory")
        self.add_toggle_setting(s, "Learn About User", "memory_enabled",
                                profile.get("memory_enabled", True), font=font)
        self._memory_count_row = self.add_info_label(
            s, "Facts Stored",
            self._memory_count_text(), font=font
        )
        self.add_action_button(s, "Clear Memory", self._on_clear_memory_confirm,
                               color=DANGER_COLOR, font=font)

        # ── Conversation ──
        H("Conversation")
        self.add_toggle_setting(s, "Save History", "save_conversation_history",
                                profile.get("save_conversation_history", True), font=font)
        self.add_global_slider(s, "Max Messages", "max_conversation_length",
                               5, 50, 5, config.MAX_CONVERSATION_LENGTH, "", font=font)
        self.add_action_button(s, "Clear History", self._on_clear_history_confirm,
                               color=DANGER_COLOR, font=font)

        # ── Profiles ──
        H("Profiles")
        self._add_profile_section(s, font=font)

    def _add_profile_section(self, parent, font="Roboto"):
        colors = self._get_theme_colors()
        profiles = self._settings.list_profiles()
        current = self._settings.active_profile_name

        row = SettingRow("Active Profile", font_name=font, even=self._next_even())
        self._profile_spinner = Spinner(
            text=current,
            values=profiles,
            size_hint_x=0.62,
            size_hint_y=None,
            height=44,
            font_size='13sp',
            font_name=font,
            background_normal='',
            background_color=colors.bg_off,
            color=colors.text_on,
            option_cls=StyledSpinnerOption,
        )
        self._profile_spinner.bind(text=self._on_profile_switch)
        row.add_widget(self._profile_spinner)
        parent.add_widget(row)

    # ── Live-update helpers ───────────────────────────────────

    def _apply_status_bar_component(self, key, value):
        """Live-update a status bar component visibility."""
        status = getattr(self._app, '_status', None)
        if not status:
            return
        if key == "status_show_mode":
            status.set_mode_visible(bool(value))
        elif key == "status_show_botname":
            status.set_model_visible(bool(value))
        elif key == "status_show_toollog":
            status.set_tool_log_enabled(bool(value))

    def _reload_tts(self, voice_path):
        """Reload the TTS engine with the new voice model."""
        assistant = getattr(self._app, '_assistant', None)
        if not assistant or not voice_path or voice_path == "(none)":
            return
        try:
            from zeina.tts import TTSEngine
            if hasattr(assistant, 'tts_engine'):
                assistant.tts_engine = TTSEngine(voice=config.TTS_VOICE)
        except Exception:
            pass  # TTS reload failed silently — user can restart the app

    def _update_system_prompt_live(self, reason="settings change"):
        """Push a rebuilt system prompt into the running assistant."""
        assistant = getattr(self._app, '_assistant', None)
        if not assistant:
            return
        assistant.refresh_system_prompt(reason=reason)

    def _flash_status(self, message: str, restore_after: float = 2.5):
        """Show a status message, then restore the mode-appropriate ready text."""
        status = getattr(self._app, '_status', None)
        if not status:
            return
        status.set_status(message, "green")
        assistant = getattr(self._app, '_assistant', None)
        if assistant and assistant.mode.value == "chat":
            ready_msg = "Enter a message"
        else:
            ready_msg = "Push to talk"
        Clock.schedule_once(
            lambda dt, msg=ready_msg: status.set_status(msg, "green"), restore_after
        )

    # ── Callbacks ────────────────────────────────────────────────

    def _on_theme_changed(self, theme_name):
        if hasattr(self._app, '_theme_manager'):
            self._app._theme_manager.apply(self._app, theme_name)
        # Refresh settings screen to pick up new theme colors
        self._refresh()
        self._update_system_prompt_live(reason=f"theme changed to {theme_name}")

    def _on_animation_changed(self, anim_name):
        if hasattr(self._app, '_face'):
            self._app._face.set_animation_theme(anim_name)
        if hasattr(self._app, '_adjust_face_size'):
            self._app._adjust_face_size(anim_name)
        self._update_system_prompt_live(reason=f"face style changed to {anim_name}")

    def _on_bot_name_changed(self, name):
        if hasattr(self._app, '_status'):
            self._app._status.set_model(name)
        self._app._bot_name = name
        self._update_system_prompt_live(reason="bot name change")

    def _memory_count_text(self) -> str:
        count = self._settings.memory_count(self._settings.active_profile_name)
        return f"{count} fact{'s' if count != 1 else ''} stored"

    # ── Destructive actions (shared confirmation popup) ──────────

    def _on_reset_personality_confirm(self):
        confirm_popup(
            message=("Reset personality settings to defaults?\n"
                     "(Bot name and memory are not affected)"),
            confirm_text="Reset",
            on_confirm=self._on_reset_personality,
            font=self._get_font(),
            message_height=52,
            size_hint=(0.7, 0.30),
        )

    def _on_reset_personality(self):
        for key, default in [
            ("user_name", ""),
            ("response_length", "concise"),
            ("language_style", "casual"),
            ("custom_instructions", ""),
        ]:
            self._settings.set(key, default)
        self._update_system_prompt_live()
        self._refresh()
        self._flash_status("Personality reset")

    def _on_clear_memory_confirm(self):
        count = self._settings.memory_count(self._settings.active_profile_name)

        def _do_clear():
            self._settings.clear_memories(self._settings.active_profile_name)
            self._update_system_prompt_live()
            self._refresh()
            self._flash_status("Memory cleared")

        confirm_popup(
            message=f"Clear all {count} stored memory facts?",
            confirm_text="Clear",
            on_confirm=_do_clear,
            font=self._get_font(),
        )

    def _on_clear_history_confirm(self):
        confirm_popup(
            message="Clear all conversation history?",
            confirm_text="Clear",
            on_confirm=self._on_clear_history,
            font=self._get_font(),
        )

    def _on_clear_history(self):
        self._settings.clear_session_history(self._settings.active_profile_name)
        if hasattr(self._app, '_chat'):
            self._app._chat.clear_messages()
        assistant = getattr(self._app, '_assistant', None)
        if assistant:
            assistant.conversation_history = []
            # Start a fresh session file so the next exchange isn't lost
            assistant._session_path = self._settings.start_session(
                self._settings.active_profile_name
            )
        self._flash_status("History cleared!")

    # ── Profile management ────────────────────────────────────────

    def _on_profile_switch(self, instance, name):
        self._settings.switch_profile(name)
        self._settings.apply_to_config()
        self._refresh()
        profile = self._settings.get_all()
        self._on_theme_changed(profile.get("theme", "default"))
        self._on_animation_changed(profile.get("animation_theme", "vector"))
        self._on_bot_name_changed(profile.get("bot_name", "Zeina"))
        # Reload the assistant's conversation history for the new profile
        if hasattr(self._app, '_assistant') and self._app._assistant:
            assistant = self._app._assistant
            from zeina.tts import TTSEngine
            assistant.tts_engine = TTSEngine(voice=config.TTS_VOICE)
            assistant.conversation_history = []
            assistant.refresh_system_prompt(reason=f"profile switch → {name}")
            recent = self._settings.load_recent_messages(
                name, config.MAX_CONVERSATION_LENGTH
            )
            assistant.conversation_history.extend(recent)
            assistant._session_path = self._settings.start_session(name)

    def _on_save_profile(self):
        font = self._get_font()
        content = BoxLayout(orientation='vertical', spacing=12, padding=[20, 16])
        inp = TextInput(
            hint_text="Profile name...",
            multiline=False,
            size_hint_y=None,
            height=44,
            font_size='14sp',
            font_name=font,
            background_color=(0.14, 0.15, 0.19, 1),
            foreground_color=(0.9, 0.92, 0.95, 1),
        )
        content.add_widget(inp)

        popup = Popup(
            title="Save As New Profile",
            content=content,
            size_hint=(0.7, 0.28),
            background_color=(0.1, 0.1, 0.12, 0.98),
        )

        def _save(instance):
            name = inp.text.strip()
            if name and name not in self._settings.list_profiles():
                self._settings.create_profile(
                    name, from_profile=self._settings.active_profile_name
                )
                self._settings.switch_profile(name)
                self._profile_spinner.values = self._settings.list_profiles()
                self._profile_spinner.text = name
                popup.dismiss()

        save_btn = Button(
            text="Save",
            size_hint_y=None,
            height=44,
            font_size='14sp',
            font_name=font,
            background_normal='atlas://data/images/defaulttheme/button',
            background_color=(0.18, 0.52, 0.46, 1),
            color=(1, 1, 1, 0.9),
        )
        save_btn.bind(on_release=_save)
        inp.bind(on_text_validate=_save)
        content.add_widget(save_btn)
        popup.open()

    def _on_delete_profile(self):
        current = self._settings.active_profile_name
        font = self._get_font()

        if current == "default":
            info_popup(title="Cannot Delete",
                       message="The default profile cannot be deleted.", font=font)
            return

        def _do_delete():
            self._settings.delete_profile(current)
            # Switch spinner and UI to default
            self._profile_spinner.values = self._settings.list_profiles()
            self._profile_spinner.text = self._settings.active_profile_name
            self._on_profile_switch(None, self._settings.active_profile_name)

        confirm_popup(
            title="Delete Profile",
            message=f'Delete profile "{current}"?\nThis cannot be undone.',
            confirm_text=f'Delete "{current}"',
            on_confirm=_do_delete,
            font=font,
            size_hint=(0.65, 0.3),
            show_cancel=False,
        )

    def _refresh(self):
        """Rebuild the settings sections with current values."""
        self._sections.clear_widgets()
        self._build_sections()

    # ── Show / Hide ──────────────────────────────────────────────

    def show(self):
        if self._visible:
            return
        self._visible = True
        self._refresh()
        self.opacity = 1
        self.disabled = False

    def hide(self):
        if not self._visible:
            return
        self._visible = False
        self.opacity = 0
        self.disabled = True

    @property
    def is_visible(self) -> bool:
        return self._visible

    # ── Touch handling ───────────────────────────────────────────

    def on_touch_down(self, touch):
        if not self._visible:
            return False
        super().on_touch_down(touch)
        return True

    def on_touch_move(self, touch):
        if not self._visible:
            return False
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if not self._visible:
            return False
        return super().on_touch_up(touch)
