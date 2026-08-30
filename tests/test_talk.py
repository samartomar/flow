"""Push-to-talk end to end: a hold on the keyboard, a paste out the other side.

`tests/test_chord.py` covers the hook's state machine and stops at the queue. This picks
the same gesture up at the queue and follows it through `Pill`'s dispatch into a real
`Session`, because everything that can actually go wrong with push-to-talk lives in the
seam between them:

  **The release cannot paste.** A final decode measured 0.7-7 s on the machine this was
  built for, so the release arms a wait and the frame loop finishes the gesture. Every
  edge case below is some way that wait can be wrong — the decode that never lands, the
  release that never arrives, the hold that starts while another is still waiting.

  **What was said is never dropped to make the code simpler.** A hold Windows took over
  with `ctrl+win+d` still commits its audio; it just does not paste. The draft is where
  words wait, and the Send chip is what the user already knows.

The microphone and the decoder are fakes, and the decode is driven by hand, so a test
can sit exactly in the half-second between a release and the final that answers it.
"""

import queue
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

if sys.platform != "win32":  # pragma: no cover - the CI legs that are not Windows
    raise unittest.SkipTest("Windows-only: flow.hotkey binds user32 at import")

import flow.ui as ui  # noqa: E402
from flow.hotkey import Chord  # noqa: E402
from flow.session import BLOCK, Session  # noqa: E402


class FakeMic:
    """Counts opens and closes, because the gesture is judged on them.

    `start`/`stop` are the pair push-to-talk has to get exactly right: a hold that opens
    a microphone it does not close is the failure mode the whole `PTT_MAX_HOLD_SEC`
    branch exists for, and one that closes a microphone it did not open is the chord
    walking off with the toggle hotkey's session.
    """

    def __init__(self) -> None:
        self.starts = 0
        self.stops = 0
        self.active = False
        self.dropped = 0
        self.device_name = "fake"
        self._blocks: list[np.ndarray] = []

    def start(self) -> None:
        self.starts += 1
        self.active = True

    def stop(self) -> None:
        self.stops += 1
        self.active = False

    def drain(self) -> list:
        out, self._blocks = self._blocks, []
        return out

    def alive(self) -> bool:
        return self.active


class FakeAsr:
    loading = False
    loaded = False

    def load(self, final=None) -> None:
        self.loaded = True

    def unload(self) -> None:
        self.loaded = False

    def text(self, audio, *, final=False, hotwords="") -> str:
        return ""


