"""Building-block widgets for the settings screen: rows, headers, dividers."""
from __future__ import annotations

from typing import NamedTuple

from kivy.graphics import Color, Rectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.widget import Widget


class ThemeColors(NamedTuple):
    """Colors + font pulled from the active theme for settings widgets."""
    accent: tuple
    bg_off: tuple
    text_on: tuple
    text_off: tuple
    section: tuple
    panel_bg: tuple
    font: str


class SettingRow(BoxLayout):
    """A single setting row: label on left, control on right.
    Even-indexed rows get a subtly lighter background for scannability."""

    def __init__(self, label_text: str, font_name: str = "Roboto",
                 even: bool = False, **kwargs):
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

    def __init__(self, text: str, color=None, font_name: str = "Roboto", **kwargs):
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


class StyledSpinnerOption(Button):
    """Custom styled option for Spinner dropdowns."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ''
        self.background_color = (0.12, 0.13, 0.17, 0.98)
        self.color = (0.85, 0.88, 0.92, 1)
        self.font_size = '13sp'
        self.height = 42
        self.size_hint_y = None
