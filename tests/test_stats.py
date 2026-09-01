"""How much has been dictated: what is counted, where it is kept, and what is printed.

Three things can go wrong here and only one of them is loud.

**The count can be wrong**, which is the quiet one. A number nobody can check is worse
than no number, and every plausible way of getting this wrong inflates it: counting a
partial counts the same sentence two or three times, counting a spoken correction counts
words the draft never gained, counting a CLI rewrite credits dictation with prose the
machine wrote. So the seam is driven through a real `Session` with a real router rather
than asserted at the arithmetic — the question is which utterances arrive there, and only
the real thing answers it.

**The count can be dishonest about its own reach.** The trace is bounded and rotates once,
so a day it cannot see the start of must not be reported as a whole day. That is the
rotation case, and it is pinned in both directions: a rotated trace says where it really
starts, and one that has never rotated does not warn about data it never lost.

**The lines can be wrong**, which is the one this file asserts to the character. `--stats`
is a one-shot whose entire output is these lines; if one is wrong there is nothing else on
screen to correct it. They are also asserted to encode on a legacy console code page, for
the reason `__main__.say` documents — the numbers here are formatted with `,` and `.` and
nothing else on purpose.

The typing comparison gets its own assertions because it is the one line in Flow that
talks about something Flow has not measured. It must read as a conditional and never as a
claim; `stats.TYPING_WPM` carries the argument.
"""

import contextlib
import io
import json
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from flow import SAMPLE_RATE  # noqa: E402
from flow import stats  # noqa: E402
from flow.audio import BLOCK  # noqa: E402
from flow.diag import FIELDS, NEVER, Diag  # noqa: E402
from flow.profile import SCHEMA, Profile  # noqa: E402
from flow.session import Session  # noqa: E402

LOUD = np.full(BLOCK, 0.2, dtype=np.float32)
QUIET = np.zeros(BLOCK, dtype=np.float32)


class ScriptedMic:
    """Hands over one utterance's worth of blocks when asked, then silence."""

    def __init__(self) -> None:
        self._blocks: list[np.ndarray] = []
        self.level_db = -60.0
        self.dropped = 0

    def utterance(self, loud: int = 20) -> None:
        self._blocks += [LOUD] * loud + [QUIET] * 16

    def start(self) -> None: ...

    def stop(self) -> None: ...

    @property
    def active(self) -> bool:
        return True

    def restart(self) -> None: ...

    def drain(self) -> list[np.ndarray]:
        out, self._blocks = self._blocks, []
        return out


class ScriptedAsr:
    """Finals from a script, and a partial on every non-final decode.

    The partial is the whole point of the fake. A transcriber that returned "" for
    partials — which is what most of the suite's fakes do — cannot show that partials are
    excluded from the count, because it never produces one to exclude.
    """

    def __init__(self, finals, partial="the meeting is on"):
        self.finals = list(finals)
        self.partial = partial
        self.partials_given = 0

    def load(self, final=None) -> None: ...

    def unload(self) -> None: ...

    loaded = True

    def text(self, audio, *, final: bool = False, hotwords: str = "") -> str:
        if not final:
            self.partials_given += 1
            return self.partial
        return self.finals.pop(0) if self.finals else ""


class Counted(unittest.TestCase):
    """A session that counts into files of this test's own, never the user's (Rule 5)."""

    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.trace = self.dir / "diag.jsonl"
        self.profile = Profile(self.dir / "profile.json")

    def run_utterances(self, finals, profile=True, **kwargs):
        """Say each of `finals`, one utterance at a time, through the real router."""
        mic, asr = ScriptedMic(), ScriptedAsr(finals)
        session = Session(
            asr=asr, mic=mic, diag=Diag(self.trace),
            profile=self.profile if profile else None, **kwargs,
        )
        session.start()
        self.addCleanup(session.close)
        for _ in finals:
            mic.utterance()
            session.wait_idle(timeout=5.0)
        return session, asr, mic

    def records(self, kind=stats.RECORD) -> list[dict]:
        if not self.trace.exists():
            return []
        out = []
        for line in self.trace.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                if kind is None or record.get("kind") == kind:
                    out.append(record)
        return out

    def counted(self) -> int:
        return sum(r["words"] for r in self.records())