class Harness:
    """A `Pill` with the four attributes push-to-talk touches, and nothing drawn.

    Built with `__new__` for `tests/test_lite.py`'s reason, word for word: `tk.Misc`
    forwards an unknown attribute to `self.tk`, so on an instance whose `__init__` never
    ran a missing attribute recurses instead of defaulting. Every attribute the paths
    under test read is set here on purpose.
    """

    def __init__(self, *, lite: bool = False) -> None:
        self.mic = FakeMic()
        # `Pill.converse` is a property reading `session.mode`, so the surface follows
        # the session here exactly as it does in the app — there is nothing to set.
        self.session = Session(asr=FakeAsr(), mic=self.mic)
        self.pasted: list[tuple[str, bool]] = []
        self.notes: list[str] = []

        p = ui.Pill.__new__(ui.Pill)
        p.session = self.session
        p.lite = lite

        p.on_send = self._on_send
        p.paste_target = 0x22
        p.bubble = mock.Mock()
        p.card = mock.Mock()
        p.bubble.note.side_effect = self.notes.append
        p.card.note.side_effect = self.notes.append
        p.armed = False
        p._flash = 0
        p._disarmed_since = 0.0
        p._ptt_since = None
        p._ptt_wait = None
        p._draw = lambda: None
        p.clipboard_clear = lambda: None
        p.clipboard_append = lambda _t: None
        p.update_idletasks = lambda: None
        self.pill = p

        self.presses: queue.Queue[str] = queue.Queue()
        self.chord = Chord(self.presses, frozenset({"ctrl", "win"}))

    def _on_send(self, text: str, target=None, submit: bool = False) -> str:
        self.pasted.append((text, submit))
        return ""

    # -- driving -----------------------------------------------------------

    def dispatch(self) -> None:
        """Drain the chord's queue through `Pill`'s own dispatch table.

        The words are re-listed here rather than calling `_frame`, which would want a
        Tk canvas. The tripwire in `test_chord.py` is what keeps this list honest: it
        asserts each of the four words appears in `ui.py` as a dispatch literal.
        """
        while not self.presses.empty():
            name = self.presses.get_nowait()
            if name == "warm":
                self.session.warm()
            elif name == "talk":
                self.pill._talk_start()
            elif name == "talk-end":
                self.pill._talk_end(send=True)
            elif name == "talk-break":
                self.pill._talk_end(send=False)
            elif name == "send":
                self.pill._send()
            elif name == "cancel":
                self.pill._clear()
            elif name == "mode":
                self.pill._ptt_wait = None
                self.session.toggle_mode()
            elif name == "toggle":
                self.pill._toggle()
        self.pump_events()

    def key(self, name: str) -> "Harness":
        """Press one of the registered hotkeys, through the same dispatch the chord uses.

        The five combos and the chord's four words land on one queue by design — the
        session cannot tell them apart, and neither should a test of what happens when
        two of them mean overlapping things.
        """
        self.presses.put(name)
        self.dispatch()
        return self

    def pump_events(self) -> None:
        """The one event this gesture depends on, handled the way `_pump_events` does.

        `talk_end` closes the microphone and *asks* the pill to disarm rather than
        reaching into it: `armed` belongs to the UI thread. In the app the real
        `_pump_events` runs in the same frame as the dispatch, so the pill is never seen
        claiming to listen with a closed device — reproducing that ordering here is what
        makes this harness worth trusting.
        """
        for ev in self.session.events():
            if ev.kind == "disarm":
                self.pill.armed = False

    def settle(self, timeout: float = 5.0) -> "Harness":
        """Wait for the real decode worker to finish what the release handed it.

        The worker is a live thread even with a fake transcriber, so `session.busy` is
        genuinely true for a moment after a release. Waiting rather than patching keeps
        the ordering under test real: the paste must follow the final, and a test that
        stubbed `busy` to False could not tell the difference.
        """
        end = time.perf_counter() + timeout
        while self.session.busy and time.perf_counter() < end:
            time.sleep(0.005)
        self.session.pump_results()
        self.pump_events()
        return self

    def press(self) -> "Harness":
        self.chord._talking = True
        self.presses.put("warm")
        self.presses.put("talk")
        self.dispatch()
        return self

    def release(self, *, clean: bool = True) -> "Harness":
        self.presses.put("talk-end" if clean else "talk-break")
        self.dispatch()
        return self

    def speak(self, seconds: float = 1.0) -> "Harness":
        """Put audio in the utterance buffer the way `_pump_audio` would."""
        blocks = max(1, int(seconds * 16000 / BLOCK))
        self.session._utter = [np.zeros(BLOCK, dtype=np.float32)] * blocks
        return self

    def decode(self, text: str) -> "Harness":
        """Land a final decode: let the worker drain, then put the words on the draft."""
        self.settle()
        self.session.draft.set(text)
        return self

    def frame(self) -> "Harness":
        self.pill._pump_talk()
        return self


class TestTheHoldOpensAndTheReleaseCloses(unittest.TestCase):
    def setUp(self):
        self.h = Harness()
        self.addCleanup(self.h.session.close)

    def test_the_press_opens_the_microphone_and_the_release_closes_it(self):
        self.h.press()
        self.assertTrue(self.h.mic.active)
        self.assertTrue(self.h.pill.armed)
        self.h.speak().release()
        self.assertFalse(self.h.mic.active)

    def test_the_press_warms_before_it_captures(self):
        # The reason the warm is a separate word. By the time capture is open the models
        # have been asked for, so the load overlaps the utterance instead of following
        # it — which is what the 1 230 ms first partial in the trace was.
        self.assertFalse(self.h.session.asr.loaded)
        self.h.press()
        self.assertTrue(self.h.session.asr.loaded)

    def test_a_second_press_does_not_reopen_a_microphone_already_open(self):
        # Key repeat, or a `talk` that raced a slow frame. Reopening mid-utterance would
        # be indistinguishable to the user from Flow having lost what they just said.
        self.h.press()
        self.h.press()
        self.assertEqual(self.h.mic.starts, 1)

    def test_a_release_with_no_hold_behind_it_does_nothing(self):
        # The OS can deliver a keyup whose keydown this process never saw — a chord
        # begun before Flow launched, or while a UAC prompt owned the input desktop.
        # It must not close a microphone the toggle hotkey opened.
        self.h.session.start()
        self.assertTrue(self.h.mic.active)
        self.h.release()
        self.assertTrue(self.h.mic.active)


