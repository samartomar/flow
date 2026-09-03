"""What Flow learns about one person, on their machine and nowhere else (P8, R9).

Three things are learned, and each exists because a fixed constant was measured to be
wrong for somebody:

  **The room.** The speech gate ships with a starting noise floor of −55 dB and a
  −70 dB lower bound. The first live-microphone run met a quiet room with a good USB
  mic at **−96.7 dB**, which the gate could not descend to, so it never opened at all.
  The bound is fixed now, but the deeper answer is not to guess a room: measure it once
  and remember it.

  **The voice.** `clean.LOW_CONFIDENCE` is one number for every speaker, and
  `avg_logprob` is not comparable between speakers. Measured across 200 accent clips,
  Spanish-accented English sits at a median of −0.62 against −0.27…−0.32 for the other
  four groups — so a threshold tuned on one voice quietly means something different for
  another. A per-user reading turns an absolute bar into a relative one.

  **The words.** Every "change X to Y" the user speaks is a labelled confusion pair
  they produced themselves: the model wrote X, they wanted Y. That is exactly the
  supervision `hotwords` needs, and it costs nothing to collect.

Everything is a plain JSON file under `~/.flow/`, readable and deletable by hand. It
never leaves the machine — R9 is not a policy here, it is that there is no code in this
module that could send anything anywhere.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections import Counter
from pathlib import Path
from typing import Sequence

from . import edits
from .refine import EFFORT_DEFAULT, EFFORTS


# -- per-field validation ---------------------------------------------------
#
# The schema number was checked and the fields were not, so a file that is
# *syntactically* perfect and semantically nonsense — what a hand-edit or a half-written
# sync produces — took the app down inside `Profile()`, before the pill existed. Worse in
# the quiet cases: a string where a number belongs loads clean and detonates later, in
# gate arithmetic a long way from the cause.
#
# Each of these answers "is this usable as the thing it claims to be", never "can I coerce
# it into one". Coercion is how `"false"` became `True` and how `"C:/one"` became five
# one-character workspaces — both silent, both worse than the crash they avoided.


def _text(value, default=None):
    """A non-blank string, or `default`."""
    return value.strip() if isinstance(value, str) and value.strip() else default


def _number(value, default=None):
    """A finite real number, or `default`.

    Returned as stored rather than coerced to float, so a hand-written integer survives a
    load/save round trip unchanged — a validator that quietly rewrites the file it is
    protecting has not protected it.

    `bool` is excluded deliberately: it is a subclass of `int` in Python, so `True` would
    otherwise pass as the number 1 and calibrate a room to 1 dB. Non-finite is excluded
    because NaN and inf survive `json.loads` as genuine floats and then poison every
    comparison they reach — NaN is not equal to itself.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return value if math.isfinite(value) else default


def _flag(value, default: bool) -> bool:
    """A real boolean, or `default`. A string is a wrong type, not a truthy."""
    return value if isinstance(value, bool) else default


