"""
Settings persistence for Zeina AI Assistant.

Layout on disk:
  data/settings.json          — app state: version, active_profile
  data/profiles/<name>.json   — one file per profile; settings ONLY (no history)
  data/sessions/<profile>/    — one JSON file per session; conversation messages

Split-out collaborators:
  zeina/settings_defaults.py  DEFAULT_PROFILE / DEFAULT_APP_STATE / MEMORY_CAP
  zeina/storage.py            atomic JSON writes + data-dir path helpers
  zeina/migrations.py         one-time on-disk format migrations
  zeina/prompt_builder.py     system prompt + state banner assembly

No Kivy dependency — usable without the GUI.
"""
from __future__ import annotations

import copy
import os
import threading
from datetime import datetime
from typing import Any, Optional

from zeina import config, migrations, prompt_builder
from zeina.settings_defaults import DEFAULT_APP_STATE, DEFAULT_PROFILE, MEMORY_CAP
from zeina.storage import (
    atomic_write_json,
    memory_path,
    profile_path,
    read_json,
    sessions_dir,
)
from zeina.types import ChatMessage

SETTINGS_PATH = config.SETTINGS_FILE


class Settings:
    """Load, save, and provide access to per-profile settings.

    Each profile is stored as its own JSON file in data/profiles/.
    Conversation history lives in data/sessions/<profile>/ — one file per
    session — so switching profiles gives the assistant independent context
    and sessions survive crashes.

    Thread-safe: all reads/writes are serialised through a lock and use
    atomic file replacement so a crash mid-write never corrupts data.
    """

    def __init__(self, path: str = SETTINGS_PATH) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._ensure_dirs()
        self._app = self._load_app_state()
        if migrations.migrate_app_state(self._app):
            self._save_app_state()
        migrations.migrate_profiles_to_sessions()
        migrations.migrate_model_keys()
        self._ensure_default_profile()
        self._profile_cache = self._load_profile(self.active_profile_name)
        migrations.cleanup_broken_exports()

    # ── Directory & file bootstrap ───────────────────────────────

    def _ensure_dirs(self) -> None:
        for d in (config.DATA_DIR, config.PROFILES_DIR, config.SESSIONS_DIR,
                  config.MEMORIES_DIR, config.CONVERSATIONS_DIR,
                  config.LOGS_DIR, config.TMP_DIR):
            os.makedirs(d, exist_ok=True)

    # ── App state (settings.json) ────────────────────────────────

    def _load_app_state(self) -> dict[str, Any]:
        state = read_json(self._path)
        if state is not None:
            state.setdefault("version", 4)
            state.setdefault("active_profile", "default")
            return state
        state = copy.deepcopy(DEFAULT_APP_STATE)
        atomic_write_json(self._path, state)
        return state

    def _save_app_state(self) -> None:
        atomic_write_json(self._path, self._app)

    # ── Profile file I/O ─────────────────────────────────────────

    def _load_profile(self, name: str) -> dict[str, Any]:
        data = read_json(profile_path(name))
        if data is not None:
            # Backfill any setting keys added since this profile was created
            for key, val in DEFAULT_PROFILE.items():
                data.setdefault(key, val)
            # Strip any stale conversation_history that snuck back in
            data.pop("conversation_history", None)
            return data
        return copy.deepcopy(DEFAULT_PROFILE)

    def _save_profile(self, name: str, data: dict[str, Any]) -> None:
        # Never let conversation_history creep back into profile files
        clean = {k: v for k, v in data.items() if k != "conversation_history"}
        atomic_write_json(profile_path(name), clean)

    def _ensure_default_profile(self) -> None:
        if not os.path.exists(profile_path("default")):
            atomic_write_json(profile_path("default"), copy.deepcopy(DEFAULT_PROFILE))

    # ── Active profile helpers ───────────────────────────────────

    @property
    def active_profile_name(self) -> str:
        return self._app.get("active_profile", "default")

    # ── Get / Set ────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._profile_cache.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._profile_cache[key] = value
            self._save_profile(self.active_profile_name, self._profile_cache)

    def get_all(self) -> dict[str, Any]:
        """Return a copy of the active profile (settings only, no history)."""
        with self._lock:
            return {k: v for k, v in self._profile_cache.items()
                    if k != "conversation_history"}

    def set_all_profiles(self, key: str, value: Any) -> None:
        """Update a setting key in every profile file (for global settings)."""
        with self._lock:
            for name in self._list_profile_names():
                data = self._load_profile(name)
                data[key] = value
                self._save_profile(name, data)
            self._profile_cache[key] = value

    # ── Profile CRUD ─────────────────────────────────────────────

    def _list_profile_names(self) -> list[str]:
        if not os.path.isdir(config.PROFILES_DIR):
            return []
        return [f[:-5] for f in sorted(os.listdir(config.PROFILES_DIR))
                if f.endswith(".json")]

    def list_profiles(self) -> list[str]:
        with self._lock:
            return self._list_profile_names()

    def create_profile(self, name: str, from_profile: Optional[str] = None) -> None:
        """Create a new profile. Copies settings from source but NOT history."""
        with self._lock:
            base = self._load_profile(from_profile) if from_profile else copy.deepcopy(DEFAULT_PROFILE)
            base.pop("conversation_history", None)  # new profile starts with no history
            self._save_profile(name, base)

    def switch_profile(self, name: str) -> None:
        with self._lock:
            if os.path.exists(profile_path(name)):
                self._app["active_profile"] = name
                self._save_app_state()
                self._profile_cache = self._load_profile(name)

    def delete_profile(self, name: str) -> bool:
        with self._lock:
            if name == "default":
                return False
            p = profile_path(name)
            if not os.path.exists(p):
                return False
            os.remove(p)
            if self._app["active_profile"] == name:
                self._app["active_profile"] = "default"
                self._save_app_state()
                self._profile_cache = self._load_profile("default")
            return True

    # ── Session-based Conversation History ───────────────────────

    def _new_session_dict(self, profile_name: str) -> dict[str, Any]:
        """Return a fresh session skeleton."""
        return {
            "started": datetime.now().isoformat(),
            "profile": profile_name,
            "model": config.CHAT_MODEL,
            "messages": [],
        }

    def _load_session_for_write(self, session_path: str) -> dict[str, Any]:
        """Return session contents ready for mutation, creating a stub if needed."""
        profile_name = os.path.basename(os.path.dirname(session_path)) or self.active_profile_name
        data = read_json(session_path)
        if data is not None:
            data.setdefault("messages", [])
            return data
        return self._new_session_dict(profile_name)

    def start_session(self, profile_name: str) -> str:
        """Return the path for a new session file (does NOT create the file yet)."""
        sess_dir = sessions_dir(profile_name)
        os.makedirs(sess_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        return os.path.join(sess_dir, f"{timestamp}.json")

    def append_to_session(self, session_path: str, user_msg: str, assistant_msg: str) -> None:
        """Atomically append a user+assistant exchange to the session file."""
        with self._lock:
            session = self._load_session_for_write(session_path)
            session["messages"].append({"role": "user", "content": user_msg})
            session["messages"].append({"role": "assistant", "content": assistant_msg})
            atomic_write_json(session_path, session)

    def append_session_event(self, session_path: str, content: str, role: str = "system") -> None:
        """Record a non-conversation event (theme change, mode switch, etc.)."""
        if not content:
            return
        with self._lock:
            session = self._load_session_for_write(session_path)
            session["messages"].append({"role": role, "content": content})
            atomic_write_json(session_path, session)

    def load_recent_messages(self, profile_name: str, max_count: int) -> list[ChatMessage]:
        """Load up to max_count recent user/assistant messages for the profile.

        Session files are read newest-first; messages are collected until max_count
        is reached, then returned in chronological order.
        """
        sess_dir = sessions_dir(profile_name)
        if not os.path.isdir(sess_dir):
            return []

        try:
            files = sorted(
                [e.path for e in os.scandir(sess_dir) if e.name.endswith('.json')],
                reverse=True,  # newest first
            )
        except OSError:
            return []

        collected: list[ChatMessage] = []
        for fpath in files:
            session = read_json(fpath)
            if session is None:
                continue
            msgs: list[ChatMessage] = [
                {"role": m["role"], "content": m["content"]}
                for m in session.get("messages", [])
                if isinstance(m, dict) and m.get("role") in ("user", "assistant")
            ]
            # Prepend so newer files don't push older messages further back
            collected = msgs + collected
            if max_count > 0 and len(collected) >= max_count:
                break

        # Trim to max_count from the most recent end
        if max_count > 0 and len(collected) > max_count:
            collected = collected[-max_count:]

        return collected

    def clear_session_history(self, profile_name: str) -> None:
        """Delete all session files for the given profile."""
        with self._lock:
            sess_dir = sessions_dir(profile_name)
            if not os.path.isdir(sess_dir):
                return
            try:
                for entry in os.scandir(sess_dir):
                    if entry.name.endswith('.json'):
                        try:
                            os.remove(entry.path)
                        except OSError:
                            pass
            except OSError:
                pass

    # ── User Memory ──────────────────────────────────────────────

    def load_memories(self, profile_name: str) -> list[str]:
        """Return the list of known facts for the profile. Thread-safe read."""
        data = read_json(memory_path(profile_name))
        if data is None:
            return []
        return data.get("facts", [])

    def _write_memories(self, profile_name: str, facts: list[str]) -> None:
        atomic_write_json(memory_path(profile_name), {
            "profile": profile_name,
            "facts": facts,
            "updated": datetime.now().isoformat(),
        })

    def append_memories(self, profile_name: str, new_facts: list[str]) -> None:
        """Add new facts to the memory file, deduplicating and capping at MEMORY_CAP."""
        if not new_facts:
            return
        with self._lock:
            existing = self.load_memories(profile_name)
            existing_lower = [f.lower() for f in existing]

            def _is_duplicate(fact: str) -> bool:
                fl = fact.lower().strip()
                for ex in existing_lower:
                    if fl == ex:
                        return True
                    # Skip if the new fact is a meaningful substring of an existing one
                    # (or vice-versa), to avoid near-duplicates like
                    # "likes coffee" vs "really likes coffee".
                    if len(fl) > 5 and len(ex) > 5 and (fl in ex or ex in fl):
                        return True
                return False

            to_add: list[str] = []
            for fact in new_facts:
                if fact.strip() and not _is_duplicate(fact):
                    to_add.append(fact)
                    # Also dedupe within this batch, not just against stored facts
                    existing_lower.append(fact.lower())
            if not to_add:
                return
            combined = existing + to_add
            # Cap: keep only the most recent MEMORY_CAP facts
            if len(combined) > MEMORY_CAP:
                combined = combined[-MEMORY_CAP:]
            self._write_memories(profile_name, combined)

    def remove_memory(self, profile_name: str, fact: str) -> None:
        """Remove a single fact from memory. No-op if the fact isn't found."""
        with self._lock:
            existing = self.load_memories(profile_name)
            updated = [f for f in existing if f != fact]
            if len(updated) == len(existing):
                return  # fact not found
            self._write_memories(profile_name, updated)

    def clear_memories(self, profile_name: str) -> None:
        """Delete all stored memories for the given profile."""
        path = memory_path(profile_name)
        with self._lock:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass

    def memory_count(self, profile_name: str) -> int:
        """Return the number of stored facts for the profile."""
        return len(self.load_memories(profile_name))

    # ── Apply to Runtime Config ──────────────────────────────────

    def apply_to_config(self) -> None:
        """Push active profile values into zeina.config module attributes."""
        profile = self.get_all()

        config.ACTIVE_PROFILE = self.active_profile_name
        config.CHAT_MODEL = profile.get("chat_model", config.CHAT_MODEL)
        config.SILENCE_DURATION = profile.get("silence_duration", config.SILENCE_DURATION)
        config.LISTENING_TIMEOUT = profile.get("listening_timeout", config.LISTENING_TIMEOUT)
        config.VAD_THRESHOLD = profile.get("vad_threshold", config.VAD_THRESHOLD)
        config.OBSERVABILITY_LEVEL = profile.get("observability_level", config.OBSERVABILITY_LEVEL)
        config.MAX_CONVERSATION_LENGTH = profile.get("max_conversation_length", config.MAX_CONVERSATION_LENGTH)
        config.SAVE_CONVERSATION_HISTORY = profile.get("save_conversation_history", config.SAVE_CONVERSATION_HISTORY)

        tts_voice = profile.get("tts_voice", "")
        if tts_voice and not os.path.isabs(tts_voice):
            tts_voice = os.path.join(config.PROJECT_ROOT, tts_voice)
        if tts_voice:
            config.TTS_VOICE = tts_voice

        ptt_key = profile.get("push_to_talk_key", "space").strip()
        if ptt_key:
            config.PUSH_TO_TALK_KEY = ptt_key

        vision_model = profile.get("vision_model", "").strip()
        if vision_model:
            config.VISION_MODEL = vision_model

        config.TTS_SPEED = float(profile.get("tts_speed", config.TTS_SPEED))

    # ── System prompt assembly ───────────────────────────────────

    def get_system_state_banner(self, runtime_state: Optional[dict[str, Any]] = None) -> str:
        """Expose the formatted runtime state banner for external callers."""
        return prompt_builder.format_system_state(self.get_all(), runtime_state)

    def get_system_prompt(self, runtime_state: Optional[dict[str, Any]] = None) -> str:
        """Assemble the full system prompt (base + personality + memory)."""
        profile = self.get_all()
        facts: list[str] = []
        if profile.get("memory_enabled", True):
            facts = self.load_memories(self.active_profile_name)
        return prompt_builder.build_system_prompt(profile, facts)
