"""UI control tool — controls the app's own interface."""
from .manager import tool_manager

_ui_control_callback = None


def set_ui_control_callback(cb) -> None:
    """Register a callback(action: str, value: str) that controls the app UI."""
    global _ui_control_callback
    _ui_control_callback = cb


@tool_manager.register(
    name="control_self",
    description=(
        "Control the app's own UI and settings. Use when the user asks to: "
        "switch color theme, change face animation style, toggle voice/chat mode, "
        "show/hide the status bar or chat feed, show/hide the menu button, "
        "mute/unmute TTS speech, clear conversation history, clear stored memories, "
        "switch profile, or open the settings or diagnostics page."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "set_theme", "set_animation", "set_mode",
                    "set_status_bar", "set_chat_feed", "set_tts_mute",
                    "clear_history", "clear_memories",
                    "open_settings", "open_diagnostics",
                    "switch_profile", "set_menu_button",
                ],
                "description": "The UI action to perform",
            },
            "value": {
                "type": "string",
                "description": (
                    "The value for the action. "
                    "set_theme: default|midnight|terminal|sunset. "
                    "set_animation: vector|ascii. "
                    "set_mode: voice|chat. "
                    "set_status_bar / set_chat_feed / set_menu_button: show|hide. "
                    "set_tts_mute: mute|unmute. "
                    "switch_profile: the profile name. "
                    "Other actions: leave empty."
                ),
            },
        },
        "required": ["action"],
    },
)
def control_self(action: str, value: str = "") -> str:
    """Invoke the registered UI control callback to change app state."""
    if _ui_control_callback:
        try:
            return _ui_control_callback(action, value or "")
        except Exception as e:
            return f"UI control error: {e}"
    return "UI control not available in this mode."