class TestTheChordGivesBackExactlyWhatItTook(unittest.TestCase):
    def setUp(self):
        self.h = Harness()
        self.addCleanup(self.h.session.close)

    def test_a_hold_over_an_already_armed_session_leaves_it_armed(self):
        # Somebody armed with the toggle hotkey for long-form dictation, then reached
        # for the chord. The release sends what they said; it does not switch off the
        # microphone they turned on by another route.
        self.h.session.start()
        opens = self.h.mic.starts
        self.h.press()
        self.assertEqual(self.h.mic.starts, opens)
        self.h.speak().release()
        self.assertTrue(self.h.mic.active)
        self.assertEqual(self.h.mic.stops, 0)

    def test_and_a_hold_that_opened_it_closes_it(self):
        self.h.press().speak().release()
        self.assertEqual(self.h.mic.stops, 1)
        self.assertFalse(self.h.pill.armed)


class TestWhatWasSaidSurvivesEveryPath(unittest.TestCase):
    """P2, on the one path with the most reason to cut a corner.

    `pause()` bumps the capture generation, which is precisely how a deliberate stop
    refuses a decode from before it — so a `talk_end` written with `pause()` would throw
    away the utterance the release exists to send. `_give_up_on_device` learned this
    first and the comment there is the longer version.
    """

    def setUp(self):
        self.h = Harness()
        self.addCleanup(self.h.session.close)

    def test_the_release_does_not_refuse_the_decode_it_just_asked_for(self):
        before = self.h.session._capture_generation
        self.h.press().speak().release()
        self.assertEqual(self.h.session._capture_generation, before)

    def test_the_utterance_reaches_the_decoder(self):
        self.h.press().speak(2.0)
        self.assertTrue(self.h.session._utter)
        self.h.release()
        self.assertFalse(self.h.session._utter)  # committed, not abandoned
        self.assertTrue(self.h.session._sent)

    def test_a_broken_hold_keeps_the_words_and_pastes_nothing(self):
        # ctrl+win+d after somebody had already started talking. The desktop switch is
        # not a reason to lose a sentence, and it is not a reason to paste one into the
        # window the switch just moved to either.
        self.h.press().speak(2.0).release(clean=False)
        self.assertTrue(self.h.session._sent)
        self.h.decode("what they said").frame()
        self.assertEqual(self.h.pasted, [])
        self.assertEqual(self.h.session.draft.text, "what they said")

    def test_a_desktop_switch_nobody_spoke_into_is_invisible(self):
        # The common case, and the one that must not produce a note. `_utter` is what
        # the gate let through, and in the 50 ms before the third key that is nothing —
        # so there is no minimum-length rule here, and nothing to say.
        self.h.press().release(clean=False)
        self.assertFalse(self.h.session._sent)
        self.assertEqual(self.h.notes, [])
        self.assertEqual(self.h.pasted, [])


