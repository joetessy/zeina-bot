"""
Enums for Zeina AI Assistant
"""
from enum import Enum


class InteractionMode(Enum):
    """Interaction mode for the assistant"""
    VOICE = "voice"  # Voice input/output
    CHAT = "chat"    # Text input/output


class RecordingState(Enum):
    """State machine for recording system"""
    IDLE = "idle"           # Not recording, waiting for activation
    LISTENING = "listening"  # Actively recording, detecting speech
    PROCESSING = "processing" # Processing the recorded audio


def face_state_from_recording(recording_state: "RecordingState", is_speaking: bool) -> str:
    """Map a RecordingState (+ speaking flag) to a face animation state name.

    Used by the display layer to drive the animated face.
    """
    if is_speaking:
        return "speaking"
    if recording_state == RecordingState.LISTENING:
        return "listening"
    if recording_state == RecordingState.PROCESSING:
        return "processing"
    return "idle"