class TestOnlyWhatReachedTheDraftFromSpeechIsCounted(Counted):
    """The seam, driven through the real router.

    Every wrong answer available here is an over-count, and an over-counted "words today"
    is the exact failure that would make this feature worth less than nothing: the number
    is only useful while somebody believes it.
    """

    def test_a_finished_utterance_is_counted_once_with_its_words(self):
        self.run_utterances(["Meeting on Tuesday at four."])
        self.assertEqual([r["words"] for r in self.records()], [5])

    def test_two_utterances_are_two_records_and_one_total(self):
        self.run_utterances(["Meeting on Tuesday.", "Bring the deck."])
        self.assertEqual([r["words"] for r in self.records()], [3, 3])
        self.assertEqual(self.counted(), 6)
        self.assertEqual(self.profile.words_dictated, 6)

    def test_a_partial_is_not_counted_because_it_is_replaced(self):
        # The defect this forbids inflates the number by roughly the number of times the
        # decoder was asked mid-sentence, which is once a second — so it would not read
        # as a bug, it would read as a very productive morning.
        #
        # Fed in two halves, because a partial is only asked for while speech is still in
        # progress: handing the mic a whole utterance and ticking once drains it inside a
        # single `_pump_audio`, and the gate has already closed by the time the request
        # would be made. The same shape `test_diag.py` uses to reach this path.
        mic, asr = ScriptedMic(), ScriptedAsr(["Meeting on Tuesday."])
        session = Session(asr=asr, mic=mic, diag=Diag(self.trace), profile=self.profile)
        session.start()
        self.addCleanup(session.close)
        mic._blocks += [LOUD] * 20
        session.tick()
        # Waited on directly rather than through `wait_idle`, which would sit out its
        # whole timeout here: speech is still in progress, so the session is not idle and
        # is not meant to be. The condition is what this test is about.
        deadline = time.perf_counter() + 5.0
        while not asr.partials_given and time.perf_counter() < deadline:
            time.sleep(0.005)
            session.tick()
        mic._blocks += [QUIET] * 16
        session.wait_idle(timeout=5.0)
        self.assertGreater(asr.partials_given, 0)
        self.assertEqual(session.draft.text, "Meeting on Tuesday.")
        self.assertEqual(self.counted(), 3)

    def test_a_spoken_correction_spends_words_the_draft_never_gains(self):
        # "change Tuesday to Thursday" is an instruction: five words said, none added.
        self.run_utterances(["Meeting on Tuesday.", "change Tuesday to Thursday"])
        self.assertEqual(self.profile.words_dictated, 3)

    def test_and_the_correction_really_happened(self):
        # Guards the test above from passing for the wrong reason: if the phrase had been
        # routed as dictation the count would be 8 *and* the draft would say so.
        session, _asr, _mic = self.run_utterances(
            ["Meeting on Tuesday.", "change Tuesday to Thursday"]
        )
        self.assertIn("Thursday", session.draft.text)
        self.assertNotIn("change", session.draft.text)

    def test_an_undo_does_not_take_words_back_off_the_total(self):
        # Deliberate, and the opposite way round from the risk above: the words were
        # dictated. An all-time counter that could go down is one that disagrees with the
        # trace it is printed beside, and "how much have I said" is not "what survived".
        self.run_utterances(["Meeting on Tuesday.", "undo"])
        self.assertEqual(self.profile.words_dictated, 3)

    def test_a_cli_rewrite_does_not_count_the_prose_it_returned(self):
        # A refine replaces the draft wholesale with text from the agent CLI. Nobody
        # spoke it, and counting it would credit dictation with a machine's paragraph.
        session, _asr, _mic = self.run_utterances(["Meeting on Tuesday."])
        session._refine_op = 999
        session._refine_result = (
            999, session.draft.revision,
            ("A far longer and much more elaborate meeting note, rewritten.", "codex"),
            (),
        )
        session._pump_refine()
        self.assertIn("elaborate", session.draft.text)
        self.assertEqual(self.profile.words_dictated, 3)

    def test_words_put_back_after_a_failed_rescue_are_not_counted_twice(self):
        # `_give_back` appends without going through `_remember_append`, deliberately:
        # the words were counted when they were first said, and returning them is not
        # saying them again.
        session, _asr, _mic = self.run_utterances(["Meeting on Tuesday."])
        before = self.profile.words_dictated
        session._give_back("Meeting on Tuesday.", "could not re-read that as a command")
        self.assertEqual(session.draft.text.count("Meeting"), 2)
        self.assertEqual(self.profile.words_dictated, before)

    def test_the_speech_behind_an_utterance_is_counted_with_it(self):
        # 20 blocks of speech at 1024 samples and 16 kHz is 1.28 s, plus whatever preroll
        # the gate hands back — so the assertion is a floor and a ceiling rather than an
        # equality, because the preroll is the gate's business and not this test's.
        self.run_utterances(["Meeting on Tuesday."])
        floor = 20 * BLOCK / SAMPLE_RATE * 1000
        self.assertGreaterEqual(self.records()[0]["ms"], floor)
        self.assertLess(self.records()[0]["ms"], floor * 2)
        self.assertGreaterEqual(self.profile.dictated_ms, floor)

    def test_the_totals_are_on_disk_and_not_only_in_memory(self):
        # `flow --stats` is a second process reading a file, so a total that never left
        # memory is a total it cannot see. Saved on every utterance rather than at the
        # Send that commits the learned pairs, because a session can end without one.
        session, _asr, _mic = self.run_utterances(["Meeting on Tuesday."])
        # One pump later, not inline: the frame that routes an utterance is the frame
        # that may paste it, and the save is owed by that frame and paid by the next.
        session.pump_results()
        self.assertEqual(Profile(self.dir / "profile.json").words_dictated, 3)

    def test_a_profile_that_will_not_write_is_said_once_and_not_every_utterance(self):
        # P2: nothing silent. But this fires on every utterance, so a note per failure
        # would be a bubble every few seconds burying the draft it sits under — and the
        # thing being reported has not changed between one and the next.
        with mock.patch.object(Profile, "save", return_value=False):
            session, _asr, _mic = self.run_utterances(
                ["Meeting on Tuesday.", "Bring the deck.", "And the numbers."]
            )
        said = [e.text for e in session.events() if "could not save" in e.text]
        self.assertEqual(len(said), 1)
        self.assertIn("corrections and counts are not being kept", said[0])


