"""
Settings persistence for Zeina AI Assistant.

Layout on disk:
  data/settings.json          — app state: version, active_profile
  data/profiles/<name>.json   — one file per profile; settings ONLY (no history)
  data/sessions/<profile>/    — one JSON file per session; conversation messages

No Kivy dependency — usable from both terminal and GUI modes.
"""
import json
import os
import copy
import tempfile
import threading
from datetime import datetime
from typing import Any, Optional

from zeina import config

SETTINGS_PATH = config.SETTINGS_FILE

DEFAULT_PROFILE = {
    "bot_name": "Zeina",
    "ollama_model": "llama3.1:8b",
    "intent_classifier_model": "llama3.2:3b",
    "tts_voice": "models/en_GB-southern_english_female-low.onnx",
    "silence_duration": 2.0,
    "listening_timeout": 5.0,
    "vad_threshold": 0.5,
    "observability_level": "lite",
    "max_conversation_length": 20,
    "save_conversation_history": True,
    "theme": "default",
    "animation_theme": "vector",
    # Status bar component visibility
    "status_show_mode": True,
    "status_show_toollog": True,
    "status_show_botname": True,
    # Personality additions (appended below the base system prompt)
    "user_name": "",            # What the AI calls the user; empty = not personalised
    "response_length": "concise",   # concise | detailed
    "language_style": "casual",    # casual | professional | wild
    "custom_instructions": "",      # Free-form addition, appended verbatim
    # User memory
    "memory_enabled": True,     # Extract and inject facts about the user
    # Vision
    "vision_model": "moondream",    # Vision-capable model for screenshot/screen queries
    # Controls
    "push_to_talk_key": "space",  # Single char (e.g. "f") or "space"
    # UI toggle states (persisted across sessions)
    "tts_muted": False,
    "chat_feed_visible": False,
    "status_bar_visible": True,
    "interaction_mode": "voice",  # "voice" | "chat"
    # conversation_history is NOT in the default template — sessions handle this.
}

# Prompt snippets for personality options
_RESPONSE_LENGTH_ADDITIONS = {
    "concise": (
        "Response length override: Be extra brief — one sentence maximum for most "
        "responses. Get straight to the point."
    ),
    "detailed": (
        "Response length override: When helpful, give thorough answers. Three to five "
        "sentences with relevant context or examples is fine when the topic warrants it."
    ),
}

_LANGUAGE_STYLE_ADDITIONS = {
    "casual": (
        "Tone override: Be relaxed and informal. Light humour is welcome. "
        "Feel free to use everyday expressions and contractions."
    ),
    "professional": (
        "Tone override: Maintain a formal, polished tone at all times. "
        "Avoid slang, contractions, and casual filler words."
    ),
    "wild": (
        "Tone override: Be unpredictable and creative. Feel free to use informal language, slang."
        "Must use humor, be unprofessional, even inappropriate."
    ),
}

MEMORY_CAP = 50  # Maximum facts stored per profile

# settings.json holds only lightweight app-level state
DEFAULT_APP_STATE = {
    "version": 4,
    "active_profile": "default",
}


def _atomic_write(path: str, data: dict) -> None:
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


def _profile_path(name: str) -> str:
    return os.path.join(config.PROFILES_DIR, f"{name}.json")


def _sessions_dir(profile_name: str) -> str:
    return os.path.join(config.SESSIONS_DIR, profile_name)


def _memory_path(profile_name: str) -> str:
    return os.path.join(config.MEMORIES_DIR, f"{profile_name}.json")


