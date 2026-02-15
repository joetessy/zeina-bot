"""
KivyDisplay - implements the Display interface for the Kivy GUI.

Every method wraps widget updates in Clock.schedule_once for thread safety.
"""
from kivy.clock import Clock
from zeina.enums import InteractionMode, RecordingState
from typing import Optional


class KivyDisplay:
    """Display backend that routes updates to Kivy widgets via Clock.schedule_once."""

    def __init__(self, face_widget, status_widget, chat_widget):
        self.face_widget = face_widget
        self.status_widget = status_widget
        self.chat_widget = chat_widget

        # Protocol compatibility attributes
        self.face_visible = True
        self.face_lines = 0  # Not used in GUI
        self.pause_face_updates = False

        # Toggle state - controls visibility / behavior of UI elements
        self.toggles = {
            'face': True,
            'status': True,
            'tool_log': True,
            'chat': True,
            'speaking': True,
        }

    # --- Helpers ---

    def _strip_emoji(self, text: str) -> str:
        """Strip non-ASCII characters (emojis) that Kivy can't render."""
        return text.encode('ascii', 'ignore').decode('ascii').strip()

    # --- Display protocol methods ---

    def show_status(self, status: str, style: str = ""):
        """Show a one-off status in the chat feed."""
        self.chat_widget.add_message(status, role="info")

    def show_header(self):
        """No-op in GUI (header is part of the layout)."""
        pass

    def show_menu_bar(self, mode: InteractionMode, model_name: str):
        def _update(dt):
            self.status_widget.set_mode(mode.value)
            self.status_widget.set_model(model_name)
        Clock.schedule_once(_update, 0)

    def show_user_message(self, message: str):
        self.chat_widget.add_message(message, role="user")

    def show_assistant_message(self, message: str):
        self.chat_widget.add_message(message, role="assistant")

    def show_error(self, message: str):
        clean = self._strip_emoji(message)
        if self.toggles.get('tool_log', True):
            def _update(dt):
                self.status_widget.set_tool_log(clean, "red")
            Clock.schedule_once(_update, 0)
        self.chat_widget.add_message(clean, role="error")

    def show_info(self, message: str):
        clean = self._strip_emoji(message)
        if self.toggles.get('tool_log', True):
            def _update(dt):
                self.status_widget.set_tool_log(clean, "yellow")
            Clock.schedule_once(_update, 0)
        self.chat_widget.add_message(clean, role="info")

    def show_status_centered(self, message: str, style: str = "cyan"):
        def _update(dt):
            self.status_widget.set_status(message, style)
        Clock.schedule_once(_update, 0)

    def show_status_detail_centered(self, message: str, style: str = "dim"):
        def _update(dt):
            self.status_widget.set_detail(message, style)
        Clock.schedule_once(_update, 0)

    def start_face_display(self, clear_screen: bool = True):
        """Face animation is managed by the FaceWidget's own Clock events."""
        self.face_visible = True

    def update_face_state(self, recording_state: RecordingState, is_speaking: bool = False):
        from zeina.face import Face
        # Reuse the same state mapping logic
        face = Face()
        state_str = face.get_state_from_recording_state(recording_state, is_speaking)
        def _update(dt):
            self.face_widget.set_state(state_str)
        Clock.schedule_once(_update, 0)

    def clear_feed(self):
        """No-op in GUI (terminal-only concept)."""
        pass

    def move_cursor_to_feed_bottom(self):
        """No-op in GUI (terminal-only concept)."""
        pass

    def move_cursor_to_content_area(self):
        """No-op in GUI."""
        pass

    def stop_face_display(self, clear_screen: bool = True):
        """No-op in GUI (face widget persists)."""
        self.face_visible = False

    def show_log(self, message: str):
        """Show a log message in the status bar (not in chat bubbles)."""
        if self.toggles.get('tool_log', True):
            clean = self._strip_emoji(message)
            def _update(dt):
                self.status_widget.set_tool_log(clean, "yellow")
            Clock.schedule_once(_update, 0)

    def get_chat_input(self, prompt: str) -> Optional[str]:
        """Block until user submits text. Called from pipeline thread, NOT main thread."""
        return self.chat_widget.get_chat_input(prompt)
