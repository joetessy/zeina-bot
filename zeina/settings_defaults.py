"""Default profile and app-state templates for Zeina settings.

Kept in their own module so both zeina/settings.py and zeina/migrations.py can
import them without a circular dependency.
"""
from __future__ import annotations

from typing import Any

DEFAULT_PROFILE: dict[str, Any] = {
    "bot_name": "Zeina",
    "chat_model": "qwen2.5-7b",
    "tts_voice": "models/en_GB-southern_english_female-low.onnx",
    "silence_duration": 2.0,
    "listening_timeout": 5.0,
    "vad_threshold": 0.5,
    "observability_level": "lite",
    "max_conversation_length": 20,
    "save_conversation_history": True,
    "theme": "default",
    "animation_theme": "vector",
    # Status bar component visibility
    "status_show_mode": True,
    "status_show_toollog": True,
    "status_show_botname": True,
    # Personality additions (appended below the base system prompt)
    "user_name": "",            # What the AI calls the user; empty = not personalised
    "response_length": "concise",   # concise | detailed
    "language_style": "casual",    # casual | professional | wild
    "custom_instructions": "",      # Free-form addition, appended verbatim
    # User memory
    "memory_enabled": True,     # Extract and inject facts about the user
    # Vision
    "vision_model": "huihui-qwen3.6-27b-abliterated-mtp",  # Vision-capable model for screen queries
    # TTS
    "tts_speed": 1.0,               # Piper length_scale: <1.0 faster, >1.0 slower
    # Controls
    "push_to_talk_key": "space",  # Single char (e.g. "f") or "space"
    # UI toggle states (persisted across sessions)
    "tts_muted": False,
    "chat_feed_visible": False,
    "status_bar_visible": True,
    "interaction_mode": "voice",  # "voice" | "chat"
    # conversation_history is NOT in the default template — sessions handle this.
}

MEMORY_CAP = 50  # Maximum facts stored per profile

# settings.json holds only lightweight app-level state
DEFAULT_APP_STATE: dict[str, Any] = {
    "version": 5,
    "active_profile": "default",
}