class TestThePasteWaitsForTheDecode(unittest.TestCase):
    def setUp(self):
        self.h = Harness()
        self.addCleanup(self.h.session.close)

    def test_nothing_is_pasted_while_the_decoder_is_still_working(self):
        # The bug this ordering prevents is pasting the *partial* — the dimmed, italic,
        # possibly-hallucinated text that precedes a final by design.
        self.h.press().speak().release()
        with mock.patch.object(type(self.h.session), "busy",
                               property(lambda _s: True)):
            self.h.decode("half a sentence").frame()
            self.assertEqual(self.h.pasted, [])

    def test_and_it_pastes_the_moment_the_final_lands(self):
        self.h.press().speak().release()
        self.h.decode("the whole sentence").frame()
        self.assertEqual(self.h.pasted, [("the whole sentence", False)])

    def test_a_hold_nobody_spoke_into_never_arms_a_wait(self):
        # An accidental tap. Without this the next decode from any source would be
        # pasted by a wait that had been sitting open since the tap.
        self.h.press().release()
        self.assertIsNone(self.h.pill._ptt_wait)
        self.h.decode("something said later").frame()
        self.assertEqual(self.h.pasted, [])

    def test_an_empty_decode_pastes_nothing(self):
        # Silence, noise, or a hallucination `clean.py` rejected. Pasting "" would clear
        # a selection in the user's window for no reason.
        self.h.press().speak().release()
        self.h.decode("").frame()
        self.assertEqual(self.h.pasted, [])

    def test_the_wait_is_disarmed_once_it_fires(self):
        # Otherwise the next thing decoded — a partial from a later utterance, an
        # answer — would be pasted again by a wait nobody rearmed.
        self.h.press().speak().release()
        self.h.decode("first").frame()
        self.h.decode("second").frame()
        self.assertEqual(self.h.pasted, [("first", False)])

    def test_a_new_hold_supersedes_a_wait_that_is_still_open(self):
        # Somebody released, got impatient, and pressed again. The old wait must not
        # fire into the new utterance — and the words it was waiting for stay in the
        # draft rather than being discarded.
        self.h.press().speak().release()
        self.h.press()
        self.assertIsNone(self.h.pill._ptt_wait)
        self.h.decode("from the first hold").frame()
        self.assertEqual(self.h.pasted, [])
        self.assertEqual(self.h.session.draft.text, "from the first hold")


class TestTheTwoTimeoutsAreNotHypothetical(unittest.TestCase):
    """Both branches of `_pump_talk`, which exist because this app has already wedged.

    The trace from the night this was written ends with `state -> idle` and no `final`
    behind it. A paste wait with no ceiling turns that into a gesture that never
    completes; a hold with no ceiling turns a dropped keyup into a microphone left open.
    """

    def setUp(self):
        self.h = Harness()
        self.addCleanup(self.h.session.close)

    def test_a_decode_that_never_lands_gives_up_and_says_where_the_words_are(self):
        self.h.press().speak().release()
        with mock.patch.object(type(self.h.session), "busy",
                               property(lambda _s: True)):
            self.h.pill._ptt_wait -= ui.PTT_PASTE_WAIT_SEC + 1
            self.h.frame()
        self.assertEqual(self.h.pasted, [])
        self.assertIsNone(self.h.pill._ptt_wait)
        self.assertIn("Press Send", " ".join(self.h.notes))

    def test_and_does_not_paste_it_late_when_it_finally_arrives(self):
        # A paste a minute after the gesture lands in whatever window the user has moved
        # to since, which is worse than not pasting at all.
        self.h.press().speak().release()
        with mock.patch.object(type(self.h.session), "busy",
                               property(lambda _s: True)):
            self.h.pill._ptt_wait -= ui.PTT_PASTE_WAIT_SEC + 1
            self.h.frame()
        self.h.decode("very late").frame()
        self.assertEqual(self.h.pasted, [])

    def test_a_hold_whose_release_never_arrives_stops_on_its_own(self):
        # A hook the OS dropped for overrunning `LowLevelHooksTimeout`, a lock screen, an
        # RDP session taking the keyboard. Without this the microphone stays open.
        self.h.press().speak(2.0)
        self.h.pill._ptt_since -= ui.PTT_MAX_HOLD_SEC + 1
        self.h.frame()
        self.assertFalse(self.h.mic.active)
        self.assertIsNone(self.h.pill._ptt_since)

    def test_and_keeps_what_was_said_rather_than_pasting_it(self):
        self.h.press().speak(2.0)
        self.h.pill._ptt_since -= ui.PTT_MAX_HOLD_SEC + 1
        self.h.frame()
        self.assertTrue(self.h.session._sent)
        self.h.decode("a long dictation").frame()
        self.assertEqual(self.h.pasted, [])
        self.assertIn("press Send", " ".join(self.h.notes))

    def test_an_ordinary_hold_is_nowhere_near_the_ceiling(self):
        # A guard on the number rather than on the branch: two minutes has to sit clear
        # of the longest hold anybody would make on purpose.
        self.h.press().speak(2.0)
        self.h.frame()
        self.assertTrue(self.h.mic.active)
        self.assertIsNotNone(self.h.pill._ptt_since)


