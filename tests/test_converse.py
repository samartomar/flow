"""P9 — converse mode: Send asks the agent CLI instead of the focused window.

No CLI subprocess is spawned here. `flow.session.ask` is replaced, because what needs
proving is the routing: that a question never reaches the clipboard, that a failed
answer costs the user nothing, and that the second question inherits the first.
"""

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.audio import BLOCK  # noqa: E402
from flow.help import AUTO_ASK_OFF_LABEL  # noqa: E402
from flow.profile import Profile  # noqa: E402
from flow.session import (  # noqa: E402
    AUTO_ASK_SEC,
    CONVERSE,
    DICTATE,
    REFINE,
    Session,
    State,
)

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

    def test_one_action_cycles_through_all_three(self):
        # Type → Refine → Ask, wrapping (design/compact/README.md).
        s = session()
        self.assertEqual(s.toggle_mode(), REFINE)
        self.assertEqual(s.toggle_mode(), CONVERSE)
        self.assertEqual(s.toggle_mode(), DICTATE)

    def test_switching_keeps_the_draft(self):
        # Someone who has dictated three sentences and then decides to ask about them
        # should not have to say it again — the words are the same words either way.
        s = session()
        s.draft.set("the deploy failed after the migration")
        s.toggle_mode(to=CONVERSE)
        self.assertEqual(s.draft.text, "the deploy failed after the migration")

    def test_the_switch_is_announced(self):
        s = session()
        s.toggle_mode(to=CONVERSE)
        events = s.events()
        self.assertEqual(next(e.text for e in events if e.kind == "mode"), CONVERSE)
        # Every note, not the last one: the first entry carries a second line now
        # (item 64), and a check reading `{kind: text}` would silently follow it.
        notes = [e.text for e in events if e.kind == "note"]
        self.assertTrue(any("converse" in n for n in notes), notes)


class TestSendRouting(unittest.TestCase):
    def test_dictate_send_returns_the_text_to_paste(self):
        s = session()
        s.draft.set("ship it on Friday")
        self.assertEqual(s.send(), "ship it on Friday")

    def test_converse_send_returns_nothing_to_paste(self):
        # The whole risk of this feature: a question pasted into whatever window
        # happened to have focus. send() must hand the caller nothing.
        s = session()
        s.toggle_mode(to=CONVERSE)
        s.draft.set("how do I widen a column")
        with mock.patch("flow.session.ask", return_value=("ALTER TABLE.", "fake")):
            self.assertEqual(s.send(), "")

    def test_an_empty_draft_does_not_ask(self):
        s = session()
        s.toggle_mode(to=CONVERSE)
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
        s.toggle_mode(to=CONVERSE)
        self._ask(s, "how do I widen a column", ("Use ALTER TABLE.", "codex"))
        self.assertEqual(s.reply, "Use ALTER TABLE.")
        self.assertIn("Use ALTER TABLE.",
                      [e.text for e in s.events() if e.kind == "reply"])

    def test_the_next_question_inherits_the_last_exchange(self):
        s = session()
        s.toggle_mode(to=CONVERSE)
        self._ask(s, "how do I widen a column", ("Use ALTER TABLE.", "codex"))
        spy = self._ask(s, "and to rename it?", ("Use RENAME COLUMN.", "codex"))
        context = spy.call_args.kwargs["context"]
        self.assertIn("how do I widen a column", context)
        self.assertIn("(reply) Use ALTER TABLE.", context)

    def test_the_current_question_is_not_in_its_own_context(self):
        # It is already in the thread by the time the ask starts; passing it as
        # background asks the CLI not to answer the thing it was just asked.
        s = session()
        s.toggle_mode(to=CONVERSE)
        spy = self._ask(s, "how do I widen a column", ("Use ALTER TABLE.", "codex"))
        self.assertNotIn("how do I widen a column",
                         spy.call_args.kwargs["context"])

    def test_a_failure_is_non_destructive_and_visible(self):
        s = session()
        s.toggle_mode(to=CONVERSE)
        self._ask(s, "how do I widen a column", (None, "codex timed out after 20s"))
        self.assertEqual(s.reply, "")
        self.assertTrue(any(e.kind == "error" for e in s.events()))
        self.assertIs(s.state, State.IDLE)

    def test_the_question_survives_a_failure_in_the_thread(self):
        s = session()
        s.toggle_mode(to=CONVERSE)
        self._ask(s, "how do I widen a column", (None, "no agent CLI found on PATH"))
        self.assertIn("how do I widen a column", s.thread.turns)


