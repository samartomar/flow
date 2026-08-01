"""P9 — converse mode: Send asks the agent CLI instead of the focused window.

No CLI subprocess is spawned here. `flow.session.ask` is replaced, because what needs
proving is the routing: that a question never reaches the clipboard, that a failed
answer costs the user nothing, and that the second question inherits the first.
"""

import sys
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.audio import BLOCK  # noqa: E402
from flow.session import AUTO_ASK_SEC, CONVERSE, DICTATE, Session, State  # noqa: E402

LOUD = np.full(BLOCK, 0.2, dtype=np.float32)


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
        return "" if not final else "how do I widen a column"


class FakeSpeaker:
    """Models the real contract, `speaking` included.

    That flag is not decoration: the microphone is gated on it, so a fake without it
    tests a session that can still hear itself — which is the defect these tests exist
    to pin.
    """

    def __init__(self) -> None:
        self.said = []
        self.stops = 0
        self.speaking = False

    def say(self, text: str) -> bool:
        self.said.append(text)
        self.speaking = True
        return True

    def stop(self) -> None:
        self.stops += 1
        self.speaking = False


def session(**kw) -> Session:
    return Session(asr=FakeAsr(), mic=FakeMic(), **kw)


class TestModeSwitch(unittest.TestCase):
    def test_it_starts_in_dictate(self):
        self.assertEqual(session().mode, DICTATE)

    def test_one_action_switches_and_switches_back(self):
        s = session()
        self.assertEqual(s.toggle_mode(), CONVERSE)
        self.assertEqual(s.toggle_mode(), DICTATE)

    def test_switching_keeps_the_draft(self):
        # Someone who has dictated three sentences and then decides to ask about them
        # should not have to say it again — the words are the same words either way.
        s = session()
        s.draft.set("the deploy failed after the migration")
        s.toggle_mode()
        self.assertEqual(s.draft.text, "the deploy failed after the migration")

    def test_the_switch_is_announced(self):
        s = session()
        s.toggle_mode()
        kinds = {e.kind: e.text for e in s.events()}
        self.assertEqual(kinds.get("mode"), CONVERSE)
        self.assertIn("converse", kinds.get("note", ""))


class TestSendRouting(unittest.TestCase):
    def test_dictate_send_returns_the_text_to_paste(self):
        s = session()
        s.draft.set("ship it on Friday")
        self.assertEqual(s.send(), "ship it on Friday")

    def test_converse_send_returns_nothing_to_paste(self):
        # The whole risk of this feature: a question pasted into whatever window
        # happened to have focus. send() must hand the caller nothing.
        s = session()
        s.toggle_mode()
        s.draft.set("how do I widen a column")
        with mock.patch("flow.session.ask", return_value=("ALTER TABLE.", "fake")):
            self.assertEqual(s.send(), "")

    def test_an_empty_draft_does_not_ask(self):
        s = session()
        s.toggle_mode()
        with mock.patch("flow.session.ask") as spy:
            s.draft.set("   ")
            s.send()
        spy.assert_not_called()


class TestAnswers(unittest.TestCase):
    def _ask(self, s, question, result):
        s.draft.set(question)
        with mock.patch("flow.session.ask", return_value=result) as spy:
            s.send()
            s.wait_idle(timeout=5.0)
        return spy

    def test_the_answer_is_emitted_and_kept(self):
        s = session()
        s.toggle_mode()
        self._ask(s, "how do I widen a column", ("Use ALTER TABLE.", "codex"))
        self.assertEqual(s.reply, "Use ALTER TABLE.")
        self.assertIn("Use ALTER TABLE.",
                      [e.text for e in s.events() if e.kind == "reply"])

    def test_the_next_question_inherits_the_last_exchange(self):
        s = session()
        s.toggle_mode()
        self._ask(s, "how do I widen a column", ("Use ALTER TABLE.", "codex"))
        spy = self._ask(s, "and to rename it?", ("Use RENAME COLUMN.", "codex"))
        context = spy.call_args.kwargs["context"]
        self.assertIn("how do I widen a column", context)
        self.assertIn("(reply) Use ALTER TABLE.", context)

    def test_the_current_question_is_not_in_its_own_context(self):
        # It is already in the thread by the time the ask starts; passing it as
        # background asks the CLI not to answer the thing it was just asked.
        s = session()
        s.toggle_mode()
        spy = self._ask(s, "how do I widen a column", ("Use ALTER TABLE.", "codex"))
        self.assertNotIn("how do I widen a column",
                         spy.call_args.kwargs["context"])

    def test_a_failure_is_non_destructive_and_visible(self):
        s = session()
        s.toggle_mode()
        self._ask(s, "how do I widen a column", (None, "codex timed out after 20s"))
        self.assertEqual(s.reply, "")
        self.assertTrue(any(e.kind == "error" for e in s.events()))
        self.assertIs(s.state, State.IDLE)

    def test_the_question_survives_a_failure_in_the_thread(self):
        s = session()
        s.toggle_mode()
        self._ask(s, "how do I widen a column", (None, "no agent CLI found on PATH"))
        self.assertIn("how do I widen a column", s.thread.turns)


