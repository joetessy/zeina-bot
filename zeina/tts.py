"""
Text-to-Speech engine for Zeina AI Assistant
"""
import sys
import os
import wave
import tempfile
import time
import pygame

try:
    from piper import PiperVoice
    PIPER_AVAILABLE = True
except ImportError:
    PIPER_AVAILABLE = False
    print("⚠️  Piper TTS not available, will fall back to macOS say")


class TTSEngine:
    """Converts text to speech using Piper TTS"""

    def __init__(self, voice: str):
        self.voice = voice
        self.is_speaking = False
        self.piper_voice = None

        self._initialize_engine()

    def _initialize_engine(self):
        """Initialize Piper TTS engine"""
        if not PIPER_AVAILABLE:
            print("❌ Piper TTS not installed!")
            print("Run: pip install piper-tts")
            sys.exit(1)

        # Initialize pygame mixer for audio playback
        pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
        print(f"✓ Piper TTS ready (voice: {self.voice})")

    def speak(self, text: str):
        """Convert text to speech and play it"""
        self.is_speaking = True
        try:
            self._speak_piper(text)
        finally:
            self.is_speaking = False

    def stop(self):
        """Stop current speech playback"""
        if self.is_speaking:
            pygame.mixer.music.stop()
            self.is_speaking = False

    def _speak_piper(self, text: str):
        """Generate and play speech using Piper TTS"""
        # Load voice model on first use (cached afterward)
        if self.piper_voice is None:
            self.piper_voice = PiperVoice.load(self.voice)

        # Create temporary file for audio
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            temp_file = f.name

        # Generate speech audio
        with wave.open(temp_file, 'wb') as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(self.piper_voice.config.sample_rate)

            # Synthesize speech
            for audio_chunk in self.piper_voice.synthesize(text):
                wav_file.writeframes(audio_chunk.audio_int16_bytes)

        # Play audio using pygame
        pygame.mixer.music.load(temp_file)
        pygame.mixer.music.play()

        # Wait for playback to finish
        while pygame.mixer.music.get_busy():
            time.sleep(0.1)

        # Cleanup temporary file
        os.remove(temp_file)
