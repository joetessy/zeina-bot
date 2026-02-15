# Zeina AI Assistant

A voice-activated AI assistant built entirely with open-source tools. Talk naturally using your voice, or switch to chat mode for text interaction. Features tool calling for web search, weather, calculations, and more.

## Features

- **Push-to-Talk**: Press spacebar to start, auto-stops when you finish speaking
- **Voice Activity Detection (VAD)**: Silero VAD detects when you stop speaking
- **Continuous Conversation**: Auto-listens for follow-up questions after responding
- **Interrupt Anytime**: Press spacebar while Zeina is speaking for instant interruption
- **Dual Modes**: Voice mode (with TTS) and Chat mode (text only), toggle with TAB
- **Tool Calling**: Web search, weather, calculator, and time tools
- **Animated Face**: ASCII art face with state-responsive expressions
- **Model Switching**: Change Ollama models on the fly with Ctrl+M

## Prerequisites

1. **Python 3.8+**
2. **Ollama** installed and running:
   ```bash
   # Install from https://ollama.ai
   ollama pull llama3.1:8b
   ollama serve
   ```

## Installation

```bash
# Clone the repository
git clone <repo-url> && cd Zeina

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Usage

```bash
python main.py
```

### Controls

| Key | Action |
|-----|--------|
| `SPACEBAR` | Start/stop recording, interrupt TTS |
| `TAB` | Toggle between Voice and Chat mode |
| `Ctrl+M` | Change Ollama model |
| `ESC` | Quit |

### Voice Mode
Press spacebar to start recording. Speak naturally - VAD auto-detects when you stop (~2s silence). Zeina transcribes, thinks, responds with voice, then auto-listens for follow-ups.

### Chat Mode
Press TAB to switch. Type your message and press Enter. Responses are displayed as text (no TTS).

## Tools

Zeina can use external tools when needed. The intent classifier automatically detects when a tool is appropriate.

| Tool | Trigger | Description |
|------|---------|-------------|
| **Web Search** | "Search for...", "Look up..." | DuckDuckGo search, returns top 5 results |
| **Weather** | "What's the weather in..." | OpenWeatherMap current conditions + forecast |
| **Calculator** | "Calculate...", math expressions | Safe eval with trig, logs, constants |
| **Time** | "What time is it?" | Current date/time with timezone support |

### Weather Tool Setup

The weather tool requires a free OpenWeatherMap API key:
1. Sign up at [openweathermap.org](https://openweathermap.org/api)
2. Copy `.env.example` to `.env` and add your key:
   ```bash
   cp .env.example .env
   # Edit .env and replace your_key_here with your actual key
   ```
3. Without an API key, the weather tool will return an error message

## Configuration

Edit `zeina/config.py` to customize:

- **OLLAMA_MODEL**: Main language model (default: `llama3.1:8b`)
- **INTENT_CLASSIFIER_MODEL**: Fast model for tool routing (default: `llama3.2:3b`)
- **WHISPER_MODEL**: Speech recognition model (`tiny`, `base`, `small`, `medium`, `large-v3`)
- **SYSTEM_PROMPT**: Zeina's personality and response style
- **TTS_VOICE**: Piper voice model path

### VAD Tuning

- **VAD_THRESHOLD** (0.5): Speech detection sensitivity (0-1, lower = more sensitive)
- **SILENCE_DURATION** (2.0): Seconds of silence before auto-stop
- **LISTENING_TIMEOUT** (5.0): Max seconds to wait for speech before returning to idle

### Observability

Set `OBSERVABILITY_LEVEL` in config:
- `"off"` - No metrics
- `"lite"` - ASR, LLM, and TTS timing displayed
- `"verbose"` - Full event logging

## Troubleshooting

**"Ollama connection failed"**
- Ensure Ollama is running: `ollama serve`
- Check model is pulled: `ollama list`

**"No speech detected"**
- Check microphone is working
- Try lowering `VAD_THRESHOLD` (e.g., 0.4)
- Try a larger Whisper model

**"Recording cuts off mid-sentence"**
- Increase `SILENCE_DURATION` (e.g., 2.5)
- Lower `VAD_THRESHOLD`

**Slow performance**
- Use `tiny` or `base` Whisper model
- Use a smaller Ollama model
- Enable GPU: set `WHISPER_DEVICE = "cuda"`

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed architecture diagrams.

## Roadmap

See [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) for the full evolution plan:
- **Phase 1**: Agent Framework + Web Search (complete)
- **Phase 1.5**: Weather Tool (complete)
- **Phase 2**: Kivy GUI for touchscreen
- **Phase 3**: Settings UI + Polish
- **Phase 4**: Additional Tools

## Credits

Built with [Whisper](https://github.com/openai/whisper), [Ollama](https://ollama.ai), [Piper TTS](https://github.com/rhasspy/piper), [Silero VAD](https://github.com/snakers4/silero-vad), [Rich](https://github.com/Textualize/rich), and [DuckDuckGo Search](https://github.com/deedy5/ddgs).
