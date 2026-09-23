"""Ask's own hold: ctrl+alt+win asks, whatever the pill is on.

Decision 4 of 2026-09-22, built on 2026-09-23 (decisions.md, "Ask's own hold"): the keys
Wispr Flow users already hold for its command mode. The hand picks the side, so the
pill's tint no longer has to be read before a hold — the talk keys dictate and the Ask
keys ask.

Four things are pinned here. **One hook**: the Ask chord rides the talk chord's
`WH_KEYBOARD_LL` hook (`Chord.riders`) rather than installing a second one on the input
path of every keystroke. **The overlap**: ctrl+win is inside ctrl+alt+win, and the
bottom row reads Ctrl, Win, Alt — so the talk chord often forms first, and has to give
way without a flicker. **The launch**: every way the chord is refused says so in the
startup block, and the talk chord's own keys are refused by name. **The surfaces**: the
compact pill and the Classic one both switch sides, and an Ask hold that was refused
never ends somebody's hands-free utterance.
"""

import io
import queue
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

if sys.platform != "win32":  # pragma: no cover - the CI legs that are not Windows
    raise unittest.SkipTest("Windows-only: flow.hotkey binds user32 at import")

import flow.__main__ as main_mod  # noqa: E402
import flow.help as help_mod  # noqa: E402
import flow.hotkey as hotkey  # noqa: E402
import flow.ui as ui  # noqa: E402
import flow.ui_compact as uc  # noqa: E402
from flow.hotkey import (  # noqa: E402
    ASK_ACTIONS, VK_LCONTROL, VK_LMENU, VK_LWIN, Chord, Hotkeys, parse_chord,
)
from flow.profile import ASK_CHORD_DEFAULT, CHORD_DEFAULT, Profile  # noqa: E402
from flow.session import CONVERSE, DICTATE, REFINE, State  # noqa: E402
from test_chord import _drained, _Keyboard  # noqa: E402
from test_ui_compact import panel_pill  # noqa: E402

VK_A = 0x41


def _pair(gesture="hold"):
    """The shipped pair: ctrl+win hosting ctrl+alt+win, on one queue."""
    presses = queue.Queue()
    talk = Chord(presses, frozenset({"ctrl", "win"}), gesture=gesture)
    ask = Chord(presses, frozenset({"ctrl", "alt", "win"}), gesture="hold", **ASK_ACTIONS)
    talk.riders.append(ask)
    return talk, ask, presses


class TestAOneHookFeedsBothChords(unittest.TestCase):
    """ctrl+alt+win rides ctrl+win's hook: one callback on every keystroke, not two."""

    def test_ctrl_alt_win_asks_and_nothing_else(self):
        talk, _ask, presses = _pair()
        keys = _Keyboard(talk).down(VK_LCONTROL, VK_LMENU, VK_LWIN)
        self.assertEqual(_drained(presses), ["warm", "ask"])
        keys.up(VK_LWIN, VK_LMENU, VK_LCONTROL)
        self.assertEqual(_drained(presses), ["ask-end"])

    def test_the_talk_keys_alone_still_talk(self):
        talk, _ask, presses = _pair()
        _Keyboard(talk).down(VK_LCONTROL, VK_LWIN).up(VK_LWIN, VK_LCONTROL)
        self.assertEqual(_drained(presses), ["warm", "talk", "talk-end"])

    def test_pressed_through_the_talk_keys_the_talk_hold_gives_way(self):
        # Ctrl, Win, Alt — the bottom row's own order. ctrl+win forms first and
        # starts a hold; Alt breaks it (never a paste) and forms ctrl+alt+win, in
        # that order on the queue, because the host is fed before its riders.
        talk, _ask, presses = _pair()
        keys = _Keyboard(talk).down(VK_LCONTROL, VK_LWIN, VK_LMENU)
        self.assertEqual(_drained(presses),
                         ["warm", "talk", "talk-break", "warm", "ask"])
        keys.up(VK_LMENU)
        self.assertEqual(_drained(presses), ["ask-end"])
        # Ctrl and Win still down: the talk chord formed long ago and never re-forms.
        keys.up(VK_LWIN, VK_LCONTROL)
        self.assertEqual(_drained(presses), [])

    def test_a_toggle_talk_chord_does_not_toggle_under_the_ask_keys(self):
        talk, _ask, presses = _pair(gesture="toggle")
        _Keyboard(talk).down(VK_LCONTROL, VK_LMENU, VK_LWIN).up(
            VK_LWIN, VK_LMENU, VK_LCONTROL)
        self.assertEqual(_drained(presses), ["warm", "ask", "ask-end"])

    def test_a_third_key_breaks_the_ask_hold_too(self):
        talk, _ask, presses = _pair()
        _Keyboard(talk).down(VK_LCONTROL, VK_LMENU, VK_LWIN, VK_A)
        self.assertEqual(_drained(presses), ["warm", "ask", "ask-break"])

    def test_a_rider_never_installs_a_hook(self):
        _talk, ask, _presses = _pair()
        self.assertFalse(ask.installed)
        self.assertIsNone(ask._hook)


