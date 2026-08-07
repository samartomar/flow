"""P9 — keeping what the conversation was worth, and the document it becomes.

Converse mode answers questions, and the answers were gone on quit. Two verbs close
that: one files an exchange, one turns everything filed into a file.

The tests that carry the risk are not the happy path. They are the three edges where
this feature could quietly cost somebody something they had: that a note verb does not
swallow ordinary dictation (which is why the payload shape is gated on an empty draft),
that a failed write keeps the notes rather than eating them, and that nothing here
writes a file unless a human said so twice — because the standing stance is that the
words are never stored, and this is the one deliberate exception to it.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling helpers

from flow.audio import BLOCK  # noqa: E402
from flow.edits import plan  # noqa: E402
from flow.notes import (  # noqa: E402
    MAX_NOTE_CHARS,
    NOTES_DIR,
    Notes,
    render,
    write,
)
from flow.session import CONVERSE, Session  # noqa: E402

LOUD = np.full(BLOCK, 0.2, dtype=np.float32)

#: A fixed wall clock, so a heading is asserted rather than described. 14:07 on
#: 2026-08-05, local time — built through `mktime` so the test reads the same clock the
#: renderer does and does not fail in another timezone.
import time as _time  # noqa: E402

WHEN = _time.mktime((2026, 8, 5, 14, 7, 0, 0, 0, -1))


class FakeMic:
    def __init__(self) -> None:
        self._blocks: list[np.ndarray] = []
        self.level_db = -60.0

    def start(self) -> None: ...

    def stop(self) -> None: ...

    @property
    def active(self) -> bool:
        return True

    def restart(self) -> None: ...

    def drain(self) -> list[np.ndarray]:
        out, self._blocks = self._blocks, []
        return out


class FakeAsr:
    def load(self, final=None) -> None: ...

    def text(self, audio, *, final=False, hotwords="") -> str:
        return "" if not final else "keep note"


def session(**kw) -> Session:
    return Session(asr=FakeAsr(), mic=FakeMic(), **kw)


def answered(s: Session, question: str, answer: str) -> None:
    """Drive a real ask through the session so the reply and its question are set."""
    s.draft.set(question)
    with mock.patch("flow.session.ask", return_value=(answer, "codex")):
        s.send()
        s.wait_idle(timeout=5.0)


def notes_of(s: Session) -> list[str]:
    return [e.text for e in s.events() if e.kind == "note"]


class TestStore(unittest.TestCase):
    def test_notes_are_kept_in_order(self):
        n = Notes()
        n.add("first")
        n.add("second")
        self.assertEqual([x.text for x in n.all], ["first", "second"])

    def test_blank_is_not_a_note(self):
        n = Notes()
        self.assertEqual(n.add("   "), 0)
        self.assertEqual(len(n), 0)

    def test_the_question_and_the_workspace_ride_with_it(self):
        n = Notes()
        n.add("Use ALTER TABLE.", question="how do I widen a column", workspace="flow")
        note = n.all[0]
        self.assertEqual(note.question, "how do I widen a column")
        self.assertEqual(note.workspace, "flow")

    def test_the_count_ceiling_drops_the_oldest_and_says_how_many(self):
        # P2's rule extended to notes: a kept note may be lost to a ceiling, it may not
        # be lost silently. `add` returning the count is what lets the session say so.
        n = Notes(max_notes=3)
        for i in range(3):
            self.assertEqual(n.add(f"note {i}"), 0)
        self.assertEqual(n.add("note 3"), 1)
        self.assertEqual([x.text for x in n.all], ["note 1", "note 2", "note 3"])

    def test_the_character_ceiling_never_trims_to_nothing(self):
        # One oversized note is the only note somebody kept. It survives.
        n = Notes(max_chars=10)
        n.add("x" * 500)
        self.assertEqual(len(n), 1)

    def test_an_enormous_note_is_cut_at_the_head_and_marked(self):
        n = Notes()
        n.add("A" * (MAX_NOTE_CHARS + 5_000) + "TAIL")
        kept = n.all[0].text
        self.assertEqual(len(kept), MAX_NOTE_CHARS)
        self.assertTrue(kept.startswith("AAA"))
        self.assertTrue(kept.endswith("…"))
        self.assertNotIn("TAIL", kept)

    def test_clear_empties_it(self):
        n = Notes()
        n.add("something")
        n.clear()
        self.assertEqual(len(n), 0)


class TestRender(unittest.TestCase):
    def _doc(self, **kw) -> str:
        n = Notes()
        n.add("Use ALTER TABLE.", question="how do I widen a column",
              workspace="flow", at=WHEN)
        return render(n.all, now=WHEN, **kw)

    def test_the_question_becomes_the_heading(self):
        doc = self._doc(workspace="flow")
        self.assertIn("## 14:07 — how do I widen a column", doc)
        self.assertIn("Use ALTER TABLE.", doc)

    def test_the_workspace_titles_it(self):
        self.assertIn("# Flow notes — flow", self._doc(workspace="flow"))

    def test_no_workspace_still_renders(self):
        self.assertIn("# Flow notes", self._doc())

    def test_a_dictated_note_has_no_question_in_its_heading(self):
        n = Notes()
        n.add("ship it behind a flag", at=WHEN)
        doc = render(n.all, now=WHEN)
        self.assertIn("## 14:07", doc)
        self.assertNotIn("—", doc.split("## 14:07")[1])

    def test_one_note_is_not_pluralised(self):
        self.assertIn("1 note\n", self._doc(workspace="flow"))

    def test_a_note_from_another_project_is_tagged_and_the_rest_are_not(self):
        # The tag exists for the session that switched projects mid-way. On the common
        # case — one project — printing it on every heading would repeat the title.
        n = Notes()
        n.add("from here", workspace="flow", at=WHEN)
        n.add("from elsewhere", workspace="acme", at=WHEN)
        doc = render(n.all, workspace="flow", now=WHEN)
        self.assertIn("· in acme", doc)
        self.assertNotIn("· in flow", doc)

    def test_a_single_project_gets_no_tags_at_all(self):
        n = Notes()
        n.add("from here", workspace="flow", at=WHEN)
        self.assertNotIn("· in", render(n.all, workspace="flow", now=WHEN))


class TestWrite(unittest.TestCase):
    def test_it_lands_in_a_named_folder_under_the_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write("# notes\n", tmp, now=WHEN)
            self.assertEqual(path.parent.name, NOTES_DIR)
            self.assertEqual(path.name, "2026-08-05-1407.md")
            self.assertEqual(path.read_text(encoding="utf-8"), "# notes\n")

    def test_two_wrap_ups_in_one_minute_do_not_overwrite(self):
        # "wrap up", read it, keep one more, "wrap up" again — inside sixty seconds is
        # ordinary, and losing the first file to it would destroy notes at exactly the
        # moment this feature exists to save them.
        with tempfile.TemporaryDirectory() as tmp:
            first = write("first\n", tmp, now=WHEN)
            second = write("second\n", tmp, now=WHEN)
            self.assertNotEqual(first, second)
            self.assertEqual(first.read_text(encoding="utf-8"), "first\n")
            self.assertEqual(second.name, "2026-08-05-1407-2.md")


class TestGrammar(unittest.TestCase):
    DRAFT = "Meeting on Tuesday with Sameer about the release notes."

    def test_the_bare_verbs_route_to_note(self):
        for u in ("keep note", "make a note", "take a note", "note that",
                  "note this down", "write that down", "save that",
                  "please keep a note"):
            self.assertEqual(plan(u, "").kind, "note", u)

    def test_the_bare_verbs_work_with_a_draft_held_too(self):
        # The bare form keeps the *exchange*, never the draft, so it is unambiguous in
        # both states — which is what makes it the shape the feature leans on.
        self.assertEqual(plan("keep note", self.DRAFT).kind, "note")

    def test_the_payload_form_fires_with_an_empty_draft(self):
        p = plan("note that we should use Postgres 15", "")
        self.assertEqual(p.kind, "note")
        self.assertEqual(p.payload, "we should use Postgres 15")

    def test_the_payload_form_is_dictation_while_a_draft_is_held(self):
        # The risk the gate exists for: someone mid-prompt says "note that the API is
        # deprecated" meaning it as part of the prompt. Those words belong in the draft.
        p = plan("note that the API is deprecated", self.DRAFT)
        self.assertEqual(p.kind, "append")

    def test_the_decoders_mis_hearing_of_the_noun_still_keeps(self):
        # Measured, not imagined: "keep note" comes back "Keep node" through the real
        # microphone path, and `scripts/selfdrive.py --only notes` failed on exactly this
        # the first time it ran. A verb the router handles and the decoder never delivers
        # is a feature nobody has.
        self.assertEqual(plan("Keep node", "").kind, "note")
        self.assertEqual(plan("make a node", "").kind, "note")
        self.assertEqual(plan("node that the release ships Tuesday", "").kind, "note")

    def test_but_the_mis_hearing_never_swallows_a_sentence_about_nodes(self):
        # The corpus cannot price these — EdAcc has the word "node" zero times in 580
        # utterances — so they are written down instead, here and in
        # `command_bench.ADVERSARIAL_EMPTY`. The first was a live defect: admitting the
        # mis-hearing after "keep" filed a note reading "three drained".
        for u in ("keep node three drained until the upgrade finishes",
                  "keep nodes warm for the rollout",
                  "node the server is down again",
                  "the node is down and the pod will not reschedule",
                  "node modules are huge and nobody prunes them"):
            self.assertEqual(plan(u, "").kind, "append", u)

    def test_a_bare_note_needs_a_frame_before_it_takes_a_payload(self):
        # "note taking is not the same as listening" was swallowed by a bare `note X`,
        # found by the empty-draft adversarial set. A weak verb is safe only when
        # something else confirms it — this module's oldest rule, applied to a new verb.
        self.assertEqual(plan("note taking is not the same as listening", "").kind,
                         "append")
        self.assertEqual(plan("note the build is red", "").kind, "append")
        self.assertEqual(plan("note that the build is red", "").kind, "note")

    def test_taking_the_answer_still_beats_the_shared_verb(self):
        for u in ("keep that answer", "take that answer", "use that answer"):
            self.assertEqual(plan(u, "").kind, "take", u)

    def test_the_wrap_verbs_route_to_wrap(self):
        for u in ("wrap up", "wrap it up", "give me my notes", "show me the notes",
                  "write up the notes", "notes please", "save the notes"):
            self.assertEqual(plan(u, "").kind, "wrap", u)

    def test_the_hyphen_the_decoder_adds_still_wraps_up(self):
        # Said on its own, "wrap up" comes back "Wrap-up" — 4 times in 6 through the real
        # microphone path, because a two-word phrase with nothing around it is where
        # Whisper reaches for the compound noun. A space-only pattern missed it two runs
        # in three, which showed up as a selfdrive check that passed three runs and
        # failed the fourth.
        for u in ("Wrap-up", "wrap-up", "write-up the notes"):
            self.assertEqual(plan(u, "").kind, "wrap", u)

    def test_remember_is_not_a_note_verb(self):
        # Pinned because it was measured, not because it was disliked. `remember that X`
        # was written, priced on the 580 real EdAcc utterances by
        # `scripts/command_bench.py`, and hit one — real speech that would have been
        # swallowed. Anyone re-adding it has to move this test, and the comment in
        # `flow/edits.py` tells them what it will cost.
        self.assertEqual(plan("remember that the deploy is on Tuesday", "").kind,
                         "append")

    def test_prose_that_merely_contains_the_verbs_is_dictation(self):
        for u in ("let's wrap up the sprint and move on",
                  "the release notes are in the wiki",
                  "boom goes the dynamite"):
            self.assertIn(plan(u, self.DRAFT).kind, ("append", "local"), u)


class TestKeeping(unittest.TestCase):
    def test_keeping_with_nothing_to_keep_refuses_out_loud(self):
        s = session()
        self.assertFalse(s.keep_note())
        self.assertTrue(any("nothing to keep" in n for n in notes_of(s)))

    def test_the_bare_verb_keeps_the_answer_with_its_question(self):
        s = session()
        s.toggle_mode()
        answered(s, "how do I widen a column", "Use ALTER TABLE.")
        self.assertTrue(s.keep_note())
        note = s.notes.all[0]
        self.assertEqual(note.text, "Use ALTER TABLE.")
        self.assertEqual(note.question, "how do I widen a column")

    def test_a_dictated_note_stands_on_its_own(self):
        s = session()
        s.keep_note("ship it behind a flag")
        note = s.notes.all[0]
        self.assertEqual(note.text, "ship it behind a flag")
        self.assertEqual(note.question, "")

    def test_the_workspace_is_stamped_at_capture_time(self):
        # Not at write time. A session that switches projects must not relabel notes it
        # already took as belonging to wherever the speaker ended up.
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            s = session(refine_cwd=one)
            s.keep_note("from the first project")
            s.set_workspace(two)
            s.keep_note("from the second")
            self.assertEqual([n.workspace for n in s.notes.all],
                             [Path(one).name, Path(two).name])

    def test_keeping_says_how_many_are_held(self):
        s = session()
        s.keep_note("one")
        s.keep_note("two")
        self.assertTrue(any("2 notes" in n for n in notes_of(s)))

    def test_a_dropped_note_is_announced(self):
        s = session()
        s.notes = Notes(max_notes=1)
        s.keep_note("first")
        s.keep_note("second")
        self.assertTrue(any("fell off" in n for n in notes_of(s)))

    def test_the_spoken_verb_reaches_the_session(self):
        # End to end through the router, which is the only path a user has.
        s = session()
        s.toggle_mode()
        answered(s, "how do I widen a column", "Use ALTER TABLE.")
        s._route("keep note")
        self.assertEqual(len(s.notes), 1)


class TestWrapUp(unittest.TestCase):
    def test_wrapping_with_nothing_kept_refuses_out_loud(self):
        s = session()
        self.assertFalse(s.wrap_up())
        self.assertTrue(any("nothing kept" in n for n in notes_of(s)))

    def test_it_writes_the_file_into_the_workspace_and_names_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = session(refine_cwd=tmp)
            s.keep_note("ship it behind a flag")
            self.assertTrue(s.wrap_up())
            files = list((Path(tmp) / NOTES_DIR).glob("*.md"))
            self.assertEqual(len(files), 1)
            self.assertIn("ship it behind a flag",
                          files[0].read_text(encoding="utf-8"))
            self.assertTrue(any(str(files[0]) in n for n in notes_of(s)))

    def test_the_document_reaches_the_card_through_the_reply(self):
        # No new surface: the conversation card already draws a reply and already
        # carries Copy and Use this, so the notes are copyable the moment they exist.
        with tempfile.TemporaryDirectory() as tmp:
            s = session(refine_cwd=tmp)
            s.keep_note("ship it behind a flag")
            s.wrap_up()
            replies = [e.text for e in s.events() if e.kind == "reply"]
            self.assertEqual(len(replies), 1)
            self.assertIn("ship it behind a flag", replies[0])
            self.assertIn("ship it behind a flag", s.reply)

    def test_it_clears_the_buffer_on_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = session(refine_cwd=tmp)
            s.keep_note("one")
            s.wrap_up()
            self.assertEqual(len(s.notes), 0)

    def test_no_workspace_writes_no_file_but_still_shows_the_notes(self):
        s = session()
        s.keep_note("ship it behind a flag")
        self.assertTrue(s.wrap_up())
        self.assertIn("ship it behind a flag", s.reply)
        self.assertTrue(any("no workspace set" in n for n in notes_of(s)))

    def test_a_failed_write_keeps_the_notes(self):
        # A full disk costs a retry, never the notes. This is the edge that decides
        # whether the buffer may be cleared before or after the write.
        with tempfile.TemporaryDirectory() as tmp:
            s = session(refine_cwd=tmp)
            s.keep_note("ship it behind a flag")
            with mock.patch("flow.session.write_notes",
                            side_effect=OSError("disk full")):
                self.assertFalse(s.wrap_up())
            self.assertEqual(len(s.notes), 1)
            self.assertTrue(any("could not write" in e.text
                                for e in s.events() if e.kind == "error"))

    def test_the_spoken_verb_reaches_the_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = session(refine_cwd=tmp)
            s.keep_note("ship it behind a flag")
            s._route("wrap up")
            self.assertEqual(len(list((Path(tmp) / NOTES_DIR).glob("*.md"))), 1)


class TestTheMenuIsTheFloor(unittest.TestCase):
    """The spoken verbs need a tap under them, because the decoder mis-hears.

    That is the argument `TAKE_VERBS` already makes about the "Use this" chip, and it
    applies harder here: this product is for speakers whose commands the decoder loses,
    so a feature reachable only by voice is one they can be locked out of.
    """

    def menu(self, **kw):
        from test_menu import Menu as MenuFixture

        fixture = MenuFixture("run")
        fixture.setUp()
        return fixture.build(fixture.profile(), **kw)

    def test_keeping_is_one_tap_when_there_is_an_answer(self):
        self.assertIn("Keep this answer", self.menu().commands)

    def test_and_absent_when_there_is_not(self):
        # A row that lies about having something behind it is worse than no row.
        self.assertNotIn("Keep this answer",
                         self.menu(can_take_reply=False).commands)

    def test_wrapping_up_appears_only_with_notes_and_counts_them(self):
        held = Notes()
        held.add("one")
        held.add("two")
        self.assertIn("Wrap up (2 notes)", self.menu(notes=held).commands)

    def test_one_note_is_not_pluralised_there_either(self):
        held = Notes()
        held.add("only one")
        self.assertIn("Wrap up (1 note)", self.menu(notes=held).commands)

    def test_no_notes_means_no_row(self):
        labels = self.menu(notes=Notes()).commands
        self.assertEqual([k for k in labels if k.startswith("Wrap up")], [])


class TestTheStanceHolds(unittest.TestCase):
    def test_nothing_is_written_without_the_second_deliberate_act(self):
        # The whole legitimacy argument in one test. decisions.md 2026-08-03 part 3 says
        # the words are never stored and that the next shape would be *opt-in, never a
        # default*. Keeping notes is one act; writing them is a second. A session that
        # takes a dozen notes and is never told to wrap up must leave the disk alone.
        with tempfile.TemporaryDirectory() as tmp:
            s = session(refine_cwd=tmp)
            before = sorted(p.name for p in Path(tmp).iterdir())
            for i in range(12):
                s.keep_note(f"a secret sentence number {i}")
            s.close()
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), before)

    def test_the_settings_folder_is_never_where_notes_go(self):
        # Item 65's invariant, re-asserted against the one feature built since that
        # could plausibly have broken it. Notes go to the user's project, never to
        # Flow's own folder.
        from flow.diag import Diag
        from flow.profile import Profile

        with tempfile.TemporaryDirectory() as settings, \
                tempfile.TemporaryDirectory() as work:
            folder = Path(settings)
            s = session(refine_cwd=work, profile=Profile(folder / "profile.json"),
                        diag=Diag(folder / "diag.jsonl"))
            s.keep_note("a secret sentence nobody may store")
            s.wrap_up()
            s.close()
            left = sorted(p.name for p in folder.iterdir())
            self.assertEqual([n for n in left
                              if n not in ("profile.json", "diag.jsonl")], [])
            blob = "".join(p.read_text(encoding="utf-8", errors="replace")
                           for p in folder.iterdir() if p.is_file())
        self.assertNotIn("a secret sentence", blob)


if __name__ == "__main__":
    unittest.main()
