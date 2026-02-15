# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Zeina is a voice-activated AI assistant with push-to-talk controls, VAD auto-stop, tool/function calling, and an animated ASCII face in a Rich terminal UI. Target deployment: Raspberry Pi 4/5 with 5-7" touchscreen.

## Commands

```bash
# Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run (requires Ollama running: ollama serve)
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
    → Intent Classification (3b model) → [Tool Execution] → LLM (8b model) → TTS → Auto-listen

Chat Mode:
  Text input → Intent Classification → [Tool Execution] → LLM → Display (no TTS)
```

### Key Modules (`zeina/` package)

- **assistant.py** (~956 lines) - Main orchestrator. State machine, keyboard handling, audio pipeline, LLM calls, tool integration. This is the central file that ties everything together.
- **tools.py** - Tool framework with decorator-based registration (`@tool_manager.register`). Tools: `web_search`, `get_current_time`, `calculate`, `get_weather`. Global `tool_manager` instance.
- **audio.py** - `AudioRecorder` class. Microphone recording with Silero VAD. Auto-stops on silence (2s) or timeout (5s).
- **tts.py** - `TTSEngine` using Piper TTS. Lazy-loads voice model, plays via pygame.
- **display.py** - Rich terminal UI with ANSI escape sequences for scrolling regions and fixed face area.
- **face.py** - Animated ASCII face with state-responsive expressions (idle/listening/processing/speaking).
- **config.py** - All configuration constants. Models, audio settings, VAD thresholds, system prompt.
- **enums.py** - `RecordingState` (IDLE/LISTENING/PROCESSING), `InteractionMode` (VOICE/CHAT).

### Tool Integration Pattern

Tools use a two-step approach to prevent the LLM from leaking tool reasoning:
1. **Intent classification** - Fast call to `INTENT_CLASSIFIER_MODEL` (3b) decides which tool (or none)
2. **Tool execution** - Result injected as assistant context message, then main LLM generates natural response

To add a new tool:
1. Register it in `tools.py` with `@tool_manager.register(name, description, parameters)`
2. Add its name to the classifier prompt in `assistant.py:_classify_tool_intent()`
3. Add argument extraction logic in `assistant.py:_build_tool_args()`

### Threading Model

- Main thread: keyboard listener (pynput)
- Daemon thread: face animation
- Audio stream thread: microphone callbacks
- Spawned daemon threads: audio processing pipeline (transcription → LLM → TTS)
- Thread safety: `threading.Lock()` for state and mode transitions

### Configuration

All settings in `zeina/config.py`. Key ones:
- `OLLAMA_MODEL` - Main LLM (default: `llama3.1:8b`)
- `INTENT_CLASSIFIER_MODEL` - Fast classifier (default: `llama3.2:3b`)
- `SYSTEM_PROMPT` - Optimized for voice output (brevity, no markdown, oral style)
- `VAD_THRESHOLD`, `SILENCE_DURATION`, `LISTENING_TIMEOUT` - Voice detection tuning
- `OBSERVABILITY_LEVEL` - `"off"` | `"lite"` | `"verbose"`

### Keyboard Controls

- `SPACEBAR` - Record / stop / interrupt TTS
- `TAB` - Toggle Voice/Chat mode
- `Ctrl+M` - Change LLM model
- `ESC` - Quit