class TestOneHoldOwnsOneSend(unittest.TestCase):
    """The collisions, which are the part of push-to-talk that is genuinely hard.

    There are four ways to send — the Send chip, the `send` hotkey, the spoken trigger
    routed as a `send` event, and converse's auto-ask countdown — and a release that has
    armed a paste is a fifth thing waiting to do the same job. Any two of them firing for
    one utterance is a double paste into somebody's editor.

    The rule is that a hold owns *one* send and whoever gets there first has it, and it
    is enforced at the single point all five have in common rather than at five guards
    that would have to be kept in step. These are the tests that say so.
    """

    def setUp(self):
        self.h = Harness()
        self.addCleanup(self.h.session.close)

    def test_the_spoken_send_word_does_not_paste_twice(self):
        # The one the whole rule exists for. Hold the chord, say "…and that's the plan,
        # boom", let go: the trigger fires a send when the decode routes, while the
        # release is still waiting to fire its own.
        self.h.press().speak().release()
        self.h.decode("that's the plan")
        self.h.pill._send()          # the trigger, arriving as a `send` event
        self.h.frame()               # the wait, arriving one line later
        self.assertEqual(len(self.h.pasted), 1)

    def test_the_send_hotkey_during_the_wait_does_not_paste_twice(self):
        # Somebody who does not yet trust the release and reaches for ctrl+alt+enter.
        self.h.press().speak().release()
        self.h.decode("said once")
        self.h.pill._send()
        self.h.frame()
        self.assertEqual(self.h.pasted, [("said once", False)])

    def test_whoever_gets_there_first_has_it_and_the_wait_stands_down(self):
        self.h.press().speak().release()
        self.assertIsNotNone(self.h.pill._ptt_wait)
        self.h.decode("first past the post")
        self.h.pill._send()
        self.assertIsNone(self.h.pill._ptt_wait)

    def test_clearing_the_draft_cancels_a_paste_that_has_not_landed(self):
        # The nastiest one to leave running: the draft is cleared, the decode lands a
        # second later and refills it, and the wait pastes into the user's window the
        # words they just pressed a key to stop. Clear means clear.
        self.h.press().speak().release()
        self.h.pill._clear()
        self.h.decode("what they cancelled").frame()
        self.assertEqual(self.h.pasted, [])

    def test_switching_mode_cancels_it_rather_than_translating_it(self):
        # A wait armed in dictate pastes into a window; fired in converse it would ask a
        # CLI. The switch is one keypress away at all times. Driven through the `mode`
        # dispatch rather than by clearing the flag here, which would be a test asserting
        # what it had just done itself.
        self.h.press().speak().release()
        self.assertIsNotNone(self.h.pill._ptt_wait)
        self.h.key("mode")
        self.assertIsNone(self.h.pill._ptt_wait)
        self.h.decode("asked, not pasted").frame()
        self.assertEqual(self.h.pasted, [])

    def test_the_toggle_hotkey_mid_hold_keeps_the_words(self):
        # `pause()` bumps the capture generation, which is how a deliberate stop refuses
        # a decode from before it — and the utterance being spoken *right now* is exactly
        # what that would refuse. The hold is ended first, so it is committed.
        self.h.press().speak(2.0)
        before = self.h.session._capture_generation
        self.h.pill._toggle()
        self.assertEqual(self.h.session._capture_generation, before)
        self.assertTrue(self.h.session._sent)

    def test_and_does_not_paste_them_because_a_toggle_is_not_a_release(self):
        # The user reached for the other control mid-sentence. Pasting on their behalf
        # is not what either gesture asked for.
        self.h.press().speak(2.0)
        self.h.pill._toggle()
        self.h.decode("mid sentence").frame()
        self.assertEqual(self.h.pasted, [])
        self.assertEqual(self.h.session.draft.text, "mid sentence")

    def test_the_toggle_does_not_then_pause_the_session_it_just_stopped(self):
        # The `return` in `_toggle`. Falling through would do the generation bump the
        # branch above exists to avoid.
        self.h.press().speak(2.0)
        self.h.pill._toggle()
        self.assertIsNone(self.h.pill._ptt_since)
        self.assertFalse(self.h.mic.active)

    def test_the_mode_switch_really_does_clear_it_in_the_app(self):
        # `Harness.dispatch` mirrors `Pill._frame`, so the test above could pass on the
        # mirror alone. This is the tripwire on the original — the same shape
        # `test_chord.py` uses for the four chord words, and for the same reason.
        ui_src = (Path(__file__).resolve().parent.parent
                  / "flow" / "ui.py").read_text(encoding="utf-8")
        branch = ui_src[ui_src.index('elif name == "mode":'):]
        branch = branch[:branch.index('elif name == "quit"')]
        self.assertIn("_ptt_wait = None", branch)

    def test_send_and_clear_clear_it_at_their_own_single_choke_point(self):
        # Same tripwire, for the two methods every other send and stop path funnels
        # through. One line in each is what makes four collisions impossible rather
        # than four guards that would have to be kept in step.
        ui_src = (Path(__file__).resolve().parent.parent
                  / "flow" / "ui.py").read_text(encoding="utf-8")
        for name in ("_send", "_clear"):
            with self.subTest(method=name):
                body = ui_src[ui_src.index(f"    def {name}(self"):]
                body = body[:body.index("\n    def ", 10)]
                self.assertIn("self._ptt_wait = None", body)

    def test_a_hold_is_refused_while_the_hand_editor_is_open(self):
        # `_pump_audio` throws away every block while `editing` is true, so a hold here
        # would open the microphone, capture nothing, and end with no paste and no
        # explanation — the silent deafness invariant 4 forbids.
        self.h.session.editing = True
        self.h.press()
        self.assertIsNone(self.h.pill._ptt_since)
        self.assertEqual(self.h.mic.starts, 0)
        self.assertIn("editing", " ".join(self.h.notes))