class TestSpokenReplies(unittest.TestCase):
    def test_the_answer_is_spoken_when_a_speaker_is_attached(self):
        sp = FakeSpeaker()
        s = session(speaker=sp)
        s.toggle_mode()
        s.draft.set("how do I widen a column")
        with mock.patch("flow.session.ask", return_value=("Use ALTER TABLE.", "codex")):
            s.send()
            s.wait_idle(timeout=5.0)
        self.assertEqual(sp.said, ["Use ALTER TABLE."])

    def test_nothing_is_spoken_when_the_ask_failed(self):
        sp = FakeSpeaker()
        s = session(speaker=sp)
        s.toggle_mode()
        s.draft.set("how do I widen a column")
        with mock.patch("flow.session.ask", return_value=(None, "timed out")):
            s.send()
            s.wait_idle(timeout=5.0)
        self.assertEqual(sp.said, [])

    def test_a_session_without_a_speaker_stays_silent_and_does_not_crash(self):
        s = session()
        s.toggle_mode()
        s.draft.set("how do I widen a column")
        with mock.patch("flow.session.ask", return_value=("Use ALTER TABLE.", "codex")):
            s.send()
            s.wait_idle(timeout=5.0)
        self.assertEqual(s.reply, "Use ALTER TABLE.")


class TestFlowDoesNotHearItself(unittest.TestCase):
    """The defect the first live converse session produced.

    The reply "Yes, we can hear you." played out of the speakers, the microphone heard
    it, the gate opened on Flow's own voice, `speaker.stop()` cut the answer off
    mid-sentence, and the fragment decoded to "Yes." and was appended to the draft. The
    next question carried a word the user never said.

    There is no echo cancellation here and there is not going to be one (R16), so the
    guarantee is half-duplex: while Flow is talking, the microphone is not evidence.
    """

    def test_the_microphone_is_ignored_while_a_reply_plays(self):
        sp = FakeSpeaker()
        s = session(speaker=sp)
        s.start()
        sp.say("Yes, we can hear you.")  # the engine is now producing sound
        for _ in range(30):
            s.mic._blocks.append(LOUD)
        s.tick()
        self.assertFalse(s.gate.speaking, "the gate opened on Flow's own voice")
        self.assertEqual(s.draft.text, "", "Flow transcribed itself into the draft")
        self.assertGreater(s.echo_blocks, 0, "the guard did not run at all")

    def test_a_reply_is_not_cut_off_by_its_own_sound(self):
        sp = FakeSpeaker()
        s = session(speaker=sp)
        s.start()
        sp.say("Yes, we can hear you.")
        for _ in range(30):
            s.mic._blocks.append(LOUD)
        s.tick()
        self.assertEqual(sp.stops, 0, "the answer stopped itself")
        self.assertTrue(sp.speaking, "the answer was cut short")

    def test_the_microphone_reopens_once_the_reply_ends(self):
        sp = FakeSpeaker()
        s = session(speaker=sp)
        s.start()
        sp.say("Yes, we can hear you.")
        for _ in range(6):
            s.mic._blocks.append(LOUD)
        s.tick()
        sp.speaking = False  # the engine went back to Ready
        for _ in range(6):
            s.mic._blocks.append(LOUD)
        s.tick()
        self.assertTrue(s.gate.speaking, "the mic never came back after the reply")

    def test_stopping_speech_is_an_explicit_action(self):
        # Acoustic barge-in is gone by design, so the deliberate stops have to work.
        sp = FakeSpeaker()
        s = session(speaker=sp)
        sp.say("a long answer")
        self.assertTrue(s.stop_speaking())
        self.assertEqual(sp.stops, 1)
        self.assertFalse(s.stop_speaking(), "reported stopping nothing")

    def test_pausing_stops_a_reply(self):
        sp = FakeSpeaker()
        s = session(speaker=sp)
        s.start()
        sp.say("a long answer")
        s.pause()
        self.assertFalse(sp.speaking)


