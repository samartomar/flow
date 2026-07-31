"""Double metaphone, vendored — how a word *sounds*, not how it is spelled.

Defect 4's second half. A spoken correction names a target by sound: the user says
"Sameer", and the draft — transcribed from the same accented voice moments earlier —
says "summer". An exact substring search finds nothing, so a free local edit escalates
to a 7 s CLI call over text that does not contain the word. Comparing phonetic keys
finds it: both encode to `SMR`.

This is a compact implementation of Lawrence Philips' Double Metaphone, covering the
rules that matter for English and for the sound substitutions accented English
actually produces. It is *vendored* rather than installed because R16 caps the
dependency list at three, and a phonetic key is a hundred lines of table lookup — the
kind of thing a dependency should not be spent on.

Two codes are returned because English pronunciation is genuinely ambiguous: "ch" is
K in "school" and X in "chair", and a name may be read either way depending on the
speaker's first language. Two words match if *any* of their codes agree, which is the
tolerant choice, and tolerance is the point.
"""

from __future__ import annotations

import difflib
import re

_VOWELS = "AEIOUY"

#: How close a span must sound before it counts as the target the user named.
#:
#: Swept rather than chosen (scripts/command_bench.py), against ten real
#: mis-transcription pairs and 354 real utterances paired with a word that is
#: genuinely absent:
#:
#:     threshold   pairs found   false spans
#:     0.75          10/10         19/354
#:     0.80          10/10         10/354
#:     0.82          10/10          4/354   <- here
#:     0.85           7/10          4/354
#:     0.90           5/10          3/354
#:
#: 0.82 is where recall is still complete and the false-span rate has already
#: flattened: everything stricter costs three of ten recoveries and buys nothing until
#: 0.90, which trades half the recall for a single false span. Every span it does get
#: wrong produces an edit the user can undo, which is the asymmetry the whole router
#: is built on.
MATCH_THRESHOLD = 0.82


def _is_vowel(s: str, i: int) -> bool:
    return 0 <= i < len(s) and s[i] in _VOWELS


def _at(s: str, start: int, *options: str) -> bool:
    """True if `s` has any of `options` at `start`. Bounds-safe by construction."""
    if start < 0:
        return False
    return any(s[start:start + len(o)] == o for o in options)


