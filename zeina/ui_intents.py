"""Stage-0 deterministic matching of UI-control intents.

Fast regex/keyword matching for ``control_self`` actions (theme changes, mode
toggles, mute, etc.). Runs before any LLM call, so common UI commands cost
nothing. Pure functions — no assistant or Kivy dependency.
"""
from __future__ import annotations

from typing import Callable

from zeina.types import UIAction

#: Extracts a proper name from free text (LLM-backed; see zeina.history).
NameExtractor = Callable[[str], str]

_THEMES = ("midnight", "terminal", "sunset", "default")

_ANIMATION_TOGGLE_PHRASES = (
    "face style", "face animation", "animation style",
    "switch animation", "change animation", "switch face",
    "change face", "switch ur face", "change ur face",
)

_VOICE_MODE_PHRASES = ("voice mode", "switch to voice", "go to voice",
                       "use voice", "activate voice", "voice input")
_CHAT_MODE_PHRASES = ("chat mode", "text mode", "chat input", "switch to chat",
                      "go to chat", "typing mode")

_CLEAR_WORDS = ("clear", "wipe", "reset", "delete", "erase", "forget")
_HISTORY_WORDS = ("histor", "conversation", "chat", "messages")
_MEMORY_WORDS = ("memor", "everything", "all")

_CHAT_FEED_PHRASES = ("chat feed", "chat window", "transcript",
                      "show chat", "hide chat", "open chat", "close chat")

_PROFILE_VERBS = ("switch", "change", "go to", "use", "load",
                  "activate", "select", "swap")

_MENU_WORDS = ("3 dot", "three dot", "dots menu", "menu button",
               "dot menu", "3dot", "triple dot")


def ui_show_hide(text: str) -> str:
    """Determine 'show' or 'hide' from natural-language phrasing."""
    if any(w in text for w in ("show", "open", "on", "enable", "visible")):
        return "show"
    return "hide"


def match_ui_patterns(
    message: str,
    *,
    multi: bool,
    extract_name: NameExtractor,
) -> list[UIAction]:
    """Match UI control actions in a user message.

    Args:
        message: the user's message (original casing; lowercased internally).
        multi: True = collect all matches; False = return after first match.
        extract_name: called for open-ended values (profile names).
    """
    m = message.lower()
    results: list[UIAction] = []

    def _emit(action: UIAction) -> bool:
        results.append(action)
        return not multi

    # ── Theme ────────────────────────────────────────────────────────
    for theme in _THEMES:
        if theme in m:
            if _emit({"action": "set_theme", "value": theme}):
                return results
            break

    # ── Animation (mutually exclusive) ───────────────────────────────
    if "ascii" in m:
        if _emit({"action": "set_animation", "value": "ascii"}):
            return results
    elif "vector" in m or "bmo" in m:
        if _emit({"action": "set_animation", "value": "vector"}):
            return results
    elif any(w in m for w in _ANIMATION_TOGGLE_PHRASES):
        if _emit({"action": "set_animation", "value": "toggle"}):
            return results

    # ── Mode (mutually exclusive) ─────────────────────────────────────
    if any(p in m for p in _VOICE_MODE_PHRASES):
        if _emit({"action": "set_mode", "value": "voice"}):
            return results
    elif any(w in m for w in _CHAT_MODE_PHRASES):
        if _emit({"action": "set_mode", "value": "chat"}):
            return results

    # ── Pages ────────────────────────────────────────────────────────
    if "setting" in m:
        if _emit({"action": "open_settings"}):
            return results
    if "diagnostic" in m or "dashboard" in m:
        if _emit({"action": "open_diagnostics"}):
            return results

    # ── Clear ────────────────────────────────────────────────────────
    if any(w in m for w in _CLEAR_WORDS):
        if any(w in m for w in _HISTORY_WORDS):
            if _emit({"action": "clear_history"}):
                return results
        if any(w in m for w in _MEMORY_WORDS):
            if _emit({"action": "clear_memories"}):
                return results

    # ── Status bar ───────────────────────────────────────────────────
    if "status bar" in m or ("status" in m and "bar" in m):
        if _emit({"action": "set_status_bar", "value": ui_show_hide(m)}):
            return results

    # ── Chat feed / transcript ────────────────────────────────────────
    if any(w in m for w in _CHAT_FEED_PHRASES):
        if _emit({"action": "set_chat_feed", "value": ui_show_hide(m)}):
            return results

    # ── TTS mute (mutually exclusive) ─────────────────────────────────
    if "unmute" in m:
        if _emit({"action": "set_tts_mute", "value": "unmute"}):
            return results
    elif "mute" in m:
        if _emit({"action": "set_tts_mute", "value": "mute"}):
            return results

    # ── Profile switching (open-ended name → LLM) ────────────────────
    if "profile" in m and any(v in m for v in _PROFILE_VERBS):
        if _emit({"action": "switch_profile", "value": extract_name(message)}):
            return results

    # ── Menu button ───────────────────────────────────────────────────
    if any(w in m for w in _MENU_WORDS) or ("menu" in m and "button" in m):
        if _emit({"action": "set_menu_button", "value": ui_show_hide(m)}):
            return results

    return results