class TestTheAnswerArrivesEvenIfNobodyIsListening(unittest.TestCase):
    """A question already with the CLI does not depend on still capturing.

    `_pump_ask` used to run only inside `tick()`, and the UI only ticks while armed —
    so disarming while waiting stranded the answer on `_ask_result` for good. Disarming
    mid-wait is the natural thing to do, and more so now that Flow goes deaf while it
    reads a reply aloud.
    """

    def test_pump_results_delivers_a_reply_with_no_audio_pump(self):
        s = session()
        s.toggle_mode()
        s.draft.set("how do I widen a column")
        with mock.patch("flow.session.ask", return_value=("Use ALTER TABLE.", "codex")):
            s.send()
            for _ in range(200):
                s.pump_results()  # never tick(); the mic is not being read at all
                if s.reply:
                    break
                time.sleep(0.01)
        self.assertEqual(s.reply, "Use ALTER TABLE.")
        self.assertIn("reply", [e.kind for e in s.events()])

    def test_asking_survives_the_user_talking(self):
        # Speaking while a question is out used to overwrite ASKING with LISTENING, so
        # the violet "still thinking" state vanished exactly when it was wanted.
        s = session()
        s.start()
        s.toggle_mode()
        s.draft.set("how do I widen a column")
        with mock.patch("flow.session.ask", return_value=("Use ALTER TABLE.", "codex")):
            s.send()
            self.assertIs(s.state, State.ASKING)
            for _ in range(6):
                s.mic._blocks.append(LOUD)
            s._pump_audio()
            self.assertIs(s.state, State.ASKING)


class TestSendSaysWhenItRefuses(unittest.TestCase):
    """A button that does nothing when pressed reads as broken, and was reported as
    exactly that. Every refusal is now spoken aloud in the note line."""

    def _notes(self, s) -> str:
        return " | ".join(e.text for e in s.events() if e.kind == "note")

    def test_an_empty_draft_says_so(self):
        s = session()
        s.events()
        self.assertEqual(s.send(), "")
        self.assertIn("nothing to send", self._notes(s))

    def test_a_second_ask_while_one_is_in_flight_says_so(self):
        s = session()
        s.toggle_mode()
        s.draft.set("first question")
        with mock.patch("flow.session.ask", return_value=("answer", "codex")):
            s.send()
            self.assertIs(s.state, State.ASKING)
            s.events()
            s.draft.set("second question")
            self.assertEqual(s.send(), "")
            self.assertIn("still waiting", self._notes(s))
        self.assertEqual(s.draft.text, "second question", "the draft was eaten")


class TestCorrectionLoopStillApplies(unittest.TestCase):
    """P9's acceptance: the P3 correction loop works on the outgoing prompt in both
    modes. Nothing before Send is mode-dependent, and this pins that."""

    def test_an_edit_shapes_the_question_before_it_is_asked(self):
        s = session()
        s.toggle_mode()
        s.draft.set("how do I widen a column in postgres")
        s._route("change postgres to MySQL")
        self.assertIn("MySQL", s.draft.text)
        with mock.patch("flow.session.ask", return_value=("ALTER TABLE.", "x")) as spy:
            s.send()
            s.wait_idle(timeout=5.0)
        self.assertIn("MySQL", spy.call_args.args[0])


if __name__ == "__main__":
    unittest.main()


