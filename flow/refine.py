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
    #: True means this CLI takes its prompt on **stdin** rather than as the last argument,
    #: which is what makes it usable behind a `.cmd` launcher (see `SHIM_SUFFIXES`). Off
    #: by default and off for everything shipped, on the same discipline `verified`
    #: carries: it goes on when somebody has run that CLI that way on a machine that has
    #: it, never from memory. codex is measured *hanging* on an open stdin — "Reading
    #: additional input from stdin..." — which is exactly why this is per-CLI and not a
    #: switch for the module.
    stdin_ok: bool = False
    #: Absolute paths (with `%VARS%` still in them) to look at when PATH does not have this
    #: CLI. Empty for everything that installs onto PATH and stays there, which is most
    #: things; see `probed` for the one measurement that earned this field.
    probe: tuple[str, ...] = ()
    #: How long this CLI needs when the module's global is not enough. `None` — every other
    #: entry — means the caller's number, which is `TIMEOUT_SEC` unless `--cli-timeout`
    #: moved it.
    #:
    #: A **floor** on the wait rather than a replacement for it: `_invoke` waits
    #: `max(caller, this)`. That is a decision and not a shortcut. `--cli-timeout` is
    #: documented as the knob that *raises* the wait, so a per-CLI value that simply won
    #: would put the one CLI measured needing the most time out of the reach of the only
    #: flag for it. Read the other way it is the same sentence: a global lowered below what
    #: a CLI was measured to need would re-create that CLI's incident on purpose.
    timeout_sec: float | None = None
    #: What the pill's marker slot draws for this CLI when the name will not fit it. Empty
    #: for everything that already fits, which is most things — see `ui.Pill.MARKER_MAX`
    #: for the wall and `CANDIDATES` for the one entry that has hit it.
    marker: str = ""


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
#:
#: **`kiro-cli` is verified live**, this machine, 2026-08-02, all four legs: `--version`
#: reports `kiro-cli-chat 2.16.0`; `chat --no-interactive --trust-tools= "<prompt>"`
#: answers in ~1 s at exit 0 with the answer on stdout; a SECRET on the last line of a
#: three-line prompt came back **verbatim** through `Popen` list-argv — a native `.exe`, so
#: none of the shim truncation below applies; and bad arguments exit 2, loudly.
#: `--trust-tools=` empty is the courier default: no tool of its own runs without being
#: asked, which is what an agent CLI used as a rewriter must never do. It meters (~0.10
#: credits a call) and prints a status line for it, which `_clean` strips per CLI.
#: Note the two names: this is `kiro-cli`, and the `kiro` above is the IDE launcher.
#:
#: **kiro-cli is also the entry that needed both of the per-CLI fields**, and the same
#: measurement earned them. The identical one-line call took **4.3 s in a bare directory
#: and 35.8 s inside a workspace whose `.kiro` settings declare MCP servers**: kiro-cli
#: spawns the project's MCP servers on every `chat` invocation, uvx-resolved and cold, so
#: the global 20 s executed the call at second twenty every time — in exactly the
#: workspaces this is used for. No flag skips the startup (`--require-mcp-startup` exists;
#: its inverse does not), and rewriting the user's kiro settings is out of bounds: Flow
#: does not reconfigure other tools. `timeout_sec=60` is 35.8 measured plus headroom. The
#: honest residue is not Flow's to fix — ~36 s a turn in an MCP-heavy workspace is
#: kiro-cli's startup cost, the cure is upstream (a persistent serve mode, or a shorter
#: server list), and until then the pin menu makes "codex for this workspace" one tap.
#: `marker="kiro"` is the other half: 8 characters do not fit the pill's slot, so without
#: an alias the pill draws `ASK` while kiro-cli is the CLI that would answer.
CANDIDATES: tuple[Cli, ...] = (
    Cli("codex", ("codex", "exec", "--skip-git-repo-check")),
    Cli("claude", ("claude", "-p")),
    Cli("kiro-cli", ("kiro-cli", "chat", "--no-interactive", "--trust-tools="),
        probe=(r"%LOCALAPPDATA%\Kiro-Cli\kiro-cli.exe",),
        timeout_sec=60.0, marker="kiro"),
    Cli("opencode", ("opencode",), verified=False),
    Cli("copilot", ("copilot",), verified=False),
    Cli("gemini", ("gemini",), verified=False),
)


#: Launcher suffixes that cannot carry a multi-line prompt on the argv, and so are refused
#: before a process starts.
#:
#: A `.cmd`/`.bat` forwards `%*` through cmd.exe, which **stops at the first newline**.
#: Every prompt this module sends is multi-line — `_PROMPT`, `_POLISH_PROMPT`,
#: `_ASK_PROMPT`, `_ASK_ARTIFACT_PROMPT` all are — so a CLI installed as an `npm -g` shim,
#: which is the install both agent CLIs document, receives the framing and none of the
#: user's text, **exits 0, and answers fluently about nothing**. There is no error
#: anywhere: the reply is confident and about a question nobody asked. Measured directly
#: on 2026-08-02 against a shim of that shape — `['line one']` arrived where
#: `['line one\nline two\nline three']` was sent — and `tests/test_refine.py` keeps
#: measuring it, because a claim about what another program does becomes folklore the day
#: it stops being checked.
#:
#: Refusing is what ships rather than repairing, and the reason is that the repair cannot
#: be picked here: the candidate that matters is stdin delivery, that is per-CLI (codex
#: hangs on an open stdin), and this machine has no npm shim of either CLI to verify
#: against. Loud beats fluent-and-wrong. `stdin_ok` is the repair, off until measured.
SHIM_SUFFIXES = (".cmd", ".bat")


