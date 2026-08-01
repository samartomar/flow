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

from flow.diag import bench_identity  # noqa: E402
from flow.refine import CANDIDATES, available, refine  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / ".bench" / "polish.json"

#: Each case carries what the three reviewer decisions predict for it:
#:   tokens   - concrete details that must survive at all (retention)
#:   numbers  - spoken forms whose normalised rendering must appear (decision 3)
#:   request  - what the FIRST line must contain to be independently actionable
#:              (decisions 1 and 2)
CASES = [
    {
        "dictation": (
            "so the login is broken when you use SSO, um, it throws a five hundred, "
            "this is on version 2.3.1 and it only happens in staging, "
            "I need you to find the root cause"
        ),
        "tokens": ["SSO", "2.3.1", "staging"],
        "numbers": ["500"],
        "request": ["root cause"],
    },
    {
        "dictation": (
            "okay so I want to add a retry to the upload thing in "
            "src/uploader/client.py, it should back off exponentially, max three "
            "attempts, and don't retry on a 4xx"
        ),
        "tokens": ["src/uploader/client.py", "three", "4xx"],
        "numbers": [],
        "request": ["retry"],
    },
    {
        "dictation": (
            "the test suite takes eleven minutes now which is too slow, I think it is "
            "the fixtures, can you profile it and tell me what to cut, but don't "
            "delete any test"
        ),
        "tokens": ["eleven", "fixtures"],
        "numbers": [],
        # "do not delete any test" is a standing prohibition: it belongs in the
        # constraints, NOT restated in the request.
        "request": ["profile"],
    },
    {
        "dictation": (
            "write a migration that adds a nullable column called last_seen_at to the "
            "users table, postgres fifteen, and it has to be online, no table lock"
        ),
        "tokens": ["last_seen_at", "users", "fifteen"],
        "numbers": ["15"],
        # The reviewer's own example: "nullable" defines the column, so it belongs in
        # the request rather than being demoted to a constraint.
        "request": ["nullable", "last_seen_at"],
    },
    {
        "dictation": (
            "Sameer says the webhook signature check fails intermittently, about one "
            "in twenty, we are on HMAC SHA256, figure out why"
        ),
        "tokens": ["Sameer", "HMAC", "SHA256", "twenty"],
        "numbers": [],
        "request": ["why"],
    },
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


def mentions(word: str, text: str) -> bool:
    """Whether the request names this thing, allowing for ordinary inflection.

    A prompt saying "add exponential-backoff **retries**" has stated the request that
    the dictation called "a **retry**". Scoring that as a miss made the metric wrong
    for the third time in this file's short life — first "fifteen" against
    "PostgreSQL 15", now this. The word is what matters, not its ending.
    """
    low, want = text.lower(), word.lower()
    if want in low:
        return True
    return len(want) > 4 and want[:-1] in low


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
        print("no agent CLI on PATH - nothing to measure")
        return

    print(f"CLI={cli.name}, {len(CASES)} dictations")
    print("decisions under test: request first | request self-contained | "
          "numbers normalised")
    print()

    kept = total = 0
    normalised = normalisable = 0
    request_ok = request_total = 0
    times, ratios, preambles = [], [], 0
    records = []

    for case in CASES:
        dictation = case["dictation"]
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
        lead = polished.strip().lower()
        preambles += any(lead.startswith(pre) for pre in PREAMBLE)

        survived = [tok for tok in case["tokens"] if survives(tok, polished)]
        kept += len(survived)
        total += len(case["tokens"])

        # Decision 3: the normalised rendering is the one that has to appear.
        got_numbers = [n for n in case["numbers"] if n in polished]
        normalised += len(got_numbers)
        normalisable += len(case["numbers"])

        # Decisions 1 and 2, both read off the FIRST line: it is the request, and it
        # carries the requirements that define the result being asked for.
        first = next((ln for ln in polished.splitlines() if ln.strip()), "")
        in_request = [w for w in case["request"] if mentions(w, first)]
        request_ok += len(in_request)
        request_total += len(case["request"])

        missing = sorted(
            (set(case["tokens"]) - set(survived))
            | (set(case["numbers"]) - set(got_numbers))
            | (set(case["request"]) - set(in_request))
        )
        print(f"  {dt:4.1f}s  x{len(polished) / len(dictation):.1f}  "
              f"detail {len(survived)}/{len(case['tokens'])}  "
              f"request {len(in_request)}/{len(case['request'])}"
              + (f"   MISSING {missing}" if missing else ""))
        print(f"        first line: {first[:88]}")
        records.append({**case, "polished": polished, "first_line": first,
                        "seconds": round(dt, 2)})

    if not times:
        print()
        print("every call failed - nothing to report")
        return

    print()
    print(f"detail retention:       {kept}/{total}")
    print(f"request self-contained: {request_ok}/{request_total}  (from the first line)")
    print(f"numbers normalised:     {normalised}/{normalisable}")
    print(f"latency:                median {sorted(times)[len(times) // 2]:.1f}s, "
          f"max {max(times):.1f}s")
    print(f"growth:                 median x{sorted(ratios)[len(ratios) // 2]:.1f}")
    print(f"preamble:               {preambles}/{len(times)}")

    # The only bench whose subject is the CLI rather than a model, so it is the only
    # one that pays a process start to name one.
    OUT.write_text(json.dumps({"identity": bench_identity(clis=(cli.name,)),
                               "cli": cli.name, "records": records}, indent=1),
                   encoding="utf-8")
    print()
    print(f"before/after for a human to judge -> {OUT}")


if __name__ == "__main__":
    main()


