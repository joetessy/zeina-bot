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
        self._closed = False  # once set, no new playback may start (app shutdown)

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
        """Stop current speech playback.

        Unconditional: a play_file() that hasn't set is_speaking yet must not
        slip past an interrupt, so we don't gate on the flag.
        """
        self.is_speaking = False
        try:
            pygame.mixer.music.stop()
        except pygame.error:
            pass  # mixer already quit

    def close(self):
        """Permanently stop playback ahead of app shutdown.

        After this, play_file() discards instead of playing — required before
        the mic stream is stopped, because live pygame output and a PortAudio
        stop on the same CoreAudio device can deadlock.
        """
        self._closed = True
        self.stop()

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

        from piper.config import SynthesisConfig
        length_scale = float(getattr(config, 'TTS_SPEED', 1.0))
        syn_config = SynthesisConfig(length_scale=length_scale)
        with wave.open(path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.piper_voice.config.sample_rate)
            for audio_chunk in self.piper_voice.synthesize(text, syn_config=syn_config):
                wf.writeframes(audio_chunk.audio_int16_bytes)

        return path

    def play_file(self, path: str) -> None:
        """Play a WAV file produced by synthesize_to_file(), block until done, then delete it."""
        if self._closed:
            try:
                os.remove(path)
            except OSError:
                pass
            return
        self.is_speaking = True
        try:
            pygame.mixer.music.load(path)
            if self._closed or not self.is_speaking:  # close()/stop() raced the load
                return
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy() and self.is_speaking:
                time.sleep(0.05)
        except pygame.error:
            pass  # mixer quit mid-playback during shutdown
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
