"""
Audio recording and Voice Activity Detection for Zeina AI Assistant
"""
from typing import Callable, Optional

import numpy as np
import time
import torch
from zeina import config

# Silero VAD requires exactly 512 samples per inference at 16 kHz.
_VAD_CHUNK_SAMPLES = 512

StopCallback = Callable[[str], None]


class AudioRecorder:
    """Records audio from microphone and detects when user stops speaking"""

    def __init__(
        self,
        sample_rate: int,
        channels: int,
        vad_model,
        stop_callback: Optional[StopCallback],
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.vad_model = vad_model
        self.stop_callback = stop_callback  # Called when silence detected
        self.is_recording = False
        self.recorded_frames: list[np.ndarray] = []

        # Voice activity detection state
        self.speech_detected = False
        self.listen_start_time: Optional[float] = None
        self.last_voice_time: Optional[float] = None

        # VAD buffer — accumulates until a full 512-sample chunk is available
        self.vad_buffer: list[np.ndarray] = []

    def start(self) -> None:
        """Start recording audio"""
        if not self.is_recording:
            self.is_recording = True
            self.recorded_frames = []
            self.speech_detected = False
            self.listen_start_time = time.time()
            self.last_voice_time = None
            self.vad_buffer = []

    def stop(self) -> Optional[np.ndarray]:
        """Stop recording and return audio data"""
        self.is_recording = False
        self.listen_start_time = None

        if not self.recorded_frames:
            return None

        # Combine all recorded frames into single array
        return np.concatenate(self.recorded_frames, axis=0)

    def _run_vad(self) -> None:
        """Run VAD on the next full chunk in the buffer, if available."""
        total_samples = sum(chunk.shape[0] for chunk in self.vad_buffer)
        if total_samples < _VAD_CHUNK_SAMPLES:
            return

        vad_audio = np.concatenate(self.vad_buffer, axis=0)
        vad_chunk = vad_audio[:_VAD_CHUNK_SAMPLES].flatten().astype(np.float32)

        # Keep any leftover samples for next check
        if vad_audio.shape[0] > _VAD_CHUNK_SAMPLES:
            self.vad_buffer = [vad_audio[_VAD_CHUNK_SAMPLES:]]
        else:
            self.vad_buffer = []

        audio_tensor = torch.from_numpy(vad_chunk)
        with torch.inference_mode():
            speech_probability = self.vad_model(audio_tensor, self.sample_rate).item()

        if speech_probability >= config.VAD_THRESHOLD:
            self.speech_detected = True
            self.last_voice_time = time.time()

    def audio_callback(self, indata: np.ndarray, frames, time_info, status) -> None:
        """Callback for audio stream - records audio and detects silence"""
        if status:
            print(f"⚠️  Audio status: {status}")

        if not self.is_recording:
            return

        # Save audio for transcription
        self.recorded_frames.append(indata.copy())

        # Accumulate audio for VAD analysis
        self.vad_buffer.append(indata.copy())
        self._run_vad()

        # Auto-stop after the configured silence duration. Reads live config so
        # settings changes apply without restarting the recorder.
        if self.speech_detected and self.last_voice_time:
            if (time.time() - self.last_voice_time) > config.SILENCE_DURATION:
                if self.stop_callback:
                    self.stop_callback(reason="silence")
                return

        # Timeout if no speech detected within configured time
        if (not self.speech_detected and
            self.listen_start_time and
            (time.time() - self.listen_start_time) > config.LISTENING_TIMEOUT):
            if self.stop_callback:
                self.stop_callback(reason="timeout")
