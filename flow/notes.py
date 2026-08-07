"""What the conversation was worth keeping, and the document it becomes (P9).

Converse mode answers questions now (decisions.md 2026-08-03, part 1), and a mode that
answers questions produces things worth having afterwards — which the session then threw
away on quit along with everything else. `Thread` holds what was *sent* and Recent holds
the last twenty of everything that happened to words; neither is a record of what the
speaker judged worth keeping, because neither was chosen. This is the chosen half.

**An explicit act is what makes the file legitimate.** decisions.md 2026-08-03 part 3
settled that the words are never stored, and named the reopen: "if quit-loss actually
bites someone, the next shape is an opt-in on-disk history, **never a default one**".
Nothing here records anything on its own — with no verb spoken this module holds an empty
deque and writes no file — and nothing here writes without a second explicit act. Two
consequences are load-bearing rather than incidental: the settings folder is never
touched, so item 65's test that a whole session leaves it as it found it keeps passing;
and the file lands in the workspace, which is the folder the user already pointed Flow at.

**Flow does not summarise the notes**, and that is R9 rather than modesty: Flow never
generates content on its own (product.md, "Being an AI itself" — it is the microphone,
the editor and the courier). The document is what was kept, in the order it was kept,
verbatim. A speaker who wants the CLI's reading of it asks for one, which is an ordinary
converse question and already works.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

#: Notes kept before the oldest starts falling off. Twenty times `Thread.MAX_TURNS`,
#: and the ratio is the argument: a turn is everything said, while a note is something
#: the speaker stopped to keep, so the same ceiling would bind at a hundredth of the
#: talking. Two hundred deliberate acts is a working day of them.
MAX_NOTES = 200

#: Total characters held. A single enormous kept answer must not evict the rest.
MAX_CHARS = 200_000

#: What one note may carry. An artifact answer is legitimately long (`ARTIFACT_SAY_*`
#: exists because they run to sixty lines), so this is generous — it is here to stop a
#: pathological paste from being the whole budget, not to edit anybody's note.
MAX_NOTE_CHARS = 20_000

#: How many same-minute files to try before giving up. Two wrap-ups inside one minute is
#: a real thing — "wrap up", read the file, keep one more, "wrap up" again — and silently
#: overwriting the first would destroy notes at the exact moment the feature exists to
#: save them.
MAX_FILENAME_TRIES = 100

#: The folder made inside the workspace. Named rather than dotted: a hidden folder is
#: where a tool puts its own state, and these are the user's words. They should be as
#: findable as anything else they wrote.
NOTES_DIR = "flow-notes"


@dataclass(frozen=True)
class Note:
    """One kept thing, and where it came from."""

    text: str
    #: Wall clock, not `perf_counter`: this one is read by a human in a file, and the
    #: rest of the session's timings are durations that never leave the process.
    at: float
    #: The question this answer was the answer to, when the note is a whole exchange.
    #: Empty for a note the speaker dictated, which stands on its own.
    question: str = ""
    #: The workspace leaf as it was *at capture time*, not at write time. A session can
    #: switch projects (`Session.set_workspace`), and a note tagged with wherever the
    #: speaker happened to be when they said "wrap up" would be a quiet lie about which
    #: project it belongs to.
    workspace: str = ""


class Notes:
    """The kept notes, oldest first."""

    def __init__(
        self, max_notes: int = MAX_NOTES, max_chars: int = MAX_CHARS
    ) -> None:
        self._notes: deque[Note] = deque()
        self.max_notes = max_notes
        self.max_chars = max_chars

    def __len__(self) -> int:
        return len(self._notes)

    @property
    def all(self) -> list[Note]:
        return list(self._notes)

    @property
    def chars(self) -> int:
        return sum(len(n.text) + len(n.question) for n in self._notes)

    def add(
        self,
        text: str,
        question: str = "",
        workspace: str = "",
        at: float | None = None,
    ) -> int:
        """Keep one note. Returns how many older notes fell off to make room.

        The count is returned rather than swallowed because of P2: a note is kept by an
        explicit act, so losing one to a ceiling is the same class of event as dropping
        speech, and the caller has to be able to say it happened. `add` itself does not
        emit — this module has no surface — but it refuses to be the place a note goes
        missing quietly.
        """
        text = (text or "").strip()
        if not text:
            return 0
        if len(text) > MAX_NOTE_CHARS:
            # Head, not tail. `refine.ask` keeps the tail of an over-long question
            # because the tail is the ask; a note is read top-down, so its opening is
            # what identifies it later.
            text = text[: MAX_NOTE_CHARS - 1] + "…"
        self._notes.append(
            Note(
                text=text,
                at=time.time() if at is None else at,
                question=(question or "").strip(),
                workspace=(workspace or "").strip(),
            )
        )
        return self._trim()

    def _trim(self) -> int:
        dropped = 0
        while len(self._notes) > self.max_notes:
            self._notes.popleft()
            dropped += 1
        # Never trim to nothing: one oversized note is kept whole rather than dropped,
        # for `Thread._trim`'s reason — the thing somebody asked to keep has to survive
        # being the only thing they asked to keep.
        while len(self._notes) > 1 and self.chars > self.max_chars:
            self._notes.popleft()
            dropped += 1
        return dropped

    def clear(self) -> None:
        self._notes.clear()


def _stamp(at: float, fmt: str) -> str:
    return time.strftime(fmt, time.localtime(at))


def render(notes: list[Note], workspace: str = "", now: float | None = None) -> str:
    """The kept notes as one markdown document.

    Markdown because the destination is a repository — the same folder the user pointed
    Flow at is a folder where `.md` renders on GitHub and opens in every editor they
    already have. Headings carry the time and the question, which are the two things
    somebody scanning this a week later navigates by.
    """
    now = time.time() if now is None else now
    leaf = workspace.strip()
    title = f"# Flow notes — {leaf}" if leaf else "# Flow notes"
    count = f"{len(notes)} note" + ("" if len(notes) == 1 else "s")
    lines = [title, "", f"{_stamp(now, '%Y-%m-%d %H:%M')} · {count}", ""]

    # Only when a note came from somewhere else does its origin get printed. On the
    # common case — one session, one project — a tag on every heading would be noise
    # repeating the title, and on the case it exists for it is the whole point.
    others = {n.workspace for n in notes if n.workspace and n.workspace != leaf}

    for note in notes:
        head = _stamp(note.at, "%H:%M")
        if note.question:
            head = f"{head} — {note.question}"
        if others and note.workspace and note.workspace != leaf:
            head = f"{head} · in {note.workspace}"
        lines += [f"## {head}", "", note.text, ""]
    return "\n".join(lines).rstrip() + "\n"


def write(text: str, workspace: str, now: float | None = None) -> Path:
    """Write the document under `workspace`, in a file named for the minute.

    Raises `OSError` — every failure here is one the caller has to say out loud, and a
    swallowed one would leave somebody believing their notes are on disk when they are
    not. The caller keeps the buffer on a raise, so nothing is lost to a full disk.
    """
    now = time.time() if now is None else now
    folder = Path(workspace) / NOTES_DIR
    folder.mkdir(parents=True, exist_ok=True)
    base = _stamp(now, "%Y-%m-%d-%H%M")
    for n in range(1, MAX_FILENAME_TRIES + 1):
        path = folder / (f"{base}.md" if n == 1 else f"{base}-{n}.md")
        try:
            # Exclusive: two wrap-ups in one minute must not have the second silently
            # replace the first. `x` makes the collision an error the loop handles
            # rather than a race between a check and a write.
            with path.open("x", encoding="utf-8", newline="\n") as f:
                f.write(text)
            return path
        except FileExistsError:
            continue
    raise OSError(f"{MAX_FILENAME_TRIES} files already exist for {base}")
