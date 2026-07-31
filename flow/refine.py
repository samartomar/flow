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

#: P5. Dictating a prompt and writing one are different acts: spoken thought arrives as
#: context, correction and afterthought, in the order it occurred to the speaker. This
#: asks for the one transformation that reliably makes it a better prompt, while
#: forbidding the two things that would make it worse: losing the specifics, or
#: inventing new ones.
#:
#: Three decisions here are the reviewer's, taken 2026-07-31 after reading five polished
#: outputs, and each is written into the instruction rather than left to the model:
#:
#: **Request first.** The reader should see what is being asked for without hunting for
#: it. Context and constraints follow, because they qualify a request the reader has
#: already understood.
#:
#: **The request stands alone.** A requirement that *defines the result* belongs in the
#: request — "a nullable last_seen_at column" is what is being asked for, and a request
#: reading "add a column" has lost the point. A standing prohibition ("do not delete any
#: test") is not part of the result and stays a constraint, so the request does not
#: become a restatement of everything.
#:
#: **Normalise only what is certain.** "a five hundred" is HTTP 500 and "postgres
#: fifteen" is PostgreSQL 15 — writing them as spoken makes a prompt look transcribed.
#: Where a number could mean more than one thing, the speaker's words are kept, because
#: guessing a number wrong is worse than leaving it colloquial.
#:
#: "Request" rather than "ask", deliberately: Ask is a product surface (P9 converse
#: mode), and a prompt instruction that says "the ask" invites confusion with it.
#:
#: Detail is called sacred explicitly because that is the failure mode worth guarding.
#: A model asked to "clean up" a rambling technical prompt will happily drop the version
#: number and the exact error string, which are the parts a reader actually needs.
_POLISH_PROMPT = (
    "Rewrite the dictated text below as a clear prompt for an AI coding assistant.\n"
    "Order it as: the REQUEST first, then supporting context, then any constraints. "
    "The first line must state what is being asked for.\n"
    "The request must be independently actionable: fold in the requirements that "
    "define the result being asked for (a column that must be nullable is 'a nullable "
    "column'), but leave standing rules and prohibitions as separate constraints "
    "rather than repeating them in the request.\n"
    "Normalise technical numbers and product names where the meaning is certain: "
    "'a five hundred' is HTTP 500, 'postgres fifteen' is PostgreSQL 15, 'version two "
    "point three point one' is version 2.3.1. Where a number or term could mean more "
    "than one thing, keep the speaker's words rather than guessing.\n"
    "Apart from those normalisations, keep EVERY concrete detail the speaker gave - "
    "names, versions, file paths, error text, identifiers - verbatim. Invent nothing "
    "that was not said.\n"
    "Remove filler, false starts, repetition and thinking-aloud.\n"
    "Output ONLY the prompt: no preamble, no explanation, no code fences, no "
    "surrounding quotes, no headings unless the speaker asked for them.\n\n"
    "DICTATED TEXT:\n{text}"
)

#: A polish legitimately grows the text — structure costs words that rambling does not
#: spend — so the commentary guard is looser here than for a revision, or it would
#: reject the successful case. Still bounded: past this it is prose *about* the prompt.
_POLISH_GROWTH = 8
_POLISH_SLACK = 600


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


#: P9. Converse mode sends the draft to the CLI as a *question* rather than as text to
#: be rewritten, so none of the rewrite discipline applies: the answer is allowed to be
#: longer than the input, allowed to be prose, and must not be measured against the
#: draft's length. What it does need is brevity, because the reply is read on a pill
#: above a floating window and, optionally, spoken aloud — neither survives an essay.
_ASK_PROMPT = (
    "Answer the question below for a developer who is speaking to you, not typing.\n"
    "Reply in at most {sentences} sentences of plain prose. No preamble, no headings, "
    "no bullet lists, no code fences unless code is the answer.\n"
    "If you need something you were not told, say what is missing in one sentence "
    "rather than guessing.\n\n"
    "QUESTION:\n{text}"
)

