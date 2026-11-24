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
import flow.refine as refine_mod  # noqa: E402
import flow.session as session_mod  # noqa: E402
import flow.ui_compact as uc  # noqa: E402
from flow.edits import whole_undo  # noqa: E402
from flow.history import History  # noqa: E402
from flow.inject import Target, backspaces, take_warnings  # noqa: E402
from flow.profile import Profile  # noqa: E402
from flow import kinds  # noqa: E402
from flow.session import (  # noqa: E402
    CONVERSE, CORRECT_MAX_CHARS, CORRECT_WINDOW_SEC, DICTATE, REFINE, Session, State,
    paste_fits,
)
from clipboard_env import sealed_clipboard  # noqa: E402
from test_inject_target import all_inserted, only  # noqa: E402
from test_session import FakeMic, FakeTranscriber  # noqa: E402
from test_ui_compact import direct, pill  # noqa: E402

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
#: The one agent CLI the rewrite tests pretend is installed.
CLAUDE = refine_mod.named("claude")


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
        with mock.patch.object(uc, "foreground_hwnd", return_value=WINDOW), \
             mock.patch.object(uc.CompactPill, "_clicked_off_pill", return_value=False):
            p._watch_paste_run()
            # Doubted for a moment - the key may be the rewrite shortcut's own - and
            # then believed (`TOUCH_GRACE_SEC`).
            self.assertIsNotNone(p.session.paste_run)
            p._touched_at -= uc.TOUCH_GRACE_SEC
            p._watch_paste_run()
        self.assertIsNone(p.session.paste_run)
        self.assertEqual(p.session._paste_ended, "you typed after it was pasted")

    def test_a_paste_about_to_go_in_does_not_wait_to_believe_it(self):
        # The space a second paste gets is decided on what is true this frame.
        p = self._live()
        p.hotkeys.hook.touched = True
        p._watch_paste_run(now=True)
        self.assertIsNone(p.session.paste_run)

    def test_the_doubt_does_not_outlive_the_key(self):
        p = self._live()
        p.hotkeys.hook.touched = True
        with mock.patch.object(uc, "foreground_hwnd", return_value=WINDOW), \
             mock.patch.object(uc.CompactPill, "_clicked_off_pill", return_value=False):
            p._watch_paste_run()
            self.assertIsNotNone(p._touched_at)
            p.hotkeys.hook.touched = False
            p._watch_paste_run()
        self.assertIsNone(p._touched_at)
        self.assertIsNotNone(p.session.paste_run)

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



