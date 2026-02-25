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
│  │          │   │ (Kivy)   │   │          │   │  (per-profile)       │  │
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
              │  → get_location        │
              │  → read_file           │
              │  → list_directory      │
              │  → get_system_health   │
              │  → take_screenshot     │
              │  → remember            │
              │  → execute_shell       │
              │  → read_clipboard      │
              │  → write_clipboard     │
              │  → none                │
              └───────────┬────────────┘
                          │
                ┌─────────┴─────────┐
                │                   │
          tool != none         tool == none
                │                   │
                ▼                   │
   ┌────────────────────────┐       │
   │   Arg Extraction       │       │
   │   (llama3.2:3b)        │       │
   │                        │       │
   │  Second fast LLM call  │       │
   │  extracts structured   │       │
   │  args from user text   │       │
   └───────────┬────────────┘       │
               │                    │
               ▼                    │
   ┌────────────────────────┐       │
   │   Tool Execution       │       │
   │   (tools.py)           │       │
   │                        │       │
   │  Execute tool function │       │
   │  Inject result as      │       │
   │  [DATA] user message   │       │
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
              │  history + tool data   │
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
           Arg Extraction       │
                    │           │
                    ▼           │
              Tool Execution    │
                    │           │
                    └─────┬─────┘
                          │
                          ▼
              ┌────────────────────────┐
              │  Main LLM Response     │
              │  (token stream →       │
              │   chat bubbles,        │
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

Icon-only dropdown (no text labels). Clicking an item toggles its state without closing the menu.

| Icon | Controls | State |
|------|----------|-------|
| Monitor | Status bar visibility | On/Off |
| Chat | Message transcript | On/Off |
| Volume | TTS audio mute | Muted/Active |
| Cog | Settings overlay | Opens settings |

### Settings Screen

Full-screen overlay with sections:
- **General**: Bot name, observability level (`off` / `lite` / `verbose`)
- **AI Model**: Main model selector (fetches live list from Ollama)
- **Voice**: TTS voice selector (scans `models/`), silence duration, VAD threshold
- **Appearance**: Color theme, animation style (Vector / ASCII)
- **Conversation**: Save history toggle, max messages, clear history
- **Profiles**: Active profile switcher, new profile creation, delete profile

Profile Save / Delete buttons are anchored at the bottom, independent of the scroll area.

## Tool Integration (Three-Step Pattern)

This design prevents the LLM from leaking tool reasoning into its spoken response.

```
Step 1: Classification          Step 2: Arg Extraction        Step 3: Execution + Response
┌───────────────────────┐    ┌────────────────────────┐    ┌───────────────────────────────┐
│                       │    │                        │    │                               │
│  User message →       │    │  Same fast model (3b)  │    │  Tool result injected as a    │
│  small fast model     │    │  extracts structured   │    │  [DATA] user message:         │
│  (3b):                │    │  args from natural     │    │                               │
│                       │    │  language:             │    │  "[DATA] Search results for   │
│  "Which tool?         │    │                        │    │   'Paris weather' ..."        │
│   web_search |        │    │  location="London"     │    │                               │
│   get_weather |       │    │  query="latest news"   │    │  Main LLM (8b) then generates │
│   calculate |         │    │  expression="2+2"      │    │  a natural conversational     │
│   get_current_time |  │    │  path="~/notes.txt"    │    │  response — never sees tool   │
│   get_location |      │    │                        │    │  schema directly              │
│   read_file |         │    │                        │    │                               │
│   list_directory |    │    │                        │    │                               │
│   get_system_health | │    │                        │    │                               │
│   none"               │    │                        │    │                               │
│                       │    │                        │    │                               │
└───────────────────────┘    └────────────────────────┘    └───────────────────────────────┘
```

### Tool Reference

| Tool | Description | Key Restriction |
|------|-------------|----------------|
| `web_search` | DuckDuckGo search, top 5 results | Requires internet |
| `get_weather` | Current conditions via OpenWeatherMap | Requires `OPENWEATHERMAP_API_KEY` in `.env` |
| `calculate` | Safe math eval (trig, logs, constants) | No arbitrary code execution |
| `get_current_time` | Current date/time with optional timezone | — |
| `get_location` | Approximate location via IP (ipinfo.io) | Requires internet |
| `read_file` | File contents up to 10 KB | Restricted to `~` and project root |
| `list_directory` | Directory listing, dirs first, cap 100 | Restricted to `~` and project root |
| `get_system_health` | CPU, memory, disk, battery, uptime (JSON) | Read-only; no historical data |
| `take_screenshot` | Capture screen, vision-model interprets, main LLM responds | macOS: `screencapture -x`; Linux: mss. Window hidden during capture |
| `remember` | Save a user fact to long-term memory | Extracted by classifier LLM; stored in `data/memories/<profile>.json` |
| `execute_shell` | Run a shell command | Requires verbal confirmation first; Zeina speaks the command and waits for user voice approval |
| `read_clipboard` | Read system clipboard text | No internet; macOS/Linux |
| `write_clipboard` | Write text to system clipboard | No internet; macOS/Linux |

### Vision Pipeline (take_screenshot)

```
User asks about screen content
        │
        ▼
  Kivy window hidden
  (hide_window → Window.hide())
        │
        ▼
  Screenshot captured
  macOS: screencapture -x /tmp/...png
  Linux: mss.monitors[1]
        │
        ▼
  Kivy window shown again
        │
        ▼
  Sanity check: file must be > 10 KB
  (blank/black = Screen Recording denied)
        │
        ▼
  Image resized to ≤ 1280 px wide (Pillow)
        │
        ▼
  Vision model (moondream default)
  prompted: "describe all visible text,
  windows, UI elements verbatim"
        │ description
        ▼
  Injected as: "[I am currently looking
  at the user's screen...] {description}
  Using what I can see, respond to:
  {user_message}"
        │
        ▼
  Main LLM responds with Zeina's
  personality as if actively watching
```

Vision model is configured per-profile: Settings > AI Model > Vision Model.

## Threading Model

```
┌──────────────────────────────────────────────────────────────┐
│                    Kivy Main Thread                          │
│                                                              │
│  Window.bind(on_key_down) keyboard handler                   │
│  ├── SPACEBAR → start_listening() / process / interrupt      │
│  ├── TAB → toggle_mode()                                     │
│  ├── Ctrl+M → model selector popup                           │
│  ├── Ctrl+D → toggle diagnostics overlay                     │
│  └── ESC → close overlay or quit                             │
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
│                      │  │                      │  │  Extract args → │
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
                  (transcribe → classify → extract args → [tool] → LLM → TTS)
```

## UI Module Structure

```
ui/
├── app.py                  # Main Kivy App class, keyboard handling, menu
├── kivy_display.py         # Display bridge (routes assistant → widgets via Clock)
├── themes.py               # Color theme definitions + ThemeManager (5 themes)
├── icons.py                # MDI icon font, Unicode/monospace font helpers
├── animation_themes.py     # Face renderers: BMORenderer (vector) and ASCIIRenderer
└── widgets/
    ├── face_widget.py      # Canvas-drawn animated face (4 states, 24fps)
    ├── status_widget.py    # Status bar (mode / status / bot name)
    ├── chat_widget.py      # Scrollable message bubbles + rounded input
    ├── settings_screen.py  # Full-screen settings overlay (6 sections)
    ├── diagnostics_widget.py  # Ctrl+D live state + event log overlay
    ├── toggle_panel.py     # Toggle panel (not currently mounted)
    └── tool_log_widget.py  # Tool log strip (not currently mounted)
```

## Data Layout

```
data/                          ← gitignored, auto-created on first run
  settings.json                ← Active profile name only
  profiles/
    default.json               ← Per-profile settings (bot name, model, theme, ...)
    <custom>.json
  sessions/
    default/                   ← One JSON file per app session (if save enabled)
      2026-02-18_142741.json
    <custom>/
  memories/
    default.json               ← Up to 50 user facts per profile
    <custom>.json
  logs/                        ← Reserved for future structured logging
  tmp/                         ← Atomic write staging + temp audio files
```

Key design decisions:
- **Conversation history is per-profile** — switching profiles resets context
- **Settings are per-profile** — theme, model, voice, and VAD settings are all independent
- **Memories are per-profile** — facts learned in one profile don't bleed into another
- **Atomic writes** — all JSON saves go through a tmp file + rename to prevent corruption

## Themes

Five built-in color themes, selectable from Settings > Appearance:

| Key | Display Name | Character |
|-----|-------------|-----------|
| `default` | Default | Dark teal/green |
| `midnight` | Midnight | Deep blue/purple |
| `terminal` | Terminal | Green-on-black monospace |
| `sunset` | Sunset | Warm orange/red |
| `ocean` | Ocean | Blue/cyan |

## Animation Themes

Two swappable renderers implement the `AnimationRenderer` base class:

| Name | Key | Description |
|------|-----|-------------|
| Vector | `"vector"` | Procedural face (BMORenderer) with eyes, pupils, mouth, blush, sparkles |
| ASCII | `"ascii"` | Unicode art frames, larger scale for readability |

Both respond to four states: `idle`, `listening`, `processing`, `speaking`.

## Observability

Controlled by `OBSERVABILITY_LEVEL` in `zeina/config.py` (also settable via Settings > General):

| Level | Terminal Output |
|-------|----------------|
| `off` | Silent (production default) |
| `lite` | Timestamped lines for intent classification, LLM calls, response sizes |
| `verbose` | Everything in `lite` plus full tool result previews |

All events are also appended to `assistant.event_log` (a `deque(maxlen=50)`) regardless of level, so the Ctrl+D diagnostics panel always has data.