class TestBTheHookKnowsWhetherAKeyWasTyped(unittest.TestCase):
    """`Chord.touched`: one boolean, for the correction after a Type paste."""

    def test_a_key_sets_it(self):
        talk, _ask, _presses = _pair()
        _Keyboard(talk).down(VK_A)
        self.assertIs(talk.touched, True)

    def test_modifiers_and_releases_do_not(self):
        talk, _ask, _presses = _pair()
        _Keyboard(talk).down(VK_LCONTROL, VK_LWIN).up(VK_LWIN, VK_LCONTROL)
        self.assertIs(talk.touched, False)

    def test_flows_own_keystrokes_do_not(self):
        # Every key `inject` sends carries INPUT_MARK: a Ctrl-V, a Backspace. Anybody
        # else's injected key — an on-screen keyboard, a text expander — does count.
        from flow.inject import INPUT_MARK

        talk, _ask, _presses = _pair()
        _Keyboard(talk, extra=INPUT_MARK).down(VK_A)
        self.assertIs(talk.touched, False)
        _Keyboard(talk, extra=0x1234).down(VK_A)
        self.assertIs(talk.touched, True)

    def test_every_key_flow_sends_carries_the_mark(self):
        from flow import inject

        for vk in (inject.VK_CONTROL, inject.VK_V, inject.VK_BACK, inject.VK_RETURN):
            for up in (False, True):
                with self.subTest(vk=vk, up=up):
                    self.assertEqual(inject._key(vk, up=up).u.ki.dwExtraInfo,
                                     inject.INPUT_MARK)

    def test_it_learns_no_more_about_a_key_than_that_one_went_down(self):
        # The privacy line of `test_chord`'s D class, for the new field: two different
        # keys leave the two chords in identical states.
        states = []
        for vk in (VK_A, 0x44):
            talk, _ask, _presses = _pair()
            _Keyboard(talk).down(vk).up(vk)
            states.append((talk.touched, talk._other))
        self.assertEqual(states[0], states[1])


class TestCHotkeysOwnsTheTeardownOfBoth(unittest.TestCase):

    def test_the_hook_is_whichever_chord_installed_one(self):
        hk = Hotkeys(hotkey.DEFAULT_BINDINGS)
        talk, ask, _presses = _pair()
        hk.chord, hk.ask_chord = talk, ask
        self.assertIsNone(hk.hook)
        talk.installed = True
        self.assertIs(hk.hook, talk)
        # With the talk chord off, the Ask chord has a hook of its own.
        hk.chord = None
        ask.installed = True
        self.assertIs(hk.hook, ask)

    def test_stop_stops_both(self):
        hk = Hotkeys(hotkey.DEFAULT_BINDINGS)
        hk.chord, hk.ask_chord = mock.Mock(), mock.Mock()
        hk.stop()
        hk.chord.stop.assert_called_once_with()
        hk.ask_chord.stop.assert_called_once_with()


