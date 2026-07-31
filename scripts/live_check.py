"""The one test that has never been run: a person, a real microphone, this loop.

Everything in `.bench/` was decoded from files. Every unit test drives the gate from a
numpy array. So the whole capture path — a real room's noise floor, a real onset, real
partial latency under real CPU contention — has never been exercised end to end, and
the numbers in the roadmap are all file-derived.

Five stages, each independently skippable, each printing a number rather than "ok":

  A  device + capture     does PortAudio deliver blocks, at what level, with what gaps
  B  gate                 does the room's floor settle, does the onset survive
  C  partial latency      R4's < 1.5 s budget, measured live instead of from a WAV
  D  commands             the eleven prompted commands, spoken, decoded, routed
  E  paste target         what P7 sees in the window you are about to paste into

Usage:  uv run python scripts/live_check.py            # all five
        uv run python scripts/live_check.py --stage C  # one of them
        uv run python scripts/live_check.py --device 3

Writes .bench/live/live-check.json so the numbers outlive the terminal.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow import SAMPLE_RATE  # noqa: E402
from flow.audio import BLOCK, Mic, SpeechGate, rms_db  # noqa: E402
from flow.edits import plan  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / ".bench" / "live"

#: The message the commands are aimed at — the same one on the recording sheet, so a
#: live run and a phone recording are scored against the same draft.
DRAFT = (
    "hi priya, the deploy is scheduled for Tuesday afternoon. sameer is writing the "
    "RELEASE NOTES and running the migration. I attached the summary from the "
    "standup. tell me if Tuesday still works."
)

#: (prompt shown, expected kind, expected op). Identical to the recording sheet's
#: eleven, so phone and live numbers are comparable.
COMMANDS = [
    ("change every Tuesday to Wednesday", "local", "replace_all"),
    ("change sameer to Samir", "local", "replace"),
    ("capitalize sameer", "local", "capitalize"),
    ("lowercase release notes", "local", "lower"),
    ("delete the bit about the standup", "local", "delete"),
    ("delete the last sentence", "local", "delete_last"),
    ("insert draft before release notes", "local", "insert_before"),
    ("undo that", "undo", ""),
    ("make it a proper prompt", "semantic", "polish"),
    ("follow up and mention the rollback plan", "followup", ""),
    ("that was a command", "rescue", ""),
]


def ask(prompt: str) -> None:
    try:
        input(f"\n  {prompt} ")
    except EOFError:
        print("\n  (no stdin — run this in your own terminal, not through a tool)")
        raise SystemExit(2)


def record(mic: Mic, seconds: float) -> list[np.ndarray]:
    """Drain the mic for `seconds`, returning every block that arrived."""
    blocks: list[np.ndarray] = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        blocks.extend(mic.drain())
        time.sleep(0.02)
    blocks.extend(mic.drain())
    return blocks


def stage_a(device: int | None) -> dict:
    """Does the real capture path deliver, and does it deliver *continuously*.

    A dropout here invalidates every later stage, and it is invisible from a WAV: the
    file always has every sample. Block count vs elapsed time is the only witness.
    """
    import sounddevice as sd

    print("\nA — device and capture")
    print(f"  default input index: {sd.default.device[0]}")
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            mark = "*" if (device is None and i == sd.default.device[0]) or \
                          i == device else " "
            print(f"  {mark}{i:3d}  {d['name'][:52]}")

    ask("Stay quiet for three seconds. Enter to start.")
    with Mic(device=device) as mic:
        t0 = time.monotonic()
        blocks = record(mic, 3.0)
        elapsed = time.monotonic() - t0

    if not blocks:
        print("  NO BLOCKS — the capture path is dead, later stages are meaningless")
        return {"blocks": 0}

    levels = [rms_db(b) for b in blocks]
    expected = elapsed * SAMPLE_RATE / BLOCK
    got = len(blocks)
    print(f"  blocks {got} of ~{expected:.0f} expected  "
          f"({got / expected:.1%} — under 95% means dropouts)")
    print(f"  quiet-room level: median {statistics.median(levels):.1f} dB, "
          f"max {max(levels):.1f} dB")
    return {"blocks": got, "expected": round(expected, 1),
            "median_db": round(statistics.median(levels), 1),
            "max_db": round(max(levels), 1)}


def stage_b(device: int | None) -> dict:
    """Does the gate open on this voice in this room, and does the onset survive.

    The pre-roll exists because soft onsets were being cut. This is the only place it
    can be checked against a real onset rather than a synthesised one.
    """
    print("\nB — speech gate in your actual room")
    ask("Say one sentence, then stop and stay quiet. Enter, then speak.")

    gate = SpeechGate()
    started = stopped = None
    preroll = 0
    with Mic(device=device) as mic:
        t0 = time.monotonic()
        floors = []
        while time.monotonic() - t0 < 12.0:
            for block in mic.drain():
                on, off = gate.push(block)
                if on and started is None:
                    started = time.monotonic() - t0
                    preroll = len(gate.take_preroll())
                if off and stopped is None:
                    stopped = time.monotonic() - t0
                floors.append(gate.floor_db)
            if stopped is not None:
                break
            time.sleep(0.02)

    if started is None:
        print("  gate never opened — the room floor may be above your voice")
        print(f"  floor settled at {gate.floor_db:.1f} dB, "
              f"needs {gate.floor_db + gate.margin_db:.1f} dB to trigger")
        return {"opened": False, "floor_db": round(gate.floor_db, 1)}

    print(f"  opened at {started:.2f} s, closed at "
          f"{stopped:.2f} s" if stopped else f"  opened at {started:.2f} s, never closed")
    print(f"  pre-roll captured: {preroll} blocks "
          f"({preroll * BLOCK / SAMPLE_RATE * 1000:.0f} ms before the onset)")
    print(f"  noise floor settled at {gate.floor_db:.1f} dB "
          f"(trigger at {gate.floor_db + gate.margin_db:.1f} dB)")
    return {"opened": True, "start_s": round(started, 2),
            "stop_s": round(stopped, 2) if stopped else None,
            "preroll_blocks": preroll, "floor_db": round(gate.floor_db, 1)}


def stage_c(device: int | None) -> dict:
    """R4's 1.5 s partial budget, measured on live audio for the first time.

    The published number came from cutting prefixes out of a WAV and decoding them
    back to back. That measures the model. This measures the loop: capture, gate,
    queue, decode, all competing for the same CPU.
    """
    from flow.asr import WhisperTranscriber

    print("\nC — partial latency, live (R4 budget: < 1.5 s)")
    print("  loading the partial model...")
    asr = WhisperTranscriber()
    asr.load(final=False)

    ask("Talk continuously for about fifteen seconds. Enter, then speak.")
    gate = SpeechGate()
    speech: list[np.ndarray] = []
    lats: list[float] = []
    with Mic(device=device) as mic:
        t0 = time.monotonic()
        last = 0.0
        while time.monotonic() - t0 < 16.0:
            for block in mic.drain():
                on, _ = gate.push(block)
                if on:
                    speech.extend(gate.take_preroll())
                if gate.speaking:
                    speech.append(block)
            now = time.monotonic()
            if gate.speaking and speech and now - last > 0.5:
                audio = np.concatenate(speech)
                t = time.monotonic()
                asr.text(audio, final=False)
                lats.append(time.monotonic() - t)
                last = time.monotonic()
            time.sleep(0.02)

    if not lats:
        print("  no partials ran — the gate never opened")
        return {"partials": 0}

    worst = max(lats)
    secs = len(speech) * BLOCK / SAMPLE_RATE
    print(f"  {len(lats)} partials over {secs:.1f} s of speech")
    print(f"  median {statistics.median(lats):.2f} s, worst {worst:.2f} s  "
          f"{'PASS' if worst < 1.5 else 'BREACH of the 1.5 s budget'}")
    return {"partials": len(lats), "speech_s": round(secs, 1),
            "median_s": round(statistics.median(lats), 2),
            "worst_s": round(worst, 2), "pass": worst < 1.5}


def stage_d(device: int | None) -> dict:
    """The eleven prompted commands, spoken live, decoded and routed.

    Same items and same draft as the recording sheet, so this number and the phone
    number answer the same question. One utterance at a time, because the point is to
    find which command fails, not to produce an average.
    """
    from flow.asr import WhisperTranscriber

    print("\nD — the eleven commands, spoken live")
    print("  loading the final model...")
    asr = WhisperTranscriber()
    asr.load(final=True)

    rows = []
    for i, (say, kind, op) in enumerate(COMMANDS, 1):
        ask(f"{i:2d}/11  say: \"{say}\"   — Enter, speak, then stay quiet.")
        gate = SpeechGate()
        speech: list[np.ndarray] = []
        with Mic(device=device) as mic:
            t0 = time.monotonic()
            while time.monotonic() - t0 < 12.0:
                for block in mic.drain():
                    on, off = gate.push(block)
                    if on:
                        speech.extend(gate.take_preroll())
                    if gate.speaking:
                        speech.append(block)
                    if off and speech:
                        break
                if not gate.speaking and speech:
                    break
                time.sleep(0.02)

        if not speech:
            print("       nothing captured")
            rows.append({"item": i, "hit": False, "text": "", "got": "no audio"})
            continue

        text = asr.text(np.concatenate(speech), final=True)
        p = plan(text, DRAFT)
        hit = (p.kind, p.op) == (kind, op)
        print(f"       heard: {text!r}")
        print(f"       routed: {p.kind}/{p.op or '-'}   "
              f"{'ok' if hit else 'MISS (wanted ' + kind + '/' + (op or '-') + ')'}")
        rows.append({"item": i, "hit": hit, "text": text,
                     "got": f"{p.kind}/{p.op}", "want": f"{kind}/{op}"})

    ok = sum(r["hit"] for r in rows)
    print(f"\n  {ok}/{len(rows)}  {ok / len(rows):.1%}")
    return {"n": len(rows), "hit": ok, "rows": rows}


def stage_e() -> dict:
    """What P7 sees in the window you are about to paste into.

    Reads only. Nothing is pasted: `inject.paste` sends a real Ctrl-V into whatever
    has focus, and a test is not a good enough reason to type into someone's editor.
    """
    from flow.inject import foreground_target, prepare

    print("\nE — paste target (read-only, nothing is sent)")
    ask("Click the window you would dictate into, then come back and press Enter.")
    target = foreground_target()
    payload, warning = prepare("delete the last sentence", target)
    print(f"  window class : {target.cls}")
    print(f"  process      : {target.process}")
    print(f"  terminal     : {target.terminal}")
    print(f"  bracketed    : {payload != 'delete the last sentence'}")
    print(f"  warning      : {warning or '(none)'}")
    return {"cls": target.cls, "process": target.process,
            "terminal": target.terminal, "bracketed": payload != "delete the last sentence",
            "warning": warning}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", type=int, default=None)
    ap.add_argument("--stage", default="ABCDE", help="subset, e.g. --stage CD")
    args = ap.parse_args()

    stages = args.stage.upper()
    print("Live check — a person, a real microphone, this loop.")
    print("Ctrl-C at any point; whatever finished is still written out.")

    out: dict = {}
    try:
        if "A" in stages:
            out["A_capture"] = stage_a(args.device)
        if "B" in stages:
            out["B_gate"] = stage_b(args.device)
        if "C" in stages:
            out["C_partial_latency"] = stage_c(args.device)
        if "D" in stages:
            out["D_commands"] = stage_d(args.device)
        if "E" in stages:
            out["E_target"] = stage_e()
    except KeyboardInterrupt:
        print("\n  stopped")

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "live-check.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"\nwritten -> {path}")


if __name__ == "__main__":
    main()