def _count(value, default=0) -> int:
    """A running total: a whole number, never negative, or `default`.

    Separate from `_number` because a total is not a measurement. A float here would
    accumulate representation error over years of `+=` and then print a lifetime word
    count with a decimal point in it, and a *negative* one is not a smaller total, it is
    a corrupt file — the only arithmetic that could produce one is a hand edit.

    `bool` is excluded for the same reason `_number` excludes it: `True` is an `int` in
    Python, and a profile whose word count had been overwritten with `true` would
    otherwise report one word dictated ever.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return default
    return value


def _text_list(value, cap: int) -> list[str]:
    """Non-blank strings from a list, bounded. Anything else is an empty list.

    The `isinstance` check is the whole fix for the workspaces case: iterating a *string*
    yields its characters, so `"C:/one"` filled the recents menu with `C`, `:`, `/`, `o`,
    `n` and raised nothing at all.
    """
    if not isinstance(value, list):
        return []
    return [t for t in (_text(v) for v in value) if t][:cap]


def _pair(value) -> list[int] | None:
    """A pair of whole numbers, or None. Never raises, for anything.

    The shape only — whether the point is *on a screen* is `ui._mic_spot`'s question and
    `Pill._placed`'s clamp, for the reason `panel` and `place` are judged there. What is
    settled here is what `save` may write, and the invariant behind that is the suite's:
    no shape of any field, however hand-edited, may raise on the way out. `inf` found
    this — a float is not iterable and `list()` on one is a `TypeError` thrown while
    writing somebody's profile.
    """
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        return [int(value[0]), int(value[1])]
    except (TypeError, ValueError, OverflowError):
        return None


def _text_set(value) -> set[str]:
    if not isinstance(value, (list, tuple, set)):
        return set()
    return {t for t in (_text(v) for v in value) if t}


def _hotkeys(value) -> dict:
    """The hotkey overrides as written: a table, or nothing.

    The one validator here that stops at the shape and does not read the contents, and
    the reason is a line this file cannot cross. Which names are actions and which
    strings are combos is `flow/hotkey.py`'s knowledge — and `flow/hotkey.py` calls
    `ctypes.WinDLL("user32")` at import, so it cannot be imported on a Mac, while this
    module is loaded on every launch including Lite's. Answering "is this usable" here
    would mean a second copy of the key table living on this side of that line, and two
    tables of key names that could disagree is exactly the drift the validators above
    exist to prevent.

    So the entries are carried through untouched — including a value that is not a
    string, which registration refuses by name rather than this dropping it silently.
    That also leaves a typo'd action where its author can see it: Flow declines to use
    the entry and says so, and the file still says what they meant to say, which is the
    same bargain `lexicon.txt` strikes with every line it never reformats.
    """
    return dict(value) if isinstance(value, dict) else {}


def _apps(value) -> dict:
    """The per-app instructions as written: a table, or nothing.

    Shape only, exactly like `_hotkeys`, and the line it stops at is the same one. What
    counts as an application name is `flow/inject.py`'s knowledge — it is whatever
    `Target.process` reports — and that module binds `user32` at import, so it cannot be
    read on a Mac while this one is loaded on every launch including Lite's.

    But the second half of `_hotkeys`' argument does not apply here, and the difference
    is worth being clear about: an action name has five right answers and a typo is
    knowable, whereas an executable name has as many right answers as there are programs
    on the machine. There is no table to check against and no such thing as a name Flow
    can prove wrong — an entry for an app that is not installed is not a mistake, it is
    somebody who has not opened it yet. So nothing here refuses an entry by name the way
    registration does, and a key that never matches simply never fires.

    Values are carried through untouched, including ones that are not strings. The
    instruction is judged where it is used, which is the only place that knows whether it
    has anything to say.
    """
    return dict(value) if isinstance(value, dict) else {}


def _counter(value) -> Counter:
    """`{phrase: positive count}`. Entries that are not that shape are dropped.

    Per-entry rather than per-field: one unparseable row in a learned-words file should
    not cost every other word the user has taught this profile.
    """
    if not isinstance(value, dict):
        return Counter()
    out: Counter[str] = Counter()
    for key, count in value.items():
        name = _text(key)
        if name is None or isinstance(count, bool) or not isinstance(count, int):
            continue
        if count > 0:
            out[name] = count
    return out

DEFAULT_PATH = Path.home() / ".flow" / "profile.json"

#: Bounded like everything else in this project (R8). A profile is a summary, not a log:
#: it must not grow with session length, so the confusion pairs are capped and the
#: least-seen are dropped first.
MAX_PAIRS = 64
MAX_MISROUTES = 32

#: A pair has to recur before it is trusted. One "change X to Y" is as likely to be the
#: user changing their mind as the model mishearing; twice is a pattern.
PROMOTE_AFTER = 2

SCHEMA = 1

#: How many workspaces the recents submenu may carry. The same budget that caps the
#: correction offers at three and the trigger presets at six: the menu is a native
#: modal loop with a measured stall, so nothing offered in it may grow with usage.
MAX_WORKSPACES = 5


#: The shipped modifier-only chord (see `flow/hotkey.py`, `Chord`).
#:
#: Canonical *here* rather than in `flow/hotkey.py`, and the direction is deliberate:
#: this module is imported on every launch including Lite and on a Mac, while
#: `flow.hotkey` binds `user32` at import and cannot be imported at all off Windows. A
#: default the profile could not read without Win32 would be a default Lite could not
#: write back, and a field that vanishes from the file on one platform is worse than one
#: nobody can edit. `flow.hotkey` owns what the string *means*; this owns what it is.
CHORD_DEFAULT = "ctrl+win"

#: The shipped panel width, by name. Spelled here and not imported from `flow/ui.py`
#: for the reason `CHORD_DEFAULT` is not imported from `flow/hotkey.py`: this module is
#: loaded on every launch including Lite's, and a default it could not read without the
#: UI would be a default Lite could not write back. `ui.panel_width` maps the name to
#: pixels and treats an unknown one as this, so the two cannot disagree about anything
#: except the spelling of a word — which `tests/test_overlay.py` checks.
PANEL_DEFAULT = "regular"

#: Where the stack sits, by name — bottom-centre of the monitor under the pointer, or
#: the bottom-right corner Flow shipped. Spelled here rather than imported from
#: `flow/ui.py` for `PANEL_DEFAULT`'s reason, and judged there for the same one.
PLACE_DEFAULT = "bottom"

#: Which gesture the chord is: `"hold"` for push-to-talk, `"toggle"` for the original
#: press-and-release. Spelled here rather than imported from `flow/hotkey.py` for
#: `CHORD_DEFAULT`'s reason — that module binds user32 at import and cannot load on a
#: Mac, and this one is read on every launch including Lite's.
GESTURE_DEFAULT = "hold"

#: How many model names the settings menu will remember. A ceiling rather than a
#: judgement: this list is only ever appended to, by hand, one name at a time, and a menu
#: is not a place for an unbounded list.
CLI_MODEL_CAP = 12


def path_key(path: str | None) -> str | None:
    """One identity for one folder, however it was spelled.

    `D:\\dev\\flow`, `D:/dev/flow` and a trailing slash are the same workspace, and on
    Windows so is a different casing — `normcase+normpath` is the OS's own answer.
    Identity only, never display: the stored spelling stays the user's. None passes
    through so "no workspace" compares like any other value.
    """
    if not path:
        return None
    return os.path.normcase(os.path.normpath(path))


def resolve_workspace(flag: str | None, profile) -> tuple[str | None, str]:
    """(the project to ask from, what to say about it). Never raises, never refuses.

    Precedence matches `--voice`: an explicit flag is a decision, a stored value is a
    preference, and neither is the ordinary case. Returned with its own sentence because
    the whole bargain of this setting is that it is *said* — the owner accepted that a
    workspace goes stale silently when a project moves, on the condition that a wrong
    grounding is on screen rather than buried in JSON.

    A path that no longer exists is reported and dropped. A startup that refuses over a
    stale setting is worse than an ungrounded ask: the project moved, and Flow is not the
    thing that should stop working over it.
    """
    stored = getattr(profile, "workspace", None) if profile is not None else None
    chosen = (flag or stored or "").strip()
    if not chosen:
        return None, "workshop: not set - Ask runs without a project"
    if not Path(chosen).is_dir():
        return None, (f"workshop: {chosen} no longer exists - "
                      "Ask runs without a project")
    return chosen, f"workshop: {chosen}"


class Profile:
    """One person's measured settings and learned words.

    Every field is optional and every read has a fallback, because the first run has no
    profile and a corrupt file must degrade to defaults rather than to a stack trace.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_PATH
        self.floor_db: float | None = None
        self.speech_db: float | None = None
        self.confidence: float | None = None
        self.calibrated_at: float | None = None
        #: The microphone the numbers above were measured through. A calibration is a
        #: measurement of a room *via a device* — the room that broke the shipped gate
        #: read −96.7 dB on a good USB mic, and the same room through a laptop array
        #: reads nothing like it — so the floor, the margin and the confidence baseline
        #: all belong to one microphone. Kept so a swap can be pointed out, never so it
        #: can be refused. Additive: an older profile loads with None and is simply not
        #: compared against anything.
        self.calibrated_device: str | None = None
        #: P9: which voice reads the replies. A name, not an index — the engine's own
        #: identifier, so a voice added or removed between sessions cannot silently
        #: shift the choice onto a different one. No schema bump: every read here has a
        #: fallback, so an older profile loads with no voice and an older Flow ignores
        #: the key it does not know.
        self.voice: str | None = None
        #: P9: whether a settled converse-mode draft asks itself after a pause. The one
        #: setting that decides whether words leave the machine without a press, which
        #: is why it is remembered rather than re-stated every launch. Absent reads as
        #: on, so an existing profile does not acquire a preference nobody expressed;
        #: same no-bump reasoning as `voice`.
        self.auto_ask: bool = True
        #: R5/P7: the words that press Send, and Send-then-Enter. Additive, schema stays
        #: 1, and a blank reads as absent rather than as "off" — `""` would match nothing
        #: and disable the feature silently, which is the `auto_ask` null trap one field
        #: over. **The defaults have to work out of the box**: the owner has said they
        #: will not hand-edit this file, so a feature needing an editor before first use
        #: is dead on arrival for its own requester.
        self.send_word: str = edits.SEND_WORD
        self.send_enter_word: str = edits.SEND_ENTER_WORD
        #: P9: the project a converse-mode question is asked *from*. `refine_cwd` has
        #: existed since converse mode did and was never given a value, so every
        #: question was asked from nowhere. Additive, schema stays 1.
        #:
        #: Its cost, argued once and accepted: a workspace set today goes stale silently
        #: when the project moves. The mitigation is visibility rather than cleverness —
        #: startup and the mode-switch note both name it, so a wrong grounding is on
        #: screen rather than in a file.
        self.workspace: str | None = None
        #: The workspaces this person has actually used, most recent first — the menu's
        #: recents list (item 36). Fed by every `--cwd` arrival and by every menu tap;
        #: there is deliberately no other way in, because a path that never resolved on
        #: this machine has no business being one tap from grounding a question.
        #: Additive, schema stays 1, bounded at MAX_WORKSPACES on save *and* load.
        self.workspaces: list[str] = []
        #: "wrong -> right", counted. Counted rather than listed so a one-off does not
        #: become a permanent bias.
        self.pairs: Counter[str] = Counter()
        #: Utterances the router appended that the user then undid — the signature of a
        #: command read as dictation.
        self.misroutes: Counter[str] = Counter()
        #: Pairs the user has been offered and said no to. Kept so the menu does not ask
        #: again about a decision already made — the answer "no" is worth as much as the
        #: answer "yes" and is otherwise the only one Flow forgets. Additive, and schema
        #: stays 1: an older profile loads with an empty set, exactly as `voice` does.
        self.dismissed: set[str] = set()
        #: Whether the welcome card has been shown. First launch only (item 71): the
        #: arm gesture, one line to try, the trigger word by name, and the colour
        #: legend. Absent reads as **not welcomed**, like `converse_seen` and for the
        #: same reason — an upgrade is the first time the card has existed at all, and a
        #: person who has been using Flow for a week still has not been told what the
        #: colours mean. Additive, schema stays 1.
        self.welcomed: bool = False
        #: Whether converse mode has been entered before. One line is shown on the
        #: conversation card the first time it is, saying that a pause sends the question
        #: and naming the setting that stops it (decisions.md 2026-08-03, part 4).
        #:
        #: A field rather than a session flag, because the thing being remembered is that
        #: *this person* has been told — and the reopen bar on auto-ask's default is one
        #: stranger reporting a surprise send, which is a report that can only come from
        #: somebody who was never warned. Absent reads as **not seen**, so an existing
        #: profile gets the notice once rather than never: an upgrade is the first time
        #: this warning has existed at all. Additive, schema stays 1.
        self.converse_seen: bool = False
        #: How many words have reached the draft from speech on this machine, ever, and
        #: how many milliseconds of speech were behind them. The lifetime half of
        #: `flow --stats`; the today half is derived from the trace, which is the only
        #: file with a clock in it.
        #:
        #: Two integers rather than a per-day table, and that is the whole reason they can
        #: live here at all: this file is a *summary*, forbidden by R8 from growing with
        #: use, and a row per day is a log with a summary's name on it. The trace already
        #: answers "when", is already bounded, and already rotates — so each store is
        #: asked the one question its own bound leaves it able to answer.
        #:
        #: Milliseconds rather than seconds because they are added to per utterance, and
        #: rounding a two-and-a-half second utterance to whole seconds a hundred times a
        #: day is a drift with no upper bound. Additive, schema stays 1: an older profile
        #: loads with zeros, and `flow --stats` says "counting started when this version
        #: first ran" rather than showing somebody a lifetime of nothing.
        self.words_dictated: int = 0
        self.dictated_ms: int = 0
        #: `{action: combo}` — the five global shortcuts, rebound by hand. Absent for
        #: almost everybody, and that is the shape of the feature rather than a shortfall:
        #: the shipped combos work, and this exists for the person one of them collides
        #: with. A settings dialog for it stays refused, so the file somebody already owns
        #: is the surface.
        #:
        #: Only ever the *first* thing tried. Each action keeps its shipped fallbacks
        #: behind whatever is written here, because a chosen combo can be owned by another
        #: program exactly as `ctrl+alt+space` already was on the machine this was built
        #: on — and a rebind that could leave an action with no working combo at all would
        #: be a worse deal than not offering one.
        #:
        #: Additive, schema stays 1: an older profile loads with an empty table and an
        #: older Flow ignores a key it does not know.
        #:
        #: Annotated as the shape a *valid* file holds, and the one caller reads it as
        #: less than that: `_hotkeys` carries an entry whose value is not a string rather
        #: than dropping it, so that registration can refuse it by name.
        self.hotkeys: dict[str, str] = {}
        #: The modifier-only chord, as written. `hotkey.parse_chord` judges what it
        #: means, for the same reason `hotkeys` is judged there: this module is imported
        #: on every launch including Lite, and `flow.hotkey` binds `user32` at import.
        self.chord: str = CHORD_DEFAULT
        #: exe name -> an extra instruction for rewrites made while that app is in front.
        self.apps: dict[str, str] = {}
        #: Which of `ui.PANEL_WIDTHS` the draft panel is drawn at. A name and not a
        #: number: three widths that have each been drawn are worth more than an integer
        #: nobody has rendered at, and the meaning is judged in `flow/ui.py` for the same
        #: reason the hotkey table's is judged in `flow/hotkey.py` — this module is read
        #: on every launch and must not need the module that knows what it means.
        self.panel: str = PANEL_DEFAULT
        #: Where the panels open. `"bottom"` is the shipped placement now — bottom-centre
        #: of whichever monitor the pointer is on — and `"corner"` is the bottom-right
        #: Flow used to use, kept for anybody who wants it back rather than removed.
        self.place: str = PLACE_DEFAULT
        #: Whether the pill draws the mic view: the focused app's initial, the mic and
        #: the level bars, with no chips, marks or panel. A view rather than a mode —
        #: nothing in this package or in `flow/session.py` reads it, and `flow/ui.py`
        #: draws fewer of the events the session emits either way.
        self.mic: bool = False
        #: Where that view sits, as an (x, y), or None for wherever `place` would put
        #: it. Its own field and not a third `PLACES` name because the view anchors no
        #: panel: the two placements exist so a 400-580 px stack is guaranteed to fit,
        #: and a 128 px row fits anywhere. Judged in `flow/ui.py` (`_mic_spot`), which
        #: is also where it is re-clamped against the monitor it is opened on.
        self.mic_at: tuple[int, int] | None = None
        #: How the chord behaves. Both gestures ship because neither replaces the other:
        #: a hold is better for a sentence, a toggle is the only one that survives a
        #: paragraph or a pair of hands that cannot hold two keys down. Judged in
        #: `flow/hotkey.py`, which knows what the words mean.
        self.gesture: str = GESTURE_DEFAULT
        #: Which model to ask the agent CLI for, "" meaning whatever it defaults to, and
        #: how hard to let it think. Both apply to whichever CLI answers - `refine.tuned`
        #: drops either for a CLI not measured to accept it.
        self.cli_model: str = ""
        self.cli_effort: str = EFFORT_DEFAULT
        #: Every model name that has been set, in the order they were first used. The
        #: settings menu has no text field to type one into and is not getting one, so
        #: this list *is* the menu: a name arrives once through `--cli-model` and is a
        #: click from then on.
        self.cli_models: tuple[str, ...] = ()
        #: Field names that were present in the file and unusable, so a caller can say so
        #: rather than leaving the user to notice their setting reverted. Empty on a first
        #: run and on any valid file.
        self.faults: list[str] = []
        self.load()

    # -- persistence -------------------------------------------------------

    def load(self) -> bool:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
            return False
        # Per field, and per field is the whole design. A calibration is the expensive
        # thing in here and the one nobody can re-create by typing, so a nonsense
        # `send_word` must cost the send word and nothing else. `faults` names what
        # degraded, because a setting that silently reverts is indistinguishable from one
        # that never saved.
        self.faults = []

        def take(key, validate, default=None, stored=None):
            present = key in raw and raw[key] is not None
            value = validate(raw.get(key), default)
            if present and value != default:
                return value
            # `stored` is the default as the *file* spells it, for a field whose Python
            # default JSON cannot hold: an empty set is written back as [], and
            # [] != set() read every saved profile as confessing a `dismissed` fault it
            # did not have — noise in a channel that exists to be believed.
            baseline = default if stored is None else stored
            if present and value == default and raw[key] != baseline:
                self.faults.append(key)
            return value

        self.floor_db = take("floor_db", _number)
        self.speech_db = take("speech_db", _number)
        self.confidence = take("confidence", _number)
        self.calibrated_at = take("calibrated_at", _number)
        self.calibrated_device = take("calibrated_device", _text)
        # `bool(None)` is False, so a key that was never written — or written as null by
        # an older Flow — would read as a deliberate "off". Absent means the default.
        self.auto_ask = take("auto_ask", _flag, True)
        # Absent means False here, the opposite way round from `auto_ask` — the default
        # is "has not been told", so an upgrade shows the notice once.
        self.converse_seen = take("converse_seen", _flag, False)
        self.welcomed = take("welcomed", _flag, False)
        self.voice = take("voice", _text)
        # Absent, null and blank all mean "use the shipped word", because none of them is
        # somebody choosing silence. A *wrong type* is different and is reported.
        self.send_word = take("send_word", _text, edits.SEND_WORD)
        self.send_enter_word = take("send_enter_word", _text, edits.SEND_ENTER_WORD)
        self.workspace = take("workspace", _text)
        # Bounded on load, not only on save: the cap is a menu-stall budget, and a
        # hand-grown file must not buy a longer menu than the flag can.
        self.workspaces = take(
            "workspaces", lambda v, _d: _text_list(v, MAX_WORKSPACES), []
        )
        # Zero is the default *and* a legitimate value, so `take`'s "present but degraded"
        # rule does the right thing here for free: a file carrying `0` reports no fault,
        # and one carrying `-3` or `"lots"` names the field so `--stats` can say the total
        # is unusable instead of printing a zero it made up.
        self.words_dictated = take("words_dictated", _count, 0)
        self.dictated_ms = take("dictated_ms", _count, 0)
        # A `hotkeys` that is not a table degrades to none and is named, like any other
        # wrong type. What is *in* the table is judged at registration, where the key
        # names live — see `_hotkeys`, and `hotkey.overridden` for what it says about
        # each entry it refuses.
        self.hotkeys = take("hotkeys", lambda v, _d: _hotkeys(v), {})
        # Absent means the shipped chord, and the empty string means "off" — somebody
        # who does not want a global keyboard hook needs a way to say so that is not
        # deleting the key, because the next save would write it straight back.
        self.chord = take("chord", _text, CHORD_DEFAULT)
        # Same bargain as `hotkeys`: a value that is not a table degrades to none and is
        # named, and what is *in* the table is judged where it is used.
        self.apps = take("apps", lambda v, _d: _apps(v), {})
        self.panel = take("panel", _text, PANEL_DEFAULT)
        self.place = take("place", _text, PLACE_DEFAULT)
        self.mic = take("mic", lambda v, _d: bool(v), False)
        self.mic_at = take("mic_at", lambda v, _d: _pair(v), None)
        self.gesture = take("gesture", _text, GESTURE_DEFAULT)
        self.cli_model = take("cli_model", _text, "")
        self.cli_effort = take("cli_effort", _text, EFFORT_DEFAULT)
        if self.cli_effort not in EFFORTS:
            self.cli_effort = EFFORT_DEFAULT
        self.cli_models = tuple(
            take("cli_models", lambda v, _d=None: _text_list(v, CLI_MODEL_CAP), [])
        )
        self.pairs = take("pairs", lambda v, _d: _counter(v), Counter())
        self.misroutes = take("misroutes", lambda v, _d: _counter(v), Counter())
        # `stored=[]` because JSON has no set: `save` writes this one as a sorted list,
        # so the file's spelling of "nothing dismissed" is [] and must read as clean.
        self.dismissed = take("dismissed", lambda v, _d: _text_set(v), set(), stored=[])
        return True

    def save(self) -> bool:
        payload = {
            "schema": SCHEMA,
            "floor_db": self.floor_db,
            "speech_db": self.speech_db,
            "confidence": self.confidence,
            "calibrated_at": self.calibrated_at,
            "calibrated_device": self.calibrated_device,
            "voice": self.voice,
            "auto_ask": self.auto_ask,
            "converse_seen": self.converse_seen,
            "welcomed": self.welcomed,
            "send_word": self.send_word,
            "send_enter_word": self.send_enter_word,
            "workspace": self.workspace,
            "workspaces": list(self.workspaces[:MAX_WORKSPACES]),
            "words_dictated": self.words_dictated,
            "dictated_ms": self.dictated_ms,
            # Written back exactly as it was read, so a hand-edit survives every save
            # Flow makes on its own — and an empty table lands in every profile, which is
            # the only advertisement this feature gets in a project with no settings
            # dialog to put it in.
            "hotkeys": dict(self.hotkeys),
            "chord": self.chord,
            # Written back as it was read, so a hand-edit survives every save Flow makes
            # on its own — and an empty table lands in every profile, which is the only
            # advertisement this feature gets in a project with no settings dialog.
            "apps": dict(self.apps),
            "panel": self.panel,
            "place": self.place,
            "mic": self.mic,
            # Through `_pair` on the way out as well as in, because this one is written
            # by the UI between loads — `Pill._remember_mic_at` assigns the tuple a drag
            # ended at — so `save` is not only re-emitting what `load` already judged.
            "mic_at": _pair(self.mic_at),
            "gesture": self.gesture,
            "cli_model": self.cli_model,
            "cli_effort": self.cli_effort,
            "cli_models": list(self.cli_models),
            "pairs": dict(self.pairs.most_common(MAX_PAIRS)),
            "misroutes": dict(self.misroutes.most_common(MAX_MISROUTES)),
            # Sorted so two saves of the same state produce the same file — a set's
            # iteration order is not stable across runs, and a profile that rewrites
            # itself differently every launch is one nobody can diff.
            "dismissed": sorted(self.dismissed)[:MAX_PAIRS],
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Written whole then moved, so a crash mid-write cannot leave a profile
            # that loads as garbage and silently resets someone's calibration.
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
            tmp.replace(self.path)
            return True
        except OSError:
            return False

    # -- what was measured -------------------------------------------------

    @property
    def calibrated(self) -> bool:
        return self.floor_db is not None and self.speech_db is not None

    def record_calibration(
        self,
        floor_db: float,
        speech_db: float,
        confidence: float | None,
        device: str | None = None,
    ) -> None:
        self.floor_db = round(floor_db, 1)
        self.speech_db = round(speech_db, 1)
        self.confidence = round(confidence, 3) if confidence is not None else None
        self.calibrated_at = time.time()
        self.calibrated_device = device or None

    def margin_db(self, default: float = 10.0) -> float:
        """How far above the floor speech has to rise before the gate opens.

        Derived, not stored: half the measured gap between this room and this voice,
        bounded either side. A speaker who is 40 dB above their room gets a margin that
        ignores keyboard noise; one who is 12 dB above gets a margin that still opens.
        """
        if self.floor_db is None or self.speech_db is None:
            return default
        gap = self.speech_db - self.floor_db
        return max(6.0, min(18.0, gap / 2.0))

    # -- what was learned --------------------------------------------------

    def learn_pair(self, wrong: str, right: str) -> None:
        """Record one spoken correction as a confusion pair.

        Two things here were quietly throwing away the corrections most worth keeping.

        **Case-only fixes are the point, not a no-op.** The guard used to compare
        `wrong.lower() == right.lower()`, which discards "priya" -> "Priya" — and
        capitalising a name is the single most common vocabulary correction there is.
        The model wrote the lower-case form and the user wants the upper-case one; that
        is exactly the supervision `hotwords` needs. Only an *identical* string is a
        genuine no-op.

        **Punctuation split the counter.** Both sides come from a word-level diff of the
        draft, so the same name arrives as "priya," in one sentence and "priya" in the
        next — two keys, one count each, and a term corrected twice never reaches
        `PROMOTE_AFTER` and is never learned at all. Stripped on *both* sides: the
        right-hand side becomes a hotword verbatim, and "Priya," biases the decoder
        toward a spelling with a comma welded to it.
        """
        edge = ".,!?;:\"'"
        wrong, right = wrong.strip().strip(edge), right.strip().strip(edge)
        if not wrong or not right or wrong == right:
            return
        # A case fix that only *removes* capitals is formatting, not vocabulary:
        # "RELEASE NOTES" -> "release notes" teaches a common phrase, and biasing the
        # decoder toward common phrases is the measured harm in flow/lexicon.py, not the
        # benefit. Going the other way — "priya" -> "Priya", "nasa" -> "NASA" — is a
        # proper noun being marked as one, which is exactly what a hotword is for.
        #
        # Note this tests the pair, not the case of the result: "cube cuttle" ->
        # "kubectl" is not a case variant at all, and an all-lower-case identifier is
        # one of the most valuable terms there is.
        if wrong.lower() == right.lower() and right == right.lower():
            return
        if len(right) > 40 or len(right.split()) > 4:
            return  # a hotword, not a sentence
        self.pairs[f"{wrong.lower()} -> {right}"] += 1
        if len(self.pairs) > MAX_PAIRS:
            for key, _ in self.pairs.most_common()[MAX_PAIRS:]:
                del self.pairs[key]

    def learned_terms(self, promote_after: int = PROMOTE_AFTER) -> list[str]:
        """The right-hand sides seen often enough to bias decoding toward (P4).

        Only the target survives. The wrong reading is what the model already produces
        unaided; feeding it back as a hotword would bias toward the mistake.
        """
        out = []
        for key, count in self.pairs.most_common():
            if count < promote_after:
                continue
            right = key.split(" -> ", 1)[-1]
            if right not in out:
                out.append(right)
        return out

    #: How many offers the menu may carry. It is a native modal loop that already costs
    #: a measured ~16 s stall at worst and one mic-overflow note, so it must not grow
    #: with the profile. The full list has no other UI on purpose: this is not a
    #: settings page, and building one stays refused.
    MAX_OFFERS = 3

    def offered_pairs(
        self,
        declared: Sequence[tuple[str, str]] = (),
        promote_after: int = PROMOTE_AFTER,
        limit: int = MAX_OFFERS,
    ) -> list[tuple[str, str]]:
        """Inferred corrections worth asking the user to declare.

        Asking, and never doing. An inferred pair is a guess from a word-level diff, and
        the difference between "seen twice" and "the user says so" is the whole reason
        `learn_pair` feeds hotwords and not substitutions: a hotword biases toward a
        spelling and changes no text, while a substitution rewrites what somebody said.
        This does not move that line — it moves the *typing*, because a correction that
        requires opening a text file and knowing the arrow syntax is one that will not
        get written.

        `declared` is what the lexicon already contains, matched on the left side the
        way the file itself matches it: case-insensitively. A pair that has been acted
        on stops being offered, so the tap's own consequence clears the menu entry.
        """
        already = {w.strip().lower() for w, _r in declared}
        out: list[tuple[str, str]] = []
        for key, count in self.pairs.most_common():
            if count < promote_after or key in self.dismissed:
                continue
            wrong, _, right = key.partition(" -> ")
            if not wrong or not right or wrong.lower() in already:
                continue
            out.append((wrong, right))
            if len(out) >= limit:
                break
        return out

    def dismiss_pair(self, wrong: str, right: str) -> None:
        """Never offer this one again. Does not unlearn it.

        "Stop asking" is not "forget what you learned": the inferred *hotword* was never
        the thing that needed consent, because it biases toward the right spelling and
        rewrites nothing. Only the substitution did.
        """
        self.dismissed.add(f"{wrong.lower()} -> {right}")

    def note_workspace(self, path: str) -> None:
        """A workspace was chosen — by `--cwd` or by a menu tap. Most recent first.

        Deduplicated by `path_key`, so a relaunch with the same flag spelled
        differently moves the entry to the front instead of growing the list; stored
        as `normpath` so the menu shows one canonical spelling in the user's own case.
        A tap counts as an arrival on purpose: the daily driver switched to from the
        menu must not be evicted by a run of one-off flags. The oldest falling off the
        end is what "recents" means, not a loss.
        """
        path = os.path.normpath((path or "").strip()) if (path or "").strip() else ""
        if not path:
            return
        key = path_key(path)
        self.workspaces = [w for w in self.workspaces if path_key(w) != key]
        self.workspaces.insert(0, path)
        del self.workspaces[MAX_WORKSPACES:]

    def note_misroute(self, utterance: str) -> None:
        """An appended utterance the user immediately undid.

        Kept as a count of the *opening words*, not the whole sentence: the signature of
        a command mis-read as dictation is its verb, and storing whole utterances would
        make this a transcript of everything the user regretted saying.
        """
        head = " ".join(utterance.split()[:3]).lower().strip(" .!?,")
        if not head:
            return
        self.misroutes[head] += 1
        if len(self.misroutes) > MAX_MISROUTES:
            for key, _ in self.misroutes.most_common()[MAX_MISROUTES:]:
                del self.misroutes[key]

    def suspected_aliases(self, promote_after: int = PROMOTE_AFTER) -> list[str]:
        """Openings that repeatedly turned out to be commands, for the alias table.

        This is a *report*, not an automatic rule. Adding to `edits._ALIASES` changes
        what a word means for every future utterance, and the same evidence that says
        "this was a command twice" cannot say "this is never dictation". The audit
        entry is the deliverable; a human decides.
        """
        return [k for k, c in self.misroutes.most_common() if c >= promote_after]

    # -- what was counted --------------------------------------------------

    def note_dictation(self, words: int, seconds: float) -> None:
        """One utterance reached the draft from speech. Add it to the lifetime totals.

        A count and a duration, and neither is reversible into anything: two integers say
        how much was said and for how long, and cannot say what any of it was. That is the
        same line `flow/diag.py` draws with its allow-list, held here by there being
        nothing else to hold.

        Refuses rather than accumulates nonsense. A caller that has miscounted must not be
        able to move a total nothing in the app can correct — there is no UI that edits
        this file, so a bad increment is permanent until somebody deletes their profile.
        `seconds` is allowed to be zero: a replayed utterance has words behind it and no
        audio of its own, and its words still reached the draft.
        """
        if isinstance(words, bool) or not isinstance(words, int) or words <= 0:
            return
        self.words_dictated += words
        if (
            not isinstance(seconds, bool)
            and isinstance(seconds, (int, float))
            and math.isfinite(seconds)
            and seconds > 0
        ):
            self.dictated_ms += int(round(seconds * 1000))
