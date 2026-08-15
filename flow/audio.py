"""Microphone capture and end-of-speech detection.

Two things live here:

`Mic`         - pulls float32 mono blocks off the input device into a bounded queue.
`SpeechGate`  - decides when the user started and stopped talking.

`SpeechGate` is an RMS gate with an adaptive noise floor rather than Silero VAD.
That is a deliberate choice: Silero would mean carrying `onnxruntime` for a question
this only has to answer coarsely ("has the talking stopped?"), where being 200 ms late
is invisible to the user because the draft is held rather than sent (R5). Twenty lines
of stdlib maths beats a 13 MB dependency here.
"""

from __future__ import annotations

import math
import queue
import threading
import time
from collections import deque

import numpy as np
import sounddevice as sd

from . import SAMPLE_RATE

BLOCK = 1024  # 64 ms at 16 kHz — fine enough for a responsive level meter (R13)

#: How long PortAudio may go without handing over a block before the stream counts as
#: dead, whatever the stream says about itself.
#:
#: **This is not a silence heuristic, and the distinction is the whole reason it is
#: allowed to exist.** A working microphone in a silent room delivers blocks of
#: near-zero samples at exactly the rate a loud one does. What is timed here is
#: *delivery* — PortAudio's own half of the contract — and never loudness. `SpeechGate`
#: below is the only thing in this file with an opinion about how loud a block is, and
#: it is deliberately not consulted here.
#:
#: Two seconds, measured rather than guessed. On this machine (PortAudio 19.7-devel,
#: sounddevice 0.5.5, a USB mic at 16 kHz/1024) the gap between callbacks is a median
#: **63.0 ms** — the block period — with a p99 of 79 ms and a maximum of 79 ms when
#: nothing else is running. Under four CPU-bound threads, standing in for a decode
#: running beside capture, the median does not move and the worst gap seen over ~109 s
#: is **453 ms**. Two seconds is 4.4x that worst case and 31 block periods.
#:
#: That much headroom is right because this is the *backstop*, not the detector. The
#: detector is `InputStream.active`, which flips within one 30 ms frame; this only has
#: to catch a host API that keeps reporting a dead stream as running. A false positive
#: tears down a working stream mid-sentence, so the bias is deliberately toward late.
STALL_SEC = 2.0

# Bounds on the adaptive noise floor. Without them, a stretch of true digital silence
# drags the floor arbitrarily low and every subsequent block reads as speech.
#
# The minimum was −70 dB, and the first live-microphone run showed what that costs: a
# quiet room with a decent USB mic measures **−96.7 dB**, so the floor could never
# descend to meet it. It stayed pinned at its −55 dB start, the trigger stayed at
# −45 dB, and the gate simply never opened. The adaptive floor was not adapting at
# all — every file-driven test had either speech or true digital silence in it, and
# neither exercises a real room's noise floor.
FLOOR_MIN_DB = -100.0
FLOOR_MAX_DB = -25.0

#: How much audio to keep from *before* the gate opened, in blocks of 64 ms.
#:
#: Defect 5: a gate can only open after it has heard something loud enough, so the
#: quiet head of the word that opened it is already gone. That head is not silence —
#: it is the unaspirated stop, the soft fricative, the approximant that carries the
#: consonant. Deleting it turns "delete" into "leet". The cost of keeping it is
#: bounded and tiny: four blocks of float32 at 16 kHz is 16 kB.
PREROLL_BLOCKS = 4


def rms_db(block: np.ndarray) -> float:
    return 20.0 * math.log10(float(np.sqrt(np.mean(block**2))) + 1e-9)


def refresh_devices() -> bool:
    """Make PortAudio look at the machine's audio hardware again. True if it did.

    PortAudio takes its device list once, when it initialises, and never looks again.
    The headset plugged in after launch is not in that list, and neither is the new
    system default that arrived with it — so `device=None`, which means "whatever the
    default input is", keeps meaning the default *as it was at startup*. That is
    precisely the wrong answer for the one case reopening exists to serve: the user
    plugged something in, and the new default is what they want. Terminating and
    re-initialising is what sounddevice offers for this, and it is the only thing that
    does.

    Costs 12.2 ms on this machine (11.5-13.8 ms over six rounds), with a 20.6 ms reopen
    behind it — small enough to pay on every attempt rather than reason about when it is
    needed.

    **Only safe when this process has no PortAudio stream open at all**, and the second
    half of that sentence is the trap. `Pa_Terminate` closes every open stream, and the
    Python object still holding one is then pointing at freed memory — a use-after-free
    on the next write or close, which no `except` catches. `Mic.restart` closes its own
    stream first, but Flow has a *second* PortAudio user: a spoken reply, played through
    a `RawOutputStream` by `flow/piper.py` and `flow/edge.py`. Only the session can see
    whether one is playing, which is why `Session._pump_device` holds the whole recovery
    while Flow is talking rather than this function trying to decide for itself.

    Never raises otherwise. This runs on the recovery path, where the caller already has
    one failure to report and a second one from the diagnosis would bury it; False here
    only means the reopen behind it is working from the older list.
    """
    try:
        sd._terminate()
        sd._initialize()
        return True
    except Exception:
        return False


