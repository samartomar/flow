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


def _text_list(value, cap: int) -> list[str]:
    """Non-blank strings from a list, bounded. Anything else is an empty list.

    The `isinstance` check is the whole fix for the workspaces case: iterating a *string*
    yields its characters, so `"C:/one"` filled the recents menu with `C`, `:`, `/`, `o`,
    `n` and raised nothing at all.
    """
    if not isinstance(value, list):
        return []
    return [t for t in (_text(v) for v in value) if t][:cap]


def _text_set(value) -> set[str]:
    if not isinstance(value, (list, tuple, set)):
        return set()
    return {t for t in (_text(v) for v in value) if t}


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

        def take(key, validate, default=None):
            present = key in raw and raw[key] is not None
            value = validate(raw.get(key), default)
            if present and value != default:
                return value
            if present and value == default and raw[key] != default:
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
        self.pairs = take("pairs", lambda v, _d: _counter(v), Counter())
        self.misroutes = take("misroutes", lambda v, _d: _counter(v), Counter())
        self.dismissed = take("dismissed", lambda v, _d: _text_set(v), set())
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
