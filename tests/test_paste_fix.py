"""Correcting a Type paste by voice (decisions.md 2026-09-23, "Correcting a Type paste").

Type pastes on the release and clears the draft, so a correction said in the next hold
used to find nothing to act on and was pasted as words — "scratch that" typed into
somebody's message. Now the words a Type paste put in a window stay changeable while
Flow can know they are still where it put them, and a change is made the one way Flow
can make one in another program: its own characters taken back with Backspace and the
corrected ones pasted after them, in one burst.

Five layers, one class each: the grammar (`edits.whole_undo`), the keys (`inject`), the
routing and the records (`Session`), the guards and the timing (`CompactPill`), and the
bounds that keep a count of Backspaces honest.
"""

import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

if sys.platform != "win32":  # pragma: no cover - the CI legs that are not Windows
    raise unittest.SkipTest("Windows-only: flow.inject binds user32 at import")

import flow.inject as inject  # noqa: E402
import flow.session as session_mod  # noqa: E402
import flow.ui_compact as uc  # noqa: E402
from flow.edits import whole_undo  # noqa: E402
from flow.history import History  # noqa: E402
from flow.inject import Target, backspaces, take_warnings  # noqa: E402
from flow.profile import Profile  # noqa: E402
from flow.session import (  # noqa: E402
    CONVERSE, CORRECT_MAX_CHARS, CORRECT_WINDOW_SEC, DICTATE, REFINE, Session, State,
    paste_fits,
)
from clipboard_env import sealed_clipboard  # noqa: E402
from test_inject_target import all_inserted, only  # noqa: E402
from test_session import FakeMic, FakeTranscriber  # noqa: E402
from test_ui_compact import pill  # noqa: E402

#: The keys class calls the real `inject.paste()`, which enumerates the machine's
#: clipboard to warn about an image a paste would destroy. Unsealed, this module went red
#: on the day an image was on the clipboard (see `clipboard_env.py`).
_CLIPBOARD = sealed_clipboard()


def setUpModule():
    _CLIPBOARD.start()


def tearDownModule():
    _CLIPBOARD.stop()

WINDOW = 0x51C
EDITOR = Target("Chrome_WidgetWin_1", "slack.exe")


class TestAOnlyTheWholeUndoTakesAPasteBack(unittest.TestCase):
    """In a draft "never mind the weather" costs an undo on screen; here, somebody's text."""

    def test_the_verbs_alone(self):
        for said in ("Scratch that.", "scratch that", "Undo.", "undo that", "Never mind.",
                     "Okay, scratch that.", "Sorry, strike that", "forget that!"):
            with self.subTest(said=said):
                self.assertTrue(whole_undo(said))

    def test_not_the_front_of_a_sentence(self):
        for said in ("Never mind the weather, let's go.", "Undo the last migration.",
                     "Scratch that itch", "forget that meeting"):
            with self.subTest(said=said):
                self.assertFalse(whole_undo(said))

    def test_a_mishearing_counts_through_the_alias_table(self):
        self.assertTrue(whole_undo("Scratch hat."))
        self.assertTrue(whole_undo("under that"))

    def test_never_through_an_edit_distance_guess(self):
        # `plan()`'s rule for undo: no target to check a guess against.
        self.assertFalse(whole_undo("Scratch bat."))


