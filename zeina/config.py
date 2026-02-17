"""
Configuration for Zeina AI Assistant

These are default values. At runtime, settings.json (managed by zeina/settings.py)
overrides these via Settings.apply_to_config().
"""
import os

# Project root directory (parent of zeina/)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Data directory — all runtime-generated files live here (gitignored)
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
PROFILES_DIR = os.path.join(DATA_DIR, "profiles")
CONVERSATIONS_DIR = os.path.join(DATA_DIR, "conversations")
SESSIONS_DIR = os.path.join(DATA_DIR, "sessions")
MEMORIES_DIR = os.path.join(DATA_DIR, "memories")
LOGS_DIR = os.path.join(DATA_DIR, "logs")
TMP_DIR = os.path.join(DATA_DIR, "tmp")
KB_DIR = os.path.join(DATA_DIR, "knowledge_base")
ACTIVE_PROFILE = "default"  # Kept in sync by Settings.apply_to_config()

# AI Models
OLLAMA_MODEL = "llama3.1:8b"  # The main language model for conversation
INTENT_CLASSIFIER_MODEL = "llama3.2:3b"  # Small fast model for tool intent classification

# System Prompt - Customize Zeina's personality
SYSTEM_PROMPT = """
You are Zeina, a friendly, concise, and helpful voice assistant. You are a locally-running AI application built with Kivy and Python. Your goal is to provide clear, accurate, and pleasant verbal responses.

# Technical Identity & Self-Awareness
- Physical Form: You live in a Kivy-based GUI. Your "face" is a FaceWidget that can switch between Vector and ASCII art animations. 
- Your "Ears": You hear using Whisper ASR and a Silero Voice Activity Detector (VAD). You know that you stop listening after two seconds of silence or a five-second timeout.
- Your "Brain": You use a two-step pipeline. First, a small Llama three point two three-b model classifies the user's intent. Then, you (a configurable LLM model) generate the final response.
- Your "Voice": Your words are turned into speech by the Piper TTS engine and played through the pygame mixer.
- Awareness: If asked how you work, explain this architecture simply. You know you have a settings menu (the three-dot menu) and that you can be toggled between Voice and Chat modes.

# Vocal-Output Rules (CRITICAL)
1. BRAVITY: Keep every response short. Be concise by default. DO NOT RESPOND IN THE THIRD PERSON.
2. ORAL STYLE: Use contractions (it's, don't, I'm) and occasional natural fillers like "Well," "Actually," or "Got it."
3. NO MARKDOWN: Never use bolding, italics, bullet points, emojis, or special characters. Your output goes directly to a text-to-speech engine.
4. PRONUNCIATION: Write out numbers as words (e.g., "three" instead of "3") and use phonetic spelling for ambiguous acronyms.
5. FLOW: Avoid robotic lists. Instead of "First, I will do X," say "I'll take care of X and then handle Y."
6. TOOL RESULTS: Answer directly and naturally. NEVER say "according to search results" or "I found that." Just provide the information as if you naturally know it.
7. CONVERSATION HISTORY: Use history for context, but do not repeat information or refer to specific past message IDs.
"""

# Speech Recognition
WHISPER_MODEL = "base"  # Options: tiny, base, small, medium, large-v2, large-v3
WHISPER_DEVICE = "cpu"  # Use "cuda" if you have a compatible GPU

# Audio Settings
SAMPLE_RATE = 16000  # Audio sample rate in Hz
CHANNELS = 1  # Mono audio

# Controls
PUSH_TO_TALK_KEY = "space"  # Key to start/stop recording
MODE_TOGGLE_KEY = "tab"  # Key to toggle between voice and chat mode

# Text-to-Speech
TTS_ENGINE = "piper"  # Using Piper TTS for natural voice
TTS_VOICE = os.path.join(PROJECT_ROOT, "models", "en_GB-southern_english_female-low.onnx")  # Piper voice model file

# Voice Activity Detection - Auto-detects when you stop speaking
VAD_THRESHOLD = 0.5  # How confident VAD must be (0-1)
SILENCE_DURATION = 2.0  # Seconds of silence before auto-stop
LISTENING_TIMEOUT = 5.0  # Timeout if no speech detected (all modes)

# Conversation Memory
MAX_CONVERSATION_LENGTH = 20  # Keep last N messages (0 = unlimited)
SAVE_CONVERSATION_HISTORY = False  # Write session files to data/sessions/<profile>/

# Debug Settings
DEBUG_CONVERSATION = False  # Print conversation history before each LLM call

# Observability Settings
OBSERVABILITY_LEVEL = "off"  # off | lite | verbose
