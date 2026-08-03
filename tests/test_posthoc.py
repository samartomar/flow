"""Tests for the post-hoc "that was a command" rescue.

A misroute costs the user two utterances today: undo, then say it again — and the
second attempt is no likelier to be heard correctly than the first. This takes one
short phrase and re-reads audio Flow already has.

The tests that matter are the ones about failure: if the re-read finds no command, the
user's words must come back exactly where they were. Losing dictation to a failed guess
would be worse than the misroute.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.audio import BLOCK  # noqa: E402
from flow.edits import plan  # noqa: E402
from flow.session import Session  # noqa: E402

LOUD = np.full(BLOCK, 0.2, dtype=np.float32)
QUIET = np.zeros(BLOCK, dtype=np.float32)


class ScriptedMic:
    def __init__(self) -> None:
        self._blocks: list[np.ndarray] = []
        self.level_db = -60.0

    def utterance(self) -> None:
        self._blocks += [LOUD] * 20 + [QUIET] * 16

    def start(self) -> None: ...
    def stop(self) -> None: ...

    @property
    def active(self) -> bool:
        return True

    def restart(self) -> None: ...

    def drain(self) -> list[np.ndarray]:
        out, self._blocks = self._blocks, []
        return out


class BiasAwareAsr:
    def __init__(self, finals, rescued=""):
        self.finals = list(finals)
        self.rescued = rescued
        self.bias_seen = []

    def load(self) -> None: ...
    def unload(self) -> None: ...
    loaded = True

    def text(self, audio, *, final: bool = False, hotwords: str = "") -> str:
        if hotwords:
            self.bias_seen.append(hotwords)
            return self.rescued
        if not final:
            return ""
        return self.finals.pop(0) if self.finals else ""


def session_with(finals, rescued="", force_append_from=None):
    """Run `finals` through a session, one utterance at a time.

    `force_append_from` presses Continue before that index, which is how a misroute is
    staged: the override has to be set *before* the utterance is routed, not after.
    """
    mic = ScriptedMic()
    asr = BiasAwareAsr(finals, rescued)
    s = Session(asr=asr, mic=mic)
    s.start()
    for i in range(len(finals)):
        if force_append_from is not None and i >= force_append_from:
            s.force_next = "append"
        mic.utterance()
        s.wait_idle(timeout=5.0)
    return s, asr, mic


class TestTrigger(unittest.TestCase):
    DRAFT = "Meeting on Tuesday. delete Tuesday"

    def test_the_phrases_people_would_actually_say(self):
        for utterance in (
            "that was a command",
            "that was an instruction",
            "that was an edit",
            "no, that was a command",
            "i meant that as a command",
            "please, that was a command",
        ):
            with self.subTest(utterance=utterance):
                self.assertEqual(plan(utterance, self.DRAFT).kind, "rescue")

    def test_ordinary_speech_is_not_a_trigger(self):
        for utterance in (
            "that was a long meeting",
            "that was an interesting point",
            "the command line is broken",
        ):
            with self.subTest(utterance=utterance):
                self.assertNotEqual(plan(utterance, self.DRAFT).kind, "rescue")


class TestPostHocRescue(unittest.TestCase):
    def test_a_misrouted_command_is_taken_back_and_applied(self):
        # "delete Tuesday" landed as dictation; the words as transcribed *are* a
        # command once the draft is restored to what it was.
        s, _asr, _mic = session_with(
            ["Meeting on Tuesday.", "delete Tuesday"], force_append_from=1
        )
        self.assertTrue(s.draft.text.endswith("delete Tuesday"), s.draft.text)

        self.assertTrue(s.rescue_last_append())
        s.wait_idle(timeout=5.0)
        self.assertEqual(s.draft.text, "Meeting on.")
        s.close()

    def test_the_re_read_uses_the_audio_when_the_words_are_not_a_command(self):
        s, asr, _mic = session_with(
            ["Meeting on Tuesday.", "the lead toosdai"],
            rescued="delete Tuesday", force_append_from=1,
        )
        self.assertTrue(s.draft.text.endswith("the lead toosdai"))
        s.rescue_last_append()
        s.wait_idle(timeout=5.0)
        for _ in range(3):
            s.tick()
        self.assertTrue(asr.bias_seen, "the biased re-read never ran")
        self.assertEqual(s.draft.text, "Meeting on.")
        s.close()

    def test_a_failed_re_read_gives_the_words_back(self):
        s, _asr, _mic = session_with(
            ["Meeting on Tuesday.", "and then we discussed the budget"],
            rescued="and then we discussed the budget", force_append_from=1,
        )
        before = s.draft.text
        s.rescue_last_append()
        s.wait_idle(timeout=5.0)
        for _ in range(3):
            s.tick()
        self.assertEqual(s.draft.text, before, "dictation was lost to a failed guess")
        notes = [e.text for e in s.events() if e.kind == "note"]
        self.assertTrue(any("could not re-read" in n for n in notes), notes)
        s.close()

    def test_nothing_to_rescue_is_said_rather_than_ignored(self):
        s, _asr, _mic = session_with([])
        self.assertFalse(s.rescue_last_append())
        notes = [e.text for e in s.events() if e.kind == "note"]
        self.assertTrue(any("nothing to re-read" in n for n in notes), notes)
        s.close()

    def test_can_rescue_reflects_whether_there_is_anything_to_take_back(self):
        s, _asr, _mic = session_with([])
        self.assertFalse(s.can_rescue)
        s.close()

        s, _asr, _mic = session_with(["Meeting on Tuesday."])
        self.assertTrue(s.can_rescue)
        s.close()

    def test_the_spoken_trigger_reaches_the_rescue(self):
        s, _asr, mic = session_with(
            ["Meeting on Tuesday.", "delete Tuesday"], force_append_from=1
        )
        # Now say the trigger as a third utterance.
        s.asr.finals.append("that was a command")
        mic.utterance()
        s.wait_idle(timeout=5.0)
        for _ in range(3):
            s.tick()
        self.assertEqual(s.draft.text, "Meeting on.")
        s.close()

    def test_a_rescue_does_not_fire_twice_on_the_same_utterance(self):
        s, _asr, _mic = session_with(
            ["Meeting on Tuesday.", "delete Tuesday"], force_append_from=1
        )
        self.assertTrue(s.rescue_last_append())
        s.wait_idle(timeout=5.0)
        after_first = s.draft.text
        self.assertFalse(s.rescue_last_append())
        self.assertEqual(s.draft.text, after_first)
        s.close()


if __name__ == "__main__":
    unittest.main()


class TestEligibilityDiesWithTheDraftItDiagnosed(unittest.TestCase):
    """DRAFT-02: "Was a command" stayed offered long after it meant anything.

    `can_rescue` asked two questions — is there a remembered append, and is the draft
    non-empty — and neither of them is *is this still the draft that append landed in*.
    So the chip stayed on screen across further dictation, edits, sends and mode changes,
    and pressing it minutes later withdrew an utterance from a draft it had never been
    part of and reinterpreted it against text it had never seen.

    The revision is the whole guard, and it is nearly free: every mutation of `Draft`
    bumps it already, because a CLI rewrite takes ~7 s and something had to be able to
    tell whether the text it was computed from still existed.
    """

    def _appended(self):
        s, _asr, mic = session_with(["some dictated words"])
        self.addCleanup(s.close)
        self.assertTrue(s.can_rescue, "nothing to test if the chip was never offered")
        return s, mic

    def test_it_is_offered_immediately_after_the_append(self):
        s, _mic = self._appended()
        self.assertTrue(s.can_rescue)

    def test_a_later_append_re_points_it_rather_than_leaving_it_stale(self):
        # Not "takes it away", which is what this check first asserted and what the item
        # spec's wording suggests. A second dictation *is* the thing a rescue should now
        # be offering to take back, and `_remember_append` re-points at it. The stale
        # case is the one below: a capture that changes the draft without appending.
        s, mic = self._appended()
        first = s._last_append
        s.asr.finals.append("and some more words")
        mic.utterance()
        s.wait_idle(timeout=5.0)
        self.assertTrue(s.can_rescue)
        self.assertIsNot(s._last_append, first, "the chip still pointed at the old one")
        self.assertEqual(s._last_append.revision, s.draft.revision)

    def test_an_edit_takes_it_away(self):
        s, _mic = self._appended()
        s.draft.set("something else entirely")
        self.assertFalse(s.can_rescue)

    def test_clearing_takes_it_away(self):
        s, _mic = self._appended()
        s.draft.clear()
        self.assertFalse(s.can_rescue)

    def test_a_mode_change_takes_it_away(self):
        # The one that the revision cannot see: `toggle_mode` deliberately does not touch
        # the draft, because someone who dictated three sentences and then decides to ask
        # about them should not have to say it again. So this is cleared by name.
        s, _mic = self._appended()
        s.toggle_mode()
        self.assertFalse(s.can_rescue)

    def test_an_undo_back_to_the_same_text_still_takes_it_away(self):
        # Revisions are counted, not compared by content. Text that looks the same is not
        # the same draft, and a rescue that matched on text would accept this.
        s, _mic = self._appended()
        before = s.draft.text
        s.draft.set("x")
        s.draft.undo()
        self.assertEqual(s.draft.text, before)
        self.assertFalse(s.can_rescue)


class TestARescueInFlightIsBoundToWhatItDiagnosed(unittest.TestCase):
    """DRAFT-03: the re-decode came back and was applied to whatever was there now.

    A rescue is a ~1 s decode. The draft can move underneath it — the user keeps talking,
    or edits, or the auto-ask countdown fires — and `_finish_rescue` applied its result
    against `self.draft.text` as it stood at delivery, with nothing checking that this was
    the text the rescue was computed for.

    Both paths need it and they need different answers on mismatch. The escalated one
    withdrew nothing, so dropping it is free. The user-pressed one already ran `undo`,
    so its words are in the air, and `_give_back`'s bargain applies: the user's words are
    never the price of a failed guess.
    """

    def _mid_rescue(self):
        """A session with a post-hoc rescue genuinely in flight.

        The utterance has to be *mis-transcribed* for one to be submitted at all. Given
        words that already read as a command, `rescue_last_append` re-plans them locally
        and never reaches the decoder — which is what the first version of this fixture
        did, leaving every check below asserting against a rescue that had already
        finished before the test touched anything.
        """
        s, asr, mic = session_with(["Meeting on Tuesday", "the lead toosdai"],
                                   rescued="delete Tuesday", force_append_from=1)
        self.addCleanup(s.close)
        s.rescue_last_append()
        self.assertIsNotNone(s._post_hoc, "no rescue was submitted")
        return s, asr, mic

    def test_an_edit_during_the_decode_discards_the_rescue(self):
        s, _asr, _mic = self._mid_rescue()
        s.draft.set("a completely different draft")
        s.wait_idle(timeout=5.0)
        s.pump_results()
        # The user's edit survives whole. What must *not* have happened is the rescue's
        # own edit — "delete Tuesday" against a draft with no Tuesday in it.
        self.assertTrue(s.draft.text.startswith("a completely different draft"),
                        s.draft.text)
        self.assertNotIn("Meeting on", s.draft.text,
                         "a stale rescue rewrote a draft it had never seen")

    def test_and_says_so(self):
        s, _asr, _mic = self._mid_rescue()
        list(s.events())  # drained *before* the result can land, or wait_idle takes it
        s.draft.set("a completely different draft")
        s.wait_idle(timeout=5.0)
        for _ in range(3):
            s.tick()
        notes = [e.text for e in s.events() if e.kind == "note"]
        self.assertTrue(any("moved" in n for n in notes), notes)

    def test_the_withdrawn_words_are_not_the_price(self):
        # The rescue withdrew the utterance with `undo` before re-reading it. A mismatch
        # must not leave that undo standing — the words were the user's, and losing them
        # to a guard is the same loss as losing them to a bad guess.
        s, _asr, _mic = self._mid_rescue()
        s.draft.set("a completely different draft")
        s.wait_idle(timeout=5.0)
        s.pump_results()
        self.assertIn("the lead toosdai", s.draft.text)

    def test_an_undisturbed_rescue_still_applies(self):
        # The guard must not become "rescue never works", which is the failure mode a
        # revision check invites.
        s, _asr, _mic = self._mid_rescue()
        s.wait_idle(timeout=5.0)
        for _ in range(3):
            s.tick()
        self.assertEqual(s.draft.text, "Meeting on")

    def test_a_result_for_a_different_utterance_is_refused(self):
        # Item 52's ids, spent. A rescue result carries the record it was submitted for,
        # so a result arriving for some other utterance is not this rescue's answer
        # whatever the draft revision happens to say.
        from flow.session import Utterance

        s, _asr, _mic = self._mid_rescue()
        s._finish_rescue("delete Tuesday",
                         Utterance(9999, np.zeros(BLOCK, dtype=np.float32), 0))
        # Refused, so the rescue's edit did not land — and the withdrawn words came back
        # rather than being spent on somebody else's answer.
        self.assertNotIn("Meeting on Tuesday delete", s.draft.text)
        self.assertIn("the lead toosdai", s.draft.text)
