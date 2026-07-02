"""System prompt assembly for Zeina.

Pure functions that turn a profile dict (+ memory facts + runtime state) into
the final system prompt and the runtime-state banner. No file I/O — the
Settings class supplies the inputs.
"""
from __future__ import annotations

from typing import Any, Optional

from zeina import config

# Prompt snippets for personality options
RESPONSE_LENGTH_ADDITIONS: dict[str, str] = {
    "concise": (
        "Response length override: Be extra brief — one sentence maximum for most "
        "responses. Get straight to the point."
    ),
    "detailed": (
        "Response length override: When helpful, give thorough answers. Three to five "
        "sentences with relevant context or examples is fine when the topic warrants it."
    ),
}

LANGUAGE_STYLE_ADDITIONS: dict[str, str] = {
    "casual": (
        "Tone override: Be relaxed and informal. Light humour is welcome. "
        "Feel free to use everyday expressions and contractions."
    ),
    "professional": (
        "Tone override: Maintain a formal, polished tone at all times. "
        "Avoid slang, contractions, and casual filler words."
    ),
    "wild": (
        "Tone override: Be unpredictable and creative. Feel free to use informal language, slang."
        "Must use humor, be unprofessional, even inappropriate."
    ),
}


def build_system_prompt(profile: dict[str, Any], facts: list[str]) -> str:
    """Assemble the full system prompt from base + personality additions + memory.

    Structure (all sections are additive — the base is never overwritten):
      1. Base SYSTEM_PROMPT (with bot name substituted)
      2. User name personalisation (if set)
      3. Response length override (if set)
      4. Language style override (if set)
      5. Custom instructions (if non-empty)
      6. Known user facts (if any)
    """
    bot_name = profile.get("bot_name", "Zeina")
    base = config.SYSTEM_PROMPT.replace("Zeina", bot_name)

    additions: list[str] = []

    user_name = (profile.get("user_name") or "").strip()
    if user_name:
        additions.append(
            f"The user's name is {user_name}. You may use it occasionally in a natural way, "
            f"but don't repeat it constantly — most replies don't need to include it."
        )

    resp_len = profile.get("response_length", "concise")
    if resp_len in RESPONSE_LENGTH_ADDITIONS:
        additions.append(RESPONSE_LENGTH_ADDITIONS[resp_len])

    lang_style = profile.get("language_style", "casual")
    if lang_style in LANGUAGE_STYLE_ADDITIONS:
        additions.append(LANGUAGE_STYLE_ADDITIONS[lang_style])

    custom = (profile.get("custom_instructions") or "").strip()
    if custom:
        additions.append(f"Additional instructions:\n{custom}")

    if facts:
        fact_lines = "\n".join(f"- {f}" for f in facts)
        additions.append(f"What you know about this user:\n{fact_lines}")

    if not additions:
        return base

    return base.rstrip() + "\n\n" + "\n\n".join(additions)


def format_system_state(
    profile: dict[str, Any], runtime_state: Optional[dict[str, Any]] = None
) -> str:
    """Return a concise snapshot of runtime configuration for the LLM."""
    state: dict[str, Any] = {
        "mode": "voice",
        "theme": profile.get("theme", "default"),
        "face_style": profile.get("animation_theme", "vector"),
        "vad_limit": profile.get("silence_duration", config.SILENCE_DURATION),
    }
    if runtime_state:
        for key, value in runtime_state.items():
            if value is not None:
                state[key] = value

    return (
        f"[SYSTEM_STATE: Mode={state['mode']}, Theme='{state['theme']}', "
        f"Face='{state['face_style']}', Voice Activity Detection limit={state['vad_limit']}s]"
    )