class TestBTheKeysCountTheirWayBack(unittest.TestCase):
    """`inject.backspaces` and the one-burst take-back."""

    def test_one_backspace_a_character(self):
        self.assertEqual(backspaces("Meet on Tuesday."), 16)
        self.assertEqual(backspaces(""), 0)

    def test_a_line_break_is_one_however_it_was_stored(self):
        self.assertEqual(backspaces("a\nb"), 3)
        self.assertEqual(backspaces("a\r\nb"), 3)

    def test_what_no_count_fits_is_refused(self):
        for text in ("thumbs \U0001F44D", "café", "a‍b", "col\tumn", "a\rb"):
            with self.subTest(text=repr(text)):
                self.assertIsNone(backspaces(text))

    def test_an_accent_that_is_one_character_is_fine(self):
        self.assertEqual(backspaces("café"), 4)

    def _paste(self, text, remove, target=EDITOR, send=all_inserted):
        take_warnings()
        with mock.patch("flow.inject.resolve", return_value=target), \
             mock.patch("flow.inject.get_clipboard_text", return_value=None), \
             mock.patch("flow.inject.set_clipboard_text", return_value=True) as put, \
             mock.patch("flow.inject._send", side_effect=send) as sent:
            ok = inject.paste(text, restore_clipboard=False, remove=remove)
        return ok, put, sent, take_warnings()

    def test_the_take_back_rides_in_front_of_the_ctrl_v_in_one_call(self):
        ok, put, sent, warnings = self._paste("uesday.", "hursday.")
        self.assertTrue(ok)
        self.assertEqual(warnings, [])
        self.assertEqual(sent.call_count, 1)
        events = sent.call_args.args
        self.assertEqual(len(events), 2 * 8 + inject.PASTE_KEYS)
        vks = [e.u.ki.wVk for e in events]
        self.assertEqual(vks[:16], [inject.VK_BACK] * 16)
        self.assertEqual(vks[16:], [inject.VK_CONTROL, inject.VK_V, inject.VK_V,
                                    inject.VK_CONTROL])
        self.assertEqual(put.call_args.args[0], "uesday.")

    def test_taking_back_alone_never_touches_the_clipboard(self):
        ok, put, sent, _warnings = self._paste("", "Hello there.")
        self.assertTrue(ok)
        put.assert_not_called()
        self.assertEqual(len(sent.call_args.args), 2 * 12)

    def test_what_cannot_be_counted_is_refused_before_a_key_moves(self):
        ok, put, sent, warnings = self._paste("x", "a \U0001F44D")
        self.assertFalse(ok)
        sent.assert_not_called()
        put.assert_not_called()
        self.assertTrue(warnings[0].startswith("not changed:"))

    def test_past_the_placeholder_line_is_refused(self):
        ok, _put, sent, warnings = self._paste("", "x" * (inject.TAKE_BACK_MAX + 1))
        self.assertFalse(ok)
        sent.assert_not_called()
        self.assertTrue(warnings[0].startswith("not changed:"))

    def test_a_short_count_is_not_changed(self):
        ok, _put, _sent, warnings = self._paste("uesday.", "hursday.", send=only(5))
        self.assertFalse(ok)
        self.assertTrue(any(w.startswith("not changed:") for w in warnings))

    def test_flow_in_front_is_not_changed(self):
        flow = Target("TkTopLevel", "python.exe", is_flow=True)
        ok, _put, sent, warnings = self._paste("", "Hello.", target=flow)
        self.assertFalse(ok)
        sent.assert_not_called()
        self.assertTrue(warnings[0].startswith("not changed:"))

    def test_the_bound_is_the_sessions_bound(self):
        # One number on both sides of the seam: what the session keeps changeable is
        # exactly what the keys will take back.
        self.assertEqual(inject.TAKE_BACK_MAX, CORRECT_MAX_CHARS)


def _session(history=None, profile=None):
    s = Session(asr=FakeTranscriber([]), mic=FakeMic(), history=history, profile=profile)
    s.events()  # start clean
    return s


def _kept():
    folder = Path(tempfile.mkdtemp())
    prof = types.SimpleNamespace(history="keep", history_days=30)
    return History(folder / "history.jsonl", prof)


def _fix(s):
    """Make the change the last `retype` announced, as a surface would, successfully."""
    fix = s.take_paste_fix()
    assert fix is not None, "no change was announced"
    s.paste_fixed(fix)
    return fix