class TestGARewriteIsAskedForAfterTheWordsHaveLanded(unittest.TestCase):
    """decisions.md 2026-11-22, "The pill is an indicator". Refine was a mode entered
    before speaking, with a panel and a second action to send. Asked for afterwards it
    needs neither: the words are on the page the moment they are said, "make it an
    email" is one more sentence, and a CLI that fails changes nothing."""

    SAID = "tell priya the release moves to tuesday and say sorry for the late notice"
    EMAIL = "Hi Priya,\n\nThe release moves to Tuesday. Sorry for the late notice.\n\nThanks,"
    MESSAGE = "Priya, the release moves to Tuesday. Sorry for the late notice."

    def asked(self, utterance, result, *, pasted=None, app="OUTLOOK.EXE"):
        """Paste, say `utterance`, and let the CLI answer `result`. Returns the session
        and the mock, with the answer already pumped."""
        s = _session()
        self.addCleanup(s.close)
        s.target_app = app
        s.delivered(pasted or self.SAID, window=WINDOW)
        s.events()
        with mock.patch("flow.session.refine", return_value=result) as call, \
                mock.patch("flow.session.available", return_value=[CLAUDE]):
            s._route(utterance)
            s.wait_idle(timeout=5.0)
            s.pump_results()
        return s, call

    def test_the_cli_is_handed_the_pasted_words_in_the_selected_style(self):
        _s, call = self.asked("polish that", (self.MESSAGE, "claude"))
        self.assertEqual(call.call_args.args[0], self.SAID)
        self.assertTrue(call.call_args.kwargs["polish"])
        self.assertEqual(call.call_args.kwargs["kind"], "prompt")

    def test_the_request_is_not_pasted_as_words(self):
        s, _call = self.asked("polish that", (self.MESSAGE, "claude"))
        self.assertEqual(s.draft.text, "")
        self.assertEqual([e for e in s.events() if e.kind == "draft" and e.text], [])

    def test_the_answer_replaces_the_paste_where_it_is(self):
        s, _call = self.asked("polish that", (self.MESSAGE, "claude"))
        self.assertIn("retype", [e.kind for e in s.events()])
        fix = _fix(s)
        self.assertEqual(fix.after, self.MESSAGE)
        self.assertEqual(s.paste_run.top.text, self.MESSAGE)
        self.assertEqual(s.last_handed, self.MESSAGE)

    def test_only_the_tail_that_differs_is_retyped(self):
        s, _call = self.asked("make it shorter", ("tell priya the release moved", "claude"))
        fix = s.take_paste_fix()
        self.assertTrue(self.SAID.startswith("tell priya the release move"))
        self.assertEqual(fix.remove, self.SAID[len("tell priya the release move"):])
        self.assertEqual(fix.insert, "d")

    def test_polish_that_uses_the_selected_style(self):
        _s, call = self.asked("polish that", (self.MESSAGE, "claude"), app="slack.exe")
        self.assertEqual(call.call_args.kwargs["kind"], "prompt")
        _s, call = self.asked("polish that", (self.MESSAGE, "claude"),
                              app="WindowsTerminal.exe")
        self.assertEqual(call.call_args.kwargs["kind"], "prompt")

    def test_a_named_change_goes_as_the_instruction_it_is(self):
        _s, call = self.asked("make it a bit more formal", (self.MESSAGE, "claude"))
        self.assertEqual(call.call_args.args[1], "make it a bit more formal")
        self.assertFalse(call.call_args.kwargs["polish"])

    def test_scratch_that_puts_the_words_as_said_back(self):
        s, _call = self.asked("polish that", (self.MESSAGE, "claude"))
        _fix(s)
        s._route("scratch that")
        fix = _fix(s)
        self.assertEqual(fix.after, self.SAID)
        self.assertEqual(s.paste_run.top.text, self.SAID)

    def test_asking_again_is_written_from_the_words_as_said(self):
        # Not from the first rewrite: two models' choices do not compound.
        s, _call = self.asked("polish that", (self.MESSAGE, "claude"))
        _fix(s)
        with mock.patch("flow.session.refine", return_value=("again", "claude")) as call, \
                mock.patch("flow.session.available", return_value=[CLAUDE]):
            s._route("polish that")
            s.wait_idle(timeout=5.0)
            s.pump_results()
        self.assertEqual(call.call_args.args[0], self.SAID)

    def test_a_failed_rewrite_changes_nothing_and_says_so(self):
        s, _call = self.asked("polish that", (None, "claude timed out after 20s"))
        events = s.events()
        self.assertNotIn("retype", [e.kind for e in events])
        self.assertIsNone(s.take_paste_fix())
        self.assertEqual(s.paste_run.top.text, self.SAID)
        errors = [e.text for e in events if e.kind == "error"]
        self.assertEqual(errors, ["could not rewrite that (claude timed out after 20s) "
                                  "- your words are unchanged"])

    def test_an_email_in_a_mail_program_stays_changeable_as_one_piece(self):
        # decisions.md 2026-11-24: a pasted email was not reformatted on the way in,
        # so outside a terminal its line breaks can be counted back over.
        s, _call = self.asked("polish that", (self.EMAIL, "claude"))
        fix = _fix(s)
        self.assertEqual(fix.after, self.EMAIL)
        self.assertEqual(s.last_handed, self.EMAIL.strip())
        self.assertIsNotNone(s.paste_run)
        s._route("scratch that")
        self.assertEqual(_fix(s).after, self.SAID)

    def test_in_a_terminal_an_email_still_ends_what_scratch_that_can_reach(self):
        # Enter and line handling there are the shell's: the strict limits stand.
        s, _call = self.asked("polish that", (self.EMAIL, "claude"),
                              app="WindowsTerminal.exe")
        s.events()
        self.assertEqual(_fix(s).after, self.EMAIL)
        self.assertIsNone(s.paste_run)
        said = [e.text for e in s.events() if e.kind == "edit"]
        self.assertEqual(said, ["refined as a prompt"])
        s._route("scratch that")
        notes = [e.text for e in s.events() if e.kind == "note"]
        self.assertEqual(notes, ["nothing to take back - it had more than one line break"])

    def test_with_nothing_pasted_it_is_refused_out_loud_not_typed(self):
        s = _session()
        self.addCleanup(s.close)
        s._route("polish that")
        self.assertEqual(s.draft.text, "")
        notes = [e.text for e in s.events() if e.kind == "note"]
        self.assertEqual(len(notes), 1)
        self.assertTrue(notes[0].startswith("nothing to rewrite - "), notes)

    def test_with_no_agent_cli_it_says_what_it_needs(self):
        s = _session()
        self.addCleanup(s.close)
        s.delivered(self.SAID, window=WINDOW)
        s.events()
        with mock.patch("flow.session.available", return_value=[]):
            s._route("polish that")
        notes = [e.text for e in s.events() if e.kind == "note"]
        self.assertEqual(notes, ["nothing to rewrite with - that needs claude or codex, "
                                 "see Flow Home, Models"])
        self.assertEqual(s.paste_run.top.text, self.SAID)

    def test_a_sentence_that_starts_like_a_request_is_dictation(self):
        # "Make it clear that ..." said after a paste is the next sentence, and taking
        # it as an instruction would rewrite the one before it.
        s = _session()
        self.addCleanup(s.close)
        s.delivered(self.SAID, window=WINDOW)
        with mock.patch("flow.session.refine") as call:
            s._route("make it clear that we need the report by Friday")
        call.assert_not_called()
        self.assertEqual(s.draft.text, "make it clear that we need the report by Friday")

    def test_words_pasted_while_the_cli_was_out_are_not_the_ones_replaced(self):
        # Six seconds is long enough to say another sentence. The rewrite is of the
        # first one; the paste at the caret is now the second.
        s = _session()
        self.addCleanup(s.close)
        s.delivered(self.SAID, window=WINDOW)

        def slow(*_a, **_kw):
            s.delivered("And one more thing.", window=WINDOW)
            return self.MESSAGE, "claude"

        with mock.patch("flow.session.refine", side_effect=slow), \
                mock.patch("flow.session.available", return_value=[CLAUDE]):
            s.events()
            s._route("polish that")
            s.wait_idle(timeout=5.0)
            s.pump_results()
        events = s.events()
        self.assertNotIn("retype", [e.kind for e in events])
        self.assertEqual(s.paste_run.top.text, "And one more thing.")
        # Not thrown away: it is what Paste last pastes.
        self.assertEqual(s.last_handed, self.MESSAGE)
        notes = [e.text for e in events if e.kind == "note"]
        self.assertIn("rewritten, but the text moved on - Paste last has it", notes)

    def test_a_keystroke_while_the_cli_was_out_leaves_the_window_alone(self):
        s = _session()
        self.addCleanup(s.close)
        s.delivered(self.SAID, window=WINDOW)

        def typed(*_a, **_kw):
            s.end_paste_run("you typed after Flow pasted")
            return self.MESSAGE, "claude"

        with mock.patch("flow.session.refine", side_effect=typed), \
                mock.patch("flow.session.available", return_value=[CLAUDE]):
            s._route("polish that")
            s.wait_idle(timeout=5.0)
            s.pump_results()
        self.assertIsNone(s.take_paste_fix())
        self.assertEqual(s.last_handed, self.MESSAGE)

    def test_a_second_request_while_one_is_out_waits(self):
        s = _session()
        self.addCleanup(s.close)
        s.delivered(self.SAID, window=WINDOW)
        s._refine_op = 7
        s.events()
        s._route("polish that")
        notes = [e.text for e in s.events() if e.kind == "note"]
        self.assertEqual(notes, ["still rewriting - one moment"])
        s._refine_op = None

    def test_it_is_a_type_thing_and_refine_mode_is_left_alone(self):
        s = _session()
        self.addCleanup(s.close)
        s.delivered(self.SAID, window=WINDOW)
        s.toggle_mode(to=REFINE)
        self.assertFalse(s._route_paste("make it an email"))


