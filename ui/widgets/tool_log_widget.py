"""
Tool log widget for Zeina AI Assistant.

A slim strip that shows the most recent tool call / info message,
positioned below the status bar and independent of the chat area.
"""
import time

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.graphics import Color, RoundedRectangle
from kivy.clock import Clock


ROLE_COLORS = {
    "info": (0.55, 0.75, 0.7, 1),
    "error": (0.95, 0.4, 0.4, 1),
}


class ToolLogWidget(BoxLayout):
    """Single-line strip showing the latest tool/info message."""

    def __init__(self, **kwargs):
        kwargs.setdefault('orientation', 'horizontal')
        kwargs.setdefault('size_hint_y', None)
        kwargs.setdefault('height', 44)
        kwargs.setdefault('padding', [14, 6])
        super().__init__(**kwargs)

        with self.canvas.before:
            Color(0.09, 0.11, 0.13, 0.85)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[8])
        self.bind(pos=self._update_bg, size=self._update_bg)

        self._label = Label(
            text="",
            font_size='12sp',
            color=ROLE_COLORS["info"],
            halign='center',
            valign='middle',
        )
        self._label.bind(size=self._label.setter('text_size'))
        self.add_widget(self._label)

    def _update_bg(self, *args):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def show_message(self, text: str, role: str = "info"):
        """Update the displayed message with timestamp. Thread-safe via Clock."""
        # Strip emojis that Kivy can't render
        clean = text.encode('ascii', 'ignore').decode('ascii').strip()
        timestamp = time.strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {clean}"
        color = ROLE_COLORS.get(role, ROLE_COLORS["info"])
        def _update(dt):
            self._label.text = formatted
            self._label.color = color
        Clock.schedule_once(_update, 0)

    def clear(self):
        def _clear(dt):
            self._label.text = ""
        Clock.schedule_once(_clear, 0)
