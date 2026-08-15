"""How much has been dictated, counted out of what Flow already writes down.

Flow has recorded every route it took since the trace existed and has never once said
what any of it added up to. The number people quote when they recommend a dictation app
is not the word error rate, it is how much of their day they got back — and Flow held
every part of that number and printed none of it.

**Two stores, because there are two questions and neither store can answer both.**

  *Today* comes from `~/.flow/diag.jsonl`. The trace is the only thing here with a clock
  in it, so it is the only thing that can say *when* a word was dictated. What it cannot
  say is "ever": it is bounded at a megabyte and rotates once (R8), so the history it
  holds is roughly two days of heavy use and then gone.

  *All time* comes from two integers in `~/.flow/profile.json`. The profile is a summary
  and is forbidden from growing with use, which is exactly why it cannot answer "today" —
  doing that needs a row per day, and a row per day is a log wearing a summary's name.
  Two counters cost 40 bytes forever.

So each store is asked the one question its own bound makes it able to answer, and the
seam between them is visible in the output: today can be a part-day and says so, all time
cannot be and does not.

**Nothing here reads words.** The trace holds a count per utterance and no text — see
`flow/diag.py`, where the field names are an allow-list and the ones that would carry
speech are named and refused at import. This module reads integers and timestamps, and
there is nothing in the files for it to read that is not one of those.

**`--no-profile` is honoured rather than worked around.** That flag means "ignore the
stored profile and learn nothing this session": nothing is counted, nothing is written,
and `flow --stats --no-profile` reads neither file and says so. A stats flag that quietly
read the profile the same command line just said to ignore would make the flag a lie in
the one place someone would check it.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import diag, profile as profile_mod

# The two paths are read off their own modules at call time rather than bound to names
# here, and that is not style: `mock.patch.object(flow.profile, "DEFAULT_PATH", ...)` is
# how the suite has always kept a test launch out of the real `~/.flow` (Rule 5), and an
# alias captured at import would quietly stop obeying it. One seam, patched in one place,
# honoured by everything that reads either file.

#: How fast an average person types, in words a minute.
#:
#: **An assumption, and the output says so every time it is used.** Flow does not watch
#: anybody type and could not: it has no keyboard hook, it has no idea what the draft
#: would have cost to write by hand, and nothing in this repository has ever measured a
#: user's typing. 40 wpm is the figure commonly cited for average adult typing speed, and
#: it is here because a comparison somebody can check the arithmetic of is more use than
#: no comparison at all.
#:
#: It is therefore stated as a conditional — "at 40 words a minute typed, ... are about
#: N minutes of typing" — and never as "you saved N minutes". The second sentence is a
#: measurement this project has not made, and the whole reason the accuracy numbers in
#: `docs/roadmap.md` are trusted is that none of them was ever written that way.
#:
#: A fast typist should read the line as an over-estimate and a hunt-and-peck typist as
#: an under-estimate. That is what an assumption with its number on the front is for.
TYPING_WPM = 40

#: The trace record dictation is counted from — written by `Session._remember_append`,
#: which is the one seam every word that reaches the draft from speech passes through.
#: Partials never reach it (they are replaced, never appended), and neither a local edit
#: nor a CLI rewrite goes near it.
RECORD = "dictated"

#: What `--stats` says when the same command line also said not to look.
NO_PROFILE_LINE = (
    "--no-profile ignores the stored profile and writes no trace, so there is nothing "
    "to count"
)


def _span(seconds: float) -> str:
    """A duration in the unit somebody would actually say it in.

    Whole minutes up to an hour and a half, tenths of an hour past that: "458 minutes" is
    a number the reader has to convert before it means anything, and the conversion is the
    part that makes them stop trusting the line. Under a minute is named rather than
    rounded to "0 minutes", which reads as nothing having happened.
    """
    minutes = seconds / 60.0
    if seconds < 60:
        return "under a minute"
    if minutes < 90:
        whole = round(minutes)
        return "1 minute" if whole == 1 else f"{whole} minutes"
    return f"{minutes / 60.0:.1f} hours"


def _typing(words: int) -> str:
    """How long `words` would have taken to type, at the assumed rate."""
    return _span(words / TYPING_WPM * 60.0)


def _midnight(now: float) -> float:
    """The start of `now`'s day, in this machine's own timezone.

    Local rather than UTC because "today" is a thing a person says about the day they are
    having, not about a meridian. `tm_isdst=-1` hands the question of which side of a
    clock change this is back to the C library, which is the only thing that knows.
    """
    local = time.localtime(now)
    return time.mktime(
        (local.tm_year, local.tm_mon, local.tm_mday, 0, 0, 0, 0, 0, -1)
    )


@dataclass(frozen=True)
class Today:
    """What the trace still holds about the day it is being read on."""

    words: int = 0
    ms: int = 0
    #: When the countable history starts, epoch seconds, or None when it starts at or
    #: before midnight and "today" is the whole of today. See `read_today` for the two
    #: conditions that have to hold before this stays None.
    since: float | None = None
    #: Whether a trace file was found at all. False and `words == 0` are different
    #: facts — "nothing recorded" against "nothing to read" — and the output says which.
    found: bool = False
    #: Lines that could not be read as a record. Counted rather than ignored: a count
    #: that silently skipped part of its own evidence is worse than no count (P2).
    unreadable: int = 0

    @property
    def whole_day(self) -> bool:
        return self.since is None


@dataclass(frozen=True)
class Lifetime:
    """The two integers the profile carries, and whether they were really there."""

    words: int = 0
    ms: int = 0
    #: A profile file exists.
    found: bool = False
    #: ...and it loaded. A file that is there and unreadable is a third state, and it is
    #: the one worth saying out loud, because the user can act on it.
    loaded: bool = False
    #: ...and it carried a total. False on every profile written before this feature
    #: existed, which is every profile in the world on the day it ships — so the output
    #: has to be able to say "counting started when this version first ran" rather than
    #: showing somebody a lifetime of zero.
    counted: bool = False
    #: Field names the profile's own validator refused, from `Profile.faults`.
    faults: tuple[str, ...] = ()


@dataclass(frozen=True)
class Reading:
    """Both answers and the two paths they came from."""

    today: Today = field(default_factory=Today)
    life: Lifetime = field(default_factory=Lifetime)
    trace: Path = field(default_factory=lambda: diag.DEFAULT_PATH)
    profile: Path = field(default_factory=lambda: profile_mod.DEFAULT_PATH)

    @property
    def anything(self) -> bool:
        """Whether either file could be read. The exit code is built out of this."""
        return self.today.found or self.life.found


def read_today(path: Path | str | None = None, now: float | None = None) -> Today:
    """Count today's dictation out of the trace, and know when it cannot see all of it.

    Both files are read, `.1` first, because rotation happens mid-day and the older
    generation is where the morning went.

    **The honesty is in `since`.** Rotation destroys one generation, so a day the trace
    cannot see the start of must not be reported as a whole day. Two conditions decide it,
    and both have to hold before the count is qualified:

      * a `.1` exists, meaning a generation really was rotated away at some point, and
      * the oldest record still on disk is later than midnight.

    The first condition is what keeps the ordinary case ordinary. Without it a fresh
    install — whose trace starts the first time Flow ran, which is today — would qualify
    its very first count with a warning about data it never had. Nothing has been lost
    when nothing has been rotated, so nothing is claimed.

    Never raises. Every failure narrows what can be said rather than ending the command:
    a trace is a diagnostic, and one that can take `--stats` down with it has stopped
    being one.

    Every line is parsed rather than pre-filtered on the record name, and that choice has
    a price worth stating: measured 2026-08-15 on this machine, both generations full —
    2.0 MB, ~18,000 records, which is the ceiling `diag.MAX_BYTES` sets — this costs
    **67 ms**. A substring test before `json.loads` would cut most of it and would also
    walk silently past the one line most likely to be broken, the half-written last one,
    which is precisely the line P2 says to report. `flow --stats` is a one-shot and the
    Help sheet opens on a click, so 67 ms buys the honesty at a price nobody is waiting
    on; the version row beside it already costs ~55 ms at every launch.
    """
    path = Path(path) if path is not None else diag.DEFAULT_PATH
    now = time.time() if now is None else now
    start = _midnight(now)
    # `.jsonl` -> `.jsonl.1`, spelled the way `Diag._rotate_if_needed` spells it. Asked
    # of the same expression rather than hardcoded, so a rename there moves both.
    rotated = path.with_suffix(path.suffix + ".1")

    words = ms = unreadable = 0
    found = False
    oldest: float | None = None
    for file in (rotated, path):
        try:
            text = file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found = True
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                # A half-written last line is the ordinary way to get here: the trace is
                # appended to by a process that may be killed mid-write.
                #
                # Counted whatever day it came from, because a line that will not parse
                # has no timestamp to place it in one. The warning it produces is
                # therefore conservative — it may be about yesterday — and that is the
                # right way round: "the count may be low" over-warns, and silence about
                # evidence that was skipped is the failure P2 exists to prevent.
                unreadable += 1
                continue
            if not isinstance(record, dict):
                unreadable += 1
                continue
            when = record.get("t")
            if isinstance(when, (int, float)) and not isinstance(when, bool):
                if oldest is None or when < oldest:
                    oldest = when
            else:
                # A record with no usable clock cannot be placed in a day, so it is
                # counted as unreadable rather than folded into today or dropped.
                if record.get("kind") == RECORD:
                    unreadable += 1
                continue
            if record.get("kind") != RECORD or when < start:
                continue
            n, span = record.get("words"), record.get("ms")
            if isinstance(n, bool) or not isinstance(n, int) or n < 0:
                unreadable += 1
                continue
            words += n
            if isinstance(span, (int, float)) and not isinstance(span, bool) and span > 0:
                ms += int(span)

    try:
        was_rotated = rotated.exists()
    except OSError:
        was_rotated = False
    since = oldest if (was_rotated and oldest is not None and oldest > start) else None
    return Today(words=words, ms=ms, since=since, found=found, unreadable=unreadable)


def read_lifetime(path: Path | str | None = None) -> Lifetime:
    """The all-time totals, through the profile's own per-field validation.

    Read with `Profile` rather than with `json.loads` here, so the two integers are
    subject to exactly the checks every other field in that file gets — a hand-edited
    `"lots"` degrades to a stated absence instead of arriving as a string and being
    formatted into a sentence.

    `load()` is called a second time on purpose: `Profile.__init__` calls it and throws
    the answer away, and "the file is not there", "the file is there and will not load"
    and "the file loaded and has no totals yet" are three different things to tell
    somebody. It costs one re-read of a ~2 KB file on a path that runs once per command.
    """
    path = Path(path) if path is not None else profile_mod.DEFAULT_PATH
    try:
        there = path.is_file()
    except OSError:
        there = False
    if not there:
        return Lifetime()
    profile = profile_mod.Profile(path)
    loaded = profile.load()
    words, ms = profile.words_dictated, profile.dictated_ms
    return Lifetime(
        words=words,
        ms=ms,
        found=True,
        loaded=loaded,
        counted=loaded and bool(words or ms),
        faults=tuple(f for f in profile.faults if f in ("words_dictated", "dictated_ms")),
    )


def read(
    trace: Path | str | None = None,
    profile: Path | str | None = None,
    now: float | None = None,
) -> Reading:
    """Both stores, in one object, with the paths that were actually read."""
    return Reading(
        today=read_today(trace, now),
        life=read_lifetime(profile),
        trace=Path(trace) if trace is not None else diag.DEFAULT_PATH,
        profile=Path(profile) if profile is not None else profile_mod.DEFAULT_PATH,
    )


def lines(reading: Reading) -> list[str]:
    """The whole of what `--stats` prints, as plain lines.

    ASCII by construction, for the reason `__main__.say` documents: a redirected stdout
    uses the locale encoding and a legacy console code page cannot encode an en-dash, so a
    decorative character here would raise instead of printing. The only strings not
    written in this file are the two paths, which are the user's own and are named at
    startup already.

    Every branch says what it could not read rather than printing a zero for it (P2). A
    stats page that answers "0" to a question it never managed to ask is the one failure
    mode that cannot be noticed from the output.
    """
    today, life = reading.today, reading.life
    out: list[str] = []

    # Two forms of the same fact, because English needs both: one that follows "words"
    # and one that owns the count in the typing sentence. A part-day has no possessive
    # that reads as English — "since 09:14's 320 words" — so it gets a demonstrative.
    when, mine = "today", "today's"
    if not today.whole_day:
        clock = time.strftime("%H:%M", time.localtime(today.since))
        when, mine = f"since {clock}", "those"
        out.append(
            f"the trace has rotated, so it reaches back only to {clock} - what follows "
            "is since then, not since midnight"
        )
    if today.unreadable:
        one = today.unreadable == 1
        out.append(
            f"{today.unreadable} line{'' if one else 's'} of the trace could not be read, "
            f"so the count below is low by whatever was in {'it' if one else 'them'}"
        )

    if not today.found:
        out.append(f"no trace at {reading.trace}, so there is nothing to count {when}")
    elif today.words:
        out.append(f"words {when}: {today.words:,}, from {_span(today.ms / 1000)} "
                   "of speech")
    else:
        out.append(f"no dictation recorded {when}")

    if not life.found:
        out.append(f"no profile at {reading.profile}, so there is no all-time total")
    elif not life.loaded:
        out.append(f"could not read {reading.profile}, so there is no all-time total")
    elif life.faults:
        out.append(f"{reading.profile} carries an unusable {' and '.join(life.faults)}, "
                   "so there is no all-time total")
    elif not life.counted:
        # The upgrade case, and on release day it is everybody's case: the profile is
        # perfectly good and predates the two counters. Said plainly, because a lifetime
        # of zero under a healthy count for today reads as a broken feature.
        out.append("no all-time total yet - counting started when this version first ran")
    else:
        out.append(f"words all time: {life.words:,}, from {_span(life.ms / 1000)} "
                   "of speech")

    # The comparison rides on whichever count exists, and names the assumption in the
    # same breath as the number. Today first, because today is the number somebody ran
    # this to see; all time only when there is no today to talk about.
    if today.words:
        out.append(f"at {TYPING_WPM} words a minute typed, {mine} {today.words:,} words "
                   f"are about {_typing(today.words)} of typing")
    elif life.counted:
        out.append(f"at {TYPING_WPM} words a minute typed, those {life.words:,} words "
                   f"are about {_typing(life.words)} of typing")
    return out


def report(
    no_profile: bool = False,
    trace: Path | str | None = None,
    profile: Path | str | None = None,
    now: float | None = None,
) -> tuple[list[str], bool]:
    """What `flow --stats` prints, and whether it managed to count anything.

    The bool is the exit code's business, the same bargain `--check-update` strikes: a
    script wrapping this has to be able to tell "nothing dictated" from "nothing to read"
    without parsing English, so the first exits 0 and the second exits 1.
    """
    if no_profile:
        return [NO_PROFILE_LINE], False
    reading = read(trace, profile, now)
    return lines(reading), reading.anything


def today_note(trace: Path | str | None = None, now: float | None = None) -> str | None:
    """One row for the Help sheet, or None when there is nothing to put on it.

    None rather than "0 words today", because the sheet is a reference to what this
    machine can do and a zero is not one of those — the same reason `_hotkey_rows` omits
    an action that registered nothing instead of listing it at zero. The row appears the
    moment there is something to say and is gone again tomorrow morning, which is what
    makes it worth glancing at.

    Short by construction so it clears `help.MAX_NOTE` without being fitted, exactly as
    the version row beside it is; `tests/test_stats.py` keeps that true.

    Costs a full trace scan — up to 67 ms, see `read_today` — on the UI thread, once per
    open of the sheet. Not cached, and for the reason the whole sheet is not: it is
    regenerated every time so that what it says is true now rather than true when Flow
    started, and a word count is the row on it that changes fastest.
    """
    today = read_today(trace, now)
    if not today.found or not today.words:
        return None
    when = ("today" if today.whole_day
            else "since " + time.strftime("%H:%M", time.localtime(today.since)))
    return (f"Dictated {when}: {today.words:,} words - about "
            f"{_typing(today.words)} of typing at {TYPING_WPM} wpm")
