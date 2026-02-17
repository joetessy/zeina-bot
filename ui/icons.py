"""
Icon font support for Zeina AI Assistant.

Registers Material Design Icons webfont and provides icon helpers.
Also locates a Unicode-capable font for ASCII face rendering.
"""
import os
from kivy.core.text import LabelBase

from zeina import config

# ── Font paths ────────────────────────────────────────────────

MDI_FONT_PATH = os.path.join(config.PROJECT_ROOT, "fonts", "materialdesignicons-webfont.ttf")

# System fonts with good Unicode coverage (geometric shapes, misc symbols)
_UNICODE_FONT_CANDIDATES = [
    # macOS
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Apple Symbols.ttf",
    # Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    # Windows
    "C:/Windows/Fonts/seguisym.ttf",
    "C:/Windows/Fonts/arialuni.ttf",
]

_unicode_font_cache = None
_mono_font_cache = None

_MONOSPACE_FONT_CANDIDATES = [
    # macOS
    "/System/Library/Fonts/Menlo.ttc",
    "/Library/Fonts/Courier New.ttf",
    "/System/Library/Fonts/Supplemental/Courier New.ttf",
    # Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
    # Windows
    "C:/Windows/Fonts/consola.ttf",
    "C:/Windows/Fonts/cour.ttf",
]

_mono_registered = False


def find_unicode_font():
    """Find a system font that supports Unicode geometric shapes."""
    global _unicode_font_cache
    if _unicode_font_cache is not None:
        return _unicode_font_cache
    for path in _UNICODE_FONT_CANDIDATES:
        if os.path.exists(path):
            _unicode_font_cache = path
            return path
    _unicode_font_cache = ""
    return ""


# ── MDI Icon Registration ────────────────────────────────────

_mdi_registered = False


def register_icon_font():
    """Register the Material Design Icons font with Kivy."""
    global _mdi_registered
    if _mdi_registered:
        return True
    if not os.path.exists(MDI_FONT_PATH):
        return False
    LabelBase.register(name="Icons", fn_regular=MDI_FONT_PATH)
    _mdi_registered = True
    return True


# ── MDI Icon Codepoints ──────────────────────────────────────
# These map to Material Design Icons codepoints (Private Use Area)

ICONS = {
    "dots_vertical": chr(0xF01D9),
    "cog": chr(0xF0493),
    "volume_high": chr(0xF057E),
    "volume_off": chr(0xF0581),
    "chat": chr(0xF0368),
    "wrench": chr(0xF0599),
    "tools": chr(0xF1064),
    "close": chr(0xF0156),
    "check": chr(0xF012C),
    "chevron_right": chr(0xF0142),
    "eye": chr(0xF0208),
    "eye_off": chr(0xF0209),
    "monitor": chr(0xF039F),
}


def find_monospace_font():
    """Find a system monospace font for terminal mode."""
    global _mono_font_cache
    if _mono_font_cache is not None:
        return _mono_font_cache
    for path in _MONOSPACE_FONT_CANDIDATES:
        if os.path.exists(path):
            _mono_font_cache = path
            return path
    _mono_font_cache = ""
    return ""


def register_mono_font():
    """Register a monospace font as 'Mono' with Kivy. Returns True if successful."""
    global _mono_registered
    if _mono_registered:
        return True
    path = find_monospace_font()
    if not path:
        return False
    try:
        LabelBase.register(name="Mono", fn_regular=path)
        _mono_registered = True
        return True
    except Exception:
        return False


def icon(name, fallback="?"):
    """Get an icon character by name. Returns fallback if font not registered."""
    if not _mdi_registered:
        return fallback
    return ICONS.get(name, fallback)
