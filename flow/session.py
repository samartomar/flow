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
from .edits import (
    added_text,
    apply_local,
    command_bias,
    describe_change,
    plan,
    removed_text,
)

#: P4/P8: the local operations that teach Flow a spelling. Every one of these replaces
#: some words with others, so the diff names both halves of a confusion pair. The rest
#: (delete, insert, break, undo) either take words away or add words that were never a
#: correction of anything, and have nothing to teach.
#: `lower` is deliberately absent. The other four mark a token as a name, an acronym or
#: a different word; lower-casing marks it as ordinary prose, which is the one thing not
#: worth biasing a decoder toward.
LEARNABLE = ("replace", "replace_all", "capitalize", "upper")
from .refine import ask, refine
from .thread import Thread

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

#: How long a Refine/Continue chip stays armed. The chip means "the next thing I say",
#: and after this long the next thing someone says is a different thought.
FORCE_NEXT_TTL_SEC = 30.0

#: P9. How long a settled draft waits in converse mode before it is asked on its own.
#:
#: Converse mode is meant to be a conversation, and product.md states P9's acceptance as
#: "speak, the reply appears, speak again" — no button in that sentence. But R5 says a
#: draft is never auto-sent, and R5 is what makes accented ASR survivable: the correction
#: loop only exists because there is a held draft to correct. The reconciliation is that
#: R5 protects the *irreversible* act. Pasting into a focused window is irreversible and
#: stays manual forever; asking a question is not, and its answer is additive.
#:
#: Four seconds is a measured floor rather than taste. On the one recording where every
#: item was located, the pauses a speaker leaves between separate spoken items run
#: 1.4–3.3 s (median 2.5 s) — and every one of those gaps also contains a spoken item
#: number, so the pure silence is shorter still. Anything under ~3.3 s therefore fires
#: while someone is still mid-thought. This clears the longest pause measured, the
#: countdown sits on the button the entire time so it is never a surprise, and speaking
#: holds it — which is what "still correctable until it fires" has to mean.
AUTO_ASK_SEC = 4.0

#: What `level_db` reports while the microphone is not evidence.
#:
#: Below any real room — a quiet room with a good USB mic measures −96.7 dB — so every
#: meter maps it to silence without needing to know why. A number rather than `None`
#: because a second type for a common state is a second thing every caller can forget.
DEAF_DB = -120.0


class State(str, Enum):
    IDLE = "idle"  # not capturing
    LISTENING = "listening"  # speech in progress
    DRAFT = "draft"  # text held, awaiting refine / continue / send
    REFINING = "refining"  # a CLI rewrite is in flight
    ASKING = "asking"  # P9: a converse-mode question is with the CLI


#: P9. Where a finished draft goes when the user sends it.
#:
#: DICTATE pastes into whatever has focus — the original product. CONVERSE hands it to
#: the agent CLI and renders the reply in Flow, so the same voice loop becomes a
#: conversation instead of a keyboard. Everything before Send is deliberately identical
#: in both: the same gate, the same decode, and the same correction grammar shaping the
#: outgoing words. That is the point — the thing being corrected is a prompt either way.
DICTATE = "dictate"
CONVERSE = "converse"


class Event(NamedTuple):
    kind: str  # partial | draft | state | note | error | reply | mode | drop
    text: str


