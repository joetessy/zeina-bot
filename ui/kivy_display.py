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
        self._face_stream_mode = False   # True when streaming text to the face widget
        self._force_face_stream = False  # Set externally to bypass toggle checks

        # Tracks the last persistent status so tool-log messages can restore it
        self._persistent_status = ""
        self._persistent_style = "cyan"
        self._log_restore_event = None   # Pending Clock event to restore status

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
        self._persistent_status = message
        self._persistent_style = style
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

    def hide_window(self) -> None:
        """Hide the Kivy window before a screenshot so it isn't captured.
        Blocks the calling thread until the hide completes."""
        import threading
        import time
        from kivy.core.window import Window
        done = threading.Event()
        def _hide(dt):
            Window.hide()
            done.set()
        Clock.schedule_once(_hide, 0)
        done.wait(timeout=1.0)
        time.sleep(0.15)  # let the OS finish hiding

    def show_window(self) -> None:
        """Show the Kivy window again after a screenshot."""
        from kivy.core.window import Window
        def _show(dt):
            Window.show()
        Clock.schedule_once(_show, 0)

    def raise_window(self, delay: float = 0.0) -> None:
        """Bring Zeina's window back to the foreground after a shell action."""
        import os
        import platform

        def _raise(dt):
            if platform.system() == "Darwin":
                import subprocess
                pid = os.getpid()
                subprocess.Popen(
                    ["osascript", "-e",
                     f"tell application \"System Events\" to set frontmost of "
                     f"(first process whose unix id is {pid}) to true"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                from kivy.core.window import Window
                Window.raise_window()

        Clock.schedule_once(_raise, delay)


    def _restore_persistent_status(self, dt):
        """Restore the status bar to the last persistent message after a tool log."""
        self._log_restore_event = None
        self.status_widget.set_status(self._persistent_status, self._persistent_style)

    def show_log(self, message: str):
        """Show a log message in the status bar (not in chat bubbles).
        Auto-clears after 1.5 s and restores the previous persistent status."""
        if self.toggles.get('tool_log', True):
            clean = self._strip_emoji(message)
            def _update(dt):
                if self._log_restore_event:
                    self._log_restore_event.cancel()
                self.status_widget.set_tool_log(clean, "yellow")
                self._log_restore_event = Clock.schedule_once(
                    self._restore_persistent_status, 1.5
                )
            Clock.schedule_once(_update, 0)

    def get_chat_input(self, prompt: str) -> Optional[str]:
        """Block until user submits text. Called from pipeline thread, NOT main thread."""
        return self.chat_widget.get_chat_input(prompt)

    # --- Streaming support ---

    has_streaming = True

    def begin_stream(self) -> None:
        """Start a new streaming assistant bubble."""
        self.chat_widget.begin_assistant_stream()
        # Face stream mode: render text onto the face widget when the chat feed
        # is hidden AND TTS is muted (normal case), OR when _force_face_stream is
        # set by the caller (e.g. control_self responses where mute may have just
        # been applied and the toggle hasn't updated yet).
        self._face_stream_mode = self._force_face_stream or (
            not self.toggles.get('chat', True)
            and not self.toggles.get('speaking', True)
        )
        self._force_face_stream = False  # consume
        if self._face_stream_mode:
            self.face_widget.begin_face_stream()

    def stream_token(self, token: str) -> None:
        """Append a token to the active streaming bubble."""
        self.chat_widget.append_stream_token(token)
        if self._face_stream_mode:
            self.face_widget.append_face_token(token)
