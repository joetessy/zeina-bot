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

Zeina is a voice-activated AI assistant with push-to-talk controls, VAD auto-stop, tool/function calling, and an animated face in a Kivy GUI. Target deployment: Raspberry Pi 4/5 with 5-7" touchscreen. A legacy terminal mode (`main.py` / Rich TUI) also exists but the Kivy GUI (`gui_main.py`) is the primary interface.

## Commands

```bash
# Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run GUI (primary — requires Ollama running: ollama serve)
python gui_main.py

# Run legacy terminal mode
python main.py

# Pull a model
ollama pull llama3.1:8b
```

There is no test suite, linter, or build step. The project is pure Python.

## Architecture

### Pipeline Flow
```
Voice Mode:
  Spacebar → AudioRecorder (VAD) → Whisper transcription
    → Classification + Arg Extraction (native tool calling, 7b model) → [Tool Execution ∥] → LLM (8b model) → TTS → Auto-listen

Chat Mode:
  Text input → Classification + Arg Extraction → [Tool Execution ∥] → LLM → Display (no TTS)
```

### Key Modules (`zeina/` package — backend)

- **assistant.py** - Main orchestrator. State machine, audio pipeline, LLM calls, tool integration. Central file that ties everything together.
- **tools/** - Tool package. `manager.py` has the `ToolManager` framework; each tool lives in its own module (`web.py`, `system.py`, `filesystem.py`, `clipboard.py`, `screenshot.py`, `memory.py`, `time_calc.py`, `ui_control.py`). All 14 tools register via `@tool_manager.register`. `__init__.py` re-exports `tool_manager`, `set_memory_callback`, `set_ui_control_callback`.
- **audio.py** - `AudioRecorder` class. Microphone recording with Silero VAD. Auto-stops on silence (2s) or timeout (5s).
- **tts.py** - `TTSEngine` using Piper TTS. Lazy-loads voice model, plays via pygame.
- **display.py** / **display_protocol.py** - Legacy terminal Rich TUI + display protocol interface.
- **face.py** - Legacy ASCII face for terminal mode.
- **config.py** - All configuration constants. Models, audio settings, VAD thresholds, system prompt.
- **enums.py** - `RecordingState` (IDLE/LISTENING/PROCESSING), `InteractionMode` (VOICE/CHAT).
- **settings.py** - JSON persistence with per-profile settings, atomic writes, memory facts.

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

### Tool Integration Pattern

Tools use a two-step approach:
1. **Classification + argument extraction** — A single `ollama.chat(tools=...)` call using native tool calling. The classifier model (`qwen2.5:7b` default) receives tool schemas and returns structured tool calls with arguments already extracted. Multiple tools can be called in one request.
2. **Tool execution** — Results injected as `[DATA]` user messages, then the main LLM generates a natural response.

#### Two-stage Classification (`assistant.py:_classify_and_extract`)

**Stage 0 — Python patterns for `control_self`**: Fast regex/keyword matching for UI control actions (theme changes, mode toggles, etc.). Zero-cost, reliable for closed vocabulary. Runs before the LLM call.

**Stage 1 — Native tool calling**: A single `ollama.chat(tools=tool_schemas)` call handles all other tools. The model sees tool JSON schemas and returns structured `tool_calls` with arguments. If Stage 0 already handled `control_self`, it's excluded from the schema to avoid duplication.

**Parallel execution**: Stateless tools (`web_search`, `get_weather`, `calculate`, etc.) run concurrently via `ThreadPoolExecutor`. Sequential tools (`take_screenshot`, `execute_shell`, `control_self`) run in order with UI guards.

To add a new tool:
1. Create a new module in `zeina/tools/` (or add to an existing one) with `@tool_manager.register(name, description, parameters)`
2. Import the module in `zeina/tools/__init__.py` to trigger registration
3. The tool will automatically appear in the native tool calling schema — no prompt changes needed

### Observability

Controlled by `OBSERVABILITY_LEVEL` in `zeina/config.py`:

| Level | Output |
|-------|--------|
| `"off"` | Silent (default). No terminal debug output. |
| `"lite"` | Prints timestamped lines for intent classification, LLM calls, and response sizes. |
| `"verbose"` | Everything in `lite` plus full tool result previews. |

Output goes to **terminal only** — never to the GUI status bar. All events are also appended to `assistant.event_log` (a `deque(maxlen=50)`) regardless of level, so the diagnostics panel always has data.

Example terminal output at `"lite"`:
```
[14:23:01] [LITE] Intent [qwen2.5:7b]: web_search
[14:23:02] [LITE] LLM [llama3.1:8b] (6 msgs)
[14:23:04] [LITE] Response: 142 chars
```

### Diagnostics Dashboard

Press **Ctrl+D** (in the GUI) to open a full-screen overlay showing live state:
- Current Ollama model
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

- Main thread: Kivy event loop (GUI mode) / pynput keyboard listener (terminal mode)
- Daemon thread: face animation (terminal mode only; Kivy uses `Clock.schedule_interval`)
- Audio stream thread: sounddevice microphone callbacks
- Background daemon thread: assistant initialization (keeps UI responsive on startup)
- Spawned daemon threads: audio processing pipeline (transcription → LLM → TTS), chat input loop
- Thread safety: `threading.Lock()` for state and mode transitions

### Configuration

All settings in `zeina/config.py`. Key ones:
- `OLLAMA_MODEL` - Main LLM (default: `llama3.1:8b`)
- `INTENT_CLASSIFIER_MODEL` - Tool-calling classifier (default: `qwen2.5:7b`)
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