class TestGBTheRewriteCanBePressedInsteadOfSaid(unittest.TestCase):
    """The `rewrite` shortcut (alt+shift+X): "polish that" for the room where nobody
    says a command out loud, and the one place a person can find it by looking."""

    SAID = TestGARewriteIsAskedForAfterTheWordsHaveLanded.SAID
    MESSAGE = TestGARewriteIsAskedForAfterTheWordsHaveLanded.MESSAGE

    def pressed(self, result=None, *, app="slack.exe", paste=True):
        s = _session()
        self.addCleanup(s.close)
        s.target_app = app
        if paste:
            s.delivered(self.SAID, window=WINDOW)
        s.events()
        with mock.patch("flow.session.refine",
                        return_value=result or (self.MESSAGE, "claude")) as call, \
                mock.patch("flow.session.available", return_value=[CLAUDE]):
            s.rewrite_last()
            s.wait_idle(timeout=5.0)
            s.pump_results()
        return s, call

    def test_it_asks_for_what_polish_that_asks_for(self):
        _s, call = self.pressed()
        self.assertEqual(call.call_args.args[0], self.SAID)
        self.assertTrue(call.call_args.kwargs["polish"])
        self.assertEqual(call.call_args.kwargs["kind"], "prompt")

    def test_the_selected_style_is_what_it_is_written_as(self):
        # decisions.md 2026-11-24: not a reading of the window.
        _s, call = self.pressed(app="OUTLOOK.EXE")
        self.assertEqual(call.call_args.kwargs["kind"], "prompt")

    def test_the_answer_replaces_the_paste_where_it_is(self):
        s, _call = self.pressed()
        self.assertIn("retype", [e.kind for e in s.events()])
        self.assertEqual(_fix(s).after, self.MESSAGE)

    def test_with_nothing_pasted_it_says_so(self):
        s, call = self.pressed(paste=False)
        call.assert_not_called()
        notes = [e.text for e in s.events() if e.kind == "note"]
        self.assertEqual(notes, ["nothing to rewrite - nothing has been pasted yet"])

    def test_not_while_words_are_being_said(self):
        s = _session()
        self.addCleanup(s.close)
        s.delivered(self.SAID, window=WINDOW)
        s.events()
        s.state = State.LISTENING
        with mock.patch("flow.session.refine") as call:
            s.rewrite_last()
        call.assert_not_called()
        notes = [e.text for e in s.events() if e.kind == "note"]
        self.assertEqual(notes, ["still listening - rewrite once the words are in"])