def probed(cli: Cli) -> str | None:
    """An install this entry knows how to find when PATH does not have it.

    PATH is asked first and is the normal answer: the Kiro MSI adds
    `%LOCALAPPDATA%\\Kiro-Cli\\` to the *user* PATH, so a fresh shell finds `kiro-cli` like
    anything else. A process started from a shell that predates the install does not —
    measured on this machine in exactly that state, `shutil.which("kiro-cli")` returned
    `None` while the executable at the probe path answered a real prompt in a second. So
    this is the difference between working and not until the next sign-in, rather than
    insurance against nothing.

    A list of paths and not a search, deliberately: a probe that went looking would be the
    guessed shape `verified` exists to forbid, one directory along.
    """
    for candidate in cli.probe:
        path = os.path.expandvars(candidate)
        if os.path.isfile(path):
            return path
    return None


def trusted(path: str | None) -> str | None:
    """`path`, if it came from somewhere a program is allowed to come from. Else None.

    Windows searches the current directory before PATH for a bare name, so a repository
    holding `codex.EXE` supplies the codex — and Flow is launched *inside* project
    directories by design, because `--cwd` is the workshop and the workshop is the
    product. Cloning a repository is the whole attack.

    `main()` sets `NoDefaultCurrentDirectoryInExePath`, which closes the search itself and
    for every child process too. This is the belt under that brace: a caller resolving
    before `main()` runs, an embedding that never calls it, or a PATH with `.` written
    into it all reach here instead. Two rules, and neither needs the environment to have
    been arranged — a result must be absolute, and its directory must not be the one Flow
    happens to be sitting in.
    """
    if not path or not os.path.isabs(path):
        return None
    try:
        if os.path.realpath(os.path.dirname(path)) == os.path.realpath(os.getcwd()):
            return None
    except OSError:
        return None
    return path


def resolve(cli: Cli) -> str | None:
    """Where this CLI actually is, or None. The one answer detection and launch share.

    They used to ask separately and could disagree — `shutil.which` honours `PATHEXT`
    while `CreateProcess` appends only `.exe`, which is how startup once named a CLI that
    every call then failed to start. One function now, so a second resolver cannot appear
    without somebody noticing it.

    A refused `which` result falls through to the entry's own probe rather than ending the
    search: a workspace copy shadowing a real install must not take the CLI away from the
    user, and `probed` is a list of literal paths written in the entry itself.
    """
    return trusted(shutil.which(cli.argv[0])) or probed(cli)


def available() -> list[Cli]:
    """The CLIs that may be *invoked*: found here, and with a shape somebody has run.

    Keeps its old meaning exactly, which is what lets every existing caller —
    `_invoke_any`, `Session._provider`, the pill's marker, the menu's picker — stay
    correct without knowing `verified` exists.
    """
    return [c for c in CANDIDATES if c.verified and resolve(c)]


def detected() -> list[Cli]:
    """Everything found here, verified or not. The only thing that may name the rest."""
    return [c for c in CANDIDATES if resolve(c)]


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


def _system_tool(name: str) -> str:
    """A stock Windows tool, addressed rather than looked up.

    `%SystemRoot%` and not a hard-coded `C:\\Windows`: the variable is what Windows itself
    uses, and a machine that installed to another drive is unusual rather than impossible.
    The literal is only the floor under a stripped environment.
    """
    return os.path.join(os.environ.get("SystemRoot") or "C:\\Windows", "System32", name)