class TestNewConversationIsOneAct(unittest.TestCase):
    """Root 4's other half: "clear prompt did not start fresh".

    `Clear draft` cleared the draft and left the thread, the reply and the mode alive,
    so starting again was three separate actions and one of them did not exist anywhere.
    """

    def asked(self):
        s = session()
        s.toggle_mode(to=CONVERSE)
        s.draft.set("how do I widen a column")
        with mock.patch("flow.session.ask", return_value=("Use ALTER TABLE.", "codex")):
            s.send()
            s.wait_idle(timeout=5.0)
        return s

    def test_the_thread_and_the_reply_go_together(self):
        s = self.asked()
        self.assertTrue(s.thread.turns)
        self.assertEqual(s.reply, "Use ALTER TABLE.")
        s.new_conversation()
        self.assertEqual(s.thread.turns, [])
        self.assertEqual(s.reply, "")

    def test_the_card_is_told(self):
        # The surface half. An event rather than the chip reaching into the window, so a
        # conversation cleared any other way still clears what is on screen.
        s = self.asked()
        s.events()
        s.new_conversation()
        kinds = [e.kind for e in s.events()]
        self.assertIn("conversation", kinds)

    def test_and_it_says_so(self):
        s = self.asked()
        s.events()
        s.new_conversation()
        said = " | ".join(e.text for e in s.events() if e.kind == "note")
        self.assertIn("new conversation", said)

    def test_the_draft_survives(self):
        # `toggle_mode`'s argument reused: words already spoken belong to the speaker,
        # and somebody saying "new conversation" mid-sentence has not asked to lose the
        # sentence. Clear draft is still the thing that clears a draft.
        s = self.asked()
        s.draft.set("half of the next question")
        s.new_conversation()
        self.assertEqual(s.draft.text, "half of the next question")

    def test_an_answer_in_flight_lands_nowhere(self):
        # It belongs to a conversation that no longer exists. `_pump_ask` drops a result
        # whose op has moved, and clearing the op is what moves it.
        s = session()
        s.toggle_mode(to=CONVERSE)
        s.draft.set("a question")
        with mock.patch("flow.session.ask", return_value=("late answer", "codex")):
            s.send()
            s.new_conversation()
            s.wait_idle(timeout=5.0)
        self.assertEqual(s.reply, "")
        self.assertEqual(s.thread.turns, [])

    def test_the_mode_is_not_changed_by_it(self):
        # It is a new conversation, not a way out of converse mode.
        s = self.asked()
        s.new_conversation()
        self.assertEqual(s.mode, CONVERSE)


