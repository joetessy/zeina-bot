"""Display interface the backend renders through.

The assistant never imports Kivy; it drives the UI exclusively through this
protocol. ``ui.kivy_display.KivyDisplay`` is the (only) implementation.
Structural typing keeps the backend GUI-toolkit-agnostic: any object with
these methods works as a display.
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from zeina.enums import InteractionMode, RecordingState


@runtime_checkable
class DisplayProtocol(Protocol):
    """What the assistant needs from a display implementation."""

    #: True if the display can render token-by-token streaming.
    has_streaming: bool

    #: Visibility/behaviour toggles ('face', 'status', 'tool_log', 'chat',
    #: 'speaking'). The assistant reads these to decide whether to speak or
    #: render to the chat feed.
    toggles: dict[str, bool]

    # ── Messages ──────────────────────────────────────────────────────
    def show_user_message(self, message: str) -> None: ...
    def show_assistant_message(self, message: str) -> None: ...
    def show_error(self, message: str) -> None: ...
    def show_info(self, message: str) -> None: ...
    def show_log(self, message: str) -> None: ...

    # ── Status bar ────────────────────────────────────────────────────
    def show_status_centered(self, message: str, style: str = "cyan") -> None: ...
    def show_menu_bar(self, mode: InteractionMode, model_name: str) -> None: ...

    # ── Face ──────────────────────────────────────────────────────────
    def start_face_display(self, clear_screen: bool = True) -> None: ...
    def update_face_state(
        self, recording_state: RecordingState, is_speaking: bool = False
    ) -> None: ...

    # ── Streaming ─────────────────────────────────────────────────────
    def begin_stream(self) -> None: ...
    def stream_token(self, token: str) -> None: ...

    # ── Input ─────────────────────────────────────────────────────────
    def get_chat_input(self, prompt: str) -> Optional[str]: ...

    # ── Window control (used around screenshots / shell commands) ────
    def hide_window(self) -> None: ...
    def show_window(self) -> None: ...
    def raise_window(self, delay: float = 0.0) -> None: ...

    # ── Terminal-era no-ops kept for protocol compatibility ──────────
    def clear_feed(self) -> None: ...
    def move_cursor_to_feed_bottom(self) -> None: ...
