"""One-time on-disk format migrations for Zeina's data/ directory.

Each function is idempotent and safe to run on every startup; Settings calls
them in order from its constructor.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from zeina import config
from zeina.settings_defaults import DEFAULT_PROFILE
from zeina.storage import atomic_write_json, profile_path, read_json, sessions_dir


def migrate_app_state(app_state: dict[str, Any]) -> bool:
    """Migrate settings.json in place. Returns True if it changed.

    Handles:
    - v<4: inline 'profiles' dict → extract to individual files
    - leftover global 'conversation_history' → discard (sessions handle this)
    """
    dirty = False

    if "profiles" in app_state:
        for name, profile_data in app_state.pop("profiles", {}).items():
            profile_data.pop("conversation_history", None)
            p = profile_path(name)
            if not os.path.exists(p):
                atomic_write_json(p, profile_data)
        app_state["version"] = 4
        dirty = True

    if "conversation_history" in app_state:
        app_state.pop("conversation_history", None)
        dirty = True

    return dirty


def migrate_profiles_to_sessions() -> None:
    """One-time migration: move conversation_history from profile files to session files."""
    if not os.path.isdir(config.PROFILES_DIR):
        return
    try:
        for entry in os.scandir(config.PROFILES_DIR):
            if not entry.name.endswith('.json'):
                continue
            profile_name = entry.name[:-5]
            data = read_json(entry.path)
            if data is None or "conversation_history" not in data:
                continue

            history = data.pop("conversation_history", [])
            # Write migration file only if it doesn't already exist
            sess_dir = sessions_dir(profile_name)
            legacy_path = os.path.join(sess_dir, "legacy_migrated.json")
            if history and not os.path.exists(legacy_path):
                os.makedirs(sess_dir, exist_ok=True)
                messages = [
                    {"role": m.get("role", "user"), "content": m.get("content", "")}
                    for m in history
                    if isinstance(m, dict) and m.get("role") in ("user", "assistant")
                ]
                if messages:
                    session = {
                        "started": datetime.now().isoformat(),
                        "profile": profile_name,
                        "model": config.CHAT_MODEL,
                        "messages": messages,
                    }
                    atomic_write_json(legacy_path, session)

            # Re-save profile without conversation_history
            atomic_write_json(entry.path, data)
    except OSError:
        pass


def migrate_model_keys() -> None:
    """Migrate Ollama-era model keys to the OpenAI-compatible scheme.

    The old keys (`ollama_model`, `intent_classifier_model`) held Ollama ids
    like ``llama3.1:8b``. The new backend (llama.cpp / llama-swap, Ollama's
    /v1, etc.) uses different ids (``llama3.1-8b``), so the old values are not
    portable. We strip them and let the ``chat_model`` default take over;
    the user re-selects a served model from the live /v1/models list.
    """
    if not os.path.isdir(config.PROFILES_DIR):
        return
    try:
        for entry in os.scandir(config.PROFILES_DIR):
            if not entry.name.endswith('.json'):
                continue
            data = read_json(entry.path)
            if data is None:
                continue
            if "ollama_model" not in data and "intent_classifier_model" not in data:
                continue
            data.pop("ollama_model", None)
            data.pop("intent_classifier_model", None)
            data.setdefault("chat_model", DEFAULT_PROFILE["chat_model"])
            atomic_write_json(entry.path, data)
    except OSError:
        pass


def cleanup_broken_exports() -> None:
    """Delete any incomplete/corrupt conversation export files.

    These are left behind when a previous session's JSON serialization failed
    mid-write. They are never read back, so deleting them is safe.
    """
    if not os.path.isdir(config.CONVERSATIONS_DIR):
        return
    try:
        for entry in os.scandir(config.CONVERSATIONS_DIR):
            if not entry.is_dir():
                continue
            for f in os.scandir(entry.path):
                if not f.name.endswith('.json'):
                    continue
                try:
                    with open(f.path) as fh:
                        json.load(fh)
                except (json.JSONDecodeError, IOError):
                    try:
                        os.remove(f.path)
                    except OSError:
                        pass
    except OSError:
        pass
