"""Does the prompt-polish verb keep the facts, and does it fit the budget? (P5)

P5's acceptance test is "a reviewer judges it stronger", which needs a human. Two
properties underneath it do not:

  **Detail retention.** Each dictation carries concrete tokens a reader actually needs
  — a version, an error code, a file path, a person. A polish that drops them has made
  the prompt worse no matter how tidy it reads. Every token is checked for verbatim
  survival, which is exactly what the instruction demands.

  **Latency and shape.** The call has to fit the existing ~7 s CLI budget, and the
  output must be a prompt rather than an essay about one — measured as growth ratio and
  as the absence of the preamble the instruction forbids ("Here is...", "Sure,").

Whether the result is *better* is still a judgement call, so the raw before/after is
printed for a human to read rather than scored.

Usage:  uv run python scripts/polish_check.py [--cli codex|claude]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.refine import CANDIDATES, available, refine  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / ".bench" / "polish.json"

#: (dictation, tokens that must survive verbatim)
CASES = [
    (
        "so the login is broken when you use SSO, um, it throws a five hundred, "
        "this is on version 2.3.1 and it only happens in staging, "
        "I need you to find the root cause",
        ["SSO", "2.3.1", "staging"],
    ),
    (
        "okay so I want to add a retry to the upload thing in "
        "src/uploader/client.py, it should back off exponentially, max three "
        "attempts, and don't retry on a 4xx",
        ["src/uploader/client.py", "three", "4xx"],
    ),
    (
        "the test suite takes eleven minutes now which is too slow, I think it is "
        "the fixtures, can you profile it and tell me what to cut, but don't delete "
        "any test",
        ["eleven", "fixtures"],
    ),
    (
        "write a migration that adds a nullable column called last_seen_at to the "
        "users table, postgres fifteen, and it has to be online, no table lock",
        ["last_seen_at", "users", "fifteen"],
    ),
    (
        "Sameer says the webhook signature check fails intermittently, about one in "
        "twenty, we are on HMAC SHA256, figure out why",
        ["Sameer", "HMAC", "SHA256", "twenty"],
    ),
]

#: A written prompt renders a spoken number as a numeral, which is a *correct*
#: transformation, not a lost detail: "postgres fifteen" came back as "PostgreSQL 15"
#: and a literal check scored that as a failure. Retention is counted both ways.
_SPOKEN_NUMBERS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11",
    "twelve": "12", "thirteen": "13", "fourteen": "14", "fifteen": "15",
    "sixteen": "16", "seventeen": "17", "eighteen": "18", "nineteen": "19",
    "twenty": "20", "thirty": "30", "hundred": "100",
}


def survives(token: str, text: str) -> bool:
    low = text.lower()
    if token.lower() in low:
        return True
    numeral = _SPOKEN_NUMBERS.get(token.lower())
    return bool(numeral) and numeral in low


PREAMBLE = ("here is", "here's", "sure,", "certainly", "of course", "i've", "i have",
            "below is", "this is the prompt")


def main() -> None:
    argv = sys.argv[1:]
    cli = None
    if "--cli" in argv:
        i = argv.index("--cli")
        want = argv[i + 1]
        cli = next((c for c in CANDIDATES if c.name == want), None)
        del argv[i:i + 2]
    if cli is None:
        cli = next(iter(available()), None)
    if cli is None:
        print("no agent CLI on PATH — nothing to measure")
        return

    print(f"CLI={cli.name}, {len(CASES)} dictations\n")
    kept = total = 0
    times, ratios, preambles = [], [], 0
    records = []
    for dictation, tokens in CASES:
        t = time.perf_counter()
        polished, note = refine(dictation, "make it a proper prompt",
                                cli=cli, polish=True)
        dt = time.perf_counter() - t
        if polished is None:
            print(f"  FAILED ({note})")
            records.append({"dictation": dictation, "error": note})
            continue
        times.append(dt)
        ratios.append(len(polished) / len(dictation))
        survived = [tok for tok in tokens if survives(tok, polished)]
        kept += len(survived)
        total += len(tokens)
        lead = polished.strip().lower()
        preambles += any(lead.startswith(p) for p in PREAMBLE)
        lost = set(tokens) - set(survived)
        print(f"  {dt:4.1f}s  x{len(polished) / len(dictation):.1f}  "
              f"kept {len(survived)}/{len(tokens)}"
              + (f"  LOST {sorted(lost)}" if lost else ""))
        records.append({"dictation": dictation, "polished": polished,
                        "tokens": tokens, "kept": survived, "seconds": round(dt, 2)})

    if not times:
        print("\nevery call failed — nothing to report")
        return
    print(f"\ndetail retention: {kept}/{total} tokens ({kept / total:.0%})")
    print(f"latency: median {sorted(times)[len(times) // 2]:.1f}s, max {max(times):.1f}s")
    print(f"growth: median x{sorted(ratios)[len(ratios) // 2]:.1f}")
    print(f"preamble despite being forbidden: {preambles}/{len(times)}")

    OUT.write_text(json.dumps({"cli": cli.name, "records": records}, indent=1),
                   encoding="utf-8")
    print(f"\nbefore/after for a human to judge -> {OUT}")


if __name__ == "__main__":
    main()
