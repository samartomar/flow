"""Speech-to-text.

Kept behind a deliberately tiny surface (`Transcriber.text`) so the engine can be
swapped for whisper.cpp later without touching the session logic — that swap is the
documented escape hatch if the ~384 MB faster-whisper footprint ever matters more
than build time.
"""

from __future__ import annotations

import threading
from typing import Protocol

import numpy as np

from .clean import is_invented, normalise


class Transcriber(Protocol):
    def text(self, audio: np.ndarray, *, final: bool = False) -> str:
        """Transcribe mono float32 audio at SAMPLE_RATE. Returns plain text."""
        ...


class WhisperTranscriber:
    """faster-whisper on CPU, int8.

    Loading is lazy so that importing this module (and therefore starting the UI)
    does not pay the ~1 s model load until speech actually arrives.
    """

    def __init__(self, model: str = "base.en", compute_type: str = "int8") -> None:
        self._name = model
        self._compute_type = compute_type
        self._model = None
        # Two threads can race to load: the background preload started by
        # Session.start() and the decode worker calling text() lazily. Without this
        # lock both build a 141 MB model and one is thrown away.
        self._lock = threading.Lock()

    def load(self) -> None:
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(
                    self._name, device="cpu", compute_type=self._compute_type
                )

    def unload(self) -> None:
        """Release the model after a long idle period (R8)."""
        with self._lock:
            self._model = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def text(self, audio: np.ndarray, *, final: bool = False) -> str:
        if audio.size == 0:
            return ""
        self.load()
        segments, _ = self._model.transcribe(
            audio,
            language="en",  # R2: never spend compute on language detection
            beam_size=2 if final else 1,  # greedy for partials; they get replaced anyway
            vad_filter=False,  # SpeechGate already decided this is speech
            # Critical for R8: with context carry-over, a long session can fall into
            # repetition loops where the model echoes earlier text forever.
            condition_on_previous_text=False,
        )
        kept = []
        for s in segments:
            # Drop segments the model invented rather than heard. See flow/clean.py for
            # the measurements behind the thresholds.
            if is_invented(
                s.text,
                getattr(s, "no_speech_prob", None),
                getattr(s, "avg_logprob", None),
            ):
                continue
            kept.append(s.text.strip())
        return normalise(" ".join(kept))