class TestGCTheShortcutsOwnKeyIsNotTyping(unittest.TestCase):
    """The key that completes the shortcut goes down like any other, and the hook does
    not know which key it was. The pill does: `RegisterHotKey` reported it."""

    def live(self):
        # The window the words went to is still in front and nobody has clicked: the
        # only thing in question in this class is the key.
        self.enterContext(mock.patch.object(uc, "foreground_hwnd", return_value=WINDOW))
        self.enterContext(mock.patch.object(uc.CompactPill, "_clicked_off_pill",
                                            return_value=False))
        p = _typer()
        p.session.delivered("Meet on Tuesday.", window=WINDOW)
        p.session.rewrite_last = mock.Mock()
        return p

    def press(self, p, held=True):
        # What the hook has already done by the time the press is drained.
        p.hotkeys.hook.touched = True
        p.hotkeys.drain.return_value = ["rewrite"]
        with mock.patch.object(uc, "modifiers_held", return_value=held):
            p._drain_hotkeys()
        p.hotkeys.drain.return_value = []

    def test_the_press_reaches_the_session(self):
        p = self.live()
        self.press(p)
        p.session.rewrite_last.assert_called_once_with()

    def test_its_key_does_not_end_what_it_is_about_to_rewrite(self):
        p = self.live()
        self.press(p)
        self.assertIs(p.hotkeys.hook.touched, False)
        with mock.patch.object(uc.CompactPill, "_clicked_off_pill", return_value=False), \
                mock.patch.object(uc, "foreground_hwnd", return_value=WINDOW):
            p._watch_paste_run()
        self.assertIsNotNone(p.session.paste_run)

    def test_nor_when_the_frame_saw_the_key_before_the_press_arrived(self):
        # The press is reported on another thread. A frame in between sees a key and
        # nothing else - which is what the doubt is for.
        p = self.live()
        p.hotkeys.hook.touched = True
        with mock.patch.object(uc.CompactPill, "_clicked_off_pill", return_value=False), \
                mock.patch.object(uc, "foreground_hwnd", return_value=WINDOW):
            p._watch_paste_run()
            self.assertIsNotNone(p.session.paste_run)
            self.press(p)
            p._watch_paste_run()
        self.assertIsNotNone(p.session.paste_run)
        self.assertIsNone(p._touched_at)

    def test_held_down_the_hook_is_told_so(self):
        p = self.live()
        self.press(p, held=True)
        self.assertIs(p.hotkeys.hook.own_key, True)

    def test_already_let_go_it_is_not(self):
        # A quick tap can be over before the press is drained. Told then, the hook
        # would wait for a key to come up - and the next one to come up is typed.
        p = self.live()
        self.press(p, held=False)
        self.assertIs(p.hotkeys.hook.own_key, False)

    def test_no_hand_on_the_keys_clears_it_within_a_frame(self):
        p = self.live()
        self.press(p, held=True)
        with mock.patch.object(uc, "modifiers_held", return_value=False), \
                mock.patch.object(uc.CompactPill, "_clicked_off_pill", return_value=False), \
                mock.patch.object(uc, "foreground_hwnd", return_value=WINDOW):
            p._watch_paste_run()
        self.assertIs(p.hotkeys.hook.own_key, False)

    def test_a_key_typed_before_it_is_not_forgiven(self):
        # The paste stopped being changeable when the letter was believed; the
        # shortcut afterwards claims nothing, and the session says why.
        p = self.live()
        p.hotkeys.hook.touched = True
        p._watch_paste_run()
        p._touched_at -= uc.TOUCH_GRACE_SEC
        p._watch_paste_run()
        self.assertIsNone(p.session.paste_run)
        self.press(p)
        self.assertIs(p.hotkeys.hook.touched, True)
        self.assertIsNot(p.hotkeys.hook.__dict__.get("own_key"), True)

    def test_with_no_hook_it_still_asks(self):
        p = self.live()
        p.hotkeys.hook = None
        p.hotkeys.drain.return_value = ["rewrite"]
        p._drain_hotkeys()
        p.session.rewrite_last.assert_called_once_with()


