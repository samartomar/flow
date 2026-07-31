"""Where to put the confidence bar that blocks destructive edits.

A mis-heard command that deletes a sentence is the worst failure this product has:
the words are gone, and the user does not know which words they were. So a command
the model was unsure about should not be allowed to delete. The question is *how*
unsure, and the answer cannot be guessed — set it too strict and accented speakers,
who score worse on `avg_logprob` for reasons that have nothing to do with being
misheard, lose the ability to delete anything.

Two distributions decide it:

  **cost** — real accented speech from the accent manifests. Every clip below the bar
  is an utterance whose destructive commands would need confirming. Reported per L1
  group, because a bar that is comfortable for the US control and blocks a third of
  the Japanese slice is not a bar, it is a tax on having an accent.

  **benefit** — the recorded commands, which are the real thing this guards, plus the
  same audio degraded until it *is* misheard. A bar that never fires on a misheard
  command is decoration.

Usage:  uv run python scripts/guardrail_bench.py [--model small.en] [--limit N]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.asr import WhisperTranscriber  # noqa: E402
from flow.clean import LOW_CONFIDENCE  # noqa: E402

BENCH = Path(__file__).resolve().parent.parent / ".bench"

#: The bars to consider. LOW_CONFIDENCE (−0.8) is where clean.py already calls an
#: utterance invented; the guardrail must sit at or above it, since anything below is
#: already being dropped outright.
CANDIDATES = (-0.5, -0.6, -0.7, -0.8, -0.9, -1.0)


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0


def degrade(audio: np.ndarray, snr_db: float, rng: np.random.Generator) -> np.ndarray:
    """The same command, buried in noise until the model starts guessing.

    Additive white noise at a stated SNR. Crude next to a real room, but it is the one
    degradation whose severity is a number, so the bar can be quoted against it.
    """
    power = float(np.mean(audio.astype(np.float64) ** 2)) or 1e-12
    noise = rng.normal(0.0, np.sqrt(power / (10 ** (snr_db / 10))), audio.shape)
    return np.clip(audio + noise.astype(np.float32), -1.0, 1.0)


def score(asr: WhisperTranscriber, audio: np.ndarray) -> tuple[str, float | None]:
    text = asr.text(audio, final=True)
    return text, asr.take_confidence()


def cost(asr: WhisperTranscriber, limit: int) -> dict:
    """How much ordinary accented speech a bar would put behind a confirmation."""
    rows = []
    for mf in sorted(BENCH.glob("accent/manifest-*.jsonl")):
        for line in mf.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    if not rows:
        print("no accent manifests — run scripts/fetch_accent_data.py")
        return {}

    by_group: dict[str, list[float]] = {}
    for row in rows:
        group = row["group"]
        seen = by_group.setdefault(group, [])
        if len(seen) >= limit:
            continue
        wav = BENCH / "accent" / row["wav"]
        if not wav.exists():
            continue
        _, lp = score(asr, read_wav(wav))
        if lp is not None:
            seen.append(lp)

    print(f"\nCOST — real accented speech, {sum(len(v) for v in by_group.values())} "
          f"clips (max {limit}/group)\n")
    header = "  " + f"{'group':<12}{'n':>4}{'median':>9}{'p10':>8}   " + \
        "".join(f"{c:>7}" for c in CANDIDATES)
    print(header)
    out = {}
    for group, lps in sorted(by_group.items()):
        lps.sort()
        blocked = [sum(1 for x in lps if x < c) / len(lps) for c in CANDIDATES]
        print(f"  {group:<12}{len(lps):>4}{statistics.median(lps):>9.2f}"
              f"{lps[len(lps) // 10]:>8.2f}   " +
              "".join(f"{b:>6.0%} " for b in blocked))
        out[group] = {"n": len(lps), "median": round(statistics.median(lps), 3),
                      "blocked": dict(zip(map(str, CANDIDATES),
                                          [round(b, 4) for b in blocked]))}
    print("\n  (each cell: share of that group's ordinary speech that would need "
          "confirming)")
    return out


def benefit(asr: WhisperTranscriber) -> dict:
    """Does the bar actually fire when a destructive command is misheard?"""
    mf = BENCH / "recorded" / "manifest-recorded.jsonl"
    if not mf.exists():
        print("\nno recorded manifest — run scripts/ingest_recordings.py")
        return {}
    rows = [json.loads(x) for x in mf.read_text(encoding="utf-8").splitlines()
            if x.strip()]
    destructive = [r for r in rows
                   if r["op"] in ("delete", "delete_last", "delete_range",
                                  "replace", "replace_all")]
    if not destructive:
        return {}

    rng = np.random.default_rng(20260731)
    print(f"\nBENEFIT — {len(destructive)} recorded destructive commands, clean and "
          "buried in noise\n")
    print(f"  {'item':<6}{'snr':>6}{'lp':>8}  heard")
    out = []
    for row in destructive:
        audio = read_wav(BENCH / "recorded" / row["wav"])
        for snr in (None, 5, 0):
            clip = audio if snr is None else degrade(audio, snr, rng)
            text, lp = score(asr, clip)
            ok = text.strip().lower() == row["said"].strip().lower()
            print(f"  {row['item']:<6}{'clean' if snr is None else str(snr) + 'dB':>6}"
                  f"{lp if lp is not None else float('nan'):>8.2f}  "
                  f"{'=' if ok else '~'} {text[:44]!r}")
            out.append({"item": row["item"], "snr": snr, "lp": lp,
                        "text": text, "intact": ok})
    print("\n  (= transcript matches the clean one, ~ it does not)")
    return {"rows": out}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="small.en")
    ap.add_argument("--limit", type=int, default=40, help="clips per group")
    args = ap.parse_args()

    asr = WhisperTranscriber(args.model, args.model)
    print(f"model {args.model}; clean.py already drops below {LOW_CONFIDENCE}")
    c = cost(asr, args.limit)
    b = benefit(asr)

    out = BENCH / "accent" / "guardrail-bench.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"cost": c, "benefit": b}, indent=1), encoding="utf-8")
    print(f"\ndetail -> {out}")


if __name__ == "__main__":
    main()
