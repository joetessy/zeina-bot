"""
Diagnostics overlay for Zeina AI Assistant.

Press Ctrl+D to toggle. Shows live system state: model, conversation length,
last tool used, and recent event log entries.
"""
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.textinput import TextInput
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.clock import Clock

from zeina import config


class DiagnosticsWidget(FloatLayout):
    """Full-screen overlay showing live assistant diagnostics."""

    is_visible = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Semi-transparent dark backdrop (full screen)
        with self.canvas.before:
            Color(0.04, 0.04, 0.06, 0.93)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(
            pos=lambda i, v: setattr(self._bg, 'pos', v),
            size=lambda i, v: setattr(self._bg, 'size', v),
        )

        # Inner panel (centred)
        panel = BoxLayout(
            orientation='vertical',
            spacing=8,
            padding=[20, 16],
            size_hint=(0.92, 0.88),
            pos_hint={'center_x': 0.5, 'center_y': 0.5},
        )

        # Solid background on the panel — prevents face-widget canvas from bleeding through
        with panel.canvas.before:
            Color(0.07, 0.08, 0.11, 0.98)
            self._panel_bg = RoundedRectangle(pos=panel.pos, size=panel.size, radius=[10])
        panel.bind(
            pos=lambda i, v: setattr(self._panel_bg, 'pos', v),
            size=lambda i, v: setattr(self._panel_bg, 'size', v),
        )

        # ── Header ──────────────────────────────────────────────
        header = BoxLayout(size_hint_y=None, height=44, spacing=6)
        header.add_widget(Label(
            text="DIAGNOSTICS",
            font_size='15sp',
            bold=True,
            color=(0.55, 0.85, 0.75, 1),
            halign='left',
            valign='middle',
            size_hint_x=1,
        ))
        refresh_btn = Button(
            text="Refresh",
            font_size='12sp',
            size_hint=(None, 1),
            width=76,
            background_normal='atlas://data/images/defaulttheme/button',
            background_color=(0.15, 0.22, 0.28, 1),
            color=(0.7, 0.85, 0.95, 1),
        )
        refresh_btn.bind(on_release=lambda _: self._repopulate(self._last_assistant))
        header.add_widget(refresh_btn)
        close_btn = Button(
            text="X",
            font_size='14sp',
            bold=True,
            size_hint=(None, 1),
            width=40,
            background_normal='atlas://data/images/defaulttheme/button',
            background_color=(0.28, 0.12, 0.12, 1),
            color=(0.9, 0.6, 0.6, 1),
        )
        close_btn.bind(on_release=lambda _: self.hide())
        header.add_widget(close_btn)
        panel.add_widget(header)

        # ── Info rows ────────────────────────────────────────────
        self._model_lbl = self._make_row("Model", "—")
        self._conv_lbl = self._make_row("Conversation", "—")
        self._tool_lbl = self._make_row("Last tool", "—")
        panel.add_widget(self._model_lbl[0])
        panel.add_widget(self._conv_lbl[0])
        panel.add_widget(self._tool_lbl[0])

        # ── Memory facts ──────────────────────────────────────────
        panel.add_widget(Label(
            text="Injected memory facts",
            font_size='11sp',
            color=(0.5, 0.55, 0.6, 1),
            size_hint_y=None,
            height=20,
            halign='left',
        ))
        self._memory_log = TextInput(
            text="(none)",
            font_size='12sp',
            readonly=True,
            foreground_color=(0.72, 0.78, 0.84, 1),
            background_color=(0.05, 0.06, 0.09, 1),
            cursor_color=(0, 0, 0, 0),
            size_hint_y=None,
            height=120,
            padding=[12, 10],
        )
        panel.add_widget(self._memory_log)

        # ── Event log ────────────────────────────────────────────
        panel.add_widget(Label(
            text="Recent events (newest at bottom)",
            font_size='11sp',
            color=(0.5, 0.55, 0.6, 1),
            size_hint_y=None,
            height=20,
            halign='left',
        ))

        # Outer container adds margin around the log box
        log_container = BoxLayout(
            size_hint_y=1,
            padding=[0, 4, 0, 8],
        )

        # TextInput (read-only) handles its own layout and scrolling cleanly.
        # No manual height management or binding cascade needed.
        self._event_log = TextInput(
            text="(no events yet)",
            font_size='12sp',
            readonly=True,
            foreground_color=(0.72, 0.78, 0.84, 1),
            background_color=(0.05, 0.06, 0.09, 1),
            cursor_color=(0, 0, 0, 0),
            size_hint_y=1,
            padding=[12, 10],
        )
        log_container.add_widget(self._event_log)
        panel.add_widget(log_container)

        self.add_widget(panel)
        self._last_assistant = None

    # ── Helpers ───────────────────────────────────────────────────

    def _make_row(self, label: str, value: str):
        """Return (row_widget, value_label) for a key/value info row."""
        row = BoxLayout(size_hint_y=None, height=30, spacing=10)
        row.add_widget(Label(
            text=label + ":",
            font_size='13sp',
            color=(0.6, 0.65, 0.72, 1),
            size_hint_x=0.35,
            halign='right',
            valign='middle',
        ))
        val_lbl = Label(
            text=value,
            font_size='13sp',
            color=(0.88, 0.92, 0.96, 1),
            size_hint_x=0.65,
            halign='left',
            valign='middle',
        )
        row.add_widget(val_lbl)
        return row, val_lbl

    def _repopulate(self, assistant):
        """Pull current values from the assistant object."""
        if assistant is None:
            return
        self._model_lbl[1].text = config.OLLAMA_MODEL
        self._conv_lbl[1].text = f"{len(assistant.conversation_history)} messages"
        self._tool_lbl[1].text = assistant._last_tool_used or "none"

        if hasattr(assistant, 'settings'):
            profile = assistant.settings.active_profile_name
            memory_enabled = assistant.settings.get("memory_enabled", True)
            if not memory_enabled:
                self._memory_log.text = "(memory disabled)"
            else:
                facts = assistant.settings.load_memories(profile)
                self._memory_log.text = (
                    "\n".join(f"• {f}" for f in facts) if facts else "(no facts yet)"
                )
        else:
            self._memory_log.text = "—"

        events = list(assistant.event_log)
        self._event_log.text = "\n".join(events) if events else "(no events yet)"

        # Move cursor to end so TextInput scrolls to show newest events
        def _scroll_to_end(dt):
            log = self._event_log
            log.cursor = log.get_cursor_from_index(len(log.text))
        Clock.schedule_once(_scroll_to_end, 0.05)

    # ── Public API ────────────────────────────────────────────────

    def refresh(self, assistant):
        """Snapshot assistant state and repopulate the panel."""
        self._last_assistant = assistant
        self._repopulate(assistant)

    def show(self):
        self.opacity = 1
        self.disabled = False
        DiagnosticsWidget.is_visible = True

    def hide(self):
        self.opacity = 0
        self.disabled = True
        DiagnosticsWidget.is_visible = False

    # ── Touch passthrough when hidden ────────────────────────────

    def on_touch_down(self, touch):
        if not self.is_visible:
            return False
        super().on_touch_down(touch)
        return True

    def on_touch_move(self, touch):
        if not self.is_visible:
            return False
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if not self.is_visible:
            return False
        return super().on_touch_up(touch)