def _kill_tree(proc: subprocess.Popen) -> None:
    """End the call and everything it started.

    `proc.kill()` reaches only the process this module launched, and that is not the
    process doing the work: `codex` is a launcher that runs `node`. Killing the
    launcher leaves the model call running — still holding the pipe it inherited, so
    the read would block on it anyway, which is how a call could time out while the
    thing it timed out on carried on. Windows has no process group to signal, so the
    tree walk is `taskkill /T`; it ships with the OS and costs no dependency (R16),
    and `send_check.py` already reaps its target window the same way.

    By its fixed location rather than by name. This runs on the cancel path, which is when
    the user is already unhappy, and a bare name here is the same current-directory door
    `trusted()` closes one process along — with the difference that this one would be
    handed the cwd the *call* was made in, which is the workshop by construction.
    """
    if proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                [_system_tool("taskkill.exe"), "/PID", str(proc.pid), "/T", "/F"],
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

    `timeout` is the caller's budget and `cli.timeout_sec` is this CLI's floor under it,
    so what is actually waited is the larger of the two — see `Cli.timeout_sec` for why it
    is a floor. The failure note quotes that number rather than the constant: with the wait
    now per-CLI, a message naming the global would be right about three entries out of four
    and wrong about the only one that ever needed saying.
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
    executable = resolve(cli) or cli.argv[0]

    # Refused before anything starts, because the failure it prevents has no symptom: the
    # shim exits 0 with a fluent answer to a prompt it never saw. See `SHIM_SUFFIXES`.
    # A CLI that takes its prompt on stdin never meets `%*`, so it is not refused.
    if not cli.stdin_ok and os.path.splitext(executable)[1].lower() in SHIM_SUFFIXES:
        return None, (
            f"{cli.name} is a {os.path.basename(executable)} launcher - cmd.exe cuts its "
            f"argument at the first newline, so it would answer a prompt it never saw. "
            f"Install the native {cli.name} build rather than npm -g."
        )

    try:
        proc = subprocess.Popen(
            # The prompt leaves the argv entirely when it travels on stdin. Sending it
            # both ways would be the truncation plus a duplicate.
            [executable, *cli.argv[1:]] + ([] if cli.stdin_ok else [prompt]),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # codex waits on stdin ("Reading additional input from stdin..."), so it
            # must be closed explicitly or the call can hang until the timeout.
            stdin=subprocess.PIPE if cli.stdin_ok else subprocess.DEVNULL,
            text=True,
            cwd=cwd,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        return None, f"{cli.name} failed to start: {exc}"

    wait = timeout if cli.timeout_sec is None else max(timeout, cli.timeout_sec)
    deadline = time.monotonic() + wait
    # `communicate` is what pipes, writes and closes stdin — and it may carry `input`
    # exactly once: a second call with it raises "Cannot send input after starting
    # communication". Since this polls, the prompt goes on the first pass and the rest of
    # the loop waits. A defect that would only ever appear on a slow call.
    to_send: str | None = prompt if cli.stdin_ok else None
    while True:
        if cancel is not None and cancel.is_set():
            return _abandon(proc, f"{cli.name} was cancelled")
        left = deadline - time.monotonic()
        if left <= 0:
            return _abandon(proc, f"{cli.name} timed out after {wait:.0f}s")
        try:
            out, err = proc.communicate(input=to_send, timeout=min(_POLL_SEC, left))
        except subprocess.TimeoutExpired:
            to_send = None
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


#: Every CSI sequence, which is all kiro-cli emits: colour resets (`\x1b[m`, `\x1b[0m`),
#: cursor hide/show (`\x1b[?25l`), column moves (`\x1b[1G`).
_ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")

#: The metering line, matched as a *shape* rather than by the word "Credits" — an answer
#: about billing is still an answer, and eating a sentence out of one would be this
#: cleaner becoming the parser the module docstring argues against.
_KIRO_STATUS = re.compile(r"^[ \t]*▸ Credits:.*$", re.MULTILINE)


def _clean_kiro(out: str) -> str:
    """Strip kiro-cli's chrome and leave the answer.

    Measured on this machine, 2026-08-02, through the same `Popen` shape `_invoke` uses:
    stdout is `\\x1b[m> \\x1b[0m` then the answer, with `\\x1b[0m\\x1b[0m` between lines of
    a multi-line one — so the `> ` marker is on the **first line only**, and stripping it
    per line would eat a quoted shell command or a diff out of a real answer.

    The status line is stripped anyway and that is worth saying: with the streams apart —
    which is this module's discipline and what `_invoke` does — `▸ Credits: … • Time: …`
    goes to **stderr** and never arrives here at all. It is handled because it is what the
    CLI prints when the two are together, and removing a line that is not there costs
    nothing. Its stderr also carries a `WARNING:` about `--trust-tools` wanting an
    `@{MCPSERVERNAME}/` prefix; the call exits 0 and answers, and nothing is done about a
    warning on the stream this module already discards.
    """
    s = _KIRO_STATUS.sub("", _ANSI.sub("", out)).strip()
    return s[2:].lstrip() if s.startswith("> ") else s


#: Per CLI, keyed by name, and empty for everything that writes its answer alone. A tidy
#: that ran for every entry would be a parser applied to output that does not need one —
#: and would damage codex, whose answers legitimately contain `>` and the word Credits.
_FURNITURE = {"kiro-cli": _clean_kiro}


def _clean(out: str, cli: Cli | None = None) -> str:
    """Light defensive tidy, after whatever `cli` needs stripped first.

    Deliberately not a parser: for codex and claude stdout is already clean, and the only
    reason this takes a `Cli` at all is that one entry meters and says so out loud.
    """
    s = out
    if cli is not None and cli.name in _FURNITURE:
        s = _FURNITURE[cli.name](s)
    s = s.strip()
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

    revised = _clean(out, chosen)
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

    answer = _clean(out, chosen)
    if not answer:
        return None, f"{chosen.name} returned nothing"
    cap = ASK_ARTIFACT_MAX_CHARS if artifact else ASK_MAX_CHARS
    if len(answer) > cap:
        answer = answer[: cap - 1].rstrip() + "…"
    return answer, chosen.name