class TestTheFirstConverseEntrySaysAPauseSends(unittest.TestCase):
    """Decision part 4. Auto-ask stays ON, and the price is that it is said out loud.

    The reopen bar on that default is one stranger reporting a surprise send — a report
    only somebody who was never told can make. It printed to a console before this,
    which is a surface no GUI user has open.
    """

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = Path(d.name)

    def profile(self):
        return Profile(self.dir / "profile.json")

    def entered(self, profile=None):
        s = session(profile=profile)
        s.toggle_mode(to=CONVERSE)
        return " | ".join(e.text for e in s.events() if e.kind == "note")

    def test_the_first_entry_names_the_pause_and_the_setting(self):
        said = self.entered(self.profile())
        self.assertIn(f"{AUTO_ASK_SEC:.0f}s", said)
        self.assertIn(AUTO_ASK_OFF_LABEL, said)
        self.assertIn("Settings", said)

    def test_and_the_second_entry_does_not(self):
        p = self.profile()
        self.entered(p)
        self.assertNotIn(AUTO_ASK_OFF_LABEL, self.entered(p))

    def test_it_survives_a_reload_so_a_new_launch_is_still_quiet(self):
        p = self.profile()
        self.entered(p)
        self.assertNotIn(AUTO_ASK_OFF_LABEL, self.entered(Profile(p.path)))

    def test_an_older_profile_is_told_once(self):
        # Absent means "has not been told", the opposite way round from `auto_ask`: an
        # upgrade is the first time this warning has existed at all.
        p = self.profile()
        p.path.write_text('{"schema": 1}', encoding="utf-8")
        self.assertTrue(Profile(p.path).converse_seen is False)
        self.assertIn(AUTO_ASK_OFF_LABEL, self.entered(Profile(p.path)))

    def test_no_profile_is_told_every_time_rather_than_never(self):
        # `--no-profile` has nothing to remember it in, and a warning a user never
        # receives is worse than one they receive twice.
        self.assertIn(AUTO_ASK_OFF_LABEL, self.entered(None))
        self.assertIn(AUTO_ASK_OFF_LABEL, self.entered(None))

    def test_the_label_is_the_menu_s_own_and_not_a_restatement(self):
        # A notice naming a control that has since been reworded points at nothing, and
        # costs the reader a hunt through a menu for a line that is not there.
        import flow.ui as ui

        self.assertIs(ui.AUTO_ASK_OFF_LABEL, AUTO_ASK_OFF_LABEL)

    def test_going_back_to_dictate_says_nothing_about_it(self):
        p = self.profile()
        s = session(profile=p)
        s.toggle_mode(to=CONVERSE)
        s.events()
        s.toggle_mode(to=DICTATE)
        said = " | ".join(e.text for e in s.events() if e.kind == "note")
        self.assertNotIn(AUTO_ASK_OFF_LABEL, said)


class TestTheThreadStoresTheCleanedAnswer(unittest.TestCase):
    """Item 61's uncovered half: what the *next* question inherits.

    Everything above mocks `flow.session.ask`, so the cleaning never runs — and the
    decision's root 2 is specifically that CLI chrome was "stored into the thread as
    context for the next answer". This one goes through the real `ask` and the real
    `_clean`, with only the subprocess faked, so a cleaner that stopped being applied on
    the way to the thread would fail here and nowhere else.

    kiro-cli because it is the one entry with measured furniture (codex's stdout carries
    none — see `_FURNITURE`). `cli=` is explicit so `_invoke_any` goes straight to the
    faked `_invoke` and no PATH lookup is involved.
    """

    FURNITURE = "\x1b[m> \x1b[0mUse ALTER TABLE.\x1b[0m\x1b[0m\nThen reindex."
    ANSWER = "Use ALTER TABLE.\nThen reindex."

    def asked(self):
        from flow import refine

        s = session(cli=refine.named("kiro-cli"))
        s.toggle_mode(to=CONVERSE)
        s.draft.set("how do I widen a column")
        with mock.patch("flow.refine._invoke", return_value=(self.FURNITURE, "")):
            s.send()
            s.wait_idle(timeout=5.0)
        self.addCleanup(s.close)
        return s

    def test_the_bubble_gets_the_answer_alone(self):
        s = self.asked()
        self.assertEqual(s.reply, self.ANSWER)
        self.assertIn(self.ANSWER, [e.text for e in s.events() if e.kind == "reply"])

    def test_and_so_does_the_thread(self):
        s = self.asked()
        self.assertEqual(s.thread.turns[-1], f"(reply) {self.ANSWER}")
        self.assertNotIn("\x1b", s.thread.turns[-1])

    def test_which_is_what_the_next_question_carries(self):
        # The end of the chain, and the one the decision names: chrome in the thread is
        # chrome in the next prompt, forever.
        s = self.asked()
        seen: list[str] = []

        def spy(cli, prompt, **kw):
            seen.append(prompt)
            return "fine", ""

        s.draft.set("and to rename it")
        with mock.patch("flow.refine._invoke", spy):
            s.send()
            s.wait_idle(timeout=5.0)
        self.assertTrue(seen)
        self.assertIn(f"(reply) {self.ANSWER}", seen[0])
        self.assertNotIn("\x1b", seen[0])


