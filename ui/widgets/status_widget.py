"""
Status bar widget for Zeina AI Assistant.

Mode pill (left) · status (center) · bot name (right).
Monospace font, all-caps status, separator dots between sections.
"""
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.label import Label
from kivy.graphics import Color, RoundedRectangle
from kivy.properties import StringProperty


# Map Rich style names to RGBA
STYLE_COLORS = {
    "cyan":    (0,    0.80, 0.80, 1),
    "green":   (0.20, 0.85, 0.40, 1),
    "magenta": (0.85, 0.30, 0.75, 1),
    "red":     (0.90, 0.25, 0.25, 1),
    "blue":    (0.30, 0.50, 0.95, 1),
    "yellow":  (0.95, 0.85, 0.20, 1),
    "dim":     (0.50, 0.50, 0.50, 1),
    "white":   (0.90, 0.90, 0.90, 1),
}

# Pill badge colors per mode
_BADGE_VOICE = (0.20, 0.85, 0.40, 1)   # green
_BADGE_CHAT  = (0.30, 0.50, 0.95, 1)   # blue
_BADGE_TEXT  = (0.04, 0.08, 0.06, 1)   # very dark — readable on both pill colors
_SEP_COLOR   = (0.35, 0.38, 0.42, 0.7)


class StatusWidget(BoxLayout):
    """Displays mode pill, status, and bot name in a single horizontal row."""

    mode_text   = StringProperty("VOICE")
    status_text = StringProperty("")
    model_text  = StringProperty("")

    def __init__(self, **kwargs):
        kwargs.setdefault('orientation', 'horizontal')
        kwargs.setdefault('size_hint_y', None)
        kwargs.setdefault('height', 74)
        kwargs.setdefault('padding', [14, 10])
        kwargs.setdefault('spacing', 6)
        super().__init__(**kwargs)

        with self.canvas.before:
            Color(0.1, 0.1, 0.12, 0.9)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[10])
        self.bind(pos=self._update_bg, size=self._update_bg)

        # ── Left: mode pill badge ──────────────────────────────
        self._mode_anchor = AnchorLayout(
            anchor_x='left',
            anchor_y='center',
            size_hint_x=None,
            width=98,
        )
        self._mode_badge = BoxLayout(
            size_hint=(None, None),
            size=(90, 38),
            padding=[18, 8, 18, 8],
        )
        with self._mode_badge.canvas.before:
            self._badge_color = Color(*_BADGE_VOICE)
            self._badge_bg = RoundedRectangle(
                pos=self._mode_badge.pos,
                size=self._mode_badge.size,
                radius=[19],
            )
        self._mode_badge.bind(
            pos=lambda i, v: setattr(self._badge_bg, 'pos', v),
            size=lambda i, v: setattr(self._badge_bg, 'size', v),
        )
        self._mode_label = Label(
            text='VOICE',
            font_size='11sp',
            font_name='Mono',
            color=_BADGE_TEXT,
            bold=True,
        )
        # No text_size binding — text renders on a single line naturally
        self._mode_badge.add_widget(self._mode_label)
        self._mode_anchor.add_widget(self._mode_badge)
        self.add_widget(self._mode_anchor)

        # ── Separator (spacer, no dot)  ───────────────────────
        self._sep1 = Label(
            text='',
            font_size='13sp',
            font_name='Mono',
            size_hint_x=None,
            width=0,
            color=_SEP_COLOR,
            halign='center',
            valign='middle',
        )
        self._sep1.bind(size=self._sep1.setter('text_size'))
        self.add_widget(self._sep1)

        # ── Center: status text ───────────────────────────────
        self._status_label = Label(
            text='',
            font_size='12sp',
            font_name='Mono',
            size_hint_x=1,
            color=STYLE_COLORS["cyan"],
            halign='center',
            valign='middle',
        )
        self._status_label.bind(size=self._status_label.setter('text_size'))
        self.add_widget(self._status_label)

        # ── Separator (spacer, no dot)  ───────────────────────
        self._sep2 = Label(
            text='',
            font_size='13sp',
            font_name='Mono',
            size_hint_x=None,
            width=0,
            color=_SEP_COLOR,
            halign='center',
            valign='middle',
        )
        self._sep2.bind(size=self._sep2.setter('text_size'))
        self.add_widget(self._sep2)

        # ── Right: bot name ────────────────────────────────────
        self._model_label = Label(
            text='',
            font_size='12sp',
            font_name='Mono',
            size_hint_x=None,
            width=0,
            color=STYLE_COLORS["cyan"],
            bold=True,
        )
        # Width tracks the rendered text size — label is always exactly as wide as its content
        self._model_label.bind(
            texture_size=self._update_model_width
        )
        self.add_widget(self._model_label)

        # Bind Kivy properties → labels
        self.bind(status_text=self._on_status_text)
        self.bind(model_text=self._on_model_text)

        # Component visibility state
        self._mode_visible  = True
        self._model_visible = True
        self._tool_log_enabled = True

    # ── Canvas ────────────────────────────────────────────────

    def _update_model_width(self, instance, texture_size):
        instance.width = texture_size[0] if self._model_visible else 0

    def _update_bg(self, *args):
        self._bg.pos = self.pos
        self._bg.size = self.size

    # ── Property callbacks ────────────────────────────────────

    def _on_status_text(self, instance, value):
        self._status_label.text = value.upper() if value else ''

    def _on_model_text(self, instance, value):
        self._model_label.text = value

    # ── Public setters ────────────────────────────────────────

    def set_status(self, message: str, style: str = "cyan"):
        clean = message.encode('ascii', 'ignore').decode('ascii').strip()
        self.status_text = clean   # _on_status_text uppercases on display
        self._status_label.color = STYLE_COLORS.get(style, STYLE_COLORS["cyan"])

    def set_detail(self, message: str, style: str = "dim"):
        if message.strip():
            clean = message.encode('ascii', 'ignore').decode('ascii').strip()
            base = self.status_text.split("  |  ")[0]
            self.status_text = f"{base}  |  {clean}"
        else:
            self.status_text = self.status_text.split("  |  ")[0]

    def set_mode(self, mode_str: str):
        if mode_str.lower() == "voice":
            self._mode_label.text = "VOICE"
            self._badge_color.rgba = _BADGE_VOICE
        else:
            self._mode_label.text = "CHAT"
            self._badge_color.rgba = _BADGE_CHAT
        self.mode_text = self._mode_label.text

    def set_tool_log(self, message: str, style: str = "yellow"):
        if not self._tool_log_enabled:
            return
        clean = message.encode('ascii', 'ignore').decode('ascii').strip()
        self.status_text = clean
        self._status_label.color = STYLE_COLORS.get(style, STYLE_COLORS["yellow"])

    def set_model(self, model_name: str):
        self.model_text = model_name.upper() if model_name else "ZEINA"

    # ── Component visibility ──────────────────────────────────

    def set_mode_visible(self, visible: bool):
        self._mode_visible = visible
        self._mode_anchor.opacity = 1 if visible else 0
        self._mode_anchor.width   = 98 if visible else 0
        self._sep1.opacity = 0
        self._sep1.width   = 0

    def set_model_visible(self, visible: bool):
        self._model_visible = visible
        self._model_label.opacity = 1 if visible else 0
        self._model_label.width = self._model_label.texture_size[0] if visible else 0
        self._sep2.opacity = 0
        self._sep2.width   = 0

    def set_tool_log_enabled(self, enabled: bool):
        self._tool_log_enabled = enabled

    def apply_theme(self, theme_dict):
        bg_color = theme_dict.get("status_bg", (0.1, 0.1, 0.12, 0.9))
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*bg_color)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[10])
        self.bind(pos=self._update_bg, size=self._update_bg)

        accent = theme_dict.get("accent", (0.18, 0.58, 0.52, 1))
        self._status_label.color = accent
        self._model_label.color  = accent

        font_name = theme_dict.get("font_name", "Mono")
        self._mode_label.font_name   = font_name
        self._status_label.font_name = font_name
        self._model_label.font_name  = font_name
        self._sep1.font_name = font_name
        self._sep2.font_name = font_name
