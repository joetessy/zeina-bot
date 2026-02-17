"""
Settings screen overlay for Zeina AI Assistant.

Full-screen overlay with sections for all configurable settings.
Respects the current theme colors.
"""
import math
import os
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.widget import Widget
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.slider import Slider
from kivy.uix.spinner import Spinner
from kivy.uix.popup import Popup
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.clock import Clock

from zeina import config
from ui.themes import THEMES, get_theme
from ui.animation_themes import ANIMATION_THEMES


# Display names for animation themes
ANIM_DISPLAY_NAMES = {
    "vector": "Vector",
    "ascii": "ASCII",
}


class SettingRow(BoxLayout):
    """A single setting row: label on left, control on right.
    Even-indexed rows get a subtly lighter background for scannability."""

    def __init__(self, label_text, font_name="Roboto", even=False, **kwargs):
        kwargs.setdefault('orientation', 'horizontal')
        kwargs.setdefault('size_hint_y', None)
        kwargs.setdefault('height', 60)
        kwargs.setdefault('spacing', 16)
        kwargs.setdefault('padding', [12, 6])
        super().__init__(**kwargs)

        if even:
            with self.canvas.before:
                Color(0.11, 0.12, 0.16, 0.55)
                self._row_bg = Rectangle(pos=self.pos, size=self.size)
            self.bind(
                pos=lambda i, v: setattr(self._row_bg, 'pos', v),
                size=lambda i, v: setattr(self._row_bg, 'size', v),
            )

        self._label = Label(
            text=label_text,
            font_size='14sp',
            font_name=font_name,
            size_hint_x=0.38,
            color=(0.78, 0.82, 0.88, 1),
            halign='left',
            valign='middle',
        )
        self._label.bind(size=self._label.setter('text_size'))
        self.add_widget(self._label)


class SectionHeader(BoxLayout):
    """Section title with a colored left accent bar."""

    def __init__(self, text, color=None, font_name="Roboto", **kwargs):
        kwargs.setdefault('size_hint_y', None)
        kwargs.setdefault('height', 44)
        kwargs.setdefault('spacing', 10)
        kwargs.setdefault('padding', [2, 10, 0, 6])
        super().__init__(**kwargs)

        bar_color = color or (0.18, 0.52, 0.46, 0.85)

        # Left accent bar
        bar = Widget(size_hint_x=None, width=3)
        with bar.canvas:
            Color(*bar_color)
            bar._rect = Rectangle(pos=bar.pos, size=bar.size)
        bar.bind(
            pos=lambda i, v: setattr(i._rect, 'pos', v),
            size=lambda i, v: setattr(i._rect, 'size', v),
        )
        self.add_widget(bar)

        lbl = Label(
            text=text,
            font_size='15sp',
            font_name=font_name,
            bold=True,
            color=bar_color,
            halign='left',
            valign='middle',
        )
        lbl.bind(size=lbl.setter('text_size'))
        self.add_widget(lbl)


class SectionDivider(BoxLayout):
    """Thin horizontal divider between sections."""

    def __init__(self, **kwargs):
        kwargs.setdefault('size_hint_y', None)
        kwargs.setdefault('height', 1)
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(0.25, 0.27, 0.32, 0.5)
            self._line = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=lambda i, v: setattr(self._line, 'pos', v),
                  size=lambda i, v: setattr(self._line, 'size', v))


