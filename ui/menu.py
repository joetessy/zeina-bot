"""Floating "..." dropdown menu: status bar / chat feed / mute / settings."""
from __future__ import annotations

from typing import TYPE_CHECKING

from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle
from kivy.uix.button import Button
from kivy.uix.dropdown import DropDown

from ui.icons import icon

if TYPE_CHECKING:
    from ui.app import ZeinaApp

MUTE_COLOR = (0.9, 0.4, 0.4, 0.9)


class DropdownMenu:
    """Icon-only dropdown attached to the floating menu button."""

    def __init__(self, app: "ZeinaApp") -> None:
        self._app = app
        self.dropdown = DropDown(auto_width=False, width=56)
        self._items: dict[str, Button] = {}
        self._bg_colors: dict[str, Color] = {}  # per-button bg for theme updates
        self._build()

    def _build(self) -> None:
        app = self._app
        theme = app._theme_manager.current_theme
        bg = theme.get("chat_input_bg", (0.10, 0.11, 0.14, 0.98))
        on_color = theme.get("face_sparkle", (0.55, 0.85, 0.75, 1))

        # (key, icon_name, fallback, callback, icon_size)
        items = [
            ("tools",    "monitor",     "[T]", app._toggle_status_bar, '22sp'),
            ("chat",     "chat",        "[C]", app._toggle_chat_feed,  '22sp'),
            ("audio",    "volume_high", "[V]", app._toggle_mute,       '22sp'),
            ("settings", "cog",         "[S]", app._open_settings,     '26sp'),
        ]

        for key, icon_name, fallback, callback, icon_size in items:
            icon_char = icon(icon_name, fallback)
            btn = Button(
                text=icon_char,
                font_name="Icons" if app._has_icons else "Roboto",
                font_size=icon_size if app._has_icons else '13sp',
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
                self._bg_colors[key] = color_instr
                btn._bg_rect = RoundedRectangle(pos=btn.pos, size=btn.size, radius=[4])
            btn.bind(
                pos=lambda inst, v: setattr(inst._bg_rect, 'pos', v),
                size=lambda inst, v: setattr(inst._bg_rect, 'size', v),
            )

            def _on_press(instance, cb=callback):
                cb()
                # Update icon colors in place — do NOT dismiss the dropdown
                Clock.schedule_once(lambda dt: self.update_status(), 0)

            btn.bind(on_release=_on_press)
            self._items[key] = btn
            self.dropdown.add_widget(btn)

    def open(self, trigger) -> None:
        """Open the dropdown menu, updating status indicators first."""
        self.update_status()
        self.dropdown.open(trigger)

    def dismiss(self) -> None:
        self.dropdown.dismiss()

    def update_status(self) -> None:
        """Update icon colors to reflect current toggle states."""
        app = self._app
        theme = app._theme_manager.current_theme
        on_color = theme.get("face_sparkle", (0.55, 0.85, 0.75, 1))
        off_color = theme.get("toggle_off_text", (0.5, 0.4, 0.4, 0.6))

        for key, btn in self._items.items():
            if key == "tools":
                btn.color = on_color if app._status_visible else off_color
                if app._has_icons:
                    btn.text = icon("monitor")
            elif key == "chat":
                btn.color = on_color if app._chat_visible else off_color
            elif key == "audio":
                muted = app._tts_muted
                btn.color = MUTE_COLOR if muted else on_color
                if app._has_icons:
                    btn.text = icon("volume_off") if muted else icon("volume_high")
            elif key == "settings":
                btn.color = on_color

    def apply_theme(self, theme: dict) -> None:
        """Update dropdown backgrounds and icon colors to match the theme."""
        bg = theme.get("chat_input_bg", (0.10, 0.11, 0.14, 0.98))
        for color_instr in self._bg_colors.values():
            color_instr.rgba = bg
        self.update_status()
