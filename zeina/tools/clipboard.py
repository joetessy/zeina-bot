"""Clipboard tools — read_clipboard, write_clipboard."""
import subprocess
import platform
from .manager import tool_manager


@tool_manager.register(
    name="read_clipboard",
    description="Read the current contents of the system clipboard.",
    parameters={"type": "object", "properties": {}, "required": []}
)
def read_clipboard() -> str:
    """Read text from the system clipboard."""
    system = platform.system()
    try:
        if system == "Darwin":
            result = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5)
            return result.stdout or "(clipboard is empty)"
        elif system == "Linux":
            for cmd in [["xclip", "-selection", "clipboard", "-o"],
                        ["xsel", "--clipboard", "--output"]]:
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        return result.stdout or "(clipboard is empty)"
                except FileNotFoundError:
                    continue
            return "Error: install xclip or xsel to use clipboard on Linux (sudo apt install xclip)."
        else:
            return "Clipboard reading is not supported on this platform."
    except Exception as e:
        return f"Error reading clipboard: {e}"


@tool_manager.register(
    name="write_clipboard",
    description="Write text to the system clipboard so the user can paste it elsewhere.",
    parameters={
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The text to copy to the clipboard"
            }
        },
        "required": ["content"]
    }
)
def write_clipboard(content: str) -> str:
    """Write text to the system clipboard."""
    system = platform.system()
    try:
        if system == "Darwin":
            result = subprocess.run(
                ["pbcopy"], input=content, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                preview = content[:60] + "..." if len(content) > 60 else content
                return f"Copied to clipboard: {preview}"
            return f"Error copying to clipboard: {result.stderr}"
        elif system == "Linux":
            for cmd in [["xclip", "-selection", "clipboard"],
                        ["xsel", "--clipboard", "--input"]]:
                try:
                    result = subprocess.run(
                        cmd, input=content, capture_output=True, text=True, timeout=5
                    )
                    if result.returncode == 0:
                        preview = content[:60] + "..." if len(content) > 60 else content
                        return f"Copied to clipboard: {preview}"
                except FileNotFoundError:
                    continue
            return "Error: install xclip or xsel to use clipboard on Linux (sudo apt install xclip)."
        else:
            return "Clipboard writing is not supported on this platform."
    except Exception as e:
        return f"Error writing to clipboard: {e}"
