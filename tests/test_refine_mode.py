"""REFINE as a third session mode (design/compact/BUILD_BRIEF.md, item 4).

The cycle and the note, and the mode's whole arc: Send hands the draft to the
CLI's polish pass with the workspace as its system role (README), and the
shaped text comes back as a `reply` — a result to be sent on purpose, not a
rewrite applied to a draft that is already committed. Refine-as-an-action
("make this shorter" over a held draft) keeps its own delivery, and is pinned
here too because the two share one pipeline now. The panel half of the arc is
pinned in test_ui_compact.py.
"""

import unittest
from pathlib import Path
from unittest import mock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from flow import refine  # noqa: E402
from flow.session import CONVERSE, DICTATE, REFINE  # noqa: E402
from test_converse import session  # noqa: E402


class TestTheChooserForm(unittest.TestCase):
    def test_to_lands_directly(self):
        # One blind flip cannot serve "choose Converse" in a three-mode world
        # — `--converse` at launch was exactly that defect, and the mode
        # menu's radios are the other caller.
        s = session()
        self.assertEqual(s.toggle_mode(to=CONVERSE), CONVERSE)
        self.assertEqual(s.toggle_mode(to=DICTATE), DICTATE)
        self.assertEqual(s.toggle_mode(to=REFINE), REFINE)

    def test_to_the_current_mode_is_a_no_op(self):
        # The way selecting an already-ticked radio is: no events, no note.
        s = session()
        s.toggle_mode(to=REFINE)
        s.events()
        self.assertEqual(s.toggle_mode(to=REFINE), REFINE)
        self.assertEqual(s.events(), [])

    def test_the_draft_survives_all_three_modes(self):
        # toggle_mode's one promise, now for three: the words are the same
        # words either way — the thing being corrected is a prompt either way.
        s = session()
        s.draft.set("the deploy failed after the migration")
        for _ in range(3):
            s.toggle_mode()
            self.assertEqual(s.draft.text,
                             "the deploy failed after the migration")


class TestTheRefineNote(unittest.TestCase):
    def notes(self, s):
        return [e.text for e in s.events() if e.kind == "note"]

    def test_the_note_names_the_provider_and_the_workspace(self):
        # The same work converse's sentence does: who the words go to, that
        # they leave the machine, and the project they leave from — which in
        # this mode is the point, because the workspace is the system role.
        s = session(cli=refine.named("claude"), refine_cwd="~/dev/products/flow")
        s.toggle_mode(to=REFINE)
        notes = self.notes(s)
        self.assertTrue(any("refine mode" in n for n in notes), notes)
        self.assertTrue(any("claude" in n for n in notes), notes)
        self.assertTrue(any("~/dev/products/flow" in n for n in notes), notes)

    def test_the_note_says_when_there_is_no_workspace(self):
        s = session(cli=refine.named("claude"))
        s.toggle_mode(to=REFINE)
        self.assertTrue(
            any("no project behind it" in n for n in self.notes(s)))

    def test_the_note_says_when_there_is_no_cli(self):
        s = session()
        with mock.patch("flow.session.available", return_value=[]):
            s.toggle_mode(to=REFINE)
        self.assertTrue(
            any("no agent CLI on PATH" in n for n in self.notes(s)))


class TestRefineSend(unittest.TestCase):
    REFINED = "Strip every control from the pill."

    def send_in_refine(self, s, refined=REFINED):
        s.toggle_mode(to=REFINE)
        s.draft.set("make the pill not show any controls")
        with mock.patch("flow.session.refine",
                        return_value=(refined, "fake")) as call:
            result = s.send()
            s.wait_idle(timeout=5.0)
            s.pump_results()
        self.addCleanup(s.close)
        return result, call

    def test_send_returns_nothing_to_paste(self):
        # Converse's risk, one mode over: text returned here would paste a
        # prompt-to-be into whatever window happened to have focus.
        result, _call = self.send_in_refine(session())
        self.assertEqual(result, "")

    def test_the_draft_is_committed_not_rewritten(self):
        s = session()
        self.send_in_refine(s)
        # Cleared by send() and never re-set: the shaped text is a result,
        # and the raw words are already in the thread.
        self.assertEqual(s.draft.text, "")

    def test_the_workspace_is_the_clis_system_role(self):
        _result, call = self.send_in_refine(
            session(refine_cwd="~/dev/products/flow"))
        self.assertEqual(call.call_args.kwargs["cwd"], "~/dev/products/flow")

    def test_the_polish_pass_runs_over_the_draft_as_said(self):
        _result, call = self.send_in_refine(session())
        self.assertTrue(call.call_args.kwargs["polish"])
        self.assertEqual(call.call_args.args[0],
                         "make the pill not show any controls")

    def test_the_shaped_text_arrives_as_a_reply(self):
        s = session()
        self.send_in_refine(s)
        events = s.events()
        reply = next(e for e in events if e.kind == "reply")
        self.assertEqual(reply.text, self.REFINED)

    def test_refine_as_an_action_still_rewrites_the_draft(self):
        # The shipped surface's form — "make this shorter" over a held draft —
        # keeps its own delivery: applied to the draft, and never a reply.
        s = session()
        s.draft.set("a very long draft indeed")
        with mock.patch("flow.session.refine",
                        return_value=("shorter", "fake")):
            s._start_refine("make this shorter")
            s.wait_idle(timeout=5.0)
            s.pump_results()
        self.addCleanup(s.close)
        self.assertEqual(s.draft.text, "shorter")
        self.assertEqual([e for e in s.events() if e.kind == "reply"], [])

    def test_a_failed_refine_is_an_error_event(self):
        s = session()
        s.toggle_mode(to=REFINE)
        s.draft.set("make the pill not show any controls")
        with mock.patch("flow.session.refine",
                        return_value=(None, "timed out")):
            s.send()
            s.wait_idle(timeout=5.0)
            s.pump_results()
        self.addCleanup(s.close)
        errors = [e.text for e in s.events() if e.kind == "error"]
        self.assertTrue(any("timed out" in e for e in errors), errors)

    def test_an_empty_draft_refuses_with_the_modes_verb(self):
        s = session()
        s.toggle_mode(to=REFINE)
        s.send()
        self.addCleanup(s.close)
        notes = [e.text for e in s.events() if e.kind == "note"]
        self.assertTrue(any("nothing to refine" in n for n in notes), notes)


if __name__ == "__main__":
    unittest.main()
