"""
Audio recording and Voice Activity Detection for Zeina AI Assistant
"""
import numpy as np
import time
import torch
from zeina import config


class AudioRecorder:
    """Records audio from microphone and detects when user stops speaking"""

    def __init__(self, sample_rate: int, channels: int, vad_model, stop_callback):
        self.sample_rate = sample_rate
        self.channels = channels
        self.vad_model = vad_model
        self.stop_callback = stop_callback  # Called when silence detected
        self.is_recording = False
        self.recorded_frames = []

        # Voice activity detection state
        self.silent_chunks_count = 0
        self.speech_detected = False
        self.listen_start_time = None
        self.last_voice_time = None

        # VAD buffer - Silero needs exactly 512 samples at 16kHz
        self.vad_buffer = []
        self.vad_buffer_size = 512

        # Calculate how many silent chunks = configured silence duration
        self.silent_chunks_threshold = int(
            config.SILENCE_DURATION * sample_rate / self.vad_buffer_size
        )

    def start(self):
        """Start recording audio"""
        if not self.is_recording:
            self.is_recording = True
            self.recorded_frames = []
            self.silent_chunks_count = 0
            self.speech_detected = False
            self.listen_start_time = time.time()
            self.last_voice_time = None
            self.vad_buffer = []

    def stop(self):
        """Stop recording and return audio data"""
        self.is_recording = False
        self.listen_start_time = None

        if not self.recorded_frames:
            return None

        # Combine all recorded frames into single array
        return np.concatenate(self.recorded_frames, axis=0)

    def audio_callback(self, indata, frames, time_info, status):
        """Callback for audio stream - records audio and detects silence"""
        if status:
            print(f"⚠️  Audio status: {status}")

        if self.is_recording:
            # Save audio for transcription
            self.recorded_frames.append(indata.copy())

            # Accumulate audio for VAD analysis
            self.vad_buffer.append(indata.copy())
            total_samples = sum(chunk.shape[0] for chunk in self.vad_buffer)

            # Check for silence when we have enough samples
            if total_samples >= self.vad_buffer_size:
                # Prepare exactly 512 samples for VAD
                vad_audio = np.concatenate(self.vad_buffer, axis=0)
                vad_chunk = vad_audio[:self.vad_buffer_size].flatten().astype(np.float32)

                # Keep any leftover samples for next check
                if vad_audio.shape[0] > self.vad_buffer_size:
                    self.vad_buffer = [vad_audio[self.vad_buffer_size:]]
                else:
                    self.vad_buffer = []

                # Run VAD to detect speech/silence
                audio_tensor = torch.from_numpy(vad_chunk)
                with torch.inference_mode():
                    speech_probability = self.vad_model(audio_tensor, self.sample_rate).item()

                if speech_probability >= config.VAD_THRESHOLD:
                    self.speech_detected = True
                    self.silent_chunks_count = 0
                    self.last_voice_time = time.time()
                else:
                    self.silent_chunks_count += 1

                # Auto-stop after configured silence duration
                if self.speech_detected and self.silent_chunks_count > self.silent_chunks_threshold:
                    if self.stop_callback:
                        self.stop_callback(reason="silence")

                # Time-based fallback for silence detection
                if self.speech_detected and self.last_voice_time:
                    if (time.time() - self.last_voice_time) > config.SILENCE_DURATION:
                        if self.stop_callback:
                            self.stop_callback(reason="silence")

            # Timeout if no speech detected within configured time
            if (not self.speech_detected and
                self.listen_start_time and
                (time.time() - self.listen_start_time) > config.LISTENING_TIMEOUT):
                if self.stop_callback:
                    self.stop_callback(reason="timeout")
