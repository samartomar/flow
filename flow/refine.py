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

import os
import re
import shutil
import subprocess
import threading
import time
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
    #: False means **detection only**: this CLI may be found on PATH and named, and it is
    #: never invoked. An invocation shape is not a thing to remember — it is a thing
    #: somebody ran on a machine that had the CLI — and an entry whose shape has not been
    #: run would otherwise sit here looking exactly like one that has.
    verified: bool = True


#: Order is the preference order — codex first, per R10.
#:
#: **An unverified entry carries no shape at all**, only the executable name that
#: detection needs. That is the rule rather than a convention, and `tests/test_refine.py`
#: asserts it of every entry: a plausible-looking argv sitting here unused is still a
#: guess, and the next person to read this file has no way to tell a guess from a
#: measurement once both are written in the same form.
#:
#: **`opencode` stays inert, and the attempt to verify it is why the rule is worth
#: having.** Run here on 2026-08-02: `opencode run "Reply with exactly: PONG"` exited 0 in
#: 8.2 s with `PONG` alone on stdout and its banner on stderr — the exact stream
#: discipline this module's docstring requires, and enough to look verified. It is not.
#: Every prompt this module sends is multi-line, and a multi-line prompt came back
#: `No SECRET was provided.`: the `opencode` on PATH here is `opencode.CMD`, an `npm -g`
#: batch shim, and a batch shim forwards `%*` through cmd.exe, which **truncates the
#: argument at the first newline**. Measured directly against a shim of the same shape:
#: `['line one']` arrived where `['line one\nline two\nline three']` was sent, while the
#: same argument through a real executable arrived whole. So what was measured is the
#: install, not opencode's contract, and a machine where opencode is a real binary would
#: answer a different question. Guessing which is what `verified` exists to forbid.
#:
#: **`kiro` is deliberately not here.** Verified the same day and the answer was that it is
#: not an agent CLI at all: the `kiro` on PATH is the IDE launcher — a VS Code fork whose
#: `--help` offers `--diff`, `--goto` and `--wait` and no headless prompt mode. Detecting
#: it and saying "not yet verified" would be false, because it *is* verified; adding it
#: would open an editor window instead of answering a question.
CANDIDATES: tuple[Cli, ...] = (
    Cli("codex", ("codex", "exec", "--skip-git-repo-check")),
    Cli("claude", ("claude", "-p")),
    Cli("opencode", ("opencode",), verified=False),
    Cli("copilot", ("copilot",), verified=False),
    Cli("gemini", ("gemini",), verified=False),
)


def available() -> list[Cli]:
    """The CLIs that may be *invoked*: on PATH, and with a shape somebody has run.

    Keeps its old meaning exactly, which is what lets every existing caller —
    `_invoke_any`, `Session._provider`, the pill's marker, the menu's picker — stay
    correct without knowing `verified` exists.
    """
    return [c for c in CANDIDATES if c.verified and shutil.which(c.argv[0])]


def detected() -> list[Cli]:
    """Everything found on PATH, verified or not. The only thing that may name the rest."""
    return [c for c in CANDIDATES if shutil.which(c.argv[0])]


def unverified() -> list[Cli]:
    """On this machine, and inert. Startup says so; nothing calls them."""
    return [c for c in detected() if not c.verified]


def unverified_note(cli: Cli) -> str:
    """What to say about a CLI that is here and has never been run."""
    return f"found {cli.name}, not yet verified - see NEEDS_YOU"


def named(name: str) -> Cli | None:
    """Look a CLI up by name, so a user can pin one rather than take the order.

    Searches every candidate including the inert ones, deliberately: `--cli gemini` on a
    machine that has gemini deserves the true reason rather than "not on PATH", which
    would be a lie about the one thing the user can check for themselves.
    """
    want = name.strip().lower()
    return next((c for c in CANDIDATES if c.name == want), None)