class TestSpokenReplies(unittest.TestCase):
    def test_the_answer_is_spoken_when_a_speaker_is_attached(self):
        sp = FakeSpeaker()
        s = session(speaker=sp)
        s.toggle_mode(to=CONVERSE)
        s.draft.set("how do I widen a column")
        with mock.patch("flow.session.ask", return_value=("Use ALTER TABLE.", "codex")):
            s.send()
            s.wait_idle(timeout=5.0)
        self.assertEqual(sp.said, ["Use ALTER TABLE."])

    def test_nothing_is_spoken_when_the_ask_failed(self):
        sp = FakeSpeaker()
        s = session(speaker=sp)
        s.toggle_mode(to=CONVERSE)
        s.draft.set("how do I widen a column")
        with mock.patch("flow.session.ask", return_value=(None, "timed out")):
            s.send()
            s.wait_idle(timeout=5.0)
        self.assertEqual(sp.said, [])

    def test_a_session_without_a_speaker_stays_silent_and_does_not_crash(self):
        s = session()
        s.toggle_mode(to=CONVERSE)
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
        s.toggle_mode(to=CONVERSE)
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
        s.toggle_mode(to=CONVERSE)
        s.draft.set("how do I widen a column")
        with mock.patch("flow.session.ask", return_value=("Use ALTER TABLE.", "codex")):
            s.send()
            self.assertIs(s.state, State.ASKING)
            for _ in range(6):
                s.mic._blocks.append(LOUD)
            s._pump_audio()
            self.assertIs(s.state, State.ASKING)


class TestTheCliIsToldTheConversationTheCardIsShowing(unittest.TestCase):
    """Item 74. Converse inherited `refine`'s 1 500-character context budget, which was
    sized for a different job: a rewrite needs just enough thread to know what "the other
    endpoint" refers to. A conversation *is* its context, and P9's card renders every
    turn of it — so the number was quietly deciding how much of a visible conversation
    the CLI could remember, and replies count against it too and are the longer half.

    Measured on the owner's own session: five turns on the card, three of the four prior
    ones sent. The CLI answered "I only have this conversation, which started with a
    question about a step-by-step plan" — accurate about what it was handed, and read as
    amnesia inside one session.
    """

    def notes(self, s) -> str:
        return " | ".join(e.text for e in s.events() if e.kind == "note")

    def ask_seeing(self, seen: list):
        def fake(question, **kw):
            seen.append(list(kw.get("context") or []))
            return "an answer", "codex"
        return fake

    def asked(self, s, turns: list[str]) -> list[str]:
        for turn in turns:
            s.thread.add(turn)
        seen: list[list[str]] = []
        s.draft.set("and what about the workers")
        with mock.patch("flow.session.ask", side_effect=self.ask_seeing(seen)):
            s.send()
            for _ in range(200):
                s.pump_results()
                if s.reply:
                    break
                time.sleep(0.01)
        return seen[0]

    def test_an_ordinary_conversation_now_arrives_whole(self):
        # The measured shape: four prior turns, question and reply alternating, none of
        # them short. All four used to be three.
        s = session()
        s.toggle_mode(to=CONVERSE)
        turns = [f"turn {i} " + "x" * 400 for i in range(4)]
        context = self.asked(s, turns)
        self.assertEqual(len(context), 4, [t[:12] for t in context])

    def test_and_a_conversation_that_still_outruns_the_bound_says_so(self):
        """The silence was the worse half. A bound nobody is told about is amnesia."""
        s = session()
        s.toggle_mode(to=CONVERSE)
        turns = [f"turn {i} " + "x" * 3000 for i in range(6)]
        context = self.asked(s, turns)
        self.assertLess(len(context), 6)
        self.assertIn("the CLI saw the last", self.notes(s))

    def test_and_says_nothing_when_nothing_was_dropped(self):
        s = session()
        s.toggle_mode(to=CONVERSE)
        self.asked(s, ["short one", "(reply) short answer"])
        self.assertNotIn("the CLI saw the last", self.notes(s))


