"""What Flow handed over and what it was asked — kept on this PC when, and only when,
somebody chose to keep it (decisions.md 2026-09-23, "History").

**Opt-in, and the choice is never made for anybody.** decisions.md 2026-08-03 part 3
settled that the words are never stored, and named its own reopen: "if quit-loss actually
bites someone, the next shape is an opt-in on-disk history, never a default one". Flow Home
is where somebody can finally see what they said (decisions.md 2026-09-22, decision 3), so
this is that shape. `Profile.history` starts as None — not chosen — and not chosen keeps
nothing, exactly as "off" does. The History page asks with nothing preselected; the first
run will ask the same question the same way.

**One file, five kinds.** What a Send handed over (dictated, or refined by the agent CLI),
what the speech filter set aside, and both halves of an Ask. One file rather than two
because one choice governs all of it, and "everything Flow keeps is in history.jsonl" is a
sentence somebody can check with Notepad.

**Written off the session's thread.** A Send ends in a paste on the UI thread, and the
2026-08-15 measurement that moved `profile.save()` off that frame applies here with more
force: an append is a file open, and a rewrite is the whole file. So the session only ever
enqueues, and one writer thread owns the list and the file. Flow Home's reads go through
the same queue, which is what makes a page that was just told "deleted" unable to show the
entry again.

**Nothing here decides what is worth keeping.** The session says what happened; this
module keeps it, bounds it by age and by count, and forgets it when asked. Every write is
an explicit act of somebody who chose "keep" — the same line `flow/notes.py` draws for the
notes file, drawn once more.
"""

from __future__ import annotations

import json
import math
import queue
import secrets
import threading
import time
import traceback
from pathlib import Path

#: Beside the profile, in the folder that already holds everything Flow knows about
#: somebody — the Settings page's "Settings folder" button opens it.
DEFAULT_PATH = Path.home() / ".flow" / "history.jsonl"

#: The two answers to "keep a history?". Not chosen is neither, and keeps nothing.
KEEP = "keep"
OFF = "off"
CHOICES = (KEEP, OFF)

#: How long an entry is kept. Thirty days is what the canvas drew and what the first run
#: will offer; a week and a quarter are the two other answers people give when asked.
DAYS = (7, 30, 90)
DAYS_DEFAULT = 30

#: What an entry is.
DICTATED = "dictated"
REFINED = "refined"
SET_ASIDE = "set_aside"
ASKED = "asked"
ANSWERED = "answered"
KINDS = (DICTATED, REFINED, SET_ASIDE, ASKED, ANSWERED)
#: The History page's kinds, and the two of them that went somewhere.
DICTATION = (DICTATED, REFINED, SET_ASIDE)
HANDED = (DICTATED, REFINED)
#: The Conversations page's kinds.
ASK = (ASKED, ANSWERED)

#: A ceiling under the age limit, for the person who dictates all day for ninety days:
#: the file is read whole at launch, and a bound is what keeps that a fraction of a
#: second forever. Twenty thousand is two hundred handovers a day for a quarter.
MAX_ENTRIES = 20_000

#: What one entry's text may carry. An Ask answer can run to sixty lines, so this is
#: generous; it exists to stop one pathological paste from being the whole file.
MAX_TEXT = 20_000

#: How long a Flow Home request waits on the writer before it says so. The writer's
#: slowest honest job is rewriting the whole file, which is milliseconds.
CALL_WAIT_SEC = 2.0

#: How long a repeat of the same set-aside words is folded into the one before it. The
#: filter's commonest catch is Whisper writing "Thank you." at the end of a hold, and a
#: page with that line twelve times is a page nobody reads down.
SET_ASIDE_REPEAT_SEC = 120.0

#: The fields an entry may carry beyond its four, and the type each must have. Anything
#: else in a line is dropped on load — a hand edit can add a field, and this is what
#: stops it from reaching the page.
_FIELDS: dict[str, type | tuple[type, ...]] = {
    "app": str,        # the executable a Send pasted into, as inject names it
    "words": int,
    "how": str,        # "pasted", "copied" or "not pasted"; a paste changed by voice
                       # after it landed is "pasted, then changed", and one taken back
                       # whole is "taken back" (decisions.md 2026-09-23)
    "note": str,       # what went wrong, when something did
    "heard": str,      # a refined entry: the words before the CLI shaped them
    "cli": str,        # which agent CLI answered or refined, as it reported itself
    "secs": (int, float),
    "reason": str,     # a set-aside entry: why the filter took it
    "conv": str,       # an Ask entry: which conversation
    "ws": str,         # an Ask entry: the workspace it was grounded in
    "via": str,        # an asked entry: "voice" or "typed"
    "failed": str,     # an answered entry with no answer: what the CLI said instead
    "fixed": bool,     # the text was corrected here after it was kept
}


