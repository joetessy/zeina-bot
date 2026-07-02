"""Settings screen package — full-screen overlay for all profile settings.

Modules:
  rows.py      Row/section building-block widgets
  dialogs.py   Shared confirmation/info popups
  builders.py  Mixin with the per-setting row builders
  screen.py    The SettingsScreen overlay itself
"""
from ui.widgets.settings.screen import SettingsScreen

__all__ = ["SettingsScreen"]
