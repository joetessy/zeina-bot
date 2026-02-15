# Zeina Evolution Plan
## From Terminal Assistant to GUI Agent with Tools

**Goal:** Transform Zeina into a fully-featured AI assistant with web search, tools, and a touch-friendly GUI for Raspberry Pi deployment.

**Target Hardware:** Raspberry Pi 4/5 with 5-7" touchscreen display

**Model:** llama3.1:8b (native tool calling support)

---

## Phase 1: Agent Framework + Web Search ✅

### Overview
Add tool/function calling capabilities to enable Zeina to use external tools like web search.

### Architecture Changes
```
Current Flow:
User Input → Whisper → LLM → TTS → Response

New Flow:
User Input → Whisper → LLM → [Tool Check] → Execute Tools → LLM → TTS → Response
                                    ↓
                              Tools: Search, Weather, etc.
```

### Status: COMPLETE
- Tool framework with decorator-based registration
- Intent classification (fast 3b model) separate from response generation
- Three tools: web_search, calculate, get_current_time, get_weather
- Tool results injected as context (no reasoning leakage)

---

## Phase 2: GUI Foundation (Kivy)

### Overview
Replace terminal UI with a Kivy-based GUI optimized for 5-7" touchscreens. The backend (assistant, audio, TTS, tools) stays the same - only the display layer changes.

### UI Concept
```
┌─────────────────────────────┐
│     [Settings] [Mode]       │  ← Top bar
├─────────────────────────────┤
│                             │
│      ┌─────────────┐        │
│      │   ◯   ◯     │        │  ← Animated Face
│      │      ‿      │        │     (BMO-inspired)
│      └─────────────┘        │
│    🎤 Ready to listen       │  ← Status
│                             │
├─────────────────────────────┤
│  You: Hello!                │
│  ┌─────────────────────┐   │
│  │ Zeina: Hi there!    │   │  ← Chat History
│  │ How can I help?     │   │     (scrollable)
│  └─────────────────────┘   │
│                             │
└─────────────────────────────┘
   [🎤 Voice] [💬 Chat]         ← Mode Toggle
```

### Display Mode Requirements

The GUI must support flexible, independently toggleable UI elements. Each element can be shown or hidden independently:

| Element | Description | Default (Voice) | Default (Chat) |
|---------|-------------|-----------------|-----------------|
| **Face** | Animated BMO-inspired face | Shown | Shown |
| **Status** | Current state (listening, processing, etc.) | Hidden | Shown |
| **Tool Log** | Tool execution details and results | Hidden | Shown |
| **Chat/Transcript** | Conversation history | Hidden | Shown |
| **Speaking Response** | TTS audio playback | Enabled | Disabled |

**Presets:**
- **Clean** (default Voice): Face only - minimal, focused view
- **Full** (default Chat): Everything visible - face, status, tool log, chat
- Users can toggle any element independently from the preset baseline
- Speaking responses can be enabled in chat mode or disabled in voice mode

**Control Scheme:**
- Touchscreen: On-screen toggle buttons/icons for each element
- Keyboard: Hotkeys for each toggle (works on laptop now, transfers to robot later)
- All controls should work well on both laptop and eventual robot with 5-7" touchscreen

### Implementation Tasks

#### 2.1 Kivy Setup
- [ ] Add Kivy to `requirements.txt`
- [ ] Create `gui_main.py` - entry point for GUI version
- [ ] Basic Kivy window with responsive layout

#### 2.2 Face Widget (`widgets/face.py`)
- [ ] Port ASCII face to Kivy Canvas drawing
- [ ] Implement smooth animation states:
  - Idle (blinking)
  - Listening (focused)
  - Processing (thinking)
  - Speaking (mouth movement)
- [ ] BMO-inspired color scheme (teal/green)

#### 2.3 Chat Interface (`widgets/chat.py`)
- [ ] ScrollView with message bubbles
- [ ] User messages (right-aligned, green)
- [ ] Assistant messages (left-aligned, teal)
- [ ] Tool execution indicators (inline or separate panel)
- [ ] Auto-scroll to latest message

#### 2.4 Status Bar (`widgets/status.py`)
- [ ] Current mode indicator
- [ ] Model name display
- [ ] Status message (listening, processing, etc.)
- [ ] Timing metrics (when observability enabled)

#### 2.5 Display Toggle System
- [ ] Independent toggle for each UI element (face, status, tool log, chat, speaking)
- [ ] Preset modes (Clean, Full) with per-element override
- [ ] Touchscreen toggle buttons/icons
- [ ] Keyboard hotkeys for each toggle
- [ ] Persist toggle state across mode switches
- [ ] Enable/disable speaking response independently of mode