class TestSpeechIsARuntimeChoice(unittest.TestCase):
    """Speech used to be a launch flag while the mode it serves is a runtime toggle.

    Anyone who found converse mode with ctrl+alt+M mid-session had no way to turn the
    voice on, which is exactly what happened the first time someone used it.
    """

    def _answer(self, s):
        s.draft.set("how do I widen a column")
        with mock.patch("flow.session.ask", return_value=("Use ALTER TABLE.", "codex")):
            s.send()
            s.wait_idle(timeout=5.0)

    def test_a_session_starts_unmuted(self):
        self.assertFalse(session().muted)

    def test_muting_silences_the_next_reply(self):
        sp = FakeSpeaker()
        s = session(speaker=sp)
        s.toggle_mode()
        self.assertFalse(s.toggle_speech())
        self._answer(s)
        self.assertEqual(sp.said, [])

    def test_unmuting_restores_it(self):
        sp = FakeSpeaker()
        s = session(speaker=sp)
        s.toggle_mode()
        s.toggle_speech()
        self.assertTrue(s.toggle_speech())
        self._answer(s)
        self.assertEqual(sp.said, ["Use ALTER TABLE."])

    def test_muting_cuts_off_whatever_is_speaking(self):
        sp = FakeSpeaker()
        s = session(speaker=sp)
        s.toggle_speech()
        self.assertEqual(sp.stops, 1)

    def test_a_muted_reply_is_still_shown(self):
        # Muting silences the voice, it does not discard the answer.
        sp = FakeSpeaker()
        s = session(speaker=sp)
        s.toggle_mode()
        s.toggle_speech()
        self._answer(s)
        self.assertEqual(s.reply, "Use ALTER TABLE.")


class TestAutoAsk(unittest.TestCase):
    """P9: converse mode is a conversation, so a settled draft goes on its own.

    product.md states the acceptance as "speak, the reply appears, speak again" — no
    button in that sentence — while R5 says a draft is never auto-sent. The
    reconciliation is that R5 protects the *irreversible* act: pasting into a focused
    window stays manual forever, asking a question does not. So this is converse-only,
    it is visible the whole time it is counting, and anything the user does resets it.
    """

    def _armed(self, **kw):
        s = session(**kw)
        s.toggle_mode()
        s.draft.set("can you hear me")
        s._after_draft_change()
        s.events()
        return s

    def _fire(self, s):
        """Wind the clock past the delay rather than sleeping through it."""
        s._settled_at -= AUTO_ASK_SEC + 0.1
        s._pump_auto_ask()

    def test_a_settled_draft_is_asked_without_a_press(self):
        s = self._armed()
        with mock.patch("flow.session.ask", return_value=("yes", "codex")) as ask:
            self._fire(s)
            self.assertIs(s.state, State.ASKING)
        self.assertEqual(ask.call_args.args[0], "can you hear me")

    def test_dictate_mode_never_sends_itself(self):
        # R5 in full force: this one pastes into whatever has focus.
        s = self._armed()
        s.toggle_mode()
        self.assertEqual(s.mode, DICTATE)
        self._fire(s)
        self.assertEqual(s.draft.text, "can you hear me")

    def test_it_does_not_fire_while_the_user_is_speaking(self):
        s = self._armed()
        s.gate.speaking = True
        self._fire(s)
        self.assertEqual(s.draft.text, "can you hear me")

    def test_it_does_not_fire_while_a_reply_is_playing(self):
        # The mic is gated then, so silence says nothing about the user.
        sp = FakeSpeaker()
        s = self._armed(speaker=sp)
        sp.say("still talking")
        self._fire(s)
        self.assertEqual(s.draft.text, "can you hear me")

    def test_a_correction_restarts_the_countdown(self):
        s = self._armed()
        s._settled_at -= AUTO_ASK_SEC - 0.5  # nearly out of time
        s._route("change hear to see")
        self.assertGreater(s.auto_ask_in, AUTO_ASK_SEC - 0.5,
                           "editing the draft did not buy any time back")

    def test_reaching_for_a_chip_holds_it(self):
        s = self._armed()
        s._settled_at -= AUTO_ASK_SEC - 0.2
        s.hold_auto_ask()
        self.assertGreater(s.auto_ask_in, AUTO_ASK_SEC - 0.5)

    def test_the_countdown_is_readable_the_whole_time(self):
        # A silent timer that sends the user's words is the thing this must never be.
        s = self._armed()
        self.assertIsNotNone(s.auto_ask_in)
        self.assertLessEqual(s.auto_ask_in, AUTO_ASK_SEC)
        s.auto_ask = False
        self.assertIsNone(s.auto_ask_in, "nothing should count down when it is off")

    def test_turning_it_off_stops_it_firing(self):
        s = self._armed()
        s.auto_ask = False
        self._fire(s)
        self.assertEqual(s.draft.text, "can you hear me")

    def test_an_emptied_draft_is_not_counting(self):
        s = self._armed()
        s.draft.set("")
        s._after_draft_change()
        self.assertIsNone(s.auto_ask_in)

    def test_it_is_not_armed_after_the_question_has_gone(self):
        s = self._armed()
        with mock.patch("flow.session.ask", return_value=("yes", "codex")):
            s.send()
            self.assertIsNone(s.auto_ask_in)


