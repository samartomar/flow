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

from flow import kinds, refine  # noqa: E402
from flow.session import ASK_TIMEOUT_SEC, CONVERSE, DICTATE, REFINE  # noqa: E402
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



def refine_twice(s, first, second, *, results=("one", "two")):
    """Two Refine-mode Sends with a result landing between them; the mock, so a test
    can read what each call was handed."""
    s.toggle_mode(to=REFINE)
    with mock.patch("flow.session.refine",
                    side_effect=[(r, "fake") for r in results]) as call:
        s.draft.set(first)
        s.send()
        s.wait_idle(timeout=5.0)
        s.pump_results()
        s.draft.set(second)
        s.send()
        s.wait_idle(timeout=5.0)
        s.pump_results()
    return call


class TestRefineWritesForTheWindow(unittest.TestCase):
    """flow/kinds.py, reached through the session: the window in front decides what
    kind of writing the words become."""

    def refine_in(self, app, title="", **profile):
        s = session()
        self.addCleanup(s.close)
        s.target_app, s.target_title = app, title
        if profile:
            # Only what a Refine reads, and a `save` that says it worked: `send()` owes
            # the profile a save, and this test is not about where it lands.
            s.profile = type("P", (), {"apps": {}, "kinds": {}, "name": "",
                                       "refine_kind": kinds.PROMPT,
                                       "save": lambda self: True, **profile})()
        s.toggle_mode(to=REFINE)
        s.events()
        s.draft.set("tell priya the release moves to tuesday")
        with mock.patch("flow.session.refine", return_value=("done", "fake")) as call:
            s.send()
            s.wait_idle(timeout=5.0)
            s.pump_results()
        return s, call


    def test_a_terminal_gets_the_prompt_it_always_got(self):
        _s, call = self.refine_in("WindowsTerminal.exe")
        self.assertEqual(call.call_args.kwargs["kind"], kinds.PROMPT)

    def test_no_window_at_all_is_a_prompt(self):
        # Lite and `--no-paste`: every install with no hands behaves as it did.
        _s, call = self.refine_in("")
        self.assertEqual(call.call_args.kwargs["kind"], kinds.PROMPT)


    def test_the_note_says_what_is_being_written(self):
        s, _call = self.refine_in("slack.exe", kinds={"slack.exe": kinds.MESSAGE})
        notes = [e.text for e in s.events() if e.kind == "note"]
        self.assertTrue(any(n.startswith("writing that as a chat message via")
                            for n in notes), notes)

    def test_a_prompt_keeps_the_sentence_it_always_had(self):
        s, _call = self.refine_in("WindowsTerminal.exe")
        notes = [e.text for e in s.events() if e.kind == "note"]
        self.assertTrue(any(n.startswith("shaping that into a prompt via")
                            for n in notes), notes)

    def test_the_users_own_entry_for_a_program_wins(self):
        _s, call = self.refine_in("notepad.exe", kinds={"Notepad.exe": kinds.EMAIL})
        self.assertEqual(call.call_args.kwargs["kind"], kinds.EMAIL)

    def test_a_pinned_default_overrides_the_window(self):
        _s, call = self.refine_in("OUTLOOK.EXE", refine_kind=kinds.PROMPT)
        self.assertEqual(call.call_args.kwargs["kind"], kinds.PROMPT)

    def test_an_email_is_signed_with_the_profiles_name(self):
        _s, call = self.refine_in("OUTLOOK.EXE", name="Samar")
        self.assertEqual(call.call_args.kwargs["name"], "Samar")



    def test_the_title_reaches_neither_the_cli_nor_the_notes(self):
        s, call = self.refine_in(
            "chrome.exe", "Quarterly numbers DRAFT - Gmail - Google Chrome")
        handed = repr(call.call_args)
        said = " ".join(e.text for e in s.events())
        self.assertNotIn("Quarterly", handed)
        self.assertNotIn("Quarterly", said)