class TestTheTraceRecordsACountAndNeverTheWords(Counted):
    """`flow/diag.py`'s whole discipline, at the one field this feature added.

    `test_diag.py` already pushes a sentinel through every session path and reads the file
    back looking for it, which covers the new record for content. What is asserted here is
    narrower and structural: that the field allowed is a number, and that allowing it did
    not quietly widen what a record may carry.
    """

    def test_the_record_carries_a_count_a_duration_and_nothing_else(self):
        self.run_utterances(["Meeting on Tuesday at four."])
        self.assertEqual(set(self.records()[0]), {"t", "kind", "words", "ms"})

    def test_the_count_is_an_integer_rather_than_anything_that_could_be_read(self):
        self.run_utterances(["Meeting on Tuesday at four."])
        self.assertIsInstance(self.records()[0]["words"], int)

    def test_words_is_allowed_and_every_name_for_the_words_still_is_not(self):
        self.assertIn("words", FIELDS)
        self.assertEqual(FIELDS & NEVER, frozenset())
        for named in ("text", "draft", "utterance", "partial", "transcript"):
            self.assertIn(named, NEVER)

    def test_no_length_of_text_rides_along_with_it(self):
        # `chars` is allowed elsewhere and is not on this record: a word count and a
        # character count together say more about a sentence than either does alone.
        self.run_utterances(["Meeting on Tuesday at four."])
        self.assertNotIn("chars", self.records()[0])


class TestNoProfileCountsNothingAndReadsNothing(Counted):
    """The flag's promise, kept in the one place somebody would check it.

    `--no-profile` means "ignore the stored profile and learn nothing this session". A
    counter that ran anyway would be the first thing in Flow that flag does not cover, and
    a `--stats` that read the profile it was told to ignore would make it a lie.
    """

    def test_a_session_with_no_profile_and_no_trace_counts_nothing(self):
        mic, asr = ScriptedMic(), ScriptedAsr(["Meeting on Tuesday."])
        # Exactly what `main()` builds under the flag: no profile, and the default
        # `NullDiag` in place of a trace.
        session = Session(asr=asr, mic=mic, profile=None, diag=None)
        session.start()
        self.addCleanup(session.close)
        mic.utterance()
        session.wait_idle(timeout=5.0)
        self.assertEqual(session.draft.text, "Meeting on Tuesday.")
        self.assertFalse(self.trace.exists())

    def test_the_flag_refuses_to_read_the_files_it_was_told_to_ignore(self):
        printed, read = stats.report(no_profile=True, trace=self.trace,
                                     profile=self.dir / "profile.json")
        self.assertFalse(read)
        self.assertEqual(printed, [
            "--no-profile ignores the stored profile and writes no trace, so there is "
            "nothing to count"
        ])


