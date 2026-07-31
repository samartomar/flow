"""Routing a spoken utterance in the DRAFT state, and applying the cheap edits locally.

This module is where R11 is actually enforced. Measurement (PROGRESS.md, stage 2a) put
both agent CLIs at ~7 s per call, which is a floor rather than a warm-up cost. A spoken
"change Tuesday to Wednesday" that takes 7 s is slower than fixing it by hand, so the
CLI cannot sit on the correction path.

So utterances are routed three ways, and only the third pays for a CLI:

  APPEND    - not a correction at all; more dictation (R7)
  LOCAL     - a literal correction expressible as a string operation (R6), applied
              in microseconds with no dependency and no subprocess
  SEMANTIC  - a genuine rewrite request ("make it more formal"), where a visible
              wait is acceptable because the user asked for a rewrite, not a fix

Ambiguity between APPEND and a correction is resolved by shape, not by asking a model.
That is cheap and it is wrong sometimes; it is only tolerable because every edit is
undoable, so a mis-route costs one undo rather than lost text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .phonetic import find_span, find_spans

Kind = Literal["append", "local", "semantic", "undo", "rescue"]

# Spoken numbers, for "delete the last two words".
_NUMS = {
    "a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

#: What people actually say before a correction, and it is more than hesitation.
#: Politeness is the half that was missing: a non-native speaker asking a tool to do
#: something reaches for "can you", "could you please" far more readily than a native
#: speaker barking "delete that" — so the polite forms were being routed as dictation
#: and appended into the draft verbatim. Repeatable (`*`), because "no, sorry, can you"
#: is one utterance, not three.
_LEAD = (
    r"(?:(?:no|actually|wait|sorry|hang on|hold on|erm|um|uh|okay|ok|right|so|"
    r"i mean|i meant)[,]?\s+|(?:can|could|would|will) you,?\s+|please,?\s+|"
    r"let's,?\s+|lets,?\s+|just,?\s+)*"
)

#: Kept as the old name so the patterns read the same; it is now the full lead-in.
_HEDGE = _LEAD

#: "That was a command" — the user telling Flow it misheard the *kind* of the last
#: utterance, not its words. Undo plus re-speaking costs two utterances and the user's
#: patience; this costs one short phrase and re-reads what they already said.
_RESCUE = re.compile(
    "^" + _LEAD + r"(?:that was (?:a|an) (?:command|instruction|edit)|"
    r"i meant that as (?:a|an) (?:command|instruction|edit)|"
    r"that was meant as (?:a|an) (?:command|instruction|edit)|"
    r"no,? that was (?:a|an) (?:command|instruction|edit))(?:\W|$)",
    re.I,
)

_UNDO = re.compile(
    "^" + _LEAD + r"(?:scratch that|undo(?: that)?|never mind|nevermind|"
    r"forget that|strike that)\b",
    re.I,
)
_REPLACE = re.compile(
    "^" + _LEAD + r"(?:change|replace|swap)\s+(.+?)\s+(?:to|with|for|into)\s+(.+)$",
    re.I,
)
_DELETE_LAST = re.compile(
    "^" + _LEAD + r"(?:delete|remove|drop|cut)\s+(?:the\s+)?last\s+"
    r"(?:(\w+)\s+)?(word|words|sentence|sentences|line|lines)$",
    re.I,
)
_DELETE = re.compile(
    "^" + _LEAD + r"(?:delete|remove|drop|take out|cut)\s+(.+)$", re.I
)
#: "capitalize" and "uppercase" are separated deliberately: each word means what it
#: means. "capitalize john" -> "John", "all caps nasa" -> "NASA". Collapsing both onto
#: upper-case turned "capitalize john" into "JOHN", which is the more jarring mistake.
_CAPS = re.compile("^" + _LEAD + r"capitali[sz]e\s+(.+)$", re.I)
_UPPER = re.compile("^" + _LEAD + r"(?:uppercase|all\s+caps|caps)\s+(.+)$", re.I)
_LOWER = re.compile(
    "^" + _LEAD + r"(?:lowercase\s+(.+)|make\s+(.+?)\s+lowercase)$", re.I
)
_BREAK = re.compile("^" + _LEAD + r"new\s+(paragraph|line)$", re.I)
_INSERT = re.compile(
    "^" + _LEAD + r"(?:insert|add)\s+(.+?)\s+(before|after)\s+(.+)$", re.I
)
_REPLACE_ALL = re.compile(
    "^" + _LEAD + r"replace\s+all\s+(.+?)\s+(?:with|by)\s+(.+)$", re.I
)
_DELETE_RANGE = re.compile(
    "^" + _LEAD + r"(?:delete|remove|cut)\s+from\s+(.+?)\s+to\s+(.+)$", re.I
)

#: Pronouns that are not usable edit targets — "make it lowercase" is a request about
#: the whole draft, not about the word "it", so it belongs to the CLI.
_PRONOUNS = {"it", "this", "that", "everything", "all of it", "the whole thing"}

# Verbs that ask for judgement rather than a substitution — these are the only
# utterances allowed to reach a CLI.
_SEMANTIC = re.compile(
    r"^(?:make (?:it|this|that)\b|rewrite\b|reword\b|rephrase\b|shorten\b|"
    r"tighten\b|expand\b|summari[sz]e\b|turn (?:it|this|that) into\b|"
    r"fix (?:the )?(?:grammar|typos|spelling)\b|format (?:it|this)\b|"
    r"bullet(?: point)?\b|proofread\b|clean (?:it|this) up\b)",
    re.I,
)


@dataclass
class Plan:
    kind: Kind
    #: For LOCAL: the concrete operation. For SEMANTIC: the instruction to hand a CLI.
    target: str = ""
    payload: str = ""
    op: str = ""
    count: int = 1
    #: True when this became SEMANTIC only because the target could not be found —
    #: "change X to Y" where no X is in the draft. That is a *suspected mis-hearing*,
    #: not a request for judgement, and it is worth one cheap re-decode before paying
    #: ~7 s for a CLI that will be asked to edit text not containing the word.
    escalated: bool = False

    def describe(self) -> str:
        if self.kind == "local":
            return f"{self.op}({self.target!r}" + (
                f" -> {self.payload!r})" if self.payload else ")"
            )
        return self.kind


def _strip(s: str) -> str:
    """Whisper punctuates and capitalises; instructions arrive as 'Change X to Y.'"""
    return s.strip().strip(" .!?,").strip()


#: The verbs a command can start with. Snapping only ever produces one of these.
_COMMAND_VERBS = (
    "change", "replace", "swap", "delete", "remove", "drop", "cut", "insert",
    "add", "capitalize", "capitalise", "uppercase", "lowercase", "scratch",
    "undo", "forget", "strike",
)

#: Mis-hearings too far from the intended word for edit distance to reach — the audit's
#: own examples. "the lead" is three edits from "delete" and would never snap, but it
#: is exactly what an accented "delete" comes back as.
#:
#: Every one of these is a *word people also say normally* ("stop", "at", "ad"), which
#: is why an alias never decides anything by itself: `plan()` only accepts a snapped
#: reading when it produces a local edit whose target is really in the draft. A wrong
#: guess costs nothing because it is discarded, not applied.
_ALIASES = {
    "the lead": "delete",
    "de lead": "delete",
    "delete the": "delete",
    "believe": "delete",
    "leplace": "replace",
    "re place": "replace",
    "displace": "replace",
    "stop": "swap",
    "swab": "swap",
    "shop": "swap",
    "chains": "change",
    "chain": "change",
    "cheng": "change",
    "in start": "insert",
    "in sert": "insert",
    "at": "add",
    "ad": "add",
    "scratched": "scratch",
    "scratch hat": "scratch that",
    "under that": "undo that",
    "and do that": "undo that",
    "cap it all eyes": "capitalize",
    "capital eyes": "capitalize",
    "low case": "lowercase",
    "up a case": "uppercase",
}

#: Suffixes a model adds to a verb it half-heard: "deletes", "deleting", "deleted".
_VERB_SUFFIXES = ("ing", "ed", "es", "s")


def _within_one_edit(a: str, b: str) -> bool:
    """True if `a` and `b` differ by at most one insert, delete or substitution.

    Bounded on purpose rather than a general Levenshtein: the question is only ever
    "is this the same word slightly mis-heard", and anything further away is a
    different word that the alias table should be deciding about explicitly.
    """
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        diffs = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
        if len(diffs) <= 1:
            return True
        # One transposition of adjacent letters — "deleet" for "delete". Two
        # substitutions by the strict definition, but a single slip of the ear, and
        # common enough in ASR output to be worth its own case.
        if len(diffs) == 2 and diffs[1] == diffs[0] + 1:
            i, j = diffs
            return a[i] == b[j] and a[j] == b[i]
        return False
    # One insertion: walk both, allowing a single skip in the longer string.
    short, long = (a, b) if la < lb else (b, a)
    i = j = 0
    skipped = False
    while i < len(short) and j < len(long):
        if short[i] == long[j]:
            i += 1
            j += 1
        elif skipped:
            return False
        else:
            skipped = True
            j += 1
    return True


def _snap_verb(word: str) -> str | None:
    """The command verb this word was probably meant to be, or None.

    Short words are matched exactly: at three characters or fewer, one edit reaches
    too many unrelated words ("cut" would swallow "but", "cat", "cup").
    """
    low = word.lower()
    if low in _COMMAND_VERBS:
        return low
    if len(low) <= 3:
        return None
    # Stem first, then match: "deleting" strips to "delet", which is not a verb but is
    # one edit from one. Both halves of the mis-hearing have to be undone at once.
    stems = [low] + [
        low[: -len(s)] for s in _VERB_SUFFIXES if low.endswith(s) and len(low) > len(s)
    ]
    for stem in stems:
        if stem in _COMMAND_VERBS:
            return stem
    for stem in stems:
        if len(stem) <= 3:
            continue
        hit = next((v for v in _COMMAND_VERBS if _within_one_edit(stem, v)), None)
        if hit:
            return hit
    return None


#: Snapping only applies to utterances this short, counted after any lead-in.
#:
#: Measured: without this, suffix-stripping turned two sentence-opening gerunds into
#: commands — "Deleting a branch does not delete the history" became a delete, and
#: "Changing Tuesday to Wednesday broke the booking" became a replace. Both are
#: ordinary dictation, and both are long. Spoken commands are short: every entry in
#: the inventory is five words or fewer, so a guess about a long utterance is a guess
#: about a sentence, and it is not worth making.
SNAP_MAX_WORDS = 6

_LEAD_ONLY = re.compile("^" + _LEAD, re.I)


def snap(utterance: str) -> str:
    """Rewrite a mis-heard leading verb into the verb it was meant to be.

    Only the front of the utterance is touched — the target words are the user's own
    text and must not be "corrected" into something else. Aliases are tried longest
    first so "scratch hat" beats "scratch".
    """
    u = _strip(utterance)
    # The lead-in is split off first, not just skipped for counting: "could you please
    # deleting Tuesday" hides the verb behind three words of politeness, and snapping
    # the *first* token would only ever look at "could".
    m = _LEAD_ONLY.match(u)
    lead, body = (u[: m.end()], u[m.end():]) if m else ("", u)
    if len(body.split()) > SNAP_MAX_WORDS:
        return u

    low = body.lower()
    for phrase in sorted(_ALIASES, key=len, reverse=True):
        if low == phrase or low.startswith(phrase + " "):
            return (lead + _ALIASES[phrase] + body[len(phrase):]).strip()
    head, _, rest = body.partition(" ")
    snapped = _snap_verb(head)
    if snapped and snapped != head.lower():
        return f"{lead}{snapped} {rest}".strip()
    return u


def plan(utterance: str, draft: str = "") -> Plan:
    """Decide what a spoken utterance means while a draft is held.

    `draft` is needed, not optional decoration. "Delete key handling is broken" is
    ordinary dictation, while "delete key handling" is an instruction — and nothing in
    the utterance distinguishes them. What distinguishes them is whether the target
    text actually exists in the draft. Requiring that is what makes a weak verb like
    "delete" safe to act on.

    Two passes. The utterance is read as spoken first; only if that produces no local
    edit is it re-read with a snapped verb (`snap()`), and that reading is accepted
    **only when it yields a local edit whose target is really in the draft**. So a
    guess can promote a mis-heard command to the thing the user meant, and can never
    demote ordinary dictation into an edit — "stop" only becomes "swap" when the words
    after it are genuinely in the draft, which is the same evidence the exact grammar
    already demands.
    """
    exact = _plan_exact(utterance, draft)
    if exact.kind == "local":
        return exact
    snapped = snap(utterance)
    if snapped.lower() != _strip(utterance).lower():
        fuzzy = _plan_exact(snapped, draft)
        if fuzzy.kind == "local":
            return fuzzy
        # Undo has no target to verify, so it is promoted only from the alias table,
        # never from an edit-distance guess: a spurious undo throws away real work.
        if fuzzy.kind == "undo" and exact.kind != "undo" and _is_alias(utterance):
            return fuzzy
    return exact


def _is_alias(utterance: str) -> bool:
    low = _strip(utterance).lower()
    return any(low == p or low.startswith(p + " ") for p in _ALIASES)


def _plan_exact(utterance: str, draft: str = "") -> Plan:
    u = _strip(utterance)
    if not u:
        return Plan("append")

    def in_draft(target: str) -> bool:
        # Phonetic, not literal: the draft was transcribed from the same voice moments
        # earlier, so the word the user is naming may be spelled differently there.
        return bool(target) and find_span(draft, target) is not None

    # Before undo: "no, that was a command" starts like a hedge and must not be read
    # as one.
    if _RESCUE.match(u):
        return Plan("rescue")

    if _UNDO.match(u):
        return Plan("undo")

    if m := _BREAK.match(u):
        return Plan("local", op="break", payload="\n\n" if m[1].lower() == "paragraph" else "\n")

    if m := _DELETE_LAST.match(u):
        word, unit = m[1], m[2].lower()
        n = _NUMS.get((word or "one").lower(), 1)
        if word and word.isdigit():
            n = int(word)
        return Plan("local", op="delete_last", target=unit.rstrip("s"), count=n)

    # Must precede the generic _REPLACE: "replace all Bob with Alice" also matches
    # that pattern, but with target "all Bob", which is never in the draft — so it
    # would silently escalate to the CLI instead of doing a free local replacement.
    if m := _REPLACE_ALL.match(u):
        target, payload = _strip(m[1]), _strip(m[2])
        if in_draft(target):
            return Plan("local", op="replace_all", target=target, payload=payload)
        return Plan("semantic", payload=u, target=target, escalated=True)

    # "change X to Y" is a strong instruction shape — the connective makes it hard to
    # produce by accident. So if the target is missing we still treat it as an
    # instruction and let the CLI interpret it, rather than appending it as dictation.
    if m := _REPLACE.match(u):
        target, payload = _strip(m[1]), _strip(m[2])
        if in_draft(target):
            return Plan("local", op="replace", target=target, payload=payload)
        return Plan("semantic", payload=u, target=target, escalated=True)

    if m := _DELETE_RANGE.match(u):
        start, end = _strip(m[1]), _strip(m[2])
        if in_draft(start) and in_draft(end):
            return Plan("local", op="delete_range", target=start, payload=end)
        return Plan("semantic", payload=u, target=start, escalated=True)

    if m := _INSERT.match(u):
        text, where, anchor = _strip(m[1]), m[2].lower(), _strip(m[3])
        if in_draft(anchor):
            return Plan("local", op=f"insert_{where}", target=anchor, payload=text)
        return Plan("semantic", payload=u, target=anchor, escalated=True)

    # Case operations. Weak shapes that collide with normal speech, so like `delete`
    # they only count as instructions when the target is really in the draft.
    for pattern, op in ((_CAPS, "capitalize"), (_UPPER, "upper"), (_LOWER, "lower")):
        if m := pattern.match(u):
            target = _strip(next(g for g in m.groups() if g))
            if target.lower() in _PRONOUNS:
                return Plan("semantic", payload=u)
            if in_draft(target):
                return Plan("local", op=op, target=target)
            return Plan("append")

    # Ordered after the structural forms: "delete the last two words" must not be
    # swallowed by the generic delete rule.
    if m := _DELETE.match(u):
        target = _strip(m[1])
        if in_draft(target):
            return Plan("local", op="delete", target=target)
        return Plan("append")

    if _SEMANTIC.match(u):
        return Plan("semantic", payload=u)

    return Plan("append")


def apply_local(text: str, p: Plan) -> tuple[str, bool]:
    """Apply a LOCAL plan. Returns (new_text, applied).

    `applied=False` means the target was not found in the draft — the caller should
    escalate to the CLI rather than silently doing nothing, because the user did ask
    for something and a no-op would look like the app ignored them.
    """
    if p.op == "break":
        return text + p.payload, True

    if p.op == "delete_last":
        if p.target == "word":
            parts = text.split()
            if len(parts) < p.count:
                return text, False
            return " ".join(parts[: -p.count]), True
        # sentence / line
        sep = "\n" if p.target == "line" else None
        if sep:
            parts = [x for x in text.split(sep) if x.strip()]
        else:
            parts = [x for x in re.split(r"(?<=[.!?])\s+", text) if x.strip()]
        if len(parts) < p.count:
            return text, False
        joined = (sep or " ").join(parts[: -p.count])
        return joined.strip(), True

    if p.op == "replace_all":
        # Spans, not `re.sub`: the target may be spelled differently in different
        # places (a name the model was unsure about twice), and the payload must be
        # inserted literally — as a substitution template, a dictated backslash reads
        # as a group reference and either raises or splices in captured text.
        # Right to left, so each replacement cannot shift the spans still to come.
        spans = find_spans(text, p.target)
        out = text
        for begin, end in reversed(spans):
            out = out[:begin] + p.payload + out[end:]
        return _tidy(out), out != text

    if p.op == "delete_range":
        first = find_span(text, p.target)
        if first is None:
            return text, False
        start = first[0]
        # Search for the end marker only *after* the start, so "delete from X to Y"
        # cannot silently produce a reversed, text-eating range.
        tail = find_span(text[first[1]:], p.payload)
        if tail is None:
            return text, False
        return _tidy(text[:start] + text[first[1] + tail[1]:]), True

    if p.op in (
        "replace", "delete", "capitalize", "upper", "lower",
        "insert_before", "insert_after",
    ):
        # Hits the LAST occurrence: a spoken correction almost always refers to what
        # was just said, not to the first time it appeared. Phonetic, so the span may
        # be spelled differently from what the user said — `found` is the draft's own
        # text, which is what case operations must transform.
        span = find_span(text, p.target)
        if span is None:
            return text, False
        idx, end = span
        found = text[idx:end]
        if p.op == "replace":
            new = p.payload
        elif p.op == "delete":
            new = ""
        elif p.op == "capitalize":
            new = found.title()
        elif p.op == "upper":
            new = found.upper()
        elif p.op == "lower":
            new = found.lower()
        elif p.op == "insert_before":
            new = f"{p.payload} {found}"
        else:
            new = f"{found} {p.payload}"
        return _tidy(text[:idx] + new + text[end:]), True

    return text, False


def _tidy(s: str) -> str:
    """Clean up what an edit leaves behind.

    Deleting a phrase that sat between two commas strands both of them next to each
    other ("Keep this,, keep the end"), so adjacent marks are collapsed too.
    """
    s = re.sub(r" {2,}", " ", s)
    s = re.sub(r"\s+([,.!?;:])", r"\1", s)
    s = re.sub(r"([,;:])(?:\s*[,;:])+", r"\1", s)  # ",," -> ","
    s = re.sub(r",\s*\.", ".", s)  # ",." -> "."
    return s.strip()


def command_bias(draft: str, limit: int = 48) -> str:
    """The vocabulary a suspected command should be re-decoded against.

    Every trigger verb, plus the words already in the draft — because the target of a
    correction is, by definition, something already on screen. Biasing toward exactly
    those two sets is what makes a second pass worth running: it is not a better model,
    it is the same model told what the answer is likely to be drawn from.

    Bounded, longest words first: the draft can be arbitrarily long, and the lexicon
    measurement in PROGRESS.md is emphatic that a large irrelevant prompt costs
    accuracy. Long words carry more information and are likelier to be the ones a
    decoder gets wrong.
    """
    seen: set[str] = set()
    words: list[str] = []
    for token in re.findall(r"[A-Za-z][A-Za-z'-]+", draft):
        key = token.lower()
        if key not in seen and len(token) > 3:
            seen.add(key)
            words.append(token)
    words.sort(key=len, reverse=True)
    room = max(0, limit - len(_COMMAND_VERBS))
    return " ".join((*_COMMAND_VERBS, *words[:room]))
