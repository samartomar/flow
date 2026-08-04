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

**Rows, not lines.** This used to render a block of text, write it to
`~/.flow/commands.txt` and hand it to Explorer, and the owner's verdict on that was
"which is not help": Notepad is another application's chrome over Flow's content, it
takes the foreground the app spends 96 call sites avoiding, and it leaves a file beside
`lexicon.txt` that looks editable and is not. So the content comes out structured — a
kind, a left column and a right one — and `ui.HelpWindow` draws it in the app's own
idiom. A layout aligned with spaces is a layout for a monospace editor; this one is
drawn, and the columns are positions rather than padding.
"""

from __future__ import annotations

import os
import subprocess
import sys

from .edits import SEND_ENTER_WORD, SEND_WORD, TAKE_VERBS

#: The public README, which is the one page that outlives any one machine. Still opened
#: with the shell: a long-form guide belongs where links work, and a browser is the right
#: application for a browser's content — which is the same argument that took the command
#: sheet out of Notepad.
GUIDE_URL = "https://github.com/samartomar/flow#readme"

TITLE = "Commands & shortcuts"

#: The Settings entry that turns auto-ask off, worded exactly as the menu words it.
#:
#: One constant because three places need to agree: the menu that draws it, the
#: first-entry notice that tells somebody where to find it, and the Help sheet. A notice
#: naming a control that has since been reworded points at nothing, and is worse than no
#: notice at all — it costs the reader a hunt through a menu for a line that is not
#: there. Lives here rather than in `ui.py` because `session.py` needs it and must not
#: import the surface.
AUTO_ASK_OFF_LABEL = "Ask only when I press it"
AUTO_ASK_ON_LABEL = "Ask after a pause"


def auto_ask_notice(seconds: float) -> str:
    """The one line converse mode owes a first-time user (decisions.md 2026-08-03).

    Auto-ask stays ON — with the question pinned on the card, a premature send no longer
    loses anything — and the reopen bar on that default is *one stranger reporting a
    surprise send*. A report like that can only come from somebody who was never told,
    so being told has to happen somewhere they will see it. It printed to a console
    before this, which is a surface no GUI user has open.
    """
    return (f"a pause of {seconds:.0f}s sends the question on its own — "
            f"right-click ▸ Settings ▸ “{AUTO_ASK_OFF_LABEL}” turns that off")

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
#: quietly misleading somebody. Untouched by the move into a window - the route check
#: never looked at the rendering, which is what made the move safe.
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

#: What a row may hold before it runs off the edge. The window draws one line per row and
#: does not wrap - wrapping would make a row's height depend on its content, and the
#: scroll offset is computed from a fixed line height - so the budget is enforced by the
#: suite instead of discovered on screen. Measured against the widest strings above at
#: the window's own column positions, with room to spare rather than to the pixel.
MAX_LEFT, MAX_RIGHT, MAX_NOTE = 32, 58, 82

#: A heading that carries a right column has to clear the same gutter a pair does, and it
#: is drawn bold, so it gets a tighter budget than a heading standing alone. "Taking the
#: answer into the draft" was 32 characters with "converse mode" beside it, which is
#: inside `MAX_LEFT` and still wide enough at 10 pt bold to run into it.
MAX_HEAD = 24


def _fit(text: str, limit: int) -> str:
    """Cut to the budget, marked. The same idiom `edits.removed_text` uses, and here for
    the same reason: exactly one row carries text nobody in this file wrote."""
    text = text.strip()
    if not text:
        return ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _hotkey_rows(hotkeys) -> list[tuple[str, str, str]]:
    """The combos that registered, not the ones that were asked for."""
    if hotkeys is None:
        return [("note", "None this launch (--no-hotkeys) - the pill and the menu still "
                 "do all of it.", "")]
    chosen = getattr(hotkeys, "chosen", {}) or {}
    failed = list(getattr(hotkeys, "failed", []) or [])
    rows = [("pair", combo, _ACTIONS.get(action, action))
            for action, combo in chosen.items()]
    # Named as unavailable rather than left out. A shortcut that silently does nothing is
    # the defect `Hotkeys.failed` was built to report, and a sheet that omitted it would
    # send somebody looking for a key that cannot exist on this machine.
    rows += [("note", f"No combo left for '{action}' - every alternative is owned by "
              "another app.", "") for action in failed]
    return rows or [("note", "None registered. The pill and the right-click menu still "
                     "work.", "")]


def exits_note(hotkeys=None) -> str:
    """One line for the moment Flow stops being able to hear, with a draft still held.

    Live at the desk on 2026-08-02: a render stall overflowed the microphone, and with the
    mic dead every *spoken* rescue was impossible — "boom" needs a decode, a decode needs
    the models, the models need the mic. What still worked was the send hotkey, announced
    once, at startup, in a console nobody was looking at. So the app says it at the moment
    it becomes the only thing left.

    Built here, beside `_hotkey_rows`, and from `hotkeys.chosen` for the same reason the
    sheet is: the combo is whatever `RegisterHotKey` accepted this launch, and a sentence
    written where `DEFAULT_BINDINGS` is in scope is a sentence that will one day name a key
    nobody on that machine can press.

    With no combo — Lite, `--no-hotkeys`, or every alternative for `send` taken — it names
    the chip instead of trailing off. Both other exits need no microphone either, which is
    the only reason they are worth listing at the moment the microphone is the problem.
    """
    send = (getattr(hotkeys, "chosen", {}) or {}).get("send")
    press = f"{send} still sends" if send else "the Send chip still works"
    return f"voice is down — {press}; click the draft to edit, or right-click to copy it"


def _arming_rows(hotkeys, lite: bool) -> list[tuple[str, str, str]]:
    """How the microphone is armed on this machine, which in Lite is not a combo.

    Lite's section is a replacement rather than an emptied version of the full one:
    "absent, not disabled-looking" (product.md). A "Hotkeys" heading with a line saying
    there are none describes a feature that was taken away, when the truth is that
    nothing was registered with the OS and nothing needed to be.
    """
    if lite:
        return [
            ("head", "Arming the microphone", "no global shortcuts in Lite"),
            ("note", "Click the pill. Nothing is registered with the OS, so no other "
             "app loses a combo.", ""),
        ]
    return [
        ("head", "Hotkeys", "the combos that actually registered this launch"),
        *_hotkey_rows(hotkeys),
    ]


def _send_rows(word: str, enter: str, lite: bool) -> list[tuple[str, str, str]]:
    """What the spoken triggers do here. Two bodies, two answers.

    The enter-variant is missing from Lite's list and still understood by the router:
    somebody who learned it in the full body will say it, and the answer to saying it is
    a copy plus a note (`ui.COPIED_ENTER`), not silence. Offered nowhere, handled anyway.
    """
    if lite:
        return [("pair", word, "copy the draft, then paste it where you want it")]
    return [
        ("pair", word, "paste the draft into the window you were in"),
        ("pair", enter, "paste it and press Enter, so a terminal prompt submits"),
    ]


def rows(hotkeys=None, send_words: tuple[str, str] | None = None,
         workspace_note: str = "", lite: bool = False) -> list[tuple[str, str, str]]:
    """The whole sheet as `(kind, left, right)`. Pure - no Tk, no disk.

    Kinds: `head` a section title, `pair` a two-column line, `note` a full-width line,
    `gap` a blank one. The window knows how to draw four things; this knows what there is
    to say. Keeping them apart is what lets the suite assert the content without a
    desktop and the window change without touching the content.

    `lite` changes only the two sections that describe hands. Everything else - the
    corrections, the take verbs, the workshop line - is the same brain and reads the same.
    """
    word, enter = send_words or (SEND_WORD, SEND_ENTER_WORD)
    out: list[tuple[str, str, str]] = [
        ("note", "Regenerated every time you open it, so this is the machine you are on "
         "right now.", ""),
        ("gap", "", ""),
        *_arming_rows(hotkeys, lite),
        ("gap", "", ""),
        ("head", "Saying Send instead of pressing it", ""),
        *_send_rows(word, enter, lite),
        # Worded without naming the word, because the word is a setting: this used to
        # illustrate whole-utterance matching with "boom goes the dynamite", which stops
        # being true the moment somebody changes the trigger - and the sheet exists to be
        # true.
        ("note", "Say it on its own - the same word inside a sentence stays "
         "dictation.", ""),
        ("note", "Change it under Settings > Trigger word.", ""),
        ("gap", "", ""),
        ("head", "Talking to the draft", "these examples assume your draft says:"),
        ("note", EXAMPLE_DRAFT, ""),
        ("note", "A correction counts only when the words it names are really in "
         "your draft.", ""),
        ("gap", "", ""),
        *[("pair", say, does) for say, does, _route in COMMANDS],
        ("gap", "", ""),
        ("note", "Politeness is absorbed: 'can you please delete Tuesday' is the same "
         "command.", ""),
        ("gap", "", ""),
        ("head", "Taking the answer", "converse mode"),
        *[("pair", f"{verb} that answer",
           "the answer becomes the draft; Flow flips to dictate"
           if verb == TAKE_VERBS[0] else "")
          for verb in TAKE_VERBS],
        ("note", "Or press the 'Use this' chip on the reply.", ""),
        ("gap", "", ""),
        ("head", "Where converse-mode questions are asked from", ""),
        ("note", workspace_note or "workshop: not set - Ask runs without a project", ""),
        ("gap", "", ""),
        ("head", "The guide", "right-click > Help > Open the guide"),
        ("note", GUIDE_URL, ""),
    ]
    limits = {"pair": (MAX_LEFT, MAX_RIGHT), "note": (MAX_NOTE, 0),
              "head": (MAX_NOTE, MAX_RIGHT), "gap": (0, 0)}
    return [(kind, _fit(left, limits[kind][0]), _fit(right, limits[kind][1]))
            for kind, left, right in out]


def open_path(target: str) -> None:
    """Hand a file, a folder or a URL to whatever this OS opens things with.

    `os.startfile` is Windows-only and is the whole implementation of two menu entries,
    so Lite would lose both to an `AttributeError` raised inside a Tk callback. stdlib
    `subprocess` elsewhere — R16 still holds at three declared dependencies.

    Everything that goes wrong leaves as `OSError`, because that is the contract both
    callers already report on screen: `subprocess.run` raises `FileNotFoundError` (an
    OSError) when the opener is missing, and `CalledProcessError` — which is not one —
    when it runs and refuses, so the second is translated rather than allowed to escape
    into a menu handler that does not catch it.
    """
    if sys.platform == "win32":
        os.startfile(target)
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    try:
        subprocess.run([opener, str(target)], check=True)
    except subprocess.SubprocessError as exc:
        raise OSError(f"{opener} could not open {target}: {exc}") from exc


def open_guide() -> None:
    """Hand the README to the browser. Raises OSError, which the caller reports."""
    open_path(GUIDE_URL)
