"""What this machine actually does, written out at the moment somebody asks.

Generated on every open, never shipped, and that is the design rather than an
implementation detail. Every question a help sheet exists to answer here has a
machine-specific answer: `ctrl+alt+space` is only the *first* alternative in
`DEFAULT_BINDINGS` and was already owned by another app on the development machine, so
the combo that arms the mic is whatever `RegisterHotKey` accepted this launch; the send
trigger is whatever `profile.json` says; the workshop is whatever `--cwd` or the profile
resolved to. A sheet written once would be correct about a machine nobody is sitting at,
which is the failure mode of every help file that has ever gone stale.

The examples are checked rather than asserted in prose: the suite feeds every line of
`COMMANDS` through `edits.plan()` and requires it to come back as the family it is filed
under, so this file cannot document a command the router does not have.

`os.startfile` opens it. Explorer is the viewer the same way it is the settings editor,
and R16 keeps its three dependencies.
"""

from __future__ import annotations

import os
from pathlib import Path

from .edits import SEND_ENTER_WORD, SEND_WORD, TAKE_VERBS

#: The public README, which is the one page that outlives any one machine.
GUIDE_URL = "https://github.com/samartomar/flow#readme"

#: Written beside `lexicon.txt`, in the folder the menu already opens. One settings
#: folder rather than two places to look, at the cost of a generated file sitting next
#: to an editable one - which the first line of the sheet exists to disambiguate.
FILENAME = "commands.txt"

#: What each hotkey does, in the words of the thing it does. An action with no entry
#: renders as its own name rather than being dropped: a combo somebody can press and
#: cannot find here is worse than one described badly.
_ACTIONS = {
    "toggle": "start and stop listening",
    "send": "hand the draft over (Send, or Ask in converse mode)",
    "cancel": "clear the draft, and cut a spoken reply short",
    "mode": "switch between dictate and converse",
    "quit": "close Flow",
}

#: The draft the examples below are aimed at, shown in the sheet rather than implied.
#: Half of these operations are only legal *because* their target is present - that is
#: what makes a weak verb like "delete" safe to act on - and it is the single thing
#: people get wrong about local corrections, so the sheet says it with a draft in hand.
EXAMPLE_DRAFT = (
    "Meeting on Tuesday with Sameer about the release notes. NASA sent the summary."
)

#: (what to say, what it does, the route it must produce). The third column is not
#: documentation: `tests/test_help.py` routes every example against `EXAMPLE_DRAFT` and
#: asserts the family, so an example that stops working fails the suite instead of
#: quietly misleading somebody.
COMMANDS: tuple[tuple[str, str, str], ...] = (
    ("change Tuesday to Wednesday", "replace the last occurrence", "local/replace"),
    ("change every Tuesday to Friday", "every occurrence", "local/replace_all"),
    ("delete the release notes", "remove a phrase", "local/delete"),
    ("delete the last two words", "or 'the last sentence', 'the last line'",
     "local/delete_last"),
    ("delete from Tuesday to Sameer", "remove a whole range", "local/delete_range"),
    ("insert urgent before release", "put words in at a place you name",
     "local/insert_before"),
    ("add today after notes", "the same, on the other side", "local/insert_after"),
    ("capitalize sameer", "-> Sameer", "local/capitalize"),
    ("all caps sameer", "-> SAMEER (also 'uppercase sameer')", "local/upper"),
    ("lowercase NASA", "-> nasa (also 'make NASA lowercase')", "local/lower"),
    ("new paragraph", "or 'new line'", "local/break"),
    ("scratch that", "undo (also 'never mind', 'forget that')", "undo/"),
    ("that was a command", "re-read what you just said as an instruction", "rescue/"),
    ("bring back my last prompt", "restore what Send handed over", "recall/"),
    ("follow up: and add a rollback", "continue the last prompt", "followup/"),
    ("make it a proper prompt", "restructure it (agent CLI, a few seconds)",
     "semantic/polish"),
    ("make it more formal", "any other rewrite (agent CLI)", "semantic/"),
)