class TestTheSecondHoldSaysMore(unittest.TestCase):
    """`hold the mic to say more`, which until 2026-11-22 refined the second hold on
    its own: `send()` cleared `following_up` before `_start_refine` read it, so the CLI
    was handed "and cap it at three attempts" and no idea what "it" was."""

    FIRST = "add retry logic to the upload client"
    SECOND = "and cap it at three attempts"

    def test_the_cli_gets_everything_heard_so_far(self):
        s = session()
        self.addCleanup(s.close)
        call = refine_twice(s, self.FIRST, self.SECOND)
        self.assertEqual(call.call_args_list[1].args[0],
                         f"{self.FIRST} {self.SECOND}")

    def test_the_first_hold_is_still_the_words_as_said(self):
        s = session()
        self.addCleanup(s.close)
        call = refine_twice(s, self.FIRST, self.SECOND)
        self.assertEqual(call.call_args_list[0].args[0], self.FIRST)

    def test_the_second_hold_is_the_same_kind_as_the_result_on_screen(self):
        # Clicking another app between the two holds must not turn the back half of
        # an email into a prompt.
        s = session()
        self.addCleanup(s.close)
        s.profile = type("P", (), {"apps": {}, "kinds": {"outlook.exe": kinds.EMAIL},
                                   "name": "", "refine_kind": kinds.PROMPT,
                                   "save": lambda self: True})()
        s.target_app = "OUTLOOK.EXE"
        s.toggle_mode(to=REFINE)
        with mock.patch("flow.session.refine",
                        side_effect=[("one", "fake"), ("two", "fake")]) as call:
            s.draft.set("tell priya the release moves")
            s.send()
            s.wait_idle(timeout=5.0)
            s.pump_results()
            s.target_app = "WindowsTerminal.exe"
            s.draft.set("and say sorry for the late notice")
            s.send()
            s.wait_idle(timeout=5.0)
            s.pump_results()
        self.assertEqual([c.kwargs["kind"] for c in call.call_args_list],
                         [kinds.EMAIL, kinds.EMAIL])

    def test_a_third_hold_carries_all_three(self):
        s = session()
        self.addCleanup(s.close)
        s.toggle_mode(to=REFINE)
        with mock.patch("flow.session.refine", return_value=("r", "fake")) as call:
            for words in ("one thing", "another thing", "a third thing"):
                s.draft.set(words)
                s.send()
                s.wait_idle(timeout=5.0)
                s.pump_results()
        self.assertEqual(call.call_args_list[2].args[0],
                         "one thing another thing a third thing")

    def test_once_the_result_has_been_pasted_the_next_hold_starts_again(self):
        s = session()
        self.addCleanup(s.close)
        s.toggle_mode(to=REFINE)
        with mock.patch("flow.session.refine", return_value=("shaped", "fake")) as call:
            s.draft.set(self.FIRST)
            s.send()
            s.wait_idle(timeout=5.0)
            s.pump_results()
            s.delivered("shaped")
            s.draft.set("a new thought entirely")
            s.send()
            s.wait_idle(timeout=5.0)
            s.pump_results()
        self.assertEqual(call.call_args_list[1].args[0], "a new thought entirely")

    def test_a_failed_refine_is_not_something_to_say_more_about(self):
        s = session()
        self.addCleanup(s.close)
        s.toggle_mode(to=REFINE)
        with mock.patch("flow.session.refine",
                        side_effect=[(None, "timed out"), ("ok", "fake")]) as call:
            s.draft.set(self.FIRST)
            s.send()
            s.wait_idle(timeout=5.0)
            s.pump_results()
            s.draft.set("try this instead")
            s.send()
            s.wait_idle(timeout=5.0)
            s.pump_results()
        self.assertEqual(call.call_args_list[1].args[0], "try this instead")




