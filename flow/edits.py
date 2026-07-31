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

Kind = Literal["append", "local", "semantic", "undo"]

# Spoken numbers, for "delete the last two words".
_NUMS = {
    "a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

# Leading hesitation that precedes a correction: "no, change X to Y".
_HEDGE = r"(?:no,?\s+|actually,?\s+|wait,?\s+|sorry,?\s+|i meant\s+)?"

_UNDO = re.compile(
    r"^(?:scratch that|undo(?: that)?|never mind|nevermind|forget that|"
    r"strike that)\b",
    re.I,
)
_REPLACE = re.compile(
    _HEDGE + r"(?:change|replace|swap)\s+(.+?)\s+(?:to|with|for|into)\s+(.+)$", re.I
)
_DELETE_LAST = re.compile(
    r"^(?:delete|remove|drop|cut)\s+(?:the\s+)?last\s+"
    r"(?:(\w+)\s+)?(word|words|sentence|sentences|line|lines)$",
    re.I,
)
_DELETE = re.compile(_HEDGE + r"(?:delete|remove|drop|take out|cut)\s+(.+)$", re.I)
#: "capitalize" and "uppercase" are separated deliberately: each word means what it
#: means. "capitalize john" -> "John", "all caps nasa" -> "NASA". Collapsing both onto
#: upper-case turned "capitalize john" into "JOHN", which is the more jarring mistake.
_CAPS = re.compile(r"^capitali[sz]e\s+(.+)$", re.I)
_UPPER = re.compile(r"^(?:uppercase|all\s+caps|caps)\s+(.+)$", re.I)
_LOWER = re.compile(r"^(?:lowercase\s+(.+)|make\s+(.+?)\s+lowercase)$", re.I)
_BREAK = re.compile(r"^new\s+(paragraph|line)$", re.I)
_INSERT = re.compile(r"^(?:insert|add)\s+(.+?)\s+(before|after)\s+(.+)$", re.I)
_REPLACE_ALL = re.compile(
    r"^replace\s+all\s+(.+?)\s+(?:with|by)\s+(.+)$", re.I
)
_DELETE_RANGE = re.compile(r"^(?:delete|remove|cut)\s+from\s+(.+?)\s+to\s+(.+)$", re.I)

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

    def describe(self) -> str:
        if self.kind == "local":
            return f"{self.op}({self.target!r}" + (
                f" -> {self.payload!r})" if self.payload else ")"
            )
        return self.kind


def _strip(s: str) -> str:
    """Whisper punctuates and capitalises; instructions arrive as 'Change X to Y.'"""
    return s.strip().strip(" .!?,").strip()


def plan(utterance: str, draft: str = "") -> Plan:
    """Decide what a spoken utterance means while a draft is held.

    `draft` is needed, not optional decoration. "Delete key handling is broken" is
    ordinary dictation, while "delete key handling" is an instruction — and nothing in
    the utterance distinguishes them. What distinguishes them is whether the target
    text actually exists in the draft. Requiring that is what makes a weak verb like
    "delete" safe to act on.
    """
    u = _strip(utterance)
    if not u:
        return Plan("append")

    def in_draft(target: str) -> bool:
        return bool(target) and target.lower() in draft.lower()

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
        return Plan("semantic", payload=u)

    # "change X to Y" is a strong instruction shape — the connective makes it hard to
    # produce by accident. So if the target is missing we still treat it as an
    # instruction and let the CLI interpret it, rather than appending it as dictation.
    if m := _REPLACE.match(u):
        target, payload = _strip(m[1]), _strip(m[2])
        if in_draft(target):
            return Plan("local", op="replace", target=target, payload=payload)
        return Plan("semantic", payload=u)

    if m := _DELETE_RANGE.match(u):
        start, end = _strip(m[1]), _strip(m[2])
        if in_draft(start) and in_draft(end):
            return Plan("local", op="delete_range", target=start, payload=end)
        return Plan("semantic", payload=u)

    if m := _INSERT.match(u):
        text, where, anchor = _strip(m[1]), m[2].lower(), _strip(m[3])
        if in_draft(anchor):
            return Plan("local", op=f"insert_{where}", target=anchor, payload=text)
        return Plan("semantic", payload=u)

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
        out = re.sub(re.escape(p.target), p.payload, text, flags=re.I)
        return _tidy(out), out != text

    if p.op == "delete_range":
        low = text.lower()
        start = low.rfind(p.target.lower())
        if start < 0:
            return text, False
        # Search for the end marker only *after* the start, so "delete from X to Y"
        # cannot silently produce a reversed, text-eating range.
        end = low.find(p.payload.lower(), start + len(p.target))
        if end < 0:
            return text, False
        return _tidy(text[:start] + text[end + len(p.payload) :]), True

    if p.op in (
        "replace", "delete", "capitalize", "upper", "lower",
        "insert_before", "insert_after",
    ):
        # Case-insensitive search, hitting the LAST occurrence: a spoken correction
        # almost always refers to what was just said, not to the first time it appeared.
        idx = text.lower().rfind(p.target.lower())
        if idx < 0:
            return text, False
        end = idx + len(p.target)
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
