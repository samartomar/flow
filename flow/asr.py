"""Speech-to-text.

Kept behind a deliberately tiny surface (`Transcriber.text`) so the engine can be
swapped for whisper.cpp later without touching the session logic — that swap is the
documented escape hatch if the ~384 MB faster-whisper footprint ever matters more
than build time.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import NamedTuple, Protocol

import numpy as np

from .clean import invented_reason, normalise
from .lexicon import Lexicon

#: How many recent drops to keep. Bounded because R8 says a long session must cost what
#: a short one costs; 100 is enough for the UI to explain what just vanished.
DROP_HISTORY = 100

#: The two tiers, split because one model cannot serve both paths on this CPU.
#:
#: `small.en` is 16–23% relative better than `base.en` on four of five accent groups
#: (largest on Japanese, the worst-served: 0.306 → 0.234) — but the R4 gate measured it
#: at 2.66–3.78 s per partial *at every prefix length from 1 s up*, against a 1.5 s
#: budget, because Whisper pads every input to one 30 s mel window and there is no
#: short-utterance regime where the tier is fast. It cannot drive partials here.
#:
#: Finals are not bound that way — the draft is held on screen while they run (R5) — so
#: the accuracy goes where the text that actually gets pasted is decided: 3.65 s median
#: (4.87 s worst) for a full 10–20 s utterance.
#:
#: The cost is a visible partial→final rewrite, since the tiers disagree on roughly one
#: word in five of accented speech. That is the trade the numbers force, and it is the
#: same one Wispr makes.
PARTIAL_MODEL = "base.en"
FINAL_MODEL = "small.en"


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


#: P2, defect 2: faster-whisper drops a segment *inside the library*, before Flow ever
#: sees it, when `no_speech_prob > 0.6` and `avg_logprob < -1.0` — and accented speech
#: scores worse on exactly those two signals. Measured on 280 short clips: 5 of 9
#: silent deletions happened there, unlogged and unattributable. `None` turns that
#: second, invisible filter off. Flow then has exactly one filter — its own, in
#: clean.py, which records what it drops and why.
#:
#: The cost is real and bounded: `no_speech_threshold` also suppresses the temperature
#: fallback on probable silence, so a *final* decoded from noise may now retry up to
#: its three capped steps. The speech gate means that is a rare path.
NO_SPEECH_THRESHOLD = None

#: `None` means: never retry a decode merely because the model was unsure. It still
#: retries when the output is *degenerate* — `compression_ratio_threshold` stays at the
#: library default and is what catches repetition loops, which is the case where a
#: hotter sample genuinely helps.
#:
#: Measured, and this is the whole argument: on the 300-clip accent slice the retry
#: buys nothing — base.en scores 0.233 / 0.283 / 0.173 / 0.189 / 0.276 across the five
#: groups without it versus 0.231 / 0.281 / 0.178 / 0.187 / 0.276 with it, differences
#: smaller than the run-to-run noise of the sampling itself. It costs, though: leaving
#: it at −1.0 turned one 5 s noise clip from 0.84 s into 3.66 s, because low confidence
#: on near-silence is exactly what a retry cannot fix.
LOG_PROB_THRESHOLD = None


def decode_options(final: bool, hotwords: str | None = None) -> dict:
    """The decode parameters, in one place.

    Exported because the benchmarks in scripts/ decode with them too; a bench that
    quietly drifts from the app measures a build nobody runs.
    """
    if hotwords:
        return {**decode_options(final), "hotwords": hotwords}
    return {
        "language": "en",  # R2: never spend compute on language detection
        "beam_size": FINAL_BEAM if final else PARTIAL_BEAM,
        "temperature": FINAL_TEMPERATURES if final else PARTIAL_TEMPERATURES,
        "vad_filter": False,  # SpeechGate already decided this is speech
        # Critical for R8: with context carry-over, a long session can fall into
        # repetition loops where the model echoes earlier text forever.
        "condition_on_previous_text": False,
        "no_speech_threshold": NO_SPEECH_THRESHOLD,
        "log_prob_threshold": LOG_PROB_THRESHOLD,
    }


class Drop(NamedTuple):
    """One segment the filter rejected, with the evidence it used.

    P2 is "never loses words silently": a rejection is allowed, an *unexplained* one is
    not. Keeping the text is what makes a later rescue possible — the user cannot
    recover words they were never shown, but they can recover these.
    """

    text: str
    reason: str
    no_speech_prob: float | None
    avg_logprob: float | None
    final: bool

    def describe(self) -> str:
        ns = "?" if self.no_speech_prob is None else f"{self.no_speech_prob:.2f}"
        lp = "?" if self.avg_logprob is None else f"{self.avg_logprob:.2f}"
        kind = "final" if self.final else "partial"
        return f"dropped {self.text.strip()!r} ({self.reason}, ns={ns} lp={lp}, {kind})"


class Transcriber(Protocol):
    def text(self, audio: np.ndarray, *, final: bool = False) -> str:
        """Transcribe mono float32 audio at SAMPLE_RATE. Returns plain text."""
        ...


class WhisperTranscriber:
    """faster-whisper on CPU, int8, in two tiers.

    A fast model for partials and a stronger one for finals — see PARTIAL_MODEL and
    FINAL_MODEL for the measurements that forced the split. Pin both to one name
    (`WhisperTranscriber("base.en", "base.en")`) to benchmark a single tier.

    Loading is lazy *per tier*, so importing this module (and therefore starting the
    UI) pays nothing, and a session that only ever shows partials never loads the
    finals model at all.
    """

    def __init__(
        self,
        partial_model: str = PARTIAL_MODEL,
        final_model: str = FINAL_MODEL,
        compute_type: str = "int8",
        lexicon: Lexicon | None = None,
    ) -> None:
        self._names = {False: partial_model, True: final_model}
        #: The user's own words, biasing both tiers (P4). Re-read when the file
        #: changes, so a name added mid-session lands on the next utterance.
        self.lexicon = lexicon if lexicon is not None else Lexicon()
        self._compute_type = compute_type
        self._models: dict[bool, object | None] = {False: None, True: None}
        # Guards the model dict and the drop log — both touched from the decode
        # thread and the UI thread. Never held across a model build.
        self._lock = threading.Lock()
        # Two threads can race to load: the background preload started by
        # Session.start() and the decode worker calling text() lazily. Without a lock
        # both build a model and one is thrown away, so each tier gets its own.
        self._locks = {False: threading.Lock(), True: threading.Lock()}
        #: Recent rejections, newest last. Written on the decode thread and drained on
        #: the UI thread, so it is a deque with a maxlen rather than a growing list.
        self._drops: deque[Drop] = deque(maxlen=DROP_HISTORY)

    def take_drops(self) -> list[Drop]:
        """Return and clear the recorded rejections.

        Draining rather than indexing, for the reason PROGRESS.md records about the
        soak test: a bounded deque stops growing once saturated, so "everything since
        last time" computed from a length silently returns nothing forever.
        """
        with self._lock:
            out = list(self._drops)
            self._drops.clear()
            return out

    def load(self, final: bool | None = None) -> None:
        """Load one tier, or both when called with no argument.

        `Session.start()` preloads both on a background thread. The order matters:
        partials are what the user waits on, and the finals model is the bigger
        download, so the fast tier is ready first even on a cold first run.
        """
        tiers = (False, True) if final is None else (final,)
        for tier in tiers:
            # One lock *per tier*, held across the build. Per tier, so that preloading
            # the finals model does not block a partial that only needs the fast one;
            # held across the build, because without that the preload thread and the
            # decode worker each construct a model and one is thrown away.
            with self._locks[tier]:
                if self._models[tier] is not None:
                    continue
                from faster_whisper import WhisperModel

                model = WhisperModel(
                    self._names[tier], device="cpu", compute_type=self._compute_type
                )
                with self._lock:
                    self._models[tier] = model

    def unload(self) -> None:
        """Release both models after a long idle period (R8)."""
        with self._lock:
            self._models = {False: None, True: None}

    @property
    def loaded(self) -> bool:
        """True once *any* tier is resident — this is what the idle-unload check reads,
        and it must fire while either model is still holding memory."""
        with self._lock:
            return any(m is not None for m in self._models.values())

    @property
    def names(self) -> tuple[str, str]:
        """(partial, final) model names, for startup diagnostics."""
        return self._names[False], self._names[True]

    def text(self, audio: np.ndarray, *, final: bool = False) -> str:
        if audio.size == 0:
            return ""
        # Only the tier being used: a partial must never wait on the finals model.
        self.load(final)
        with self._lock:
            model = self._models[final]
        segments, _ = model.transcribe(
            audio, **decode_options(final, self.lexicon.hotwords())
        )
        kept = []
        for s in segments:
            # Drop segments the model invented rather than heard, and record every one
            # with the evidence used (P2). See flow/clean.py for the measurements
            # behind the thresholds.
            ns = getattr(s, "no_speech_prob", None)
            lp = getattr(s, "avg_logprob", None)
            reason = invented_reason(s.text, ns, lp)
            if reason is not None:
                with self._lock:
                    self._drops.append(Drop(s.text, reason, ns, lp, final))
                continue
            kept.append(s.text.strip())
        return normalise(" ".join(kept))
