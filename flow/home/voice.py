"""Flow Home's listeners: tuning and the accuracy check on the Voice page, and the first
run's microphone test.

Each is a person talking for a while, and each borrows the microphone from the pill
for exactly that while (`Session.lend_mic`): capture stops, the pill refuses to arm and
says why, and the task opens a stream of its own. Whatever happens — done, failed,
cancelled, an exception — the microphone goes back (`return_mic`), because a pill that
stays refused after a crash in a settings page is a broken product.

Each task runs on a thread of its own and keeps its state in plain fields the page reads
every quarter second; decoding goes through the session's own transcriber, so the check
measures the pipeline Flow pastes from — the models in use and the dictionary included.
Anything that changes the session — the calibration saved into the profile and applied
to the live gate, the loan and its return — is posted to the session's thread.
"""

from __future__ import annotations

import threading
import time

import numpy as np

from .. import SAMPLE_RATE, accuracy, calibrate
from ..audio import BLOCK, Mic, SpeechGate, rms_db

#: The longest one accuracy sentence may take to read. The gate ends a take on its own
#: once the speaker stops; this is the ceiling for somebody who never starts.
CHECK_MAX_SEC = 20.0

#: How long the first run's microphone test listens before it stops on its own: time to
#: say a sentence into two microphones, and short enough that a page left open does not
#: keep the pill's microphone.
LISTEN_MAX_SEC = 45.0

#: What counts as a voice on the microphone test: blocks this far above the room, the
#: room being the quietest tenth of what was heard, for at least `HEARD_SEC`. The Voice
#: page's `calibrate.heard` split is not used here because it always splits — a silent
#: room still has a louder half — and "Hearing you" said over silence would be the one
#: lie this step exists to prevent. Fifteen decibels is under half the gap a voice at a
#: normal distance made over this machine's room (`calibrate`'s readings, 25-40 dB).
HEARD_OVER_ROOM_DB = 15.0
HEARD_SEC = 0.6