class TestTheProfileKeepsTheLifetimeTotals(unittest.TestCase):
    """Two integers in `profile.json`, held to the same rules as every field beside them.

    The per-field validation exists because valid JSON with wrong types used to take the
    app down inside `Profile()` — or worse, load clean and detonate later. A running total
    is the field most likely to be hand-edited by somebody curious, so it gets the same
    treatment: usable as what it claims to be, or refused and named.
    """

    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "profile.json"

    def written(self, **fields) -> Profile:
        """A profile file with `fields` in it, loaded back through the real validator."""
        base = {"schema": SCHEMA, "floor_db": -96.5, "speech_db": -40.0}
        self.path.write_text(json.dumps({**base, **fields}), encoding="utf-8")
        return Profile(self.path)

    def test_a_counted_utterance_survives_a_save_and_a_reload(self):
        profile = Profile(self.path)
        profile.note_dictation(12, 6.5)
        profile.note_dictation(8, 3.5)
        self.assertTrue(profile.save())
        again = Profile(self.path)
        self.assertEqual(again.words_dictated, 20)
        self.assertEqual(again.dictated_ms, 10_000)

    def test_a_profile_written_before_this_existed_loads_with_zeros(self):
        # Every profile in the world, on the day this ships. Additive, schema stays 1.
        profile = self.written()
        self.assertEqual((profile.words_dictated, profile.dictated_ms), (0, 0))
        self.assertEqual(profile.faults, [])

    def test_the_room_is_not_disturbed_by_any_of_this(self):
        # The calibration is the expensive thing in this file and the one nobody can
        # re-create by typing. A word count must not be able to cost it.
        profile = self.written(words_dictated="lots")
        self.assertEqual(profile.floor_db, -96.5)
        self.assertEqual(profile.words_dictated, 0)

    def test_a_total_that_is_not_a_whole_number_is_refused_and_named(self):
        for bad in ("lots", 12.5, None, [3], {"a": 1}):
            with self.subTest(bad=bad):
                profile = self.written(words_dictated=bad)
                self.assertEqual(profile.words_dictated, 0)
                # `None` reads as absent everywhere in this file, so it is not a fault.
                self.assertEqual("words_dictated" in profile.faults, bad is not None)

    def test_a_negative_total_is_a_corrupt_file_rather_than_a_smaller_one(self):
        profile = self.written(words_dictated=-3, dictated_ms=-1)
        self.assertEqual((profile.words_dictated, profile.dictated_ms), (0, 0))
        self.assertEqual(sorted(profile.faults), ["dictated_ms", "words_dictated"])

    def test_true_is_not_one_word_dictated(self):
        # `bool` is a subclass of `int` in Python, so an unguarded check would read a
        # profile whose count had been overwritten with `true` as one word ever said.
        profile = self.written(words_dictated=True)
        self.assertEqual(profile.words_dictated, 0)
        self.assertIn("words_dictated", profile.faults)

    def test_a_zero_that_was_written_on_purpose_is_not_a_fault(self):
        profile = self.written(words_dictated=0, dictated_ms=0)
        self.assertEqual(profile.faults, [])

    def test_nonsense_handed_to_the_counter_moves_nothing(self):
        # The counter has no UI and nothing that can correct it, so a bad increment is
        # permanent until somebody deletes their profile.
        profile = Profile(self.path)
        for words in (0, -4, True, 2.5, "three", None):
            profile.note_dictation(words, 1.0)
        for seconds in (float("nan"), float("inf"), -2.0, "long", None):
            profile.note_dictation(1, seconds)
        self.assertEqual(profile.words_dictated, 5)
        self.assertEqual(profile.dictated_ms, 0)

    def test_an_utterance_with_no_audio_still_counts_its_words(self):
        # A replayed utterance has words behind it and no sound of its own, and its words
        # did reach the draft.
        profile = Profile(self.path)
        profile.note_dictation(6, 0.0)
        self.assertEqual((profile.words_dictated, profile.dictated_ms), (6, 0))


class Planted(unittest.TestCase):
    """Trace and profile files this test wrote, read at a moment this test chose."""

    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.trace = self.dir / "diag.jsonl"
        self.profile = self.dir / "profile.json"
        # Mid-afternoon, so "today" has room either side of it in every timezone the
        # suite might run in: nothing here may depend on the wall clock.
        self.now = stats._midnight(time.time()) + 15 * 3600

    def at(self, hours: float) -> float:
        """Epoch seconds `hours` after this test's midnight."""
        return stats._midnight(self.now) + hours * 3600

    def plant(self, records, path=None) -> None:
        path = path or self.trace
        path.write_text(
            "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8"
        )

    def said(self, when: float, words: int, ms: int = 0) -> dict:
        return {"t": when, "kind": stats.RECORD, "words": words, "ms": ms}

    def with_lifetime(self, words: int, ms: int) -> None:
        profile = Profile(self.profile)
        profile.words_dictated, profile.dictated_ms = words, ms
        profile.save()

    def lines(self) -> list[str]:
        return stats.lines(stats.read(self.trace, self.profile, self.now))