class TestAQuestionGetsLongerThanARewrite(unittest.TestCase):
    """Grounded questions measured 11-27 s on 2026-11-22 against a 20 s cutoff."""

    def test_ask_waits_at_least_the_floor(self):
        s = session()
        self.addCleanup(s.close)
        self.assertEqual(s.ask_timeout, ASK_TIMEOUT_SEC)
        self.assertLess(s.cli_timeout, s.ask_timeout)

    def test_a_larger_number_from_the_user_still_wins(self):
        s = session(cli_timeout=120.0)
        self.addCleanup(s.close)
        self.assertEqual(s.ask_timeout, 120.0)

    def test_a_smaller_one_cannot_put_ask_back_under_the_wall(self):
        s = session(cli_timeout=5.0)
        self.addCleanup(s.close)
        self.assertEqual(s.ask_timeout, ASK_TIMEOUT_SEC)

    def test_the_question_is_asked_with_it_and_the_rewrite_is_not(self):
        s = session(cli=refine.named("claude"))
        self.addCleanup(s.close)
        s.toggle_mode(to=CONVERSE)
        s.draft.set("where is the timeout set")
        with mock.patch("flow.session.ask", return_value=("here", "claude")) as asked:
            s.send()
            s.wait_idle(timeout=5.0)
            s.pump_results()
        self.assertEqual(asked.call_args.kwargs["timeout"], ASK_TIMEOUT_SEC)
        s.toggle_mode(to=REFINE)
        s.draft.set("make the pill smaller")
        with mock.patch("flow.session.refine", return_value=("ok", "claude")) as shaped:
            s.send()
            s.wait_idle(timeout=5.0)
            s.pump_results()
        self.assertEqual(shaped.call_args.kwargs["timeout"], s.cli_timeout)


class TestACliThatDidNotAnswerIsNamedOnce(unittest.TestCase):
    def test_the_note_says_which_and_why_and_only_the_first_time(self):
        s = session()
        self.addCleanup(s.close)

        def passed_over(*_a, **kw):
            kw["health"].failed("codex", "codex exited 1: the model is not supported")
            return "shaped", "claude"

        said = []
        both = [refine.named("codex"), refine.named("claude")]
        with mock.patch("flow.session.refine", side_effect=passed_over), \
                mock.patch("flow.session.available", return_value=both):
            s.toggle_mode(to=REFINE)
            s.events()
            for words in ("first thing to shape", "second thing to shape"):
                s.draft.set(words)
                s.send()
                s.wait_idle(timeout=5.0)
                s.pump_results()
                s.delivered("shaped")
                said.append([e.text for e in s.events()
                             if e.kind == "note" and e.text.startswith("skipping ")])
        self.assertEqual(len(said[0]), 1, said)
        # Which, where to read the rest, then why - in that order, because the strip
        # cuts a long line at its end.
        self.assertEqual(
            said[0][0],
            "skipping codex - see Flow Home, Models: exited 1: the model is not supported")
        self.assertEqual(said[1], [], "it was announced a second time")

    def test_nothing_is_said_when_nothing_is_being_passed_over(self):
        # One CLI installed, and it timed out. It is still the one that will be asked,
        # so "skipping claude" would be a sentence about something not happening.
        s = session()
        self.addCleanup(s.close)
        # Before anything asks which CLIs are here: the session remembers the answer
        # for half a minute, and the mode switch below is the first to ask.
        only_claude = mock.patch("flow.session.available",
                                 return_value=[refine.named("claude")])
        only_claude.start()
        self.addCleanup(only_claude.stop)
        s.toggle_mode(to=REFINE)
        s.events()

        def timed_out(*_a, **kw):
            kw["health"].failed("claude", "claude timed out after 20s")
            return None, "claude timed out after 20s"

        with mock.patch("flow.session.refine", side_effect=timed_out):
            s.draft.set("something to shape")
            s.send()
            s.wait_idle(timeout=5.0)
            s.pump_results()
        notes = [e.text for e in s.events() if e.kind == "note"]
        self.assertEqual([n for n in notes if n.startswith("skipping ")], [])

    def test_the_cli_named_before_a_call_is_the_one_that_will_be_asked(self):
        s = session()
        self.addCleanup(s.close)
        both = [refine.named("codex"), refine.named("claude")]
        with mock.patch("flow.session.available", return_value=both):
            self.assertEqual(s.provider, "codex")
            s.cli_health.failed("codex", "codex exited 1")
            self.assertEqual(s.provider, "claude")
            s.cli_health.answered("codex")
            self.assertEqual(s.provider, "codex")