class TestHoldingThePillIsPushToTalkWithoutAHotkey(unittest.TestCase):
    """The gesture for every platform that has no chord — which is every platform but one.

    `Chord` is a `WH_KEYBOARD_LL` hook and there is no such thing off Windows, so Flow
    Lite has never had push-to-talk. It does not need a hotkey to: the button can be a
    window Flow already draws, which costs no Accessibility permission, no Input
    Monitoring, and no signed bundle to ask for them from. That is the one thing Lite
    can do that a native app driving a system hotkey cannot.

    Three gestures now share the left button, and each test below is one of them, plus
    the bug that fell out of fixing the arrangement.
    """

    def setUp(self):
        self.h = Harness()
        self.addCleanup(self.h.session.close)
        self.p = self.h.pill
        self.timers = []
        self.p.after = lambda ms, fn: self.timers.append(fn) or len(self.timers)
        self.p.after_cancel = lambda tid: self.timers.__setitem__(tid - 1, None)
        self.p._toggle = mock.Mock(name="toggle")

    def at(self, x=0, y=0):
        return mock.Mock(x_root=x, y_root=y)

    def hold(self):
        """Let the pending hold timer fire, as Tk would after `PILL_HOLD_SEC`."""
        for fn in self.timers:
            if fn is not None:
                fn()

    def test_a_quick_click_still_toggles(self):
        # The gesture that was there first, and the one muscle memory depends on.
        self.p._on_press(self.at())
        self.p._on_release()
        self.p._toggle.assert_called_once()
        self.assertEqual(self.h.mic.starts, 0)

    def test_holding_it_starts_capturing_before_the_button_comes_up(self):
        # The whole difference between this and a long-click: capture has to start while
        # the user is still holding, because the hold *is* the utterance. Waiting for
        # the release to notice would record nothing at all.
        self.p._on_press(self.at())
        self.hold()
        self.assertTrue(self.h.mic.active)
        self.assertIsNotNone(self.p._ptt_since)

    def test_and_releasing_sends_what_was_said(self):
        self.p._on_press(self.at())
        self.hold()
        self.h.speak()
        self.p._on_release()
        self.h.decode("held the pill and spoke").frame()
        self.assertEqual(self.h.pasted, [("held the pill and spoke", False)])
        self.p._toggle.assert_not_called()

    def test_a_hold_never_also_toggles(self):
        # Both gestures on one button, so the release has to pick exactly one.
        self.p._on_press(self.at())
        self.hold()
        self.h.speak()
        self.p._on_release()
        self.p._toggle.assert_not_called()

    def test_dragging_the_pill_no_longer_toggles_listening(self):
        # The bug this arrangement fixes, and it predates hold-to-talk: `_toggle` was
        # bound to `<Button-1>`, which in Tk is the *press* — so every drag of the pill
        # armed or disarmed capture on the way past.
        self.p._on_press(self.at(0, 0))
        self.p._on_motion(self.at(60, 0))
        self.p._on_release()
        self.p._toggle.assert_not_called()

    def test_a_drag_does_not_start_an_utterance_either(self):
        self.p._on_press(self.at(0, 0))
        self.p._on_motion(self.at(60, 0))
        self.hold()
        self.assertEqual(self.h.mic.starts, 0)
        self.assertIsNone(self.p._ptt_since)

    def test_a_hand_that_is_merely_not_still_is_not_a_drag(self):
        # `PILL_DRAG_SLOP` exists because a hand resting on a mouse trembles, and a hold
        # that lost its nerve on one pixel would be a gesture nobody could rely on.
        self.p._on_press(self.at(0, 0))
        self.p._on_motion(self.at(ui.PILL_DRAG_SLOP, ui.PILL_DRAG_SLOP))
        self.hold()
        self.assertTrue(self.h.mic.active)

    def test_moving_while_talking_does_not_cancel_the_utterance(self):
        # Once capture is open the pointer is irrelevant: somebody talking into a held
        # pill may well move the mouse, and cancelling their sentence for it would be
        # the gesture betraying them.
        self.p._on_press(self.at(0, 0))
        self.hold()
        self.p._on_motion(self.at(400, 400))
        self.assertTrue(self.h.mic.active)
        self.h.speak()
        self.p._on_release()
        self.h.decode("still mine").frame()
        self.assertEqual(self.h.pasted, [("still mine", False)])

    def test_a_click_cancels_the_pending_hold_rather_than_leaving_it_armed(self):
        # Otherwise the timer fires after the button is already up and opens a
        # microphone nobody is holding — the exact failure `PTT_MAX_HOLD_SEC` exists to
        # catch, arriving by a route it should never have to.
        self.p._on_press(self.at())
        self.p._on_release()
        self.hold()
        self.assertEqual(self.h.mic.starts, 0)

    def test_it_works_in_lite_where_there_is_no_chord_at_all(self):
        # The point of the whole gesture. Lite copies instead of pasting — `_send`
        # already knows — so the hold ends on the clipboard with nothing granted but
        # the microphone.
        h = Harness(lite=True)
        self.addCleanup(h.session.close)
        timers = []
        h.pill.after = lambda ms, fn: timers.append(fn) or len(timers)
        h.pill.after_cancel = lambda tid: timers.__setitem__(tid - 1, None)
        h.pill._on_press(mock.Mock(x_root=0, y_root=0))
        for fn in timers:
            if fn is not None:
                fn()
        self.assertTrue(h.mic.active)
        h.speak()
        h.pill._on_release()
        h.decode("onto the clipboard").frame()
        self.assertEqual(h.pasted, [])   # copied, not pasted