class TestTodayIsCountedOutOfTheTrace(Planted):
    """The trace is the only file here with a clock in it, so it answers "when"."""

    def test_only_what_was_said_today_is_counted(self):
        self.plant([
            self.said(self.at(-6), 500),     # yesterday evening
            self.said(self.at(9), 120),
            self.said(self.at(14), 80),
        ])
        self.assertEqual(stats.read_today(self.trace, self.now).words, 200)

    def test_both_generations_are_read_because_rotation_happens_mid_day(self):
        # The morning is in `.1` and the afternoon is in the live file. Reading only the
        # live one would silently halve every heavy user's day.
        self.plant([self.said(self.at(9), 300)], self.dir / "diag.jsonl.1")
        self.plant([self.said(self.at(14), 120)])
        self.assertEqual(stats.read_today(self.trace, self.now).words, 420)

    def test_nothing_but_a_dictation_record_is_counted(self):
        self.plant([
            {"t": self.at(9), "kind": "state", "state": "listening"},
            {"t": self.at(9), "kind": "route", "route": "append", "chars": 400},
            {"t": self.at(9), "kind": "decode", "route": "final", "ms": 900},
            self.said(self.at(10), 40),
        ])
        self.assertEqual(stats.read_today(self.trace, self.now).words, 40)

    def test_the_speech_behind_today_is_added_up_too(self):
        self.plant([self.said(self.at(9), 40, 20_000),
                    self.said(self.at(10), 60, 30_000)])
        self.assertEqual(stats.read_today(self.trace, self.now).ms, 50_000)

    def test_a_line_that_is_not_a_record_is_counted_rather_than_skipped(self):
        # A half-written last line is the ordinary way to get one: the trace is appended
        # to by a process that can be killed mid-write. Counted so the output can say the
        # total is low, which is the P2 half of this whole file.
        self.trace.write_text(
            json.dumps(self.said(self.at(9), 40)) + "\n{\"t\": 1, \n[1,2,3]\n",
            encoding="utf-8",
        )
        today = stats.read_today(self.trace, self.now)
        self.assertEqual(today.words, 40)
        self.assertEqual(today.unreadable, 2)

    def test_a_dictation_record_with_a_nonsense_count_is_named_not_added(self):
        self.plant([
            self.said(self.at(9), 40),
            {"t": self.at(10), "kind": stats.RECORD, "words": "many"},
            {"t": self.at(11), "kind": stats.RECORD, "words": -5},
            {"kind": stats.RECORD, "words": 90},   # no clock, so no day to put it in
        ])
        today = stats.read_today(self.trace, self.now)
        self.assertEqual(today.words, 40)
        self.assertEqual(today.unreadable, 3)

    def test_a_trace_that_is_not_there_is_absence_rather_than_zero(self):
        today = stats.read_today(self.dir / "nothing.jsonl", self.now)
        self.assertFalse(today.found)
        self.assertEqual(today.words, 0)

    def test_a_trace_that_is_there_and_empty_is_a_real_zero(self):
        self.plant([])
        today = stats.read_today(self.trace, self.now)
        self.assertTrue(today.found)
        self.assertEqual(today.words, 0)