class TestTheSurfaceDecidesWhenAResultIsGone(unittest.TestCase):
    """A result is something to say more about only while somebody can see it, and the
    session cannot see a panel. Found reviewing the second-hold fix: a hold over a
    panel closed with Esc drew a fresh heard block while the CLI was handed the old
    words in front of the new ones."""

    FIRST = "add retry logic to the upload client"

    def refined_once(self):
        s = session()
        self.addCleanup(s.close)
        s.toggle_mode(to=REFINE)
        with mock.patch("flow.session.refine", return_value=("shaped", "fake")):
            s.draft.set(self.FIRST)
            s.send()
            s.wait_idle(timeout=5.0)
            s.pump_results()
        return s

    def next_hold(self, s, words):
        with mock.patch("flow.session.refine", return_value=("again", "fake")) as call:
            s.draft.set(words)
            s.send()
            s.wait_idle(timeout=5.0)
            s.pump_results()
        return call.call_args

    def test_after_the_surface_puts_the_result_away_the_next_hold_starts_again(self):
        s = self.refined_once()
        s.end_refine()
        handed = self.next_hold(s, "a different thought entirely")
        self.assertEqual(handed.args[0], "a different thought entirely")
        self.assertNotIn(self.FIRST, handed.args[0])

    def test_and_the_next_one_uses_the_style_that_applies_there(self):
        # decisions.md 2026-11-24: the program's own style, not a reading of the window.
        s = self.refined_once()
        s.end_refine()
        s.profile = type("P", (), {"apps": {}, "kinds": {"outlook.exe": kinds.EMAIL},
                                   "name": "", "refine_kind": kinds.PROMPT,
                                   "save": lambda self: True})()
        s.target_app = "OUTLOOK.EXE"
        handed = self.next_hold(s, "tell priya it moved")
        self.assertEqual(handed.kwargs["kind"], kinds.EMAIL)

    def test_a_spoken_kind_with_no_result_to_restyle_is_dictation_again(self):
        s = self.refined_once()
        s.end_refine()
        handed = self.next_hold(s, "make it an email")
        self.assertEqual(handed.args[0], "make it an email")

    def test_a_surface_with_no_heard_block_never_extends(self):
        # The shipped surface: a second Refine that quietly carried the first one's
        # words would be a rewrite of text nobody can see.
        s = self.refined_once()
        s.refine_says_more = False
        handed = self.next_hold(s, "and cap it at three attempts")
        self.assertEqual(handed.args[0], "and cap it at three attempts")

    def test_the_session_says_what_the_cli_was_handed(self):
        # The heard block reads this, so what is on screen is what was sent.
        s = self.refined_once()
        self.assertEqual(s.refine_heard, self.FIRST)
        self.next_hold(s, "and cap it at three attempts")
        self.assertEqual(s.refine_heard,
                         f"{self.FIRST} and cap it at three attempts")


    def test_ending_it_leaves_the_follow_up_verb_alone(self):
        # `following_up` is also the shipped surface's "follow up", which is not this
        # method's to end.
        s = self.refined_once()
        self.assertTrue(s.following_up)
        s.end_refine()
        self.assertTrue(s.following_up)



