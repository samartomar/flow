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


#: Partials pay for no retries at all. faster-whisper re-decodes a segment at rising
#: temperatures whenever `avg_logprob` falls under its −1.0 threshold, and accented
#: speech fails that check constantly: a 1 s Japanese-accented prefix scores −1.15 and
#: costs **2.40 s median (1.48–3.69 s, nondeterministic) against a 1.5 s R4 budget**,
#: versus 0.75 s greedy. A partial is provisional — the final replaces it within
#: seconds — so buying quality with latency is the wrong trade on this path.
PARTIAL_TEMPERATURES = (0.0,)

#: Finals are what gets pasted, so they can afford a bounded retry; the draft is held
#: on screen while they run (R5). Bounded, not open-ended: the library's full six-step
#: ladder costs **7.6 s and 8.5 s on 5 s of room noise** (measured, `.bench/room.wav`
#: and `fan55_quiet.wav`), which the three-step cap cuts to 5.3 s and 6.2 s.
FINAL_TEMPERATURES = (0.0, 0.2, 0.4)

#: Beam width. Partials are greedy — they get replaced. Finals use the library default
#: of 5 rather than the 2 this build shipped with: measured at +0.25 s median on a full
#: utterance for base.en (1.12 → 1.37 s), off the latency path entirely.
PARTIAL_BEAM = 1
FINAL_BEAM = 5


def decode_options(final: bool) -> dict:
    """The decode parameters, in one place.

    Exported because the benchmarks in scripts/ decode with them too; a bench that
    quietly drifts from the app measures a build nobody runs.
    """
    return {
        "language": "en",  # R2: never spend compute on language detection
        "beam_size": FINAL_BEAM if final else PARTIAL_BEAM,
        "temperature": FINAL_TEMPERATURES if final else PARTIAL_TEMPERATURES,
        "vad_filter": False,  # SpeechGate already decided this is speech
        # Critical for R8: with context carry-over, a long session can fall into
        # repetition loops where the model echoes earlier text forever.
        "condition_on_previous_text": False,
    }


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
        segments, _ = self._model.transcribe(audio, **decode_options(final))
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
