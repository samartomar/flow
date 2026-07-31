"""Semantic rewrites via an already-authenticated agent CLI (R9, R10, R11).

No API key is ever read, stored or passed by this code. It shells out to a CLI the
user has already signed into, which is the whole point of R9.

Reached only for genuine rewrite requests. Measured cost of one call is ~7 s and
~19.7 k tokens (PROGRESS.md, stage 2a), so `edits.py` keeps every literal correction
away from here.

Stream discipline matters: both CLIs write **only the answer to stdout** and put their
banner, prompt echo and token accounting on **stderr**. Capturing them separately means
no output parser is needed — merging them is what makes the output look polluted.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass

#: R11: never hand the CLI an unbounded draft. Past this, only the tail is sent.
MAX_CHARS = 2000
TIMEOUT_SEC = 20.0

_PROMPT = (
    "Revise the text below according to the instruction.\n"
    "Output ONLY the revised text: no preamble, no explanation, no code fences, "
    "no surrounding quotes.\n\n"
    "INSTRUCTION: {instruction}\n\n"
    "TEXT:\n{text}"
)


@dataclass(frozen=True)
class Cli:
    name: str
    argv: tuple[str, ...]  # the prompt is appended as the final argument


#: Order is the preference order — codex first, per R10.
CANDIDATES: tuple[Cli, ...] = (
    Cli("codex", ("codex", "exec", "--skip-git-repo-check")),
    Cli("claude", ("claude", "-p")),
)


def available() -> list[Cli]:
    return [c for c in CANDIDATES if shutil.which(c.argv[0])]


def _split_tail(text: str) -> tuple[str, str]:
    """Return (head_kept_verbatim, tail_to_refine) respecting MAX_CHARS."""
    if len(text) <= MAX_CHARS:
        return "", text
    cut = len(text) - MAX_CHARS
    # Prefer a sentence boundary so the CLI is not handed a fragment.
    m = re.search(r"(?<=[.!?])\s+", text[cut:])
    if m:
        cut += m.end()
    return text[:cut], text[cut:]


def _clean(out: str) -> str:
    """Light defensive tidy. Deliberately not a parser — stdout is already clean."""
    s = out.strip()
    if s.startswith("```"):
        lines = [ln for ln in s.splitlines() if not ln.strip().startswith("```")]
        s = "\n".join(lines).strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1].strip()
    return s


def refine(
    text: str,
    instruction: str,
    *,
    cli: Cli | None = None,
    timeout: float = TIMEOUT_SEC,
    cwd: str | None = None,
) -> tuple[str | None, str]:
    """Apply a semantic instruction to `text`.

    Returns `(revised_text, note)`, or `(None, reason)` on any failure. Failure must
    always be non-destructive: the caller keeps the pre-edit draft, so a CLI that is
    slow, missing or misbehaving degrades the feature instead of losing the user's words.
    """
    chosen = cli or next(iter(available()), None)
    if chosen is None:
        return None, "no agent CLI found on PATH"

    head, tail = _split_tail(text)
    prompt = _PROMPT.format(instruction=instruction, text=tail)

    try:
        proc = subprocess.run(
            [*chosen.argv, prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
            # codex waits on stdin ("Reading additional input from stdin..."), so it
            # must be closed explicitly or the call can hang until the timeout.
            stdin=subprocess.DEVNULL,
            cwd=cwd,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return None, f"{chosen.name} timed out after {timeout:.0f}s"
    except OSError as exc:
        return None, f"{chosen.name} failed to start: {exc}"

    if proc.returncode != 0:
        first = (proc.stderr or "").strip().splitlines()
        return None, f"{chosen.name} exited {proc.returncode}: {first[0] if first else ''}"

    revised = _clean(proc.stdout)
    if not revised:
        return None, f"{chosen.name} returned nothing"

    # A rewrite that balloons is almost always the model explaining itself rather than
    # revising. Refuse it rather than pasting commentary into the user's text.
    if len(revised) > 4 * len(tail) + 200:
        return None, f"{chosen.name} returned commentary, not a revision"

    return head + revised, chosen.name
