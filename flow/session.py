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
from pathlib import Path
from typing import NamedTuple

import numpy as np

from . import MAX_UTTERANCE_SEC, SAMPLE_RATE
from .asr import Transcriber, WhisperTranscriber
from .audio import BLOCK, Mic, SpeechGate
from .diag import Diag, NullDiag
from .edits import (
    SEND_ENTER_WORD,
    SEND_WORD,
    added_text,
    apply_local,
    command_bias,
    describe_change,
    is_artifact_request,
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
from .help import auto_ask_notice, exits_note
from .notes import Notes, render as render_notes, write as write_notes
from .phonetic import similarity
from .profile import path_key
from .refine import TIMEOUT_SEC as REFINE_TIMEOUT_SEC
from .refine import MAX_CHARS as REFINE_MAX_CHARS
from .refine import ask, available, refine, tail_sent
from .thread import ASK_CONTEXT_CHARS, Thread

#: What every converse ask carries after the question. It used to say the opposite of
#: this — "help the developer refine the prompt above … do not carry out the task it
#: describes" — and that is the sentence Flow's first three outside users met
#: (decisions.md 2026-08-03). Asked "how are you", codex answered *"The prompt is clear
#: as casual conversation, but it does not request any coding work"*. The instruction
#: was obeyed exactly, which is the proof it was the wrong instruction: nobody was
#: workshopping a prompt, they were asking to learn about a project. The
#: improve-this-prompt brief survives where a prompt actually exists, which is Refine.
#:
#: **Placed after the question, and that is not a style choice.** `refine.ask()` keeps
#: the *tail* of an over-long input, so anything in front of the text is the first thing
#: discarded — and it would be discarded for exactly the long questions this is most
#: likely to be handling. Trailing framing survives the cut that heading framing does
#: not, which a test asserts on a question 3 000 characters past `MAX_CHARS`.
GROUNDING = (
    "\n\n---\n"
    "Answer the question above for the developer who asked it.{workspace}"
)

#: The workspace clause, empty when there is none, so an ungrounded ask does not claim
#: a project it has not got. It grants rather than instructs: a question about the
#: weather must not send the CLI reading source files, and a question about the project
#: must.
GROUNDING_WHERE = (
    "\nWORKSPACE: {path} - the developer is working there; consult it when the question "
    "concerns it."
)


def ask_framing(cwd: str | None) -> str:
    """The trailing clause `_start_ask` appends, and what the budget is measured against.

    A function rather than a `.format` inside `_start_ask` because two callers need the
    same string to agree — the one that sends it and the one that sizes the question to
    fit beside it.
    """
    return GROUNDING.format(
        workspace=GROUNDING_WHERE.format(path=cwd) if cwd else ""
    )

#: The moment of egress names the ground (decisions.md "Workspace grounding"): the
#: leaf, not the path, because the note is glanced at as the question leaves — and
#: bounded, because it is the one word in that note the user's filesystem wrote.
#: `help.MAX_HEAD`'s figure, `help.fit`'s idiom.
WORKSPACE_LEAF_MAX = 24

#: How close an utterance has to sound to a configured trigger before Flow says so.
#:
#: Swept, not chosen. Over every distinct one- and two-word sequence in the 580 real
#: EdAcc utterances — **4 866 of them** — against all six shipped presets and their
#: enter-variants: 0.70 fires 13 times, 0.75 fires 7 (`ZOOM`/boom, `MAN`/mango,
#: `BOOK`/boom, `DOING`/tango, `POEM`/boom, `TONIC`/tango), and **0.78 and everything
#: above it fires zero**. Against 25 plausible decoder misses written down before the
#: sweep ran, 0.78 catches 22, 0.82 catches 21, 0.90 catches 15. So 0.78 is the knee:
#: the lowest bar with no false fire on real speech, and the one that gives up least.
#:
#: Deliberately *not* `edits.MATCH_THRESHOLD` (0.82), and the difference is what the two
#: numbers buy. That one fires an edit; this one only speaks. A notify rule can afford to
#: be more sensitive than an editing one, and sharing a constant would tie a note's
#: sensitivity to a rewrite's caution for no reason but tidiness.
NEAR_MISS_SIMILARITY = 0.78

#: How many recent items are kept for the Recent menu. Bounded by count the way `Thread`
#: is, and for R8's reason: a long session must cost what a short one costs.
#:
#: **In memory and nowhere else** (decisions.md 2026-08-03, part 3). Flow's standing
#: position is that the words are never stored, and that holds here by construction
#: rather than by care — nothing in this file writes, `diag.NEVER` refuses every field
#: that could carry them, and a test asserts no new file appears under the settings
#: folder across a full session. The cost is that quitting loses it. If that ever bites
#: somebody the next shape is an opt-in on-disk history, never a default one.
RECENT_MAX = 20

#: What a Recent entry is, in one word: dictated, asked, or answered. Roles rather than a
#: bare list, because "what I said" and "what came back" are the two things somebody is
#: looking for and a flat list makes them look the same.
RECENT_SAID = "said"
RECENT_ASKED = "asked"
RECENT_ANSWERED = "answer"

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

#: How long `close()` waits for a thread it owns before abandoning it. Every wait on the
#: quit path is bounded, because the two threads being waited on are the ones with no
#: ceiling of their own: a decode is however long the audio is, and a first-run preload
#: is a 141 MB download. Both are daemons, so abandoning one costs nothing at the door;
#: blocking the quit behind either costs the user a window that will not go away.
JOIN_SEC = 2.0

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

#: P9 profiles: past either bound, an artifact answer is rendered whole and *spoken* as
#: a one-line pointer instead of read out. The reason is invariant 6, not politeness:
#: Flow is deaf for as long as it talks, and a 60-line prompt read at the measured
#: 1.5 words/s is minutes of deafness with no way back in but clear, disarm or mute.
#: Three lines / 300 chars is about what a listener can hold of structured content
#: anyway; a conversational answer is never summarised, whatever its length.
ARTIFACT_SAY_MAX_LINES = 3
ARTIFACT_SAY_MAX_CHARS = 300

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
    #:                | conversation - the thread and the reply were cleared (item 64)
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


@dataclass(frozen=True)
class Utterance:
    """One captured stretch of speech, and the identity its result carries back.

    Frozen and passed by value because the defect it exists to close is a *mutable slot*:
    `_last_audio` held whatever the most recent `_finalise` wrote, so a result arriving
    after the next utterance had been captured was paired with that one's sound. Those
    two are the same object exactly when decoding is instant, and decoding is the slowest
    thing in this app.

    `generation` is the capture epoch. A pause is a boundary — everything spoken before it
    belongs to a session the user deliberately stopped — so a result minted under an older
    generation is refused on arrival rather than folded into the new draft.
    """

    id: int
    audio: np.ndarray
    generation: int


@dataclass(frozen=True)
class Append:
    """The last dictation, plus enough identity to know it is still the last one.

    `revision` is the draft's revision immediately *after* this append landed, and it is
    the whole of DRAFT-02: "Was a command" used to ask only whether an append was
    remembered and whether the draft was non-empty, neither of which is *is this still
    the draft that append went into*. The chip stayed offered across further dictation,
    edits and sends, and pressing it withdrew an utterance from a draft it had never been
    part of.

    Nearly free, because every mutation of `Draft` already bumps the revision — a CLI
    rewrite takes ~7 s and something had to be able to tell whether the text it was
    computed from still existed.
    """

    text: str
    record: "Utterance | None"
    revision: int


@dataclass(frozen=True)
class Rescue:
    """A re-decode in flight, and what it was a re-decode *of*.

    Both rescue paths are ~1 s of decoding during which the draft can move — the user
    keeps talking, edits, or the auto-ask countdown fires — and both used to apply their
    result against whatever `self.draft.text` held at delivery. `payload` is what to fall
    back to: the withdrawn utterance for the user-pressed path, the instruction for the
    escalated one.
    """

    payload: str
    record: "Utterance | None"
    revision: int


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
        #: (audio, utterance). The record rides with the work rather than being looked up
        #: when the result lands, which is the whole of CAP-01: a lookup at delivery time
        #: reads a slot that a later utterance may already have overwritten.
        self._finals: deque[tuple[np.ndarray, Utterance | None]] = deque()
        #: (audio, hotwords, utterance) re-decodes of an utterance the router suspects was
        #: a mis-heard command. Queued like finals, because losing one means paying the
        #: CLI call this exists to avoid.
        self._rescues: deque[tuple[np.ndarray, str, Utterance | None]] = deque()
        #: (kind, text, seconds). The duration rides along so a caller can record
        #: it without draining `timings`, which the soak test reads for its own
        #: latency check and would otherwise find empty.
        self._out: deque[tuple[str, str, float]] = deque()
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

    def submit_final(self, audio: np.ndarray, utterance: "Utterance | None" = None) -> None:
        """`utterance` is optional so the probes that submit bare audio still work.

        `selfdrive.py` and several tests call this with audio alone — deliberately, since
        it is the seam `Session._finalise` itself uses and that is what makes those checks
        exercise the real decoder, router and apply. They have no identity to mint, and a
        result carrying `None` simply routes without one, exactly as before.
        """
        with self._cv:
            self._finals.append((audio, utterance))
            self._partial = None  # a final supersedes a pending partial of the same audio
            self._cv.notify()

    def submit_rescue(self, audio: np.ndarray, hotwords: str,
                      utterance: "Utterance | None" = None) -> None:
        """Re-decode this audio biased toward `hotwords`. Result kind: "rescue"."""
        with self._cv:
            self._rescues.append((audio, hotwords, utterance))
            self._cv.notify()

    def results(self) -> list[tuple[str, str, float, float | None]]:
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

    def close(self, timeout: float = JOIN_SEC) -> None:
        """Signal, then wait a bounded moment for the thread to actually leave.

        Signalling alone is a statement of intent: the thread may be inside a decode,
        which holds a model and a tier lock, and it went on running after `close()`
        returned. Joining makes "closed" mean the thread is gone — and the bound makes
        it safe to say so on the quit path, where a decode in flight can be seconds.
        Past the bound it is abandoned deliberately, which a daemon thread survives.
        """
        with self._cv:
            self._alive = False
            self._cv.notify()
        if self._thread is not threading.current_thread():
            self._thread.join(timeout)

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
                utterance: Utterance | None = None
                if self._finals:
                    (audio, utterance), kind = self._finals.popleft(), "final"
                elif self._rescues:
                    (audio, hotwords, utterance), kind = self._rescues.popleft(), "rescue"
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
            # Drained here, beside the text it belongs to, and unconditionally.
            # `take_confidence` clears as it reads, and this thread does not wait for
            # the UI thread: read later and the number would belong to whichever decode
            # happened next. Left undrained after an error it would belong to nothing at
            # all and still be there for the following utterance. `getattr` because
            # every fake transcriber in the tests predates the method — the way
            # `Mic.dropped` is read.
            take = getattr(self._asr, "take_confidence", None)
            confidence = take() if callable(take) else None
            with self._cv:
                self._busy = False
                self.timings.append((kind, elapsed))
                self._out.append((kind, text, elapsed, confidence, utterance))


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
        diag: Diag | None = None,
        cli: object | None = None,
        cli_timeout: float = REFINE_TIMEOUT_SEC,
        lite: bool = False,
    ) -> None:
        # `mic` and `asr` are injectable so the state machine can be tested without a
        # microphone or a 141 MB model — the routing logic is where the subtle bugs live.
        self.asr = asr or WhisperTranscriber()
        #: Lite (product.md): the draft is copied rather than pasted. Nothing in the
        #: state machine changes — routing, the draft, the thread and every refusal are
        #: the same brain — so this is read in exactly one place, the note that would
        #: otherwise name a focused window Lite cannot see.
        self.lite = lite
        self.mic = mic or Mic(device=device)
        self.gate = SpeechGate()
        self.worker = DecodeWorker(self.asr)
        self.draft = Draft()
        #: P6: what has already been sent. Send appends here instead of erasing, so a
        #: follow-up has something to follow.
        self.thread = Thread()
        #: The last `RECENT_MAX` things that happened to words, newest last: what was
        #: dictated, what was asked, what came back. A separate store from `thread`
        #: rather than a view of it, and the difference is the point — `thread` is what
        #: the *CLI* is told, trimmed to a character budget for that purpose and cleared
        #: by a workspace switch or a new conversation. This is what the *user* did, and
        #: it survives both, because "what did I say ten minutes ago" is a question
        #: about the session rather than about the current conversation.
        self._recent: deque[tuple[str, str]] = deque(maxlen=RECENT_MAX)
        #: P9: what the speaker stopped to keep. A third store rather than a view of the
        #: other two, and for the reason that separates all three: `thread` is what the
        #: CLI is told, `_recent` is what happened, and this is what was *chosen* — the
        #: only one of them entered by a deliberate act, which is what makes it the only
        #: one that may reach a file (`flow/notes.py`).
        self.notes = Notes()
        #: The question the answer on screen came from, so keeping "that exchange" keeps
        #: both halves of it. `_recent` holds the same string, but reading it back out
        #: would mean trusting a search through a mixed-role deque to find the right one;
        #: this is the fact itself, set where the question is known.
        self._last_question = ""
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
        #: Monotonic, so two utterances are never the same one however alike they sound.
        self._utterance_id = 0
        #: The capture epoch. `pause()` bumps it, and a result minted under an older one
        #: is refused: everything spoken before a deliberate pause belongs to a session
        #: the user stopped.
        self._capture_generation = 0
        #: A bounded tail of what has been submitted, for inspection only — the record
        #: that decides anything rides with the work. Bounded because R8 says a long
        #: session costs what a short one costs, and because a list of every utterance
        #: with its audio is a recording of the room.
        self._sent: deque[Utterance] = deque(maxlen=8)
        #: What the router was about to send to the CLI when it asked for a rescue.
        self._pending_rescue: str | None = None
        #: The last utterance that was appended as dictation, with its audio, so
        #: "that was a command" can re-read it instead of asking the user to repeat.
        self._last_append: Append | None = None
        #: Set while a post-hoc rescue is in flight, so its re-decode is routed back
        #: here rather than to the escalation path.
        self._post_hoc: str | None = None
        self._decoded_sec = 0.0
        self._events: deque[Event] = deque()
        self._refine_cwd = refine_cwd
        #: A pinned agent CLI, or None to walk the preference order with fallback.
        #: Pinning is a decision and is never second-guessed; None is a preference.
        self._cli = cli
        self._cli_timeout = cli_timeout
        #: (op, draft revision, result) — see `_next_op`.
        self._refine_result: (
            tuple[int, int, tuple[str | None, str], tuple[str, ...]] | None
        ) = None
        self._refine_lock = threading.Lock()
        #: Identity for CLI calls, and the id of whichever one is in flight. `state`
        #: cannot carry this: routing keeps running while a call is out and used to
        #: overwrite REFINING with DRAFT, after which everything that read the state
        #: believed no CLI work was happening.
        self._op = 0
        self._refine_op: int | None = None
        self._ask_op: int | None = None
        #: P9 profiles: whether the ask in flight requested a piece of work. Decided
        #: when the question leaves (edits.is_artifact_request) and read when the
        #: answer lands, to choose what the speaker says about it.
        self._ask_artifact = False
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
        #:
        #: Read from the profile, which defaults it to True, so the shipped behaviour is
        #: unchanged and a user who switched it off does not have to say so again every
        #: launch. `getattr` because a profile is optional and the fakes predate the
        #: field.
        self.auto_ask = bool(getattr(profile, "auto_ask", True))
        #: When the draft last stopped changing. None means nothing is pending.
        self._settled_at: float | None = None
        #: P8. What Flow has measured and learned about this person, on this machine.
        #: None disables learning entirely — the tests and the benchmarks pass None so
        #: a harness run never writes to the user's real profile.
        self.profile = profile
        #: A content-free shadow of the event stream (see flow/diag.py). Off unless
        #: the caller passes one, for the same reason `profile=None` disables learning:
        #: the tests build sessions in their hundreds, and a default that wrote to
        #: `~/.flow/diag.jsonl` would fill the real user's trace with runs that were
        #: never theirs. Caught exactly that way — the first run of this file left 1513
        #: records from the unit suite in a real profile directory.
        self.diag = diag if diag is not None else NullDiag()
        self._ask_result: (
            tuple[int, tuple[str | None, str], tuple[str, ...]] | None
        ) = None
        self._ask_lock = threading.Lock()
        #: The last answer, kept so the UI can re-render it and so a follow-up has
        #: something to refer to.
        self.reply = ""
        #: Explicit override for the next utterance's routing, set by the UI chips.
        #: The heuristic in edits.py is the default; this is the escape hatch for when
        #: it guesses wrong, per the "heuristic + explicit override" design in §4.
        self._force_next: str | None = None  # "append" | "edit" | None
        self._force_next_at = 0.0
        #: True while the draft is open in the bubble's keyboard editor. Three things
        #: read it: the microphone is suspended, the auto-ask countdown is held, and
        #: the indicator says which of the two deafnesses this is.
        self.editing = False
        #: The draft revision the editor opened on, so a commit can say whether
        #: anything landed behind it while the user typed.
        self._edit_revision = 0
        self._last_activity = time.perf_counter()
        self._last_mic_check = time.perf_counter()
        self._mic_started = False
        #: Blocks the microphone queue threw away, as observed by this session. The
        #: mic's own counter is the source; this one survives a device that brings a
        #: fresh counter with it, and is the number the diagnostics trace wants.
        self.mic_dropped = 0
        self._last_mic_dropped = getattr(self.mic, "dropped", 0)
        #: What registered this launch, assigned by `main()` after `Hotkeys.start()` —
        #: which is after this object exists, hence an attribute rather than an argument.
        #: Read only to say what still works when voice stops working (`_say_exits`).
        self.hotkeys = None
        #: Whether the voice-down note has already been said for the draft currently on
        #: screen. Cleared the moment there is nothing left to rescue, so one incident
        #: produces one note and the next incident produces the next.
        self._said_exits = False
        #: The device a mismatch has already been reported for, so a mic that keeps
        #: being reopened does not say the same thing every five seconds.
        self._noted_device: str | None = None
        #: When the CLI call in flight began. One of each kind runs at a time, so one
        #: slot is enough; it is only ever read by the trace.
        self._cli_started = 0.0
        #: Guards the three facts `start()` and `close()` disagree about — whether this
        #: session is still open, and which preload it owns. Held only around those
        #: decisions, never across a join, so closing cannot deadlock against an arm.
        self._lifecycle = threading.Lock()
        self._closed = False
        #: The one preload this session owns, or None before the first arm. Single, not
        #: one per arm: see `_warm`.
        self._preload_thread: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Open the mic and warm the model.

        The model load is *not* awaited here. On a first run it includes a ~141 MB
        download, and doing that inline froze the whole UI on the first click with no
        indication of why. The decode worker loads lazily on its own thread anyway, so
        this only pre-warms; `mic.start()` is what actually has to succeed.

        Runs on every arm, not once per session — which is why the warm-up is
        single-flight and why arming a closed session is refused rather than half done.
        `Pill._toggle` already renders a refusal to start capture and stays disarmed, so
        the raise reaches the user as a sentence instead of a green pill over a session
        whose worker is gone.
        """
        with self._lifecycle:
            if self._closed:
                raise RuntimeError("this session is closed")
        self.mic.start()
        self._mic_started = True
        self._last_activity = time.perf_counter()
        self._check_calibrated_device()
        self._warm()
        self._set_state(State.IDLE)

    def _warm(self) -> None:
        """One preload at a time, however often this session is armed.

        Invisible while the model is already loaded — the thread finds it warm and
        exits. On the run where it matters it is not: during a first-run download every
        arm used to park another thread on the tier lock, and 100 arm/pause cycles
        against a blocked load left **100 live threads**, each holding this session and
        each waking when the load finally landed.

        The gate is "is one running", not "has one ever run", so a load that failed —
        no disk, no network on a first launch — is tried again the next time the user
        arms. That is the door a "warmed once" flag would close.
        """
        with self._lifecycle:
            if self._closed:
                return
            running = self._preload_thread
            if running is not None and running.is_alive():
                return
            self._preload_thread = threading.Thread(
                target=self._preload, daemon=True, name="preload")
            self._preload_thread.start()

    def _check_calibrated_device(self) -> None:
        """Say when this is not the microphone the profile was measured through.

        A calibration is a measurement of a room *via a device*: the floor, the derived
        margin and this speaker's confidence baseline all move with the microphone. The
        room that broke the shipped gate read −96.7 dB on a good USB mic, and the same
        room through a laptop array does not read anything like that — so a swap leaves
        the gate tuned to a device that is no longer there, and nothing said so.

        Advisory, and only that. The stored numbers still beat the shipped defaults for
        the same room, and discarding a calibration because a device name changed would
        punish somebody for plugging in a headset. Silent when either side is unnamed:
        nothing to compare is not evidence of a mismatch.
        """
        if self.profile is None or not getattr(self.profile, "calibrated", False):
            return
        want = getattr(self.profile, "calibrated_device", None)
        have = getattr(self.mic, "device_name", "")
        if not want or not have or want == have or have == self._noted_device:
            return
        self._noted_device = have
        self._emit(
            "note",
            f"this is {have!r}; the calibration was measured on {want!r} — "
            "run flow --calibrate to redo it for this microphone",
        )

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
        # An atomic boundary, not just a stopped stream. Everything below survived a
        # pause until 2026-08-03 and arrived in the *next* transcript: `_utter` kept the
        # half-said sentence, the gate stayed open so the next arm resumed mid-utterance
        # with no onset, and the 256-block mic queue still held whatever was captured
        # before the stop. Nothing consumed any of it in between either — `ui.py` skips
        # `tick()` entirely while disarmed — so all three reached the other side intact.
        #
        # The generation covers the fourth road: a decode already in flight when the user
        # paused. That one cannot be discarded here because it is not here yet, so it is
        # refused on arrival instead.
        self._utter = []
        self.gate.reset()
        self.mic.drain()
        self._decoded_sec = 0.0
        self._capture_generation += 1
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
        """Give back everything `start()` and the constructor took, in that order.

        Idempotent because the quit paths overlap: `__exit__` on the way out of `main()`
        and the pill's own teardown both reach here, and a second round of teardown
        against a torn-down session is how a quit turns into a traceback. Nothing after
        the flag runs twice.

        The order is the argument:

        1. **Admission first.** Everything below is a statement about the past unless
           nothing new can start behind it — an arm one scheduling slot later used to
           re-open the microphone and warm a model for a session with no worker left.
        2. **The microphone**, so the room stops being recorded before anything that
           might take a moment.
        3. **Cancel, then the worker** — cancel first because it is the one that reaches
           outside the process. A refine thread used to run its `subprocess.run` to
           completion after the app was gone, and killing the CLI Flow launched still
           left the `node` it launched behind it: a model call billing tokens for an
           answer with no reader.
        4. **The speaker**, which is a PowerShell subprocess and outlives this one if
           nobody closes it. `speak.close()` existed from the beginning and nothing in
           the app called it.
        5. **The preload last**, because it is the longest wait and the least urgent —
           by the time it is joined the mic is shut and the worker is gone.

        Steps 3 and 5 are bounded joins (`JOIN_SEC`); past the bound the thread is
        abandoned deliberately. Both are daemons.
        """
        with self._lifecycle:
            if self._closed:
                return
            self._closed = True
            preload = self._preload_thread
        self.mic.stop()
        self._mic_started = False
        self._cancel.set()
        self.worker.close()
        # `getattr` because the speaker is injected and half the harnesses pass a
        # stand-in — the same reason `profile` is read that way.
        shut = getattr(self.speaker, "close", None)
        if callable(shut):
            shut()
        if preload is not None:
            preload.join(JOIN_SEC)

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
            self.diag.write("state", was=self.state.value, state=state.value)
            self.state = state
            self._emit("state", state.value)

    @staticmethod
    def _failure_category(note: str) -> str:
        """One word for a failure sentence, so the trace can be counted.

        A failure reason is built from the CLI's own stderr, so it is reduced to a
        category rather than written down. The categories are the ones `refine._invoke`
        produces.
        """
        low = note.lower()
        for word, category in (("timed out", "timeout"), ("cancelled", "cancelled"),
                               ("exited", "exit"), ("failed to start", "no-start"),
                               ("no agent cli", "no-cli"),
                               ("no time left", "no-time"),
                               ("commentary", "commentary"),
                               ("returned nothing", "empty")):
            if word in low:
                return category
        return "other"

    def _trace_cli(self, kind: str, op: int, ok: bool, note: str,
                   skipped: tuple[str, ...] = ()) -> None:
        """Record how a CLI call ended, without recording what it said.

        `note` is the provider's name on success and a failure reason on the way out.

        `skipped` is what the walk passed over on the way to an answer, and it is
        recorded because its absence is what made this defect unreadable from the trace.
        Every ask failure on the owner's machine — 11 of 11 — read `provider:null,
        reason:"timeout"`, and every success read one provider and nothing else; there
        was no third shape, so a fallback that fired and a first choice that answered
        were the same record. Categories rather than sentences, for the reason above.
        """
        self.diag.write(
            kind, op=op, ok=ok,
            ms=round((time.perf_counter() - self._cli_started) * 1000),
            provider=note if ok else None,
            reason=None if ok else self._failure_category(note),
            skipped=[self._failure_category(s) for s in skipped] or None,
        )

    def _provider(self) -> str:
        """Which agent CLI will answer, named *before* it is used.

        The notes already said which CLI answered, and the startup diagnostics say which
        one would — but between those two there was nowhere the app admitted, at the
        moment somebody is about to press Ask, that the question is leaving the machine.
        Naming it after the fact is a receipt, not a warning.

        The pin comes first, because the pin is what `_start_refine` and `_start_ask`
        hand to `refine`/`ask` — reading the preference order here named codex while
        claude answered, and printed that one line under a marker that had it right.
        A pin that is no longer on PATH is still named: `_invoke_any` does not
        second-guess an explicit `cli=`, so it is what gets run and what fails.

        `available()` is two PATH lookups and is only reached from note paths — a mode
        switch and the start of a CLI call — each of which is already paying for a user
        action or a process start; a pin skips even that.
        """
        cli = self._cli
        if cli is None:
            found = available()
            cli = found[0] if found else None
        return cli.name if cli is not None else ""

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

        False exactly while `_pump_audio` drains the device and throws every block away:
        a reply is playing, or the draft is being edited by hand. The distinction is not
        decoration — "busy, still listening" and "busy, and deaf" are different promises
        to the user, and only the second one means *stop talking*.
        """
        return not (
            (self.speaker is not None and self.speaker.speaking) or self.editing
        )

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
        # Before the speaking case, because both are deafnesses and only this one is the
        # user's own doing: told "not listening" with no reason, somebody typing would
        # read it as a fault.
        if self.editing:
            return Activity("editing - not listening", False)
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

    def _say_exits(self) -> None:
        """Name the ways out that still work — once per draft, and never for no draft.

        The four fixes the long-draft incident produced share one principle: a draft must
        never disable its own exits. This is the one that only has to *say* something,
        because the exits were all still there — the send hotkey worked the whole time and
        had been named once, at startup, in a console.

        Nothing is said with an empty draft. There is nothing to rescue, and a warning
        about a draft that does not exist is the noise that teaches people to ignore the
        real one. The latch is what keeps a burst of ticks to a single note; it clears in
        `_pump_health` the moment the draft is empty again.
        """
        if self._said_exits or not self.draft.text:
            return
        self._said_exits = True
        self._emit("note", exits_note(self.hotkeys))

    def _pump_health(self) -> None:
        """Long-session upkeep (R8): overflow, device liveness, idle model unload."""
        now = time.perf_counter()
        if not self.draft.text:
            self._said_exits = False
        self._pump_overflow()

        if now - self._last_mic_check >= MIC_CHECK_SEC:
            self._last_mic_check = now
            if self._mic_started and not self.mic.active:
                self._emit("note", "input device went away — restarting capture")
                try:
                    self.mic.restart()
                except Exception as exc:
                    self.diag.write("device", ok=False, reason="reopen-failed")
                    self._emit("error", f"could not reopen the mic: {exc}")
                else:
                    self.diag.write("device", ok=True, reason="reopened")
                    # A device that went away is often replaced by a different one —
                    # the USB mic is unplugged and the laptop array takes over — and
                    # the reopened stream is calibrated for neither.
                    self._check_calibrated_device()

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

        # The other way voice dies, written as a *state* rather than as a callback on the
        # unload above: that branch refuses to unload while a draft is held, so it cannot
        # produce this itself. What matters to the person holding the draft is that there
        # is nothing left to decode their rescue with, whatever took the models away.
        if not getattr(self.asr, "loaded", True):
            self._say_exits()

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
            self.diag.write("overflow", n=lost, ms=round(seconds * 1000),
                            dropped=self.mic_dropped)
            self._emit(
                "note",
                f"microphone overflowed — about {amount} of audio was lost while the "
                "UI was held",
            )
            # Beside the loss rather than instead of it. Invariant 4 owns "how much audio
            # went"; this answers the question the user asks next, which is what is left.
            self._say_exits()
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

        # The same half-duplex bargain, for the other reason someone can be at the
        # keyboard rather than at the microphone: whatever the room says while the user
        # types would be appended to the very text they are typing. Announced when it
        # starts and when it ends (`begin_edit`), because invariant 4 forbids a silent
        # deafness, not a deliberate one.
        if self.editing:
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
        self._utterance_id += 1
        record = Utterance(self._utterance_id, audio, self._capture_generation)
        # Kept only so the *bounded* tail is inspectable — the record that matters travels
        # with the work. `_sent` exists for the tests and for a reader trying to follow an
        # id through a log, and it is capped for R8: a long session must cost what a short
        # one costs, and an unbounded list of every utterance ever spoken is a recording.
        self._sent.append(record)
        self._last_audio = audio
        # The send words are deliberately *not* handed to the decoder. Biasing toward
        # them made it produce them: 6 of 280 short clips decoded to exactly "boom" —
        # references "MM HMM", "UM", "YEAH THAT'S COOL" — and a whole-utterance match is
        # a Send. `flow/asr.py` carries the measurement. `_note_near_miss` below is the
        # part that survives, because it reads what the decoder said unprompted.
        self.worker.submit_final(audio, record)
        self._utter = []
        self._decoded_sec = 0.0

    def _pump_decodes(self) -> None:
        for kind, text, elapsed, confidence, utterance in self.worker.results():
            self.diag.write("decode", route=kind, ms=round(elapsed * 1000))
            if kind == "error":
                self._emit("error", text)
            elif kind == "partial":
                # Only non-empty: a partial that clean.py filtered to nothing would
                # otherwise pop an empty bubble open on screen.
                if text:
                    self._emit("partial", text)
            elif kind == "rescue":
                self._finish_rescue(text, utterance)
            elif text:
                self._route(text, confidence, record=utterance)
            else:
                # The utterance decoded to nothing — silence, noise, or a hallucination
                # that clean.py rejected. Without this the state machine stays on
                # LISTENING and the pill sits there green with nothing happening.
                self._after_draft_change()

    # -- routing -----------------------------------------------------------

    def _route(self, utterance: str, confidence: float | None = None,
               record: Utterance | None = None) -> None:
        """Decide what a completed utterance means, given whether a draft is held.

        `confidence` is recorded and nothing else. The router has always chosen between
        a local edit and a ~7 s CLI call without knowing how well the decoder heard the
        sentence it was choosing about — and the live sheet turned 2 of 33 spoken
        commands into garbled semantic instructions. A gate on this number was declined
        for want of a real distribution to set it from; this is where that distribution
        comes from. Default None so the callers that are not a decode (a replay, a test,
        a rescue) do not have to invent a reading.

        `record` is the utterance this text was decoded *from*, and it is what makes the
        rescue path honest: `_remember_append` used to read `_last_audio`, a slot the next
        utterance overwrites, so a slow decode left the rescue pointing at somebody else's
        sound. Also None for the callers that are not a decode — a replay routes text that
        never had audio, and inventing an identity for it would be worse than admitting
        there is none.
        """
        if record is not None and record.generation != self._capture_generation:
            # Spoken before a pause the user chose. The draft on screen belongs to the
            # session they started afterwards, and folding an older utterance into it is
            # the same defect as the un-drained mic queue arriving by a slower road.
            self._emit("note", "dropped what was said before the pause")
            return
        # Consumed here, before any early return, and expired by age. The chip is
        # pressed *for the utterance the user is about to say*; leaving it set when
        # that utterance takes another path meant it silently applied to a later,
        # unrelated one — the user pressed Refine, said something that started a fresh
        # draft, and then a minute later had an ordinary sentence routed to the CLI.
        forced = self._take_force_next()

        # Traced at every exit rather than once at the top, because the kind is not
        # known until the branch is taken. A single call after the early returns is
        # what the first version did, and it left the commonest route of all — the
        # first sentence into an empty draft — recorded nowhere.
        def trace(kind: str) -> None:
            # Rounded: `avg_logprob` arrives with a dozen decimals and the fourth of
            # them cannot separate a decode that was heard from one that was guessed.
            # Only a real number is rounded, and anything else is passed on untouched
            # to be refused by the writer — `round()` on a string raises, and this runs
            # on the UI thread inside the router, where a diagnostics line that can
            # raise takes the commonest path in the app down with it.
            score = (round(confidence, 3) if isinstance(confidence, (int, float))
                     else confidence)
            self.diag.write("route", route=kind, chars=len(utterance), confidence=score)

        # The two thread verbs are the only commands that mean anything with an empty
        # draft — which is precisely the state Send leaves behind.
        thread_plan = plan(utterance, self.draft.text, self.send_words)
        if thread_plan.kind == "send_trigger":
            # Asked for, not done here. In dictate mode the paste belongs to the UI
            # thread, which is the only place that knows which window Send is aimed at —
            # so the trigger presses the same button the chip does, down to the refusals,
            # rather than growing a second Send that would have to be kept in step.
            trace("send_trigger")
            if thread_plan.op == "enter" and self.mode == CONVERSE:
                # Converse pastes nothing, so there is nothing for an Enter to submit.
                # Said rather than silently ignored: a suffix that sometimes does
                # something and sometimes does not, with no signal either way, is how a
                # user learns to distrust the one that does.
                self._emit("note", "converse mode - asking; nothing to submit here")
            self._emit("send", thread_plan.op)
            return
        self._note_near_miss(utterance)
        if thread_plan.kind == "recall":
            trace("recall")
            self._recall()
            return
        if thread_plan.kind == "take":
            # Also meaningful with an empty draft — which is precisely the state an
            # answer arrives into, since asking clears the question.
            trace("take")
            self.take_reply()
            return
        if thread_plan.kind == "followup":
            trace("followup")
            self._start_followup(thread_plan.payload, record)
            return
        if thread_plan.kind == "note":
            # P9. Meaningful with an empty draft for the same reason `take` is: an answer
            # arrives into one, and keeping the answer is what the verb is mostly for.
            trace("note")
            self.keep_note(thread_plan.payload)
            return
        if thread_plan.kind == "wrap":
            trace("wrap")
            self.wrap_up()
            return

        if not self.draft.text:
            trace("append")
            self.draft.append(utterance)
            self._remember_append(utterance, record)
            self._after_draft_change()
            return

        if forced == "append":
            trace("append")
            self.draft.append(utterance)
            self._remember_append(utterance, record)
            self._after_draft_change()
            return

        # The same triggers as the thread pass above. Two `plan()` calls with different
        # arguments is how a renamed trigger word turned "boom" into a `send_trigger`
        # here that nothing handled, and `_escalate` then started a ~7 s CLI call on an
        # empty instruction.
        p = plan(utterance, self.draft.text, self.send_words)
        trace(p.kind)
        if forced == "edit" and p.kind == "append":
            # The user explicitly said "this is an instruction", so honour that over
            # the heuristic and let the CLI interpret whatever they asked for.
            p = type(p)("semantic", payload=utterance)

        if p.kind == "rescue":
            self.rescue_last_append()
            return
        if p.kind == "append":
            self.draft.append(utterance)
            self._remember_append(utterance, record)
        elif p.kind == "undo":
            # P8: an undo that lands straight on top of an append is the signature of
            # a command the router read as dictation. Recorded before the undo, since
            # undoing is what clears the evidence.
            if self.profile is not None and self._last_append is not None:
                self.profile.note_misroute(self._last_append.text)
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
                self._emit("edit", describe_change(p, before, new))
            else:
                # Asked for something we could not do locally — escalate rather than
                # silently no-op, which would read as the app ignoring the user.
                self._start_refine(utterance)
                return
        elif p.kind == "send_trigger":
            # Unreachable via the pass above, which returns on it — kept because
            # `_escalate` is the `else` here, and a trigger arriving in it would spend
            # ~7 s of CLI on an empty instruction. That is not hypothetical: it is what
            # the second `plan()` call did while it was still using the default words.
            self._emit("send", p.op)
            return
        else:
            self._escalate(p, record)
            return

        self._after_draft_change()

    def undo_edit(self) -> bool:
        """Take back the edit the note above the draft is describing.

        The way back, beside the fact — the design pass asked for both in the same
        breath (decisions.md 2026-08-09): *the user needs the fact and the way back*. A
        note saying `changed “thursday” to “Tuesday”` is only half an answer if the only
        way to disagree with it is to say "undo" and hope the router hears that one
        correctly, which is precisely the situation somebody is in when a correction has
        just gone wrong.

        Not `_route`'s undo branch, deliberately, and the difference is what P8 learns.
        A *spoken* undo landing on an append is evidence the router read a command as
        dictation, so that path records a misroute. This is a button on a note about an
        edit Flow already made — there is no misreading to learn from, and counting one
        would teach the profile to distrust an opening the user never spoke.
        """
        if not self.draft.undo():
            self._emit("note", "nothing to undo")
            return False
        # The note described an edit that no longer stands.
        self._emit("note", "")
        self._after_draft_change()
        return True

    def recall(self) -> None:
        """P6: put the last sent prompt back, by button rather than by voice.

        The bubble's "Bring it back" chip after a Send, and the spoken "bring back my last
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

    def _note_near_miss(self, utterance: str) -> None:
        """Say when something almost was the send word, and never act on it.

        Root 5's second half. The trigger fails every voice but the owner's *silently*:
        the match is exact whole-utterance equality, so a miss lands in the draft as
        text and the user's evidence that the feature exists at all is that nothing
        happened. The reference shares this flaw — an unrecognised spoken command types
        itself, quietly — and this note is the one point where Flow is better than it.

        **Notify, never execute.** Letting edit distance fire a send is a standing
        refusal: a send is irreversible in dictate mode (it pastes into somebody else's
        window and presses nothing back), and the whole grammar is built on the
        asymmetry that a wrong *edit* costs one undo while a wrong *send* costs a
        paragraph in a stranger's terminal. So the exact-match rule stands untouched and
        this only speaks.

        Two words at most, because that is the shape a trigger has. A longer utterance
        that happens to score is a sentence, not a mis-heard word.
        """
        if len(utterance.split()) > 2:
            return
        best, word = 0.0, ""
        for configured in self.send_words:
            score = similarity(utterance, configured)
            if score > best:
                best, word = score, configured
        if best < NEAR_MISS_SIMILARITY or not word:
            return
        self.diag.write("route", route="near_miss")
        self._emit("note", f"that sounded like “{word}”, which sends the draft — "
                           f"say it on its own if that is what you meant")

    @property
    def send_words(self) -> tuple[str, str]:
        """The two spoken triggers: (Send, Send-then-Enter).

        From the profile when there is one, and from the shipped defaults otherwise —
        `--no-profile` has to keep working, and so does a first run.
        """
        if self.profile is None:
            return (SEND_WORD, SEND_ENTER_WORD)
        return (getattr(self.profile, "send_word", SEND_WORD),
                getattr(self.profile, "send_enter_word", SEND_ENTER_WORD))

    @property
    def workspace(self) -> str | None:
        """The project a converse question is asked from, as this session resolved it.

        Read by the generated help sheet, which has to name the workshop the CLI is
        actually being run in. Re-deriving it from the profile would be wrong on the one
        run where it matters: `--cwd` wins over the stored value and never reaches the
        file, so a sheet that consulted `profile.workspace` would print a path this
        session is not using.
        """
        return self._refine_cwd

    def _workspace_leaf(self) -> str:
        """The workspace's own name, cut to WORKSPACE_LEAF_MAX. "" when none is set."""
        if not self._refine_cwd:
            return ""
        # A drive root has an empty `.name`; the path itself is the only name it has.
        leaf = Path(self._refine_cwd).name or self._refine_cwd
        if len(leaf) > WORKSPACE_LEAF_MAX:
            leaf = leaf[: WORKSPACE_LEAF_MAX - 1] + "…"
        return leaf

    def set_workspace(self, path: str | None) -> bool:
        """Switch the project questions are asked from, mid-session. True if it moved.

        A workspace switch is a topic switch (decisions.md "Workspace grounding"):
        the thread is cleared and the note says both things in one line, because
        carrying one project's conversation into another project's grounding is the
        contamination the switch exists to end. The refusals are the honest edges,
        each with its own sentence:

        - the **same** workspace, by path identity rather than spelling, is a no-op —
          the one tap that clears a conversation is one that changes the ground;
        - a folder that is **gone** is refused with the reason and switches nothing —
          `resolve_workspace`'s stale-path honesty, at the menu instead of startup;
        - an **ask in flight** refuses the way send() does: `_pump_ask` records the
          answer as a turn and its op id would still match, so the old project's
          reply would land as the first turn of the new project's thread.

        The draft is deliberately untouched (R5): the words are the user's, whatever
        ground they stand on. Persisted like the trigger word — on the tap, because a
        choice made just before closing the app is still a choice — and a save that
        fails is said, since next launch would then ground the old project, which is
        exactly the trap this exists to end.
        """
        path = (path or "").strip() or None
        if path_key(path) == path_key(self._refine_cwd):
            return False
        if path is not None and not Path(path).is_dir():
            self.diag.write("workspace", ok=False, reason="missing")
            self._emit("note", f"workshop: {path} no longer exists - keeping "
                               f"{self._workspace_leaf() or 'no workspace'}")
            return False
        if self._ask_op is not None:
            self._emit("note",
                       "still waiting on the last answer - switch after it lands")
            return False
        self._refine_cwd = path
        self.thread.clear()
        self.diag.write("workspace", ok=True)
        self._emit("note",
                   f"workshop: {self._workspace_leaf() or 'not set'} — new conversation")
        if self.profile is not None:
            self.profile.workspace = path
            if path is not None:
                self.profile.note_workspace(path)
            if not self.profile.save():
                self._emit("note", f"could not save {self.profile.path} - "
                                   "the switch lasts this session only")
        return True

    @property
    def can_take_reply(self) -> bool:
        """True when there is an answer on screen to move into the draft."""
        return bool(self.reply)

    def take_reply(self) -> bool:
        """P9's promised verb: the answer becomes the thing Send hands over.

        The workshop loop — discuss, refine, send the good version to the terminal —
        dead-ended here. `send()` hands over the *draft*, and the refined prompt is in
        the *reply*, so the only way across was to re-type it.

        **Replace, never append.** An answer is a whole thing, and gluing it onto a
        half-written question makes a third thing nobody asked for. `_recall` appends
        because a recalled prompt is *more of the same request*; this is not that. Undo
        is what makes replacing safe, and the note names what was displaced.
        """
        if not self.reply:
            self._emit("note", "no answer to take yet")
            return False
        # Reaching for the text is "I have what I need" — the same interrupt Clear uses.
        self.stop_speaking()
        displaced = self.draft.text
        self.draft.set(self.reply)
        # Staying in converse would make the next Send re-ask Flow's own answer back at
        # the CLI, which is the confusion this verb exists to remove. The flip is said
        # out loud because it changes what the button under the user's cursor does.
        was = self.mode
        self.mode = DICTATE
        if was != DICTATE:
            self._emit("mode", DICTATE)
        self._emit(
            "note",
            ("took the answer - Send now pastes it" if not displaced
             else "took the answer, replaced the draft - Send now pastes it "
                  "(one undo brings your text back)"),
        )
        self.diag.write("take", chars=len(self.reply), mode=was)
        # Deliberately *not* `_after_draft_change()`. That is what settles a draft, and a
        # settled converse draft is what the countdown fires on — so the whole guard
        # would be the trap it exists to prevent: converse auto-asking Flow's own answer
        # straight back at the CLI. A taken draft is not an utterance somebody finished.
        self._settle_state()
        self._settled_at = None
        self._emit("draft", self.draft.text)
        return True

    def keep_note(self, text: str = "") -> bool:
        """P9: file something worth keeping. True when a note was actually kept.

        Two callers, two meanings, and the argument is which one:

        - **`text` given** — the speaker dictated the note. Kept as it was said, with no
          question above it, because it stands on its own.
        - **`text` empty** — the bare verb, which keeps *the exchange on screen*: the
          answer and the question that produced it. That pairing is the whole value. An
          answer filed without its question reads a week later as an assertion from
          nowhere, and the question is the thing somebody scanning the file navigates by.

        Refuses out loud rather than quietly doing nothing, the way `send()` does: a verb
        that sometimes works and sometimes is silent is one people stop trusting.
        """
        text = (text or "").strip()
        question = ""
        if not text:
            if not self.reply:
                self._emit("note", "nothing to keep yet - ask something first")
                return False
            text, question = self.reply, self._last_question
        dropped = self.notes.add(
            text, question=question, workspace=self._workspace_leaf()
        )
        n = len(self.notes)
        self.diag.write("note", kept=n, chars=len(text), exchange=bool(question))
        self._emit("note", f"kept - {n} note" + ("" if n == 1 else "s")
                   + " so far, say \"wrap up\" for the file")
        if dropped:
            # P2's rule, extended from dropped speech to dropped notes: it may happen,
            # it may not happen unexplained. Said second so the confirmation lands first.
            self._emit("note", f"the oldest {dropped} fell off - the buffer is full")
        return True

    def wrap_up(self) -> bool:
        """P9: the kept notes as one document, on screen and — with a workspace — on disk.

        **On screen always, and through the reply.** The conversation card already draws
        an answer, already carries Copy and Use this, and `take_reply` already moves one
        into the draft. Routing the document through the same slot means the notes are
        copyable and pasteable the moment they exist, with no new surface and no second
        rendering to keep in step.

        **A file only where the user already pointed Flow.** With no workspace there is
        no folder this app has any business choosing on somebody's behalf, so the notes
        stop at the screen and the note says so — which is Lite's answer to the same
        question (the last inch is the clipboard) rather than a degraded version of it.

        **The buffer is cleared only on success**, and never on a failed write: a full
        disk must cost a retry, not the notes.
        """
        held = self.notes.all
        if not held:
            self._emit("note", 'nothing kept yet - say "keep note" after an answer')
            return False
        leaf = self._workspace_leaf()
        doc = render_notes(held, workspace=leaf)
        where = self._refine_cwd
        if where:
            try:
                path = write_notes(doc, where)
            except OSError as exc:
                self.diag.write("wrap", ok=False, kept=len(held))
                self._emit("error", f"could not write the notes ({exc}) - "
                                    "they are still kept")
                return False
            self._emit("reply", doc)
            self.reply = doc
            self._emit("note", f"{len(held)} note"
                       + ("" if len(held) == 1 else "s") + f" written to {path}")
        else:
            self._emit("reply", doc)
            self.reply = doc
            self._emit("note", f"{len(held)} note"
                       + ("" if len(held) == 1 else "s")
                       + " on screen - Copy takes them (no workspace set, so no file)")
        self.diag.write("wrap", ok=True, kept=len(held), wrote=bool(where))
        self.notes.clear()
        return True

    def _start_followup(self, rest: str, record: Utterance | None = None) -> None:
        """P6: the next thing said continues the thread rather than starting over."""
        if not self.thread.last:
            # Nothing to follow, so this is just dictation with an odd opening.
            if rest:
                self.draft.append(rest)
                self._remember_append(rest, record)
            self._emit("note", "nothing sent yet - treating that as dictation")
            self._after_draft_change()
            return
        self.following_up = True
        if rest:
            self.draft.append(rest)
            self._remember_append(rest, record)
        self._emit("note", f"following up on {len(self.thread)} sent")
        self._after_draft_change()

    @property
    def recent(self) -> list[tuple[str, str]]:
        """The Recent menu's contents, newest first. In memory, never on disk."""
        return list(reversed(self._recent))

    def _remember_recent(self, role: str, text: str) -> None:
        """One entry, deduped against the one before it.

        The dedupe is not tidiness: a question is remembered when it is asked and the
        same words are already in the ring as the dictation they were built from, so
        without it every converse turn would fill two slots with one sentence.
        """
        text = text.strip()
        if not text or (self._recent and self._recent[-1] == (role, text)):
            return
        if self._recent and self._recent[-1][1] == text:
            # Same words, new role — the dictation just became a question. Replace
            # rather than append, so the ring holds one entry per thing that happened.
            self._recent[-1] = (role, text)
            return
        self._recent.append((role, text))

    def _remember_append(self, utterance: str, record: Utterance | None = None) -> None:
        """Keep the last dictation, with **its own** audio, for a reinterpretation.

        The audio comes from the record this text was decoded from, not from
        `_last_audio`. Those differ exactly when they matter: a decode slow enough for
        the next utterance to have been captured meanwhile is the case rescue exists to
        serve, and reading the slot paired the words with the wrong sound.
        """
        self._last_append = Append(utterance, record, self.draft.revision)
        self._remember_recent(RECENT_SAID, utterance)

    @property
    def can_rescue(self) -> bool:
        """True when there is a *just*-appended utterance to reinterpret.

        "Just" is the word that was missing. The draft must still be the one the append
        landed in, or the chip is offering to take back an utterance from text that has
        moved on — and every capture, edit, undo, send and clear moves the revision, so
        one comparison covers all of them.
        """
        return (
            self._last_append is not None
            and self._last_append.revision == self.draft.revision
            and bool(self.draft.text)
        )

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
        if not self.can_rescue or self._last_append is None:
            # `can_rescue` and not just "is there one": the chip is drawn from that
            # property, and a spoken "was a command" reaches here without passing it.
            # Two answers to one question is how the button and the grammar come to
            # disagree about what is possible.
            self._emit("note", "nothing to re-read")
            return False
        appended = self._last_append
        utterance, audio = appended.text, (
            appended.record.audio if appended.record is not None else None
        )
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
                self._emit("edit", f"re-read — {describe_change(p, before, new)}")
                self._after_draft_change()
                return True

        if audio is not None and self._post_hoc is None:
            # The words as transcribed are not a command either, so ask the decoder
            # again with the command vocabulary in hand.
            #
            # The revision is taken *after* the undo, because that is the draft this
            # rescue is being computed against — the target of a correction is in the
            # text as it was when the command was spoken.
            self._post_hoc = Rescue(utterance, appended.record, self.draft.revision)
            self._emit("note", "re-listening to that as a command")
            self.worker.submit_rescue(audio, command_bias(self.draft.text),
                                      appended.record)
            return True

        self._give_back(utterance, "could not re-read that as a command", audio)
        return False

    def _give_back(self, utterance: str, note: str,
                   audio: np.ndarray | None = None) -> None:
        """Put a withdrawn utterance back. The user's words are never the price of a
        failed guess.

        The audio goes back with them. Re-reading `_last_audio` here would hand the
        restored utterance whatever was captured most recently, so a second "Was a
        command" on the same words would re-decode a different sentence — the original
        defect, reached through the recovery path for it.
        """
        self.draft.append(utterance)
        self._last_append = Append(
            utterance,
            Utterance(-1, audio, self._capture_generation) if audio is not None else None,
            self.draft.revision,
        )
        self._emit("note", note)
        self._after_draft_change()

    def _escalate(self, p, record: Utterance | None = None) -> None:
        """A semantic plan. Try one cheap re-decode first, if it might be a mis-hearing.

        `escalated` means the shape was a correction but the target was nowhere in the
        draft — which is far likelier to be a mis-heard word than a request for
        judgement. A second decode biased toward the trigger verbs and the draft's own
        words costs about a second; the CLI costs seven and will be asked to edit text
        that does not contain the word.

        The re-decode is of `record`'s audio — the utterance this plan came from — for
        the same reason `_remember_append` takes one. Asking the decoder to re-listen to
        whatever was captured most recently is the version of this that sounds right and
        re-reads a different sentence.
        """
        if p.op == "polish":
            # A named request for a specific transformation, not an instruction to be
            # interpreted — and never a mis-hearing to re-listen for.
            self._start_refine(p.payload, polish=True)
            return
        audio = record.audio if record is not None else self._last_audio
        if p.escalated and audio is not None and self._pending_rescue is None:
            self._pending_rescue = Rescue(p.payload, record, self.draft.revision)
            self._emit("note", f"re-listening for {p.target!r}")
            self.worker.submit_rescue(audio, command_bias(self.draft.text), record)
            return
        self._start_refine(p.payload)

    def _answers(self, pending: Rescue, record: Utterance | None) -> bool:
        """Is this result the one `pending` is waiting for, against the draft it saw?

        Two questions, and they fail differently. A **different utterance** means the
        result is somebody else's answer — item 52's ids, spent here. A **moved draft**
        means it is the right answer to a question about text that no longer exists: the
        target of a correction is in the draft the command was spoken against, and
        applying it to whatever is there now is how a stale rescue rewrites text it never
        saw.
        """
        if pending.record is not None and (record is None
                                           or record.id != pending.record.id):
            return False
        return pending.revision == self.draft.revision

    def _finish_rescue(self, text: str, record: Utterance | None = None) -> None:
        """The biased re-decode came back. Accept it only if it beats the first read."""
        if self._post_hoc is not None:
            pending, self._post_hoc = self._post_hoc, None
            if not self._answers(pending, record):
                # The words are still withdrawn — `rescue_last_append` ran `undo` before
                # submitting — so they go back. `_give_back`'s bargain is that the user's
                # words are never the price of a failed guess, and a guard is a kind of
                # failed guess: it is Flow declining to act, not the user changing
                # their mind.
                self._give_back(pending.payload, "the draft moved - put that back",
                                pending.record.audio if pending.record else None)
                return
            p = plan(text, self.draft.text) if text else None
            if p is not None and p.kind == "local":
                before = self.draft.text
                new, applied = apply_local(before, p)
                if applied:
                    self.draft.set(new)
                    self._emit("edit",
                               f"re-read — {describe_change(p, before, new)}")
                    self._after_draft_change()
                    return
            self._give_back(pending.payload, "could not re-read that as a command",
                            pending.record.audio if pending.record else None)
            return

        pending, self._pending_rescue = self._pending_rescue, None
        if pending is None:
            return  # a rescue nobody is waiting for; ignore rather than act on it
        if not self._answers(pending, record):
            # Nothing was withdrawn on this path, so dropping it costs the user nothing
            # and the draft is already what they want. Starting the CLI fallback instead
            # would send an instruction computed against text that has since changed —
            # a ~7 s call whose answer is wrong before it is asked.
            self._emit("note", "the draft moved - dropped that re-read")
            return
        p = plan(text, self.draft.text) if text else None
        if p is not None and p.kind == "local":
            before = self.draft.text
            new, applied = apply_local(before, p)
            if applied:
                self.draft.set(new)
                self._emit("edit", f"re-heard — {describe_change(p, before, new)}")
                self._after_draft_change()
                return
        # The second read did not find a command either. The CLI was always the
        # fallback; it just costs a second more than it used to.
        self._start_refine(pending.payload)

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
        the gate is open, audio is waiting to be decoded, a decode is running, the
        previous answer is still playing — during which the microphone is gated, so
        silence proves nothing about the user — or somebody is typing into it.

        The editor is the sharpest of them and the reason the clause is not a `state`
        check either. It commits once, on close, so while it is open the session sees a
        settled draft *and* guaranteed silence: exactly the two conditions this reads as
        "finished", against a sentence that is half-typed.

        The two CLI clauses ask the calls themselves rather than reading `state`. That
        is the whole defect this pins: routing overwrote REFINING with DRAFT, the
        countdown re-armed against a draft a rewrite was still out on, and the question
        went unrewritten with no press.
        """
        return (
            self.auto_ask
            and self.mode == CONVERSE
            and not self.editing
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

    # -- repairing the text by hand ----------------------------------------

    def begin_edit(self) -> str | None:
        """Take the draft into a keyboard editor. Returns the text to put in it.

        None means the editor was refused and a note says why — the same shape `send()`
        uses, so a caller that ignores the return value cannot silently open two.

        This exists because the only repair Flow offered was saying it again, into the
        decoder that got it wrong the first time. For a speaker whose accent is what the
        decoder is struggling with, that is a loop with no exit, and the live sheet
        scored 55/73/55% against P3's >= 95%.
        """
        if self.editing:
            self._emit("note", "already editing - finish or cancel that first")
            return None
        if self._utter:
            # Words captured before the editor opened are the user's, exactly as they
            # are when a reply starts playing. They will land behind the editor and be
            # displaced by the commit, which `commit_edit` says out loud — and the undo
            # stack holds words, so displaced is not lost.
            self._finalise()
        self.editing = True
        self._edit_revision = self.draft.revision
        self.diag.write("edit", ok=True, chars=len(self.draft.text))
        self._emit("note", "editing - the microphone is off while you type")
        return self.draft.text

    def commit_edit(self, text: str) -> None:
        """Close the editor, writing `text` into the draft."""
        if not self.editing:
            return
        self.editing = False
        moved = self.draft.revision != self._edit_revision
        if text != self.draft.text:
            # Through `Draft.set()`, which is what makes this an ordinary draft change:
            # the revision moves, so a rewrite in flight across the edit is discarded by
            # the invariant-11 check rather than overwriting what was typed, and the
            # previous text goes on the undo stack for free.
            self.draft.set(text)
            self._emit("note", "edited by hand - listening again"
                       + (" (what arrived while you typed is one undo back)"
                          if moved else ""))
            self._after_draft_change()
        else:
            self._emit("note", "listening again - nothing was changed")
        self.diag.write("edit", ok=True, chars=len(text), route="commit")

    def paste_draft(self, text: str) -> str:
        """Start from something already written: the clipboard becomes the draft.

        Three outside users went looking for this and did not find it (decisions.md
        2026-08-03). Every way into a draft was speech, which is exactly wrong for the
        first thing somebody does with a dictation tool they have just installed — they
        have a paragraph in front of them and want to work on it, not compose one.

        `Draft.set` is the whole implementation and that is the point: the undo snapshot,
        the revision bump and the invariant-11 discard of any rewrite in flight all come
        with it. Refused while the editor is open, for the same reason a spoken result is
        held back there: the draft is two things at once until the box closes.

        Returns "" on success, or the reason it refused. A **returned** reason rather
        than an emitted note, because the caller is the only thing that knows whether
        there is a window on screen to put a note on — and this runs with an empty draft
        and a hidden bubble, which is the state it exists for.
        """
        text = (text or "").strip()
        if not text:
            return "nothing on the clipboard to start from"
        if self.editing:
            return "finish or cancel the edit first"
        self.draft.set(text)
        self._remember_recent(RECENT_SAID, text)
        self._emit("note", f"started from the clipboard - {len(text)} characters, "
                           "one undo back")
        self._after_draft_change()
        self.diag.write("edit", ok=True, chars=len(text), route="paste")
        return ""

    def cancel_edit(self) -> None:
        """Close the editor and keep the draft exactly as it was."""
        if not self.editing:
            return
        self.editing = False
        self._emit("note", "editing cancelled - listening again")
        self.diag.write("edit", ok=False, route="cancel")

    @property
    def cli(self):
        """The pinned agent CLI, or None when the preference order is being walked."""
        return self._cli

    def set_cli(self, cli) -> None:
        """Choose which agent CLI to use, mid-session.

        Pinning is what makes a slow or wedged CLI recoverable without a restart: the
        fallback below only runs *after* the first one has failed, which for a timeout
        costs the full wait before the second is even tried. Someone who already knows
        which one is answering should not have to pay that on every call.
        """
        self._cli = cli
        self._emit("note", f"agent CLI: {cli.name}" if cli is not None
                   else "agent CLI: automatic, in preference order")

    def toggle_auto_ask(self) -> bool:
        self.auto_ask = not self.auto_ask
        # Saved now rather than at the next Send, for the reason `set_voice` gives: this
        # is a choice about how someone wants to work, and one made just before closing
        # the app is still a choice.
        if self.profile is not None:
            self.profile.auto_ask = self.auto_ask
            self.profile.save()
        self._emit("note", "auto-ask on - a pause sends the question"
                   if self.auto_ask else "auto-ask off - press Ask when you are ready")
        return self.auto_ask

    def _pump_auto_ask(self) -> None:
        if not self._auto_ask_armed():
            return
        if time.perf_counter() - self._settled_at < AUTO_ASK_SEC:
            return
        # The countdown's final state carries the ground too: auto-ask is the one
        # path where words leave with no press, so its firing note is the last thing
        # standing between a stale workspace and a question asked from it.
        where = self._workspace_leaf()
        self._emit("note", f"no more speech - asking · {where}" if where
                   else "no more speech - asking")
        self.send()

    # -- semantic refine (off-thread: ~7 s measured) ------------------------

    def _start_refine(self, instruction: str, *, polish: bool = False) -> None:
        if self._refine_op is not None:
            # The refusal `send()` already makes, for the same reason. Two rewrites of
            # one draft race to write it, and the loser's words are the user's.
            self._emit("note", "still rewriting — say that again when it lands")
            return
        op = self._refine_op = self._next_op()
        self.diag.write("refine", op=op, chars=len(self.draft.text),
                        sent=tail_sent(self.draft.text),
                        route="polish" if polish else "semantic")
        self._cli_started = time.perf_counter()
        # The version this rewrite is an answer about. The draft stays editable for
        # the whole ~7 s the CLI takes, so the result has to be checked against it.
        revision = self.draft.revision
        self._settle_state()
        who = self._provider() or "no CLI on PATH"
        self._emit(
            "note",
            f"shaping that into a prompt via {who}" if polish
            else f"refining via {who}: {instruction!r}",
        )
        before = self.draft.text
        sent = tail_sent(before)
        if sent < len(before):
            # R11 caps what the CLI is handed, and from outside the cap looks like the
            # CLI ignoring most of the request: ask for a long draft to be shortened
            # and only its ending comes back shorter. The head is reattached verbatim,
            # so "left as it is" is a promise rather than a hedge.
            self._emit(
                "note",
                f"only the last {sent} characters went to the CLI — "
                "the text before that is left as it is",
            )

        context = self.thread.tail() if self.following_up else []

        def work() -> None:
            passed_over: list[str] = []
            result = refine(
                before, instruction, cwd=self._refine_cwd, polish=polish,
                context=context, cancel=self._cancel,
                cli=self._cli, timeout=self._cli_timeout,
                skipped=passed_over,
            )
            with self._refine_lock:
                self._refine_result = (op, revision, result, tuple(passed_over))

        threading.Thread(target=work, daemon=True, name="refine").start()

    def _pump_refine(self) -> None:
        with self._refine_lock:
            pending, self._refine_result = self._refine_result, None
        if pending is None:
            return
        op, revision, (revised, note), skipped = pending
        if op != self._refine_op:
            # A result for a call nobody is waiting on any more — the same rule as a
            # rescue nobody asked for: ignore it rather than act on it.
            return
        self._refine_op = None
        self._trace_cli("refine", op, revised is not None, note, skipped)
        if revised is None:
            self._emit("error", f"refine failed ({note}) — draft unchanged")
        elif revision != self.draft.revision:
            # A rewrite of text that no longer exists. Applying it would delete
            # whatever was said while the CLI was thinking, and would do it invisibly,
            # because what replaced the draft reads like a plausible draft.
            self.diag.write("stale", op=op, route="refine")
            self._emit("note", "discarded a stale rewrite — the draft moved on")
        else:
            self.draft.set(revised)
            self._emit("note", f"refined via {note}" if not skipped
                       else f"refined via {note}, after {'; then '.join(skipped)}")
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

    def _first_converse_notice(self) -> None:
        """Say once, on screen, that a pause sends the question.

        Auto-ask stays ON (decisions.md 2026-08-03, part 4) because the card now pins
        the question, so a premature send costs nothing. The bargain that makes that
        defensible is that the first entry says so — and the reopen bar is one stranger
        reporting a surprise send, which is a report only somebody who was never told
        can make.

        With `--no-profile` there is nothing to remember it in, so it is shown on every
        entry rather than never. A session with no profile is a session that has also
        forgotten the calibration and the trigger word; being told twice about auto-ask
        is the cheapest of those costs, and the alternative is a warning that a
        `--no-profile` user never receives.
        """
        if self.profile is not None and self.profile.converse_seen:
            return
        self._emit("note", auto_ask_notice(AUTO_ASK_SEC))
        if self.profile is not None:
            self.profile.converse_seen = True
            self.profile.save()

    def new_conversation(self) -> None:
        """Start again: the thread, the reply and the card, in one act.

        Root 4's other half. `Clear draft` cleared the draft and left the thread, the
        reply and the mode alive, so "clear prompt did not start fresh" was exactly
        right — a new conversation was three separate actions and one of them did not
        exist anywhere. The UI clears its own card off the back of this call.

        **The draft is deliberately untouched**, which is `toggle_mode`'s argument
        reused: words already spoken belong to the speaker whatever surface they were
        heading for, and somebody who says "new conversation" mid-sentence has not asked
        to lose the sentence. `Clear draft` is still the thing that clears a draft.

        An answer still in flight is cancelled at the operation id rather than waited
        for: it belongs to a conversation that no longer exists, and `_pump_ask` drops a
        result whose op has moved.
        """
        self.thread.clear()
        self.reply = ""
        self._ask_op = None
        self._emit("conversation", "")
        self._emit("note", "new conversation")

    def toggle_mode(self) -> str:
        """P9: one action switches dictate <-> converse. Returns the new mode.

        Deliberately does not touch the draft. Someone who has dictated three sentences
        and then decides they want to ask about them rather than paste them should not
        have to say it again — the words are the same words either way.
        """
        self.mode = CONVERSE if self.mode == DICTATE else DICTATE
        # The one clearing the revision cannot do, because this deliberately does
        # not touch the draft. Asking about words is a different intent from having
        # mis-dictated them, and the chip should not survive the change of mind.
        self._last_append = None
        self._emit("mode", self.mode)
        # Named after the button that is actually on screen. This used to say "Send asks
        # the CLI" while the chip renamed itself to "Ask", so the app announced one verb
        # and displayed another — and the first person to read both concluded the mode
        # had not really changed. In converse mode there is no Send anywhere; saying so
        # is free, and the same class of defect as the chip whose label the grammar
        # rejected.
        if self.mode == CONVERSE:
            who = self._provider()
            # Names the provider and says what that means, in the one sentence somebody
            # reads when they switch. "the CLI" was true and told nobody anything: the
            # point is not which executable runs, it is that the words go off the
            # machine to whatever that executable is signed into.
            # And where it is asked *from*. Naming the workspace on every switch is what
            # pays for the risk the owner accepted when they chose an explicit path over
            # a guessed one: a workspace set months ago goes stale silently, so the
            # mitigation has to be that it is on screen rather than that it is clever.
            where = (f", grounded in {self._refine_cwd}" if self._refine_cwd
                     else ", with no project behind it")
            self._emit("note",
                       f"converse mode - Ask sends the draft to {who}, and the question "
                       f"leaves this machine{where}"
                       if who else
                       "converse mode - no agent CLI on PATH, so Ask has nothing to send")
            self._first_converse_notice()
        else:
            self._emit("note", "dictate mode - Send copies the draft, and you paste it"
                       if self.lite
                       else "dictate mode - Send pastes into the focused window")
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
            # Named for the button that was pressed and for what is on screen while it
            # says this. In converse the chip reads **Ask**, and the card behind it is
            # showing the question, its answer and the turns before them — so "nothing to
            # send - the draft is empty" was three names for two things, and it read as
            # Flow denying the conversation it was displaying. Reported that way on
            # 2026-08-06: "even though there is context". The draft really was empty; the
            # sentence was talking about the wrong object.
            self._emit("note",
                       "nothing to ask - say a question first" if self.mode == CONVERSE
                       else "nothing to send - the draft is empty")
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
        # Decided from the request, before the answer exists to bias the guess. The
        # flag outlives the call because the *speaker* needs it when the answer lands.
        artifact = self._ask_artifact = is_artifact_request(question)
        # Framed here rather than in `refine.ask`, so the notes and the trace stay
        # measurements of what the *user* said: `question` is their words.
        #
        # Cut to fit *before* handing it over, and that is a defect fix rather than
        # tidiness. `ask()` keeps the tail of an over-long input and walks the cut
        # forward to a sentence boundary — so with a long question containing no
        # punctuation, the first boundary it finds is inside the framing, and the cut
        # takes the whole question and half the preamble with it. Measured exactly that
        # way: a 5 000-character question arrived at the CLI as two sentences of
        # instructions and none of the prompt. Keeping the framed string inside
        # `MAX_CHARS` makes that split a no-op, so the framing is intact by construction
        # rather than by luck.
        framing = ask_framing(self._refine_cwd)
        budget = max(0, REFINE_MAX_CHARS - len(framing))
        kept = question if len(question) <= budget else question[-budget:]
        framed = kept + framing

        self._remember_recent(RECENT_ASKED, question)
        # Recorded from the *user's* words, like the note and the trace above it, and
        # before the answer exists: this is what a kept exchange is headed with, and a
        # heading naming the framed string would name a sentence nobody said.
        self._last_question = question
        self.diag.write("ask", op=op, chars=len(question),
                        sent=len(kept), mode=self.mode, artifact=artifact)
        self._cli_started = time.perf_counter()
        self._set_state(State.ASKING)
        # The moment of egress names the ground. The startup line and the mode-switch
        # note both name the workspace and both had scrolled away by the time the
        # misfire that decided this was asked; this note is on screen at exactly the
        # moment the name is worth reading. No workspace → the note is unchanged, not
        # suffixed: the absence of a name is itself legible, and "· (not set)" would
        # be noise on the common case.
        who = self._provider() or "nobody — no CLI on PATH"
        where = self._workspace_leaf()
        self._emit("note", f"asking {who} · {where}…" if where else f"asking {who}…")
        sent = len(kept)
        if sent < len(question):
            # Worse than the Refine case and worded to say so: `ask()` sends the tail
            # and discards the head, so the answer is to a question the user did not
            # ask. Nothing reattaches anything here.
            self._emit(
                "note",
                f"only the last {sent} characters of the question went — "
                "the CLI never saw the start of it",
            )
        # The thread already holds this question (send() added it), so the context is
        # every *earlier* turn — passing the current one would ask the CLI not to
        # answer the thing it was just asked.
        context = self.thread.tail(ASK_CONTEXT_CHARS)[:-1]
        # The card is showing all of them; only some of them go. That gap used to be
        # invisible, and an invisible gap is what makes a CLI look like it has forgotten
        # a conversation the user can still see — the note is the difference between
        # amnesia and a bound. Said only when it bites, so the ordinary case stays quiet.
        behind = len(self.thread.turns) - 1
        if behind > len(context):
            self._emit("note", f"the CLI saw the last {len(context)} of {behind} "
                               f"earlier turns - the older ones did not fit")

        def work() -> None:
            passed_over: list[str] = []
            result = ask(framed, cwd=self._refine_cwd, context=context,
                         cancel=self._cancel, artifact=artifact,
                         cli=self._cli, timeout=self._cli_timeout,
                         skipped=passed_over)
            with self._ask_lock:
                # Written after `ask` returns and read under this lock, which is what
                # makes the list safe to hand across: the worker owns it until here.
                self._ask_result = (op, result, tuple(passed_over))

        threading.Thread(target=work, daemon=True, name="ask").start()

    def _pump_ask(self) -> None:
        with self._ask_lock:
            pending, self._ask_result = self._ask_result, None
        if pending is None:
            return
        op, (answer, note), skipped = pending
        if op != self._ask_op:
            return
        self._ask_op = None
        self._trace_cli("ask", op, answer is not None, note, skipped)
        if answer is None:
            # Non-destructive by construction: the question is still in the thread, so
            # "say that again" and a retry both still work.
            self._emit("error", f"ask failed ({note})")
            self.reply = ""
        else:
            self.reply = answer
            self._remember_recent(RECENT_ANSWERED, answer)
            # Recorded as a turn so the next question inherits it — this is what makes
            # "and what about the other one?" mean anything.
            self.thread.add(f"(reply) {answer}")
            self._emit("reply", answer)
            if self.speaker is not None and not self.muted:
                spoken = answer
                if self._ask_artifact:
                    lines = answer.count("\n") + 1
                    if (lines > ARTIFACT_SAY_MAX_LINES
                            or len(answer) > ARTIFACT_SAY_MAX_CHARS):
                        # The work is on screen in full; the voice only points at it.
                        spoken = f"a {lines}-line answer is on screen"
                self.speaker.say(spoken)
            # One sentence, both facts. A fallback that rescues a call is good news and
            # still has to be legible: without the tail, a 40 s wait answered by the
            # third CLI looked exactly like a fast first-choice answer, and the provider
            # the pill named was not the one that spoke.
            self._emit("note", f"answered via {note}" if not skipped
                       else f"answered via {note}, after {'; then '.join(skipped)}")
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