class TestGDARefineThatLandedIsChangeableToo(unittest.TestCase):
    """Where a Refine goes straight into the window (`Session.refine_lands`, the compact
    pill since 2026-11-22), what landed is Flow's own paste - so the next hold can change
    it. Before this, "scratch that" said after a landing was *refined*, and pasted."""

    SAID = "tell priya the release moves to tuesday and say sorry for the late notice"
    MESSAGE = "Priya, the release moves to Tuesday. Sorry for the late notice."

    def landed(self, lands=True, app="slack.exe"):
        """A session in Refine whose rewrite of SAID has just been pasted."""
        s = _session()
        self.addCleanup(s.close)
        s.refine_lands = lands
        s.mode = REFINE
        s.target_app = app
        # What `_pump_refine` leaves for `delivered` to recognise the rewrite by.
        s._refined = {"text": self.MESSAGE, "heard": self.SAID, "cli": "claude",
                      "secs": 6.0}
        s.delivered(self.MESSAGE, window=WINDOW)
        s.events()
        return s

    def test_it_is_kept_with_the_words_it_was_written_from(self):
        s = self.landed()
        self.assertEqual(s.paste_run.top.text, self.MESSAGE)
        self.assertEqual(s.paste_run.top.heard, self.SAID)

    def test_scratch_that_takes_it_back_out(self):
        s = self.landed()
        s._route("scratch that")
        fix = _fix(s)
        self.assertEqual(fix.remove, self.MESSAGE)
        self.assertEqual(fix.after, "")
        self.assertEqual(s.draft.text, "")

    def test_a_spoken_change_is_made_in_the_window(self):
        s = self.landed()
        s._route("change Tuesday to Thursday")
        self.assertEqual(_fix(s).after, self.MESSAGE.replace("Tuesday", "Thursday"))

    def test_asking_again_is_written_from_the_words_as_said_in_the_selected_style(self):
        s = self.landed()
        email = "Hi Priya,\n\nThe release moves to Tuesday.\n\nThanks,"
        with mock.patch("flow.session.refine", return_value=(email, "claude")) as call, \
                mock.patch("flow.session.available", return_value=[CLAUDE]):
            s._route("polish that")
            s.wait_idle(timeout=5.0)
            s.pump_results()
        self.assertEqual(call.call_args.args[0], self.SAID)
        self.assertEqual(call.call_args.kwargs["kind"], "prompt")
        self.assertEqual(s.draft.text, "")
        self.assertEqual(_fix(s).after, email)

    def test_the_next_landing_in_that_window_gets_its_space(self):
        s = self.landed()
        self.assertEqual(s.join_paste("Also ask her about QA.", WINDOW),
                         " Also ask her about QA.")

    def test_new_paragraph_is_left_for_the_cli(self):
        # In Type it is a break held for the next words. In Refine the next words go
        # to the CLI, which lays the text out itself.
        s = self.landed()
        self.assertFalse(s._route_paste("new paragraph"))

    def test_ordinary_words_are_still_dictation(self):
        s = self.landed()
        self.assertFalse(s._route_paste("and tell her the migration is done"))

    def test_where_the_result_waits_on_a_panel_nothing_changes(self):
        # The flow before 2026-11-22, still a setting: nothing was pasted that Flow
        # could count its way back over, and "make it an email" there is the panel's.
        s = self.landed(lands=False)
        self.assertIsNone(s.paste_run)
        self.assertFalse(s._route_paste("scratch that"))
        self.assertFalse(s._route_paste("make it an email"))

    def test_an_answer_is_never_a_paste(self):
        s = self.landed()
        s.mode = CONVERSE
        self.assertFalse(s._route_paste("scratch that"))