def _invoke_any(
    cli: Cli | None,
    prompt: str,
    *,
    timeout: float,
    cwd: str | None = None,
    cancel: threading.Event | None = None,
) -> tuple[str | None, str, Cli | None]:
    """Run `prompt`, falling through the preference order until one CLI answers.

    `CANDIDATES` has always been documented as a preference order and startup has always
    printed "(fallbacks: claude)", but both entry points took `next(iter(available()))`
    and stopped there — so the fallback was a promise the code never kept. The first
    person to hit a `codex` timeout got a dead feature and a message naming a second CLI
    that was installed, working, and never tried.

    Falls over on *not answering at all*: failing to start, exiting non-zero, timing out,
    or returning nothing. A CLI that answers badly has still answered, and the callers'
    own quality guards deal with that — retrying the same prompt on another model would
    double the wait to relitigate a judgement.

    An explicit `cli=` is a decision, not a preference, so it is never second-guessed.
    Cancellation stops the walk: quitting should not start a second process.
    """
    if cli is not None:
        out, reason = _invoke(cli, prompt, timeout=timeout, cwd=cwd, cancel=cancel)
        return out, reason, cli

    reasons: list[str] = []
    for candidate in available():
        out, reason = _invoke(candidate, prompt, timeout=timeout, cwd=cwd, cancel=cancel)
        if out is not None:
            return out, "", candidate
        reasons.append(reason)
        if cancel is not None and cancel.is_set():
            break
    if not reasons:
        # Appended rather than substituted: "no agent CLI found on PATH" stays true —
        # none that may be *called* was found — and the detail says what is sitting there
        # unusable, which is the difference between an empty PATH and an unfinished entry.
        pending = ", ".join(unverified_note(c) for c in unverified())
        return None, "no agent CLI found on PATH" + (f" ({pending})" if pending else ""), None
    return None, "; then ".join(reasons), None


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

#: P9 profiles. When the request is for a piece of work — a prompt, a plan, a list —
#: the three-sentence brief is exactly wrong: it truncates the thing the conversation
#: was for. This prompt drops the ceiling and honours requested structure instead.
#: The caller decides which brief applies (edits.is_artifact_request), from the
#: request, never from the answer.
_ASK_ARTIFACT_PROMPT = (
    "The developer speaking to you has asked for a complete piece of work - a prompt, "
    "a plan, a list, a document. Produce the whole thing.\n"
    "No length ceiling applies; do not summarise parts away. Honor any structure the "
    "request names - headings, bullets, a table - and impose none it does not.\n"
    "Keep every concrete detail from the conversation that the work needs - names, "
    "versions, file paths, error text - verbatim. Invent nothing that was not said.\n"
    "Output ONLY the work itself: no preamble, no explanation around it, no code "
    "fences unless code is the work.\n\n"
    "REQUEST:\n{text}"
)

#: The artifact ceiling is a render bound, not a brief: the bubble scrolls, and
#: truncating a prompt someone asked for in full is worse than a tall bubble. Three
#: times the conversational cap covers the longest artifact seen in design review
#: (~60 lines) with room; past it the model is padding, not working.
ASK_ARTIFACT_MAX_CHARS = 12_000


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


#: How often a running call checks whether anyone still wants it. Small enough that
#: quitting feels immediate, large enough to be free against a call that takes ~7 s.
_POLL_SEC = 0.1


def _kill_tree(proc: subprocess.Popen) -> None:
    """End the call and everything it started.

    `proc.kill()` reaches only the process this module launched, and that is not the
    process doing the work: `codex` is a launcher that runs `node`. Killing the
    launcher leaves the model call running — still holding the pipe it inherited, so
    the read would block on it anyway, which is how a call could time out while the
    thing it timed out on carried on. Windows has no process group to signal, so the
    tree walk is `taskkill /T`; it ships with the OS and costs no dependency (R16),
    and `send_check.py` already reaps its target window the same way.
    """
    if proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                timeout=5.0,
            )
        except (OSError, subprocess.SubprocessError):
            pass  # fall through to the direct kill, which is better than nothing
    try:
        proc.kill()
    except OSError:
        pass


def _abandon(proc: subprocess.Popen, reason: str) -> tuple[None, str]:
    """Kill a call and reap it, so no thread of ours is left waiting on a dead pipe."""
    _kill_tree(proc)
    try:
        proc.communicate(timeout=5.0)
    except subprocess.TimeoutExpired:
        pass
    return None, reason