class TestAFallbackThatRescuesACallIsNotSilent(unittest.TestCase):
    """Item 74. `_invoke_any` dropped every earlier failure the moment a later CLI
    answered, so a codex timeout rescued by kiro-cli left no mark in the note, the trace
    or anywhere else — indistinguishable from a run where codex was never installed. The
    owner read a 40 s wait answered by the third CLI as the first one being broken.

    Invariant 5 from the other side: a refusal is not silent because something else
    eventually said yes.
    """

    class Recording:
        """A diag that keeps its records in memory. The default writes nothing at all."""

        path = None

        def __init__(self):
            self.records: list[dict] = []

        def write(self, kind, /, **fields):
            self.records.append({"kind": kind, **fields})

    def notes(self, s) -> str:
        return " | ".join(e.text for e in s.events() if e.kind == "note")

    def answer_after(self, *failures):
        """An `ask` that fills its `skipped` out-parameter the way `_invoke_any` does."""
        def fake(question, **kw):
            kw["skipped"].extend(failures)
            return "Use ALTER TABLE.", "kiro-cli"
        return fake

    def run_ask(self, fake):
        s = session(diag=self.Recording())
        s.toggle_mode(to=CONVERSE)
        s.draft.set("how do I widen a column")
        with mock.patch("flow.session.ask", side_effect=fake):
            s.send()
            for _ in range(200):
                s.pump_results()
                if s.reply:
                    break
                time.sleep(0.01)
        return s

    def test_the_note_names_the_one_that_answered_and_the_one_that_did_not(self):
        s = self.run_ask(self.answer_after("codex timed out after 20s"))
        notes = self.notes(s)
        self.assertIn("answered via kiro-cli", notes)
        self.assertIn("codex timed out after 20s", notes)

    def test_a_clean_first_answer_still_reads_as_one_sentence(self):
        s = self.run_ask(lambda question, **kw: ("Use ALTER TABLE.", "codex"))
        self.assertIn("answered via codex", self.notes(s))
        self.assertNotIn("after", self.notes(s))

    def test_the_trace_can_tell_the_two_runs_apart(self):
        # It could not: every success wrote one provider and nothing else, so a fallback
        # that fired and a first choice that answered were the same record.
        s = self.run_ask(self.answer_after("codex timed out after 20s",
                                           "claude exited 1: not logged in"))
        written = [r for r in s.diag.records if r.get("kind") == "ask" and r.get("ok")]
        self.assertEqual(written[-1]["provider"], "kiro-cli")
        self.assertEqual(written[-1]["skipped"], ["timeout", "exit"])


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

    def test_and_in_converse_it_talks_about_the_button_that_was_pressed(self):
        """Item 74, reported as "even though there is context".

        The chip reads **Ask**, and the card behind it is showing the question, its
        answer and the turns before them — so a refusal naming the *draft* read as Flow
        denying the conversation it was displaying. The draft really was empty; the
        sentence was about the wrong object.
        """
        s = session()
        s.toggle_mode(to=CONVERSE)
        s.thread.add("what is the deploy order")
        s.thread.add("(reply) migrations first, then the workers")
        s.events()
        self.assertEqual(s.send(), "")
        notes = self._notes(s)
        self.assertIn("nothing to ask", notes)
        self.assertNotIn("draft", notes)

    def test_a_second_ask_while_one_is_in_flight_says_so(self):
        s = session()
        s.toggle_mode(to=CONVERSE)
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
        s.toggle_mode(to=CONVERSE)
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
        s.toggle_mode(to=CONVERSE)
        self.assertFalse(s.toggle_speech())
        self._answer(s)
        self.assertEqual(sp.said, [])

    def test_unmuting_restores_it(self):
        sp = FakeSpeaker()
        s = session(speaker=sp)
        s.toggle_mode(to=CONVERSE)
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
        s.toggle_mode(to=CONVERSE)
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
        s.toggle_mode(to=CONVERSE)
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
        # The user's words go first and whole; the grounding clause follows them (it
        # trails deliberately — see `ask_framing`). What this pins is that auto-ask sends
        # the draft as spoken, not a summary or a fragment of it.
        sent = ask.call_args.args[0]
        self.assertTrue(sent.startswith("can you hear me"), sent[:80])

    def test_dictate_mode_never_sends_itself(self):
        # R5 in full force: this one pastes into whatever has focus.
        s = self._armed()
        s.toggle_mode(to=DICTATE)
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
            s.toggle_mode(to=CONVERSE)
        note = self.notes(s)
        self.assertIn("codex", note)
        self.assertIn("leaves this machine", note)

    def test_dictate_mode_makes_no_such_claim(self):
        # Nothing leaves the machine in dictate mode, so nothing should say it does.
        s = session()
        s.toggle_mode(to=CONVERSE)
        s.events()
        s.toggle_mode(to=CONVERSE)
        self.assertNotIn("leaves this machine", self.notes(s))

    def test_an_absent_cli_is_said_plainly_rather_than_named(self):
        s = session()
        with mock.patch("flow.session.available", return_value=[]):
            s.toggle_mode(to=CONVERSE)
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


