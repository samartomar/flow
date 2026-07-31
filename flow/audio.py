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

import numpy as np
import sounddevice as sd

from . import SAMPLE_RATE

BLOCK = 1024  # 64 ms at 16 kHz — fine enough for a responsive level meter (R13)

# Bounds on the adaptive noise floor. Without them, a stretch of true digital silence
# drags the floor arbitrarily low and every subsequent block reads as speech.
FLOOR_MIN_DB = -70.0
FLOOR_MAX_DB = -25.0
DIGITAL_SILENCE_DB = -80.0


def rms_db(block: np.ndarray) -> float:
    return 20.0 * math.log10(float(np.sqrt(np.mean(block**2))) + 1e-9)


class Mic:
    """Bounded, non-blocking capture.

    The queue drops the oldest block when full rather than growing. If the consumer
    stalls (a slow decode, say), memory stays flat and we lose audio instead of
    accumulating an ever-growing backlog — the right trade for R8.
    """

    def __init__(self, device: int | None = None, max_blocks: int = 256) -> None:
        self._device = device
        self._q: queue.Queue[np.ndarray] = queue.Queue(maxsize=max_blocks)
        self._stream: sd.InputStream | None = None
        self._level = -90.0
        self._lock = threading.Lock()
        self.dropped = 0

    def _callback(self, indata, _frames, _time, status) -> None:
        # Runs on the PortAudio thread: no allocation-heavy or blocking work here.
        if status:
            pass  # over/underflows are non-fatal; the level meter will show the gap
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
        self._stream = sd.InputStream(
            device=self._device,
            channels=1,
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

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
    def active(self) -> bool:
        """False if the device went away mid-session (unplugged, driver reset).

        A dead PortAudio stream stops delivering blocks without raising anywhere the
        session can see, so over a long run this has to be polled (R8).
        """
        return self._stream is not None and bool(self._stream.active)

    def restart(self) -> None:
        self.stop()
        self.start()

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
    ) -> None:
        self.margin_db = margin_db
        self.hang_blocks = max(1, int(hang_ms / block_ms))
        self.floor_db = floor_db
        self.speaking = False
        self._quiet_blocks = 0

    def push(self, block: np.ndarray) -> tuple[bool, bool]:
        """Feed one block. Returns (started, stopped) edge flags."""
        level = rms_db(block)
        loud = level > self.floor_db + self.margin_db

        if not self.speaking:
            # Track the room only while nobody is talking, otherwise speech would
            # drag the floor up and the gate would slowly go deaf.
            #
            # Two clamps, both found by running this against padded silence, where the
            # floor ran away to -142 dB and the gate turned hypersensitive:
            #   - digital silence is not room noise, so it must not train the floor
            #   - the floor is bounded, so no input can make the gate deaf or paranoid
            if not loud and level > DIGITAL_SILENCE_DB:
                self.floor_db += 0.05 * (level - self.floor_db)
                self.floor_db = min(FLOOR_MAX_DB, max(FLOOR_MIN_DB, self.floor_db))
            if loud:
                self.speaking = True
                self._quiet_blocks = 0
                return True, False
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

    def reset(self) -> None:
        self.speaking = False
        self._quiet_blocks = 0
