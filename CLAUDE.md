# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Data Directory

All runtime-generated files live under `data/` (gitignored). The structure is created automatically on first run:

```
data/
  settings.json          # App state: active profile name only
  profiles/
    default.json         # One file per profile — settings ONLY (no history)
    work.json            # Each profile has completely independent AI context
  sessions/
    default/             # One JSON file per app session, grows incrementally
      2026-02-18_142741.json
    work/
  memories/
    default.json         # Known facts about the user, per profile (up to 50 facts)
    work.json
  logs/                  # Reserved for future structured logging
  tmp/                   # Atomic write staging + temp audio files
```

Paths are centralised in `zeina/config.py`:

| Constant | Path |
|----------|------|
| `DATA_DIR` | `data/` |
| `SETTINGS_FILE` | `data/settings.json` |
| `PROFILES_DIR` | `data/profiles/` |
| `SESSIONS_DIR` | `data/sessions/` |
| `MEMORIES_DIR` | `data/memories/` |
| `LOGS_DIR` | `data/logs/` |
| `TMP_DIR` | `data/tmp/` |

Always import paths from `config` — never hardcode them. The `data/` directory is gitignored; only the `.gitkeep` placeholder files in each subdirectory are tracked.

## Project Overview

Zeina is a voice-activated AI assistant with push-to-talk controls, VAD auto-stop, tool/function calling, and an animated face in a Kivy GUI. Target deployment: Raspberry Pi 4/5 with 5-7" touchscreen. The Kivy GUI (`gui_main.py`) is the sole interface — the old Rich-TUI terminal mode was removed.

