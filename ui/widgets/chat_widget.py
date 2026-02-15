"""
Chat widget for Zeina AI Assistant.

ScrollView with messenger-style bubbles + TextInput for chat mode.
Uses threading.Event pattern for blocking chat input from the pipeline thread.
"""
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.graphics import Color, RoundedRectangle, Rectangle
from kivy.clock import Clock
import threading


# Modern dark palette, teal accent to match BMO theme
BUBBLE_COLORS = {
    "user": (0.11, 0.44, 0.40, 0.92),       # Teal accent
    "assistant": (0.12, 0.13, 0.17, 0.92),   # Cool dark
    "info": (0.10, 0.12, 0.15, 0.50),        # Near-invisible
    "error": (0.58, 0.18, 0.18, 0.80),       # Soft coral
}

TEXT_COLORS = {
    "user": (0.95, 1, 0.98, 1),
    "assistant": (0.82, 0.86, 0.90, 1),
    "info": (0.50, 0.55, 0.60, 0.9),
    "error": (1, 0.70, 0.68, 1),
}

# Messenger-style rounded corners per role
BUBBLE_RADII = {
    "user": [16, 4, 16, 16],        # flat top-right (tail side)
    "assistant": [4, 16, 16, 16],    # flat top-left (tail side)
    "info": [10, 10, 10, 10],
    "error": [10, 10, 10, 10],
}

# Max bubble width as fraction of parent
BUBBLE_MAX_WIDTH = 0.68


class MessageBubble(BoxLayout):
    """A single chat message bubble with rounded background."""

    def __init__(self, text: str, role: str = "assistant", **kwargs):
        kwargs.setdefault('orientation', 'vertical')
        kwargs.setdefault('size_hint_y', None)
        super().__init__(**kwargs)

        self._role = role
        bg_color = BUBBLE_COLORS.get(role, BUBBLE_COLORS["assistant"])
        txt_color = TEXT_COLORS.get(role, TEXT_COLORS["assistant"])
        radii = BUBBLE_RADII.get(role, [16, 16, 16, 16])

        self.padding = [14, 8, 14, 8]

        with self.canvas.before:
            Color(*bg_color)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=radii)
        self.bind(pos=self._update_bg, size=self._update_bg)

        self._label = Label(
            text=text,
            font_size='14sp',
            color=txt_color,
            markup=False,
            halign='left',
            valign='top',
            size_hint_y=None,
            text_size=(None, None),
        )
        self._label.bind(texture_size=self._on_texture_size)
        self.add_widget(self._label)
        self.bind(width=self._update_text_width)

    def _update_bg(self, *args):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def _update_text_width(self, *args):
        pad_h = self.padding[0] + self.padding[2]
        self._label.text_size = (max(self.width - pad_h, 80), None)

    def _on_texture_size(self, instance, size):
        instance.height = size[1]
        pad_v = self.padding[1] + self.padding[3]
        self.height = size[1] + pad_v


class _BubbleRow(AnchorLayout):
    """Wrapper that anchors a bubble left or right within the full-width row."""

    def __init__(self, role: str, **kwargs):
        if role == "user":
            anchor_x = 'right'
        elif role in ("info", "error"):
            anchor_x = 'center'
        else:
            anchor_x = 'left'

        kwargs.setdefault('size_hint_y', None)
        kwargs.setdefault('anchor_x', anchor_x)
        kwargs.setdefault('anchor_y', 'top')
        super().__init__(**kwargs)