class Activity(NamedTuple):
    """What Flow is doing right now, when the user is waiting on it.

    One value, read every frame, rather than an event: a wait has no edges to emit — it
    is a condition that holds for a while — and a UI that had to reconstruct "still
    working" from a start event and an end event would show a stale indicator the first
    time one of those events was missed.

    `waiting` marks the indeterminate ones. Those get the animated dots, because the
    honest thing to show for a wait of unknown length is motion, not a progress bar that
    has to invent a denominator.
    """

    label: str
    waiting: bool


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
        #: (audio, hotwords) re-decodes of an utterance the router suspects was a
        #: mis-heard command. Queued like finals, because losing one means paying the
        #: CLI call this exists to avoid.
        self._rescues: deque[tuple[np.ndarray, str]] = deque()
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
            return (
                self._busy
                or self._partial is not None
                or bool(self._finals)
                or bool(self._rescues)
            )

    def submit_partial(self, audio: np.ndarray) -> None:
        with self._cv:
            self._partial = audio  # replaces any pending partial
            self._cv.notify()

    def submit_final(self, audio: np.ndarray) -> None:
        with self._cv:
            self._finals.append(audio)
            self._partial = None  # a final supersedes a pending partial of the same audio
            self._cv.notify()

    def submit_rescue(self, audio: np.ndarray, hotwords: str) -> None:
        """Re-decode this audio biased toward `hotwords`. Result kind: "rescue"."""
        with self._cv:
            self._rescues.append((audio, hotwords))
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
                while (
                    self._alive
                    and self._partial is None
                    and not self._finals
                    and not self._rescues
                ):
                    self._cv.wait()
                if not self._alive:
                    return
                hotwords = ""
                if self._finals:
                    audio, kind = self._finals.popleft(), "final"
                elif self._rescues:
                    (audio, hotwords), kind = self._rescues.popleft(), "rescue"
                else:
                    audio, kind = self._partial, "partial"
                    self._partial = None
                self._busy = True
            started = time.perf_counter()
            try:
                # `hotwords` is passed only when there is a bias to apply, so a
                # Transcriber that predates this (every fake in the tests) still works.
                extra = {"hotwords": hotwords} if hotwords else {}
                text = self._asr.text(audio, final=(kind != "partial"), **extra)
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
    #: Bumped on every change. A CLI rewrite costs ~7 s with the microphone open, so
    #: by the time one comes back the text it was computed from may no longer exist;
    #: this is how the caller can tell without keeping a copy of it.
    revision: int = 0
    _history: list[str] = field(default_factory=list)
    MAX_HISTORY = 30
    #: R8: 30 snapshots of a very long draft is the one place undo can quietly become
    #: megabytes, so the history is bounded by total characters as well as by count.
    MAX_HISTORY_CHARS = 200_000

    def _remember(self) -> None:
        # Every mutation but `undo` snapshots first, so this is also the one place
        # that knows the text is about to change. `undo` bumps the revision itself.
        self._history.append(self.text)
        self.revision += 1
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
        self.revision += 1
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
        speaker: object | None = None,
        profile: object | None = None,
    ) -> None:
        # `mic` and `asr` are injectable so the state machine can be tested without a
        # microphone or a 141 MB model — the routing logic is where the subtle bugs live.
        self.asr = asr or WhisperTranscriber()
        self.mic = mic or Mic(device=device)
        self.gate = SpeechGate()
        self.worker = DecodeWorker(self.asr)
        self.draft = Draft()
        #: P6: what has already been sent. Send appends here instead of erasing, so a
        #: follow-up has something to follow.
        self.thread = Thread()
        #: True when the current draft was opened as a follow-up, which is what lets a
        #: CLI rewrite see the thread tail without every ordinary correction paying for
        #: the extra context.
        self.following_up = False
        self.state = State.IDLE
        self._utter: list[np.ndarray] = []
        #: The audio of the utterance being decoded, kept until routing is done so a
        #: suspected mis-heard command can be re-decoded without asking the user to
        #: say it again.
        self._last_audio: np.ndarray | None = None
        #: What the router was about to send to the CLI when it asked for a rescue.
        self._pending_rescue: str | None = None
        #: The last utterance that was appended as dictation, with its audio, so
        #: "that was a command" can re-read it instead of asking the user to repeat.
        self._last_append: tuple[str, object] | None = None
        #: Set while a post-hoc rescue is in flight, so its re-decode is routed back
        #: here rather than to the escalation path.
        self._post_hoc: str | None = None
        self._decoded_sec = 0.0
        self._events: deque[Event] = deque()
        self._refine_cwd = refine_cwd
        #: (op, draft revision, result) — see `_next_op`.
        self._refine_result: tuple[int, int, tuple[str | None, str]] | None = None
        self._refine_lock = threading.Lock()
        #: Identity for CLI calls, and the id of whichever one is in flight. `state`
        #: cannot carry this: routing keeps running while a call is out and used to
        #: overwrite REFINING with DRAFT, after which everything that read the state
        #: believed no CLI work was happening.
        self._op = 0
        self._refine_op: int | None = None
        self._ask_op: int | None = None
        #: Set once, by `close()`. Every CLI call watches it, so quitting does not
        #: wait out a rewrite nobody will read. Deliberately not touched by `pause()`:
        #: disarming is a way of saying "stop capturing", and an answer to a question
        #: already asked does not depend on still listening.
        self._cancel = threading.Event()
        #: P9: dictate (paste into the focused window) or converse (ask the CLI).
        self.mode = DICTATE
        #: Spoken replies. None means the engine was unavailable or refused.
        self.speaker = speaker
        #: Runtime mute, separate from `speaker` being absent — one is a capability,
        #: the other is a preference, and the UI has to be able to change the second.
        self.muted = False
        #: How many microphone blocks were discarded because Flow was talking. Counted
        #: rather than logged: it is the one number that says whether the half-duplex
        #: guard is doing anything, and a per-block note would drown the bubble.
        self.echo_blocks = 0
        #: P9: let a settled draft go to the CLI on its own after a pause. Converse mode
        #: only — see AUTO_ASK_SEC for why that distinction is the whole argument.
        self.auto_ask = True
        #: When the draft last stopped changing. None means nothing is pending.
        self._settled_at: float | None = None
        #: P8. What Flow has measured and learned about this person, on this machine.
        #: None disables learning entirely — the tests and the benchmarks pass None so
        #: a harness run never writes to the user's real profile.
        self.profile = profile
        self._ask_result: tuple[int, tuple[str | None, str]] | None = None
        self._ask_lock = threading.Lock()
        #: The last answer, kept so the UI can re-render it and so a follow-up has
        #: something to refer to.
        self.reply = ""
        #: Explicit override for the next utterance's routing, set by the UI chips.
        #: The heuristic in edits.py is the default; this is the escape hatch for when
        #: it guesses wrong, per the "heuristic + explicit override" design in §4.
        self._force_next: str | None = None  # "append" | "edit" | None
        self._force_next_at = 0.0
        self._last_activity = time.perf_counter()
        self._last_mic_check = time.perf_counter()
        self._mic_started = False
        #: Blocks the microphone queue threw away, as observed by this session. The
        #: mic's own counter is the source; this one survives a device that brings a
        #: fresh counter with it, and is the number the diagnostics trace wants.
        self.mic_dropped = 0
        self._last_mic_dropped = getattr(self.mic, "dropped", 0)

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
        # Disarming is one of the ways to say "enough" to a reply in progress. Since the
        # microphone is gated while Flow talks, an answer cannot be interrupted by
        # talking over it any more, so every deliberate stop has to actually stop it.
        self.stop_speaking()
        self._set_state(State.IDLE)

    def stop_speaking(self) -> bool:
        """Cut off a reply that is being read aloud. True if there was one."""
        if self.speaker is None or not self.speaker.speaking:
            return False
        self.speaker.stop()
        self._emit("note", "stopped reading the answer")
        return True

    def close(self) -> None:
        self.mic.stop()
        self._mic_started = False
        # Before the worker, because this is the one that reaches outside the process.
        # A refine thread used to run its `subprocess.run` to completion after the app
        # was gone, and killing the CLI Flow launched still left the `node` it launched
        # behind it — a model call billing tokens for an answer with no reader.
        self._cancel.set()
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

    def _next_op(self) -> int:
        """Identity for one CLI call.

        Monotonic, so a result can be matched against the intent that asked for it
        instead of against whatever happens to be current when it lands. What it buys
        on its own is small — one call of each kind is in flight at a time — and it is
        what a cancelled call will be recognised by once one can be cancelled.
        """
        self._op += 1
        return self._op

    def _settle_state(self) -> None:
        """Set the state to what is actually true, with in-flight CLI work winning.

        This used to be an unconditional `DRAFT if draft else IDLE` at the end of every
        route, so speaking during a rewrite dropped REFINING to DRAFT — and everything
        that reads `state` believed it: `send()` stopped refusing, and the converse
        countdown re-armed against a draft the CLI was still holding.

        Asking outranks refining for the same reason `activity` lists it first: it is
        the one the user is waiting on an answer from.
        """
        if self._ask_op is not None:
            self._set_state(State.ASKING)
        elif self._refine_op is not None:
            self._set_state(State.REFINING)
        else:
            self._set_state(State.DRAFT if self.draft.text else State.IDLE)

    @property
    def hearing(self) -> bool:
        """Whether the microphone counts as evidence right now.

        False exactly while a reply is playing — which is when `_pump_audio` drains the
        device and throws every block away. The distinction is not decoration: "busy,
        still listening" and "busy, and deaf" are different promises to the user, and
        only the second one means *stop talking*.
        """
        return not (self.speaker is not None and self.speaker.speaking)

    @property
    def level_db(self) -> float:
        """Live input level, for the waveform display (R13).

        Floored while Flow is talking, and that is a defect fix rather than a nicety.
        `Mic._level` is written by the PortAudio callback, which knows nothing about the
        echo guard; during a spoken reply it tracks Flow's own voice coming back through
        the speakers. Measured: with the guard discarding all 30 blocks of a reply, the
        meter still read 83% of full scale — eighteen bars dancing to prove Flow was
        listening at the one moment it was guaranteed not to be.
        """
        if not self.hearing:
            return DEAF_DB
        return self.mic.level_db

    @property
    def activity(self) -> Activity | None:
        """The one honest answer to "what is Flow doing right now".

        `None` when there is nothing to wait for. Listening, a held draft and idle are
        already said by the pill's colour, by the level bars and by the countdown on the
        Ask button, and an indicator that is always on is an indicator nobody reads.

        Ordered by what the user most needs to know. Speaking is first because it is the
        only one of these that means "stop talking" rather than "wait a moment"; the
        model load is checked before the decode because a first decode of a tier is a
        model build with a decode behind it, and those differ by about a second.
        """
        if not self.hearing:
            return Activity("speaking - not listening", False)
        if self.state is State.ASKING:
            return Activity("asking", True)
        if self.state is State.REFINING:
            return Activity("refining", True)
        if getattr(self.asr, "loading", False):
            return Activity("loading the model", True)
        # Only once the gate has closed. While it is open the user is mid-sentence and
        # the partial decoder is running continuously, so this would be lit permanently
        # and would say nothing; the bars are what carries that moment.
        if self.worker.busy and not self.gate.speaking:
            return Activity("decoding", True)
        return None

    # -- the pump ----------------------------------------------------------

    def tick(self) -> None:
        self._pump_audio()
        self.pump_results()
        # Deliberately in tick() and not in pump_results(): auto-ask needs a live
        # microphone to mean anything. Disarming is a way of saying "stop", and a pill
        # the user just switched off must not fire a question a few seconds later.
        self._pump_auto_ask()
        self._pump_health()

    def pump_results(self) -> None:
        """Everything that is waiting on something other than the microphone.

        Split out of `tick()` because the caller drives the pump only while it is
        capturing, and that quietly made a disarmed pill lose whatever was in flight: a
        question already with the CLI came back onto `_ask_result` and stayed there,
        because the only code that collects it ran behind the microphone check. The
        answer to a question you already asked does not depend on still listening, and
        disarming while waiting is the natural thing to do — especially now that Flow
        goes deaf while it reads a reply aloud.
        """
        self._pump_decodes()
        self._pump_drops()
        self._pump_refine()
        self._pump_ask()

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
        """Long-session upkeep (R8): overflow, device liveness, idle model unload."""
        now = time.perf_counter()
        self._pump_overflow()

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

    def _pump_overflow(self) -> None:
        """Say when the microphone queue threw audio away.

        `Mic.dropped` counted and nothing read it, which made the microphone the one
        hole in "no words are dropped silently": the queue discards its oldest block
        when full, and the user hears about it never.

        Checked every tick and reported on growth, which cannot become spam even
        though it sounds like it could. The queue holds 256 blocks, so reaching a drop
        at all means the reader stalled for ~16 s — and the first tick afterwards
        drains it, so the next drop is another 16 s of stalling away. Bursts, not a
        trickle, and the burst is one note.

        `getattr` because `Mic` is injectable and every fake in the tests predates the
        counter — the same reason `_pump_drops` asks the transcriber that way.
        """
        raw = getattr(self.mic, "dropped", 0)
        if raw > self._last_mic_dropped:
            lost = raw - self._last_mic_dropped
            self.mic_dropped += lost
            seconds = lost * BLOCK / SAMPLE_RATE
            amount = f"{seconds:.1f} s" if seconds >= 1.0 else f"{seconds * 1000:.0f} ms"
            self._emit(
                "note",
                f"microphone overflowed — about {amount} of audio was lost while the "
                "UI was held",
            )
        # Rebased even when it went backwards: a reopened device brings a fresh counter,
        # and counting that as recovered audio would be the opposite of the truth.
        self._last_mic_dropped = raw

    def _utter_sec(self) -> float:
        return len(self._utter) * BLOCK / SAMPLE_RATE

    def _pump_audio(self) -> None:
        blocks = self.mic.drain()

        # P9: while an answer is playing, the microphone is hearing the speakers, not
        # the user — and there is no echo cancellation here to tell those apart (a real
        # AEC is a dependency, and R16 does not have room for one).
        #
        # Feeding it anyway is what broke converse mode in the first live session. The
        # reply "Yes, we can hear you." played, the gate opened on Flow's own voice,
        # `speaker.stop()` cut the answer off mid-sentence, and the captured fragment
        # decoded to "Yes." and was appended to the draft — so the next question sent to
        # the CLI carried a word the user never said, and the conversation looked like
        # it had silently reverted to dictation.
        #
        # Half-duplex is the honest fix: hear the user, or talk, not both. Interrupting
        # is an explicit action now (clear, disarm, or mute) rather than a guess about
        # whose voice just arrived.
        if self.speaker is not None and self.speaker.speaking:
            if self._utter:
                # Speech already in flight when the answer began is genuinely the
                # user's. Commit it rather than dropping it on the floor.
                self._finalise()
            # Reset rather than leave it half-open: the pre-roll must not keep a tail of
            # Flow's own voice to prepend to whatever the user says next.
            self.gate.reset()
            self.echo_blocks += len(blocks)
            return

        for block in blocks:
            started, stopped = self.gate.push(block)
            if self.gate.speaking:
                if started:
                    # The gate could only open once it heard something loud, so the
                    # quiet head of that very word is already behind us. Take it back.
                    self._utter.extend(self.gate.take_preroll())
                self._utter.append(block)
                self._last_activity = time.perf_counter()
                # Neither of the two CLI states may be overwritten here. REFINING was
                # always excluded; ASKING was not, so speaking while a question was out
                # turned the pill green, and the answer landing then set IDLE — the
                # violet "still thinking" state vanished the moment the user said
                # anything, which is precisely when they most want to see it.
                if self.state not in (State.REFINING, State.ASKING):
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
        audio = np.concatenate(self._utter)
        self._last_audio = audio
        self.worker.submit_final(audio)
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
            elif kind == "rescue":
                self._finish_rescue(text)
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
        # Consumed here, before any early return, and expired by age. The chip is
        # pressed *for the utterance the user is about to say*; leaving it set when
        # that utterance takes another path meant it silently applied to a later,
        # unrelated one — the user pressed Refine, said something that started a fresh
        # draft, and then a minute later had an ordinary sentence routed to the CLI.
        forced = self._take_force_next()

        # The two thread verbs are the only commands that mean anything with an empty
        # draft — which is precisely the state Send leaves behind.
        thread_plan = plan(utterance, self.draft.text)
        if thread_plan.kind == "recall":
            self._recall()
            return
        if thread_plan.kind == "followup":
            self._start_followup(thread_plan.payload)
            return

        if not self.draft.text:
            self.draft.append(utterance)
            self._remember_append(utterance)
            self._after_draft_change()
            return

        if forced == "append":
            self.draft.append(utterance)
            self._remember_append(utterance)
            self._after_draft_change()
            return

        p = plan(utterance, self.draft.text)
        if forced == "edit" and p.kind == "append":
            # The user explicitly said "this is an instruction", so honour that over
            # the heuristic and let the CLI interpret whatever they asked for.
            p = type(p)("semantic", payload=utterance)

        if p.kind == "rescue":
            self.rescue_last_append()
            return
        if p.kind == "append":
            self.draft.append(utterance)
            self._remember_append(utterance)
        elif p.kind == "undo":
            # P8: an undo that lands straight on top of an append is the signature of
            # a command the router read as dictation. Recorded before the undo, since
            # undoing is what clears the evidence.
            if self.profile is not None and self._last_append is not None:
                self.profile.note_misroute(self._last_append[0])
            if not self.draft.undo():
                self._emit("note", "nothing to undo")
        elif p.kind == "local":
            before = self.draft.text
            new, applied = apply_local(before, p)
            if applied:
                self.draft.set(new)
                # P8: a correction is a confusion pair the user labelled themselves —
                # the model wrote X, they wanted Y. Exactly the supervision hotwords
                # need, and free to collect.
                #
                # The case operations are in this list, and they are not an afterthought:
                # "capitalize sameer" is how people fix a name, it is item 3 on the
                # recording sheet, and it used to teach nothing at all because the plan
                # carries only a target and no payload.
                if self.profile is not None and p.op in LEARNABLE:
                    # Both sides come from the *texts*, not from the plan. "change
                    # sameer to Samir" is transcribed "change Samir to Samir" — the
                    # spoken target and payload are homophones, which is precisely why
                    # the correction was needed — so learning from the plan discards
                    # exactly the corrections worth learning. What left the draft is the
                    # model's own wrong reading; what arrived is the spelling wanted.
                    gone = removed_text(before, new).split(" … ")[0]
                    got = added_text(before, new).split(" … ")[0]
                    self.profile.learn_pair(gone, got or p.payload)
                self._emit("note", f"local: {describe_change(p, before, new)}")
            else:
                # Asked for something we could not do locally — escalate rather than
                # silently no-op, which would read as the app ignoring the user.
                self._start_refine(utterance)
                return
        else:
            self._escalate(p)
            return

        self._after_draft_change()

    def recall(self) -> None:
        """P6: put the last sent prompt back, by button rather than by voice.

        The bubble's "Put it back" chip after a Send, and the spoken "bring back my last
        prompt", are the same act and go down the same path deliberately — the second
        implementation is the one that would rot.
        """
        self._recall()

    def _recall(self) -> None:
        """P6: put the last sent prompt back in the draft."""
        last = self.thread.last
        if not last:
            self._emit("note", "nothing sent yet")
            return
        if self.draft.text:
            # Never silently discard what is on screen to make room for history.
            self.draft.append(last)
        else:
            self.draft.set(last)
        self.following_up = True
        self._emit("note", "brought back the last prompt")
        self._after_draft_change()

    def _start_followup(self, rest: str) -> None:
        """P6: the next thing said continues the thread rather than starting over."""
        if not self.thread.last:
            # Nothing to follow, so this is just dictation with an odd opening.
            if rest:
                self.draft.append(rest)
                self._remember_append(rest)
            self._emit("note", "nothing sent yet - treating that as dictation")
            self._after_draft_change()
            return
        self.following_up = True
        if rest:
            self.draft.append(rest)
            self._remember_append(rest)
        self._emit("note", f"following up on {len(self.thread)} sent")
        self._after_draft_change()

    def _remember_append(self, utterance: str) -> None:
        """Keep the last dictation, with its audio, for a post-hoc reinterpretation."""
        self._last_append = (utterance, self._last_audio)

    @property
    def can_rescue(self) -> bool:
        """True when there is a just-appended utterance to reinterpret."""
        return self._last_append is not None and bool(self.draft.text)

    def rescue_last_append(self) -> bool:
        """"That was a command." Take back the last dictation and re-read it.

        A misroute currently costs the user two utterances — undo, then say it again —
        and the second one is no likelier to be heard correctly than the first. This
        costs one short phrase and re-reads audio already captured.

        The append is withdrawn *first*, so the re-plan sees the draft as it was when
        the command was spoken; the target of a correction is in that text, not in the
        text with the correction appended to it. Nothing is lost if the re-read fails:
        the words go back exactly where they were.
        """
        if self._last_append is None:
            self._emit("note", "nothing to re-read")
            return False
        utterance, audio = self._last_append
        self._last_append = None

        restored = self.draft.undo()
        if not restored:
            self._emit("note", "nothing to re-read")
            return False

        p = plan(utterance, self.draft.text)
        if p.kind == "local":
            before = self.draft.text
            new, applied = apply_local(before, p)
            if applied:
                self.draft.set(new)
                self._emit("note", f"re-read as {describe_change(p, before, new)}")
                self._after_draft_change()
                return True

        if audio is not None and self._post_hoc is None:
            # The words as transcribed are not a command either, so ask the decoder
            # again with the command vocabulary in hand.
            self._post_hoc = utterance
            self._emit("note", "re-listening to that as a command")
            self.worker.submit_rescue(audio, command_bias(self.draft.text))
            return True

        self._give_back(utterance, "could not re-read that as a command")
        return False

    def _give_back(self, utterance: str, note: str) -> None:
        """Put a withdrawn utterance back. The user's words are never the price of a
        failed guess."""
        self.draft.append(utterance)
        self._last_append = (utterance, self._last_audio)
        self._emit("note", note)
        self._after_draft_change()

    def _escalate(self, p) -> None:
        """A semantic plan. Try one cheap re-decode first, if it might be a mis-hearing.

        `escalated` means the shape was a correction but the target was nowhere in the
        draft — which is far likelier to be a mis-heard word than a request for
        judgement. A second decode biased toward the trigger verbs and the draft's own
        words costs about a second; the CLI costs seven and will be asked to edit text
        that does not contain the word.
        """
        if p.op == "polish":
            # A named request for a specific transformation, not an instruction to be
            # interpreted — and never a mis-hearing to re-listen for.
            self._start_refine(p.payload, polish=True)
            return
        if p.escalated and self._last_audio is not None and self._pending_rescue is None:
            self._pending_rescue = p.payload
            self._emit("note", f"re-listening for {p.target!r}")
            self.worker.submit_rescue(
                self._last_audio, command_bias(self.draft.text)
            )
            return
        self._start_refine(p.payload)

    def _finish_rescue(self, text: str) -> None:
        """The biased re-decode came back. Accept it only if it beats the first read."""
        if self._post_hoc is not None:
            original, self._post_hoc = self._post_hoc, None
            p = plan(text, self.draft.text) if text else None
            if p is not None and p.kind == "local":
                before = self.draft.text
                new, applied = apply_local(before, p)
                if applied:
                    self.draft.set(new)
                    self._emit("note",
                               f"re-read as {describe_change(p, before, new)}")
                    self._after_draft_change()
                    return
            self._give_back(original, "could not re-read that as a command")
            return

        instruction, self._pending_rescue = self._pending_rescue, None
        if instruction is None:
            return  # a rescue nobody is waiting for; ignore rather than act on it
        p = plan(text, self.draft.text) if text else None
        if p is not None and p.kind == "local":
            before = self.draft.text
            new, applied = apply_local(before, p)
            if applied:
                self.draft.set(new)
                self._emit("note", f"re-heard as {describe_change(p, before, new)}")
                self._after_draft_change()
                return
        # The second read did not find a command either. The CLI was always the
        # fallback; it just costs a second more than it used to.
        self._start_refine(instruction)

    @property
    def force_next(self) -> str | None:
        """Explicit routing override for the next utterance ("append" | "edit").

        A property so that *assigning* it stamps the time — the UI, the tests and the
        probes all set it directly, and a TTL that depended on each caller remembering
        to record a timestamp would be a TTL that quietly did not apply.
        """
        return self._force_next

    @force_next.setter
    def force_next(self, mode: str | None) -> None:
        self._force_next = mode
        self._force_next_at = time.perf_counter()

    def _take_force_next(self) -> str | None:
        """Consume the override, or drop it if it has gone stale."""
        forced, self._force_next = self._force_next, None
        if forced and time.perf_counter() - self._force_next_at > FORCE_NEXT_TTL_SEC:
            self._emit("note", f"{forced} expired - treating this as normal speech")
            return None
        return forced

    def _after_draft_change(self) -> None:
        self._settle_state()
        # Every route ends here — dictation, a local edit, an undo, a rescue — so this
        # is the one place that knows the draft has stopped moving. A correction
        # restarts the clock, which is what keeps the draft correctable until it fires.
        self._settled_at = time.perf_counter() if self.draft.text else None
        self._emit("draft", self.draft.text)

    # -- P9: asking without a button press ---------------------------------

    def _auto_ask_armed(self) -> bool:
        """Whether a settled converse-mode draft is counting down to being asked.

        Every clause is a way the draft is not finished with: a CLI call is holding it,
        the gate is open, audio is waiting to be decoded, a decode is running, or the
        previous answer is still playing — during which the microphone is gated, so
        silence proves nothing about the user.

        The two CLI clauses ask the calls themselves rather than reading `state`. That
        is the whole defect this pins: routing overwrote REFINING with DRAFT, the
        countdown re-armed against a draft a rewrite was still out on, and the question
        went unrewritten with no press.
        """
        return (
            self.auto_ask
            and self.mode == CONVERSE
            and self._refine_op is None
            and self._ask_op is None
            and self._settled_at is not None
            and bool(self.draft.text.strip())
            and not self.gate.speaking
            and not self._utter
            and not self.worker.busy
            and not (self.speaker is not None and self.speaker.speaking)
        )

    @property
    def auto_ask_in(self) -> float | None:
        """Seconds until the draft goes on its own, or None if nothing is counting.

        Read by the UI every frame to put the countdown on the Ask button. A silent
        timer that sends the user's words is the thing this must never be.
        """
        if not self._auto_ask_armed():
            return None
        return max(0.0, AUTO_ASK_SEC - (time.perf_counter() - self._settled_at))

    def hold_auto_ask(self) -> None:
        """Restart the countdown. The user is still working on this draft."""
        if self._settled_at is not None:
            self._settled_at = time.perf_counter()

    def toggle_auto_ask(self) -> bool:
        self.auto_ask = not self.auto_ask
        self._emit("note", "auto-ask on - a pause sends the question"
                   if self.auto_ask else "auto-ask off - press Ask when you are ready")
        return self.auto_ask

    def _pump_auto_ask(self) -> None:
        if not self._auto_ask_armed():
            return
        if time.perf_counter() - self._settled_at < AUTO_ASK_SEC:
            return
        self._emit("note", "no more speech - asking")
        self.send()

    # -- semantic refine (off-thread: ~7 s measured) ------------------------

    def _start_refine(self, instruction: str, *, polish: bool = False) -> None:
        if self._refine_op is not None:
            # The refusal `send()` already makes, for the same reason. Two rewrites of
            # one draft race to write it, and the loser's words are the user's.
            self._emit("note", "still rewriting — say that again when it lands")
            return
        op = self._refine_op = self._next_op()
        # The version this rewrite is an answer about. The draft stays editable for
        # the whole ~7 s the CLI takes, so the result has to be checked against it.
        revision = self.draft.revision
        self._settle_state()
        self._emit(
            "note",
            "shaping that into a prompt" if polish
            else f"refining via CLI: {instruction!r}",
        )
        before = self.draft.text

        context = self.thread.tail() if self.following_up else []

        def work() -> None:
            result = refine(
                before, instruction, cwd=self._refine_cwd, polish=polish,
                context=context, cancel=self._cancel,
            )
            with self._refine_lock:
                self._refine_result = (op, revision, result)

        threading.Thread(target=work, daemon=True, name="refine").start()

    def _pump_refine(self) -> None:
        with self._refine_lock:
            pending, self._refine_result = self._refine_result, None
        if pending is None:
            return
        op, revision, (revised, note) = pending
        if op != self._refine_op:
            # A result for a call nobody is waiting on any more — the same rule as a
            # rescue nobody asked for: ignore it rather than act on it.
            return
        self._refine_op = None
        if revised is None:
            self._emit("error", f"refine failed ({note}) — draft unchanged")
        elif revision != self.draft.revision:
            # A rewrite of text that no longer exists. Applying it would delete
            # whatever was said while the CLI was thinking, and would do it invisibly,
            # because what replaced the draft reads like a plausible draft.
            self._emit("note", "discarded a stale rewrite — the draft moved on")
        else:
            self.draft.set(revised)
            self._emit("note", f"refined via {note}")
        self._after_draft_change()

    # -- actions -----------------------------------------------------------

    def voices(self) -> list:
        """What this machine can speak with. Empty when there is no engine at all.

        Cached in `speak`, and warmed at startup by `__main__` when the engine is
        available — which matters because the UI thread calls this to build the menu,
        and the uncached answer costs a PowerShell start-up (measured: 516 ms cold,
        0.01 ms warm). Left as a plain call rather than made async: it is warm by the
        time any menu opens, and a background thread here would be a second way to
        reach the engine for no benefit.
        """
        if self.speaker is None:
            return []
        from .speak import installed_voices

        return installed_voices()

    def set_voice(self, name: str | None) -> bool:
        """P9: choose the voice that reads the replies, and remember it.

        Saved immediately rather than at the next Send, which is where the profile is
        normally committed. A voice is chosen by listening to it, and someone who picks
        one and closes the app has still made the choice.
        """
        if self.speaker is None:
            return False
        self.speaker.use(name)
        if self.profile is not None:
            self.profile.voice = name
            self.profile.save()
        self._emit("note", f"voice: {name}" if name else "voice: engine default")
        return True

    def toggle_speech(self) -> bool:
        """Mute or unmute spoken replies mid-session. True when it will now speak."""
        self.muted = not self.muted
        if self.muted and self.speaker is not None:
            self.speaker.stop()
        self._emit("note", "replies muted" if self.muted else "replies spoken aloud")
        return not self.muted

    def toggle_mode(self) -> str:
        """P9: one action switches dictate <-> converse. Returns the new mode.

        Deliberately does not touch the draft. Someone who has dictated three sentences
        and then decides they want to ask about them rather than paste them should not
        have to say it again — the words are the same words either way.
        """
        self.mode = CONVERSE if self.mode == DICTATE else DICTATE
        self._emit("mode", self.mode)
        # Named after the button that is actually on screen. This used to say "Send asks
        # the CLI" while the chip renamed itself to "Ask", so the app announced one verb
        # and displayed another — and the first person to read both concluded the mode
        # had not really changed. In converse mode there is no Send anywhere; saying so
        # is free, and the same class of defect as the chip whose label the grammar
        # rejected.
        self._emit("note", "converse mode - press Ask to put the draft to the CLI"
                   if self.mode == CONVERSE else "dictate mode - Send pastes")
        return self.mode

    def send(self) -> str:
        """Hand off the draft and reset.

        In dictate mode the caller injects the returned text (stage 8). In converse
        mode the text goes to the CLI instead and the caller gets "" — there is nothing
        to paste, and returning the text anyway would paste the question into whatever
        window happened to have focus.

        Both refusals below say so out loud. Send is a button, and a button that does
        nothing when pressed reads as broken — which is exactly how it was reported.
        """
        if not self.draft.text.strip():
            self._emit("note", "nothing to send - the draft is empty")
            return ""
        # The in-flight calls, not `state`: the state is a display of what is happening
        # and routing can move it, while these two are the fact itself.
        if self._ask_op is not None:
            self._emit("note", "still waiting on the last answer")
            return ""
        if self._refine_op is not None:
            self._emit("note", "still rewriting - one moment")
            return ""
        text = self.draft.clear()
        # Cleared here rather than in `_after_draft_change`, which send() does not call:
        # a stale timestamp would leave the countdown armed against an empty draft.
        self._settled_at = None
        self.thread.add(text)
        # P8: send is the natural commit point — rare, user-initiated, and the moment
        # a session's corrections have proved themselves by surviving to a handoff.
        if self.profile is not None:
            self.profile.save()
        self.following_up = False
        self.gate.reset()
        self._utter = []
        self._emit("draft", "")
        if self.mode == CONVERSE and text.strip():
            self._start_ask(text)
            return ""
        self._set_state(State.IDLE)
        return text

    def _start_ask(self, question: str) -> None:
        """P9: put the draft to the CLI off the hot path (R11) and wait for the reply."""
        op = self._ask_op = self._next_op()
        self._set_state(State.ASKING)
        self._emit("note", "asking…")
        # The thread already holds this question (send() added it), so the context is
        # every *earlier* turn — passing the current one would ask the CLI not to
        # answer the thing it was just asked.
        context = self.thread.tail()[:-1]

        def work() -> None:
            result = ask(question, cwd=self._refine_cwd, context=context,
                         cancel=self._cancel)
            with self._ask_lock:
                self._ask_result = (op, result)

        threading.Thread(target=work, daemon=True, name="ask").start()

    def _pump_ask(self) -> None:
        with self._ask_lock:
            pending, self._ask_result = self._ask_result, None
        if pending is None:
            return
        op, (answer, note) = pending
        if op != self._ask_op:
            return
        self._ask_op = None
        if answer is None:
            # Non-destructive by construction: the question is still in the thread, so
            # "say that again" and a retry both still work.
            self._emit("error", f"ask failed ({note})")
            self.reply = ""
        else:
            self.reply = answer
            # Recorded as a turn so the next question inherits it — this is what makes
            # "and what about the other one?" mean anything.
            self.thread.add(f"(reply) {answer}")
            self._emit("reply", answer)
            if self.speaker is not None and not self.muted:
                self.speaker.say(answer)
            self._emit("note", f"answered via {note}")
        # Not IDLE: the microphone was open for the whole wait, so there may be a draft
        # by now — and a rewrite of it may already be out. Reporting nothing held would
        # also stop the countdown that was running on that draft, silently.
        self._settle_state()

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """Pump until no decode or refine is outstanding. For tests and harnesses."""
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            self.tick()
            if (
                not self.worker.busy
                and self._refine_op is None
                and self._ask_op is None
                and not self._utter
            ):
                return True
            time.sleep(0.02)
        return False