def new_id() -> str:
    """Twelve hex characters: unique enough for one person's ninety days."""
    return secrets.token_hex(6)


def _cut(text: str) -> str:
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1] + "…"


def make_entry(kind: str, text: str, *, at: float | None = None, **fields) -> dict:
    """One record, as the file and both pages read it. Empty fields are left out.

    Made here rather than inside `History` because the session keeps the conversation
    on screen in memory whether or not history is kept, and one shape for both is what
    lets the Conversations page draw them the same way.
    """
    entry = {"id": new_id(), "at": round(time.time() if at is None else at, 3),
             "kind": kind, "text": _cut((text or "").strip())}
    for key, value in fields.items():
        if value is None or value == "" or key not in _FIELDS:
            continue
        entry[key] = _cut(value) if isinstance(value, str) else value
    return entry


def _valid(raw) -> dict | None:
    """A line of the file as an entry, or None. Never raises.

    Judged the way `profile.py` judges its fields — "is this usable as what it claims to
    be", never "can it be coerced into one" — because this file is plain text in a folder
    people open, and a hand edit must cost the line it broke rather than the page.
    """
    if not isinstance(raw, dict):
        return None
    ident, at, kind, text = raw.get("id"), raw.get("at"), raw.get("kind"), raw.get("text")
    if not isinstance(ident, str) or not 0 < len(ident) <= 32:
        return None
    if isinstance(at, bool) or not isinstance(at, (int, float)) or not math.isfinite(at):
        return None
    if kind not in KINDS or not isinstance(text, str):
        return None
    entry = {"id": ident, "at": at, "kind": kind, "text": _cut(text)}
    for key, wanted in _FIELDS.items():
        value = raw.get(key)
        if value is None:
            continue
        # `True` is an `int` in Python; a count or a duration that is a boolean is a
        # wrong type, not the number 1.
        if isinstance(value, bool) and wanted is not bool:
            continue
        if not isinstance(value, wanted):
            continue
        if isinstance(value, float) and not math.isfinite(value):
            continue
        entry[key] = _cut(value) if isinstance(value, str) else value
    return entry


def matches(entry: dict, query: str) -> bool:
    if not query:
        return True
    q = query.casefold()
    return any(q in str(entry.get(key, "")).casefold() for key in ("text", "heard", "app"))


