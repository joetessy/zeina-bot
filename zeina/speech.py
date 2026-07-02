"""Speech output pipeline: sentence-level TTS with streaming and interrupts.

Sits between the LLM token stream and the TTS engine. A daemon synthesis
thread turns buffered sentences into WAV files while streaming continues,
giving sentence-level latency; playback (with interrupt checks) runs on the
calling thread after streaming ends.
"""
from __future__ import annotations

import os
import queue
import re
import threading
from typing import Callable

from zeina import config, llm
from zeina.display import DisplayProtocol
from zeina.tts import TTSEngine
from zeina.types import ChatMessage

ObsFn = Callable[[str, str], None]

# Sentence boundary: end punctuation + whitespace, or a paragraph break.
SENTENCE_END_RE = re.compile(r'(?<=[.!?])\s+|(?<=\n)\s*(?=\S)')

_MIN_SENTENCE_CHARS = 8   # don't synthesize fragments shorter than this
_SYNTH_JOIN_TIMEOUT = 60  # seconds to wait for the synthesis thread


class SpeechPipeline:
    """Streams LLM output to the display while speaking it sentence-by-sentence."""

    def __init__(
        self,
        get_tts: Callable[[], TTSEngine],
        display: DisplayProtocol,
        obs: ObsFn,
        set_speaking: Callable[[bool], None],
        is_interrupted: Callable[[], bool],
    ) -> None:
        # The TTS engine is swapped at runtime on profile/voice changes, so it
        # is resolved lazily via ``get_tts`` instead of being captured here.
        self._get_tts = get_tts
        self._display = display
        self._obs = obs
        self._set_speaking = set_speaking
        self._is_interrupted = is_interrupted

    @property
    def _tts(self) -> TTSEngine:
        return self._get_tts()

    # ── Public API ────────────────────────────────────────────────────

    def stream_and_speak(self, messages: list[ChatMessage]) -> str:
        """Stream an LLM response and speak each sentence as it arrives."""
        sentence_q: queue.Queue = queue.Queue(maxsize=3)
        play_q: queue.Queue = queue.Queue()
        full_response: list[str] = []

        def _synth_worker() -> None:
            while True:
                try:
                    sentence = sentence_q.get(timeout=0.3)
                except queue.Empty:
                    continue
                if sentence is None:
                    break
                try:
                    play_q.put(self._tts.synthesize_to_file(sentence))
                except Exception as e:
                    self._obs("lite", f"TTS synthesis error: {e}")
                finally:
                    sentence_q.task_done()

        synth_thread = threading.Thread(target=_synth_worker, daemon=True)
        synth_thread.start()

        buf = ""
        can_stream = getattr(self._display, 'has_streaming', False)
        if can_stream:
            self._display.begin_stream()

        try:
            for token in llm.chat(messages, model=config.CHAT_MODEL, stream=True):
                buf += token
                full_response.append(token)
                if can_stream:
                    self._display.stream_token(token)

                parts = SENTENCE_END_RE.split(buf, maxsplit=1)
                if len(parts) > 1 and len(parts[0].strip()) >= _MIN_SENTENCE_CHARS:
                    sentence_q.put(parts[0].strip())
                    buf = parts[1]
        except Exception as e:
            self._obs("lite", f"Streaming LLM error: {e}")

        if buf.strip():
            sentence_q.put(buf.strip())

        sentence_q.put(None)
        synth_thread.join(timeout=_SYNTH_JOIN_TIMEOUT)

        # Audio is about to start — only NOW flag speaking, so push-to-talk
        # interrupts playback rather than the LLM computation. The callback
        # also refreshes the face state.
        self._set_speaking(True)

        play_q.put(None)
        while True:
            path = play_q.get()
            if path is None:
                break
            self._play_or_discard(path)

        return "".join(full_response).strip()

    def speak_text(self, text: str) -> None:
        """Speak a complete string sentence-by-sentence.

        Used for the direct-answer path (where the text wasn't token-streamed).
        """
        sentences = [s.strip() for s in SENTENCE_END_RE.split(text) if s.strip()]
        if not sentences:
            return

        self._set_speaking(True)

        for sentence in sentences:
            if self._is_interrupted():
                break
            try:
                path = self._tts.synthesize_to_file(sentence)
            except Exception as e:
                self._obs("lite", f"TTS synthesis error: {e}")
                continue
            self._play_or_discard(path)

    # ── Internals ─────────────────────────────────────────────────────

    def _play_or_discard(self, path: str) -> None:
        """Play a synthesized WAV unless the user interrupted; clean up either way."""
        if not self._is_interrupted():
            self._tts.play_file(path)  # deletes the file after playback
        else:
            try:
                os.remove(path)
            except OSError:
                pass
