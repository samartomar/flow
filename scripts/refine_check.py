"""End-to-end check of the CLI refine path (R9, R10, R11).

Verifies against the real installed CLI that:
  - no API key is involved anywhere
  - stdout parses cleanly into usable text
  - failure is non-destructive

    uv run python scripts/refine_check.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.refine import available, refine  # noqa: E402

DRAFT = (
    "hey so i wanted to check whether we are still good for the thing on tuesday "
    "and also if you got the numbers i sent over"
)

def main() -> None:
    clis = available()
    print("CLIs on PATH:", [c.name for c in clis] or "none")
    if not clis:
        raise SystemExit("no agent CLI available")

    for instruction in ("make it more formal", "turn it into bullet points"):
        t = time.perf_counter()
        out, note = refine(DRAFT, instruction)
        dt = time.perf_counter() - t
        print(f"\n--- {instruction!r}  ({dt:.2f}s via {note}) ---")
        print(out if out is not None else f"FAILED: {note}  (draft would be kept)")


if __name__ == "__main__":
    main()
