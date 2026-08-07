"""What biasing the decoder toward the send word costs.

    uv run python scripts/trigger_bias_bench.py                     # 300 conversational
    uv run python scripts/trigger_bias_bench.py --short             # 280 short clips
    uv run python scripts/trigger_bias_bench.py --model small.en --device cpu

Two arms over the same clips, both through `WhisperTranscriber.text(final=True)` so the
filters in clean.py and the lexicon pass run exactly as the app runs them:

    none      no bias at all
    trigger   "boom enter boom" as `hotwords`, which is what the app did between
              b7bc6aa and its removal

`hotwords` is passed explicitly because the standing bias no longer carries the send
words — that is the thing this bench exists to have measured. The library path is the
same either way: faster-whisper encodes `hotwords` into the `<|startofprev|>` prompt.

Three numbers come out, and the third is the one that mattered:

    WER            pooled per accent group
    invented       the send word appears in text whose reference does not have it
    false SEND     the *whole* utterance decodes to a trigger, which fires a Send

The short slice is where this lives. A trigger is a short utterance by construction, and
a short utterance is where a prompt has the least audio to argue with.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from accent_bench import BENCH, load_wav, norm_words, wer_counts  # noqa: E402

from flow.asr import WhisperTranscriber  # noqa: E402
from flow.diag import bench_identity  # noqa: E402
from flow.edits import SEND_ENTER_WORD, SEND_WORD, plan  # noqa: E402

TRIGGERS = (SEND_WORD, SEND_ENTER_WORD)


class NoLexicon:
    """No terms and no corrections, so the only variable is the trigger bias."""

    def terms(self) -> list[str]:
        return []

    def apply(self, text: str) -> str:
        return text


def invented(hyp: str, ref: str) -> bool:
    h, r = norm_words(hyp), norm_words(ref)
    return any(h.count(w) > r.count(w) for w in norm_words(" ".join(TRIGGERS)))


def false_send(hyp: str) -> bool:
    """Would this text, arriving while a draft is held, press Send?"""
    return plan(hyp, "a held draft", TRIGGERS).kind == "send_trigger"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--short", action="store_true",
                    help="the 280 short clips rather than the 300 conversational ones")
    ap.add_argument("--model", default=None, help="default: whatever the device runs")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    manifest = f"manifest-edacc{'-short' if args.short else ''}.jsonl"
    rows = [json.loads(x) for x in
            (BENCH / manifest).read_text().splitlines() if x]
    if args.limit:
        by_group: dict[str, list] = {}
        for r in rows:
            by_group.setdefault(r["group"], []).append(r)
        per = max(1, args.limit // len(by_group))
        rows = [r for g in by_group.values() for r in g[:per]]

    asr = WhisperTranscriber(args.model, args.model, lexicon=NoLexicon(),
                             device=args.device)
    t0 = time.perf_counter()
    asr.load(True)
    # ASCII: this prints to a Windows console whose code page mangles an em dash.
    print(f"{asr.names[1]} on {asr.device}, loaded in {time.perf_counter() - t0:.1f}s"
          f" - {len(rows)} clips from {manifest}", flush=True)

    arms = {"none": "", "trigger": " ".join(TRIGGERS)}
    stats: dict[str, dict[str, list[int]]] = {a: {} for a in arms}
    flags: dict[str, dict[str, list]] = {
        a: {"invented": [], "false_send": []} for a in arms}
    detail = []

    for i, row in enumerate(rows, 1):
        audio = load_wav(BENCH / row["wav"])
        rec = {"wav": row["wav"], "group": row["group"], "ref": row["ref"]}
        for arm, bias in arms.items():
            asr.take_drops()
            hyp = asr.text(audio, final=True, hotwords=bias)
            d, n = wer_counts(row["ref"], hyp)
            g = stats[arm].setdefault(row["group"], [0, 0])
            g[0] += d
            g[1] += n
            rec[arm] = hyp
            entry = {"wav": row["wav"], "ref": row["ref"], "hyp": hyp}
            if invented(hyp, row["ref"]):
                flags[arm]["invented"].append(entry)
            if false_send(hyp):
                flags[arm]["false_send"].append(entry)
        detail.append(rec)
        if i % 20 == 0 or i == len(rows):
            print(f"  {i}/{len(rows)}", flush=True)

    groups = sorted(stats["none"])
    print(f"\n{'group':<12}{'none':>9}{'trigger':>9}{'delta':>9}{'rel':>8}")
    for g in groups:
        a = stats["none"][g][0] / stats["none"][g][1]
        b = stats["trigger"][g][0] / stats["trigger"][g][1]
        print(f"{g:<12}{a:>9.3f}{b:>9.3f}{b - a:>+9.3f}"
              f"{((b - a) / a * 100) if a else 0:>+7.1f}%")
    ta = (sum(stats["none"][g][0] for g in groups)
          / sum(stats["none"][g][1] for g in groups))
    tb = (sum(stats["trigger"][g][0] for g in groups)
          / sum(stats["trigger"][g][1] for g in groups))
    print(f"{'POOLED':<12}{ta:>9.3f}{tb:>9.3f}{tb - ta:>+9.3f}"
          f"{(tb - ta) / ta * 100:>+7.1f}%")

    for arm in arms:
        print(f"\n{arm:>8}: invented {len(flags[arm]['invented'])}/{len(rows)}   "
              f"false SEND {len(flags[arm]['false_send'])}/{len(rows)}")
        for f in flags[arm]["false_send"]:
            print(f"    SEND  {f['ref'][:48]!r} -> {f['hyp'][:32]!r}")

    if args.out:
        Path(args.out).write_text(json.dumps(
            {"identity": bench_identity(models=(asr.names[1],), device=asr.device),
             "model": asr.names[1], "device": asr.device, "manifest": manifest,
             "clips": len(rows), "stats": stats, "flags": flags,
             "detail": detail}, indent=1))
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
