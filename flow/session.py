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
    apply_local,
    command_bias,
    describe_change,
    plan,
    removed_text,
)
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
        self._refine_result: tuple[str | None, str] | None = None
        self._refine_lock = threading.Lock()
        #: P9: dictate (paste into the focused window) or converse (ask the CLI).
        self.mode = DICTATE
        #: Spoken replies. None means the engine was unavailable or refused.
        self.speaker = speaker
        #: Runtime mute, separate from `speaker` being absent — one is a capability,
        #: the other is a preference, and the UI has to be able to change the second.
        self.muted = False
        #: P8. What Flow has measured and learned about this person, on this machine.
        #: None disables learning entirely — the tests and the benchmarks pass None so
        #: a harness run never writes to the user's real profile.
        self.profile = profile
        self._ask_result: tuple[str | None, str] | None = None
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
        self._pump_ask()
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
            started, stopped = self.gate.push(block)
            if self.gate.speaking:
                if started:
                    # The gate could only open once it heard something loud, so the
                    # quiet head of that very word is already behind us. Take it back.
                    self._utter.extend(self.gate.take_preroll())
                    # P9: the user talking over the answer means they are done with
                    # it. Speech that keeps going while they speak is also speech the
                    # microphone is picking up.
                    if self.speaker is not None:
                        self.speaker.stop()
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
                # P8: "change X to Y" is a confusion pair the user labelled themselves
                # — the model wrote X, they wanted Y. Exactly the supervision hotwords
                # need, and free to collect.
                if self.profile is not None and p.op in ("replace", "replace_all"):
                    # The pair comes from the *texts*, not from the plan. "change
                    # sameer to Samir" is transcribed "change Samir to Samir" — the
                    # spoken target and payload are homophones, which is precisely why
                    # the correction was needed — so learning from the plan discards
                    # exactly the corrections worth learning. What was removed from the
                    # draft is the model's own wrong reading, which is the label.
                    gone = removed_text(before, new).split(" … ")[0]
                    self.profile.learn_pair(gone, p.payload)
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
        self._set_state(State.DRAFT if self.draft.text else State.IDLE)
        self._emit("draft", self.draft.text)

    # -- semantic refine (off-thread: ~7 s measured) ------------------------

    def _start_refine(self, instruction: str, *, polish: bool = False) -> None:
        self._set_state(State.REFINING)
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
                context=context,
            )
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
        self._emit("note", "converse mode - Send asks the CLI"
                   if self.mode == CONVERSE else "dictate mode - Send pastes")
        return self.mode

    def send(self) -> str:
        """Hand off the draft and reset.

        In dictate mode the caller injects the returned text (stage 8). In converse
        mode the text goes to the CLI instead and the caller gets "" — there is nothing
        to paste, and returning the text anyway would paste the question into whatever
        window happened to have focus.
        """
        text = self.draft.clear()
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
        self._set_state(State.ASKING)
        self._emit("note", "asking…")
        # The thread already holds this question (send() added it), so the context is
        # every *earlier* turn — passing the current one would ask the CLI not to
        # answer the thing it was just asked.
        context = self.thread.tail()[:-1]

        def work() -> None:
            result = ask(question, cwd=self._refine_cwd, context=context)
            with self._ask_lock:
                self._ask_result = result

        threading.Thread(target=work, daemon=True, name="ask").start()

    def _pump_ask(self) -> None:
        with self._ask_lock:
            result, self._ask_result = self._ask_result, None
        if result is None:
            return
        answer, note = result
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
        self._set_state(State.IDLE)

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """Pump until no decode or refine is outstanding. For tests and harnesses."""
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            self.tick()
            if (
                not self.worker.busy
                and self.state is not State.REFINING
                and self.state is not State.ASKING
                and not self._utter
            ):
                return True
            time.sleep(0.02)
        return False
