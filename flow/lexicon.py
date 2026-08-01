"""The user's own words.

Whisper decodes toward what it has seen most, which means a name, a repo, or a piece
of in-house jargon loses to whatever common word sounds nearest — and it loses harder
in an accent, because the acoustic evidence is already weaker (P4). faster-whisper
takes a `hotwords` string that is prepended to the decoder prompt, biasing it toward
those spellings. This module is where that string comes from.

A plain text file, one term per line, `#` for comments, re-read whenever it changes so
editing it does not mean restarting:

    # ~/.flow/lexicon.txt
    Kubernetes
    kubectl
    Grafana
    Samir

Deliberately not a config format. The user editing this is mid-task and annoyed that
their colleague's name keeps coming out wrong; a text file they can open and type into
is the whole interface.

**Biasing is not free, and the measurement says so loudly** (scripts/lexicon_bench.py,
`small.en`, EdAcc). When a term really is being said, biasing recovers **27–34%** of
the rare words the model otherwise missed, for about 3% relative WER. But on speech
containing *none* of the terms — the common case, since a lexicon is the user's
vocabulary rather than this utterance's — WER got **14–38% relatively worse**:
0.221 → 0.252 and 0.223 → 0.265 with 61 terms, and 0.201 → 0.278 with only **eight**.
The harm did not scale down with size, which is why there is no "safe small lexicon"
recommendation here.

So the file does not exist by default, and creating it is the opt-in. That is the
honest shape of the feature given the numbers: useful when a meaningful share of what
you dictate contains your terms, harmful when it does not. The targeted fix is Phase 3's
constrained re-decode — bias *only* when the first pass produced something phonetically
near a lexicon term — which spends the bias where it pays.

The cap is Flow's, not the library's. faster-whisper truncates the prompt at
`max_length // 2 - 1` tokens (223 for these models) *silently*, mid-term, which would
turn "Kubernetes" into a fragment biasing the decoder toward nothing in particular. So
terms are dropped whole, from the end, and the drop is reportable.

**Corrections are the other half, and they are not bias.** A word the recogniser keeps
getting wrong *despite the speaker's effort* is a word bias has already failed on —
live run 1 spent a 7 s CLI call on "Change Semir to Samir" because the name never
survived decoding, with the term in the file. Declaring the confusion is stronger
evidence than hinting at it, so an arrow line

    semir -> Samir

is applied as a substitution on the decoder's output instead: whole words, the left
side case-insensitive, the right side verbatim. Microseconds, no acoustic cost, and
nothing added to the prompt — biasing toward "semir" is the mistake, not the fix. The
arrow is the one the profile's learned pairs are already keyed by, so a pair copied out
of profile.json means here what it means there.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Sequence

#: Where the file lives unless told otherwise. `~` expands on Windows too.
DEFAULT_PATH = Path.home() / ".flow" / "lexicon.txt"

#: A path that cannot exist, for `--no-lexicon`. Pointing the loader at nothing is
#: simpler than threading an enabled flag through the transcriber, and it keeps
#: "no lexicon" and "empty lexicon" the same code path.
NUL_PATH = Path(__file__).resolve().parent / "__no_such_lexicon__"

#: Cap on the prompt Flow will build. The library's own limit is 223 tokens; a term
#: averages 2–4 for the kind of words that end up here (proper nouns, tool names), so
#: 64 terms sits comfortably under it while leaving room for the space separators.
#: Measured cost of a full 64-term lexicon: see PROGRESS.md, 2026-07-31.
MAX_TERMS = 64

#: A single absurd line cannot eat the budget on its own.
MAX_TERM_CHARS = 40

#: What the file says the first time somebody opens the settings folder.
#:
#: Comments only, and that is load-bearing: creating the file must not switch biasing
#: on for a person who wanted to look at the folder. It stays opt-in until they type a
#: line that is not a comment.
#:
#: The measured cost sits next to the thing that costs it, rather than in a doc nobody
#: opens, because the failure it prevents is a lexicon of everything and a session that
#: quietly got worse.
TEMPLATE = """\
# Flow settings - your words, on this machine, read by nothing else.
#
# ONE TERM PER LINE biases the recogniser toward that spelling. Your name, the people
# you write to, your repos and your tools:
#
#   Samir
#   Priya
#   kubectl
#
# Biasing is not free. On speech containing none of these terms - the common case,
# since this is your vocabulary and not this sentence's - word error measured 14-38%
# relatively worse. So keep this to words you actually say, not every word you know.
#
# AN ARROW IS A CORRECTION, and it biases nothing: when the recogniser writes the left
# side, Flow writes the right side instead. This is for the words it keeps getting
# wrong however clearly you say them:
#
#   semir -> Samir
#   cube cuttle -> kubectl
#
# Whole words only; the left side ignores case, the right side is written exactly as
# you type it. 64 lines in all, terms and corrections together.
#
# Saved without restarting Flow: the next thing you say picks this up.
#
# FLOW ADDS A LINE HERE ONLY WHEN YOU ASK IT TO. When it has watched you correct the
# same word twice, it offers the pair in the right-click menu - "Add correction: semir
# -> Samir" - and one tap appends it below. That is the only thing Flow ever writes to
# this file after creating it: one new line at the end, never an edit to yours, never a
# reorder, never a deletion. "Never offer" in the same menu makes it stop asking.
#
# SETTINGS THAT HAVE A VALUE live next door in profile.json - `voice` (which installed
# voice reads replies aloud) and `auto_ask` (true or false: whether a settled converse
# draft asks itself after a pause). Plain JSON, yours to edit, but edit it with Flow
# closed - Flow writes that file too, and the last writer wins.
"""


def entries(text: str) -> tuple[list[str], list[tuple[str, str]]]:
    """(terms, corrections) from file contents, in order, sharing one cap.

    Order is the user's: the first lines in the file are the ones that survive the
    cap, so a lexicon that has grown past it degrades predictably from the bottom.

    One cap over both because there is one file and one person filling it. Counting
    them separately would let 64 corrections buy 64 more hotwords than the measured
    budget allows, which is the one number in this module nobody may quietly raise.

    A half-written line — an arrow with nothing on one side — is dropped rather than
    read as a term, because "semir ->" as a hotword biases toward exactly the spelling
    the user was in the middle of correcting.
    """
    seen_terms: set[str] = set()
    seen_wrong: set[str] = set()
    terms: list[str] = []
    corrections: list[tuple[str, str]] = []
    for line in text.splitlines():
        entry = line.split("#", 1)[0].strip()
        if not entry:
            continue
        wrong, arrow, right = entry.partition("->")
        if arrow:
            wrong, right = wrong.strip(), right.strip()
            # An identical pair is a no-op, but a case fix is the commonest correction
            # there is — "priya" -> "Priya" — so only an exact match is discarded.
            if not wrong or not right or wrong == right:
                continue
            if len(wrong) > MAX_TERM_CHARS or len(right) > MAX_TERM_CHARS:
                continue
            if wrong.lower() in seen_wrong:
                continue
            seen_wrong.add(wrong.lower())
            corrections.append((wrong, right))
        else:
            if len(entry) > MAX_TERM_CHARS or entry.lower() in seen_terms:
                continue
            seen_terms.add(entry.lower())
            terms.append(entry)
        if len(terms) + len(corrections) >= MAX_TERMS:
            break
    return terms, corrections


def parse(text: str) -> list[str]:
    """The terms to bias decoding toward. Arrow lines are not among them."""
    return entries(text)[0]


def pairs(text: str) -> list[tuple[str, str]]:
    """The declared corrections: (what the decoder writes, what to write instead)."""
    return entries(text)[1]


def substitute(text: str, corrections: Sequence[tuple[str, str]]) -> str:
    """Apply declared corrections to one line of decoded text.

    One pass, all corrections at once. Applying them in sequence would let a rewritten
    word be rewritten again by a later line — `a -> b` followed by `b -> c` turning "a"
    into "c" — which makes the file's meaning depend on line order in a way nobody
    typing it intends, and makes a cycle non-terminating.

    Longest left side first, so a two-word correction is not pre-empted by a one-word
    one that starts it. `(?<!\\w)`/`(?!\\w)` rather than `\\b`, because both sides come
    out of a text file and may begin or end with punctuation, where `\\b` means the
    opposite of what is wanted.

    The pattern is rebuilt per call rather than cached: 64 short alternatives is a few
    microseconds against a decode measured in seconds, and `re` keeps its own compiled
    cache anyway. A cache here would be a second copy of the file's state to keep in
    step with the file.
    """
    if not text or not corrections:
        return text
    lookup: dict[str, str] = {}
    for wrong, right in corrections:
        lookup.setdefault(" ".join(wrong.split()).lower(), right)
    # Whitespace inside a phrase is matched loosely: `normalise` has collapsed runs by
    # the time this runs, but a correction is worth applying to text that did not come
    # through it.
    def phrase(wrong: str) -> str:
        return r"\s+".join(re.escape(w) for w in wrong.split())

    ordered = sorted(lookup, key=len, reverse=True)
    pattern = r"(?<!\w)(?:" + "|".join(phrase(w) for w in ordered) + r")(?!\w)"
    return re.sub(
        pattern,
        lambda m: lookup[" ".join(m.group(0).split()).lower()],
        text,
        flags=re.IGNORECASE,
    )


def as_hotwords(terms: list[str]) -> str | None:
    """The string faster-whisper wants, or None when there is nothing to bias toward.

    `None` rather than `""` because an empty string still makes the library build a
    prompt prefix, and paying for a prompt that biases toward nothing is pure cost.
    """
    joined = " ".join(terms).strip()
    return joined or None


def ensure(path: Path | str) -> bool:
    """Write the template if there is no file yet. True if it wrote one.

    Never overwrites: the file is the user's, and the second thing they do with it is
    delete these comments. The parent is created too — `~/.flow` exists as soon as
    anything has been calibrated or learned, but a first run has neither.
    """
    path = Path(path)
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE, encoding="utf-8")
    return True


def append_pair(path: Path | str, wrong: str, right: str) -> str:
    """Add one `wrong -> right` line. "" if it went in, otherwise the reason.

    The whole of what Flow may do to this file. It appends one line, only on an explicit
    tap in the menu, and never edits, reorders or removes one — the file is the user's,
    and the second thing anyone does with it is delete the comments Flow wrote. So the
    existing bytes come back byte for byte and the new line goes at the end.

    A missing file is created from the template first, because the alternative is a file
    containing one arrow and none of the explanation of what an arrow is.

    `MAX_TERMS` is refused rather than trimmed. It is one budget across terms and
    corrections together, and a silent drop past a cap is the exact failure this project
    already found once in the decoder's own library.
    """
    path = Path(path)
    try:
        ensure(path)
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"could not open {path}: {exc}"
    terms, corrections = entries(text)
    if len(terms) + len(corrections) >= MAX_TERMS:
        return (f"the lexicon is full at {MAX_TERMS} entries - "
                "remove a line before adding another")
    # A file whose last line has no newline would otherwise be joined to this one, and
    # `term-> right` is a different entry from either of the two it was made of.
    lead = "" if not text or text.endswith("\n") else "\n"
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"{lead}{wrong} -> {right}\n")
    except OSError as exc:
        return f"could not write {path}: {exc}"
    return ""


class Lexicon:
    """A lexicon file, re-read when it changes.

    Checked by mtime on every decode: a `stat` is microseconds against a decode of
    hundreds of milliseconds, and it means a user can add a name mid-session and have
    the next utterance pick it up.
    """

    def __init__(
        self, path: Path | str | None = None, learned=None
    ) -> None:
        self.path = Path(path) if path is not None else DEFAULT_PATH
        self._terms: list[str] = []
        #: Declared confusions, applied to the decoder's output rather than to its
        #: prompt. Kept apart from `_learned` on purpose: those are inferred from what
        #: the user corrected by hand, and inferring a substitution is not the same
        #: claim as being told one.
        self._pairs: list[tuple[str, str]] = []
        self._stamp: tuple[float, int] | None = None
        self._lock = threading.Lock()
        #: P8: a callable returning terms Flow learned from the user's own corrections,
        #: merged with the file at read time rather than written into it. The file
        #: stays something the user typed and owns; what Flow inferred is kept
        #: separately, so deleting the profile forgets the inferences and nothing else.
        self._learned = learned

    def _merged(self) -> list[str]:
        """File terms first, learned terms after, deduplicated case-insensitively.

        File first because a term the user typed is a stated preference, and the
        `MAX_TERMS` cut has to fall on the inferred tail rather than on it.
        """
        terms = list(self._terms)
        if self._learned is None:
            return terms
        try:
            extra = self._learned() or []
        except Exception:
            return terms  # learning must never be able to break decoding
        seen = {t.lower() for t in terms}
        for term in extra:
            if term.lower() not in seen and len(term) <= MAX_TERM_CHARS:
                terms.append(term)
                seen.add(term.lower())
        return terms[:MAX_TERMS]

    def terms(self) -> list[str]:
        with self._lock:
            self._refresh()
            return self._merged()

    def hotwords(self) -> str | None:
        with self._lock:
            self._refresh()
            return as_hotwords(self._merged())

    def pairs(self) -> list[tuple[str, str]]:
        with self._lock:
            self._refresh()
            return list(self._pairs)

    def apply(self, text: str) -> str:
        """The decoded text with this file's corrections applied.

        The substitution runs outside the lock: it is a regex over an utterance, and
        the lock exists to keep two threads from re-reading the file at once, not to
        serialise work on a string nobody else can see.
        """
        return substitute(text, self.pairs())

    def _refresh(self) -> None:
        try:
            st = self.path.stat()
            stamp = (st.st_mtime, st.st_size)
        except OSError:
            # No file is the normal case, not an error: Flow works without one.
            if self._stamp is not None:
                self._terms, self._pairs, self._stamp = [], [], None
            return
        if stamp == self._stamp:
            return
        try:
            text = self.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return  # mid-write, or a permissions blip; keep the previous terms
        self._terms, self._pairs = entries(text)
        self._stamp = stamp
