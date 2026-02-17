"""
Color theme definitions for Zeina AI Assistant.

Each theme is a dict of named colors used by all widgets.
ThemeManager pushes colors to widgets via their apply_theme() methods.
"""
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.core.text import LabelBase


THEMES = {
    "default": {
        "name": "Default",
        "window_bg": (0.06, 0.06, 0.08, 1),
        # Face
        "face_screen": (0.06, 0.12, 0.14, 1),
        "face_eye": (0.85, 0.95, 0.90, 1),
        "face_pupil": (0.06, 0.12, 0.14, 1),
        "face_mouth": (0.85, 0.95, 0.90, 1),
        "face_sparkle": (0.6, 1.0, 0.9, 1.0),
        "face_blush": (0.85, 0.45, 0.55, 0.35),
        "face_signal": (0.3, 0.9, 0.75, 0.6),
        "face_brow": (0.75, 0.88, 0.82, 1),
        "face_mouth_inner": (0.10, 0.06, 0.08, 1),
        "face_lip": (0.78, 0.88, 0.84, 1),
        "face_tongue": (0.82, 0.48, 0.52, 0.55),
        "face_thought_dot": (0.55, 0.85, 0.75, 0.7),
        # Status
        "status_bg": (0.07, 0.08, 0.1, 0.9),
        # Toggles
        "toggle_on": (0.18, 0.58, 0.52, 1),
        "toggle_off": (0.2, 0.2, 0.24, 1),
        "toggle_on_text": (1, 1, 1, 0.95),
        "toggle_off_text": (0.55, 0.55, 0.6, 0.9),
        "toggle_bg": (0.07, 0.08, 0.1, 0.9),
        # Chat
        "bubble_user": (0.11, 0.44, 0.40, 0.92),
        "bubble_assistant": (0.12, 0.13, 0.17, 0.92),
        "bubble_info": (0.10, 0.12, 0.15, 0.50),
        "bubble_error": (0.58, 0.18, 0.18, 0.80),
        "text_user": (0.95, 1, 0.98, 1),
        "text_assistant": (0.82, 0.86, 0.90, 1),
        "text_info": (0.50, 0.55, 0.60, 0.9),
        "text_error": (1, 0.70, 0.68, 1),
        "chat_bg": (0.05, 0.06, 0.08, 0.85),
        "chat_input_bg": (0.10, 0.11, 0.14, 1),
        "chat_input_text": (0.88, 0.90, 0.94, 1),
        # Accent
        "accent": (0.18, 0.58, 0.52, 1),
        "settings_btn_bg": (0.2, 0.2, 0.24, 0.7),
        "settings_btn_text": (0.7, 0.75, 0.8, 0.9),
        "font_name": "Roboto",
    },

    "midnight": {
        "name": "Midnight",
        "window_bg": (0.04, 0.04, 0.07, 1),
        "face_screen": (0.05, 0.05, 0.12, 1),
        "face_eye": (0.70, 0.75, 0.95, 1),
        "face_pupil": (0.05, 0.05, 0.12, 1),
        "face_mouth": (0.70, 0.75, 0.95, 1),
        "face_sparkle": (0.5, 0.6, 1.0, 1.0),
        "face_blush": (0.75, 0.40, 0.65, 0.35),
        "face_signal": (0.4, 0.5, 0.95, 0.6),
        "face_brow": (0.65, 0.70, 0.90, 1),
        "face_mouth_inner": (0.06, 0.06, 0.10, 1),
        "face_lip": (0.68, 0.72, 0.90, 1),
        "face_tongue": (0.72, 0.42, 0.58, 0.55),
        "face_thought_dot": (0.5, 0.6, 0.9, 0.7),
        "status_bg": (0.06, 0.06, 0.10, 0.9),
        "toggle_on": (0.25, 0.35, 0.70, 1),
        "toggle_off": (0.15, 0.15, 0.22, 1),
        "toggle_on_text": (1, 1, 1, 0.95),
        "toggle_off_text": (0.48, 0.48, 0.58, 0.9),
        "toggle_bg": (0.06, 0.06, 0.10, 0.9),
        "bubble_user": (0.18, 0.28, 0.55, 0.92),
        "bubble_assistant": (0.10, 0.10, 0.18, 0.92),
        "bubble_info": (0.08, 0.08, 0.14, 0.50),
        "bubble_error": (0.55, 0.15, 0.25, 0.80),
        "text_user": (0.90, 0.92, 1.0, 1),
        "text_assistant": (0.78, 0.82, 0.92, 1),
        "text_info": (0.45, 0.48, 0.60, 0.9),
        "text_error": (1, 0.65, 0.70, 1),
        "chat_bg": (0.04, 0.04, 0.08, 0.85),
        "chat_input_bg": (0.08, 0.08, 0.14, 1),
        "chat_input_text": (0.82, 0.85, 0.95, 1),
        "accent": (0.25, 0.35, 0.70, 1),
        "settings_btn_bg": (0.15, 0.15, 0.24, 0.7),
        "settings_btn_text": (0.65, 0.68, 0.82, 0.9),
        "font_name": "Roboto",
    },

    "terminal": {
        "name": "Terminal",
        "window_bg": (0.0, 0.0, 0.0, 1),
        "face_screen": (0.0, 0.03, 0.0, 1),
        "face_eye": (0.0, 1.0, 0.0, 1),
        "face_pupil": (0.0, 0.03, 0.0, 1),
        "face_mouth": (0.0, 1.0, 0.0, 1),
        "face_sparkle": (0.3, 1.0, 0.3, 1.0),
        "face_blush": (0.0, 0.8, 0.0, 0.20),
        "face_signal": (0.0, 0.8, 0.0, 0.6),
        "face_brow": (0.0, 0.85, 0.0, 1),
        "face_mouth_inner": (0.0, 0.03, 0.0, 1),
        "face_lip": (0.0, 0.9, 0.0, 1),
        "face_tongue": (0.0, 0.6, 0.0, 0.55),
        "face_thought_dot": (0.0, 0.7, 0.0, 0.7),
        "status_bg": (0.0, 0.04, 0.0, 0.9),
        "toggle_on": (0.0, 0.55, 0.0, 1),
        "toggle_off": (0.12, 0.12, 0.12, 1),
        "toggle_on_text": (0.7, 1.0, 0.7, 0.95),
        "toggle_off_text": (0.0, 0.45, 0.0, 0.9),
        "toggle_bg": (0.0, 0.04, 0.0, 0.9),
        "bubble_user": (0.0, 0.28, 0.0, 0.92),
        "bubble_assistant": (0.06, 0.06, 0.06, 0.92),
        "bubble_info": (0.04, 0.06, 0.04, 0.50),
        "bubble_error": (0.50, 0.0, 0.0, 0.80),
        "text_user": (0.7, 1.0, 0.7, 1),
        "text_assistant": (0.0, 0.9, 0.0, 1),
        "text_info": (0.0, 0.5, 0.0, 0.9),
        "text_error": (1, 0.3, 0.3, 1),
        "chat_bg": (0.0, 0.02, 0.0, 0.85),
        "chat_input_bg": (0.0, 0.06, 0.0, 1),
        "chat_input_text": (0.0, 0.9, 0.0, 1),
        "accent": (0.0, 0.55, 0.0, 1),
        "settings_btn_bg": (0.1, 0.1, 0.1, 0.7),
        "settings_btn_text": (0.0, 0.7, 0.0, 0.9),
        "font_name": "Mono",
    },

    "sunset": {
        "name": "Sunset",
        "window_bg": (0.08, 0.04, 0.06, 1),
        # Face
        "face_screen": (0.12, 0.05, 0.08, 1),
        "face_eye": (1.0, 0.72, 0.45, 1),
        "face_pupil": (0.12, 0.05, 0.08, 1),
        "face_mouth": (1.0, 0.72, 0.45, 1),
        "face_sparkle": (1.0, 0.5, 0.2, 1.0),
        "face_blush": (0.95, 0.35, 0.35, 0.35),
        "face_signal": (0.95, 0.55, 0.3, 0.6),
        "face_brow": (0.95, 0.65, 0.40, 1),
        "face_mouth_inner": (0.08, 0.04, 0.06, 1),
        "face_lip": (0.95, 0.70, 0.45, 1),
        "face_tongue": (0.95, 0.45, 0.35, 0.55),
        "face_thought_dot": (1.0, 0.65, 0.35, 0.7),
        # Status
        "status_bg": (0.10, 0.05, 0.08, 0.9),
        # Toggles
        "toggle_on": (0.80, 0.35, 0.20, 1),
        "toggle_off": (0.20, 0.12, 0.14, 1),
        "toggle_on_text": (1, 1, 1, 0.95),
        "toggle_off_text": (0.55, 0.42, 0.45, 0.9),
        "toggle_bg": (0.10, 0.05, 0.08, 0.9),
        # Chat
        "bubble_user": (0.70, 0.28, 0.12, 0.92),
        "bubble_assistant": (0.14, 0.08, 0.10, 0.92),
        "bubble_info": (0.12, 0.07, 0.08, 0.50),
        "bubble_error": (0.55, 0.12, 0.18, 0.80),
        "text_user": (1.0, 0.95, 0.88, 1),
        "text_assistant": (0.92, 0.78, 0.72, 1),
        "text_info": (0.55, 0.42, 0.40, 0.9),
        "text_error": (1, 0.62, 0.58, 1),
        "chat_bg": (0.06, 0.03, 0.05, 0.85),
        "chat_input_bg": (0.14, 0.08, 0.10, 1),
        "chat_input_text": (0.95, 0.82, 0.72, 1),
        # Accent
        "accent": (0.90, 0.48, 0.22, 1),
        "settings_btn_bg": (0.20, 0.12, 0.14, 0.7),
        "settings_btn_text": (0.80, 0.62, 0.52, 0.9),
        "font_name": "Roboto",
    },

    "ocean": {
        "name": "Ocean",
        "window_bg": (0.04, 0.07, 0.12, 1),
        # Face
        "face_screen": (0.04, 0.09, 0.16, 1),
        "face_eye": (0.45, 0.85, 1.0, 1),
        "face_pupil": (0.04, 0.09, 0.16, 1),
        "face_mouth": (0.45, 0.85, 1.0, 1),
        "face_sparkle": (0.2, 0.9, 1.0, 1.0),
        "face_blush": (0.30, 0.55, 0.90, 0.30),
        "face_signal": (0.25, 0.75, 1.0, 0.6),
        "face_brow": (0.40, 0.78, 0.95, 1),
        "face_mouth_inner": (0.04, 0.09, 0.16, 1),
        "face_lip": (0.42, 0.80, 0.95, 1),
        "face_tongue": (0.30, 0.60, 0.90, 0.55),
        "face_thought_dot": (0.35, 0.75, 1.0, 0.7),
        # Status
        "status_bg": (0.04, 0.08, 0.14, 0.9),
        # Toggles
        "toggle_on": (0.18, 0.55, 0.85, 1),
        "toggle_off": (0.10, 0.14, 0.22, 1),
        "toggle_on_text": (1, 1, 1, 0.95),
        "toggle_off_text": (0.40, 0.48, 0.62, 0.9),
        "toggle_bg": (0.04, 0.08, 0.14, 0.9),
        # Chat
        "bubble_user": (0.12, 0.38, 0.68, 0.92),
        "bubble_assistant": (0.08, 0.12, 0.20, 0.92),
        "bubble_info": (0.06, 0.10, 0.16, 0.50),
        "bubble_error": (0.55, 0.15, 0.22, 0.80),
        "text_user": (0.88, 0.96, 1.0, 1),
        "text_assistant": (0.72, 0.85, 0.96, 1),
        "text_info": (0.40, 0.52, 0.68, 0.9),
        "text_error": (1, 0.62, 0.58, 1),
        "chat_bg": (0.03, 0.06, 0.10, 0.85),
        "chat_input_bg": (0.08, 0.12, 0.22, 1),
        "chat_input_text": (0.78, 0.90, 1.0, 1),
        # Accent
        "accent": (0.25, 0.72, 0.98, 1),
        "settings_btn_bg": (0.10, 0.15, 0.26, 0.7),
        "settings_btn_text": (0.55, 0.75, 0.92, 0.9),
        "font_name": "Roboto",
    },
}