class TestTheProviderIsNamedBeforeTheFact(unittest.TestCase):
    """The notes said which CLI answered; nothing said which one was about to.

    Naming it afterwards is a receipt, not a warning. The moment that matters is the
    one where somebody switches into converse mode or presses Ask, because that is when
    the question leaves the machine — and "the CLI" told them neither which service
    that is nor that it is a service at all.
    """

    def notes(self, s) -> str:
        return " | ".join(e.text for e in s.events() if e.kind == "note")

    def found(self, name: str):
        # A real Cli, because `name` is a reserved word in Mock's constructor and a
        # Mock built with it reports its own repr instead — which the first version of
        # this test asserted against and passed nothing useful.
        from flow.refine import Cli

        return [Cli(name, (name,))]

    def test_switching_to_converse_names_the_cli_and_says_it_leaves(self):
        s = session()
        with mock.patch("flow.session.available", return_value=self.found("codex")):
            s.toggle_mode()
        note = self.notes(s)
        self.assertIn("codex", note)
        self.assertIn("leaves this machine", note)

    def test_dictate_mode_makes_no_such_claim(self):
        # Nothing leaves the machine in dictate mode, so nothing should say it does.
        s = session()
        s.toggle_mode()
        s.events()
        s.toggle_mode()
        self.assertNotIn("leaves this machine", self.notes(s))

    def test_an_absent_cli_is_said_plainly_rather_than_named(self):
        s = session()
        with mock.patch("flow.session.available", return_value=[]):
            s.toggle_mode()
        note = self.notes(s)
        self.assertIn("no agent CLI", note)
        self.assertNotIn("leaves this machine", note, "it cannot leave via nothing")

    def test_a_rewrite_names_who_is_about_to_do_it(self):
        s = session()
        s.draft.set("widen the column")
        with mock.patch("flow.session.available", return_value=self.found("claude")), \
             mock.patch("flow.session.refine", return_value=("x", "claude")):
            s._start_refine("make it formal")
            s.wait_idle(timeout=5.0)
        self.assertIn("refining via claude", self.notes(s))

    def test_a_question_names_who_is_about_to_answer_it(self):
        s = session()
        with mock.patch("flow.session.available", return_value=self.found("codex")), \
             mock.patch("flow.session.ask", return_value=("yes", "codex")):
            s._start_ask("can you hear me")
            s.wait_idle(timeout=5.0)
        self.assertIn("asking codex", self.notes(s))


