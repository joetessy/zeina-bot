# Zeina Project Structure

## File Organization

```
Zeina/
├── main.py                  # Entry point - creates ZeinaAssistant and runs it
├── requirements.txt         # Python dependencies
├── CLAUDE.md                # Claude Code guidance
├── README.md                # User documentation
│
├── zeina/                   # Main package
│   ├── __init__.py          # Exports ZeinaAssistant
│   ├── assistant.py         # Main orchestrator - state machine, pipeline, tool integration
│   ├── config.py            # All configuration constants
│   ├── enums.py             # InteractionMode (VOICE/CHAT), RecordingState (IDLE/LISTENING/PROCESSING)
│   ├── audio.py             # AudioRecorder - microphone recording with Silero VAD
│   ├── tts.py               # TTSEngine - Piper TTS synthesis + pygame playback
│   ├── display.py           # Rich terminal UI with ANSI scrolling regions
│   ├── face.py              # Animated ASCII face expressions (idle/listening/processing/speaking)
│   └── tools.py             # Tool framework (decorator registration) + tool implementations
│
├── models/                  # Voice model files
│   └── en_GB-southern_english_female-low.onnx  # Piper TTS voice model
│
├── docs/                    # Documentation
│   ├── STRUCTURE.md         # This file
│   ├── ARCHITECTURE.md      # System architecture diagram
│
├── data/                    # Runtime data — gitignored (sessions, memories, profiles, logs)
└── venv/                    # Python virtual environment
```

## Import Dependencies

```
main.py
  └─→ zeina/__init__.py
        └─→ assistant.py (ZeinaAssistant)
              ├─→ config.py        (all settings)
              ├─→ enums.py         (InteractionMode, RecordingState)
              ├─→ display.py       (Display - terminal UI)
              ├─→ audio.py         (AudioRecorder - mic + VAD)
              ├─→ tts.py           (TTSEngine - speech synthesis)
              └─→ tools.py         (tool_manager - tool framework + implementations)
```

## Module Responsibilities

| Module | Key Class/Object | Purpose |
|--------|-----------------|---------|
| `assistant.py` | `ZeinaAssistant` | Orchestrates entire pipeline: audio → transcription → tools → LLM → TTS |
| `tools.py` | `tool_manager` | Registers and executes tools (web_search, calculate, get_current_time, get_weather) |
| `audio.py` | `AudioRecorder` | Records from mic with real-time VAD, auto-stops on silence/timeout |
| `tts.py` | `TTSEngine` | Text-to-speech via Piper, playback via pygame |
| `display.py` | `Display` | Terminal UI: menu bar, face area, status lines, message panels |
| `face.py` | `Face` | ASCII art animation frames for each assistant state |
| `config.py` | (constants) | Models, audio settings, VAD thresholds, system prompt, controls |
| `enums.py` | `RecordingState`, `InteractionMode` | State machine enums |