class TestARotatedTraceDoesNotPretendToBeAWholeDay(Planted):
    """Rotation destroys one generation, and the output has to admit it.

    "Words today" over a trace that starts at nine o'clock is a claim about fourteen hours
    made out of five. The alternative was to say nothing, which is worse: the number is the
    product, and a number with a stated reach beats no number at all.
    """

    def test_a_day_it_cannot_see_the_start_of_is_labelled_from_where_it_can(self):
        self.plant([{"t": self.at(9.25), "kind": "state"}], self.dir / "diag.jsonl.1")
        self.plant([self.said(self.at(10), 320)])
        today = stats.read_today(self.trace, self.now)
        self.assertFalse(today.whole_day)
        self.assertEqual(today.since, self.at(9.25))

    def test_a_trace_that_never_rotated_is_a_whole_day_however_late_it_starts(self):
        # The fresh-install case, and it is everybody's first `--stats`: the trace begins
        # the first time Flow ran, which is today. Nothing was rotated away, so nothing
        # was lost, so nothing is claimed. Without this the very first run of the feature
        # would warn about data that never existed.
        self.plant([self.said(self.at(9.25), 320)])
        self.assertTrue(stats.read_today(self.trace, self.now).whole_day)

    def test_a_rotation_that_happened_yesterday_still_leaves_today_whole(self):
        # `.1` exists, but what it holds predates midnight — so the trace really can see
        # every hour of today and should say "today".
        self.plant([{"t": self.at(-8), "kind": "state"}], self.dir / "diag.jsonl.1")
        self.plant([self.said(self.at(10), 320)])
        self.assertTrue(stats.read_today(self.trace, self.now).whole_day)

    def test_the_part_day_is_named_before_a_number_is_printed(self):
        self.plant([{"t": self.at(9.25), "kind": "state"}], self.dir / "diag.jsonl.1")
        self.plant([self.said(self.at(10), 320, 120_000)])
        self.with_lifetime(18_320, 137 * 60 * 1000)
        self.assertEqual(self.lines(), [
            "the trace has rotated, so it reaches back only to 09:15 - what follows is "
            "since then, not since midnight",
            "words since 09:15: 320, from 2 minutes of speech",
            "words all time: 18,320, from 2.3 hours of speech",
            "at 40 words a minute typed, those 320 words are about 8 minutes of typing",
        ])

    def test_a_part_day_with_nothing_in_it_still_says_where_it_starts(self):
        # Not "no dictation today": the morning may well have had some, and it is gone.
        self.plant([{"t": self.at(9.25), "kind": "state"}], self.dir / "diag.jsonl.1")
        self.plant([{"t": self.at(10), "kind": "state"}])
        self.with_lifetime(18_320, 137 * 60 * 1000)
        self.assertIn("no dictation recorded since 09:15", self.lines())