class TestDTheLaunchSaysWhatHappened(unittest.TestCase):
    """`__main__._ask_chord`: every path out prints a line, `_chord`'s contract."""

    def _launch(self, ask_chord=ASK_CHORD_DEFAULT, talk=True, start=True):
        profile = mock.Mock(ask_chord=ask_chord)
        hotkeys = mock.Mock(presses=queue.Queue())
        hotkeys.chord = (Chord(hotkeys.presses, frozenset({"ctrl", "win"}))
                         if talk else None)
        hotkeys.ask_chord = None
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.object(Chord, "start",
                                                     return_value=start) as started:
            chord = main_mod._ask_chord(profile, hotkeys, Chord, parse_chord,
                                        hotkey._echo, ASK_CHORD_DEFAULT)
        return chord, hotkeys, out.getvalue(), started

    def test_it_rides_the_talk_chord(self):
        chord, hotkeys, out, started = self._launch()
        self.assertIsNotNone(chord)
        self.assertIn(chord, hotkeys.chord.riders)
        self.assertIs(hotkeys.ask_chord, chord)
        started.assert_not_called()
        self.assertIn("chord   ask      ctrl+alt+win  (hold to ask", out)

    def test_it_is_always_a_hold(self):
        chord, _hotkeys, _out, _started = self._launch()
        self.assertEqual(chord.gesture, "hold")
        self.assertEqual((chord.action, chord.end_action, chord.break_action),
                         ("ask", "ask-end", "ask-break"))

    def test_without_a_talk_chord_it_hooks_on_its_own(self):
        chord, hotkeys, out, started = self._launch(talk=False)
        started.assert_called_once_with()
        self.assertIs(hotkeys.ask_chord, chord)
        self.assertIn("chord   ask", out)

    def test_a_refused_hook_is_said(self):
        chord, hotkeys, out, _started = self._launch(talk=False, start=False)
        self.assertIsNone(chord)
        self.assertIsNone(hotkeys.ask_chord)
        self.assertIn(hotkey.ASK_CHORD_UNAVAILABLE, out)

    def test_empty_is_off_and_quiet(self):
        chord, hotkeys, out, _started = self._launch(ask_chord="")
        self.assertIsNone(chord)
        self.assertEqual(hotkeys.chord.riders, [])
        self.assertEqual(out, "")

    def test_the_talk_keys_are_refused_by_name(self):
        chord, hotkeys, out, _started = self._launch(ask_chord="win+ctrl")
        self.assertIsNone(chord)
        self.assertEqual(hotkeys.chord.riders, [])
        self.assertIn("ask_chord in profile.json ignored", out)
        self.assertIn("those are the talk keys", out)

    def test_a_chord_that_cannot_be_read_is_said(self):
        chord, _hotkeys, out, _started = self._launch(ask_chord="ctrl+q")
        self.assertIsNone(chord)
        self.assertIn("ask_chord in profile.json ignored", out)

    def test_the_default_is_the_wispr_command_mode_keys(self):
        self.assertEqual(parse_chord(ASK_CHORD_DEFAULT)[0],
                         frozenset({"ctrl", "alt", "win"}))
        self.assertNotEqual(parse_chord(ASK_CHORD_DEFAULT)[0],
                            parse_chord(CHORD_DEFAULT)[0])


class TestEOffMeansOffAcrossARestart(unittest.TestCase):
    """The empty string turns a chord off — and used to be read back as the default."""

    def _load(self, **fields):
        import json
        import tempfile

        path = Path(tempfile.mkdtemp()) / "profile.json"
        path.write_text(json.dumps({"schema": 1, **fields}), encoding="utf-8")
        p = Profile(path)
        p.load()
        return p

    def test_an_empty_talk_chord_stays_off(self):
        p = self._load(chord="")
        self.assertEqual(p.chord, "")
        self.assertNotIn("chord", p.faults)

    def test_an_empty_ask_chord_stays_off(self):
        p = self._load(ask_chord="")
        self.assertEqual(p.ask_chord, "")
        self.assertNotIn("ask_chord", p.faults)

    def test_absent_is_the_shipped_keys(self):
        p = self._load()
        self.assertEqual((p.chord, p.ask_chord), (CHORD_DEFAULT, ASK_CHORD_DEFAULT))

    def test_a_wrong_type_is_named(self):
        p = self._load(ask_chord=3)
        self.assertEqual(p.ask_chord, ASK_CHORD_DEFAULT)
        self.assertIn("ask_chord", p.faults)

    def test_a_save_writes_it_back(self):
        import json

        p = self._load(ask_chord="")
        p.save()
        self.assertEqual(json.loads(p.path.read_text(encoding="utf-8"))["ask_chord"], "")


def _moving(p):
    """Make the Mock session's mode follow `toggle_mode(to=...)`, as the real one does."""
    def toggle(to=None):
        p.session.mode = to
        return to
    p.session.toggle_mode.side_effect = toggle
    p.session.provider = "claude"
    return p