def _invoke(
    cli: Cli,
    prompt: str,
    *,
    timeout: float,
    cwd: str | None = None,
    cancel: threading.Event | None = None,
) -> tuple[str | None, str]:
    """Run one CLI call. Returns `(stdout, "")`, or `(None, reason)` on any failure.

    The one place this module starts a process, so that ending one early is also in
    one place. `subprocess.run` could not do that: it blocks until the child exits,
    so closing Flow left the call running to completion — up to `TIMEOUT_SEC` of a
    child nobody was waiting for, and its own child after that.

    `cancel` is polled rather than waited on. The child's output has to be drained
    while we wait or a full pipe blocks it, and `communicate` is what drains it, so
    the wait has to be the one `communicate` is already doing.
    """
    if cancel is not None and cancel.is_set():
        return None, f"{cli.name} was cancelled"

    # Launch what `available()` found, not the name it looked up. The two resolvers do
    # not agree on Windows: `shutil.which` honours `PATHEXT` and finds `codex.cmd`, while
    # `CreateProcess` — which is what a bare name in `Popen` reaches — searches PATH
    # appending only `.exe`. So on a machine where an agent CLI is an `npm -g` shim,
    # which is how both CLIs document installing them, startup said "refine CLI: codex"
    # and every call came back "codex failed to start: [WinError 2] The system cannot
    # find the file specified". Both statements were true, which is what made it
    # baffling. Found on a Hyper-V VM on 2026-08-02; invisible on the machine this was
    # built on, where WinGet had put a real `codex.EXE` on the path.
    #
    # `or cli.argv[0]` keeps the genuinely-absent case honest: nothing is fabricated,
    # the bare name goes to Popen, and the OSError below still says what is missing.
    executable = shutil.which(cli.argv[0]) or cli.argv[0]

    try:
        proc = subprocess.Popen(
            [executable, *cli.argv[1:], prompt],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # codex waits on stdin ("Reading additional input from stdin..."), so it
            # must be closed explicitly or the call can hang until the timeout.
            stdin=subprocess.DEVNULL,
            text=True,
            cwd=cwd,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        return None, f"{cli.name} failed to start: {exc}"

    deadline = time.monotonic() + timeout
    while True:
        if cancel is not None and cancel.is_set():
            return _abandon(proc, f"{cli.name} was cancelled")
        left = deadline - time.monotonic()
        if left <= 0:
            return _abandon(proc, f"{cli.name} timed out after {timeout:.0f}s")
        try:
            out, err = proc.communicate(timeout=min(_POLL_SEC, left))
        except subprocess.TimeoutExpired:
            continue  # retrying communicate loses no output; the docs promise that
        break

    if proc.returncode != 0:
        first = (err or "").strip().splitlines()
        return None, f"{cli.name} exited {proc.returncode}: {first[0] if first else ''}"
    return out, ""


def tail_sent(text: str) -> int:
    """How much of `text` a CLI call will actually see, in characters.

    `len(text)` for anything inside `MAX_CHARS`. Asked here rather than computed by the
    caller because the cut walks forward to a sentence boundary — so the real figure is
    a little under `MAX_CHARS` and varies with the text, and a note quoting the constant
    would be a guess dressed as a measurement.
    """
    return len(_split_tail(text)[1])


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
    cancel: threading.Event | None = None,
) -> tuple[str | None, str]:
    """Apply a semantic instruction to `text`.

    `polish=True` ignores the instruction and runs the P5 prompt-shaping pass instead:
    the user asked for a *kind* of rewrite, not for their words to be interpreted.

    `context` is the thread tail (P6) — prompts already sent in this session. It is
    labelled as background and explicitly excluded from the output, because a follow-up
    like "and do the same for the other endpoint" is meaningless without it and
    disastrous if the model decides to rewrite it too.

    `cancel` abandons the call — the session sets it on close, so quitting does not
    wait out a rewrite nobody is going to read.

    Returns `(revised_text, note)`, or `(None, reason)` on any failure. Failure must
    always be non-destructive: the caller keeps the pre-edit draft, so a CLI that is
    slow, missing or misbehaving degrades the feature instead of losing the user's words.
    """
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

    out, reason, chosen = _invoke_any(
        cli, prompt, timeout=timeout, cwd=cwd, cancel=cancel
    )
    if out is None:
        return None, reason

    revised = _clean(out)
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
    cancel: threading.Event | None = None,
    artifact: bool = False,
) -> tuple[str | None, str]:
    """P9: put a question to the agent CLI and return its answer.

    `artifact=True` swaps the three-sentence conversational brief for the
    deliverable one: no length ceiling in the prompt, requested structure honoured,
    and a wider render bound (`ASK_ARTIFACT_MAX_CHARS`). The caller chooses from the
    *request* — see `edits.is_artifact_request` — because an answer's length cannot
    reveal which brief it should have been given.

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
    _, tail = _split_tail(question)
    prompt = (
        _ASK_ARTIFACT_PROMPT.format(text=tail)
        if artifact
        else _ASK_PROMPT.format(text=tail, sentences=sentences)
    )
    if context:
        prior = chr(10).join(f"- {turn}" for turn in context)
        prompt = (
            "EARLIER IN THIS CONVERSATION (for continuity - do not answer these again):"
            + chr(10) + prior + chr(10) + chr(10) + prompt
        )

    out, reason, chosen = _invoke_any(
        cli, prompt, timeout=timeout, cwd=cwd, cancel=cancel
    )
    if out is None:
        return None, reason

    answer = _clean(out)
    if not answer:
        return None, f"{chosen.name} returned nothing"
    cap = ASK_ARTIFACT_MAX_CHARS if artifact else ASK_MAX_CHARS
    if len(answer) > cap:
        answer = answer[: cap - 1].rstrip() + "…"
    return answer, chosen.name
