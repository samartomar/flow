"""Long-session soak test (R8, proof criterion 5).

Drives a real Session with a real Whisper model for N minutes, feeding looped speech in
real time, and samples resident memory and decode latency throughout. The question it
answers is narrow but the important one: does a long session grow, or drift slower?

Memory is read via PSAPI through ctypes, so this needs no psutil (R16).

    uv run python scripts/soak.py 10
"""

from __future__ import annotations

import ctypes
import sys
import time
import wave
from ctypes import wintypes
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow import SAMPLE_RATE  # noqa: E402
from flow.asr import WhisperTranscriber  # noqa: E402
from flow.audio import BLOCK  # noqa: E402
from flow.session import Session  # noqa: E402


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


_psapi = ctypes.WinDLL("psapi", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_psapi.GetProcessMemoryInfo.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD
]
_psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
_kernel32.GetCurrentProcess.restype = wintypes.HANDLE


def rss_mb() -> float:
    c = PROCESS_MEMORY_COUNTERS()
    c.cb = ctypes.sizeof(c)
    if not _psapi.GetProcessMemoryInfo(
        _kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb
    ):
        return -1.0
    return c.WorkingSetSize / (1024 * 1024)


class LoopingMic:
    """Replays a WAV on repeat, in real time, with gaps so utterances close."""

    def __init__(self, path: Path, gap_sec: float = 1.4) -> None:
        with wave.open(str(path), "rb") as w:
            sr, nch = w.getframerate(), w.getnchannels()
            raw = w.readframes(w.getnframes())
        a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if nch > 1:
            a = a.reshape(-1, nch).mean(axis=1)
        if sr != SAMPLE_RATE:
            n = int(len(a) * SAMPLE_RATE / sr)
            a = np.interp(
                np.linspace(0, len(a) - 1, n), np.arange(len(a)), a
            ).astype(np.float32)
        # A touch of noise in the gap: pure digital silence is not what a room sounds
        # like, and the gate's noise floor should be tracking something realistic.
        gap = (np.random.default_rng(7).standard_normal(int(gap_sec * SAMPLE_RATE))
               * 0.0004).astype(np.float32)
        self._loop = np.concatenate([a, gap])
        self._pos = 0
        self._clock = time.perf_counter()
        self.level_db = -60.0
        self.utterances = 0

    def start(self) -> None: ...
    def stop(self) -> None: ...

    @property
    def active(self) -> bool:
        return True

    def restart(self) -> None: ...

    def drain(self) -> list[np.ndarray]:
        """Hand over exactly as many blocks as real time has produced."""
        now = time.perf_counter()
        due = int((now - self._clock) * SAMPLE_RATE / BLOCK)
        if due <= 0:
            return []
        self._clock += due * BLOCK / SAMPLE_RATE
        out = []
        for _ in range(due):
            end = self._pos + BLOCK
            if end <= len(self._loop):
                out.append(self._loop[self._pos : end])
                self._pos = end
            else:
                self._pos = 0
                self.utterances += 1
                out.append(self._loop[0:BLOCK])
                self._pos = BLOCK
        return out


def main() -> None:
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
    wav = Path(__file__).resolve().parent.parent / ".bench" / "long.wav"

    mic = LoopingMic(wav)
    session = Session(asr=WhisperTranscriber("base.en"), mic=mic)
    session.start()

    t0 = time.perf_counter()
    baseline = rss_mb()
    print(f"soak {minutes:.0f} min · baseline RSS {baseline:.1f} MB", flush=True)
    print(
        f"{'min':>5} {'RSS MB':>8} {'drift':>7} {'draft':>7} {'utt':>5} "
        f"{'p50 dec':>9} {'n':>5} {'state':<10}",
        flush=True,
    )

    samples: list[tuple[float, float]] = []
    # Latency has to be sampled as a *window*, not cumulatively: the question is whether
    # decode at minute 10 costs what it cost at minute 1, which an average over the whole
    # run would hide.
    lat_windows: list[tuple[float, float, int]] = []
    next_sample = 0.0
    deadline = t0 + minutes * 60

    while time.perf_counter() < deadline:
        session.tick()
        # Keep the draft bounded the way the UI would: a real user sends periodically.
        if len(session.draft.text) > 4000:
            session.send()
        elapsed = time.perf_counter() - t0
        if elapsed >= next_sample:
            next_sample += 30.0
            mb = rss_mb()
            samples.append((elapsed, mb))

            # Drain, so each sample covers exactly the decodes since the last one.
            secs = sorted(s for _k, s in session.worker.take_timings())
            med = secs[len(secs) // 2] if secs else float("nan")
            if secs:
                lat_windows.append((elapsed, med, len(secs)))

            print(
                f"{elapsed / 60:5.1f} {mb:8.1f} {mb - baseline:+7.1f} "
                f"{len(session.draft.text):7d} {mic.utterances:5d} "
                f"{med:9.2f} {len(secs):5d} {session.state.value:<10}",
                flush=True,
            )
        time.sleep(0.01)

    session.close()

    print("\n--- result ---")
    if len(samples) >= 4:
        head = sum(m for _t, m in samples[:2]) / 2
        tail = sum(m for _t, m in samples[-2:]) / 2
        span = (samples[-1][0] - samples[0][0]) / 60
        print(f"RSS first samples : {head:.1f} MB")
        print(f"RSS last samples  : {tail:.1f} MB")
        print(f"drift             : {tail - head:+.1f} MB over {span:.1f} min "
              f"({(tail - head) / max(span, 0.1):+.2f} MB/min)")

    if len(lat_windows) >= 4:
        q = max(1, len(lat_windows) // 4)
        first = sum(m for _t, m, _n in lat_windows[:q]) / q
        last = sum(m for _t, m, _n in lat_windows[-q:]) / q
        print(f"p50 decode first quartile: {first:.3f}s")
        print(f"p50 decode last  quartile: {last:.3f}s")
        print(f"latency change           : {(last - first) * 1000:+.0f} ms "
              f"({(last / first - 1) * 100:+.1f}%)")
    print(f"utterances decoded: {mic.utterances}")


if __name__ == "__main__":
    main()