class TestGETheRefineHoldThatWasAChangeAsksForNothing(unittest.TestCase):
    """The pill's half: a hold in Refine whose words the session took as a change
    leaves no dictation behind, and the release must not ask the CLI about nothing."""

    def refining(self, draft):
        p = direct(mode=REFINE)
        p.session.draft.text = draft
        p.paste_target = WINDOW
        return p

    def test_an_empty_draft_sends_nothing_and_lands_nothing(self):
        p = self.refining("")
        p._ask()
        p.session.send.assert_not_called()
        self.assertIsNone(p._landing)

    def test_words_are_sent_and_remembered_for_the_landing(self):
        p = self.refining("tell priya the release moves")
        p._ask()
        p.session.send.assert_called_once_with()
        self.assertEqual(p._landing, (WINDOW, "tell priya the release moves"))

    def test_a_question_is_not_held_to_that_rule(self):
        p = direct(mode=CONVERSE)
        p.session.draft.text = ""
        p._last_draft = "what does this do"
        p._ask()
        p.session.send.assert_called_once_with()

    def test_the_session_is_told_which_flow_it_is_in(self):
        self.assertIs(direct(mode=REFINE).panel_flows, False)
        src = Path(uc.__file__).read_text(encoding="utf-8")
        self.assertIn("session.refine_lands = not self.panel_flows", src)