class TestCTheSessionRoutesACorrectionToThePaste(unittest.TestCase):

    def test_a_type_paste_is_changeable(self):
        s = _session()
        s.delivered("Meet on Tuesday.", window=WINDOW)
        run = s.paste_run
        self.assertIsNotNone(run)
        self.assertEqual(run.window, WINDOW)
        self.assertEqual(run.top.text, "Meet on Tuesday.")

    def test_a_change_is_the_fewest_keys(self):
        s = _session()
        s.delivered("Meet on Tuesday.", window=WINDOW)
        s._route("change Tuesday to Thursday")
        kinds = [e.kind for e in s.events()]
        self.assertIn("retype", kinds)
        fix = s.take_paste_fix()
        self.assertEqual((fix.remove, fix.insert), ("uesday.", "hursday."))
        self.assertEqual(fix.after, "Meet on Thursday.")
        # Nothing was appended: the correction is not dictation.
        self.assertEqual(s.draft.text, "")

    def test_once_made_it_is_what_the_window_holds(self):
        s = _session()
        s.delivered("Meet on Tuesday.", window=WINDOW)
        s._route("change Tuesday to Thursday")
        s.events()
        _fix(s)
        self.assertEqual(s.paste_run.top.text, "Meet on Thursday.")
        self.assertEqual(s.last_handed, "Meet on Thursday.")
        edits = [e.text for e in s.events() if e.kind == "edit"]
        self.assertEqual(edits, ["changed “Tuesday.” to “Thursday.”"])

    def test_scratch_that_undoes_the_change_and_then_the_paste(self):
        s = _session()
        s.delivered("Meet on Tuesday.", window=WINDOW)
        s._route("change Tuesday to Thursday")
        _fix(s)
        s._route("scratch that")
        fix = _fix(s)
        self.assertEqual(fix.kind, "undo")
        self.assertEqual(s.paste_run.top.text, "Meet on Tuesday.")
        s._route("scratch that")
        fix = _fix(s)
        self.assertEqual(fix.kind, "back")
        self.assertEqual((fix.remove, fix.insert), ("Meet on Tuesday.", ""))
        self.assertIsNone(s.paste_run)

    def test_scratch_that_walks_back_through_the_pastes_in_one_window(self):
        s = _session()
        s.delivered("First sentence.", window=WINDOW)
        s.delivered("Second sentence.", window=WINDOW)
        s._route("scratch that")
        self.assertEqual(_fix(s).remove, "Second sentence.")
        s._route("scratch that")
        self.assertEqual(_fix(s).remove, "First sentence.")
        s._route("scratch that")
        notes = [e.text for e in s.events() if e.kind == "note"]
        self.assertEqual(notes[-1], "nothing to take back - it was taken back")

    def test_a_paste_into_another_window_starts_over(self):
        s = _session()
        s.delivered("One.", window=WINDOW)
        s.delivered("Two.", window=WINDOW + 1)
        self.assertEqual(len(s.paste_run.pastes), 1)
        self.assertEqual(s.paste_run.window, WINDOW + 1)

    def test_the_front_of_a_sentence_is_still_dictation(self):
        s = _session()
        s.delivered("Meet on Tuesday.", window=WINDOW)
        s._route("Never mind the weather, let's go.")
        self.assertIsNone(s.take_paste_fix())
        self.assertEqual(s.draft.text, "Never mind the weather, let's go.")

    def test_a_change_whose_words_are_not_there_is_dictation(self):
        s = _session()
        s.delivered("Meet on Tuesday.", window=WINDOW)
        s._route("change the oil to synthetic")
        self.assertIsNone(s.take_paste_fix())
        self.assertEqual(s.draft.text, "change the oil to synthetic")

    def test_new_paragraph_waits_for_the_next_words(self):
        # Neither a change to the paste nor words: the break, which goes in with what
        # is said next. It used to be pasted as the two words "new paragraph".
        s = _session()
        s.delivered("Meet on Tuesday.", window=WINDOW)
        s._route("new paragraph")
        self.assertIsNone(s.take_paste_fix())
        self.assertEqual(s.draft.text, "\n\n")
        self.assertIn("new paragraph - it goes in with your next words",
                      [e.text for e in s.events() if e.kind == "edit"])
        s._route("Agenda below.")
        self.assertEqual(s.draft.text, "\n\nAgenda below.")

    def test_new_line_with_nothing_pasted_too(self):
        s = _session()
        s._route("new line")
        self.assertEqual(s.draft.text, "\n")

    def test_that_was_a_command_takes_the_command_back_out(self):
        s = _session()
        s.delivered("Meet on Tuesday.", window=WINDOW)
        s.delivered("please delete Tuesday", window=WINDOW)
        s._route("that was a command")
        fix = _fix(s)
        self.assertEqual((fix.kind, fix.remove), ("back", "please delete Tuesday"))
        self.assertEqual(s.paste_run.top.text, "Meet on Tuesday.")

    def test_a_delete_that_empties_the_paste_takes_it_back(self):
        s = _session()
        s.delivered("Tuesday", window=WINDOW)
        s._route("delete Tuesday")
        self.assertEqual(_fix(s).kind, "back")

    def test_too_short_to_delete_is_said_not_pasted(self):
        s = _session()
        s.delivered("Hi.", window=WINDOW)
        s._route("delete the last three words")
        self.assertIsNone(s.take_paste_fix())
        self.assertEqual(s.draft.text, "")
        notes = [e.text for e in s.events() if e.kind == "note"]
        self.assertTrue(notes[-1].startswith("nothing to change"))

    def test_only_in_type(self):
        for mode in (REFINE, CONVERSE):
            with self.subTest(mode=mode):
                s = _session()
                s.delivered("Meet on Tuesday.", window=WINDOW)
                s.mode = mode
                self.assertFalse(s._route_paste("scratch that"))


