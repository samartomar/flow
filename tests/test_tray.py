"""Hiding Flow without losing it.

The need, in the owner's words: "there are times where i wanted to dictate but at the
same time i wanted to see but i don't want it to keep it on my screen". Parking the
window is the easy half and the dangerous one — a Flow with no window and no icon is a
process that cannot be reached, configured or quit except through Task Manager.

So the property under test is not "it hides". It is **that it refuses to hide unless
there is a way back**, and that the way back works.

No window is created and no icon is registered here. `flow.tray` is a thin ctypes wrapper
around `Shell_NotifyIconW`, verified against the real shell by hand; what these check is
the decision Flow makes around it.
"""

import queue
import sys
import unittest
from unittest import mock

import flow.tray as tray
import flow.ui as ui


def pill(**kw):
    """A pill with just enough of one to hide and come back."""
    p = ui.Pill.__new__(ui.Pill)
    # `front` is a read-only property choosing bubble-or-card by mode, so the stand-in
    # goes on the thing it chooses rather than over the property itself.
    p.session = mock.Mock(mode=ui.DICTATE)
    p.bubble = mock.Mock()
    p.card = mock.Mock()
    p._tray_events = queue.Queue()
    p._tray = None
    p._hidden = False
    p._flash = 0
    p._ptt_since = None
    p.park = mock.Mock()
    p.deiconify = mock.Mock()
    p.lift = mock.Mock()
    p._sync_shell = mock.Mock()
    p.quit_app = mock.Mock()
    for name, value in kw.items():
        setattr(p, name, value)
    return p


class TestHidingNeedsAWayBack(unittest.TestCase):
    def test_it_hides_once_the_icon_is_actually_there(self):
        p = pill()
        icon = mock.Mock(**{"start.return_value": True})
        with mock.patch.object(tray, "available", return_value=True), \
                mock.patch.object(tray, "Tray", return_value=icon), \
                mock.patch.object(ui, "park") as parked:
            self.assertTrue(p.hide_to_tray())
        self.assertTrue(p._hidden)
        parked.assert_called_once_with(p)

    def test_an_icon_that_would_not_register_leaves_the_window_alone(self):
        """The one that matters. `Shell_NotifyIcon` can fail — a shell that is still
        starting, a notification area that is full — and hiding anyway would strand the
        user with no window and nothing to click."""
        p = pill()
        icon = mock.Mock(**{"start.return_value": False})
        with mock.patch.object(tray, "available", return_value=True), \
                mock.patch.object(tray, "Tray", return_value=icon), \
                mock.patch.object(ui, "park") as parked:
            self.assertFalse(p.hide_to_tray())
        self.assertFalse(p._hidden)
        parked.assert_not_called()
        self.assertIn("would not take", p.front.note.call_args.args[0])

    def test_a_platform_with_no_notification_area_says_so(self):
        # macOS has a menu bar item and Linux has whatever the desktop offers; neither
        # is `Shell_NotifyIcon`, and pretending otherwise would hide a window for good.
        p = pill()
        with mock.patch.object(tray, "available", return_value=False), \
                mock.patch.object(ui, "park") as parked:
            self.assertFalse(p.hide_to_tray())
        self.assertFalse(p._hidden)
        parked.assert_not_called()

    def test_the_icon_is_built_once_and_reused(self):
        # Somebody who hides Flow once will hide it again, and a second `Shell_NotifyIcon`
        # for the same app is a second icon in the tray.
        p = pill()
        icon = mock.Mock(**{"start.return_value": True})
        with mock.patch.object(tray, "available", return_value=True), \
                mock.patch.object(tray, "Tray", return_value=icon) as made, \
                mock.patch.object(ui, "park"):
            p.hide_to_tray()
            p.show_from_tray()
            p.hide_to_tray()
        made.assert_called_once()


class TestComingBack(unittest.TestCase):
    def test_showing_puts_the_window_where_it_was(self):
        p = pill(_hidden=True)
        p.show_from_tray()
        self.assertFalse(p._hidden)
        p._sync_shell.assert_called_once()
        p.deiconify.assert_called_once()

    def test_showing_a_window_that_is_already_up_does_nothing(self):
        p = pill(_hidden=False)
        p.show_from_tray()
        p.deiconify.assert_not_called()

    def test_the_chord_brings_it_back_before_it_opens_the_microphone(self):
        """A hold that showed nothing would be an open microphone with no way to tell
        it was open — which is invariant 4 read from the other side."""
        p = pill(_hidden=True)
        p.session = mock.Mock()
        p.session.talk_start.side_effect = lambda *a, **k: None
        with mock.patch.object(ui.Pill, "show_from_tray",
                               autospec=True) as shown, \
                mock.patch.object(ui.Pill, "_pump_talk", autospec=True):
            try:
                ui.Pill._talk_start(p)
            except Exception:
                pass
        shown.assert_called_once()


class TestWhatTheIconSaysArrivesOnTheUIThread(unittest.TestCase):
    """`tray.Tray` runs its window procedure on a thread of its own and puts *strings*
    on a queue rather than calling back. That is the whole of the threading argument:
    Tk is touched from one place, `_frame`, and nothing in `flow/tray.py` touches it."""

    def test_a_show_click_shows(self):
        p = pill(_hidden=True)
        p._tray_events.put(tray.SHOW)
        p._drain_tray()
        self.assertFalse(p._hidden)

    def test_a_quit_click_quits(self):
        p = pill()
        p._tray_events.put(tray.QUIT)
        p._drain_tray()
        p.quit_app.assert_called_once()

    def test_an_empty_queue_is_the_ordinary_case_and_costs_nothing(self):
        p = pill()
        p._drain_tray()
        p.quit_app.assert_not_called()

    def test_everything_waiting_is_taken_in_one_pass(self):
        # The queue is drained, not sampled: a frame that took one event and left the
        # rest would answer a click a frame late for every click before it.
        p = pill(_hidden=True)
        for _ in range(3):
            p._tray_events.put(tray.SHOW)
        p._drain_tray()
        self.assertTrue(p._tray_events.empty())


class TestTheModule(unittest.TestCase):
    def test_it_is_windows_only_and_says_so(self):
        for platform, expected in (("win32", True), ("darwin", False), ("linux", False)):
            with self.subTest(platform=platform):
                with mock.patch.object(sys, "platform", platform):
                    self.assertIs(tray.available(), expected)

    def test_stopping_an_icon_that_never_started_is_safe(self):
        # `quit_app` calls this unconditionally, including after a `hide_to_tray` that
        # was refused.
        icon = tray.Tray("probe")
        icon.stop()
        self.assertEqual(icon.hwnd, 0)

    def test_starting_twice_returns_the_first_answer(self):
        icon = tray.Tray("probe")
        icon._thread = mock.Mock()
        icon._ok = True
        self.assertTrue(icon.start())

    @unittest.skipUnless(sys.platform == "win32", "Windows-only: Shell_NotifyIconW")
    def test_the_struct_is_the_size_the_shell_expects(self):
        # `cbSize` is how the shell knows which layout it has been handed, and it is
        # `sizeof` rather than a number typed in — this asserts the field is wired to
        # the struct at all.
        icon = tray.Tray("probe")
        import ctypes

        self.assertEqual(icon._icon_data().cbSize,
                         ctypes.sizeof(tray._NOTIFYICONDATAW))

    def test_the_window_procedure_is_held_alive(self):
        """A ctypes callback is garbage like anything else, and one collected while
        Windows still holds its address is an access violation on a thread nobody is
        watching."""
        icon = tray.Tray("probe")
        self.assertIsNotNone(icon._proc)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
