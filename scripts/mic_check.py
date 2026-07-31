"""Verify the real capture path: sounddevice -> Mic -> blocks (no speech required).

Every earlier test drove audio from a WAV or a fake, so the actual PortAudio path had
never run. This opens the real device briefly and reports what arrived.

    uv run python scripts/mic_check.py [seconds] [--device N]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow import SAMPLE_RATE  # noqa: E402
from flow.audio import BLOCK, Mic, SpeechGate, rms_db  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("seconds", nargs="?", type=float, default=3.0)
    ap.add_argument("--device", type=int, default=None)
    args = ap.parse_args()

    gate = SpeechGate()
    blocks = 0
    levels: list[float] = []
    speech_edges = 0

    with Mic(device=args.device) as mic:
        print(f"stream active: {mic.active}")
        deadline = time.perf_counter() + args.seconds
        while time.perf_counter() < deadline:
            for block in mic.drain():
                blocks += 1
                levels.append(rms_db(block))
                started, _stopped = gate.push(block)
                speech_edges += int(started)
            time.sleep(0.01)

    expected = int(args.seconds * SAMPLE_RATE / BLOCK)
    print(f"blocks received : {blocks} (expected ~{expected})")
    print(f"dropped         : {mic.dropped}")
    if levels:
        print(f"level dB        : min {min(levels):.1f}  max {max(levels):.1f}")
        print(f"noise floor     : {gate.floor_db:.1f} dB")
        print(f"speech onsets   : {speech_edges}")
    ok = blocks >= expected * 0.8 and mic.dropped == 0
    print("RESULT:", "ok" if ok else "PROBLEM — too few blocks or drops")


if __name__ == "__main__":
    main()