class TestItFailsTheWayTheRestOfTheSurfaceDoes(unittest.TestCase):
    def test_a_microphone_that_will_not_open_leaves_the_pill_disarmed(self):
        # `_toggle` already refuses to show a green pill over a dead capture, and the
        # chord must tell the same truth — with the added stake that under push-to-talk
        # the user is about to speak into it.
        h = Harness()
        self.addCleanup(h.session.close)
        with mock.patch.object(h.mic, "start", side_effect=OSError("device in use")):
            h.press()
        self.assertFalse(h.pill.armed)
        self.assertIsNone(h.pill._ptt_since)
        self.assertTrue(h.pill._flash)

    def test_and_the_release_afterwards_is_a_no_op(self):
        # There is no hold to end. Without the `_ptt_since` guard this would commit an
        # empty utterance and stop a microphone that never started.
        h = Harness()
        self.addCleanup(h.session.close)
        with mock.patch.object(h.mic, "start", side_effect=OSError("device in use")):
            h.press()
        h.release()
        self.assertEqual(h.mic.stops, 0)

    def test_lite_copies_instead_of_pasting(self):
        # The gesture is the same; where the words go is `_send`'s business, and it
        # already knows. Asserted so the chord does not grow its own idea of Lite.
        h = Harness(lite=True)
        self.addCleanup(h.session.close)
        h.press().speak().release()
        h.decode("into the clipboard").frame()
        self.assertEqual(h.pasted, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