#: How long an answer may be before it is treated as the model ignoring the brief. Far
#: looser than the rewrite guard — an answer has no input length to be measured against
#: — but not unbounded, because the pill has to render it.
ASK_MAX_CHARS = 4000

#: Sentences requested. Three is the shortest that can carry an answer plus its caveat.
ASK_SENTENCES = 3


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
    polish: bool = False,
    context: list[str] | None = None,
) -> tuple[str | None, str]:
    """Apply a semantic instruction to `text`.

    `polish=True` ignores the instruction and runs the P5 prompt-shaping pass instead:
    the user asked for a *kind* of rewrite, not for their words to be interpreted.

    `context` is the thread tail (P6) — prompts already sent in this session. It is
    labelled as background and explicitly excluded from the output, because a follow-up
    like "and do the same for the other endpoint" is meaningless without it and
    disastrous if the model decides to rewrite it too.

    Returns `(revised_text, note)`, or `(None, reason)` on any failure. Failure must
    always be non-destructive: the caller keeps the pre-edit draft, so a CLI that is
    slow, missing or misbehaving degrades the feature instead of losing the user's words.
    """
    chosen = cli or next(iter(available()), None)
    if chosen is None:
        return None, "no agent CLI found on PATH"

    head, tail = _split_tail(text)
    prompt = (
        _POLISH_PROMPT.format(text=tail)
        if polish
        else _PROMPT.format(instruction=instruction, text=tail)
    )
    if context:
        prior = chr(10).join(f"- {turn}" for turn in context)
        prompt = (
            "EARLIER IN THIS THREAD (background only - do not repeat or rewrite it):"
            + chr(10) + prior + chr(10) + chr(10) + prompt
        )

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
    growth, slack = (_POLISH_GROWTH, _POLISH_SLACK) if polish else (4, 200)
    if len(revised) > growth * len(tail) + slack:
        return None, f"{chosen.name} returned commentary, not a revision"

    return head + revised, chosen.name


def ask(
    question: str,
    *,
    cli: Cli | None = None,
    timeout: float = TIMEOUT_SEC,
    cwd: str | None = None,
    context: list[str] | None = None,
    sentences: int = ASK_SENTENCES,
) -> tuple[str | None, str]:
    """P9: put a question to the agent CLI and return its answer.

    The sibling of `refine`, and deliberately not the same function. `refine` rewrites
    the user's words and guards hard against the model returning anything longer than
    what it was given, because commentary pasted into a draft is a defect. An answer
    *is* commentary — that is what was asked for — so that guard would reject every
    correct result.

    `context` is the same thread tail P6 already keeps. There is no persistent CLI
    process: continuity is re-sent, not held open. That keeps R11 (the CLI is never on
    the hot path) and R8 (a long session costs what a short one costs) intact, and it
    means a crashed or upgraded CLI cannot take the conversation with it.

    Returns `(answer, cli_name)` or `(None, reason)`. Failure is always non-destructive:
    the caller keeps the draft, so an absent or slow CLI degrades converse mode to
    dictate mode rather than losing what was said.
    """
    chosen = cli or next(iter(available()), None)
    if chosen is None:
        return None, "no agent CLI found on PATH"

    _, tail = _split_tail(question)
    prompt = _ASK_PROMPT.format(text=tail, sentences=sentences)
    if context:
        prior = chr(10).join(f"- {turn}" for turn in context)
        prompt = (
            "EARLIER IN THIS CONVERSATION (for continuity - do not answer these again):"
            + chr(10) + prior + chr(10) + chr(10) + prompt
        )

    try:
        proc = subprocess.run(
            [*chosen.argv, prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,  # codex blocks on stdin otherwise
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

    answer = _clean(proc.stdout)
    if not answer:
        return None, f"{chosen.name} returned nothing"
    if len(answer) > ASK_MAX_CHARS:
        answer = answer[: ASK_MAX_CHARS - 1].rstrip() + "…"
    return answer, chosen.name
