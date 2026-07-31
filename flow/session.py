"""The state machine: capture -> partials -> held draft -> voice corrections -> send.

UI-agnostic on purpose. `Session.tick()` is a pump the caller drives — a `while` loop
in the headless harness today, `tkinter.after()` once the pill exists — and
`Session.events()` drains what happened. No UI framework is imported here.

Decode runs on a worker thread. That is the fix for the defect stage 3 exposed: with a
synchronous decode, wall time became `audio + sum(decode)` and partial latency drifted
further behind speech the longer someone talked.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import NamedTuple

import numpy as np

from . import MAX_UTTERANCE_SEC, SAMPLE_RATE
from .asr import Transcriber, WhisperTranscriber
from .audio import BLOCK, Mic, SpeechGate
from .edits import apply_local, plan
from .refine import refine

#: Minimum audio growth before asking for a fresh partial. Paired with the
#: worker-idle check below, this is what bounds partial latency.
PARTIAL_MIN_GROWTH_SEC = 0.7

#: R8: drop the 141 MB model after a long quiet spell. The mic stays open — it is
#: cheap, and keeping it means speech still wakes the session with no keypress. This
#: is a deliberate narrowing of what docs/analysis.md §4 proposed (which released the
#: mic too): releasing it would make the app unable to hear its own wake-up.
IDLE_UNLOAD_SEC = 300.0

#: How often to check that the input device is still alive.
MIC_CHECK_SEC = 5.0


class State(str, Enum):
    IDLE = "idle"  # not capturing
    LISTENING = "listening"  # speech in progress
    DRAFT = "draft"  # text held, awaiting refine / continue / send
    REFINING = "refining"  # a CLI rewrite is in flight


class Event(NamedTuple):
    kind: str  # partial | draft | state | note | error
    text: str


class DecodeWorker:
    """One thread. Partials are latest-wins; finals are never dropped.

    Replacing the pending partial instead of queueing it is the whole point: if speech
    outruns the decoder, intermediate states are skipped rather than accumulating a
    backlog. Finals go through a FIFO because losing one would lose the user's words.
    """

    def __init__(self, asr: Transcriber) -> None:
        self._asr = asr
        self._cv = threading.Condition()
        self._partial: np.ndarray | None = None
        self._finals: deque[np.ndarray] = deque()
        self._out: deque[tuple[str, str]] = deque()
        #: Recent decode durations as (kind, seconds). Bounded, so this is safe to keep
        #: on in a long session; the soak test reads it to check latency does not drift.
        self.timings: deque[tuple[str, float]] = deque(maxlen=300)
        self._busy = False
        self._alive = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="decode")
        self._thread.start()

    @property
    def busy(self) -> bool:
        with self._cv:
            return self._busy or self._partial is not None or bool(self._finals)

    def submit_partial(self, audio: np.ndarray) -> None:
        with self._cv:
            self._partial = audio  # replaces any pending partial
            self._cv.notify()

    def submit_final(self, audio: np.ndarray) -> None:
        with self._cv:
            self._finals.append(audio)
            self._partial = None  # a final supersedes a pending partial of the same audio
            self._cv.notify()

    def results(self) -> list[tuple[str, str]]:
        with self._cv:
            out = list(self._out)
            self._out.clear()
            return out

    def take_timings(self) -> list[tuple[str, float]]:
        """Return and clear recorded decode durations.

        Draining rather than letting a caller index into `timings`: it is a bounded
        deque, so once it saturates its length stops growing and an index-based
        "everything since last time" silently returns nothing forever. The soak test
        did exactly that and reported latency for the first third of a run as if it
        covered the whole thing.
        """
        with self._cv:
            out = list(self.timings)
            self.timings.clear()
            return out

    def close(self) -> None:
        with self._cv:
            self._alive = False
            self._cv.notify()

    def _run(self) -> None:
        while True:
            with self._cv:
                while self._alive and self._partial is None and not self._finals:
                    self._cv.wait()
                if not self._alive:
                    return
                if self._finals:
                    audio, kind = self._finals.popleft(), "final"
                else:
                    audio, kind = self._partial, "partial"
                    self._partial = None
                self._busy = True
            started = time.perf_counter()
            try:
                text = self._asr.text(audio, final=(kind == "final"))
            except Exception as exc:  # a decode failure must not kill the thread
                text, kind = f"{type(exc).__name__}: {exc}", "error"
            elapsed = time.perf_counter() - started
            with self._cv:
                self._busy = False
                self.timings.append((kind, elapsed))
                self._out.append((kind, text))


@dataclass
class Draft:
    """The held text plus an undo stack.

    Undo is what makes the router's heuristic acceptable: a mis-routed utterance costs
    one undo, not lost words.
    """

    text: str = ""
    _history: list[str] = field(default_factory=list)
    MAX_HISTORY = 30
    #: R8: 30 snapshots of a very long draft is the one place undo can quietly become
    #: megabytes, so the history is bounded by total characters as well as by count.
    MAX_HISTORY_CHARS = 200_000

    def _remember(self) -> None:
        self._history.append(self.text)
        while len(self._history) > self.MAX_HISTORY or (
            len(self._history) > 1
            and sum(len(h) for h in self._history) > self.MAX_HISTORY_CHARS
        ):
            self._history.pop(0)

    def append(self, more: str) -> None:
        more = more.strip()
        if not more:
            return
        self._remember()
        if not self.text or self.text.endswith(("\n", " ")):
            self.text = f"{self.text}{more}"
        else:
            self.text = f"{self.text} {more}"

    def set(self, value: str) -> None:
        self._remember()
        self.text = value

    def undo(self) -> bool:
        if not self._history:
            return False
        self.text = self._history.pop()
        return True

    def clear(self) -> str:
        out = self.text
        self._remember()
        self.text = ""
        return out


class Session:
    def __init__(
        self,
        asr: Transcriber | None = None,
        device: int | None = None,
        refine_cwd: str | None = None,
        mic: Mic | None = None,
    ) -> None:
        # `mic` and `asr` are injectable so the state machine can be tested without a
        # microphone or a 141 MB model — the routing logic is where the subtle bugs live.
        self.asr = asr or WhisperTranscriber()
        self.mic = mic or Mic(device=device)
        self.gate = SpeechGate()
        self.worker = DecodeWorker(self.asr)
        self.draft = Draft()
        self.state = State.IDLE
        self._utter: list[np.ndarray] = []
        self._decoded_sec = 0.0
        self._events: deque[Event] = deque()
        self._refine_cwd = refine_cwd
        self._refine_result: tuple[str | None, str] | None = None
        self._refine_lock = threading.Lock()
        #: Explicit override for the next utterance's routing, set by the UI chips.
        #: The heuristic in edits.py is the default; this is the escape hatch for when
        #: it guesses wrong, per the "heuristic + explicit override" design in §4.
        self.force_next: str | None = None  # "append" | "edit" | None
        self._last_activity = time.perf_counter()
        self._last_mic_check = time.perf_counter()
        self._mic_started = False

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Open the mic and warm the model.

        The model load is *not* awaited here. On a first run it includes a ~141 MB
        download, and doing that inline froze the whole UI on the first click with no
        indication of why. The decode worker loads lazily on its own thread anyway, so
        this only pre-warms; `mic.start()` is what actually has to succeed.
        """
        self.mic.start()
        self._mic_started = True
        self._last_activity = time.perf_counter()
        threading.Thread(target=self._preload, daemon=True, name="preload").start()
        self._set_state(State.IDLE)

    def _preload(self) -> None:
        try:
            self.asr.load()
        except Exception as exc:
            # Surfaced through the normal event stream so the UI can show it; a raise
            # on this thread would vanish into stderr.
            self._emit("error", f"model failed to load: {exc}")

    def pause(self) -> None:
        """Stop capturing without tearing the session down.

        Goes through here rather than calling `mic.stop()` directly so the health check
        can tell "deliberately paused" from "the device disappeared" — otherwise it
        would helpfully reopen a mic the user just switched off.
        """
        self.mic.stop()
        self._mic_started = False
        self._set_state(State.IDLE)

    def close(self) -> None:
        self.mic.stop()
        self._mic_started = False
        self.worker.close()

    def __enter__(self) -> "Session":
        self.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    # -- output ------------------------------------------------------------

    def events(self) -> list[Event]:
        out = list(self._events)
        self._events.clear()
        return out

    def _emit(self, kind: str, text: str = "") -> None:
        self._events.append(Event(kind, text))

    def _set_state(self, state: State) -> None:
        if state != self.state:
            self.state = state
            self._emit("state", state.value)

    @property
    def level_db(self) -> float:
        """Live input level, for the waveform display (R13)."""
        return self.mic.level_db

    # -- the pump ----------------------------------------------------------

    def tick(self) -> None:
        self._pump_audio()
        self._pump_decodes()
        self._pump_drops()
        self._pump_refine()
        self._pump_health()

    def _pump_drops(self) -> None:
        """Surface what the filter rejected (P2).

        Emitted as its own event kind rather than folded into `note`, because a drop is
        the one event a UI may want to make *recoverable* rather than merely readable —
        the text is still in the record. `getattr` because the Transcriber protocol is
        deliberately one method wide, and fakes in the tests do not carry a drop log.
        """
        take = getattr(self.asr, "take_drops", None)
        if take is None:
            return
        for drop in take():
            self._emit("drop", drop.describe())

    def _pump_health(self) -> None:
        """Long-session upkeep (R8): device liveness and idle model unload."""
        now = time.perf_counter()

        if now - self._last_mic_check >= MIC_CHECK_SEC:
            self._last_mic_check = now
            if self._mic_started and not self.mic.active:
                self._emit("note", "input device went away — restarting capture")
                try:
                    self.mic.restart()
                except Exception as exc:
                    self._emit("error", f"could not reopen the mic: {exc}")

        idle = now - self._last_activity
        if (
            idle >= IDLE_UNLOAD_SEC
            and not self.draft.text
            and not self.gate.speaking
            and not self.worker.busy
            and getattr(self.asr, "loaded", False)
        ):
            self.asr.unload()
            self._emit("note", f"idle {idle / 60:.0f} min — model unloaded")

    def _utter_sec(self) -> float:
        return len(self._utter) * BLOCK / SAMPLE_RATE

    def _pump_audio(self) -> None:
        for block in self.mic.drain():
            _started, stopped = self.gate.push(block)
            if self.gate.speaking:
                self._utter.append(block)
                self._last_activity = time.perf_counter()
                if self.state is not State.REFINING:
                    self._set_state(State.LISTENING)
                # Risk 7: never let one utterance cross Whisper's 30 s mel window,
                # past which decode cost stops being flat.
                if self._utter_sec() >= MAX_UTTERANCE_SEC:
                    self._finalise()
            elif stopped:
                self._finalise()

        # Ask for a partial only when the worker is free. Combined with latest-wins,
        # this is what stops partial latency from drifting behind live speech.
        if (
            self.gate.speaking
            and self._utter
            and not self.worker.busy
            and self._utter_sec() - self._decoded_sec >= PARTIAL_MIN_GROWTH_SEC
        ):
            self._decoded_sec = self._utter_sec()
            self.worker.submit_partial(np.concatenate(self._utter))

    def _finalise(self) -> None:
        if not self._utter:
            return
        self.worker.submit_final(np.concatenate(self._utter))
        self._utter = []
        self._decoded_sec = 0.0

    def _pump_decodes(self) -> None:
        for kind, text in self.worker.results():
            if kind == "error":
                self._emit("error", text)
            elif kind == "partial":
                # Only non-empty: a partial that clean.py filtered to nothing would
                # otherwise pop an empty bubble open on screen.
                if text:
                    self._emit("partial", text)
            elif text:
                self._route(text)
            else:
                # The utterance decoded to nothing — silence, noise, or a hallucination
                # that clean.py rejected. Without this the state machine stays on
                # LISTENING and the pill sits there green with nothing happening.
                self._after_draft_change()

    # -- routing -----------------------------------------------------------

    def _route(self, utterance: str) -> None:
        """Decide what a completed utterance means, given whether a draft is held."""
        if not self.draft.text:
            self.draft.append(utterance)
            self._after_draft_change()
            return

        forced, self.force_next = self.force_next, None
        if forced == "append":
            self.draft.append(utterance)
            self._after_draft_change()
            return

        p = plan(utterance, self.draft.text)
        if forced == "edit" and p.kind == "append":
            # The user explicitly said "this is an instruction", so honour that over
            # the heuristic and let the CLI interpret whatever they asked for.
            p = type(p)("semantic", payload=utterance)

        if p.kind == "append":
            self.draft.append(utterance)
        elif p.kind == "undo":
            if not self.draft.undo():
                self._emit("note", "nothing to undo")
        elif p.kind == "local":
            new, applied = apply_local(self.draft.text, p)
            if applied:
                self.draft.set(new)
                self._emit("note", f"local: {p.describe()}")
            else:
                # Asked for something we could not do locally — escalate rather than
                # silently no-op, which would read as the app ignoring the user.
                self._start_refine(utterance)
                return
        else:
            self._start_refine(p.payload)
            return

        self._after_draft_change()

    def _after_draft_change(self) -> None:
        self._set_state(State.DRAFT if self.draft.text else State.IDLE)
        self._emit("draft", self.draft.text)

    # -- semantic refine (off-thread: ~7 s measured) ------------------------

    def _start_refine(self, instruction: str) -> None:
        self._set_state(State.REFINING)
        self._emit("note", f"refining via CLI: {instruction!r}")
        before = self.draft.text

        def work() -> None:
            result = refine(before, instruction, cwd=self._refine_cwd)
            with self._refine_lock:
                self._refine_result = result

        threading.Thread(target=work, daemon=True, name="refine").start()

    def _pump_refine(self) -> None:
        with self._refine_lock:
            result, self._refine_result = self._refine_result, None
        if result is None:
            return
        revised, note = result
        if revised is None:
            self._emit("error", f"refine failed ({note}) — draft unchanged")
        else:
            self.draft.set(revised)
            self._emit("note", f"refined via {note}")
        self._after_draft_change()

    # -- actions -----------------------------------------------------------

    def send(self) -> str:
        """Hand off the draft and reset. Injection is the caller's job (stage 8)."""
        text = self.draft.clear()
        self.gate.reset()
        self._utter = []
        self._set_state(State.IDLE)
        self._emit("draft", "")
        return text

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """Pump until no decode or refine is outstanding. For tests and harnesses."""
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            self.tick()
            if (
                not self.worker.busy
                and self.state is not State.REFINING
                and not self._utter
            ):
                return True
            time.sleep(0.02)
        return False