class TestTheStatsFlagPrintsExactlyThis(Planted):
    """The whole output, to the character, over files this test planted.

    Asserted exactly rather than matched loosely for the reason `test_version.py` gives:
    this is a one-shot whose entire output is these lines, so "prints something about
    words" is not a behaviour anybody can rely on.
    """

    def run_flag(self, argv=("--stats",)) -> tuple[int, list[str]]:
        """`flow --stats`, reading this test's files instead of the user's `~/.flow`."""
        import flow.__main__ as mod
        import flow.diag
        import flow.profile

        out = io.StringIO()
        with mock.patch.object(flow.diag, "DEFAULT_PATH", self.trace), \
                mock.patch.object(flow.profile, "DEFAULT_PATH", self.profile), \
                mock.patch.object(stats, "time", FrozenTime(self.now)), \
                contextlib.redirect_stdout(out):
            code = mod.main(list(argv))
        return code, out.getvalue().splitlines()

    def an_ordinary_day(self) -> None:
        self.plant([self.said(self.at(9), 1_240, 9 * 60 * 1000 + 25_000)])
        self.with_lifetime(18_320, 137 * 60 * 1000)

    def test_the_three_lines_of_an_ordinary_day(self):
        self.an_ordinary_day()
        code, lines = self.run_flag()
        self.assertEqual(code, 0)
        self.assertEqual(lines, [
            "words today: 1,240, from 9 minutes of speech",
            "words all time: 18,320, from 2.3 hours of speech",
            "at 40 words a minute typed, today's 1,240 words are about 31 minutes "
            "of typing",
        ])

    def test_the_comparison_is_a_conditional_and_never_a_measurement(self):
        # The one line in Flow that talks about something Flow has not measured. "at 40
        # words a minute typed" is a premise the reader can reject; "you saved 31
        # minutes" would be a claim, and this project's accuracy numbers are worth
        # something precisely because none of them was ever written that way.
        self.an_ordinary_day()
        _code, lines = self.run_flag()
        self.assertTrue(lines[-1].startswith("at 40 words a minute typed,"))
        for claim in ("you saved", "faster than", "saved you", "x faster"):
            self.assertNotIn(claim, " ".join(lines).lower())

    def test_and_the_number_in_it_is_the_words_divided_by_the_assumption(self):
        self.an_ordinary_day()
        _code, lines = self.run_flag()
        self.assertEqual(1_240 // stats.TYPING_WPM, 31)
        self.assertIn("about 31 minutes of typing", lines[-1])

    def test_nothing_dictated_today_still_reports_the_lifetime(self):
        self.plant([self.said(self.at(-6), 900)])
        self.with_lifetime(18_320, 137 * 60 * 1000)
        code, lines = self.run_flag()
        self.assertEqual(code, 0)
        self.assertEqual(lines, [
            "no dictation recorded today",
            "words all time: 18,320, from 2.3 hours of speech",
            "at 40 words a minute typed, those 18,320 words are about 7.6 hours "
            "of typing",
        ])

    def test_a_profile_that_predates_the_counters_is_told_apart_from_a_zero(self):
        # The upgrade case, which on release day is everybody's case. A lifetime of "0"
        # under a healthy count for today reads as a broken feature.
        self.plant([self.said(self.at(9), 1_240, 9 * 60 * 1000)])
        Profile(self.profile).save()
        _code, lines = self.run_flag()
        self.assertIn(
            "no all-time total yet - counting started when this version first ran", lines
        )

    def test_a_missing_file_is_named_rather_than_printed_as_a_zero(self):
        code, lines = self.run_flag()
        self.assertEqual(code, 1)
        self.assertEqual(lines, [
            f"no trace at {self.trace}, so there is nothing to count today",
            f"no profile at {self.profile}, so there is no all-time total",
        ])

    def test_a_profile_that_will_not_load_says_so_instead_of_counting_it_as_none(self):
        self.plant([self.said(self.at(9), 40)])
        self.profile.write_text("{ this is not json", encoding="utf-8")
        _code, lines = self.run_flag()
        self.assertIn(f"could not read {self.profile}, so there is no all-time total",
                      lines)

    def test_an_unusable_total_is_named_along_with_the_field(self):
        self.plant([self.said(self.at(9), 40)])
        self.profile.write_text(
            json.dumps({"schema": SCHEMA, "words_dictated": "lots"}), encoding="utf-8"
        )
        _code, lines = self.run_flag()
        self.assertIn(
            f"{self.profile} carries an unusable words_dictated, so there is no "
            "all-time total", lines
        )

    def test_an_unreadable_line_is_named_above_the_count_it_lowered(self):
        self.trace.write_text(
            json.dumps(self.said(self.at(9), 40)) + "\nhalf a rec",
            encoding="utf-8",
        )
        self.with_lifetime(100, 60_000)
        _code, lines = self.run_flag()
        self.assertEqual(lines[0], "1 line of the trace could not be read, so the count "
                                   "below is low by whatever was in it")

    def test_the_exit_code_tells_nothing_dictated_from_nothing_to_read(self):
        # The same bargain the update check strikes: a script wrapping this must not have
        # to parse English to tell the two apart.
        self.plant([])
        Profile(self.profile).save()
        self.assertEqual(self.run_flag()[0], 0)

    def test_and_the_no_profile_combination_exits_one_with_its_reason(self):
        self.an_ordinary_day()
        code, lines = self.run_flag(("--stats", "--no-profile"))
        self.assertEqual(code, 1)
        self.assertEqual(lines, [stats.NO_PROFILE_LINE])
        self.assertNotIn("1,240", " ".join(lines))

    def test_it_exits_before_a_model_a_microphone_or_a_window(self):
        # The whole point of short-circuiting right after `parse_args`. A stats flag that
        # loaded a 141 MB model to print three lines would not be run twice.
        import flow.asr
        import flow.ui

        import flow.__main__ as mod

        self.an_ordinary_day()
        with mock.patch.object(mod, "Session") as session, \
                mock.patch.object(flow.asr, "WhisperTranscriber") as asr, \
                mock.patch.object(flow.ui, "Pill") as pill:
            code, _lines = self.run_flag()
        self.assertEqual(code, 0)
        self.assertEqual((session.call_count, asr.call_count, pill.call_count), (0, 0, 0))

    def test_and_prints_none_of_the_startup_block(self):
        # Not one line of "refine CLI", "trace:", "lexicon:" — this is a question about
        # what already happened, not a launch.
        self.an_ordinary_day()
        _code, lines = self.run_flag()
        for line in lines:
            self.assertFalse(line.startswith(("version:", "refine CLI", "trace:",
                                              "lexicon:", "mode:", "hotkey")))


class FrozenTime:
    """`time`, with `time()` pinned. Everything else is the real module.

    The seam is `flow.stats.time` rather than `time.time` globally, because half the suite
    runs threads that need a clock that moves.
    """

    def __init__(self, now: float) -> None:
        self._now = now

    def time(self) -> float:
        return self._now

    def __getattr__(self, name):
        return getattr(time, name)


class TestEveryLineSurvivesALegacyConsole(Planted):
    """`say()` prints these, and a redirected stdout uses the locale encoding.

    A cp437 console cannot encode an en-dash, so one decorative character would raise
    `UnicodeEncodeError` in place of the entire output. Every separator here is a plain
    hyphen and every number is grouped with commas for exactly that reason.

    The two file paths are the exception and are excluded knowingly: they are the user's
    own, they only appear when something is missing, and startup already prints one.
    """

    def every_line(self) -> list[str]:
        out = [stats.NO_PROFILE_LINE]
        # An ordinary day, a part day, an empty day, an upgraded profile, a broken line,
        # and the two large-number forms the span helper switches between.
        self.with_lifetime(18_320, 137 * 60 * 1000)
        for records in (
            [self.said(self.at(9), 1_240, 9 * 60 * 1000)],
            [self.said(self.at(9), 1, 30_000)],
            [self.said(self.at(9), 500_000, 900 * 60 * 1000)],
            [self.said(self.at(-6), 900)],
            [],
        ):
            self.plant(records)
            out += self.lines()
        self.plant([{"t": self.at(9.25), "kind": "state"}], self.dir / "diag.jsonl.1")
        self.plant([self.said(self.at(10), 320, 120_000)])
        out += self.lines()
        self.trace.write_text("not a record\nnor this\n", encoding="utf-8")
        out += self.lines()
        Profile(self.profile).save()
        out += self.lines()
        note = stats.today_note(self.trace, self.now)
        return out + ([note] if note else [])

    def test_every_line_the_flag_can_print_encodes_to_cp437_and_ascii(self):
        for line in self.every_line():
            with self.subTest(line=line):
                line.encode("cp437")
                line.encode("ascii")

    def test_and_every_one_of_them_is_a_single_line(self):
        for line in self.every_line():
            with self.subTest(line=line):
                self.assertNotIn("\n", line)

    def test_and_none_of_them_is_wider_than_a_console(self):
        # Not a hard rule anywhere in this project, but these are read at a prompt and a
        # wrapped sentence is a sentence somebody stops reading. The two path lines are
        # exempt because the path is the user's.
        for line in self.every_line():
            with self.subTest(line=line):
                if str(self.dir) not in line:
                    self.assertLessEqual(len(line), 105)


class TestTheHelpSheetCarriesTodaysWords(Planted):
    """The GUI half of the number, in the surface that is always reachable.

    `--stats` is the full answer and a GUI user has no prompt open to type it into — the
    same gap the version row and the welcome card were built for.
    """

    def sheet(self) -> list[tuple[str, str, str]]:
        import flow.ui as ui

        shown: list[list] = []
        pill = ui.Pill.__new__(ui.Pill)
        pill.session = mock.Mock(send_words=("goose", "enter goose"), workspace=None)
        pill.hotkeys = None
        pill.lite = True
        pill._help = mock.Mock(show=shown.append)
        with mock.patch.object(ui, "today_note",
                               lambda: stats.today_note(self.trace, self.now)):
            pill._open_commands()
        return shown[0]

    def test_the_row_sits_just_above_the_version_row_at_the_bottom(self):
        self.plant([self.said(self.at(9), 1_240, 9 * 60 * 1000)])
        rows = self.sheet()
        self.assertEqual(
            rows[-2],
            ("note", "Dictated today: 1,240 words - about 31 minutes of typing at "
                     "40 wpm", ""),
        )
        self.assertTrue(rows[-1][1].startswith("Flow "))

    def test_it_is_absent_on_a_day_with_nothing_on_it(self):
        # Rather than a row reading zero. The sheet is a reference to what this machine
        # does, and "you have dictated nothing" is not one of the things it does.
        self.plant([{"t": self.at(9), "kind": "state"}])
        rows = self.sheet()
        self.assertTrue(rows[-1][1].startswith("Flow "))
        self.assertNotIn("Dictated", " ".join(left for _k, left, _r in rows))

    def test_and_absent_when_there_is_no_trace_to_read_at_all(self):
        rows = self.sheet()
        self.assertNotIn("Dictated", " ".join(left for _k, left, _r in rows))

    def test_it_says_since_when_the_trace_cannot_see_the_whole_day(self):
        self.plant([{"t": self.at(9.25), "kind": "state"}], self.dir / "diag.jsonl.1")
        self.plant([self.said(self.at(10), 320, 120_000)])
        self.assertIn("Dictated since 09:15: 320 words", self.sheet()[-2][1])

    def test_and_it_fits_the_row_budget_at_a_years_worth_of_dictation(self):
        # The window draws one line per row and does not wrap, and this row is built in
        # `ui.py` without going through `help._fitted` — so the budget is kept by keeping
        # the string short, exactly as the version row beside it is.
        from flow.help import MAX_NOTE

        self.plant([self.said(self.at(9), 500_000, 900 * 60 * 1000)])
        self.assertLessEqual(len(self.sheet()[-2][1]), MAX_NOTE)


if __name__ == "__main__":
    unittest.main()
