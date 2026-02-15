#!/usr/bin/env python3
"""
Zeina AI Assistant - Entry Point
A voice-activated AI assistant using Whisper, Ollama, and TTS
"""
import sys
from dotenv import load_dotenv
from zeina import ZeinaAssistant

load_dotenv()


def main():
    """Application entry point"""
    assistant = None
    try:
        assistant = ZeinaAssistant()
        assistant.run()
    except KeyboardInterrupt:
        if assistant:
            assistant._save_conversation()
        print("\n👋 Goodbye!")
    except Exception as e:
        if assistant:
            assistant._save_conversation()
        print(f"❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
