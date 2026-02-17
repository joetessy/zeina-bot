"""
Text-to-Speech engine for Zeina AI Assistant
"""
import sys
import os
import wave
import tempfile
import time
import pygame

from zeina import config

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

    def synthesize_to_file(self, text: str) -> str:
        """Synthesize text to a temp WAV file and return its path.

        The caller is responsible for deleting the file after playback.
        The Piper voice model is loaded lazily and cached after first use.
        """
        if self.piper_voice is None:
            self.piper_voice = PiperVoice.load(self.voice)

        os.makedirs(config.TMP_DIR, exist_ok=True)
        fd, path = tempfile.mkstemp(suffix='.wav', dir=config.TMP_DIR)
        os.close(fd)

        with wave.open(path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.piper_voice.config.sample_rate)
            for audio_chunk in self.piper_voice.synthesize(text):
                wf.writeframes(audio_chunk.audio_int16_bytes)

        return path

    def play_file(self, path: str) -> None:
        """Play a WAV file produced by synthesize_to_file(), block until done, then delete it."""
        self.is_speaking = True
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy() and self.is_speaking:
                time.sleep(0.05)
        finally:
            self.is_speaking = False
            try:
                os.remove(path)
            except OSError:
                pass

    def _speak_piper(self, text: str):
        """Generate and play speech using Piper TTS"""
        path = self.synthesize_to_file(text)
        self.play_file(path)