class TestDNothingChangeableIsSaidNotPasted(unittest.TestCase):
    """With nothing to change, the bare verbs are refused out loud — and say why."""

    def _said(self, s, utterance):
        s.events()
        s._route(utterance)
        return [e.text for e in s.events() if e.kind == "note"]

    def test_before_any_paste(self):
        s = _session()
        self.assertEqual(self._said(s, "Scratch that."),
                         ["nothing to take back - nothing has been pasted yet"])
        self.assertEqual(s.draft.text, "")

    def test_the_other_bare_verbs(self):
        for said in ("delete the last word", "that was a command"):
            with self.subTest(said=said):
                s = _session()
                self.assertTrue(self._said(s, said)[-1].startswith("nothing to take back"))
                self.assertEqual(s.draft.text, "")

    def test_after_typing(self):
        s = _session()
        s.delivered("Meet on Tuesday.", window=WINDOW)
        s.end_paste_run("you typed after it was pasted")
        self.assertEqual(self._said(s, "scratch that"),
                         ["nothing to take back - you typed after it was pasted"])

    def test_after_a_minute(self):
        s = _session()
        s.delivered("Meet on Tuesday.", window=WINDOW)
        s._paste_run.at -= CORRECT_WINDOW_SEC + 1
        self.assertIsNone(s.paste_run)
        self.assertEqual(self._said(s, "scratch that"),
                         ["nothing to take back - it was over a minute ago"])

    def test_after_enter(self):
        s = _session()
        s.delivered("ls -la", window=WINDOW, submitted=True)
        self.assertIsNone(s.paste_run)
        self.assertEqual(self._said(s, "scratch that"),
                         ["nothing to take back - it went in with Enter"])

    def test_after_a_copy(self):
        s = _session()
        s.delivered("Meet on Tuesday.", copied=True, window=WINDOW)
        self.assertIsNone(s.paste_run)

    def test_after_a_refused_paste(self):
        s = _session()
        s.delivered("Meet on Tuesday.", "not pasted: the target window changed",
                    window=WINDOW)
        self.assertIsNone(s.paste_run)

    def test_a_surface_that_cannot_watch_never_offers_one(self):
        s = _session()
        s.delivered("Meet on Tuesday.")
        self.assertIsNone(s.paste_run)

    def test_ordinary_dictation_is_still_dictation(self):
        s = _session()
        s._route("Meet on Tuesday.")
        self.assertEqual(s.draft.text, "Meet on Tuesday.")


