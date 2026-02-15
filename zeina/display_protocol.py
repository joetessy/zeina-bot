"""
Display protocol for Zeina AI Assistant.

Documents the interface that any display backend must implement.
The terminal Display class and the KivyDisplay class both follow this contract.
"""
from typing import Protocol, Optional
from zeina.enums import InteractionMode, RecordingState


class DisplayProtocol(Protocol):
    """Interface contract for Zeina display backends."""

    face_visible: bool
    face_lines: int
    pause_face_updates: bool

    def show_status(self, status: str, style: str = "") -> None:
        """Show a one-off status message in the feed area."""
        ...

    def show_header(self) -> None:
        """Show application header / title bar."""
        ...

    def show_menu_bar(self, mode: InteractionMode, model_name: str) -> None:
        """Update the mode indicator and model name in the menu bar."""
        ...

    def show_user_message(self, message: str) -> None:
        """Display a user message bubble in the chat feed."""
        ...

    def show_assistant_message(self, message: str) -> None:
        """Display an assistant message bubble in the chat feed."""
        ...

    def show_error(self, message: str) -> None:
        """Display an error message in the feed."""
        ...

    def show_info(self, message: str) -> None:
        """Display an informational message in the feed."""
        ...

    def show_status_centered(self, message: str, style: str = "cyan") -> None:
        """Update the persistent status line (below the face)."""
        ...

    def show_status_detail_centered(self, message: str, style: str = "dim") -> None:
        """Update the secondary status / timing detail line."""
        ...

    def start_face_display(self, clear_screen: bool = True) -> None:
        """Start face animation loop."""
        ...

    def update_face_state(self, recording_state: RecordingState, is_speaking: bool = False) -> None:
        """Update the face expression to match the current assistant state."""
        ...

    def move_cursor_to_feed_bottom(self) -> None:
        """Scroll / position so the next print lands at the feed bottom."""
        ...

    def stop_face_display(self, clear_screen: bool = True) -> None:
        """Stop face animation and clean up."""
        ...

    # --- Optional extended interface for GUI displays ---

    def get_chat_input(self, prompt: str) -> Optional[str]:
        """Block until the user submits text input. Returns None if cancelled.
        Only implemented by GUI displays; terminal display uses assistant._get_chat_input().
        """
        ...