#### 2.6 Core Integration
- [ ] Port `ZeinaAssistant` to work with GUI (abstract display interface)
- [ ] Bridge audio callbacks to GUI updates
- [ ] Thread-safe GUI updates from audio/LLM threads
- [ ] Keep backend unchanged - refactor only the display layer

### Deliverables
- Working Kivy GUI with animated face
- Independently toggleable UI elements with presets
- Chat interface with conversation history
- Touch + keyboard controls
- Terminal version preserved as `main.py`, GUI as `gui_main.py`

---

## Phase 3: Settings & Polish

### Overview
Add settings UI and polish the user experience.

### Implementation Tasks

#### 3.1 Settings Screen (`screens/settings.py`)
- [ ] Model selection dropdown (from Ollama models)
- [ ] Voice selection (TTS voice picker)
- [ ] VAD sensitivity slider
- [ ] Silence duration slider
- [ ] Observability level toggle
- [ ] Theme options (if time permits)

#### 3.2 Settings Persistence
- [ ] Create `settings.json` for user preferences
- [ ] Load settings on startup
- [ ] Save settings on change
- [ ] Migrate from hardcoded `config.py`

#### 3.3 Face Animation Improvements
- [ ] More expressive BMO-like faces
- [ ] Emotion variations (happy, confused, thinking)
- [ ] Potential emotional engine that detects user sentiment to select response face
- [ ] Smooth interpolation between states

#### 3.4 Conversation Persistence
- [ ] Save chat history to SQLite
- [ ] Load previous conversations
- [ ] Clear history option in settings

### Deliverables
- Full settings UI
- Persistent user preferences
- Polished animations
- Conversation history

---

## Phase 4: Additional Tools

### Overview
Expand agent capabilities with more tools.

### Implementation Tasks

#### 4.1 Tool Management UI
- [ ] Settings screen showing available tools
- [ ] Enable/disable individual tools
- [ ] Tool usage statistics
- [ ] Tool help/documentation

#### 4.2 Tool Execution Feedback
- [ ] Visual indicators when tools are running
- [ ] Show tool results in chat (or tool log panel)
- [ ] Collapsible tool execution details

### Deliverables
- 4+ working tools (search, weather, calculator, time)
- Tool management interface
- Rich tool feedback in UI

---

## Project Structure (After Phase 4)

```
Zeina/
├── main.py                    # Terminal version
├── gui_main.py                # GUI version entry point
├── zeina/
│   ├── assistant.py           # Core ZeinaAssistant (shared backend)
│   ├── tools.py               # Tool framework + implementations
│   ├── audio.py               # Audio recording (shared)
│   ├── tts.py                 # Text-to-speech (shared)
│   ├── config.py              # Default config
│   ├── enums.py               # Shared enums
│   ├── display.py             # Terminal display (legacy)
│   └── face.py                # Terminal face (legacy)
│
├── ui/
│   ├── __init__.py
│   ├── app.py                 # Main Kivy App
│   ├── screens/
│   │   ├── main_screen.py     # Chat + Face
│   │   └── settings_screen.py # Settings UI
│   └── widgets/
│       ├── face.py            # Animated face widget
│       ├── chat.py            # Chat message list
│       └── status.py          # Status bar
│
├── settings.json              # User settings (generated)
├── conversations.db           # SQLite conversation history
├── requirements.txt
└── README.md
```

---

## Deployment Guide (Post Phase 4)

### Raspberry Pi Setup
```bash
# Install system dependencies
sudo apt update
sudo apt install -y python3-pip portaudio19-dev

# Install Kivy dependencies
sudo apt install -y python3-setuptools git-core
sudo apt install -y libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev

# Install Python packages
pip3 install -r requirements.txt

# Pull model
ollama pull llama3.1:8b

# Run GUI
python3 gui_main.py --fullscreen
```

### Autostart on Boot
```bash
# Add to ~/.config/autostart/zeina.desktop
[Desktop Entry]
Type=Application
Name=Zeina Assistant
Exec=/home/pi/Zeina/venv/bin/python3 /home/pi/Zeina/gui_main.py --fullscreen
```

---

## Success Metrics

### Phase 1 ✅
- Web search returns relevant results
- Tool calling works reliably
- No performance degradation

### Phase 2
- GUI runs smoothly on Pi (30+ FPS)
- Touch controls responsive
- Memory usage < 1GB
- All toggles work independently

### Phase 3
- Settings persist correctly
- UI feels polished
- Conversation history loads quickly

### Phase 4
- All 4+ tools working
- Tool execution < 2 seconds average
- Agent selects correct tools 90%+ of time

---

## Next Steps

1. ✅ Phase 1: Agent framework + web search
2. ✅ Phase 1.5: Weather tool
3. Execute Phase 2 (Kivy GUI with display toggles)
4. Test Phase 2 on target hardware
5. Execute Phase 3 (settings + polish)
6. Execute Phase 4 (additional tools)
7. Final testing and deployment