class TestOnlyAResultOnScreenCanBeExtended(unittest.TestCase):
    """The independent review, 2026-11-22. The first cut read "a result is on the panel"
    off two flags that mean other things, and each case here sent an earlier dictation
    in front of words that had nothing to do with it - run on the real session."""

    FIRST = "tell priya the release moves to tuesday"

    def refined_once(self):
        s = session()
        self.addCleanup(s.close)
        s.toggle_mode(to=REFINE)
        with mock.patch("flow.session.refine", return_value=("shaped", "fake")):
            s.draft.set(self.FIRST)
            s.send()
            s.wait_idle(timeout=5.0)
            s.pump_results()
        self.assertTrue(s.can_say_more)
        return s

    def handed(self, s, words, result=("again", "fake")):
        with mock.patch("flow.session.refine", return_value=result) as call:
            s.draft.set(words)
            s.send()
            s.wait_idle(timeout=5.0)
            s.pump_results()
        return call.call_args.args[0]

    def test_a_send_that_does_not_begin_with_a_hold(self):
        # Finding 1. The panel is closed - Esc, a click outside - and the next words
        # arrive by the `send` key or the spoken trigger, which never pass through the
        # hold that used to be the only place the session was told.
        s = self.refined_once()
        s.end_refine()                       # what `CompactPill._close_panel` calls
        self.assertFalse(s.can_say_more)
        self.assertEqual(self.handed(s, "write a migration for the users table"),
                         "write a migration for the users table")

    def test_a_trip_through_another_mode(self):
        s = self.refined_once()
        s.toggle_mode(to=DICTATE)
        s.toggle_mode(to=REFINE)
        self.assertFalse(s.can_say_more)
        self.assertEqual(self.handed(s, "a different thought"), "a different thought")

    def test_a_new_conversation(self):
        s = self.refined_once()
        s.new_conversation()
        self.assertFalse(s.can_say_more)

    def test_a_failed_second_hold_then_a_recalled_prompt(self):
        # Finding 2, case A: `_recall` arms `following_up`, and the record of the first
        # result was still there, so the two old conditions were both true again.
        s = self.refined_once()
        self.handed(s, "and cap it", result=(None, "timed out"))
        self.assertFalse(s.can_say_more)
        s.following_up = True                # what "bring back my last prompt" sets
        self.assertFalse(s.can_say_more)
        self.assertEqual(self.handed(s, "something else entirely"),
                         "something else entirely")

    def test_a_rewrite_applied_to_a_draft_is_not_a_result_on_a_panel(self):
        # Finding 2, case B: "make it a proper prompt" over a held draft sets the same
        # record a reply does, and "follow up" had armed the other flag.
        s = session()
        self.addCleanup(s.close)
        s.following_up = True
        s.draft.set("also add tests")
        with mock.patch("flow.session.refine", return_value=("POLISHED", "fake")):
            s._start_refine("make it a proper prompt", polish=True)
            s.wait_idle(timeout=5.0)
            s.pump_results()
        self.assertEqual(s.draft.text, "POLISHED")
        s.toggle_mode(to=REFINE)
        self.assertFalse(s.can_say_more)
        self.assertEqual(self.handed(s, "POLISHED"), "POLISHED")

    def test_the_flag_follows_the_result_through_its_whole_life(self):
        s = self.refined_once()                              # delivered as a reply
        self.handed(s, "and thank her")                      # extended: still there
        self.assertTrue(s.can_say_more)
        s.delivered("again")                                 # pasted
        self.assertFalse(s.can_say_more)

    def test_a_surface_with_no_heard_block_is_never_told_it_can(self):
        s = self.refined_once()
        s.refine_says_more = False
        self.assertFalse(s.can_say_more)




class TestTheSelectedStyleIsWhatIsWritten(unittest.TestCase):
    """decisions.md 2026-11-24: the selected style everywhere, a program's own where it
    has one, and the style's own instructions when it is yours or edited."""

    def refine_with(self, app, styles=(), **profile):
        s = session()
        self.addCleanup(s.close)
        # After the session: building one registers its own profile's styles.
        kinds.register(list(styles))
        self.addCleanup(kinds.register, [])
        s.target_app = app
        fields = {"apps": {}, "kinds": {}, "name": "", "refine_kind": kinds.PROMPT,
                  "style_used": {}, "save": lambda self: True}
        fields.update(profile)
        s.profile = type("P", (), fields)()
        s.toggle_mode(to=REFINE)
        with mock.patch("flow.session.refine", return_value=("shaped", "fake")) as call:
            s.draft.set("tell priya the release moves to tuesday")
            s.send()
            s.wait_idle(timeout=5.0)
            s.pump_results()
        return s, call

    def test_a_mail_program_gets_the_selected_style_not_a_guess(self):
        _s, call = self.refine_with("OUTLOOK.EXE")
        self.assertEqual(call.call_args.kwargs["kind"], kinds.PROMPT)
        self.assertIsNone(call.call_args.kwargs["instructions"])

    def test_your_own_style_sends_its_instructions_and_is_marked_used(self):
        key = "my:standup"
        s, call = self.refine_with(
            "slack.exe", styles=[{"key": key, "name": "Standup"}], refine_kind=key,
            style_instructions=lambda self, k: "Three bullets." if k == key else None)
        self.assertEqual(call.call_args.kwargs["kind"], key)
        self.assertEqual(call.call_args.kwargs["instructions"], "Three bullets.")
        self.assertIn(key, s.profile.style_used)

if __name__ == "__main__":
    unittest.main()
