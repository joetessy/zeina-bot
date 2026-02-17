# Zeina Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         ZeinaAssistant                                  │
│                     (assistant.py - Orchestrator)                       │
│                                                                         │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────────────────┐  │
│  │  State   │   │ Keyboard │   │  Thread  │   │  Conversation        │  │
│  │  Machine │   │ Handler  │   │  Manager │   │  History             │  │
│  │          │   │ (Kivy)   │   │          │   │  (global, shared)    │  │
│  └──────────┘   └──────────┘   └──────────┘   └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Pipeline: Voice Mode

```
                    ┌─────────────┐
                    │  User       │
                    │  pushes     │
                    │  SPACEBAR   │
                    └──────┬──────┘
                           │
                           ▼
              ┌────────────────────────┐
              │    AudioRecorder       │
              │    (audio.py)          │
              │                        │
              │  Microphone → Buffer   │
              │  Silero VAD monitors   │
              │  Auto-stop on silence  │
              │  (2s) or timeout (5s)  │
              └───────────┬────────────┘
                          │ audio_data (numpy array)
                          ▼
              ┌────────────────────────┐
              │    Whisper ASR         │
              │    (openai-whisper)    │
              │                        │
              │  Audio → Text          │
              │  Model: base (default) │
              └───────────┬────────────┘
                          │ transcription (string)
                          ▼
              ┌────────────────────────┐
              │  Intent Classification │
              │  (llama3.2:3b - fast)  │
              │                        │
              │  "Which tool needed?"  │
              │  → web_search          │
              │  → get_weather         │
              │  → calculate           │
              │  → get_current_time    │
              │  → get_system_health   │
              │  → none                │
              └───────────┬────────────┘
                          │
                ┌─────────┴─────────┐
                │                   │
          tool != none         tool == none
                │                   │
                ▼                   │
   ┌────────────────────────┐       │
   │   Tool Execution       │       │
   │   (tools.py)           │       │
   │                        │       │
   │  Execute tool function │       │
   │  Inject result as      │       │
   │  assistant context msg │       │
   └───────────┬────────────┘       │
               │                    │
               └────────┬───────────┘
                        │
                        ▼
              ┌────────────────────────┐
              │  Main LLM Response     │
              │  (llama3.1:8b)         │
              │                        │
              │  Full conversation     │
              │  history + tool context│
              │  → Natural response    │
              └───────────┬────────────┘
                          │ response text
                          ▼
              ┌────────────────────────┐
              │    Piper TTS           │
              │    (tts.py)            │
              │                        │
              │  Text → WAV → Playback │
              │  (pygame mixer)        │
              │  Interruptible         │
              └───────────┬────────────┘
                          │
                          ▼
              ┌────────────────────────┐
              │    Auto-Listen         │
              │                        │
              │  Automatically starts  │
              │  listening for follow- │
              │  up (5s timeout)       │
              └────────────────────────┘
```

## Pipeline: Chat Mode

```
              ┌────────────────────────┐
              │  User types message    │
              │  (Kivy TextInput)      │
              └───────────┬────────────┘
                          │ text
                          ▼
              ┌────────────────────────┐
              │  Intent Classification │
              │  (same as voice mode)  │
              └───────────┬────────────┘
                          │
                    ┌─────┴─────┐
                    │           │
              tool needed    no tool
                    │           │
                    ▼           │
              Tool Execution    │
                    │           │
                    └─────┬─────┘
                          │
                          ▼
              ┌────────────────────────┐
              │  Main LLM Response     │
              │  (displayed as text,   │
              │   no TTS playback)     │
              └────────────────────────┘
```

## GUI Layout (Kivy)

```
┌─────────────────────────────────────────┐
│                                     [⋮] │  ← 3-dot menu (top-right float)
│  ┌─────────────────────────────────┐    │
│  │                                 │    │
│  │         FaceWidget              │    │  ← Animated face (Vector or ASCII)
│  │      (canvas-drawn)             │    │
│  │                                 │    │
│  └─────────────────────────────────┘    │
│  ┌─────────────────────────────────┐    │
│  │ VOICE │  Push to talk   │ ZEINA │    │  ← StatusWidget (hideable)
│  └─────────────────────────────────┘    │
│  ┌─────────────────────────────────┐    │
│  │  [chat bubbles / transcript]    │    │  ← ChatWidget (hideable)
│  │                                 │    │
│  │  ╭──────────────────────────╮   │    │
│  │  │  Enter message...        │   │    │  ← Rounded TextInput (CHAT mode only)
│  │  ╰──────────────────────────╯   │    │
│  └─────────────────────────────────┘    │
└─────────────────────────────────────────┘
```

### 3-Dot Menu
Icon-only dropdown (no text labels). Clicking an item toggles its state without closing the menu. Click outside to close.

| Icon | Controls | State |
|------|----------|-------|
| 👁 | Status bar visibility | On/Off (color change) |
| 💬 | Message transcript | On/Off |
| 🔊 | TTS audio mute | Muted/Active |
| ⚙ | Settings overlay | Opens settings |