def voice_seconds(levels: list[float]) -> float:
    """Seconds of blocks loud enough over the room to be somebody talking."""
    if len(levels) < 8:
        return 0.0
    room = sorted(levels)[len(levels) // 10]
    loud = sum(1 for level in levels if level >= room + HEARD_OVER_ROOM_DB)
    return loud * BLOCK / SAMPLE_RATE

def worth_offering(sentence: str, missed: list[str]) -> list[str]:
    """The missed words worth offering for the dictionary: names and terms, which in
    these sentences are the words capitalised mid-sentence.

    Never the opening word and never a lower-case one, however badly it was heard.
    Biasing common words is the measured harm in `flow/lexicon.py`; a name or a product
    the decoder missed is the measured help.
    """
    firsts = {sentence.split()[0].strip(".,!?;:").lower()} if sentence.split() else set()
    out = []
    for word in missed:
        if word and word[0].isupper() and word.lower() not in firsts and word not in out:
            out.append(word)
    return out


class _Task:
    """What both tasks share: the loan, the thread, and a state the page can read."""

    WHY = "Flow Home is using the microphone"

    def __init__(self, home) -> None:
        self.home = home
        self.state = "idle"
        self.error = ""
        self.level_db = -90.0
        self._stop = threading.Event()
        self._lent = False
        self._lock = threading.Lock()

    @property
    def busy(self) -> bool:
        return self.state not in ("idle", "done", "failed")

    def _mic(self) -> Mic:
        """A stream of the task's own, on the microphone the pill uses."""
        factory = getattr(self.home, "mic_factory", None)
        if factory is not None:
            return factory()
        pill_mic = getattr(self.home.session, "mic", None)
        mic = Mic(device=getattr(pill_mic, "pinned", None))
        mic.want = getattr(pill_mic, "want", None)
        return mic

    def _borrow(self) -> str:
        """Lend the microphone, on the session's thread. "" when it is ours."""
        why = self.home.bridge.call(lambda: self.home.session.lend_mic(self.WHY))
        if not why:
            self._lent = True
        return why

    def _give_back(self) -> None:
        if self._lent:
            self._lent = False
            self.home.session.post(self.home.session.return_mic)

    def _gate(self) -> SpeechGate:
        """A speech gate tuned the way the pill's is, so "you stopped" means the same."""
        gate = SpeechGate()
        profile = self.home.profile
        if profile is not None and profile.calibrated:
            calibrate.apply(profile, gate)
        return gate


class Tune(_Task):
    """Tune Flow to this room and this voice: the `flow --calibrate` minute, in a window."""

    WHY = "Flow is being tuned to your voice"

    def __init__(self, home) -> None:
        super().__init__(home)
        self.seconds = calibrate.LISTEN_SEC
        self.elapsed = 0.0
        self.enough = False
        self.result: dict | None = None
        self._cancel = threading.Event()

    def start(self) -> str:
        """Begin listening. "" when it started, otherwise why not."""
        with self._lock:
            if self.busy:
                return "already listening"
            if self.home.profile is None:
                return "Flow was started with --no-profile, so a tuning has nowhere to be saved"
            why = self._borrow()
            if why:
                return why
            self.state, self.error, self.result = "listening", "", None
            self.elapsed, self.enough, self.level_db = 0.0, False, -90.0
            self._stop.clear()
            self._cancel.clear()
        threading.Thread(target=self._run, daemon=True, name="tune").start()
        return ""

    def finish(self) -> None:
        """"Done reading": measure what was heard. Only once there is enough of it."""
        if self.state == "listening" and self.enough:
            self._stop.set()

    def cancel(self) -> None:
        if self.busy:
            self._cancel.set()
            self._stop.set()

    def _run(self) -> None:
        levels: list[float] = []

        def on_level(level: float, elapsed: float) -> None:
            levels.append(level)
            self.level_db, self.elapsed = level, elapsed
            if len(levels) % 16 == 0:
                self.enough = calibrate.enough(levels)

        def measuring() -> None:
            self.state = "measuring"

        mic = None
        try:
            mic = self._mic()
            mic.start()
            # The session's own transcriber decodes what was read, so the confidence
            # baseline is the one `--calibrate` stores, measured on the models in use.
            # A cancel ends the listening; whatever `measure` still works out is dropped.
            asr = getattr(self.home.session, "asr", None)
            result = calibrate.measure(
                mic, asr=asr, seconds=self.seconds, on_level=on_level,
                stop=self._stop.is_set,
                on_decode=lambda: None if self._cancel.is_set() else measuring(),
            ) if not self._cancel.is_set() else None
            mic.stop()
            mic = None
            if self._cancel.is_set() or result is None:
                self.state = "idle"
                return
            if not result.usable:
                self.state = "failed"
                self.error = (f"not enough to measure - it needs at least "
                              f"{calibrate.MIN_SPEECH_SEC:.0f} seconds of reading and "
                              f"{calibrate.MIN_QUIET_SEC:.0f} of pauses between sentences")
                return
            device = getattr(getattr(self.home.session, "mic", None), "device_name", "") or None
            self.home.bridge.call(lambda: self._save(result, device))
            self.result = _describe(result)
            self.state = "done"
        except Exception as exc:
            self.state = "failed"
            self.error = f"tuning stopped: {exc}"
        finally:
            if mic is not None:
                try:
                    mic.stop()
                except Exception:
                    pass
            self._give_back()

    def _save(self, result, device) -> None:
        """On the session's thread: store the reading and apply it to the live gate."""
        profile = self.home.profile
        profile.record_calibration(result.floor_db, result.speech_db, result.confidence,
                                   device=device)
        profile.save()
        gate = getattr(self.home.session, "gate", None)
        if gate is not None:
            calibrate.apply(profile, gate)

    def public(self) -> dict:
        return {"state": self.state, "error": self.error, "elapsed": round(self.elapsed, 1),
                "seconds": self.seconds, "enough": self.enough,
                "level_db": round(self.level_db, 1), "result": self.result,
                "passage": calibrate.PASSAGE}


def _describe(result) -> dict:
    return {"floor_db": round(result.floor_db, 1), "speech_db": round(result.speech_db, 1),
            "gap_db": round(result.speech_db - result.floor_db, 1),
            "confidence": result.confidence,
            "speech_sec": round(result.speech_sec), "quiet_sec": round(result.quiet_sec)}


class Check(_Task):
    """Five sentences, read and scored: how well Flow hears this voice, and what it missed."""

    WHY = "Flow is checking how well it hears you"

    def __init__(self, home) -> None:
        super().__init__(home)
        self.sentences = accuracy.SENTENCES
        self.index = 0
        self.scores: list[accuracy.Score] = []
        self.note = ""
        self.last: accuracy.Score | None = None

    @property
    def busy(self) -> bool:
        return self.state in ("ready", "recording", "decoding")

    def start(self) -> str:
        with self._lock:
            if self.busy:
                return "the check is already running"
            why = self._borrow()
            if why:
                return why
            self.state, self.error, self.note = "ready", "", ""
            self.index, self.scores, self.last = 0, [], None
        return ""

    def record(self) -> str:
        """Record the current sentence. It ends on its own when the reader stops."""
        with self._lock:
            if self.state != "ready":
                return "start the check first" if self.state in ("idle", "done", "failed") \
                    else "already listening"
            self.state, self.note, self.level_db = "recording", "", -90.0
            self._stop.clear()
        threading.Thread(target=self._take, daemon=True, name="check").start()
        return ""

    def stop(self) -> None:
        """End the take now — the reader finished and the pause has not yet been long
        enough for the gate to say so."""
        if self.state == "recording":
            self._stop.set()

    def cancel(self) -> None:
        self._stop.set()
        with self._lock:
            if self.state in ("ready", "recording", "decoding"):
                self.state = "idle"
        self._give_back()

    def _take(self) -> None:
        sentence = self.sentences[self.index]
        mic = None
        try:
            mic = self._mic()
            gate = self._gate()
            mic.start()
            blocks: list[np.ndarray] = []
            spoke = False
            began = time.monotonic()
            while not self._stop.is_set() and time.monotonic() - began < CHECK_MAX_SEC:
                done = False
                for block in mic.drain():
                    self.level_db = rms_db(block)
                    blocks.append(block)
                    _started, stopped = gate.push(block)
                    spoke = spoke or gate.speaking or _started
                    if spoke and stopped:
                        done = True
                if done:
                    break
                time.sleep(0.02)
            mic.stop()
            mic = None
            if self.state == "idle":  # cancelled while recording
                return
            if not spoke or not blocks:
                self.note = "Flow heard nothing - check the microphone on Settings, then try again"
                self.state = "ready"
                return
            self.state = "decoding"
            heard = self.home.session.asr.text(np.concatenate(blocks), final=True)
            if self.state == "idle":
                return
            score = accuracy.align(sentence, heard)
            self.scores.append(score)
            self.last = score
            self.index += 1
            if self.index >= len(self.sentences):
                self.state = "done"
                self._give_back()
            else:
                self.state = "ready"
        except Exception as exc:
            self.state = "failed"
            self.error = f"the check stopped: {exc}"
            self._give_back()
        finally:
            if mic is not None:
                try:
                    mic.stop()
                except Exception:
                    pass

    def public(self) -> dict:
        def score(s: accuracy.Score) -> dict:
            return {"reference": s.reference, "heard": s.heard, "errors": s.errors,
                    "total": s.total,
                    "steps": [{"op": st.op, "said": st.said, "heard": st.heard}
                              for st in s.steps],
                    "offer": worth_offering(s.reference, s.missed)}

        offers: list[str] = []
        for s in self.scores:
            for word in worth_offering(s.reference, s.missed):
                if word not in offers:
                    offers.append(word)
        return {
            "state": self.state, "error": self.error, "note": self.note,
            "index": self.index, "total": len(self.sentences),
            "sentence": self.sentences[self.index] if self.index < len(self.sentences) else "",
            "level_db": round(self.level_db, 1),
            "scores": [score(s) for s in self.scores],
            "per_hundred": accuracy.per_hundred(self.scores),
            "offers": offers,
        }


class Listen(_Task):
    """The first run's microphone test: is this microphone hearing you?

    Opens the microphone the pill uses, reports its level every block for the page's
    meter, and says `heard` once somebody has talked into it (`voice_seconds`). Nothing
    is decoded and nothing is kept. It stops on its own after `LISTEN_MAX_SEC`, and
    `stop` waits for the stream to close — switching the microphone refreshes PortAudio,
    which is only safe with no stream open anywhere in the process (`audio.refresh_devices`).
    """

    WHY = "Flow is testing your microphone"

    def __init__(self, home) -> None:
        super().__init__(home)
        self.heard = False
        self.peak_db = -90.0
        self.device = ""
        self._thread: threading.Thread | None = None

    @property
    def busy(self) -> bool:
        return self.state == "listening"

    def start(self) -> str:
        """Begin listening. "" when it is listening, otherwise why not."""
        with self._lock:
            if self.busy:
                return ""
            why = self._borrow()
            if why:
                return why
            self.state, self.error, self.device = "listening", "", ""
            self.heard, self.peak_db, self.level_db = False, -90.0, -90.0
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True, name="listen")
            self._thread.start()
        return ""

    def stop(self, wait: float = 2.0) -> None:
        """Stop, and wait for the stream to be closed and the microphone given back."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(wait)

    cancel = stop

    def _run(self) -> None:
        mic = None
        levels: list[float] = []
        try:
            mic = self._mic()
            mic.start()
            self.device = str(getattr(mic, "device_name", "") or "")
            began = time.monotonic()
            while not self._stop.is_set() and time.monotonic() - began < LISTEN_MAX_SEC:
                for block in mic.drain():
                    level = rms_db(block)
                    self.level_db = level
                    self.peak_db = max(self.peak_db, level)
                    levels.append(level)
                if not self.heard and voice_seconds(levels) >= HEARD_SEC:
                    self.heard = True
                time.sleep(0.03)
            self.state = "idle"
        except Exception as exc:
            self.state = "failed"
            self.error = f"the microphone did not open: {exc}"
        finally:
            if mic is not None:
                try:
                    mic.stop()
                except Exception:
                    pass
            self.level_db = -90.0
            self._give_back()

    def public(self) -> dict:
        return {"state": self.state, "error": self.error, "heard": self.heard,
                "level_db": round(self.level_db, 1), "peak_db": round(self.peak_db, 1),
                "device": self.device}


class VoiceTasks:
    """Flow Home's listeners, one of each per Home."""

    def __init__(self, home) -> None:
        self.tune = Tune(home)
        self.check = Check(home)
        self.listen = Listen(home)

    def busy(self) -> str:
        """Which of them is using the microphone, for a refusal to start another."""
        if self.tune.busy:
            return "tuning is still listening"
        if self.check.busy:
            return "the accuracy check is still running"
        if self.listen.busy:
            return "the microphone test is still listening"
        return ""