def _hotkeys(hotkeys) -> list[str]:
    """The combos that registered, not the ones that were asked for."""
    if hotkeys is None:
        return ["  none this launch (--no-hotkeys) - the pill and the right-click menu",
                "  still do everything the keys do"]
    chosen = getattr(hotkeys, "chosen", {}) or {}
    failed = list(getattr(hotkeys, "failed", []) or [])
    out = [f"  {action:<8}{combo:<20}{_ACTIONS.get(action, action)}"
           for action, combo in chosen.items()]
    # Named as unavailable rather than left out. A shortcut that silently does nothing is
    # the defect `Hotkeys.failed` was built to report, and a sheet that omitted it would
    # send somebody looking for a key that cannot exist on this machine.
    out += [f"  {action:<8}{'NOT AVAILABLE':<20}every alternative combo is owned by "
            "another app" for action in failed]
    return out or ["  none registered - the pill and the right-click menu still work"]


def sheet(hotkeys=None, send_words: tuple[str, str] | None = None,
          workspace_note: str = "") -> str:
    """The whole file, as text. Pure, so the suite can read it without a desktop.

    ASCII only, for the reason the lexicon template is: this is opened by whatever
    Windows hands a `.txt` to, and Notepad on a legacy code page is still a thing people
    have.
    """
    word, enter_word = send_words or (SEND_WORD, SEND_ENTER_WORD)
    lines = [
        "Flow - commands & shortcuts",
        "",
        "Regenerated every time you open it from the menu, so it describes this machine",
        "as it is running right now. Anything typed in here is overwritten. The file you",
        "are meant to edit is lexicon.txt, next door.",
        "",
        "HOTKEYS - the combos that actually registered this launch",
        *_hotkeys(hotkeys),
        "",
        "SAYING SEND INSTEAD OF PRESSING IT",
        f"  {word:<30}paste the draft into the window you were in",
        f"  {enter_word:<30}paste it and press Enter, so a terminal prompt submits",
        # Worded without naming the word, because the word is a setting: the sheet used
        # to illustrate this with "boom goes the dynamite", which stops being true the
        # moment somebody changes the trigger - and this file exists to be true.
        "  Say it on its own. The same word inside a sentence stays dictation, which is",
        "  what makes a false Send rare. Change it in the right-click menu, under",
        "  Settings > Trigger word.",
        "",
        "TALKING TO THE DRAFT",
        "  A correction counts only when the words it names are really in your draft.",
        "  These examples assume the draft says:",
        f"    {EXAMPLE_DRAFT}",
        "",
        *[f"  {say:<33}{does}" for say, does, _route in COMMANDS],
        "",
        "  Hesitation and politeness are absorbed: 'no, sorry, can you delete Tuesday'",
        "  is the same command as 'delete Tuesday'.",
        "",
        "TAKING THE ANSWER INTO THE DRAFT (converse mode)",
        "  " + ", ".join(f"{verb} that answer" for verb in TAKE_VERBS),
        "  Or press the 'Use this' chip on the reply. The answer becomes the draft and",
        "  Flow flips back to dictate, so the next Send pastes it.",
        "",
        "WHERE CONVERSE-MODE QUESTIONS ARE ASKED FROM",
        f"  {workspace_note or 'workshop: not set - Ask runs without a project'}",
        "",
        "THE GUIDE",
        f"  {GUIDE_URL}",
        "",
    ]
    return "\n".join(lines)


def write(folder: Path | str, **kw) -> Path:
    """Write the sheet into the settings folder and return where it went.

    Truncating rather than appending, and unconditionally: the point of the file is that
    it says what is true now, so a stale copy is the one outcome worth refusing. The
    folder is created for the same reason `Profile.save` creates it - a first run that
    has never been calibrated has no `~/.flow/` yet.
    """
    path = Path(folder) / FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sheet(**kw), encoding="utf-8")
    return path


def open_file(path: Path | str) -> None:
    """Hand it to whatever Windows opens a .txt with. Raises OSError, like the caller
    already handles for the settings folder."""
    os.startfile(str(path))


def open_guide() -> None:
    os.startfile(GUIDE_URL)