def get_theme(name: str) -> dict:
    """Get a theme dict by name, falling back to default."""
    return THEMES.get(name, THEMES["default"])


class ThemeManager:
    """Applies a theme to all widgets in the app."""

    def __init__(self):
        self._current_theme_name = "default"

    @property
    def current_theme(self) -> dict:
        return THEMES.get(self._current_theme_name, THEMES["default"])

    def apply(self, app, theme_name: str = None):
        """Apply a theme to the entire app. Call from any thread."""
        if theme_name:
            self._current_theme_name = theme_name
        theme = self.current_theme

        # Ensure mono font is registered if needed
        font_name = theme.get("font_name", "Roboto")
        if font_name == "Mono":
            from ui.icons import register_mono_font
            if not register_mono_font():
                # Fallback: use Roboto if mono font not found
                theme = dict(theme)
                theme["font_name"] = "Roboto"

        def _apply(dt):
            Window.clearcolor = theme["window_bg"]

            if hasattr(app, '_face') and hasattr(app._face, 'apply_theme'):
                app._face.apply_theme(theme)

            if hasattr(app, '_chat') and hasattr(app._chat, 'apply_theme'):
                app._chat.apply_theme(theme)

            if hasattr(app, '_status') and hasattr(app._status, 'apply_theme'):
                app._status.apply_theme(theme)

            # Theme the menu button
            btn = getattr(app, '_menu_btn', None)
            if btn:
                btn.background_color = theme.get("settings_btn_bg", (0.2, 0.2, 0.24, 0.7))
                btn.color = theme.get("settings_btn_text", (0.7, 0.75, 0.8, 0.9))

            # Theme the dropdown menu items
            if hasattr(app, 'apply_menu_theme'):
                app.apply_menu_theme(theme)

        Clock.schedule_once(_apply, 0)