class ChatWidget(BoxLayout):
    """Chat area with scrollable message list and text input."""

    def __init__(self, **kwargs):
        kwargs.setdefault('orientation', 'vertical')
        kwargs.setdefault('spacing', 0)
        super().__init__(**kwargs)

        # Message container inside a scroll view, wrapped in anchor for top-pinning
        self._scroll = ScrollView(
            do_scroll_x=False,
            bar_width=3,
            bar_color=(0.4, 0.7, 0.65, 0.35),
            bar_inactive_color=(0.3, 0.5, 0.45, 0.15),
        )
        self._message_box = BoxLayout(
            orientation='vertical',
            size_hint_y=None,
            spacing=12,
            padding=[8, 12],
        )
        self._message_box.bind(minimum_height=self._message_box.setter('height'))
        self._message_box.bind(minimum_height=self._on_content_changed)
        self._stick_to_bottom = True

        # Anchor wrapper pins messages to top when content is shorter than viewport
        self._anchor = AnchorLayout(
            anchor_y='top',
            size_hint_y=None,
        )
        self._anchor.add_widget(self._message_box)
        self._scroll.add_widget(self._anchor)
        self._scroll.bind(height=self._sync_anchor_height)
        self._message_box.bind(height=self._sync_anchor_height)
        self.add_widget(self._scroll)

        # Input container with background and padding (shown in chat mode)
        self._input_container = BoxLayout(
            size_hint_y=None,
            height=0,
            padding=[12, 8, 12, 10],
        )
        with self._input_container.canvas.before:
            Color(0.1, 0.1, 0.12, 0.95)
            self._input_bg = Rectangle(
                pos=self._input_container.pos,
                size=self._input_container.size,
            )
        self._input_container.bind(
            pos=self._update_input_bg,
            size=self._update_input_bg,
        )

        # Text input field
        self._input = TextInput(
            hint_text="Type a message...",
            size_hint_y=None,
            height=52,
            multiline=False,
            background_color=(0.16, 0.18, 0.22, 1),
            foreground_color=(0.92, 0.94, 0.96, 1),
            hint_text_color=(0.45, 0.48, 0.52, 0.8),
            cursor_color=(0.3, 0.85, 0.7, 1),
            padding=[14, 6, 14, 6],
            font_size='16sp',
        )
        self._input.bind(on_text_validate=self._on_submit)
        self.add_widget(self._input_container)

        # Threading for blocking get_chat_input
        self._input_event = threading.Event()
        self._input_result = None
        self._waiting_for_input = False
        self._input_cancelled = False

    def _update_input_bg(self, *args):
        self._input_bg.pos = self._input_container.pos
        self._input_bg.size = self._input_container.size

    def show_input(self):
        """Show the text input field."""
        self._input_container.height = 70
        if self._input.parent != self._input_container:
            if self._input.parent:
                self._input.parent.remove_widget(self._input)
            self._input_container.add_widget(self._input)
        # If stream is hidden, resize to fit just the input
        if self._scroll.opacity == 0:
            self.size_hint_y = None
            self.height = 70
        Clock.schedule_once(lambda dt: setattr(self._input, 'focus', True), 0.1)

    def hide_input(self):
        """Hide the text input field."""
        self._input_container.height = 0
        if self._input.parent == self._input_container:
            self._input_container.remove_widget(self._input)
        # If stream is also hidden, collapse completely
        if self._scroll.opacity == 0:
            self.size_hint_y = None
            self.height = 0

    def _on_submit(self, instance):
        text = instance.text.strip()
        instance.text = ""
        if self._waiting_for_input and text:
            self._input_result = text
            self._input_event.set()
        elif text:
            if self._on_message_callback:
                self._on_message_callback(text)

    _on_message_callback = None

    def set_message_callback(self, callback):
        """Set callback for when user submits a message directly."""
        self._on_message_callback = callback

    def add_message(self, text: str, role: str = "assistant"):
        """Add a messenger-style bubble to the chat. Thread-safe via Clock."""
        def _add(dt):
            bubble = MessageBubble(text=text, role=role)

            # Wrap in an anchor row for left/right alignment
            row = _BubbleRow(role=role)

            # User/assistant bubbles cap at max width; info/error stay full
            if role in ("user", "assistant"):
                bubble.size_hint_x = BUBBLE_MAX_WIDTH
            else:
                bubble.size_hint_x = 1

            row.add_widget(bubble)

            # Sync row height to bubble height
            def _sync_h(inst, h):
                row.height = h
            bubble.bind(height=_sync_h)
            # Set initial height if already computed
            if bubble.height > 0:
                row.height = bubble.height

            self._stick_to_bottom = True
            self._message_box.add_widget(row)
        Clock.schedule_once(_add, 0)

    def _sync_anchor_height(self, *args):
        """Ensure anchor wrapper is at least as tall as viewport so messages pin to top."""
        self._anchor.height = max(self._message_box.height, self._scroll.height)

    def _on_content_changed(self, *args):
        """Auto-scroll to bottom when content grows (unless user scrolled up)."""
        if self._stick_to_bottom:
            # Schedule after layout pass to ensure heights are final
            Clock.schedule_once(self._do_scroll_bottom, 0)
            Clock.schedule_once(self._do_scroll_bottom, 0.1)

    def _do_scroll_bottom(self, *args):
        self._scroll.scroll_y = 0

    def _scroll_to_bottom(self):
        self._stick_to_bottom = True
        self._scroll.scroll_y = 0

    def get_chat_input(self, prompt: str) -> str:
        """Block the calling thread until user submits text. Returns the text or None if cancelled.
        Must NOT be called from the Kivy main thread."""
        self._input_event.clear()
        self._input_result = None
        self._waiting_for_input = True
        self._input_cancelled = False

        Clock.schedule_once(lambda dt: self.show_input(), 0)
        Clock.schedule_once(lambda dt: setattr(self._input, 'hint_text', prompt), 0)

        self._input_event.wait()
        self._waiting_for_input = False

        if self._input_cancelled:
            return None

        return self._input_result

    def cancel_input(self):
        """Unblock get_chat_input so the chat thread can exit. Called on mode switch."""
        self._input_cancelled = True
        self._input_event.set()

    def set_stream_visible(self, visible):
        """Show/hide the message scroll area. When hidden the widget shrinks
        so the face can take the space, but the input stays unaffected."""
        if visible:
            self._scroll.opacity = 1
            self._scroll.size_hint_y = 1
            self.size_hint_y = 1.2
        else:
            self._scroll.opacity = 0
            self._scroll.size_hint_y = 0.001
            # Shrink to just fit the input (or nothing if input hidden)
            self.size_hint_y = None
            self.height = self._input_container.height

    def clear_messages(self):
        """Remove all message bubbles."""
        def _clear(dt):
            self._message_box.clear_widgets()
        Clock.schedule_once(_clear, 0)