class Mic:
    """Bounded, non-blocking capture, and whether it is still happening.

    The queue drops the oldest block when full rather than growing. If the consumer
    stalls (a slow decode, say), memory stays flat and we lose audio instead of
    accumulating an ever-growing backlog — the right trade for R8.

    The second job is `trouble`. A microphone that fails at startup fails loudly, but
    one that goes away *mid-session* — a headset unplugged, a Bluetooth link dropping,
    Windows moving the default device out from under an open stream — fails as an
    absence: the callback simply stops being called. Nothing raises on the session's
    thread, so this object is where the question "is capture still happening" has to be
    answerable, and it answers it from PortAudio's own signals rather than from the
    audio (see `trouble` and `STALL_SEC`).
    """

    def __init__(self, device: int | None = None, max_blocks: int = 256) -> None:
        self._device = device
        self._q: queue.Queue[np.ndarray] = queue.Queue(maxsize=max_blocks)
        self._stream: sd.InputStream | None = None
        self._level = -90.0
        self._lock = threading.Lock()
        self.dropped = 0
        #: Monotonic time of the last block PortAudio handed over, and the whole of the
        #: liveness check. Written on the PortAudio thread and read on the session's; a
        #: float store is atomic under the GIL, so this deliberately does *not* take
        #: `_lock` — the callback must never queue behind a reader.
        self._last_block = 0.0
        #: Set by PortAudio's own `finished_callback` when a stream ends without our
        #: having asked it to. The earliest death signal there is, and the only pushed
        #: one; `_stopping` is what keeps our own teardown from setting it.
        self._ended = False
        self._stopping = False
        #: What the open stream is called, read once at open time. Recorded rather than
        #: asked for later because the question is unanswerable exactly when it matters:
        #: `device_name` has to reach PortAudio, and a device that is being unplugged is
        #: the case where that fails. A pinned index that reopens onto a different name
        #: is the one substitution Flow can make without choosing to, and this is what
        #: lets the session notice and say so.
        self.opened_name = ""
        #: How many callbacks arrived with PortAudio's input-overflow flag set: audio
        #: the hardware threw away before Flow ever saw it. Distinct from `dropped`,
        #: which is this process's own queue discarding blocks it did receive. Counted
        #: rather than ignored because invariant 4 does not care which side of the API
        #: lost the words.
        self.overflows = 0

    def _callback(self, indata, _frames, _time, status) -> None:
        # Runs on the PortAudio thread: no allocation-heavy or blocking work here.
        #
        # The timestamp first, and before anything that could go wrong with the block
        # itself: a block that arrived is proof this stream is still delivering,
        # whatever else is true of it.
        self._last_block = time.monotonic()
        if status:
            # Over/underflows are non-fatal — the level meter will show the gap — and a
            # status flag is emphatically *not* how a device announces that it is gone;
            # there is no such flag. What it does announce is loss, and an input
            # overflow is audio dropped in the driver, upstream of the queue. Counted
            # here, said out loud by `Session._pump_overflow`.
            if status.input_overflow:
                self.overflows += 1
        block = indata[:, 0].copy() if indata.ndim > 1 else indata.copy()
        with self._lock:
            self._level = rms_db(block)
        try:
            self._q.put_nowait(block)
        except queue.Full:
            try:
                self._q.get_nowait()
                self._q.put_nowait(block)
            except queue.Empty:
                pass
            self.dropped += 1

    def start(self) -> None:
        # Ask the device for 16 kHz mono directly and let the driver resample; the
        # local mic is natively 44.1 kHz stereo, and doing it here would mean writing
        # a resampler we do not need.
        self._ended = False
        self._stopping = False
        # Stamped before the stream exists, so a stream that dies between here and its
        # first callback goes stale on schedule instead of being eternally fresh. The
        # first block measured 111-266 ms behind the open on this machine, comfortably
        # inside `STALL_SEC`.
        self._last_block = time.monotonic()
        self._stream = sd.InputStream(
            device=self._device,
            channels=1,
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK,
            dtype="float32",
            callback=self._callback,
            # PortAudio's own "this stream is over", however it got there — including a
            # host API abandoning a device that has been removed, which raises nowhere.
            finished_callback=self._finished,
        )
        self._stream.start()
        self.opened_name = self.device_name

    def _finished(self) -> None:
        """PortAudio's own end-of-stream, delivered on the PortAudio thread.

        Recorded only when nobody here asked for it, which is what makes it evidence:
        a stream that finished with no `stop()` behind it finished because the device
        did. `stop()` claims the flag before it calls into PortAudio, since this fires
        from inside that call and would otherwise file our own teardown as a fault.
        """
        if not self._stopping:
            self._ended = True

    def stop(self) -> None:
        if self._stream is not None:
            self._stopping = True
            self._stream.stop()
            self._stream.close()
            self._stream = None
        # Cleared here rather than in `start()` alone, so a Mic that is stopped and left
        # stopped does not keep reporting the last device it had as though it were open.
        self._ended = False
        self.opened_name = ""

    def __enter__(self) -> "Mic":
        self.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.stop()

    @property
    def level_db(self) -> float:
        with self._lock:
            return self._level

    @property
    def trouble(self) -> str:
        """Why capture is not working, in one ASCII phrase — or "" while it is.

        A dead PortAudio stream stops delivering blocks without raising anywhere the
        session can see, so over a long run this has to be polled (R8). Four questions,
        cheapest and most certain first, and every one of them reads a signal PortAudio
        itself produces rather than inferring anything from the audio:

        1. **Is there a stream at all.** Nothing opened yet, or `stop()` closed it.
        2. **Did PortAudio end it.** `finished_callback` fires when a stream finishes
           for any reason that was not our own `stop()` — a callback raising
           `CallbackAbort`, a host API giving up on a device that has been removed.
        3. **Does it still say it is running.** `Pa_IsStreamActive`, measured at
           **0.43 us** a call here, which is what makes it affordable on every 30 ms
           frame rather than on a five-second heartbeat. A raise counts as an answer:
           a stream whose device is being pulled can throw out of the accessor, and an
           exception from the stream machinery is a death signal like any other.
        4. **Is it still delivering.** The backstop for a host API that reports a dead
           stream as active — see `STALL_SEC`, which times *blocks arriving*, not
           quiet. Silence is a working microphone in a quiet room.

        A phrase and not a bool because the session has to say what happened, and a
        note reading "the microphone stopped" with no reason attached is the kind
        people learn to scroll past. ASCII because it ends up in a note and notes are
        also printed (`__main__.say`).
        """
        stream = self._stream
        if stream is None:
            return "capture is not open"
        if self._ended:
            return "PortAudio ended the stream"
        try:
            if not stream.active:
                return "the stream stopped running"
        except Exception as exc:
            return f"the stream could not be read ({type(exc).__name__})"
        quiet = time.monotonic() - self._last_block
        if quiet >= STALL_SEC:
            return f"no blocks arrived for {quiet:.1f} s"
        return ""

    @property
    def active(self) -> bool:
        """False if the device went away mid-session (unplugged, driver reset).

        `trouble` asked as a yes/no, for the callers that only need to draw a label
        with the answer. One implementation, so the pill's `NO INPUT` and the session's
        recovery can never disagree about whether there is a microphone.
        """
        return not self.trouble

    @property
    def pinned(self) -> int | None:
        """The device index a person chose, or None for "whatever is default".

        What reopening is allowed to do turns on this. With no pin, the right device
        after a change is whatever the system now calls default, and following it is
        the feature — plug in a headset and Flow moves to it. With a pin, the index is
        an instruction, and quietly opening a different microphone because this one
        stopped answering would be Flow overruling it in the one direction nobody can
        check: a recording that keeps going, from somewhere else.
        """
        return self._device

    @property
    def device_name(self) -> str:
        """Which input device this is, by name, or "" when it cannot be named.

        By name and never by index: indexes are assigned in enumeration order and shift
        when anything is plugged in, so a stored index would quietly come to mean a
        different microphone — which is the exact confusion the profile records this to
        catch. Asks the open stream first, because `device=None` means "whatever the
        system default is" and the answer to that changes between sessions.

        Never raises. This is decoration on an advisory note, and PortAudio will happily
        refuse to describe a device that is being unplugged as we ask.

        The name is whatever the host API gives, truncation included — MME caps device
        names at 31 characters, so the local mic reports as "OBSBOT Tiny 3 Lite
        Microphone (" with the bracket left open. Compared, not parsed, so a stable
        truncation is as good as a full name.
        """
        try:
            index = self._stream.device if self._stream is not None else self._device
            if index is None:
                index = sd.default.device[0]
            return str(sd.query_devices(index)["name"])
        except Exception:
            return ""

    def restart(self) -> None:
        """Close whatever is left, and open again against the machine as it is now.

        The refresh in the middle is the whole difference between this and
        `stop(); start()`, and without it the auto-device promise is empty: `device=None`
        would reopen onto the default *as it was at launch*, which is the one answer
        guaranteed to be wrong when the reason for reopening is that the hardware
        changed. A pinned index is re-read from the same fresh list, so `--device 3`
        keeps meaning index 3 on the machine as it is now — and `opened_name` is what
        lets the caller notice when index 3 has become a different microphone.

        Between the close and the open, because that is the only window in which
        `refresh_devices` is safe — read its second paragraph before moving this line.
        """
        self.stop()
        self.refresh()
        self.start()

    def refresh(self) -> bool:
        """`refresh_devices`, reachable through the object the session already holds.

        A method rather than the bare function at the session's call sites, so a fake
        microphone simply does not have it and the suite never terminates the real
        PortAudio — the `getattr` idiom `dropped` and `trouble` are read through.
        """
        return refresh_devices()

    def drain(self) -> list[np.ndarray]:
        """Take every block captured since the last call."""
        out = []
        while True:
            try:
                out.append(self._q.get_nowait())
            except queue.Empty:
                return out


