"""Row-builder mixin for the settings screen.

Each ``add_*`` method appends one themed setting row (text input, slider,
toggle, spinner, ...) to a parent layout and wires persistence through
``self._settings``. The host class must provide ``_settings``, ``_app``,
``_next_even()``, ``_get_theme_colors()``, ``_update_system_prompt_live()``,
``_reload_tts()``, ``_apply_status_bar_component()``, and
``_on_bot_name_changed()`` (see screen.SettingsScreen).
"""
from __future__ import annotations

import math
import os
from typing import Callable, Optional

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.slider import Slider
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.graphics import Color, RoundedRectangle

from zeina import config
from ui.widgets.settings.rows import SettingRow, StyledSpinnerOption


class SettingBuildersMixin:
    """Reusable builders for the individual setting rows."""

    # ── Text inputs ──────────────────────────────────────────────

    def add_text_setting(self, parent, label: str, key: str, value: str,
                         font: str = "Roboto") -> None:
        colors = self._get_theme_colors()
        row = SettingRow(label, font_name=font, even=self._next_even(), height=66)
        inp = TextInput(
            text=str(value),
            multiline=False,
            size_hint_x=0.62,
            size_hint_y=None,
            font_size='14sp',
            font_name=font,
            background_color=(colors.bg_off[0] - 0.01, colors.bg_off[1] - 0.01,
                              colors.bg_off[2] - 0.01, 1),
            foreground_color=(0.9, 0.92, 0.95, 1),
            cursor_color=(colors.accent[0], colors.accent[1], colors.accent[2], 1),
            padding=[12, 10],
            pos_hint={'center_y': 0.5},
        )
        inp.bind(minimum_height=inp.setter('height'))

        def _on_change(instance) -> None:
            val = instance.text.strip()
            self._settings.set(key, val)
            if key == "bot_name":
                self._on_bot_name_changed(val)
            elif key == "user_name":
                _name_keywords = ("name is", "called ", "known as", "goes by")
                for fact in self._settings.load_memories(self._settings.active_profile_name):
                    if any(kw in fact.lower() for kw in _name_keywords):
                        self._settings.remove_memory(self._settings.active_profile_name, fact)
                self._update_system_prompt_live()

        # Commit on Enter or focus loss only — a per-keystroke binding would
        # write the profile to disk (and rescan memories) on every character.
        inp.bind(on_text_validate=_on_change)
        inp.bind(focus=lambda inst, focused: _on_change(inst) if not focused else None)
        row.add_widget(inp)
        parent.add_widget(row)

    def add_multiline_setting(self, parent, label: str, key: str, value: str,
                              font: str = "Roboto") -> None:
        """A tall multiline TextInput for free-form text (custom instructions etc.)."""
        colors = self._get_theme_colors()
        row = SettingRow(label, font_name=font, even=self._next_even(), height=110)

        inp = TextInput(
            text=str(value),
            multiline=True,
            size_hint_x=0.62,
            size_hint_y=None,
            height=96,
            font_size='13sp',
            font_name=font,
            background_color=(colors.bg_off[0] - 0.01, colors.bg_off[1] - 0.01,
                              colors.bg_off[2] - 0.01, 1),
            foreground_color=(0.9, 0.92, 0.95, 1),
            cursor_color=(colors.accent[0], colors.accent[1], colors.accent[2], 1),
            padding=[12, 10],
            pos_hint={'center_y': 0.5},
        )

        def _on_change(instance) -> None:
            self._settings.set(key, instance.text)
            self._update_system_prompt_live()

        inp.bind(focus=lambda inst, focused: _on_change(inst) if not focused else None)
        row.add_widget(inp)
        parent.add_widget(row)

    # ── Sliders ──────────────────────────────────────────────────

    def _make_slider_row(self, parent, label: str, min_val, max_val, step, value,
                         suffix: str, font: str,
                         on_value: Callable[[float, Label], None]) -> None:
        """Shared slider row scaffolding; ``on_value`` handles persistence."""
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
        slider.bind(value=lambda instance, val: on_value(val, value_label))
        slider_box.add_widget(slider)
        slider_box.add_widget(value_label)
        row.add_widget(slider_box)
        parent.add_widget(row)

    def add_slider(self, parent, label: str, key: str, min_val, max_val, step, value,
                   suffix: str, font: str = "Roboto",
                   post_callback: Optional[Callable[[], None]] = None) -> None:
        """Per-profile slider persisted via settings + apply_to_config."""
        def _on_value(val: float, value_label: Label) -> None:
            if isinstance(step, float) and step < 1:
                value_label.text = f"{val:.1f}{suffix}"
                self._settings.set(key, round(val, 1))
            else:
                value_label.text = f"{int(val)}{suffix}"
                self._settings.set(key, int(val))
            self._settings.apply_to_config()
            if post_callback:
                post_callback()

        self._make_slider_row(parent, label, min_val, max_val, step, value,
                              suffix, font, _on_value)

    def add_global_slider(self, parent, label: str, config_attr: str,
                          min_val, max_val, step, value, suffix: str,
                          font: str = "Roboto") -> None:
        """Slider that updates a global config value shared across all profiles."""
        def _on_value(val: float, value_label: Label) -> None:
            int_val = int(val)
            value_label.text = f"{int_val}{suffix}"
            setattr(config, config_attr.upper(), int_val)
            self._settings.set_all_profiles(config_attr, int_val)

        self._make_slider_row(parent, label, min_val, max_val, step, value,
                              suffix, font, _on_value)

    # ── Toggles & choice buttons ─────────────────────────────────

    def add_toggle_group(self, parent, label: str, key: str, options: list[str],
                         current: str, font: str = "Roboto",
                         post_callback: Optional[Callable[[], None]] = None) -> None:
        colors = self._get_theme_colors()
        row = SettingRow(label, font_name=font, even=self._next_even())
        btn_box = BoxLayout(orientation='horizontal', size_hint_x=0.62, spacing=6)

        def _make_handler(opt: str, buttons: list[Button]):
            def _handler(instance) -> None:
                self._settings.set(key, opt)
                self._settings.apply_to_config()
                for b in buttons:
                    b.background_color = colors.bg_off
                    b.color = colors.text_off
                instance.background_color = colors.accent
                instance.color = colors.text_on
                if post_callback:
                    post_callback()
            return _handler

        buttons: list[Button] = []
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
                background_color=colors.accent if is_active else colors.bg_off,
                color=colors.text_on if is_active else colors.text_off,
            )
            buttons.append(btn)
            btn_box.add_widget(btn)

        for opt, btn in zip(options, buttons):
            btn.bind(on_release=_make_handler(opt, buttons))

        row.add_widget(btn_box)
        parent.add_widget(row)

    def add_toggle_setting(self, parent, label: str, key: str, value: bool,
                           font: str = "Roboto") -> None:
        colors = self._get_theme_colors()
        row = SettingRow(label, font_name=font, even=self._next_even())
        btn = Button(
            text="ON" if value else "OFF",
            size_hint_x=0.62,
            size_hint_y=None,
            height=38,
            font_size='13sp',
            font_name=font,
            background_normal='atlas://data/images/defaulttheme/button',
            background_color=colors.accent if value else colors.bg_off,
            color=colors.text_on if value else colors.text_off,
        )

        def _toggle(instance) -> None:
            new_val = not self._settings.get(key, False)
            self._settings.set(key, new_val)
            self._settings.apply_to_config()
            instance.text = "ON" if new_val else "OFF"
            instance.background_color = colors.accent if new_val else colors.bg_off
            instance.color = colors.text_on if new_val else colors.text_off
            self._apply_status_bar_component(key, new_val)

        btn.bind(on_release=_toggle)
        row.add_widget(btn)
        parent.add_widget(row)

    def add_choice_buttons(self, parent, label: str, key: str, options: list[str],
                           current: str, callback: Optional[Callable[[str], None]] = None,
                           value_labels: Optional[dict[str, str]] = None,
                           font: str = "Roboto", cols: Optional[int] = None) -> None:
        colors = self._get_theme_colors()

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

        def _make_handler(opt: str, buttons: list[Button]):
            def _handler(instance) -> None:
                self._settings.set(key, opt)
                for b in buttons:
                    b.background_color = colors.bg_off
                    b.color = colors.text_off
                instance.background_color = colors.accent
                instance.color = colors.text_on
                if callback:
                    callback(opt)
            return _handler

        buttons: list[Button] = []
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
                background_color=colors.accent if is_active else colors.bg_off,
                color=colors.text_on if is_active else colors.text_off,
            )
            buttons.append(btn)
            btn_box.add_widget(btn)

        for opt, btn in zip(options, buttons):
            btn.bind(on_release=_make_handler(opt, buttons))

        row.add_widget(btn_box)
        parent.add_widget(row)

    # ── Spinners ─────────────────────────────────────────────────

    def _make_spinner_row(self, parent, label: str, values: list[str], current: str,
                          on_select: Callable[[str], None], font: str,
                          font_size: str = '13sp') -> Spinner:
        colors = self._get_theme_colors()
        row = SettingRow(label, font_name=font, even=self._next_even())
        spinner = Spinner(
            text=current,
            values=values,
            size_hint_x=0.62,
            size_hint_y=None,
            height=44,
            font_size=font_size,
            font_name=font,
            background_normal='',
            background_color=colors.bg_off,
            color=colors.text_on,
            option_cls=StyledSpinnerOption,
        )
        spinner.bind(text=lambda instance, val: on_select(val))
        row.add_widget(spinner)
        parent.add_widget(row)
        return spinner

    def add_model_spinner(self, parent, label: str, key: str, current: str,
                          font: str = "Roboto") -> None:
        models = [current]
        try:
            from zeina import llm
            model_names = llm.list_model_ids()
            if model_names:
                models = model_names
                if current not in models:
                    models.insert(0, current)
        except Exception:
            pass

        def _on_select(val: str) -> None:
            self._settings.set(key, val)
            self._settings.apply_to_config()

        self._make_spinner_row(parent, label, models, current, _on_select, font)

    def add_voice_spinner(self, parent, label: str, key: str, current: str,
                          font: str = "Roboto") -> None:
        models_dir = os.path.join(config.PROJECT_ROOT, "models")
        voices: list[str] = []
        if os.path.isdir(models_dir):
            for f in os.listdir(models_dir):
                if f.endswith(".onnx"):
                    voices.append(f"models/{f}")
        if not voices:
            voices = [current] if current else ["(none)"]
        if current and current not in voices:
            voices.insert(0, current)

        def _on_select(val: str) -> None:
            self._settings.set(key, val)
            self._settings.apply_to_config()
            # Reload TTS engine with new voice immediately
            self._reload_tts(val)

        self._make_spinner_row(parent, label, voices, current or "(none)",
                               _on_select, font, font_size='12sp')

    # ── Misc rows ────────────────────────────────────────────────

    def add_action_button(self, parent, label: str, callback: Callable[[], None],
                          color=(0.18, 0.52, 0.46, 1), font: str = "Roboto") -> None:
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

    def add_info_label(self, parent, label: str, value_text: str,
                       font: str = "Roboto") -> Label:
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