def double_metaphone(word: str) -> tuple[str, str]:
    """(primary, alternate) phonetic keys. The alternate repeats the primary when the
    word has only one plausible reading."""
    s = "".join(c for c in word.upper() if c.isalpha())
    if not s:
        return "", ""

    primary: list[str] = []
    alternate: list[str] = []

    def add(p: str, a: str | None = None) -> None:
        primary.append(p)
        alternate.append(p if a is None else a)

    i = 0
    length = len(s)
    # Silent initial clusters: GN, KN, PN, WR, PS all begin with a sound that is not
    # pronounced ("knee", "wrist", "psalm").
    if _at(s, 0, "GN", "KN", "PN", "WR", "PS"):
        i = 1
    # An initial X sounds like S ("Xavier").
    if s[0] == "X":
        add("S")
        i = 1

    while i < length:
        c = s[i]

        if c in _VOWELS:
            # Vowels are only encoded at the very start; inside a word they carry no
            # discriminating information for this purpose.
            if i == 0:
                add("A")
            i += 1
            continue

        if c == "B":
            add("P")
            i += 2 if _at(s, i + 1, "B") else 1
        elif c == "Ç":
            add("S")
            i += 1
        elif c == "C":
            if _at(s, i + 1, "H"):
                # CH is K in Greek-derived words, X ("sh") otherwise — genuinely
                # ambiguous, which is what the alternate code is for.
                if i == 0 and _at(s, i + 2, "AR", "OR", "YM", "IA", "EM"):
                    add("K")
                elif _at(s, i + 2, "AE", "OE"):  # "chaos"-like
                    add("K")
                else:
                    add("X", "K")
                i += 2
            elif _at(s, i + 1, "I") and _at(s, i + 2, "A"):  # "-cia-"
                add("X")
                i += 3
            elif _at(s, i + 1, "E", "I", "Y"):  # soft C
                add("S")
                i += 2 if _at(s, i + 1, "C") else 1
            elif _at(s, i + 1, "K", "Q"):
                add("K")
                i += 2
            else:
                add("K")
                i += 2 if _at(s, i + 1, "C") else 1
        elif c == "D":
            if _at(s, i + 1, "G"):
                if _at(s, i + 2, "E", "I", "Y"):  # "edge"
                    add("J")
                    i += 3
                else:
                    add("TK")
                    i += 2
            else:
                add("T")
                i += 2 if _at(s, i + 1, "D", "T") else 1
        elif c == "F":
            add("F")
            i += 2 if _at(s, i + 1, "F") else 1
        elif c == "G":
            if _at(s, i + 1, "H"):
                if i > 0 and not _is_vowel(s, i - 1):
                    add("K")
                    i += 2
                else:  # "night", "through" — silent
                    i += 2
            elif _at(s, i + 1, "N"):
                add("KN", "N")
                i += 2
            elif _at(s, i + 1, "E", "I", "Y"):  # soft G
                add("J", "K")
                i += 2
            else:
                add("K")
                i += 2 if _at(s, i + 1, "G") else 1
        elif c == "H":
            # Pronounced only between a vowel and a following vowel.
            if (i == 0 or _is_vowel(s, i - 1)) and _is_vowel(s, i + 1):
                add("H")
            i += 1
        elif c == "J":
            add("J", "A")  # "Jose" is H-ish in Spanish; A stands in for that reading
            i += 2 if _at(s, i + 1, "J") else 1
        elif c == "K":
            add("K")
            i += 2 if _at(s, i + 1, "K") else 1
        elif c == "L":
            add("L")
            i += 2 if _at(s, i + 1, "L") else 1
        elif c == "M":
            add("M")
            i += 2 if _at(s, i + 1, "M") else 1
        elif c == "N":
            add("N")
            i += 2 if _at(s, i + 1, "N") else 1
        elif c == "P":
            if _at(s, i + 1, "H"):
                add("F")
                i += 2
            else:
                add("P")
                i += 2 if _at(s, i + 1, "P", "B") else 1
        elif c == "Q":
            add("K")
            i += 2 if _at(s, i + 1, "Q") else 1
        elif c == "R":
            add("R")
            i += 2 if _at(s, i + 1, "R") else 1
        elif c == "S":
            if _at(s, i + 1, "H"):
                add("X")
                i += 2
            elif _at(s, i + 1, "IO", "IA"):  # "-sion", "-sial"
                add("X", "S")
                i += 3
            elif _at(s, i + 1, "CH"):
                add("SK", "X")
                i += 3
            else:
                add("S")
                i += 2 if _at(s, i + 1, "S", "Z") else 1
        elif c == "T":
            if _at(s, i + 1, "IO", "IA"):  # "-tion"
                add("X")
                i += 3
            elif _at(s, i + 1, "H"):
                add("0", "T")  # theta; T is the common non-native substitution
                i += 2
            else:
                add("T")
                i += 2 if _at(s, i + 1, "T", "D") else 1
        elif c == "V":
            add("F")
            i += 2 if _at(s, i + 1, "V") else 1
        elif c == "W":
            # W is only audible before a vowel ("write" begins with R).
            if _is_vowel(s, i + 1):
                add("A" if i == 0 else "F", "F")
            i += 1
        elif c == "X":
            add("KS")
            i += 2 if _at(s, i + 1, "C", "X") else 1
        elif c == "Z":
            add("S")
            i += 2 if _at(s, i + 1, "Z") else 1
        else:
            i += 1

    return "".join(primary), "".join(alternate)


def sounds_like(a: str, b: str) -> bool:
    """True if two words share any phonetic reading. Empty keys never match — a word
    of pure vowels encodes to almost nothing and would otherwise match everything."""
    pa, aa = double_metaphone(a)
    pb, ab = double_metaphone(b)
    if not pa or not pb:
        return False
    return bool({pa, aa} & {pb, ab})


