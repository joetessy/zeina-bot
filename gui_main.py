#!/usr/bin/env python3
"""
Zeina AI Assistant - Kivy GUI Entry Point

Launches the Kivy-based GUI while keeping the same backend
(assistant, audio, TTS, tools) as the terminal version.
"""
import os
import sys
import logging

# Set Kivy config before importing Kivy
os.environ.setdefault('KIVY_LOG_LEVEL', 'warning')

# Suppress chatty third-party debug logs — never useful at any observability level.
# httpx/httpcore: raw HTTP frame events on every Ollama API call.
# piper: "Guessing voice config path" + per-utterance phoneme dumps.
for _lib in ("httpx", "httpcore", "hpack", "urllib3", "piper", "piper.voice"):
    logging.getLogger(_lib).setLevel(logging.WARNING)

# Initialize pygame mixer early to avoid SDL conflicts with Kivy.
# Both pygame and Kivy use SDL; initializing pygame's audio subsystem
# first prevents contention over the audio device.
try:
    import pygame
    pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
except (ImportError, pygame.error) as e:
    # TTS will handle this if pygame fails to initialize
    print(f"Warning: pygame mixer initialization failed: {e}", file=sys.stderr)

from dotenv import load_dotenv
load_dotenv()

from ui.app import ZeinaApp


def main():
    """Entry point for the Kivy GUI application."""
    try:
        ZeinaApp().run()
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Fatal error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()