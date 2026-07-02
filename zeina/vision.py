"""Vision: describe a screenshot with the vision model.

The returned description is injected as tool-result context for the main chat
model, which then answers with the assistant's own personality.
"""
from __future__ import annotations

import os
from typing import Callable

from zeina import llm

ObsFn = Callable[[str, str], None]

# Captures smaller than this are almost certainly blank/black (e.g. macOS
# Screen Recording permission denied) and make vision models hallucinate.
_MIN_CAPTURE_BYTES = 10_000

_MAX_WIDTH = 1280  # resize wider captures to keep inference fast

_SCREEN_READER_PROMPT = (
    "You are a precise screen reader. Describe ONLY what is literally visible in the "
    "screenshot with as much detail as possible: every window title, app name, menu, "
    "button label, visible text (quote it verbatim), error messages, code snippets, "
    "URL in the address bar, file names, icons, and the overall layout. "
    "Do NOT invent, infer, or add anything not directly visible. "
    "If something is partially obscured or unclear, say so explicitly."
)


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def describe_screenshot(
    screenshot_path: str,
    user_message: str,
    vision_model: str,
    obs: ObsFn,
) -> str:
    """Run the vision model on a screenshot and return its description.

    Deletes the screenshot when done. Returns "" if the capture is invalid or
    the vision call fails.
    """
    try:
        file_size = os.path.getsize(screenshot_path)
    except OSError:
        obs("lite", "Vision: screenshot file missing — aborting")
        return ""

    if file_size < _MIN_CAPTURE_BYTES:
        obs("lite", f"Vision: screenshot too small ({file_size} bytes) — likely blank; "
                    f"check macOS Screen Recording permission")
        _remove_quietly(screenshot_path)
        return ""

    # Resize to keep inference fast.
    try:
        from PIL import Image
        img = Image.open(screenshot_path)
        if img.width > _MAX_WIDTH:
            img = img.resize(
                (_MAX_WIDTH, int(img.height * _MAX_WIDTH / img.width)), Image.LANCZOS
            )
            img.save(screenshot_path)
    except Exception:
        pass

    obs("lite", f"Vision: screenshot {file_size // 1024} KB → {screenshot_path}")

    messages = [
        {"role": "system", "content": _SCREEN_READER_PROMPT},
        {"role": "user", "content": [
            {"type": "text", "text": user_message or "What do you see on the screen?"},
            {"type": "image_url", "image_url": {"url": llm.image_data_uri(screenshot_path)}},
        ]},
    ]

    description = ""
    try:
        for token in llm.chat(messages, model=vision_model, stream=True):
            description += token
    except Exception as e:
        obs("lite", f"Vision model error: {e}")

    description = description.strip()
    obs("lite", f"Vision [{vision_model}]: {description}")

    _remove_quietly(screenshot_path)
    return description
