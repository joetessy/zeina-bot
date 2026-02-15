"""
Toggle panel for Zeina AI Assistant.

Toggle buttons for face/status/tools/chat/speaking + preset buttons.
"""
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.graphics import Color, RoundedRectangle


# Preset definitions
PRESETS = {
    "clean": {
        "face": True,
        "status": True,
        "tool_log": True,
        "chat": False,
        "speaking": True,
    },
    "silent": {
        "chat": True,
        "speaking": False,
    },
}

# Colors
ON_COLOR = (0.18, 0.58, 0.52, 1)
OFF_COLOR = (0.2, 0.2, 0.24, 1)
ON_TEXT = (1, 1, 1, 0.95)
OFF_TEXT = (0.55, 0.55, 0.6, 0.9)


class TogglePanel(BoxLayout):
    """Panel with toggle buttons for each UI element and preset buttons."""

    def __init__(self, on_toggle_changed=None, **kwargs):
        kwargs.setdefault('orientation', 'horizontal')
        kwargs.setdefault('size_hint_y', None)
        kwargs.setdefault('height', 40)
        kwargs.setdefault('spacing', 6)
        kwargs.setdefault('padding', [10, 5])
        super().__init__(**kwargs)

        self._on_toggle_changed = on_toggle_changed

        with self.canvas.before:
            Color(0.07, 0.08, 0.1, 0.9)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[4])
        self.bind(pos=self._update_bg, size=self._update_bg)

        # Toggle buttons
        self._toggles = {}
        toggle_items = [
            ("face", "Face"),
            ("status", "Status"),
            ("tool_log", "Tool Log"),
            ("chat", "Chat"),
            ("speaking", "TTS"),
        ]

        for key, label_text in toggle_items:
            btn = ToggleButton(
                text=label_text,
                state='down',
                size_hint_x=1,
                font_size='11sp',
                background_normal='atlas://data/images/defaulttheme/button',
                background_down='atlas://data/images/defaulttheme/button_pressed',
                background_color=ON_COLOR,
                color=ON_TEXT,
            )
            btn._toggle_key = key
            btn.bind(state=self._on_toggle)
            self._toggles[key] = btn
            self.add_widget(btn)

        # Separator
        sep = Label(text="", size_hint_x=0.05)
        self.add_widget(sep)

        # Preset buttons
        for name, label_text in [("clean", "Clean"), ("silent", "Silent")]:
            btn = Button(
                text=label_text,
                size_hint_x=0.7,
                font_size='11sp',
                background_normal='atlas://data/images/defaulttheme/button',
                background_color=(0.22, 0.48, 0.44, 1),
                color=(0.9, 0.95, 0.92, 0.95),
            )
            btn.bind(on_release=lambda x, n=name: self.apply_preset(n))
            self.add_widget(btn)

    def _update_bg(self, *args):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def _on_toggle(self, instance, state):
        key = instance._toggle_key
        is_on = state == 'down'
        instance.background_color = ON_COLOR if is_on else OFF_COLOR
        instance.color = ON_TEXT if is_on else OFF_TEXT

        if self._on_toggle_changed:
            self._on_toggle_changed(key, is_on)

    def apply_preset(self, preset_name: str):
        """Apply a toggle preset."""
        preset = PRESETS.get(preset_name, {})
        for key, value in preset.items():
            btn = self._toggles.get(key)
            if btn:
                btn.state = 'down' if value else 'normal'

    def set_toggle_state(self, key: str, is_on: bool):
        """Programmatically set a toggle button's state."""
        btn = self._toggles.get(key)
        if btn:
            btn.state = 'down' if is_on else 'normal'

    def get_toggles(self) -> dict:
        """Return current toggle states as a dict."""
        return {
            key: btn.state == 'down'
            for key, btn in self._toggles.items()
        }