class SpeechGate:
    """Adaptive-threshold speech detector with hangover.

    While quiet, the noise floor tracks the room. Speech starts when a block rises
    `margin_db` above that floor and stops after `hang_ms` of continuous quiet, so
    natural pauses mid-sentence do not end the utterance.
    """

    def __init__(
        self,
        block_ms: float = 1000.0 * BLOCK / SAMPLE_RATE,
        margin_db: float = 10.0,
        hang_ms: float = 800.0,
        floor_db: float = -55.0,
        preroll_blocks: int = PREROLL_BLOCKS,
    ) -> None:
        self.margin_db = margin_db
        self.hang_blocks = max(1, int(hang_ms / block_ms))
        self.floor_db = floor_db
        self.speaking = False
        self._quiet_blocks = 0
        #: The last few blocks heard while quiet, so the onset that opened the gate is
        #: not the first thing the model gets to hear.
        self._preroll: deque[np.ndarray] = deque(maxlen=max(0, preroll_blocks))

    def push(self, block: np.ndarray) -> tuple[bool, bool]:
        """Feed one block. Returns (started, stopped) edge flags."""
        level = rms_db(block)
        loud = level > self.floor_db + self.margin_db

        if not self.speaking:
            if loud:
                # The pre-roll now holds the blocks just before this one; the caller
                # takes them with `take_preroll()`.
                self.speaking = True
                self._quiet_blocks = 0
                return True, False
            # Track the room only while nobody is talking, otherwise speech would
            # drag the floor up and the gate would slowly go deaf.
            #
            # Two clamps, both found by running this against padded silence, where the
            # floor ran away to -142 dB and the gate turned hypersensitive:
            #   - digital silence is not room noise, so it must not train the floor
            #   - the floor is bounded, so no input can make the gate deaf or paranoid
            #
            # Digital silence is tested exactly, not by loudness. It used to be "below
            # -80 dB", which is a guess about where rooms stop and files begin — and a
            # real quiet room came in at -96.7 dB, was classified as a padded WAV, and
            # never trained the floor. A block of literal zeros is the only thing this
            # clamp was ever meant to catch, and `any()` catches exactly that.
            if block.any():
                self.floor_db += 0.05 * (level - self.floor_db)
                self.floor_db = min(FLOOR_MAX_DB, max(FLOOR_MIN_DB, self.floor_db))
            self._preroll.append(block)
            return False, False

        if loud:
            self._quiet_blocks = 0
        else:
            self._quiet_blocks += 1
            if self._quiet_blocks >= self.hang_blocks:
                self.speaking = False
                self._quiet_blocks = 0
                return False, True
        return False, False

    def take_preroll(self) -> list[np.ndarray]:
        """The quiet blocks captured just before the gate opened, oldest first.

        Drained rather than read, so a second utterance cannot begin with the head of
        the first one.
        """
        out = list(self._preroll)
        self._preroll.clear()
        return out

    def reset(self) -> None:
        self.speaking = False
        self._quiet_blocks = 0
        self._preroll.clear()
