"""Screenshot tool — captures the screen for vision analysis."""
import os
from .manager import tool_manager


@tool_manager.register(
    name="take_screenshot",
    description=(
        "Capture the current screen for visual analysis. Use when the user asks about "
        "what's on their screen, wants you to look at or read something on screen, "
        "or says 'what do you see'. Only call once per request."
    ),
    parameters={"type": "object", "properties": {}, "required": []},
)
def take_screenshot() -> str:
    """Capture the full desktop, save to data/tmp/, return the file path."""
    import sys
    from datetime import datetime as _dt
    from zeina import config as _cfg
    path = os.path.join(_cfg.TMP_DIR, f"screenshot_{_dt.now().strftime('%Y%m%d_%H%M%S')}.png")
    os.makedirs(_cfg.TMP_DIR, exist_ok=True)

    if sys.platform == "darwin":
        import subprocess
        result = subprocess.run(
            ["screencapture", "-x", "-t", "png", path],
            capture_output=True,
        )
        if result.returncode != 0 or not os.path.exists(path):
            return f"Error: screencapture failed — {result.stderr.decode().strip()}"
    else:
        try:
            import mss
            import mss.tools
        except ImportError:
            return "Error: mss library not installed. Run: pip install mss"
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
            mss.tools.to_png(shot.rgb, shot.size, output=path)

    return path