class TestEBoundsKeepTheCountHonest(unittest.TestCase):
    """Claude Code folds a paste of more than 800 characters or two lines into a
    placeholder a count of Backspaces cannot see into."""

    def test_the_bounds(self):
        self.assertTrue(paste_fits("x" * CORRECT_MAX_CHARS))
        self.assertFalse(paste_fits("x" * (CORRECT_MAX_CHARS + 1)))
        self.assertTrue(paste_fits("one\ntwo"))
        self.assertFalse(paste_fits("one\ntwo\nthree"))
        self.assertFalse(paste_fits("ends in a break\n"))
        self.assertFalse(paste_fits("   "))

    def test_a_long_paste_is_never_changeable(self):
        s = _session()
        s.delivered("word " * 200, window=WINDOW)
        self.assertIsNone(s.paste_run)

    def test_the_words_kept_are_the_words_sent_spaces_and_all(self):
        s = _session()
        s.delivered("a list - ", window=WINDOW)
        self.assertEqual(s.paste_run.top.text, "a list - ")

    def test_a_change_that_would_cross_the_bound_is_refused(self):
        s = _session()
        s.delivered("x " + "y" * 700, window=WINDOW)
        s._route("change x to " + "z " * 60)
        self.assertIsNone(s.take_paste_fix())


class TestFTheRecordsFollowTheWindow(unittest.TestCase):
    """History and Paste last hold the words as they now stand — and a take-back is
    kept, marked, as the way back from a "scratch that" said by mistake."""

    def test_a_change_updates_the_kept_entry(self):
        h = _kept()
        s = _session(history=h)
        s.delivered("Meet on Tuesday.", window=WINDOW)
        s._route("change Tuesday to Thursday")
        _fix(s)
        h.flush()
        entry = h.entries()[0]
        self.assertEqual(entry["text"], "Meet on Thursday.")
        self.assertEqual(entry["how"], "pasted, then changed")

    def test_undoing_it_puts_the_entry_back(self):
        h = _kept()
        s = _session(history=h)
        s.delivered("Meet on Tuesday.", window=WINDOW)
        s._route("change Tuesday to Thursday")
        _fix(s)
        s._route("scratch that")
        _fix(s)
        h.flush()
        entry = h.entries()[0]
        self.assertEqual((entry["text"], entry["how"]), ("Meet on Tuesday.", "pasted"))

    def test_a_take_back_is_kept_and_marked(self):
        h = _kept()
        s = _session(history=h)
        s.delivered("Meet on Tuesday.", window=WINDOW)
        s._route("scratch that")
        _fix(s)
        h.flush()
        entry = h.entries()[0]
        self.assertEqual((entry["text"], entry["how"]), ("Meet on Tuesday.", "taken back"))
        # And Paste last still has the words: the way back from a mistaken scratch.
        self.assertEqual(s.last_handed, "Meet on Tuesday.")

    def test_a_change_teaches_the_pair(self):
        folder = Path(tempfile.mkdtemp())
        profile = Profile(folder / "profile.json")
        s = _session(profile=profile)
        s.delivered("Ask Samir about it.", window=WINDOW)
        s._route("change Samir to Sameer")
        _fix(s)
        self.assertEqual(profile.pairs["samir -> Sameer"], 1)

    def test_a_change_that_did_not_go_in_ends_it(self):
        s = _session()
        s.delivered("Meet on Tuesday.", window=WINDOW)
        s._route("change Tuesday to Thursday")
        fix = s.take_paste_fix()
        s.paste_fixed(fix, "not changed: Windows took 5 of 20 keystrokes")
        self.assertIsNone(s.paste_run)
        s.events()
        s._route("scratch that")
        notes = [e.text for e in s.events() if e.kind == "note"]
        self.assertEqual(notes, ["nothing to take back - the last change did not go in"])

    def test_a_paste_in_the_meantime_makes_the_change_stale(self):
        s = _session()
        s.delivered("Meet on Tuesday.", window=WINDOW)
        s._route("change Tuesday to Thursday")
        s.delivered("Another thing.", window=WINDOW)
        self.assertIsNone(s.take_paste_fix())

    def test_a_run_that_ended_hands_back_nothing(self):
        s = _session()
        s.delivered("Meet on Tuesday.", window=WINDOW)
        s._route("change Tuesday to Thursday")
        s.end_paste_run("you clicked after it was pasted")
        self.assertIsNone(s.take_paste_fix())