class TestFTheCompactPillSwitchesSides(unittest.TestCase):
    """The hand picks the side: Ask keys to Ask, talk keys back to where they came from."""

    def _pill(self, mode=DICTATE, names=()):
        p = _moving(panel_pill(mode=mode))
        p.hotkeys = mock.Mock()
        p.hotkeys.drain.return_value = list(names)
        return p

    def test_the_ask_keys_ask_from_type(self):
        p = self._pill(DICTATE, ["warm", "ask"])
        p._drain_hotkeys()
        self.assertEqual(p.session.mode, CONVERSE)
        p.session.talk_start.assert_called_once_with()
        self.assertTrue(p._panel_open)
        self.assertTrue(p._ask_hold)
        self.assertEqual(p._dictate_side, DICTATE)

    def test_their_release_asks(self):
        p = self._pill(DICTATE, ["warm", "ask"])
        p._drain_hotkeys()
        p.session.talk_end.return_value = True
        p.hotkeys.drain.return_value = ["ask-end"]
        p._drain_hotkeys()
        self.assertTrue(p._ask_pending)
        self.assertFalse(p._send_pending)
        self.assertFalse(p._ask_hold)

    def test_the_talk_keys_go_back_to_refine_when_that_is_where_ask_came_from(self):
        p = self._pill(REFINE, ["warm", "ask"])
        p._drain_hotkeys()
        p.hotkeys.drain.return_value = ["ask-end"]
        p._drain_hotkeys()
        self.assertEqual(p._dictate_side, REFINE)
        p.hotkeys.drain.return_value = ["warm", "talk"]
        p._drain_hotkeys()
        # Still on Ask inside the settle — the Ask keys may be on their way.
        self.assertEqual(p.session.mode, CONVERSE)
        p._side_since -= uc.SIDE_SETTLE_SEC
        p._pump_side()
        self.assertEqual(p.session.mode, REFINE)
        self.assertEqual(p._dictate_side, DICTATE)

    def test_from_an_ask_tapped_to_by_hand_the_talk_keys_go_to_type(self):
        p = self._pill(CONVERSE, ["warm", "talk"])
        p._drain_hotkeys()
        p._side_since -= uc.SIDE_SETTLE_SEC
        p._pump_side()
        self.assertEqual(p.session.mode, DICTATE)

    def test_the_talk_hold_on_ask_leaves_the_answer_alone_while_it_settles(self):
        p = self._pill(CONVERSE, ["warm", "talk"])
        p._panel_open = True
        p._panel_heard, p._panel_result = "the question", "the answer"
        p._drain_hotkeys()
        p.session.talk_start.assert_called_once_with()
        self.assertTrue(p._panel_open)
        self.assertEqual(p._panel_result, "the answer")
        self.assertFalse(p._hold_fresh)
        # A partial of this hold is dictation, and Ask's heard block is not its.
        from flow.session import Event
        p.session.events.return_value = [Event("partial", "some words")]
        p._pump_events()
        self.assertEqual(p._panel_heard, "the question")

    def test_pressed_through_from_ask_it_never_leaves_ask(self):
        # Ctrl, Win, Alt with the pill on Ask: talk, then break, then ask.
        p = self._pill(CONVERSE, ["warm", "talk", "talk-break", "warm", "ask"])
        p._drain_hotkeys()
        self.assertEqual(p.session.mode, CONVERSE)
        p.session.toggle_mode.assert_not_called()
        self.assertTrue(p._ask_hold)
        self.assertIsNone(p._side_since)

    def test_a_quick_talk_hold_from_ask_still_dictates(self):
        p = self._pill(CONVERSE, ["warm", "talk"])
        p._drain_hotkeys()
        p.session.talk_end.return_value = True
        p.hotkeys.drain.return_value = ["talk-end"]
        p._drain_hotkeys()
        # The side changed before the release armed its send, so it is a paste.
        self.assertEqual(p.session.mode, DICTATE)
        self.assertTrue(p._send_pending)
        self.assertFalse(p._ask_pending)

    def test_with_no_agent_cli_the_ask_keys_say_so_and_hold_nothing(self):
        p = self._pill(DICTATE, ["warm", "ask"])
        p.session.provider = ""
        p._say = mock.Mock()
        p._drain_hotkeys()
        p.session.talk_start.assert_not_called()
        self.assertEqual(p.session.mode, DICTATE)
        self.assertIn("agent CLI", p._say.call_args[0][0])
        # And their release ends nothing — a hands-free utterance may be under way.
        p.hotkeys.drain.return_value = ["ask-end"]
        p._drain_hotkeys()
        p.session.talk_end.assert_not_called()