class TestGFAChangeThatCouldNotLandIsSaid(unittest.TestCase):
    """A rewrite takes six to twelve seconds, and people click back into their work in
    less. The change was dropped without a word; a rewrite went with it."""

    SAID = "tell priya the release moves to tuesday and say sorry for the late notice"
    MESSAGE = "Priya, the release moves to Tuesday. Sorry for the late notice."

    def rewriting(self, result=None):
        """A rewrite built and announced, not yet made in the window."""
        s = _session()
        self.addCleanup(s.close)
        s.target_app = "slack.exe"
        s.delivered(self.SAID, window=WINDOW)
        s.events()
        with mock.patch("flow.session.refine",
                        return_value=result or (self.MESSAGE, "claude")), \
                mock.patch("flow.session.available", return_value=[CLAUDE]):
            s._route("polish that")
            s.wait_idle(timeout=5.0)
            s.pump_results()
        return s

    def notes(self, s):
        return [e.text for e in s.events() if e.kind == "note"]

    def test_a_rewrite_on_its_way_in_is_kept_and_said(self):
        s = self.rewriting()
        s.events()
        s.end_paste_run("you clicked after it was pasted")
        self.assertEqual(self.notes(s), ["rewritten, but you clicked after it was "
                                         "pasted - Paste last has it"])
        self.assertEqual(s.last_handed, self.MESSAGE)
        self.assertIsNone(s.take_paste_fix())

    def test_a_correction_on_its_way_in_is_said(self):
        s = _session()
        self.addCleanup(s.close)
        s.delivered("Meet on Tuesday.", window=WINDOW)
        s._route("change Tuesday to Thursday")
        s.events()
        s.end_paste_run("you typed after it was pasted")
        self.assertEqual(self.notes(s),
                         ["nothing to change - you typed after it was pasted"])

    def test_with_nothing_on_its_way_nothing_is_said(self):
        s = _session()
        self.addCleanup(s.close)
        s.delivered("Meet on Tuesday.", window=WINDOW)
        s.events()
        s.end_paste_run("you typed after it was pasted")
        self.assertEqual(self.notes(s), [])

    def test_a_rewrite_that_comes_back_too_late_says_why(self):
        s = _session()
        self.addCleanup(s.close)
        s.target_app = "slack.exe"
        s.delivered(self.SAID, window=WINDOW)
        s.events()
        with mock.patch("flow.session.refine", return_value=(self.MESSAGE, "claude")), \
                mock.patch("flow.session.available", return_value=[CLAUDE]):
            s._route("polish that")
            s.end_paste_run("another window came to the front")
            s.wait_idle(timeout=5.0)
            s.pump_results()
        self.assertIn("rewritten, but another window came to the front - "
                      "Paste last has it", self.notes(s))
        self.assertEqual(s.last_handed, self.MESSAGE)

    def test_a_rewrite_that_changes_nothing_leaves_the_window_alone(self):
        s = self.rewriting(result=(self.SAID, "claude"))
        self.assertIn("nothing to change - it already reads well", self.notes(s))
        self.assertIsNone(s.take_paste_fix())
        self.assertEqual(s.paste_run.top.text, self.SAID)