class _Hook:
    touched = False


def _typer(**attrs):
    """A compact pill in Type with a hook, a paste handler and a real session."""
    p = pill(mode=DICTATE, **attrs)
    p.session = _session()
    p.hotkeys = mock.Mock(hook=_Hook())
    p.on_send = mock.Mock(return_value="")
    p.paste_target = WINDOW
    p._say = mock.Mock()
    p._quicken = mock.Mock()
    return p


class TestGTheCompactPillWatchesAndTypes(unittest.TestCase):

    def test_a_type_paste_is_offered_as_changeable(self):
        p = _typer()
        p.hotkeys.hook.touched = True
        p.session.draft.append("Meet on Tuesday.")
        p._send()
        p.on_send.assert_called_once_with("Meet on Tuesday.", WINDOW)
        # "Since" starts before the Ctrl-V.
        self.assertIs(p.hotkeys.hook.touched, False)
        self.assertEqual(p.session.paste_run.top.text, "Meet on Tuesday.")

    def test_not_with_enter_behind_it(self):
        p = _typer()
        p.session.draft.append("ls -la")
        p._send(submit=True)
        self.assertIsNone(p.session.paste_run)

    def test_not_without_a_hook_to_watch_the_keys_with(self):
        p = _typer()
        p.hotkeys = None
        p.session.draft.append("Meet on Tuesday.")
        p._send()
        self.assertIsNone(p.session.paste_run)

    def _live(self):
        p = _typer()
        p.session.delivered("Meet on Tuesday.", window=WINDOW)
        return p

    def test_a_typed_key_ends_it(self):
        p = self._live()
        p.hotkeys.hook.touched = True
        p._watch_paste_run()
        self.assertIsNone(p.session.paste_run)
        self.assertEqual(p.session._paste_ended, "you typed after it was pasted")

    def test_a_click_off_the_pill_ends_it(self):
        p = self._live()
        with mock.patch.object(uc.CompactPill, "_clicked_off_pill", return_value=True):
            p._watch_paste_run()
        self.assertEqual(p.session._paste_ended, "you clicked after it was pasted")

    def test_another_window_in_front_ends_it(self):
        p = self._live()
        with mock.patch.object(uc, "foreground_hwnd", return_value=WINDOW + 7), \
             mock.patch.object(uc, "owned_by_flow", return_value=False), \
             mock.patch.object(uc.CompactPill, "_clicked_off_pill", return_value=False):
            p._watch_paste_run()
        self.assertEqual(p.session._paste_ended, "another window came to the front")

    def test_flows_own_windows_in_front_do_not(self):
        p = self._live()
        with mock.patch.object(uc, "foreground_hwnd", return_value=WINDOW + 7), \
             mock.patch.object(uc, "owned_by_flow", return_value=True), \
             mock.patch.object(uc.CompactPill, "_clicked_off_pill", return_value=False):
            p._watch_paste_run()
        self.assertIsNotNone(p.session.paste_run)

    def test_a_click_on_the_pill_is_not_a_click_off_it(self):
        p = self._live()
        p._shell_xy, p._shell_w, p._shell_h = (100, 400), uc.PILL_W, uc.PILL_H
        p.dev = lambda v: v
        pt_on = (110, 410)

        def cursor(ptr):
            ptr._obj.x, ptr._obj.y = pt_on
            return 1

        with mock.patch.object(uc._user32, "GetAsyncKeyState", return_value=-32768), \
             mock.patch.object(uc._user32, "GetCursorPos", side_effect=cursor):
            self.assertFalse(p._clicked_off_pill())
            pt_on = (900, 900)
            self.assertTrue(p._clicked_off_pill())

    def _retyping(self):
        p = self._live()
        p.session._route("change Tuesday to Thursday")
        p._pump_events()  # the `retype` event arms the wait
        self.assertIsNotNone(p._retype_wait)
        return p

    def test_the_change_goes_in_once_the_keys_are_up(self):
        p = self._retyping()
        with mock.patch.object(uc, "modifiers_held", return_value=False), \
             mock.patch.object(uc, "foreground_hwnd", return_value=WINDOW):
            p._pump_retype()
        p.on_send.assert_called_once_with("hursday.", WINDOW, remove="uesday.")
        self.assertEqual(p.session.paste_run.top.text, "Meet on Thursday.")

    def test_it_waits_out_the_hold(self):
        p = self._retyping()
        p._press_talking = True
        with mock.patch.object(uc, "modifiers_held", return_value=False), \
             mock.patch.object(uc, "foreground_hwnd", return_value=WINDOW):
            p._pump_retype()
        p.on_send.assert_not_called()
        self.assertIsNotNone(p._retype_wait)

    def test_it_waits_for_the_modifiers(self):
        # A Backspace under a held Ctrl is Ctrl+Backspace: a word per key.
        p = self._retyping()
        with mock.patch.object(uc, "modifiers_held", return_value=True), \
             mock.patch.object(uc, "foreground_hwnd", return_value=WINDOW):
            p._pump_retype()
        p.on_send.assert_not_called()
        p._retype_wait -= uc.PASTE_LAST_WAIT_SEC + 1
        with mock.patch.object(uc, "modifiers_held", return_value=True), \
             mock.patch.object(uc, "foreground_hwnd", return_value=WINDOW):
            p._pump_retype()
        p.on_send.assert_not_called()
        self.assertIn("keys stayed down", p._say.call_args[0][0])
        self.assertIsNone(p.session.paste_run)

    def test_a_key_typed_in_between_refuses_it(self):
        p = self._retyping()
        p.hotkeys.hook.touched = True
        with mock.patch.object(uc, "modifiers_held", return_value=False), \
             mock.patch.object(uc, "foreground_hwnd", return_value=WINDOW):
            p._pump_retype()
        p.on_send.assert_not_called()
        self.assertIn("you typed", p._say.call_args[0][0])

    def test_another_window_in_front_refuses_it(self):
        p = self._retyping()
        with mock.patch.object(uc, "modifiers_held", return_value=False), \
             mock.patch.object(uc, "foreground_hwnd", return_value=WINDOW + 1):
            p._pump_retype()
        p.on_send.assert_not_called()

    def test_a_refusal_from_the_keys_ends_it_out_loud(self):
        p = self._retyping()
        p.on_send.return_value = "not changed: Windows took 5 of 20 keystrokes"
        with mock.patch.object(uc, "modifiers_held", return_value=False), \
             mock.patch.object(uc, "foreground_hwnd", return_value=WINDOW):
            p._pump_retype()
        self.assertIsNone(p.session.paste_run)
        self.assertTrue(p._flash)
        self.assertIn("not changed", p._say.call_args[0][0])

    def test_a_warning_is_said_and_is_not_a_failure(self):
        p = self._retyping()
        p.on_send.return_value = "your clipboard held an image - it will not be restored"
        with mock.patch.object(uc, "modifiers_held", return_value=False), \
             mock.patch.object(uc, "foreground_hwnd", return_value=WINDOW):
            p._pump_retype()
        self.assertEqual(p.session.paste_run.top.text, "Meet on Thursday.")
        self.assertIn("clipboard", p._say.call_args[0][0])

    def test_the_retype_event_arms_the_wait(self):
        p = self._live()
        p.session._route("scratch that")
        p._pump_events()
        self.assertIsNotNone(p._retype_wait)

    def test_paste_last_ends_it(self):
        p = self._live()
        p._paste_last_wait = ("Meet on Tuesday.", time.perf_counter(), False)
        with mock.patch.object(uc, "modifiers_held", return_value=False):
            p._pump_paste_last()
        self.assertIsNone(p.session.paste_run)
        self.assertEqual(p.session._paste_ended, "Paste last pasted after it")