### Settings Screen
Full-screen overlay with sections:
- **General**: Bot name, observability level
- **AI Model**: Main model selector (Ollama)
- **Voice**: TTS voice, silence duration, VAD threshold
- **Appearance**: Color theme, animation style (Vector / ASCII)
- **Status Bar**: Toggle mode label, tool log, bot name
- **Conversation**: Save history, max messages (global/shared), clear history
- **Profiles**: Active profile switcher

Profile action buttons (Save / Delete) are anchored at the bottom, independent of the scroll area.

## Tool Integration (Two-Step Pattern)

This design prevents the LLM from leaking tool reasoning into its spoken response.

```
Step 1: Classification (isolated call)            Step 2: Execution + Response
┌──────────────────────────────────────┐    ┌────────────────────────────────────┐
│                                      │    │                                    │
│  User message → Small fast model     │    │  Tool result injected as assistant │
│  (3b) with simple prompt:            │    │  context message:                  │
│                                      │    │                                    │
│  "Which tool? web_search |           │    │  "I looked this up for you.        │
│   get_weather | calculate |          │    │   Here's what I found: ..."        │
│   get_current_time | none"           │    │                                    │
│                                      │    │  Then main LLM (8b) generates      │
│  Returns: tool name or "none"        │    │  natural conversational response   │
│                                      │    │  (never sees tool schema)          │
└──────────────────────────────────────┘    └────────────────────────────────────┘
```

## Threading Model

```
┌──────────────────────────────────────────────────────────────┐
│                    Kivy Main Thread                          │
│                                                              │
│  Window.bind(on_key_down) keyboard handler                   │
│  ├── SPACEBAR → start_listening() / process / interrupt      │
│  ├── TAB → toggle_mode()                                     │
│  ├── Ctrl+M → model selector popup                           │
│  └── ESC → close settings or quit                            │
│                                                              │
│  Clock.schedule_once() for all widget updates                │
└──────────────────────────────────────────────────────────────┘
         │
         │ spawns
         ▼
┌──────────────────────┐  ┌──────────────────────┐  ┌─────────────────┐
│  Face Animation      │  │  Audio Stream        │  │  Pipeline Thread│
│  (Kivy Clock 24fps)  │  │  Thread (sounddevice)│  │  (daemon, per   │
│                      │  │                      │  │   interaction)  │
│  FaceWidget ticks    │  │  Mic callback feeds  │  │                 │
│  via Clock.schedule_ │  │  AudioRecorder       │  │  Transcribe →   │
│  interval()          │  │  VAD analysis        │  │  Classify →     │
│                      │  │                      │  │  [Tool] → LLM → │
│                      │  │                      │  │  TTS → Auto-    │
│                      │  │                      │  │  listen         │
└──────────────────────┘  └──────────────────────┘  └─────────────────┘

Thread Safety:
  state_lock  → protects RecordingState transitions
  mode_lock   → protects InteractionMode transitions
  Clock.schedule_once() → all Kivy widget updates from non-main threads
```

## State Machine

```
                    ┌─────────┐
          ┌────────►│  IDLE   │◄──────────────┐
          │         └────┬────┘               │
          │              │                    │
          │         spacebar /           no speech /
          │         auto-listen          error /
          │              │               response done
          │              ▼                    │
          │        ┌───────────┐              │
     timeout       │ LISTENING │              │
     (no speech)   └─────┬─────┘              │
          │              │                    │
          │         silence detected /        │
          │         spacebar                  │
          │              │                    │
          │              ▼                    │
          │       ┌────────────┐              │
          └───────│ PROCESSING │──────────────┘
                  └────────────┘
                  (transcribe → classify → [tool] → LLM → TTS)
```

## UI Module Structure

```
ui/
├── app.py                  # Main Kivy App class, keyboard handling, menu
├── kivy_display.py         # Display bridge (routes assistant → widgets via Clock)
├── themes.py               # Color theme definitions + ThemeManager
├── icons.py                # MDI icon font, Unicode/monospace font helpers
├── animation_themes.py     # Face renderers: Vector and ASCII
└── widgets/
    ├── face_widget.py      # Canvas-drawn animated face
    ├── status_widget.py    # Status bar (mode / status / bot name)
    ├── chat_widget.py      # Scrollable message bubbles + rounded input
    ├── toggle_panel.py     # Toggle panel (not currently mounted)
    ├── tool_log_widget.py  # Tool log strip (not currently mounted)
    └── settings_screen.py  # Full-screen settings overlay
```

## Settings & Profiles

Settings are persisted to `settings.json` in the project root.

```
settings.json
├── version: 3
├── active_profile: "default"
├── conversation_history: [...]   ← Global, shared across all profiles
└── profiles:
    ├── default: { bot_name, ollama_model, theme, animation_theme, ... }
    └── <custom>: { ... }         ← Inherits from current profile on creation
```

Key design decisions:
- **Conversation history is global** — switching profiles doesn't reset conversation
- **Max messages is global** — setting it updates all profiles simultaneously
- **Theme/animation/voice are per-profile** — each profile can have its own look and voice

## Animation Themes

Two swappable renderers implement the `AnimationRenderer` base class:

| Name | Key | Description |
|------|-----|-------------|
| Vector | `"vector"` | Procedural face with eyes, pupils, mouth, blush |
| ASCII | `"ascii"` | Unicode art frames (larger scale for readability) |

Both renderers respond to four states: `idle`, `listening`, `processing`, `speaking`.