class History:
    """The kept entries, oldest first, and the file they live in."""

    def __init__(self, path: Path | str | None = None, profile=None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_PATH
        #: Where the choice and the retention live. None — `--no-profile` — has nowhere
        #: to have made a choice, so it keeps nothing, which is what the flag promises.
        self.profile = profile
        self._items: list[dict] = []
        self._ops: queue.SimpleQueue = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        #: Keeping stops for the rest of this launch without changing the choice: the
        #: Pause button, for the minute somebody is about to dictate a password.
        self.paused = False
        #: What went wrong the last time the file was read or written, or "". The page
        #: says it, because a history that silently stopped saving is the P2 failure in
        #: a new place.
        self.error = ""
        #: Lines of the file that could not be read, and were left out.
        self.unreadable = 0
        #: The newest entry that went somewhere, for Paste last after a restart. Set on
        #: the writer thread and read on the UI thread; one assignment, never mutated.
        self.newest: dict | None = None
        if self.choice == KEEP:
            # Read at launch, on the writer, so the first Send never waits on it.
            self._start()

    # -- the choice ----------------------------------------------------------------

    @property
    def choice(self) -> str:
        """"keep", "off", or "" for not chosen yet."""
        value = getattr(self.profile, "history", None) if self.profile is not None else None
        return value if value in CHOICES else ""

    @property
    def days(self) -> int:
        value = getattr(self.profile, "history_days", DAYS_DEFAULT) \
            if self.profile is not None else DAYS_DEFAULT
        return value if value in DAYS else DAYS_DEFAULT

    @property
    def keeping(self) -> bool:
        return self.choice == KEEP and not self.paused

    # -- the session's side: enqueue, never wait -----------------------------------

    def keep(self, entry: dict | None) -> bool:
        """Keep `entry` if history is being kept. True if it was queued."""
        if not entry or not self.keeping:
            return False
        self._start()
        self._ops.put((self._append, (dict(entry),), None))
        return True

    def add(self, kind: str, text: str, **fields) -> dict | None:
        """Make an entry and keep it. None when nothing is being kept."""
        if not self.keeping:
            return None
        entry = make_entry(kind, text, **fields)
        if not entry["text"] and kind != ANSWERED:
            return None
        self.keep(entry)
        return entry

    def revise(self, entry_id: str, **changes) -> bool:
        """`update`, queued rather than waited on: the session's side of it.

        A paste corrected by voice changes the words its entry kept (decisions.md
        2026-09-23, "Correcting a Type paste"), and the session must not wait on a disk
        to say so — the keystroke is what somebody is waiting on. Behind the entry's own
        `keep` on the same queue, so the entry is there by the time this runs. True if
        it was queued.
        """
        if not entry_id or self.choice != KEEP:
            return False
        self._start()

        def change() -> None:
            for e in self._items:
                if e["id"] == entry_id:
                    for key, value in changes.items():
                        if key == "text":
                            e["text"] = _cut(str(value))
                        elif key in _FIELDS and value is not None:
                            e[key] = value
                    self._rewrite()
                    return

        self._ops.put((change, (), None))
        return True

    # -- Flow Home's side: ask the writer and wait ---------------------------------

    def entries(self, kinds=None, *, query: str = "", limit: int | None = None) -> list[dict]:
        """Kept entries, newest first."""
        if self.choice != KEEP:
            return []

        def read() -> list[dict]:
            self._prune()
            out = [dict(e) for e in reversed(self._items)
                   if (kinds is None or e["kind"] in kinds) and matches(e, query)]
            return out if limit is None else out[:limit]

        return self._call(read)

    def conversations(self) -> list[dict]:
        """Every kept conversation, most recently active first."""
        if self.choice != KEEP:
            return []

        def read() -> list[dict]:
            self._prune()
            found: dict[str, dict] = {}
            for e in self._items:
                conv = e.get("conv")
                if e["kind"] not in ASK or not conv:
                    continue
                c = found.get(conv)
                if c is None:
                    c = found[conv] = {"conv": conv, "title": "", "started": e["at"],
                                       "last": e["at"], "ws": "", "asked": 0}
                c["last"] = e["at"]
                if e["kind"] == ASKED:
                    c["asked"] += 1
                    if not c["title"]:
                        c["title"] = e["text"]
                    if not c["ws"] and e.get("ws"):
                        c["ws"] = e["ws"]
            return sorted(found.values(), key=lambda c: c["last"], reverse=True)

        return self._call(read)

    def conversation(self, conv: str) -> list[dict]:
        """One kept conversation's entries, oldest first."""
        if self.choice != KEEP or not conv:
            return []
        return self._call(lambda: [dict(e) for e in self._items
                                   if e.get("conv") == conv and e["kind"] in ASK])

    def get(self, entry_id: str) -> dict | None:
        """One kept entry, by id, or None."""
        if self.choice != KEEP or not entry_id:
            return None
        return self._call(lambda: next((dict(e) for e in self._items
                                        if e["id"] == entry_id), None))

    def update(self, entry_id: str, **changes) -> dict | None:
        """Change one entry's fields and rewrite the file. The entry as it now is."""
        if self.choice != KEEP:
            return None

        def change() -> dict | None:
            for e in self._items:
                if e["id"] != entry_id:
                    continue
                for key, value in changes.items():
                    if key == "text":
                        e["text"] = _cut(str(value))
                    elif key in _FIELDS and value is not None:
                        e[key] = value
                self._rewrite()
                return dict(e)
            return None

        return self._call(change)

    def remove(self, entry_id: str) -> bool:
        return self._drop(lambda e: e["id"] == entry_id) > 0

    def remove_conversation(self, conv: str) -> int:
        return self._drop(lambda e: bool(conv) and e.get("conv") == conv)

    def clear(self, kinds) -> int:
        kinds = tuple(kinds)
        return self._drop(lambda e: e["kind"] in kinds)

    def forget(self) -> bool:
        """Everything kept, and the file. What choosing "off" means."""

        def wipe() -> bool:
            self._items = []
            self.newest = None
            self.unreadable = 0
            try:
                self.path.unlink(missing_ok=True)
                self.path.with_suffix(".tmp").unlink(missing_ok=True)
            except OSError as exc:
                self.error = f"could not delete {self.path}: {exc}"
                return False
            self.error = ""
            return True

        return self._call(wipe)

    def flush(self, wait: float = 1.0) -> bool:
        """Wait for everything queued to reach the file. For the quit path and tests."""
        if self._thread is None:
            return True
        try:
            self._call(lambda: None, wait=wait)
            return True
        except TimeoutError:
            return False

    # -- the writer ----------------------------------------------------------------

    def _start(self) -> None:
        with self._start_lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, daemon=True,
                                                name="history")
                self._thread.start()

    def _call(self, fn, wait: float = CALL_WAIT_SEC):
        self._start()
        done = threading.Event()
        box: dict = {}
        self._ops.put((fn, (), (done, box)))
        if not done.wait(wait):
            raise TimeoutError("history is busy - try again in a moment")
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def _run(self) -> None:
        self._load()
        while True:
            fn, args, reply = self._ops.get()
            try:
                value = fn(*args)
                if reply is not None:
                    reply[1]["value"] = value
            except Exception as exc:
                if reply is not None:
                    reply[1]["error"] = exc
                else:
                    traceback.print_exc()
            finally:
                if reply is not None:
                    reply[0].set()

    def _load(self) -> None:
        if self.choice != KEEP:
            return
        try:
            text = self.path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            text = ""
        except OSError as exc:
            self.error = f"could not read {self.path}: {exc}"
            text = ""
        items, bad = [], 0
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                entry = _valid(json.loads(line))
            except ValueError:
                entry = None
            if entry is None:
                bad += 1
                continue
            items.append(entry)
        # Appends arrive in order; a hand edit need not have kept it.
        items.sort(key=lambda e: e["at"])
        self._items = items
        self.unreadable = bad
        self._prune()
        self.newest = next((e for e in reversed(self._items) if e["kind"] in HANDED), None)

    def _append(self, entry: dict) -> None:
        # Asked again here, because the choice can change between the enqueue and now:
        # "off" chosen a moment after a Send must not have that Send land after the wipe.
        if self.choice != KEEP:
            return
        if entry["kind"] == SET_ASIDE and self._repeat(entry):
            return
        self._items.append(entry)
        if entry["kind"] in HANDED:
            self.newest = entry
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self.error = ""
        except OSError as exc:
            self.error = f"could not write {self.path}: {exc}"
        self._prune()

    def _repeat(self, entry: dict) -> bool:
        """True when `entry` is the set-aside words just kept, said again."""
        for e in reversed(self._items):
            if entry["at"] - e["at"] > SET_ASIDE_REPEAT_SEC:
                return False
            if e["kind"] == SET_ASIDE:
                return e["text"].casefold() == entry["text"].casefold()
        return False

    def _prune(self) -> bool:
        """Drop what is older than the retention or past the ceiling. True if it did."""
        if not self._items:
            return False
        cutoff = time.time() - self.days * 86400
        if self._items[0]["at"] >= cutoff and len(self._items) <= MAX_ENTRIES:
            return False
        kept = [e for e in self._items if e["at"] >= cutoff][-MAX_ENTRIES:]
        self._items = kept
        if self.newest is not None and self.newest["at"] < cutoff:
            self.newest = None
        self._rewrite()
        return True

    def _drop(self, doomed) -> int:
        if self.choice != KEEP:
            return 0

        def drop() -> int:
            before = len(self._items)
            self._items = [e for e in self._items if not doomed(e)]
            gone = before - len(self._items)
            if gone:
                if self.newest is not None and doomed(self.newest):
                    self.newest = next((e for e in reversed(self._items)
                                        if e["kind"] in HANDED), None)
                self._rewrite()
            return gone

        return self._call(drop)

    def _rewrite(self) -> bool:
        """The whole file from the list: written whole, then moved, like the profile."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8", newline="\n") as f:
                for e in self._items:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
            tmp.replace(self.path)
            self.error = ""
            self.unreadable = 0
            return True
        except OSError as exc:
            self.error = f"could not write {self.path}: {exc}"
            return False


class NullHistory:
    """No history at all — `--no-profile`, the tests, the harnesses — with the same
    methods answering "nothing kept", so no caller needs to ask which it has."""

    path = None
    profile = None
    choice = ""
    days = DAYS_DEFAULT
    keeping = False
    paused = False
    error = ""
    unreadable = 0
    newest = None

    def keep(self, entry) -> bool:
        return False

    def add(self, kind, text, **fields):
        return None

    def entries(self, kinds=None, *, query: str = "", limit=None) -> list:
        return []

    def conversations(self) -> list:
        return []

    def conversation(self, conv) -> list:
        return []

    def get(self, entry_id):
        return None

    def update(self, entry_id, **changes):
        return None

    def revise(self, entry_id, **changes) -> bool:
        return False

    def remove(self, entry_id) -> bool:
        return False

    def remove_conversation(self, conv) -> int:
        return 0

    def clear(self, kinds) -> int:
        return 0

    def forget(self) -> bool:
        return True

    def flush(self, wait: float = 1.0) -> bool:
        return True
