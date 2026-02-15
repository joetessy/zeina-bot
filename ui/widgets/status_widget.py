"""
Status bar widget for Zeina AI Assistant.

Three sections: mode label (left), status (center), model name (right).
All vertically centered on a single row.
"""
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.graphics import Color, RoundedRectangle
from kivy.properties import StringProperty


# Map Rich style names to RGBA
STYLE_COLORS = {
    "cyan": (0, 0.8, 0.8, 1),
    "green": (0.2, 0.85, 0.4, 1),
    "magenta": (0.85, 0.3, 0.75, 1),
    "red": (0.9, 0.25, 0.25, 1),
    "blue": (0.3, 0.5, 0.95, 1),
    "yellow": (0.95, 0.85, 0.2, 1),
    "dim": (0.5, 0.5, 0.5, 1),
    "white": (0.9, 0.9, 0.9, 1),
}


class StatusWidget(BoxLayout):
    """Displays mode, status, and model info in a single horizontal row."""

    mode_text = StringProperty("VOICE")
    status_text = StringProperty("")
    status_detail = StringProperty("")
    model_text = StringProperty("")

    def __init__(self, **kwargs):
        kwargs.setdefault('orientation', 'horizontal')
        kwargs.setdefault('size_hint_y', None)
        kwargs.setdefault('height', 52)
        kwargs.setdefault('padding', [14, 0])
        kwargs.setdefault('spacing', 10)
        super().__init__(**kwargs)

        with self.canvas.before:
            Color(0.1, 0.1, 0.12, 0.9)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[10])
        self.bind(pos=self._update_bg, size=self._update_bg)

        # Left: mode label
        self._mode_label = Label(
            text=self.mode_text,
            font_size='13sp',
            size_hint_x=0.2,
            color=STYLE_COLORS["green"],
            bold=True,
            halign='left',
            valign='middle',
        )
        self._mode_label.bind(size=self._mode_label.setter('text_size'))
        self.add_widget(self._mode_label)

        # Center: status text (single line, vertically centered)
        self._status_label = Label(
            text=self.status_text,
            font_size='13sp',
            size_hint_x=0.6,
            color=STYLE_COLORS["cyan"],
            halign='center',
            valign='middle',
        )
        self._status_label.bind(size=self._status_label.setter('text_size'))
        self.add_widget(self._status_label)

        # Right: model name
        self._model_label = Label(
            text=self.model_text,
            font_size='12sp',
            size_hint_x=0.2,
            color=STYLE_COLORS["cyan"],
            bold=True,
            halign='right',
            valign='middle',
        )
        self._model_label.bind(size=self._model_label.setter('text_size'))
        self.add_widget(self._model_label)

        # Bind properties to labels
        self.bind(mode_text=self._on_mode_text)
        self.bind(status_text=self._on_status_text)
        self.bind(model_text=self._on_model_text)

    def _update_bg(self, *args):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def _on_mode_text(self, instance, value):
        self._mode_label.text = value

    def _on_status_text(self, instance, value):
        self._status_label.text = value

    def _on_model_text(self, instance, value):
        self._model_label.text = value

    def set_status(self, message: str, style: str = "cyan"):
        # Strip emojis/unicode that Kivy can't render
        clean = message.encode('ascii', 'ignore').decode('ascii').strip()
        self.status_text = clean
        self._status_label.color = STYLE_COLORS.get(style, STYLE_COLORS["cyan"])

    def set_detail(self, message: str, style: str = "dim"):
        # Append detail to status as a suffix
        if message.strip():
            clean = message.encode('ascii', 'ignore').decode('ascii').strip()
            base = self.status_text.split("  |  ")[0]  # Remove previous detail
            self.status_text = f"{base}  |  {clean}"
        else:
            self.status_text = self.status_text.split("  |  ")[0]

    def set_mode(self, mode_str: str):
        if mode_str.lower() == "voice":
            self.mode_text = "VOICE"
            self._mode_label.color = STYLE_COLORS["green"]
        else:
            self.mode_text = "CHAT"
            self._mode_label.color = STYLE_COLORS["cyan"]

    def set_tool_log(self, message: str, style: str = "yellow"):
        """Show a tool log message in the center status label."""
        clean = message.encode('ascii', 'ignore').decode('ascii').strip()
        self.status_text = clean
        self._status_label.color = STYLE_COLORS.get(style, STYLE_COLORS["yellow"])

    def set_model(self, model_name: str):
        self.model_text = "ZEINA"
