"""Zeina tools package — registers all tools and exposes public API."""

from .manager import tool_manager
from .memory import set_memory_callback
from .ui_control import set_ui_control_callback

# Import all tool modules to trigger @tool_manager.register decorators
from . import (  # noqa: F401
    memory,
    web,
    time_calc,
    filesystem,
    system,
    clipboard,
    screenshot,
    ui_control,
)

__all__ = ["tool_manager", "set_memory_callback", "set_ui_control_callback"]
