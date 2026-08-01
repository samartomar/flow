"""A content-free record of what Flow did, on this machine and nowhere else.

Every defect worth fixing in this project so far was found by *measuring* it, and the
measurements all came from harnesses that had to be set up in advance for a failure
somebody had already seen. This is the other half: a running record of shape and timing
so that the next report — "it stopped hearing me for a bit", "the answer took ages" —
has something behind it besides memory.

The whole design question is what may be written down. A voice app's log is the one log
that can quietly become a transcript, and a transcript of everything somebody dictated
is worse than no diagnostics at all. So the rule here is not "be careful with content",
it is **content cannot get in**:

  **Field names are an allow-list.** `FIELDS` is the complete set. A value is safe
  because of where it came from, and only the field name records that — a draft reading
  "yes" is indistinguishable from a status token by inspection, so inspection is not
  what decides.

  **The words are named and refused as well.** `NEVER` lists the fields that would carry
  user text. It exists so that adding one to `FIELDS` fails at import rather than
  quietly shipping somebody's draft, and so the intent is written down where the next
  person edits.

  **Values are numbers, booleans, or short tokens.** Anything else is replaced with a
  marker, so a mistake shows up in the file as a refusal instead of as content.

R9 is enforced the same way it is in `profile.py`: there is no code here that could send
anything anywhere. R8 too — the file is bounded and rotates once, so a long session
costs what a short one costs.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

DEFAULT_PATH = Path.home() / ".flow" / "diag.jsonl"

#: R8. Past this the file is rotated to `.1` and a fresh one started, so the trace costs
#: at most twice this on disk however long Flow runs. A megabyte is roughly a day of
#: heavy use at the rates below — enough to still contain yesterday's puzzle.
MAX_BYTES = 1_000_000

#: Every field that may be written, and nothing else.
#:
#: An allow-list, not a filter. What makes a value safe to record is where it came from,
#: and the field name is the only thing that knows that: `chars` is a length, `route` is
#: one of six words the router chose, `provider` is the name of an executable. None of
#: them can be a sentence somebody said.
FIELDS = frozenset({
    "t",          # seconds since the epoch, rounded to milliseconds
    "kind",       # what this record is
    "op",         # operation id, for matching a CLI result to its request
    "state",      # a State value
    "was",        # the State it replaced
    "route",      # append | local | semantic | undo | rescue | recall | followup
    "tier",       # base.en | small.en
    "ms",         # a duration
    "provider",   # codex | claude
    "chars",      # a length, never the thing measured
    "confidence",  # how well the decoder heard: worst avg_logprob, or null for unknown
    "sent",       # a length: how much of an over-long input the CLI was given
    "n",          # a count
    "dropped",    # microphone blocks lost, cumulative
    "echo",       # blocks discarded because Flow was talking, cumulative
    "reason",     # an error *category*, never a message
    "ok",         # whether it worked
    "mode",       # dictate | converse
    "component",  # what a version belongs to: a package, the OS, a model, a CLI
    "version",    # a version string or a revision hash, never a path
    "artifact",   # whether the ask requested a piece of work rather than an answer
})

#: Named so that adding one to FIELDS fails loudly. These are the words themselves —
#: what the user said, what Flow drafted, what came back, what was on their clipboard,
#: what they taught it. A trace containing any of them is a transcript.
NEVER = frozenset({
    "text", "draft", "reply", "answer", "transcript", "utterance", "partial",
    "instruction", "question", "payload", "clipboard", "lexicon", "term", "hotwords",
    "device", "path", "window", "title",
})

assert not (FIELDS & NEVER), "a field that may never be written is on the allow-list"

#: A value that is text at all has to be a token: short, and from a vocabulary the code
#: chose rather than the user. A draft, a reply or a clipboard cannot be squeezed
#: through this and still be one.
_TOKEN = re.compile(r"^[A-Za-z0-9._:+-]{1,40}$")

#: What replaces a value that does not qualify. Written rather than dropped, so a
#: mistake reads as a refusal in the file instead of as an absence nobody notices.
REFUSED = "<refused>"


def _safe(value):
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str) and _TOKEN.match(value):
        return value
    return REFUSED


class NullDiag:
    """Records nothing, and is the default.

    The same shape as `profile=None` disabling learning, and for the same reason: a
    test, a benchmark or a probe constructs a `Session` in its hundreds, and a default
    that wrote to `~/.flow/diag.jsonl` would fill the real user's trace with runs that
    were never theirs. Tracing is something the app turns on, not something a `Session`
    does by existing.
    """

    path = None

    def write(self, kind: str, /, **fields) -> None: ...


class Diag:
    """Append-only JSONL, one record per line, bounded and rotated once.

    Every method is best-effort: a diagnostics writer that can raise is a diagnostics
    writer that takes the app down with it, and nothing here is worth that. A disk that
    is full or a file that is locked means no trace, not a stack trace.
    """

    def __init__(self, path: Path | str | None = None, max_bytes: int = MAX_BYTES) -> None:
        self.path = Path(path) if path is not None else DEFAULT_PATH
        self.max_bytes = max_bytes
        #: Records refused for an unknown field name. Counted rather than written,
        #: because the safest thing to do with a record nobody vetted is nothing.
        self.rejected = 0
        self._lock = threading.Lock()

    def write(self, kind: str, /, **fields) -> None:
        record = {"t": round(time.time(), 3), "kind": _safe(kind)}
        for key, value in fields.items():
            # `t` and `kind` are this method's own, so a caller passing either as a
            # field would silently rewrite the record's identity. Positional-only
            # above stops the collision; this stops the overwrite.
            if key in ("t", "kind"):
                self.rejected += 1
            elif key in FIELDS:
                record[key] = _safe(value)
            else:
                # An unknown field is a caller this module has not agreed with. Refusing
                # the *field* rather than the record keeps the timing evidence, which is
                # the part that was never in question.
                self.rejected += 1
        line = json.dumps(record, separators=(",", ":"), ensure_ascii=False)
        with self._lock:
            try:
                self._rotate_if_needed(len(line) + 1)
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError:
                pass

    def _rotate_if_needed(self, incoming: int) -> None:
        try:
            size = self.path.stat().st_size
        except OSError:
            return
        if size + incoming <= self.max_bytes:
            return
        # One generation, deliberately. Two files with a known ceiling is a bound; a
        # numbered series is a log directory that grows until somebody notices.
        backup = self.path.with_suffix(self.path.suffix + ".1")
        try:
            os.replace(self.path, backup)
        except OSError:
            pass


# -- what produced a measurement -------------------------------------------

#: How long to wait for a CLI to say what version it is. Each costs a process start,
#: which is why this whole section runs off the startup path.
_VERSION_TIMEOUT_SEC = 10.0

#: Where faster-whisper's short names come from. Recorded so a decode result can be
#: matched to the weights that produced it: "base.en" names a model, not a build of one.
_HF_PREFIX = "Systran/faster-whisper-"

_VERSION_IN = re.compile(r"\d+(?:\.\d+)+[A-Za-z0-9._+-]*")


def _packages() -> list[tuple[str, str]]:
    import importlib.metadata as md

    out = []
    # ctranslate2 is not a declared dependency of this project and is the one that
    # actually decides decode speed and numerics, so it is worth more here than most
    # of the things that are.
    for name in ("faster-whisper", "ctranslate2", "numpy", "sounddevice", "tokenizers"):
        try:
            out.append((name, md.version(name)))
        except Exception:
            out.append((name, "absent"))
    return out


def _hub_cache() -> Path:
    hub = os.environ.get("HF_HUB_CACHE")
    if hub:
        return Path(hub)
    home = os.environ.get("HF_HOME")
    if home:
        return Path(home) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def model_revision(name: str) -> str:
    """The commit the local cache resolved a model name to, or "".

    Read from the cache's own `refs/main` rather than asked over the network: the point
    is to record what this machine actually decoded with, and a lookup that could
    disagree with the files on disk would be recording the wrong thing.

    Recorded and not pinned, which was a decision rather than an omission.
    `WhisperModel(...)` does take a `revision`, so pinning is available; what is not
    available is a complete table to pin *from*. `--model` accepts any name, the
    benchmarks use several beyond the two defaults, and a pin covering only `base.en`
    and `small.en` would quietly not apply to exactly the runs whose reproducibility is
    the reason for wanting it. A guarantee that silently does not hold where it is
    needed is worse than a recorded fact that always does. The pin is a decision for
    the owner, with the cost written down in NEEDS_YOU.md.
    """
    repo = name if "/" in name else _HF_PREFIX + name
    ref = _hub_cache() / ("models--" + repo.replace("/", "--")) / "refs" / "main"
    try:
        return ref.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _cli_version(name: str) -> str:
    """`<name> --version`, reduced to the version in it. "" if it will not say."""
    import subprocess

    try:
        done = subprocess.run(
            [name, "--version"], capture_output=True, text=True,
            timeout=_VERSION_TIMEOUT_SEC, stdin=subprocess.DEVNULL,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    found = _VERSION_IN.search((done.stdout or "") + " " + (done.stderr or ""))
    return found.group(0) if found else ""


def identity(models=()) -> list[tuple[str, str]]:
    """Everything that decides what a measurement means, as (component, version).

    Gathered rather than assumed. Half the numbers in `docs/architecture.md` are decode
    latencies and word error rates, and every one of them belongs to a build: a
    ctranslate2 release changes the arithmetic, a model revision changes the weights, and
    neither announces itself. Without this a benchmark result six months old cannot be
    compared to a fresh one except by hoping.

    Costs several process starts and a handful of file reads, so callers run it off the
    startup path.
    """
    import platform

    out = list(_packages())
    out.append(("python", platform.python_version()))
    out.append(("os", platform.version()))
    for name in models:
        revision = model_revision(name)
        out.append((f"model:{name}", revision or "uncached"))
    for cli in ("codex", "claude"):
        version = _cli_version(cli)
        if version:
            out.append((f"cli:{cli}", version))
    return out


def record_identity(diag, models=()) -> None:
    """Write `identity()` into the trace. Best-effort, like everything else here."""
    try:
        for component, version in identity(models):
            diag.write("identity", component=component, version=version)
    except Exception:
        pass
