"""Handler for the ``control_self`` tool — lets the bot drive its own UI.

Called from a background (tool-execution) thread; every Kivy mutation is
scheduled onto the main thread via Clock.schedule_once. Returns a
human-readable result string for the LLM to relay.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from kivy.clock import Clock

from zeina import config
from zeina.enums import InteractionMode

if TYPE_CHECKING:
    from ui.app import ZeinaApp


# ── Value normalizers ─────────────────────────────────────────────────

def _resolve_theme(v: str) -> Optional[str]:
    """Return the theme name contained in v, or None."""
    for t in ("midnight", "terminal", "sunset", "default"):
        if t in v:
            return t
    return None


def _resolve_show(v: str) -> Optional[bool]:
    """Return True=show, False=hide, None=toggle."""
    if any(w in v for w in ("show", "open", "on", "enable", "visible")):
        return True
    if any(w in v for w in ("hide", "close", "off", "disable", "hidden")):
        return False
    return None


def _resolve_mute(v: str) -> Optional[bool]:
    """Return True=mute, False=unmute, None=toggle."""
    if any(w in v for w in ("unmute", "enable", "on", "start")):
        return False
    if any(w in v for w in ("mute", "disable", "off", "stop", "silence")):
        return True
    return None


def _resolve_mode(v: str) -> Optional[str]:
    """Return 'chat', 'voice', or None."""
    if "chat" in v or "text" in v or "type" in v:
        return "chat"
    if "voice" in v or "speak" in v or "talk" in v:
        return "voice"
    return None


class UIControlHandler:
    """Executes control_self actions against the running ZeinaApp."""

    def __init__(self, app: "ZeinaApp") -> None:
        self._app = app

    def _resolve_anim(self, v: str) -> Optional[str]:
        """Return the animation style from v, resolving 'toggle' against current settings."""
        if "ascii" in v:
            return "ascii"
        if "vector" in v or "bmo" in v:
            return "vector"
        if v == "toggle":
            current = self._app._settings.get("animation_theme", "vector")
            return "ascii" if current == "vector" else "vector"
        return None

    def _run_switch_profile(self, value: str) -> str:
        """Handle switch_profile synchronously then schedule Kivy UI updates."""
        app = self._app
        available = app._settings.list_profiles()
        target = value.lower().strip()
        match = next((p for p in available if p.lower() == target), None)
        if not match:
            match = next((p for p in available if target in p.lower()), None)
        if not match:
            return (f"Profile '{value}' not found. "
                    f"Available profiles: {', '.join(available)}.")

        # Update config and TTS synchronously so the new voice is in effect
        # before the LLM response starts streaming.
        app._settings.switch_profile(match)
        app._settings.apply_to_config()
        if app._assistant:
            from zeina.tts import TTSEngine
            app._assistant.tts_engine = TTSEngine(voice=config.TTS_VOICE)

        def _do_ui_update(dt=None):
            new = app._settings.get_all()
            app._theme_manager.apply(app, new.get("theme", "default"))
            bot = new.get("bot_name", "Zeina")
            app._bot_name = bot
            app._status.set_model(bot)
            if app._assistant:
                app._kivy_display.show_menu_bar(app._assistant.mode, bot)

        Clock.schedule_once(_do_ui_update, 0)
        return f"Switched to profile '{match}'."

    def handle(self, action: str, value: str = "") -> str:
        """Perform ``action``; returns a result sentence for the LLM."""
        app = self._app
        value = (value or "").strip()
        v = value.lower()

        theme = _resolve_theme(v)
        anim = self._resolve_anim(v)
        mode = _resolve_mode(v)
        show_bool = _resolve_show(v)
        mute_bool = _resolve_mute(v)

        if action == "switch_profile":
            return self._run_switch_profile(value)

        # Resolve the *effective* new state for toggle-style actions up front,
        # so the pre-update and the reported result are both accurate even for
        # the "toggle" (None) case.
        new_status_visible = show_bool if show_bool is not None else not app._status_visible
        new_chat_visible = show_bool if show_bool is not None else not app._chat_visible
        new_muted = mute_bool if mute_bool is not None else not app._tts_muted
        menu_visible = show_bool if show_bool is not None else True

        # Pre-update KivyDisplay toggles synchronously so begin_stream() sees
        # the correct future state before the Clock callback has executed.
        if action == "set_chat_feed":
            app._kivy_display.toggles['chat'] = new_chat_visible
        elif action == "set_tts_mute":
            app._kivy_display.toggles['speaking'] = not new_muted

        def _run(dt=None):
            if action == "set_theme":
                if theme:
                    app._theme_manager.apply(app, theme)
                    app._settings.set("theme", theme)

            elif action == "set_animation":
                if anim:
                    app._face.set_animation_theme(anim)
                    app._adjust_face_size(anim)
                    app._settings.set("animation_theme", anim)

            elif action == "set_mode":
                if mode and app._assistant:
                    if mode == "voice" and app._assistant.mode == InteractionMode.CHAT:
                        app._toggle_mode()
                    elif mode == "chat" and app._assistant.mode == InteractionMode.VOICE:
                        app._toggle_mode()

            elif action == "set_status_bar":
                if new_status_visible != app._status_visible:
                    app._toggle_status_bar()

            elif action == "set_chat_feed":
                if new_chat_visible != app._chat_visible:
                    app._toggle_chat_feed()

            elif action == "set_tts_mute":
                if new_muted != app._tts_muted:
                    app._toggle_mute()

            elif action == "clear_history":
                if app._assistant:
                    app._assistant.conversation_history.clear()
                app._settings.clear_session_history(config.ACTIVE_PROFILE)

            elif action == "clear_memories":
                app._settings.clear_memories(app._settings.active_profile_name)

            elif action == "set_bot_name":
                if value:
                    app._settings.set("bot_name", value)
                    app._bot_name = value
                    app._status.set_model(value)
                    if app._assistant:
                        app._kivy_display.show_menu_bar(app._assistant.mode, value)

            elif action == "set_user_name":
                if value:
                    app._settings.set("user_name", value)
                    # Remove memories referring to a previous name to avoid
                    # conflicts with the updated user_name in the system prompt.
                    _name_keywords = ("name is", "called ", "known as", "goes by")
                    for fact in app._settings.load_memories(config.ACTIVE_PROFILE):
                        if any(kw in fact.lower() for kw in _name_keywords):
                            app._settings.remove_memory(config.ACTIVE_PROFILE, fact)
                    if app._assistant:
                        app._assistant.conversation_history.append({
                            "role": "user",
                            "content": f"[My name is {value} — please use this name from now on, not any previous name]",
                        })

            elif action == "open_settings":
                app._settings_screen.show()

            elif action == "open_diagnostics":
                app._diagnostics.refresh(app._assistant)
                app._diagnostics.show()

            elif action == "set_menu_button":
                app._menu_container.opacity = 1 if menu_visible else 0
                app._menu_btn.disabled = not menu_visible

        Clock.schedule_once(_run, 0)

        results = {
            "set_theme":        f"Theme changed to {theme or value}.",
            "set_animation":    f"Animation style changed to {anim or value}.",
            "set_mode":         f"Mode switched to {mode or value}.",
            "set_status_bar":   f"Status bar {'shown' if new_status_visible else 'hidden'}.",
            "set_chat_feed":    f"Chat feed {'opened' if new_chat_visible else 'closed'}.",
            "set_tts_mute":     "TTS muted." if new_muted else "TTS unmuted.",
            "clear_history":    "Conversation history cleared.",
            "clear_memories":   "Memories cleared.",
            "set_bot_name":     f"Bot name updated to {value}.",
            "set_user_name":    f"User name updated to {value}.",
            "open_settings":    "Settings page opened.",
            "open_diagnostics": "Diagnostics page opened.",
            "set_menu_button":  f"Menu button {'shown' if menu_visible else 'hidden'}.",
        }
        return results.get(action, "Done.")