class SettingsScreen(FloatLayout):
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

    def _get_theme_colors(self):
        """Get active theme accent and background colors."""
        theme_name = self._settings.get("theme", "default")
        theme = get_theme(theme_name)
        accent = theme.get("accent", (0.18, 0.52, 0.46, 1))
        bg_off = theme.get("toggle_off", (0.15, 0.16, 0.20, 1))
        text_on = theme.get("toggle_on_text", (1, 1, 1, 0.95))
        text_off = theme.get("toggle_off_text", (0.55, 0.55, 0.6, 0.9))
        section_color = (accent[0], accent[1], accent[2], 0.85)
        panel_bg = theme.get("status_bg", (0.08, 0.09, 0.12, 0.98))
        font_name = theme.get("font_name", "Roboto")
        return accent, bg_off, text_on, text_off, section_color, panel_bg, font_name

    def _get_font(self):
        theme_name = self._settings.get("theme", "default")
        return get_theme(theme_name).get("font_name", "Roboto")

    def _next_even(self):
        """Return True for even-indexed rows (zero-based), then increment."""
        even = (self._row_idx % 2 == 0)
        self._row_idx += 1
        return even

    def _build_sections(self):
        s = self._sections
        self._row_idx = 0
        profile = self._settings.get_all()
        accent, bg_off, text_on, text_off, section_color, panel_bg, font = self._get_theme_colors()

        # Update panel background
        self._content_bg_color.rgba = panel_bg
        self._title_label.font_name = font

        # Update bottom bar button colors
        self._save_btn_bg_color.rgba = accent
        self._save_profile_btn.font_name = font
        self._delete_profile_btn.font_name = font

        def H(text):
            """Shorthand: section header with spacing."""
            s.add_widget(BoxLayout(size_hint_y=None, height=8))  # spacer
            hdr = SectionHeader(text, color=section_color, font_name=font)
            s.add_widget(hdr)

        # ── General ──
        H("General")
        self._add_text_setting(s, "Bot Name", "bot_name",
                               profile.get("bot_name", "Zeina"), font=font)
        self._add_toggle_group(s, "Observability", "observability_level",
                               ["off", "lite", "verbose"],
                               profile.get("observability_level", "lite"), font=font)

        # ── AI Model ──
        H("AI Model")
        self._add_model_spinner(s, "Main Model", "ollama_model",
                                profile.get("ollama_model", "llama3.1:8b"), font=font)

        # ── Voice ──
        H("Voice")
        self._add_voice_spinner(s, "TTS Voice", "tts_voice",
                                profile.get("tts_voice", ""), font=font)
        self._add_text_setting(s, "PTT Key", "push_to_talk_key",
                               profile.get("push_to_talk_key", "space"), font=font)
        self._add_slider(s, "Silence Duration", "silence_duration",
                         1.0, 5.0, 0.5, profile.get("silence_duration", 2.0), "s", font=font,
                         post_callback=self._update_system_prompt_live)
        self._add_slider(s, "VAD Threshold", "vad_threshold",
                         0.1, 0.9, 0.1, profile.get("vad_threshold", 0.5), "", font=font)

        # ── Appearance ──
        H("Appearance")
        theme_names = list(THEMES.keys())
        self._add_choice_buttons(s, "Theme", "theme",
                                 theme_names, profile.get("theme", "default"),
                                 self._on_theme_changed, font=font, cols=3)
        anim_names = list(ANIMATION_THEMES.keys())
        self._add_choice_buttons(s, "Animation", "animation_theme",
                                 anim_names, profile.get("animation_theme", "vector"),
                                 self._on_animation_changed,
                                 value_labels=ANIM_DISPLAY_NAMES, font=font)

        # ── Status Bar ──
        H("Status Bar")
        self._add_toggle_setting(s, "Mode Label", "status_show_mode",
                                 profile.get("status_show_mode", True), font=font)
        self._add_toggle_setting(s, "Tool Log", "status_show_toollog",
                                 profile.get("status_show_toollog", True), font=font)
        self._add_toggle_setting(s, "Bot Name", "status_show_botname",
                                 profile.get("status_show_botname", True), font=font)

        # ── Personality ──
        H("Personality")
        self._add_text_setting(s, "User's Name", "user_name",
                               profile.get("user_name", ""), font=font)
        self._add_toggle_group(s, "Response Length", "response_length",
                               ["concise", "detailed"],
                               profile.get("response_length", "default"), font=font,
                               post_callback=self._update_system_prompt_live)
        self._add_toggle_group(s, "Language Style", "language_style",
                               ["casual", "professional", "wild"],
                               profile.get("language_style", "default"), font=font,
                               post_callback=self._update_system_prompt_live)
        self._add_multiline_setting(s, "Custom Instructions", "custom_instructions",
                                    profile.get("custom_instructions", ""), font=font)
        self._add_action_button(s, "Reset Personality", self._on_reset_personality_confirm,
                                color=((0.75, 0.15, 0.15, 0.95)), font=font)

        # ── Memory ──
        H("Memory")
        self._add_toggle_setting(s, "Learn About User", "memory_enabled",
                                 profile.get("memory_enabled", True), font=font)
        self._memory_count_row = self._add_info_label(
            s, "Facts Stored",
            self._memory_count_text(), font=font
        )
        self._add_action_button(s, "Clear Memory", self._on_clear_memory_confirm,
                                color=(0.75, 0.15, 0.15, 0.95), font=font)

        # ── Conversation ──
        H("Conversation")
        self._add_toggle_setting(s, "Save History", "save_conversation_history",
                                 profile.get("save_conversation_history", True), font=font)
        self._add_global_slider(s, "Max Messages", "max_conversation_length",
                                5, 50, 5, config.MAX_CONVERSATION_LENGTH, "", font=font)
        self._add_action_button(s, "Clear History", self._on_clear_history_confirm,
                                color=(0.75, 0.15, 0.15, 0.95), font=font)

        # ── Profiles ──
        H("Profiles")
        self._add_profile_section(s, font=font)

    # ── Setting builders ─────────────────────────────────────────

    def _add_text_setting(self, parent, label, key, value, font="Roboto"):
        accent, bg_off, text_on, text_off, _, _, _ = self._get_theme_colors()
        row = SettingRow(label, font_name=font, even=self._next_even(), height=66)
        inp = TextInput(
            text=str(value),
            multiline=False,
            size_hint_x=0.62,
            size_hint_y=None,
            font_size='14sp',
            font_name=font,
            background_color=(bg_off[0] - 0.01, bg_off[1] - 0.01, bg_off[2] - 0.01, 1),
            foreground_color=(0.9, 0.92, 0.95, 1),
            cursor_color=(accent[0], accent[1], accent[2], 1),
            padding=[12, 10],
            pos_hint={'center_y': 0.5},
        )
        inp.bind(minimum_height=inp.setter('height'))

        def _on_change(instance):
            val = instance.text.strip()
            self._settings.set(key, val)
            if key == "bot_name":
                self._on_bot_name_changed(val)
            elif key == "user_name":
                self._update_system_prompt_live()

        inp.bind(on_text_validate=_on_change)
        inp.bind(focus=lambda inst, focused: _on_change(inst) if not focused else None)
        row.add_widget(inp)
        parent.add_widget(row)

    def _add_slider(self, parent, label, key, min_val, max_val, step, value, suffix,
                    font="Roboto", post_callback=None):
        row = SettingRow(label, font_name=font, even=self._next_even())

        slider_box = BoxLayout(orientation='horizontal', size_hint_x=0.62, spacing=10)
        value_label = Label(
            text=f"{value:.1f}{suffix}" if isinstance(value, float) else f"{int(value)}{suffix}",
            font_size='14sp',
            font_name=font,
            size_hint_x=0.28,
            color=(0.75, 0.8, 0.85, 1),
            halign='right',
            valign='middle',
        )
        value_label.bind(size=value_label.setter('text_size'))
        slider = Slider(
            min=min_val, max=max_val, step=step, value=value,
            size_hint_x=0.72,
            cursor_size=(22, 22),
        )

        def _on_value(instance, val):
            if isinstance(step, float) and step < 1:
                display = f"{val:.1f}{suffix}"
                self._settings.set(key, round(val, 1))
            else:
                display = f"{int(val)}{suffix}"
                self._settings.set(key, int(val))
            value_label.text = display
            self._settings.apply_to_config()
            if post_callback:
                post_callback()

        slider.bind(value=_on_value)
        slider_box.add_widget(slider)
        slider_box.add_widget(value_label)
        row.add_widget(slider_box)
        parent.add_widget(row)

    def _add_global_slider(self, parent, label, config_attr, min_val, max_val, step, value, suffix, font="Roboto"):
        """Slider that updates a global config value shared across all profiles."""
        row = SettingRow(label, font_name=font, even=self._next_even())

        slider_box = BoxLayout(orientation='horizontal', size_hint_x=0.62, spacing=10)
        value_label = Label(
            text=f"{int(value)}{suffix}",
            font_size='14sp',
            font_name=font,
            size_hint_x=0.28,
            color=(0.75, 0.8, 0.85, 1),
            halign='right',
            valign='middle',
        )
        value_label.bind(size=value_label.setter('text_size'))
        slider = Slider(
            min=min_val, max=max_val, step=step, value=value,
            size_hint_x=0.72,
            cursor_size=(22, 22),
        )

        def _on_value(instance, val):
            int_val = int(val)
            value_label.text = f"{int_val}{suffix}"
            setattr(config, config_attr.upper(), int_val)
            self._settings.set_all_profiles(config_attr, int_val)

        slider.bind(value=_on_value)
        slider_box.add_widget(slider)
        slider_box.add_widget(value_label)
        row.add_widget(slider_box)
        parent.add_widget(row)

    def _add_toggle_group(self, parent, label, key, options, current, font="Roboto",
                          post_callback=None):
        accent, bg_off, text_on, text_off, _, _, _ = self._get_theme_colors()
        row = SettingRow(label, font_name=font, even=self._next_even())
        btn_box = BoxLayout(orientation='horizontal', size_hint_x=0.62, spacing=6)

        def _make_handler(opt, buttons):
            def _handler(instance):
                self._settings.set(key, opt)
                self._settings.apply_to_config()
                for b in buttons:
                    b.background_color = bg_off
                    b.color = text_off
                instance.background_color = accent
                instance.color = text_on
                if post_callback:
                    post_callback()
            return _handler

        buttons = []
        for opt in options:
            is_active = opt == current
            btn = Button(
                text=opt.capitalize(),
                size_hint_x=1,
                size_hint_y=None,
                height=38,
                font_size='13sp',
                font_name=font,
                background_normal='atlas://data/images/defaulttheme/button',
                background_color=accent if is_active else bg_off,
                color=text_on if is_active else text_off,
            )
            buttons.append(btn)
            btn_box.add_widget(btn)

        for opt, btn in zip(options, buttons):
            btn.bind(on_release=_make_handler(opt, buttons))

        row.add_widget(btn_box)
        parent.add_widget(row)

    def _add_toggle_setting(self, parent, label, key, value, font="Roboto"):
        accent, bg_off, text_on, text_off, _, _, _ = self._get_theme_colors()
        row = SettingRow(label, font_name=font, even=self._next_even())
        btn = Button(
            text="ON" if value else "OFF",
            size_hint_x=0.62,
            size_hint_y=None,
            height=38,
            font_size='13sp',
            font_name=font,
            background_normal='atlas://data/images/defaulttheme/button',
            background_color=accent if value else bg_off,
            color=text_on if value else text_off,
        )

        def _toggle(instance):
            current = self._settings.get(key, False)
            new_val = not current
            self._settings.set(key, new_val)
            self._settings.apply_to_config()
            instance.text = "ON" if new_val else "OFF"
            instance.background_color = accent if new_val else bg_off
            instance.color = text_on if new_val else text_off
            self._apply_status_bar_component(key, new_val)

        btn.bind(on_release=_toggle)
        row.add_widget(btn)
        parent.add_widget(row)

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

    def _add_model_spinner(self, parent, label, key, current, font="Roboto"):
        accent, bg_off, text_on, text_off, _, _, _ = self._get_theme_colors()
        row = SettingRow(label, font_name=font, even=self._next_even())
        models = [current]
        try:
            import ollama
            resp = ollama.list()
            model_names = [m.model for m in resp.models]
            if model_names:
                models = model_names
                if current not in models:
                    models.insert(0, current)
        except Exception:
            pass

        spinner = Spinner(
            text=current,
            values=models,
            size_hint_x=0.62,
            size_hint_y=None,
            height=44,
            font_size='13sp',
            font_name=font,
            background_normal='',
            background_color=bg_off,
            color=text_on,
            option_cls=_StyledSpinnerOption,
        )

        def _on_select(instance, val):
            self._settings.set(key, val)
            self._settings.apply_to_config()

        spinner.bind(text=_on_select)
        row.add_widget(spinner)
        parent.add_widget(row)

    def _add_voice_spinner(self, parent, label, key, current, font="Roboto"):
        accent, bg_off, text_on, text_off, _, _, _ = self._get_theme_colors()
        row = SettingRow(label, font_name=font, even=self._next_even())
        models_dir = os.path.join(config.PROJECT_ROOT, "models")
        voices = []
        if os.path.isdir(models_dir):
            for f in os.listdir(models_dir):
                if f.endswith(".onnx"):
                    voices.append(f"models/{f}")
        if not voices:
            voices = [current] if current else ["(none)"]
        if current and current not in voices:
            voices.insert(0, current)

        spinner = Spinner(
            text=current or "(none)",
            values=voices,
            size_hint_x=0.62,
            size_hint_y=None,
            height=44,
            font_size='12sp',
            font_name=font,
            background_normal='',
            background_color=bg_off,
            color=text_on,
            option_cls=_StyledSpinnerOption,
        )

        def _on_select(instance, val):
            self._settings.set(key, val)
            self._settings.apply_to_config()
            # Reload TTS engine with new voice immediately
            self._reload_tts(val)

        spinner.bind(text=_on_select)
        row.add_widget(spinner)
        parent.add_widget(row)

    def _reload_tts(self, voice_path):
        """Reload the TTS engine with the new voice model."""
        assistant = getattr(self._app, '_assistant', None)
        if not assistant or not voice_path or voice_path == "(none)":
            return
        try:
            from zeina.tts import TTSEngine
            if hasattr(assistant, 'tts_engine'):
                assistant.tts_engine = TTSEngine(voice=voice_path)
        except Exception:
            pass  # TTS reload failed silently — user can restart the app

    def _add_choice_buttons(self, parent, label, key, options, current,
                             callback=None, value_labels=None, font="Roboto", cols=None):
        accent, bg_off, text_on, text_off, _, _, _ = self._get_theme_colors()

        use_grid = cols is not None and len(options) > cols
        if use_grid:
            num_rows = math.ceil(len(options) / cols)
            btn_area_h = num_rows * 38 + max(0, num_rows - 1) * 6
            row = SettingRow(label, font_name=font, even=self._next_even(),
                             height=btn_area_h + 22)
            btn_box = GridLayout(
                cols=cols,
                size_hint_x=0.62,
                size_hint_y=1,
                spacing=6,
                row_force_default=True,
                row_default_height=38,
            )
        else:
            row = SettingRow(label, font_name=font, even=self._next_even())
            btn_box = BoxLayout(orientation='horizontal', size_hint_x=0.62, spacing=6)

        def _make_handler(opt, buttons):
            def _handler(instance):
                self._settings.set(key, opt)
                for b in buttons:
                    b.background_color = bg_off
                    b.color = text_off
                instance.background_color = accent
                instance.color = text_on
                if callback:
                    callback(opt)
            return _handler

        buttons = []
        for opt in options:
            is_active = opt == current
            # Get display name: from value_labels map, then capitalize/upper heuristic
            if value_labels and opt in value_labels:
                display = value_labels[opt]
            elif len(opt) <= 3:
                display = opt.upper()
            else:
                display = opt.capitalize()

            btn = Button(
                text=display,
                size_hint_x=1,
                size_hint_y=None,
                height=38,
                font_size='13sp',
                font_name=font,
                background_normal='atlas://data/images/defaulttheme/button',
                background_color=accent if is_active else bg_off,
                color=text_on if is_active else text_off,
            )
            buttons.append(btn)
            btn_box.add_widget(btn)

        for opt, btn in zip(options, buttons):
            btn.bind(on_release=_make_handler(opt, buttons))

        row.add_widget(btn_box)
        parent.add_widget(row)

    def _add_action_button(self, parent, label, callback,
                           color=(0.18, 0.52, 0.46, 1), font="Roboto"):
        row = BoxLayout(
            size_hint_y=None, height=52,
            orientation='horizontal', spacing=16, padding=[12, 6],
        )
        # Spacer matching the label column so the button aligns with other controls
        row.add_widget(Widget(size_hint_x=0.38))
        btn = Button(
            text=label,
            size_hint_x=0.62,
            size_hint_y=1,
            font_size='14sp',
            font_name=font,
            background_normal='',
            background_color=(0, 0, 0, 0),
            color=(1, 1, 1, 0.9),
        )
        with btn.canvas.before:
            Color(*color)
            btn._bg = RoundedRectangle(pos=btn.pos, size=btn.size, radius=[8])
        btn.bind(
            pos=lambda i, v: setattr(i._bg, 'pos', v),
            size=lambda i, v: setattr(i._bg, 'size', v),
        )
        btn.bind(on_release=lambda x: callback())
        row.add_widget(btn)
        parent.add_widget(row)

    def _add_multiline_setting(self, parent, label, key, value, font="Roboto"):
        """A tall multiline TextInput for free-form text (custom instructions etc.)."""
        accent, bg_off, text_on, text_off, _, _, _ = self._get_theme_colors()
        row = SettingRow(label, font_name=font, even=self._next_even(), height=110)

        inp = TextInput(
            text=str(value),
            multiline=True,
            size_hint_x=0.62,
            size_hint_y=None,
            height=96,
            font_size='13sp',
            font_name=font,
            background_color=(bg_off[0] - 0.01, bg_off[1] - 0.01, bg_off[2] - 0.01, 1),
            foreground_color=(0.9, 0.92, 0.95, 1),
            cursor_color=(accent[0], accent[1], accent[2], 1),
            padding=[12, 10],
            pos_hint={'center_y': 0.5},
        )

        def _on_change(instance):
            self._settings.set(key, instance.text)
            self._update_system_prompt_live()

        inp.bind(focus=lambda inst, focused: _on_change(inst) if not focused else None)
        row.add_widget(inp)
        parent.add_widget(row)

    def _add_info_label(self, parent, label, value_text, font="Roboto"):
        """A read-only info row showing a computed value."""
        row = SettingRow(label, font_name=font, even=self._next_even())
        lbl = Label(
            text=value_text,
            font_size='14sp',
            font_name=font,
            size_hint_x=0.62,
            color=(0.55, 0.85, 0.75, 1),
            halign='left',
            valign='middle',
        )
        lbl.bind(size=lbl.setter('text_size'))
        row.add_widget(lbl)
        parent.add_widget(row)
        return lbl

    def _add_profile_section(self, parent, font="Roboto"):
        accent, bg_off, text_on, text_off, _, _, _ = self._get_theme_colors()
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
            background_color=bg_off,
            color=text_on,
            option_cls=_StyledSpinnerOption,
        )
        self._profile_spinner.bind(text=self._on_profile_switch)
        row.add_widget(self._profile_spinner)
        parent.add_widget(row)

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

    def _update_system_prompt_live(self, reason="settings change"):
        """Push a rebuilt system prompt into the running assistant."""
        assistant = getattr(self._app, '_assistant', None)
        if not assistant:
            return
        assistant.refresh_system_prompt(reason=reason)

    def _on_reset_personality_confirm(self):
        """Show confirmation before resetting personality additions."""
        font = self._get_font()
        content = BoxLayout(orientation='vertical', spacing=14, padding=[20, 16])
        content.add_widget(Label(
            text="Reset personality settings to defaults?\n(Bot name and memory are not affected)",
            font_size='14sp',
            font_name=font,
            color=(0.9, 0.9, 0.9, 1),
            size_hint_y=None,
            height=52,
            halign='center',
        ))

        popup = Popup(
            title="",
            separator_height=0,
            content=content,
            size_hint=(0.7, 0.30),
            background_color=(0.1, 0.1, 0.12, 0.98),
        )

        btn_row = BoxLayout(orientation='horizontal', spacing=10, size_hint_y=None, height=44)
        cancel_btn = Button(
            text="Cancel", font_size='14sp', font_name=font,
            background_normal='atlas://data/images/defaulttheme/button',
            background_color=(0.22, 0.22, 0.26, 1), color=(0.7, 0.7, 0.75, 1),
        )
        cancel_btn.bind(on_release=lambda x: popup.dismiss())

        confirm_btn = Button(
            text="Reset", font_size='14sp', font_name=font,
            background_normal='atlas://data/images/defaulttheme/button',
            background_color=(0.75, 0.15, 0.15, 0.95), color=(1, 1, 1, 0.95),
        )

        def _do_reset(instance):
            popup.dismiss()
            self._on_reset_personality()

        confirm_btn.bind(on_release=_do_reset)
        btn_row.add_widget(cancel_btn)
        btn_row.add_widget(confirm_btn)
        content.add_widget(btn_row)
        popup.open()

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
        if hasattr(self._app, '_status'):
            self._app._status.set_status("Personality reset", "green")
            Clock.schedule_once(
                lambda dt: self._app._status.set_status(
                    "Push to talk" if not (
                        self._app._assistant and
                        self._app._assistant.mode.value == "chat"
                    ) else "Enter a message", "green"
                ), 2.5
            )

    def _on_clear_memory_confirm(self):
        """Show confirmation before clearing memory."""
        font = self._get_font()
        count = self._settings.memory_count(self._settings.active_profile_name)
        content = BoxLayout(orientation='vertical', spacing=14, padding=[20, 16])
        content.add_widget(Label(
            text=f"Clear all {count} stored memory facts?",
            font_size='15sp',
            font_name=font,
            color=(0.9, 0.9, 0.9, 1),
            size_hint_y=None,
            height=32,
        ))

        popup = Popup(
            title="",
            separator_height=0,
            content=content,
            size_hint=(0.65, 0.28),
            background_color=(0.1, 0.1, 0.12, 0.98),
        )

        btn_row = BoxLayout(orientation='horizontal', spacing=10, size_hint_y=None, height=44)
        cancel_btn = Button(
            text="Cancel", font_size='14sp', font_name=font,
            background_normal='atlas://data/images/defaulttheme/button',
            background_color=(0.22, 0.22, 0.26, 1), color=(0.7, 0.7, 0.75, 1),
        )
        cancel_btn.bind(on_release=lambda x: popup.dismiss())

        confirm_btn = Button(
            text="Clear", font_size='14sp', font_name=font,
            background_normal='atlas://data/images/defaulttheme/button',
            background_color=(0.75, 0.15, 0.15, 0.95), color=(1, 1, 1, 0.95),
        )

        def _do_clear(instance):
            popup.dismiss()
            self._settings.clear_memories(self._settings.active_profile_name)
            self._update_system_prompt_live()
            self._refresh()
            if hasattr(self._app, '_status'):
                self._app._status.set_status("Memory cleared", "green")
                Clock.schedule_once(
                    lambda dt: self._app._status.set_status("Push to talk", "green"), 2.5
                )

        confirm_btn.bind(on_release=_do_clear)
        btn_row.add_widget(cancel_btn)
        btn_row.add_widget(confirm_btn)
        content.add_widget(btn_row)
        popup.open()

    def _on_clear_history_confirm(self):
        """Show confirmation before clearing history."""
        font = self._get_font()
        content = BoxLayout(orientation='vertical', spacing=14, padding=[20, 16])
        content.add_widget(Label(
            text="Clear all conversation history?",
            font_size='15sp',
            font_name=font,
            color=(0.9, 0.9, 0.9, 1),
            size_hint_y=None,
            height=32,
        ))

        popup = Popup(
            title="",
            separator_height=0,
            content=content,
            size_hint=(0.65, 0.28),
            background_color=(0.1, 0.1, 0.12, 0.98),
        )

        btn_row = BoxLayout(orientation='horizontal', spacing=10, size_hint_y=None, height=44)
        cancel_btn = Button(
            text="Cancel",
            font_size='14sp',
            font_name=font,
            background_normal='atlas://data/images/defaulttheme/button',
            background_color=(0.22, 0.22, 0.26, 1),
            color=(0.7, 0.7, 0.75, 1),
        )
        cancel_btn.bind(on_release=lambda x: popup.dismiss())

        confirm_btn = Button(
            text="Clear",
            font_size='14sp',
            font_name=font,
            background_normal='atlas://data/images/defaulttheme/button',
            background_color=(0.75, 0.15, 0.15, 0.95),
            color=(1, 1, 1, 0.95),
        )

        def _do_clear(instance):
            popup.dismiss()
            self._on_clear_history()

        confirm_btn.bind(on_release=_do_clear)

        btn_row.add_widget(cancel_btn)
        btn_row.add_widget(confirm_btn)
        content.add_widget(btn_row)
        popup.open()

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
        # Visual confirmation in status bar
        if hasattr(self._app, '_status'):
            self._app._status.set_status("History cleared!", "green")
            assistant = getattr(self._app, '_assistant', None)
            from zeina.enums import InteractionMode
            if assistant and assistant.mode == InteractionMode.CHAT:
                ready_msg = "Enter a message"
            else:
                ready_msg = "Push to talk"
            Clock.schedule_once(
                lambda dt, msg=ready_msg: self._app._status.set_status(msg, "green"), 2.5
            )

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
    def is_visible(self):
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


class _StyledSpinnerOption(Button):
    """Custom styled option for Spinner dropdowns."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ''
        self.background_color = (0.12, 0.13, 0.17, 0.98)
        self.color = (0.85, 0.88, 0.92, 1)
        self.font_size = '13sp'
        self.height = 42
        self.size_hint_y = None