class TestHTypePastesInARowGetTheirSpace(unittest.TestCase):
    """Two holds used to paste as "Hello there.How are you?" — each paste a draft of its
    own, and a draft never starts with a space. A changeable paste is the one place Flow
    knows what is in front of the caret."""

    def _after(self, first, window=WINDOW):
        s = _session()
        s.delivered(first, window=window)
        return s

    def test_a_paste_that_continues_the_last_one_gets_the_space(self):
        s = self._after("Hello there.")
        self.assertEqual(s.join_paste("How are you?", WINDOW), " How are you?")

    def test_a_command_in_two_holds_joins_up(self):
        s = self._after("git commit")
        self.assertEqual(s.join_paste("-m fix", WINDOW), " -m fix")

    def test_nothing_where_flow_cannot_know_what_is_in_front(self):
        # No paste yet, another window, a run that ended: the caret could be anywhere.
        self.assertEqual(_session().join_paste("How are you?", WINDOW), "How are you?")
        s = self._after("Hello there.")
        self.assertEqual(s.join_paste("How are you?", WINDOW + 1), "How are you?")
        s.end_paste_run("you typed after it was pasted")
        self.assertEqual(s.join_paste("How are you?", WINDOW), "How are you?")

    def test_nothing_where_the_two_already_meet(self):
        self.assertEqual(self._after("a list - ").join_paste("milk", WINDOW), "milk")
        self.assertEqual(self._after("Dear team,\nThanks").join_paste("\n\nBest", WINDOW),
                         "\n\nBest")

    def test_nothing_before_punctuation_that_belongs_to_the_word_in_front(self):
        for text in (", and more", ".5 seconds", "? Really", ") too", "% faster"):
            with self.subTest(text=text):
                self.assertEqual(self._after("It was 3").join_paste(text, WINDOW), text)

    def test_nothing_after_a_bracket_a_hyphen_or_a_slash(self):
        for before, text in (("see (", "below"), ("well-", "known"), ("src/", "flow")):
            with self.subTest(before=before):
                self.assertEqual(self._after(before).join_paste(text, WINDOW), text)

    def test_only_in_type(self):
        s = self._after("Hello there.")
        s.mode = CONVERSE
        self.assertEqual(s.join_paste("How are you?", WINDOW), "How are you?")

    def test_the_space_is_kept_where_the_backspaces_count_and_nowhere_else(self):
        h = _kept()
        s = _session(history=h)
        s.delivered("Hello there.", window=WINDOW)
        joined = s.join_paste("How are you?", WINDOW)
        s.delivered(joined, window=WINDOW)
        # The window holds the space, so the run does; History and Paste last do not.
        self.assertEqual(s.paste_run.top.text, " How are you?")
        self.assertEqual(s.last_handed, "How are you?")
        h.flush()
        self.assertEqual(h.entries()[0]["text"], "How are you?")
        # And "scratch that" takes the space back with the words.
        s._route("scratch that")
        self.assertEqual(s.take_paste_fix().remove, " How are you?")

    def test_the_compact_pill_pastes_the_space(self):
        p = _typer()
        p.session.delivered("Hello there.", window=WINDOW)
        p.session.draft.append("How are you?")
        with mock.patch.object(uc.CompactPill, "_clicked_off_pill", return_value=False), \
             mock.patch.object(uc, "foreground_hwnd", return_value=WINDOW):
            p._send()
        p.on_send.assert_called_once_with(" How are you?", WINDOW)
        self.assertEqual(p.session.paste_run.top.text, " How are you?")

    def test_a_key_typed_just_before_it_means_no_space(self):
        # The frame's watch runs every 30 ms; the paste asks again on the spot.
        p = _typer()
        p.session.delivered("Hello there.", window=WINDOW)
        p.hotkeys.hook.touched = True
        p.session.draft.append("How are you?")
        p._send()
        p.on_send.assert_called_once_with("How are you?", WINDOW)

    def test_a_click_just_before_it_means_no_space(self):
        p = _typer()
        p.session.delivered("Hello there.", window=WINDOW)
        p.session.draft.append("How are you?")
        with mock.patch.object(uc.CompactPill, "_clicked_off_pill", return_value=True):
            p._send()
        p.on_send.assert_called_once_with("How are you?", WINDOW)


if __name__ == "__main__":
    unittest.main()