The LLM backend is **any OpenAI-compatible server** (llama.cpp/llama-swap, Ollama's `/v1`, LM Studio, cloud). All model calls go through `zeina/llm.py`; nothing imports a vendor SDK. The backend is chosen by `ZEINA_LLM_BASE_URL` (default `http://localhost:9292/v1`).

## Commands

```bash
# Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure the backend (base URL + model ids)
cp .env.example .env   # edit ZEINA_LLM_BASE_URL / ZEINA_CHAT_MODEL / ZEINA_VISION_MODEL

# Run GUI (requires an OpenAI-compatible model server reachable at ZEINA_LLM_BASE_URL)
python gui_main.py
```

There is no test suite, linter, or build step. The project is pure Python.

## Architecture

### Pipeline Flow
```
Voice Mode:
  Spacebar → AudioRecorder (VAD) → Whisper transcription
    → Stage 0 regex (control_self) + unified tool-calling loop (one chat model)
    → [Tool Execution ∥] → final streamed answer → TTS → Auto-listen

Chat Mode:
  Text input → Stage 0 regex + unified tool-calling loop → [Tool Execution ∥] → Display (no TTS)
```

### Key Modules (`zeina/` package — backend)

- **assistant.py** - Main orchestrator. State machine, audio pipeline, the unified tool-calling loop, tool execution, vision, TTS. Central file the Kivy app drives.
- **llm.py** - The single LLM seam. Thin wrapper over the `openai` SDK pointed at `config.LLM_BASE_URL`: `chat()` (stream + non-stream), `parse_tool_calls()`, `assistant_tool_call_msg()`, `list_model_ids()`, `health()`, `image_data_uri()`.
- **memory_extractor.py** - Background extraction of durable user facts (JSON-object output, first-person gate). Runs on a worker thread after non-tool turns.
- **tools/** - Tool package. `manager.py` has the `ToolManager` framework (`to_openai_schema`, `get_tool_schemas`); each tool lives in its own module (`web.py`, `system.py`, `filesystem.py`, `clipboard.py`, `screenshot.py`, `memory.py`, `time_calc.py`, `ui_control.py`). All 14 tools register via `@tool_manager.register`. `__init__.py` re-exports `tool_manager`, `set_memory_callback`, `set_ui_control_callback`.
- **audio.py** - `AudioRecorder` class. Microphone recording with Silero VAD. Auto-stops on silence (2s) or timeout (5s).
- **tts.py** - `TTSEngine` using Piper TTS. Lazy-loads voice model, plays via pygame.
- **config.py** - All configuration constants. LLM backend (base URL, models), audio settings, VAD thresholds, system prompt.
- **enums.py** - `RecordingState` (IDLE/LISTENING/PROCESSING), `InteractionMode` (VOICE/CHAT), `face_state_from_recording()` helper.
- **settings.py** - JSON persistence with per-profile settings, atomic writes, memory facts, schema migrations.

### Key Modules (`ui/` package — Kivy GUI layer)

- **app.py** - Main Kivy app. FloatLayout wrapper, keyboard handling (Kivy Window events), dropdown menu, mode toggle, assistant init.
- **kivy_display.py** - `KivyDisplay` — implements the display protocol for Kivy, bridging the backend to GUI widgets.
- **themes.py** - `ThemeManager` with 4 built-in themes: `default`, `midnight`, `terminal`, `sunset`.
- **animation_themes.py** - `BotRenderer` (vector) and `ASCIIRenderer` (text-based) for the face widget.
- **icons.py** - MDI webfont registration and icon codepoint map. `icon(name)` helper returns the character.
- **widgets/face_widget.py** - Canvas-drawn animated face. 24fps, 4 states (idle/listening/processing/speaking).
- **widgets/status_widget.py** - 3-section status bar: mode badge (left) | status text (center) | bot name (right).
- **widgets/chat_widget.py** - Messenger-style chat bubbles + text input. Streaming token append support.
- **widgets/settings_screen.py** - Full-screen settings overlay. 10 sections covering all profile settings.
- **widgets/diagnostics_widget.py** - Ctrl+D overlay showing live assistant state and event log.

### Tool Integration Pattern — unified loop (`assistant.py:_get_llm_response`)

One chat model both decides which tools to call and writes the reply (a standard
agent loop), so there is no separate classifier model.

**Stage 0 — Python patterns for `control_self`**: Fast regex/keyword matching for UI control actions (theme changes, mode toggles, etc.). Zero-cost, reliable for closed vocabulary. Runs before any LLM call. These actions have no `tool_call_id`, so their results are injected as a short acknowledgement note, not a `tool` message.

**Stage 1 — Native tool calling**: a single `llm.chat(tools=...)` call to `CHAT_MODEL`.
- If it returns **no** tool calls (and Stage 0 matched nothing), its text **is** the answer — the common path costs one round-trip.
- If it returns tool calls, they're executed and the results fed back as proper `role:"tool"` messages (with `tool_call_id`), then a second streamed call produces the spoken answer. If Stage 0 matched `control_self`, that tool is excluded from the schema.

Tool-call/result messages live only in a **turn-local working list**; the persisted `conversation_history` stays clean user/assistant pairs.

**Parallel execution**: Stateless tools (`web_search`, `get_weather`, `calculate`, etc.) run concurrently via `ThreadPoolExecutor`. Sequential tools (`take_screenshot`, `execute_shell`, `control_self`) run in order with UI guards (window hide/raise). `take_screenshot` runs the vision model and returns the description as its tool result.

To add a new tool:
1. Create a new module in `zeina/tools/` (or add to an existing one) with `@tool_manager.register(name, description, parameters)`
2. Import the module in `zeina/tools/__init__.py` to trigger registration
3. The tool will automatically appear in the tool-calling schema — no prompt changes needed

### Observability

Controlled by `OBSERVABILITY_LEVEL` in `zeina/config.py`:

| Level | Output |
|-------|--------|
| `"off"` | Silent (default). No terminal debug output. |
| `"lite"` | Prints timestamped lines for tool routing, LLM calls, and responses. |
| `"verbose"` | Everything in `lite` plus full tool result previews. |

Output goes to **terminal only** — never to the GUI status bar. All events are also appended to `assistant.event_log` (a `deque(maxlen=50)`) regardless of level, so the diagnostics panel always has data.

Example terminal output at `"lite"`:
```
[14:23:01] [LITE] Intent [qwen2.5-7b]: web_search
[14:23:02] [LITE] LLM [qwen2.5-7b] (6 msgs)
[14:23:04] [LITE] Response: ...
```

### Diagnostics Dashboard

Press **Ctrl+D** (in the GUI) to open a full-screen overlay showing live state:
- Current chat model
- Conversation history length
- Last tool used
- Recent event log (last 50 entries, newest at bottom)

Press **Ctrl+D** again or **ESC** to close. The "Refresh" button re-snapshots state without closing.

### File System Tools

**`list_directory`** — Lists a directory's contents (dirs first, capped at 100 entries). Restricted to `~` and the project root.

**`read_file`** — Reads a file's text content (up to 10 KB). Same path restriction. Larger files are rejected.

Both use LLM-based path extraction — the model interprets what folder or file the user means using its own knowledge of standard OS path conventions. No hardcoded word-to-path mappings anywhere in the code.

**What it cannot do:** No write access, no access outside `~` or project root, no files > 10 KB.

**Example phrases:** "What's in my documents folder?", "Read my .zshrc", "What files are in ~/Projects?", "Show me ~/Documents/notes.txt"

### System Health Tool (`get_system_health`)

Provides a comprehensive real-time report of the computer's health and performance metrics as structured JSON data.

**Metrics included:**
- **System**: Operating system type, uname info, and timestamp
- **CPU**: Current usage percentage and load average
- **Memory**: Total, available, and usage percentage (in GB)
- **Storage**: Disk space (total, free, usage percentage for root filesystem)
- **Battery**: Charge level and power status (if available on laptops)
- **Network**: Basic connectivity status
- **Directory**: Current working directory
- **Uptime**: System uptime information

**What it cannot do:** No historical data, no detailed process information, no network configuration details, no temperature sensors beyond basic CPU.

**Example phrases:** "How's my computer doing?", "What's the battery level?", "How much memory is being used?", "Check system health", "What's the CPU usage?", "How much storage space do I have left?", "What OS am I running?", "What's my current directory?", "How long has this been up?", "Where is the app located?"

### Threading Model

- Main thread: Kivy event loop (owns the window, keyboard, and audio input stream)
- Audio stream thread: sounddevice microphone callbacks
- Background daemon thread: assistant initialization (keeps UI responsive on startup)
- Spawned daemon threads: audio processing pipeline (transcription → LLM → TTS), GUI chat input loop, TTS sentence synthesis
- Background (non-daemon) threads: memory extraction, tracked in `assistant._memory_threads` and joined on shutdown
- Thread safety: `threading.Lock()` for state, mode, and speaking transitions

### Configuration

LLM backend is configured via environment (see `.env.example`): `ZEINA_LLM_BASE_URL`,
`ZEINA_LLM_API_KEY`, `ZEINA_CHAT_MODEL`, `ZEINA_VISION_MODEL`, optional `ZEINA_ROUTER_MODEL`
and `ZEINA_SEARXNG_URL`. Everything else is in `zeina/config.py`:
- `CHAT_MODEL` - Main conversation + tool-calling model (env `ZEINA_CHAT_MODEL`)
- `VISION_MODEL` - Vision model for screen queries (env `ZEINA_VISION_MODEL`)
- `ROUTER_MODEL` - Optional cheap model for summaries/memory extraction (defaults to `CHAT_MODEL`)
- `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_TIMEOUT` / `LLM_MAX_RETRIES` - OpenAI-compatible client config
- `SYSTEM_PROMPT` - Optimized for voice output (brevity, no markdown, oral style)
- `VAD_THRESHOLD`, `SILENCE_DURATION`, `LISTENING_TIMEOUT` - Voice detection tuning
- `OBSERVABILITY_LEVEL` - `"off"` | `"lite"` | `"verbose"`
- `DATA_DIR`, `SETTINGS_FILE`, `PROFILES_DIR`, `SESSIONS_DIR`, `MEMORIES_DIR`, `LOGS_DIR`, `TMP_DIR` - All runtime file paths (rooted at `data/`)

### Keyboard Controls

- `SPACEBAR` - Record / stop / interrupt TTS
- `TAB` - Toggle Voice/Chat mode
- `Ctrl+M` - Change LLM model
- `Ctrl+D` - Toggle diagnostics overlay (GUI only)
- `ESC` - Close overlay / Quit
