"""File system tools — read_file, list_directory."""
import pathlib
from .manager import tool_manager


def _get_safe_roots():
    """Return allowed root paths (lazy so config is fully loaded)."""
    from zeina import config as _cfg
    return [pathlib.Path.home(), pathlib.Path(_cfg.PROJECT_ROOT)]


_MAX_FILE_SIZE = 10_000  # 10 KB


def _safe_path(raw: str):
    """Resolve path and verify it is within an allowed root. Returns Path or None."""
    p = pathlib.Path(raw).expanduser().resolve()
    for root in _get_safe_roots():
        if p == root or root in p.parents:
            return p
    return None


@tool_manager.register(
    name="read_file",
    description="Read the text contents of a file. Only works for files inside the home directory or project folder.",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute or ~ path to the file (e.g. '~/Documents/notes.txt', '~/.zshrc'). "
                    "Use standard macOS/Linux path conventions. Expand common names: "
                    "'my documents' → '~/Documents', 'desktop' → '~/Desktop'."
                )
            }
        },
        "required": ["path"]
    }
)
def read_file(path: str) -> str:
    """Read and return file contents (up to 10 KB)."""
    p = _safe_path(path)
    if p is None:
        return "Path is outside allowed directories (home or project root)."
    if not p.exists():
        return f"File not found: {path}"
    if not p.is_file():
        return f"Not a file: {path}"
    if p.stat().st_size > _MAX_FILE_SIZE:
        return "File too large to read (> 10 KB)."
    return p.read_text(errors="replace")


_MAX_DIR_ENTRIES = 100


@tool_manager.register(
    name="list_directory",
    description="List files and folders in a directory. Defaults to the home directory.",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Directory path to list (defaults to ~). "
                    "Use standard macOS/Linux paths. Expand common names: "
                    "'my documents' → '~/Documents', 'downloads' → '~/Downloads'."
                )
            }
        },
        "required": []
    }
)
def list_directory(path: str = "~") -> str:
    """List directory contents, dirs first. Caps at 100 entries."""
    p = _safe_path(path or "~")
    if p is None:
        return "Path is outside allowed directories (home or project root)."
    if not p.exists():
        return f"Directory not found: {path}"
    if not p.is_dir():
        return f"Not a directory: {path}"
    try:
        entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name))
        lines = [f"{'[DIR] ' if e.is_dir() else '      '}{e.name}" for e in entries[:_MAX_DIR_ENTRIES]]
        if len(entries) > _MAX_DIR_ENTRIES:
            lines.append(f"... ({len(entries) - _MAX_DIR_ENTRIES} more entries not shown)")
        return "\n".join(lines) or "Empty directory."
    except PermissionError:
        return f"Permission denied: {path}"
