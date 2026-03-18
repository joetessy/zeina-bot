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
│   └── tools/               # Tool package
│       ├── __init__.py      # Re-exports tool_manager, set_memory_callback, set_ui_control_callback
│       ├── manager.py       # Tool dataclass, ToolManager class, global tool_manager instance
│       ├── web.py           # web_search, get_weather, get_location
│       ├── system.py        # get_system_health, execute_shell
│       ├── filesystem.py    # read_file, list_directory
│       ├── clipboard.py     # read_clipboard, write_clipboard
│       ├── screenshot.py    # take_screenshot
│       ├── memory.py        # remember + set_memory_callback
│       ├── time_calc.py     # get_current_time, calculate
│       └── ui_control.py    # control_self + set_ui_control_callback
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
              └─→ tools/           (tool_manager - tool framework + per-module registrations)
```

## Module Responsibilities

| Module | Key Class/Object | Purpose |
|--------|-----------------|---------|
| `assistant.py` | `ZeinaAssistant` | Orchestrates entire pipeline: audio → transcription → tools → LLM → TTS |
| `tools/` | `tool_manager` | Tool package: 14 tools across 8 modules (web, system, filesystem, clipboard, screenshot, memory, time_calc, ui_control) |
| `audio.py` | `AudioRecorder` | Records from mic with real-time VAD, auto-stops on silence/timeout |
| `tts.py` | `TTSEngine` | Text-to-speech via Piper, playback via pygame |
| `display.py` | `Display` | Terminal UI: menu bar, face area, status lines, message panels |
| `face.py` | `Face` | ASCII art animation frames for each assistant state |
| `config.py` | (constants) | Models, audio settings, VAD thresholds, system prompt, controls |
| `enums.py` | `RecordingState`, `InteractionMode` | State machine enums |
