"""First-run calibration: measure this room and this voice instead of guessing (P8).

Three constants in this codebase were tuned on one machine and one speaker, and each
has since been caught being wrong for somebody else:

  the gate's starting noise floor (−55 dB), which a −96.7 dB room could not reach;
  the gate's margin (10 dB), which decides whether a soft speaker opens it at all;
  `clean.LOW_CONFIDENCE` (−0.8), which means different things to different accents —
  Spanish-accented English medians −0.62 against −0.27…−0.32 for other groups.

Sixty seconds of someone reading a paragraph fixes all three, because that recording
contains both halves of every comparison: the silence between their sentences is their
room, the sentences are their voice, and the decode of a *known* text is the only
honest way to see what this speaker's `avg_logprob` looks like when nothing is wrong.

Nothing here is sent anywhere (R9); the result is a JSON file the user owns.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from . import SAMPLE_RATE
from .audio import BLOCK, FLOOR_MAX_DB, FLOOR_MIN_DB, Mic, SpeechGate, rms_db

#: The passage. Chosen to be ordinary developer speech rather than a pangram: it has to
#: elicit the delivery the gate and the model will actually meet. About 45–60 s read at
#: a natural pace.
PASSAGE = (
    "The deploy failed again this morning, about ten minutes after the migration "
    "started. I checked the logs and the connection pool was exhausted, so every "
    "request after the first hundred timed out. The fix is probably to raise the pool "
    "size, but I would like to understand why it only happens in staging and never in "
    "production before we change anything. I have asked Priya to look at the traffic "
    "shape, and Samir is going to check whether the migration itself is holding "
    "connections open longer than it needs to."
)

#: How long to listen. Shorter than the passage on purpose — someone who stops early
#: still produces a usable measurement, and someone who reads on is simply cut off.
LISTEN_SEC = 60.0

#: A calibration with almost no speech in it is not a calibration. Both halves have to
#: be present or the numbers describe nothing.
MIN_SPEECH_SEC = 8.0
MIN_QUIET_SEC = 2.0


@dataclass
class Calibration:
    floor_db: float
    speech_db: float
    confidence: float | None
    speech_sec: float
    quiet_sec: float
    text: str = ""

    @property
    def usable(self) -> bool:
        return (
            self.speech_sec >= MIN_SPEECH_SEC
            and self.quiet_sec >= MIN_QUIET_SEC
            and self.speech_db > self.floor_db
        )

    def describe(self) -> str:
        conf = "?" if self.confidence is None else f"{self.confidence:.2f}"
        return (
            f"room {self.floor_db:.1f} dB, voice {self.speech_db:.1f} dB "
            f"(gap {self.speech_db - self.floor_db:.1f} dB), confidence {conf}, "
            f"{self.speech_sec:.0f}s speech / {self.quiet_sec:.0f}s quiet"
        )


def _split(levels: list[float]) -> tuple[float, float, float]:
    """Separate the room from the voice, and return (floor, speech, boundary).

    By the widest gap in the sorted levels, not by a fixed percentile. A percentile
    assumes how much of the minute is silence, and that assumption fails on the person
    it matters most for: a fluent reader pauses for maybe a sixth of the time, so "the
    quietest fifth is the room" lands inside their voice and calibrates the floor to
    −45 dB. The gap makes no assumption about the ratio — it finds the boundary between
    two modes wherever it happens to be.

    The search is confined to the middle of the distribution so that one door slam or
    one clipped plosive, which sits alone at an extreme, cannot be mistaken for the
    boundary between speech and silence.
    """
    ordered = sorted(levels)
    n = len(ordered)
    if n < 4:
        return ordered[0], ordered[-1], (ordered[0] + ordered[-1]) / 2.0
    lo, hi = max(1, n // 10), min(n - 1, n - n // 10)
    cut = max(range(lo, hi), key=lambda i: ordered[i] - ordered[i - 1])
    quiet, loud = ordered[:cut], ordered[cut:]
    floor = quiet[len(quiet) // 2]
    speech = loud[len(loud) // 2]
    return floor, speech, (ordered[cut - 1] + ordered[cut]) / 2.0


def measure(
    mic: Mic,
    asr=None,
    seconds: float = LISTEN_SEC,
    on_level=None,
) -> Calibration:
    """Listen for `seconds` and return what this room and this voice measure at.

    The split between room and voice is made by loudness percentile rather than by the
    gate, deliberately: the gate is the thing being calibrated, so using it to decide
    what counts as speech would make the measurement agree with whatever the gate
    already believed.
    """
    levels: list[float] = []
    blocks: list[np.ndarray] = []

    def observe(block: np.ndarray, elapsed: float | None = None) -> None:
        # Digital silence is not a room, and the gate already refuses to learn its
        # floor from it. Calibration has to refuse too, or it writes -180 dB into the
        # profile and `apply` pushes that straight past the very guard the gate has —
        # producing a floor no real input can sit under and a gate that opens on
        # anything. Found by calibrating on synthesised speech, which pads with exact
        # zeros; a muted or noise-gated microphone does the same thing.
        if not block.any():
            return
        blocks.append(block)
        levels.append(rms_db(block))
        if on_level is not None and elapsed is not None:
            on_level(levels[-1], elapsed)

    end = time.monotonic() + seconds
    while time.monotonic() < end:
        for block in mic.drain():
            observe(block, time.monotonic() - (end - seconds))
        time.sleep(0.02)
    for block in mic.drain():
        observe(block)

    if not levels:
        return Calibration(-55.0, -55.0, None, 0.0, 0.0)

    floor, speech, mid = _split(levels)
    # Bounded by the same limits the gate enforces on its own adaptation, so a stored
    # profile can never describe a gate the gate itself would refuse to become.
    floor = max(FLOOR_MIN_DB, min(FLOOR_MAX_DB, floor))
    per_block = BLOCK / SAMPLE_RATE
    speech_sec = sum(1 for x in levels if x >= mid) * per_block
    quiet_sec = sum(1 for x in levels if x < mid) * per_block

    confidence, text = None, ""
    if asr is not None and blocks and speech_sec >= MIN_SPEECH_SEC:
        loud = [b for b, lv in zip(blocks, levels) if lv >= mid]
        if loud:
            # Only the speech, and only the tail of it: Whisper pads to one 30 s mel
            # window, so handing it a minute costs time without adding evidence.
            audio = np.concatenate(loud)[-30 * SAMPLE_RATE:]
            text = asr.text(audio, final=True)
            take = getattr(asr, "take_confidence", None)
            confidence = take() if callable(take) else None

    return Calibration(floor, speech, confidence, speech_sec, quiet_sec, text)


def apply(profile, gate: SpeechGate) -> bool:
    """Push a stored profile into a live gate. False when there is nothing to apply."""
    if not profile.calibrated:
        return False
    gate.floor_db = profile.floor_db
    gate.margin_db = profile.margin_db()
    return True


def _meter(level_db: float, width: int = 24) -> str:
    filled = int(width * max(0.0, min(1.0, (level_db + 70.0) / 60.0)))
    return "#" * filled + "." * (width - filled)


def run(mic: Mic, profile, asr=None, seconds: float = LISTEN_SEC, log=print) -> bool:
    """Calibrate, store, and report. Returns False if the reading was not usable."""
    log("Read the passage below at your normal pace. Listening for "
        f"{seconds:.0f} seconds.\n")
    log(PASSAGE + "\n")

    # A minute of silence from the program while the user reads aloud is
    # indistinguishable from a program that has hung, and the first thing anyone does
    # about that is stop it — which is the one thing that ruins the measurement.
    last = [0.0]

    def tick(level_db: float, elapsed: float) -> None:
        if elapsed - last[0] < 2.0:
            return
        last[0] = elapsed
        log(f"  {elapsed:4.0f}s / {seconds:.0f}s  [{_meter(level_db)}] "
            f"{level_db:6.1f} dB")

    result = measure(mic, asr=asr, seconds=seconds, on_level=tick)
    log("\nlistening done; decoding what you read...")
    log(result.describe())
    if result.text:
        log(f"heard: {result.text[:110]}")
    if not result.usable:
        log("not usable — needs at least "
            f"{MIN_SPEECH_SEC:.0f}s of speech and {MIN_QUIET_SEC:.0f}s of quiet")
        return False
    profile.record_calibration(result.floor_db, result.speech_db, result.confidence)
    profile.save()
    log(f"gate margin set to {profile.margin_db():.1f} dB; saved to {profile.path}")
    return True
