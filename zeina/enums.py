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