def similarity(a: str, b: str) -> float:
    """0..1, blending sound with spelling.

    Neither signal is enough alone. Phonetic keys are coarse — "Tuesday" and "Thursday"
    both encode to TST/TRST-ish neighbourhoods — while raw string similarity misses the
    substitutions that accent actually produces. The blend takes the better of the two
    when they agree phonetically, and falls back to spelling when they do not.
    """
    a_low, b_low = a.lower().strip(), b.lower().strip()
    if not a_low or not b_low:
        return 0.0
    if a_low == b_low:
        return 1.0
    spelled = difflib.SequenceMatcher(None, a_low, b_low).ratio()
    if not sounds_like(a_low, b_low):
        return spelled
    pa, _ = double_metaphone(a_low)
    pb, _ = double_metaphone(b_low)
    keyed = difflib.SequenceMatcher(None, pa, pb).ratio()
    # Sounding alike is the stronger evidence, but spelling still separates a true
    # match from two words that merely collide in a lossy code.
    return max(spelled, 0.5 + 0.5 * keyed * max(spelled, 0.5))


def _word_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]


def _tighten(text: str, begin: int, end: int) -> tuple[int, int]:
    """Trim punctuation off a matched window.

    Windows are whitespace-delimited, so a match on the last word of a sentence
    includes its full stop — and replacing that span deletes the punctuation with it.
    "Meeting on Tuesday." became "Meeting on Friday" rather than "Meeting on Friday.".
    """
    while begin < end and not text[begin].isalnum():
        begin += 1
    while end > begin and not text[end - 1].isalnum():
        end -= 1
    return begin, end


def find_span(
    text: str, target: str, threshold: float = MATCH_THRESHOLD
) -> tuple[int, int] | None:
    """Where in `text` the user's spoken `target` actually is, or None.

    Exact substring first, because when the transcription is right this must behave
    exactly as it always did — and it must find the **last** occurrence, since a
    spoken correction refers to what was just said rather than to the first mention.

    Failing that, word windows are scored by sound. The window is sized around the
    target's own word count and allowed to vary by one, because a mis-transcription
    changes word boundaries as readily as letters: "Sameer" comes back as "some ear"
    at least as often as "summer".
    """
    if not target.strip() or not text.strip():
        return None
    low_text, low_target = text.lower(), target.lower()
    idx = low_text.rfind(low_target)
    if idx >= 0:
        return idx, idx + len(target)

    words = _word_spans(text)
    if not words:
        return None
    k = len(target.split())
    sizes = {k, k + 1, max(1, k - 1)}
    best: tuple[float, int, int] | None = None
    for size in sizes:
        for start in range(len(words) - size + 1):
            begin, end = words[start][0], words[start + size - 1][1]
            score = similarity(text[begin:end], target)
            # `>=` so that a tie resolves to the later span, matching the exact path.
            if score >= threshold and (best is None or score >= best[0]):
                best = (score, begin, end)
    return _tighten(text, best[1], best[2]) if best else None


def find_spans(
    text: str, target: str, threshold: float = MATCH_THRESHOLD
) -> list[tuple[int, int]]:
    """Every non-overlapping place `target` appears, by sound. Left to right.

    For "replace all X with Y", where X may have been transcribed differently in
    different places — which is precisely what happens to a name the model is unsure
    about.
    """
    if not target.strip() or not text.strip():
        return []
    low_text, low_target = text.lower(), target.lower()
    out: list[tuple[int, int]] = []
    start = 0
    while (idx := low_text.find(low_target, start)) >= 0:
        out.append((idx, idx + len(target)))
        start = idx + len(target)
    if out:
        return out

    words = _word_spans(text)
    k = len(target.split())
    sizes = sorted({k, k + 1, max(1, k - 1)})
    scored: list[tuple[float, int, int]] = []
    for size in sizes:
        for i in range(len(words) - size + 1):
            begin, end = words[i][0], words[i + size - 1][1]
            score = similarity(text[begin:end], target)
            if score >= threshold:
                scored.append((score, begin, end))
    # Best first, then drop anything overlapping an already-taken span, so one region
    # of text cannot be replaced twice.
    for _score, begin, end in sorted(scored, key=lambda r: -r[0]):
        if all(end <= b or begin >= e for b, e in out):
            out.append(_tighten(text, begin, end))
    return sorted(out)