class TestHARefineGrowsIntoOnePiece(unittest.TestCase):
    """decisions.md 2026-11-24: in Refine, each hold adds what was said to the piece;
    the whole of it is rewritten from the words as said and replaces what landed. It
    ends when you edit it, change window or style, or say "done"."""

    FIRST = "tell priya the release moves to tuesday"
    LANDED = "Priya, the release moves to Tuesday."

    def landed(self, app="slack.exe"):
        s = _session()
        self.addCleanup(s.close)
        s.refine_lands = True
        s.refine_says_more = False  # the compact pill's, without the panel flow
        s.mode = REFINE
        s.target_app = app
        s.refine_kind = s.kind_here()
        s._refined = {"text": self.LANDED, "heard": self.FIRST, "cli": "claude",
                      "secs": 6.0}
        s.delivered(self.LANDED, window=WINDOW)
        s.events()
        return s

    def hold(self, s, words, result):
        with mock.patch("flow.session.refine", return_value=result) as call,                 mock.patch("flow.session.available", return_value=[CLAUDE]):
            s.draft.set(words)
            s.send()
            s.wait_idle(timeout=5.0)
            s.pump_results()
        return call

    def test_the_second_hold_rewrites_the_whole_piece_in_place(self):
        s = self.landed()
        grown = "Priya, the release moves to Tuesday. Please tell QA."
        call = self.hold(s, "and ask her to tell qa", (grown, "claude"))
        self.assertEqual(call.call_args.args[0],
                         "tell priya the release moves to tuesday and ask her to tell qa")
        self.assertTrue(call.call_args.kwargs["polish"])
        self.assertEqual(call.call_args.kwargs["kind"], kinds.PROMPT)
        self.assertEqual([e.kind for e in s.events() if e.kind in ("retype", "reply")],
                         ["retype"])
        fix = _fix(s)
        self.assertEqual(fix.after, grown)
        self.assertEqual(s.paste_run.top.heard,
                         "tell priya the release moves to tuesday and ask her to tell qa")

    def test_the_replacement_is_in_the_trace(self):
        class Recording:
            path = None

            def __init__(self):
                self.records = []

            def write(self, kind, /, **fields):
                self.records.append({"kind": kind, **fields})

        s = self.landed()
        s.diag = Recording()
        self.hold(s, "and ask her to tell qa", ("Priya, it moves. Tell QA.", "claude"))
        _fix(s)
        landed = [r for r in s.diag.records if r["kind"] == "landed"]
        self.assertEqual([(r["how"], r["ok"]) for r in landed], [("replaced", True)])

    def test_a_third_hold_carries_all_three(self):
        s = self.landed()
        self.hold(s, "and ask her to tell qa", ("two", "claude"))
        _fix(s)
        call = self.hold(s, "actually make it wednesday", ("three", "claude"))
        self.assertEqual(call.call_args.args[0],
                         "tell priya the release moves to tuesday and ask her to tell qa "
                         "actually make it wednesday")

    def test_done_ends_the_piece_and_the_next_hold_is_new(self):
        s = self.landed()
        s._route("done")
        self.assertIn("done - the next Refine starts a new piece",
                      [e.text for e in s.events() if e.kind == "note"])
        self.assertIsNone(s.open_piece())
        call = self.hold(s, "a different thought", ("new", "claude"))
        self.assertEqual(call.call_args.args[0], "a different thought")

    def test_a_piece_does_not_end_on_a_timer(self):
        s = self.landed()
        s.paste_run.at -= 10 * 60
        self.assertIsNotNone(s.open_piece(), "a piece ended on the clock")

    def test_a_dictated_paste_still_expires_after_the_minute(self):
        s = _session()
        self.addCleanup(s.close)
        s.delivered("We are", window=WINDOW)
        s.paste_run.at -= 61
        self.assertIsNone(s.paste_run)

    def test_typing_in_the_window_ends_it(self):
        s = self.landed()
        s.end_paste_run("you typed after Flow pasted")
        call = self.hold(s, "and ask her to tell qa", ("new", "claude"))
        self.assertEqual(call.call_args.args[0], "and ask her to tell qa")

    def test_a_different_style_starts_a_new_piece(self):
        s = self.landed()
        s.profile = types.SimpleNamespace(kinds={}, refine_kind=kinds.EMAIL, name="",
                                          apps={}, save=lambda: True)
        self.assertIsNone(s.open_piece())

    def test_a_piece_that_cannot_grow_keeps_what_landed_and_says_so(self):
        s = self.landed()
        self.hold(s, "and ask her to tell qa", (None, "claude timed out after 20s"))
        errors = [e.text for e in s.events() if e.kind == "error"]
        # The release's own fallback line: the surface pastes the new words as said.
        self.assertEqual(errors, ["refine failed (claude timed out after 20s) - draft unchanged"])
        self.assertIsNone(s.take_paste_fix())
        self.assertEqual(s.paste_run.top.text, self.LANDED)

    def test_in_type_mode_done_is_just_a_word(self):
        s = _session()
        self.addCleanup(s.close)
        s.delivered("We are", window=WINDOW)
        self.assertFalse(s._route_paste("done"))

if __name__ == "__main__":
    unittest.main()