class TestTheNotesObeyThePin(unittest.TestCase):
    """The pin moved the call and the marker; the words beside them stayed put.

    Found while building item 15 and outside that item's files: `_provider()` returned
    `available()[0].name` while `_start_refine` and `_start_ask` both passed
    `cli=self._cli`. So after **Agent CLI -> claude** in the menu, claude answered, the
    pill drew `claude`, and every note beside it said codex — a warning about where the
    words go, naming the wrong destination, printed one line from the badge that had it
    right.
    """

    def notes(self, s) -> str:
        return " | ".join(e.text for e in s.events() if e.kind == "note")

    def clis(self):
        # Real `Cli`s: `name` is reserved in Mock's constructor, and item 11 shipped a
        # Mock repr into a note before a test caught it.
        from flow.refine import Cli

        return Cli("codex", ("codex",)), Cli("claude", ("claude",))

    def test_the_mode_switch_note_names_the_pin_and_not_the_first_on_path(self):
        codex, claude = self.clis()
        s = session(cli=claude)
        with mock.patch("flow.session.available", return_value=[codex, claude]):
            s.toggle_mode(to=CONVERSE)
        note = self.notes(s)
        self.assertIn("claude", note)
        self.assertNotIn("codex", note, "the note named a CLI that will not be called")

    def test_the_asking_note_names_the_pin(self):
        codex, claude = self.clis()
        s = session(cli=claude)
        with mock.patch("flow.session.available", return_value=[codex, claude]), \
             mock.patch("flow.session.ask", return_value=("yes", "claude")):
            s._start_ask("can you hear me")
            s.wait_idle(timeout=5.0)
        self.assertIn("asking claude", self.notes(s))

    def test_the_refining_note_names_the_pin(self):
        codex, claude = self.clis()
        s = session(cli=claude)
        s.draft.set("widen the column")
        with mock.patch("flow.session.available", return_value=[codex, claude]), \
             mock.patch("flow.session.refine", return_value=("x", "claude")):
            s._start_refine("make it formal")
            s.wait_idle(timeout=5.0)
        self.assertIn("refining via claude", self.notes(s))

    def test_a_pin_taken_mid_session_carries_the_notes_with_it(self):
        # The menu is the only way most people will ever pin one, and it pins into a
        # live session — so the fix has to hold for a `set_cli` after startup, not just
        # for a `--cli` flag read once.
        codex, claude = self.clis()
        s = session()
        with mock.patch("flow.session.available", return_value=[codex, claude]):
            s.toggle_mode(to=CONVERSE)
            s.toggle_mode(to=DICTATE)
            s.set_cli(claude)
            s.events()
            s.toggle_mode(to=CONVERSE)
        self.assertIn("claude", self.notes(s))

    def test_with_no_pin_the_preference_order_still_decides(self):
        # None is a preference, not a decision: unpinned has to keep walking the order.
        codex, claude = self.clis()
        s = session()
        with mock.patch("flow.session.available", return_value=[codex, claude]):
            s.toggle_mode(to=CONVERSE)
        self.assertIn("codex", self.notes(s))

    def test_a_pin_that_is_not_on_path_is_still_what_gets_named(self):
        # `_invoke_any` never re-checks PATH for an explicit `cli=` — a pin is a
        # decision and is never second-guessed — so the pinned CLI is what will be run
        # and what will fail. Naming the one that happens to be installed instead would
        # report a call that is not made, which is the defect this class exists for, and
        # a note is not the place to invent a fallback the caller does not have.
        codex, claude = self.clis()
        s = session(cli=claude)
        with mock.patch("flow.session.available", return_value=[codex]):
            s.toggle_mode(to=CONVERSE)
        self.assertIn("claude", self.notes(s))

    def test_the_marker_and_the_note_cannot_disagree(self):
        # The two are read together — the badge on the pill and the note drawn beside
        # it — and item 15 gave the badge the pin. Same inputs, same answer, or the
        # window contradicts itself.
        #
        # Restated when the adapter grew past two names, because "same answer" was only
        # ever the whole rule by accident: every shipped name fitted the 6-character slot,
        # so equality and agreement were the same assertion. They are not. The marker may
        # **decline** to name a CLI — a clipped name reads as a different CLI, so it draws
        # the mode instead — and what it may never do is name a *different* one. `ASK` is
        # the mode, and `opencode` at 8 characters is the first shipped name to reach it.
        #
        # Restated a second time when an entry gained a `marker` alias. A shorter name for
        # the same CLI is not a different CLI, so the rule is still "declines or agrees" —
        # what changes is what agreement looks like: the alias where the entry has one, the
        # name where it fits, `ASK` where neither does. Written from the entry rather than
        # from a literal, because a hardcoded "kiro" here would pass whatever the pill drew.
        import flow.ui as ui

        from flow.refine import named

        codex, claude = self.clis()
        # The last three rows are the adapter's new names, and they are here because the
        # marker refuses anything over six characters while the note has no such budget:
        # the two can only agree by both falling back, and nothing but a test says so.
        opencode, gemini = named("opencode"), named("gemini")
        # `kiro-cli` is the first *verified* name to overflow the slot, which is the case
        # that matters: `opencode` proved the rule while being inert, so nothing could
        # ever have been asked of it. This one answers.
        kiro = named("kiro-cli")
        for pinned, resolved in ((claude, [codex, claude]), (None, [codex, claude]),
                                 (claude, [codex]),
                                 (opencode, [codex, opencode]), (None, [opencode]),
                                 (kiro, [codex, kiro]), (None, [kiro]),
                                 (None, [gemini])):
            with self.subTest(pinned=pinned, resolved=[c.name for c in resolved]):
                pill = ui.Pill.__new__(ui.Pill)
                pill._clis = None
                pill.session = mock.Mock(cli=pinned)
                s = session(cli=pinned)
                with mock.patch("flow.session.available", return_value=resolved), \
                     mock.patch.object(ui, "available", return_value=resolved):
                    who, marker = s._provider(), pill._marker()
                answering = next((c for c in resolved if c.name == who), None)
                short = (answering.marker if answering is not None else "") or who
                if len(short) <= ui.Pill.MARKER_MAX:
                    self.assertEqual(marker, short)
                else:
                    self.assertEqual(marker, "ASK", "it named a CLI that is not answering")


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
        s.toggle_mode(to=CONVERSE)
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
