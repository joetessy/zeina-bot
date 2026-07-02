"""Shared file-system helpers for Zeina's data/ directory.

Used by zeina/settings.py and zeina/migrations.py so both agree on where
profiles, sessions, and memories live and how JSON is written safely.
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Optional

from zeina import config


def atomic_write_json(path: str, data: dict[str, Any]) -> None:
    """Write JSON to a temp file in data/tmp/ then atomically rename into place."""
    os.makedirs(config.TMP_DIR, exist_ok=True)
    try:
        fd, tmp_path = tempfile.mkstemp(dir=config.TMP_DIR, suffix=".json.tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
    except OSError:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)


def read_json(path: str) -> Optional[dict[str, Any]]:
    """Read a JSON object from disk; None if missing or corrupt."""
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (FileNotFoundError, json.JSONDecodeError, IOError):
        return None


def profile_path(name: str) -> str:
    return os.path.join(config.PROFILES_DIR, f"{name}.json")


def sessions_dir(profile_name: str) -> str:
    return os.path.join(config.SESSIONS_DIR, profile_name)


def memory_path(profile_name: str) -> str:
    return os.path.join(config.MEMORIES_DIR, f"{profile_name}.json")