class TestTheReplyCanBecomeTheDraft(unittest.TestCase):
    """P9 promised the verb and the loop dead-ended without it.

    The owner's workshop loop is discuss in converse, refine, then send the good version
    to the terminal — and `send()` hands over the *draft*, while the refined prompt is in
    the *reply*. P9's own scenario promises the connection ("turn that last answer into a
    code comment" and paste it); nothing built it, so the answer could only be re-typed.

    Replace, never append: an answer is a whole thing, and gluing it onto a half-written
    question makes a third thing nobody asked for. Undo is what makes that safe.
    """

    def notes(self, s) -> str:
        return " | ".join(e.text for e in s.events() if e.kind == "note")

    def answered(self, text: str = "Write a migration that adds last_seen_at.", **kw):
        s = session(**kw)
        s.toggle_mode()
        s.draft.set("how do I add a column")
        with mock.patch("flow.session.ask", return_value=(text, "codex")):
            s.send()
            s.wait_idle(timeout=5.0)
        self.assertEqual(s.reply, text)
        s.events()
        return s

    def test_taking_it_into_an_empty_draft_is_verbatim(self):
        s = self.answered()
        self.assertEqual(s.draft.text, "")
        self.assertTrue(s.take_reply())
        self.assertEqual(s.draft.text, "Write a migration that adds last_seen_at.")

    def test_and_the_revision_moved_so_undo_holds_the_empty_state(self):
        s = self.answered()
        was = s.draft.revision
        s.take_reply()
        self.assertGreater(s.draft.revision, was)
        s.draft.undo()
        self.assertEqual(s.draft.text, "")

    def test_a_non_empty_draft_is_replaced_and_the_note_says_what_went(self):
        s = self.answered()
        s.draft.set("some half-written question")
        s.events()
        s.take_reply()
        self.assertEqual(s.draft.text, "Write a migration that adds last_seen_at.")
        self.assertIn("replaced", self.notes(s))
        s.draft.undo()
        self.assertEqual(s.draft.text, "some half-written question")

    def test_taking_it_flips_to_dictate_and_says_send_now_pastes(self):
        # Staying in converse would make the next Send re-ask Flow's own answer back at
        # the CLI, which is the exact confusion this verb exists to remove.
        s = self.answered()
        self.assertEqual(s.mode, CONVERSE)
        s.take_reply()
        self.assertEqual(s.mode, DICTATE)
        self.assertIn("paste", self.notes(s).lower())

    def test_it_does_not_arm_the_auto_ask_countdown(self):
        # A taken draft is not a settled utterance. Without this the trap is converse
        # auto-asking the owner's own answer straight back at the CLI. Item 17's editor
        # held the countdown; this removes what it counts from, which is the stronger
        # guard of the two — there is no clock to run down rather than a clock on hold.
        s = self.answered()
        s.take_reply()
        self.assertIsNone(s.auto_ask_in, "the countdown armed on a taken reply")
        # Even back in converse, and even after the pause has elapsed: nothing settled
        # this draft, so there is nothing counting.
        s.mode = CONVERSE
        with mock.patch("flow.session.ask", return_value=("no", "codex")) as asked:
            for _ in range(5):
                s.tick()
            self.assertIsNone(s.auto_ask_in)
            asked.assert_not_called()
        s.close()

    def test_but_speaking_afterwards_settles_it_the_ordinary_way(self):
        # The guard is "a taken reply is not an utterance", not "this draft is frozen".
        # Once the user says something in converse, the countdown is theirs again.
        s = self.answered()
        s.take_reply()
        s.mode = CONVERSE
        s._route("and mention the rollback plan")
        self.assertIsNotNone(s.auto_ask_in, "speech no longer settles the draft")
        s.close()

    def test_taking_it_stops_the_reply_being_read_aloud(self):
        # Reaching for the text is "I have what I need".
        sp = FakeSpeaker()
        s = self.answered(speaker=sp)
        self.assertTrue(sp.speaking)
        s.take_reply()
        self.assertFalse(sp.speaking)

    def test_with_no_reply_there_is_nothing_to_take(self):
        s = session()
        self.assertFalse(s.take_reply())
        self.assertEqual(s.draft.text, "")
        self.assertIn("no answer", self.notes(s))

    def test_a_twelve_thousand_character_artifact_is_taken_whole(self):
        # ASK_ARTIFACT_MAX_CHARS is 12 000 and taking one as the draft is legitimate —
        # the artifact *was* the deliverable. refine.MAX_CHARS still applies if the
        # owner then rewrites it, and the existing tail note already says so.
        big = "x" * 12_000
        s = self.answered(big)
        s.take_reply()
        self.assertEqual(len(s.draft.text), 12_000)