class Settings:
    """Load, save, and provide access to per-profile settings.

    Each profile is stored as its own JSON file in data/profiles/.
    Conversation history lives in data/sessions/<profile>/ — one file per
    session — so switching profiles gives the assistant independent context
    and sessions survive crashes.

    Thread-safe: all reads/writes are serialised through a lock and use
    atomic file replacement so a crash mid-write never corrupts data.
    """

    def __init__(self, path: str = SETTINGS_PATH):
        self._path = path
        self._lock = threading.Lock()
        self._ensure_dirs()
        self._app = self._load_app_state()
        self._migrate_old_format()
        self._migrate_to_sessions()
        self._ensure_default_profile()
        self._profile_cache = self._load_profile(self.active_profile_name)
        self._cleanup_broken_exports()

    # ── Directory & file bootstrap ───────────────────────────────

    def _cleanup_broken_exports(self) -> None:
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

    def _ensure_dirs(self) -> None:
        for d in (config.DATA_DIR, config.PROFILES_DIR, config.SESSIONS_DIR,
                  config.MEMORIES_DIR, config.CONVERSATIONS_DIR,
                  config.LOGS_DIR, config.TMP_DIR):
            os.makedirs(d, exist_ok=True)

    # ── App state (settings.json) ────────────────────────────────

    def _load_app_state(self) -> dict:
        if os.path.exists(self._path):
            try:
                with open(self._path, "r") as f:
                    state = json.load(f)
                state.setdefault("version", 4)
                state.setdefault("active_profile", "default")
                return state
            except (json.JSONDecodeError, IOError):
                pass
        state = copy.deepcopy(DEFAULT_APP_STATE)
        _atomic_write(self._path, state)
        return state

    def _save_app_state(self) -> None:
        _atomic_write(self._path, self._app)

    # ── Migration from older formats ─────────────────────────────

    def _migrate_old_format(self) -> None:
        """Handle two migration cases:
        - v<4: inline 'profiles' dict → extract to individual files
        - v4 with leftover 'conversation_history' → move into active profile
        """
        dirty = False

        # v<4: profiles were stored inline in settings.json
        if "profiles" in self._app:
            for name, profile_data in self._app.pop("profiles", {}).items():
                profile_data.pop("conversation_history", None)
                p = _profile_path(name)
                if not os.path.exists(p):
                    _atomic_write(p, profile_data)
            self._app["version"] = 4
            dirty = True

        # Leftover global conversation_history → discard (sessions handle this now)
        if "conversation_history" in self._app:
            self._app.pop("conversation_history", None)
            dirty = True

        if dirty:
            self._save_app_state()

    def _migrate_to_sessions(self) -> None:
        """One-time migration: move conversation_history from profile files to session files."""
        if not os.path.isdir(config.PROFILES_DIR):
            return
        try:
            for entry in os.scandir(config.PROFILES_DIR):
                if not entry.name.endswith('.json'):
                    continue
                profile_name = entry.name[:-5]
                try:
                    with open(entry.path) as f:
                        data = json.load(f)
                except (json.JSONDecodeError, IOError):
                    continue

                if "conversation_history" not in data:
                    continue

                history = data.pop("conversation_history", [])
                # Write migration file only if it doesn't already exist
                sess_dir = _sessions_dir(profile_name)
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
                            "model": config.OLLAMA_MODEL,
                            "messages": messages,
                        }
                        _atomic_write(legacy_path, session)

                # Re-save profile without conversation_history
                _atomic_write(entry.path, data)
        except OSError:
            pass

    # ── Profile file I/O ─────────────────────────────────────────

    def _load_profile(self, name: str) -> dict:
        p = _profile_path(name)
        if os.path.exists(p):
            try:
                with open(p, "r") as f:
                    data = json.load(f)
                # Backfill any setting keys added since this profile was created
                for key, val in DEFAULT_PROFILE.items():
                    data.setdefault(key, val)
                # Strip any stale conversation_history that snuck back in
                data.pop("conversation_history", None)
                return data
            except (json.JSONDecodeError, IOError):
                pass
        return copy.deepcopy(DEFAULT_PROFILE)

    def _save_profile(self, name: str, data: dict) -> None:
        # Never let conversation_history creep back into profile files
        clean = {k: v for k, v in data.items() if k != "conversation_history"}
        _atomic_write(_profile_path(name), clean)

    def _ensure_default_profile(self) -> None:
        if not os.path.exists(_profile_path("default")):
            _atomic_write(_profile_path("default"), copy.deepcopy(DEFAULT_PROFILE))

    # ── Active profile helpers ───────────────────────────────────

    @property
    def active_profile_name(self) -> str:
        return self._app.get("active_profile", "default")

    # ── Get / Set ────────────────────────────────────────────────

    def get(self, key: str, default=None) -> Any:
        with self._lock:
            return self._profile_cache.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._profile_cache[key] = value
            self._save_profile(self.active_profile_name, self._profile_cache)

    def get_all(self) -> dict:
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

    def _list_profile_names(self) -> list:
        if not os.path.isdir(config.PROFILES_DIR):
            return []
        return [f[:-5] for f in sorted(os.listdir(config.PROFILES_DIR))
                if f.endswith(".json")]

    def list_profiles(self) -> list:
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
            if os.path.exists(_profile_path(name)):
                self._app["active_profile"] = name
                self._save_app_state()
                self._profile_cache = self._load_profile(name)

    def delete_profile(self, name: str) -> bool:
        with self._lock:
            if name == "default":
                return False
            p = _profile_path(name)
            if not os.path.exists(p):
                return False
            os.remove(p)
            if self._app["active_profile"] == name:
                self._app["active_profile"] = "default"
                self._save_app_state()
                self._profile_cache = self._load_profile("default")
            return True

    # ── Session-based Conversation History ───────────────────────

    def _new_session_dict(self, profile_name: str) -> dict:
        """Return a fresh session skeleton."""
        return {
            "started": datetime.now().isoformat(),
            "profile": profile_name,
            "model": config.OLLAMA_MODEL,
            "messages": [],
        }

    def _load_session_for_write(self, session_path: str) -> dict:
        """Return session contents ready for mutation, creating a stub if needed."""
        profile_name = os.path.basename(os.path.dirname(session_path)) or self.active_profile_name
        if os.path.exists(session_path):
            try:
                with open(session_path) as f:
                    data = json.load(f)
                data.setdefault("messages", [])
                return data
            except (json.JSONDecodeError, IOError):
                pass
        return self._new_session_dict(profile_name)

    def start_session(self, profile_name: str) -> str:
        """Return the path for a new session file (does NOT create the file yet)."""
        sess_dir = _sessions_dir(profile_name)
        os.makedirs(sess_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        return os.path.join(sess_dir, f"{timestamp}.json")

    def append_to_session(self, session_path: str, user_msg: str, assistant_msg: str) -> None:
        """Atomically append a user+assistant exchange to the session file."""
        with self._lock:
            session = self._load_session_for_write(session_path)
            session["messages"].append({"role": "user", "content": user_msg})
            session["messages"].append({"role": "assistant", "content": assistant_msg})
            _atomic_write(session_path, session)

    def append_session_event(self, session_path: str, content: str, role: str = "system") -> None:
        """Record a non-conversation event (theme change, mode switch, etc.)."""
        if not content:
            return
        with self._lock:
            session = self._load_session_for_write(session_path)
            session["messages"].append({"role": role, "content": content})
            _atomic_write(session_path, session)

    def load_recent_messages(self, profile_name: str, max_count: int) -> list:
        """Load up to max_count recent user/assistant messages for the profile.

        Session files are read newest-first; messages are collected until max_count
        is reached, then returned in chronological order.
        """
        sess_dir = _sessions_dir(profile_name)
        if not os.path.isdir(sess_dir):
            return []

        try:
            files = sorted(
                [e.path for e in os.scandir(sess_dir) if e.name.endswith('.json')],
                reverse=True,  # newest first
            )
        except OSError:
            return []

        collected = []
        for fpath in files:
            try:
                with open(fpath) as f:
                    session = json.load(f)
            except (json.JSONDecodeError, IOError):
                continue
            msgs = [
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
            sess_dir = _sessions_dir(profile_name)
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

    # ── Conversation History compatibility wrappers ───────────────

    def get_conversation_history(self) -> list:
        """Return recent messages for the active profile."""
        return self.load_recent_messages(
            self.active_profile_name, config.MAX_CONVERSATION_LENGTH
        )

    def clear_conversation_history(self) -> None:
        """Delete all session files for the active profile."""
        self.clear_session_history(self.active_profile_name)

    # ── User Memory ──────────────────────────────────────────────

    def load_memories(self, profile_name: str) -> list:
        """Return the list of known facts for the profile. Thread-safe read."""
        path = _memory_path(profile_name)
        if not os.path.exists(path):
            return []
        try:
            with open(path) as f:
                data = json.load(f)
            return data.get("facts", [])
        except (json.JSONDecodeError, IOError):
            return []

    def append_memories(self, profile_name: str, new_facts: list) -> None:
        """Add new facts to the memory file, deduplicating and capping at MEMORY_CAP."""
        if not new_facts:
            return
        path = _memory_path(profile_name)
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

            to_add = [f for f in new_facts if f.strip() and not _is_duplicate(f)]
            if not to_add:
                return
            combined = existing + to_add
            # Cap: keep only the most recent MEMORY_CAP facts
            if len(combined) > MEMORY_CAP:
                combined = combined[-MEMORY_CAP:]
            _atomic_write(path, {
                "profile": profile_name,
                "facts": combined,
                "updated": datetime.now().isoformat(),
            })

    def remove_memory(self, profile_name: str, fact: str) -> None:
        """Remove a single fact from memory. No-op if the fact isn't found."""
        path = _memory_path(profile_name)
        with self._lock:
            existing = self.load_memories(profile_name)
            updated = [f for f in existing if f != fact]
            if len(updated) == len(existing):
                return  # fact not found
            _atomic_write(path, {
                "profile": profile_name,
                "facts": updated,
                "updated": datetime.now().isoformat(),
            })

    def clear_memories(self, profile_name: str) -> None:
        """Delete all stored memories for the given profile."""
        path = _memory_path(profile_name)
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
        config.OLLAMA_MODEL = profile.get("ollama_model", config.OLLAMA_MODEL)
        config.INTENT_CLASSIFIER_MODEL = profile.get("intent_classifier_model", config.INTENT_CLASSIFIER_MODEL)
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

    def _format_system_state(self, runtime_state: Optional[dict] = None) -> str:
        """Return a concise snapshot of runtime configuration for the LLM."""
        state = {
            "mode": "voice",
            "theme": self.get("theme", "default"),
            "face_style": self.get("animation_theme", "vector"),
            "vad_limit": self.get("silence_duration", config.SILENCE_DURATION),
        }
        if runtime_state:
            for key, value in runtime_state.items():
                if value is not None:
                    state[key] = value

        return (
            f"[SYSTEM_STATE: Mode={state['mode']}, Theme='{state['theme']}', "
            f"Face='{state['face_style']}', Voice Activity Detection limit={state['vad_limit']}s]"
        )

    def get_system_state_banner(self, runtime_state: Optional[dict] = None) -> str:
        """Expose the formatted runtime state banner for external callers."""
        return self._format_system_state(runtime_state)

    def get_system_prompt(self, runtime_state: Optional[dict] = None) -> str:
        """Assemble the full system prompt from base + personality additions + memory.

        Structure (all sections are additive — the base is never overwritten):
          1. Base SYSTEM_PROMPT (with bot name substituted)
          2. User name personalisation (if set)
          3. Response length override (if not concise)
          4. Language style override (if not casual)
          5. Custom instructions (if non-empty)
          6. Known user facts (if memory enabled and facts exist)
        """
        bot_name = self.get("bot_name", "Zeina")
        base = config.SYSTEM_PROMPT.replace("Zeina", bot_name)

        additions = []

        user_name = self.get("user_name", "").strip()
        if user_name:
            additions.append(
                f"The user's name is {user_name}. This is definitive — always use {user_name} "
                f"regardless of any other name that appears in the conversation history."
            )

        resp_len = self.get("response_length", "concise")
        if resp_len in _RESPONSE_LENGTH_ADDITIONS:
            additions.append(_RESPONSE_LENGTH_ADDITIONS[resp_len])

        lang_style = self.get("language_style", "casual")
        if lang_style in _LANGUAGE_STYLE_ADDITIONS:
            additions.append(_LANGUAGE_STYLE_ADDITIONS[lang_style])

        custom = self.get("custom_instructions", "").strip()
        if custom:
            additions.append(f"Additional instructions:\n{custom}")

        memory_enabled = self.get("memory_enabled", True)
        if memory_enabled:
            facts = self.load_memories(self.active_profile_name)
            if facts:
                fact_lines = "\n".join(f"- {f}" for f in facts)
                additions.append(
                    f"What you know about this user:\n{fact_lines}"
                )

        if not additions:
            return base

        return base.rstrip() + "\n\n" + "\n\n".join(additions)