class TestGTheClassicPillSwitchesSidesToo(unittest.TestCase):

    def _pill(self, mode=DICTATE, names=()):
        from test_pill import pill

        p = _moving(pill(mode=mode))
        p.hotkeys = mock.Mock()
        p.hotkeys.drain.return_value = list(names)
        p._talk_start = mock.Mock()
        p._talk_end = mock.Mock()
        # `front` is the card or the bubble, whichever the mode wears: one Mock for both.
        p.card = p.bubble = mock.Mock()
        return p

    def test_the_ask_keys_ask(self):
        p = self._pill(DICTATE, ["warm", "ask"])
        p._talk_start.side_effect = lambda: setattr(p, "_ptt_since", 1.0)
        p._drain_hotkeys()
        self.assertEqual(p.session.mode, CONVERSE)
        p._talk_start.assert_called_once_with()
        p.hotkeys.drain.return_value = ["ask-end"]
        p._drain_hotkeys()
        p._talk_end.assert_called_once_with(send=True)

    def test_the_talk_keys_come_back_after_the_settle(self):
        p = self._pill(CONVERSE, ["warm", "talk"])
        p._drain_hotkeys()
        self.assertEqual(p.session.mode, CONVERSE)
        p._side_since -= ui.SIDE_SETTLE_SEC
        p._pump_side()
        self.assertEqual(p.session.mode, DICTATE)

    def test_no_cli_is_a_note(self):
        p = self._pill(DICTATE, ["ask"])
        p.session.provider = ""
        p._drain_hotkeys()
        p._talk_start.assert_not_called()
        self.assertIn("agent CLI", p.bubble.note.call_args[0][0])


class TestHTheSheetAndHomeNameTheKeys(unittest.TestCase):

    def test_the_help_sheet_lists_both_chords(self):
        hk = mock.Mock(chosen={}, failed=[])
        hk.chord = mock.Mock(action="talk")
        hk.chord.describe.return_value = "ctrl+win"
        hk.ask_chord = mock.Mock(action="ask")
        hk.ask_chord.describe.return_value = "ctrl+alt+win"
        rows = help_mod._hotkey_rows(hk)
        self.assertEqual(rows[0][1], "ctrl+win (held)")
        self.assertEqual(rows[1][1], "ctrl+alt+win (held)")
        self.assertIn("ask", rows[1][2])

    def test_home_names_the_ask_keys(self):
        from flow.home.api import Api

        api = Api.__new__(Api)
        api.home = mock.Mock(hotkeys=mock.Mock(chosen={}))
        api.home.hotkeys.chord.describe.return_value = "ctrl+win"
        api.home.hotkeys.ask_chord.describe.return_value = "ctrl+alt+win"
        self.assertEqual(api._shortcut_names()["ask"], "ctrl+alt+win")


class TestIFlowHomeSetsTheAskKeys(unittest.TestCase):
    """Settings' Ask keys box: judged, empty for off, never the talk keys."""

    def setUp(self):
        from flow.home import demo

        self.home, self.session = demo.build()

    def tearDown(self):
        self.home.close()

    def _api(self):
        from flow.home.api import Api

        return Api(self.home)

    def test_the_settings_page_shows_them(self):
        page = self._api().settings({})
        self.assertEqual(page["shortcuts"]["ask_chord"]["describe"], "ctrl+alt+win")

    def test_saving_new_keys(self):
        api = self._api()
        api.set_ask_chord({"keys": "Ctrl+Shift+Win"})
        self.assertEqual(self.home.profile.ask_chord, "ctrl+shift+win")

    def test_empty_turns_it_off(self):
        api = self._api()
        api.set_ask_chord({"keys": ""})
        self.assertEqual(self.home.profile.ask_chord, "")

    def test_the_talk_keys_are_refused(self):
        from flow.home.api import ApiError

        api = self._api()
        with self.assertRaises(ApiError) as caught:
            api.set_ask_chord({"keys": "win+ctrl"})
        self.assertIn("talk keys", str(caught.exception))

    def test_and_the_talk_keys_cannot_become_the_ask_keys(self):
        from flow.home.api import ApiError

        api = self._api()
        with self.assertRaises(ApiError) as caught:
            api.set_chord({"keys": "ctrl+alt+win"})
        self.assertIn("Ask keys", str(caught.exception))

    def test_a_chord_that_cannot_be_read_is_refused(self):
        from flow.home.api import ApiError

        with self.assertRaises(ApiError):
            self._api().set_ask_chord({"keys": "ctrl"})


if __name__ == "__main__":
    unittest.main()
