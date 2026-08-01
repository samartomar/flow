"""Tests for terminal-safe paste (P7), and for pasting into the right window at all.

The failure P7 prevents is the loudest one Flow can cause: a draft ending in a newline,
pasted into a shell, runs. Everything here is about the target — which window is being
pasted into decides what is safe to send, and where nothing can be guaranteed the user
is told rather than surprised.

Which window that *is* is the other half, and it was wrong for the whole life of the
app: `paste()` asked what had the foreground at the moment it ran, which is after the
click that started the Send. The answer was Flow's own window, so P7 was deciding about
a Tk canvas and the guarantee above was never once exercised on the Send chip's path.
"""

import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.inject import (  # noqa: E402
    BRACKETED_PASTE,
    TERMINAL_CLASSES,
    TERMINAL_PROCESSES,
    Target,
    clipboard_sequence,
    prepare,
    resolve,
    take_warnings,
)

WT = Target("CASCADIA_HOSTING_WINDOW_CLASS", "WindowsTerminal.exe")
CMD = Target("ConsoleWindowClass", "cmd.exe")
BASH = Target("mintty", "mintty.exe")
EDITOR = Target("Chrome_WidgetWin_1", "Code.exe")
UNKNOWN = Target()
FLOW = Target("TkTopLevel", "python.exe", is_flow=True)


class TestClassification(unittest.TestCase):
    def test_terminals_are_recognised_by_class_or_process(self):
        for target in (WT, CMD, BASH):
            with self.subTest(target=target):
                self.assertTrue(target.is_terminal)

    def test_an_editor_is_not_a_terminal(self):
        self.assertFalse(EDITOR.is_terminal)

    def test_an_unknown_window_is_treated_as_ordinary(self):
        # The behaviour Flow had before any of this: no classification, no change.
        self.assertFalse(UNKNOWN.is_terminal)
        self.assertEqual(prepare("hello\n", UNKNOWN), ("hello\n", ""))

    def test_class_matching_is_case_insensitive(self):
        self.assertTrue(Target("consolewindowclass", "").is_terminal)
        self.assertTrue(Target("CONSOLEWINDOWCLASS", "").is_terminal)

    def test_bracketed_paste_is_a_property_of_the_terminal(self):
        self.assertTrue(WT.brackets_paste)
        self.assertTrue(BASH.brackets_paste)
        self.assertFalse(CMD.brackets_paste)

    def test_the_tables_are_lowercase_so_matching_works(self):
        for table in (TERMINAL_CLASSES, TERMINAL_PROCESSES, BRACKETED_PASTE):
            for entry in table:
                self.assertEqual(entry, entry.lower(), entry)

    def test_every_bracketed_terminal_is_also_a_terminal(self):
        for process in BRACKETED_PASTE:
            with self.subTest(process=process):
                self.assertIn(process, TERMINAL_PROCESSES)


class TestPrepare(unittest.TestCase):
    def test_the_guarantee_a_trailing_newline_never_reaches_a_shell(self):
        for target in (WT, CMD, BASH):
            with self.subTest(target=target):
                payload, _ = prepare("deploy the thing\n", target)
                self.assertEqual(payload, "deploy the thing")

    def test_several_trailing_newlines_all_go(self):
        payload, _ = prepare("one\ntwo\n\r\n\n", CMD)
        self.assertEqual(payload, "one\ntwo")

    def test_interior_newlines_are_never_touched(self):
        # Flow does not get to rewrite the user's text to make it safe.
        payload, _ = prepare("line one\nline two\nline three\n", CMD)
        self.assertEqual(payload, "line one\nline two\nline three")

    def test_a_non_terminal_keeps_its_trailing_newline(self):
        payload, warning = prepare("a paragraph\n", EDITOR)
        self.assertEqual(payload, "a paragraph\n")
        self.assertEqual(warning, "")

    def test_a_legacy_console_warns_about_multiple_lines(self):
        _, warning = prepare("one\ntwo", CMD)
        self.assertIn("cmd.exe", warning)
        self.assertIn("each line", warning)

    def test_a_bracketing_terminal_does_not_warn(self):
        self.assertEqual(prepare("one\ntwo", WT)[1], "")

    def test_a_single_line_never_warns(self):
        for target in (WT, CMD, BASH):
            with self.subTest(target=target):
                self.assertEqual(prepare("just one line\n", target)[1], "")

    def test_empty_text(self):
        self.assertEqual(prepare("", CMD), ("", ""))


class TestResolve(unittest.TestCase):
    """Which window a paste is aimed at, given what the caller tracked."""

    def _resolve(self, live, tracked=None, windows=None, live_hwnd=0x11):
        """`live` is what the OS reports; `windows` maps hwnd -> Target."""
        table = {live_hwnd: live, **(windows or {})}
        with mock.patch("flow.inject.foreground_hwnd", return_value=live_hwnd), \
             mock.patch("flow.inject.classify", side_effect=lambda h: table.get(h, UNKNOWN)):
            return resolve(tracked)

    def test_with_nothing_tracked_it_is_whatever_has_the_foreground(self):
        self.assertIs(self._resolve(EDITOR), EDITOR)

    def test_the_tracked_window_is_what_gets_classified(self):
        # The caller polled this 30 ms before the click and the window still holds the
        # foreground, so its own classification is the one P7 acts on.
        got = self._resolve(CMD, tracked=0x11, windows={0x11: CMD})
        self.assertIs(got, CMD)
        self.assertFalse(got.stale)

    def test_flow_in_the_foreground_is_a_refusal_whatever_was_tracked(self):
        # If Flow really has the focus, the Ctrl-V lands on Flow no matter what the
        # caller believes, so the tracked window must not be allowed to paper over it.
        got = self._resolve(FLOW, tracked=0x22, windows={0x22: CMD})
        self.assertTrue(got.is_flow)

    def test_no_foreground_at_all_falls_back_to_the_tracked_window(self):
        # Refusing here would be refusing on the *absence* of evidence. `0` means the
        # OS would not say, not that somebody else is holding it.
        with mock.patch("flow.inject.foreground_hwnd", return_value=0), \
             mock.patch("flow.inject.classify",
                        side_effect=lambda h: CMD if h == 0x22 else UNKNOWN):
            got = resolve(0x22)
        self.assertIs(got, CMD)
        self.assertFalse(got.stale)


class TestTheTargetIsRevalidatedAtPasteTime(unittest.TestCase):
    """A third window taking the foreground between the poll and the click.

    `resolve()` refused when *Flow* held the foreground and trusted the caller for
    everything else, so anything else that took focus in those 30 ms — a notification,
    a switcher, an installer finishing — received the draft. And received it prepared
    for a different window: the newline strip that is P7's one guarantee was decided
    against a terminal the keystroke was never going to reach.

    The caller's window is now a claim to check rather than an answer to trust. It is
    still the thing that makes Send aimable; what it aims at is confirmed at the last
    moment it can be.
    """

    def _resolve(self, live, tracked, live_hwnd=0x33):
        table = {live_hwnd: live, 0x22: CMD}
        with mock.patch("flow.inject.foreground_hwnd", return_value=live_hwnd), \
             mock.patch("flow.inject.classify",
                        side_effect=lambda h: table.get(h, UNKNOWN)):
            return resolve(tracked)

    def test_a_third_window_holding_the_foreground_is_a_refusal(self):
        got = self._resolve(EDITOR, tracked=0x22)
        self.assertTrue(got.stale, "the paste would have gone to the wrong window")

    def test_the_refusal_names_what_actually_has_the_focus(self):
        # So the note can say where the words would have gone, not just that they did
        # not go where they were meant to.
        self.assertEqual(self._resolve(EDITOR, tracked=0x22).process, "Code.exe")

    def test_paste_refuses_and_says_the_target_changed(self):
        take_warnings()
        with mock.patch("flow.inject.foreground_hwnd", return_value=0x33), \
             mock.patch("flow.inject.classify",
                        side_effect=lambda h: CMD if h == 0x22 else EDITOR), \
             mock.patch("flow.inject.get_clipboard_text", return_value=None), \
             mock.patch("flow.inject.set_clipboard_text", return_value=True) as put, \
             mock.patch("flow.inject._send", return_value=1) as sent:
            from flow.inject import paste

            ok = paste("deploy it\n", hwnd=0x22, restore_clipboard=False)
        warnings = take_warnings()
        self.assertFalse(ok)
        self.assertEqual(len(warnings), 1)
        self.assertIn("target window changed", warnings[0])
        # A refusal that still wrote the clipboard and typed Ctrl-V would be the same
        # defect with a message attached — the same thing invariant 10 already demands.
        put.assert_not_called()
        sent.assert_not_called()

    def test_the_paste_still_happens_when_the_window_stayed_put(self):
        take_warnings()
        with mock.patch("flow.inject.foreground_hwnd", return_value=0x22), \
             mock.patch("flow.inject.classify",
                        side_effect=lambda h: CMD if h == 0x22 else EDITOR), \
             mock.patch("flow.inject.get_clipboard_text", return_value=None), \
             mock.patch("flow.inject.set_clipboard_text", return_value=True) as put, \
             mock.patch("flow.inject._send", return_value=1):
            from flow.inject import paste

            ok = paste("deploy it\n", hwnd=0x22, restore_clipboard=False)
        self.assertTrue(ok)
        self.assertEqual(put.call_args.args[0], "deploy it")
        self.assertEqual(take_warnings(), [])


class TestPasteUsesTheTarget(unittest.TestCase):
    def _paste(self, text, target):
        take_warnings()  # start clean
        with mock.patch("flow.inject.resolve", return_value=target), \
             mock.patch("flow.inject.get_clipboard_text", return_value=None), \
             mock.patch("flow.inject.set_clipboard_text", return_value=True) as put, \
             mock.patch("flow.inject._send", return_value=1):
            from flow.inject import paste

            ok = paste(text, restore_clipboard=False)
        written = put.call_args.args[0] if put.call_args else None
        return ok, written, take_warnings()

    def test_what_lands_on_the_clipboard_is_the_prepared_payload(self):
        ok, written, warnings = self._paste("deploy it\n", CMD)
        self.assertTrue(ok)
        self.assertEqual(written, "deploy it")
        self.assertEqual(warnings, [])

    def test_a_multi_line_paste_into_a_legacy_console_warns(self):
        _ok, written, warnings = self._paste("one\ntwo\n", CMD)
        self.assertEqual(written, "one\ntwo")
        self.assertEqual(len(warnings), 1)
        self.assertIn("each line", warnings[0])

    def test_pasting_into_an_editor_is_unchanged(self):
        _ok, written, warnings = self._paste("a paragraph\n", EDITOR)
        self.assertEqual(written, "a paragraph\n")
        self.assertEqual(warnings, [])

    def test_warnings_drain(self):
        self._paste("one\ntwo\n", CMD)
        self.assertEqual(take_warnings(), [])

    def test_the_window_the_caller_names_is_the_one_classified(self):
        """The fix, end to end through `paste`: a named terminal gets P7 applied.

        Before, this could only ever be reached by the hotkey path. The chip path
        classified Flow's own window — not a terminal — so the newline survived.
        """
        take_warnings()
        with mock.patch("flow.inject.foreground_hwnd", return_value=0x22), \
             mock.patch("flow.inject.classify",
                        side_effect=lambda h: CMD if h == 0x22 else EDITOR), \
             mock.patch("flow.inject.get_clipboard_text", return_value=None), \
             mock.patch("flow.inject.set_clipboard_text", return_value=True) as put, \
             mock.patch("flow.inject._send", return_value=1):
            from flow.inject import paste

            ok = paste("deploy it\n", hwnd=0x22, restore_clipboard=False)
        self.assertTrue(ok)
        self.assertEqual(put.call_args.args[0], "deploy it")


class TestFlowNeverPastesIntoItself(unittest.TestCase):
    """Invariant: Flow does not paste into its own window.

    This is the state that used to return True with nothing pasted anywhere, which is
    the reason the defect survived — the failure was completely silent.
    """

    def _paste_into_flow(self):
        take_warnings()
        with mock.patch("flow.inject.resolve", return_value=FLOW), \
             mock.patch("flow.inject.get_clipboard_text", return_value=None), \
             mock.patch("flow.inject.set_clipboard_text", return_value=True) as put, \
             mock.patch("flow.inject._send", return_value=1) as sent:
            from flow.inject import paste

            ok = paste("some words", restore_clipboard=False)
        return ok, put, sent, take_warnings()

    def test_it_refuses(self):
        ok, _put, _sent, _warnings = self._paste_into_flow()
        self.assertFalse(ok)

    def test_it_says_why(self):
        _ok, _put, _sent, warnings = self._paste_into_flow()
        self.assertEqual(len(warnings), 1)
        self.assertIn("Flow had the focus", warnings[0])

    def test_it_touches_neither_the_clipboard_nor_the_keyboard(self):
        # A refusal that still typed Ctrl-V into Flow would be the same defect with a
        # message attached.
        _ok, put, sent, _warnings = self._paste_into_flow()
        put.assert_not_called()
        sent.assert_not_called()

    def test_a_clipboard_failure_also_says_why(self):
        take_warnings()
        with mock.patch("flow.inject.resolve", return_value=EDITOR), \
             mock.patch("flow.inject.get_clipboard_text", return_value=None), \
             mock.patch("flow.inject.set_clipboard_text", return_value=False), \
             mock.patch("flow.inject._send", return_value=1):
            from flow.inject import paste

            ok = paste("some words", restore_clipboard=False)
        warnings = take_warnings()
        self.assertFalse(ok)
        self.assertEqual(len(warnings), 1)
        self.assertIn("clipboard", warnings[0])


class TestTheClipboardIsGivenBackOnlyIfNobodyElseTookIt(unittest.TestCase):
    """Flow borrows the clipboard for one paste and hands it back 0.6 s later.

    It used to hand it back unconditionally. Six hundred milliseconds is long enough to
    copy something — it is a keystroke, and the reason the pause exists is that people
    are doing things — and the write that followed did not restore anything. It deleted
    what the user had just copied and replaced it with what they had copied before, the
    one clipboard write nothing on screen could account for.
    """

    def _paste(self, sequences, previous="what the user had"):
        """Paste and let the restore run. `sequences` are the counter's readings:
        the first when Flow's text lands, the second after the pause."""
        take_warnings()
        writes: list[str] = []
        with mock.patch("flow.inject.resolve", return_value=EDITOR), \
             mock.patch("flow.inject.RESTORE_DELAY_SEC", 0.0), \
             mock.patch("flow.inject.clipboard_sequence", side_effect=sequences), \
             mock.patch("flow.inject.get_clipboard_text", return_value=previous), \
             mock.patch("flow.inject.set_clipboard_text",
                        side_effect=lambda t: (writes.append(t), True)[1]), \
             mock.patch("flow.inject._send", return_value=1):
            from flow.inject import paste

            paste("deploy it", restore_clipboard=True)
            # The thread is registered by the time `start()` returns, so it is either
            # here to be joined or already finished. Either way this is not a sleep.
            for t in threading.enumerate():
                if t.name == "clipboard-restore":
                    t.join(5.0)
        return writes, take_warnings()

    def test_an_untouched_clipboard_is_put_back(self):
        writes, warnings = self._paste([7, 7])
        self.assertEqual(writes, ["deploy it", "what the user had"])
        self.assertEqual(warnings, [])

    def test_something_copied_during_the_pause_is_kept(self):
        writes, _warnings = self._paste([7, 8])
        self.assertEqual(writes, ["deploy it"], "the user's newer clipboard was erased")

    def test_and_the_skip_is_said_out_loud(self):
        _writes, warnings = self._paste([7, 8])
        self.assertEqual(len(warnings), 1)
        self.assertIn("kept what you copied", warnings[0])

    def test_a_counter_that_will_not_answer_restores_as_before(self):
        # Zero means the OS declined to say, not that nothing happened. Refusing to
        # restore on the absence of evidence would lose the clipboard it exists to save.
        writes, warnings = self._paste([0, 0])
        self.assertEqual(writes, ["deploy it", "what the user had"])
        self.assertEqual(warnings, [])

    def test_an_empty_clipboard_starts_no_restore_at_all(self):
        writes, warnings = self._paste([7, 7], previous=None)
        self.assertEqual(writes, ["deploy it"])
        self.assertEqual(warnings, [])

    def test_the_counter_never_raises(self):
        self.assertIsInstance(clipboard_sequence(), int)

    def test_a_warning_from_the_restore_thread_is_not_lost(self):
        # `take_warnings` copies and then clears, and the restore appends from another
        # thread 0.6 s after paste() returned. Without the lock a line landing between
        # those two statements would vanish.
        from flow.inject import _warn

        take_warnings()
        stop = threading.Event()

        def drain() -> None:
            while not stop.is_set():
                seen.extend(take_warnings())

        seen: list[str] = []
        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        for i in range(2000):
            _warn(f"line {i}")
        stop.set()
        reader.join(5.0)
        seen.extend(take_warnings())
        self.assertEqual(len(seen), 2000)


if __name__ == "__main__":
    unittest.main()


class TestLateWarningsReachTheBubble(unittest.TestCase):
    """A warning raised after `paste()` returns must not wait for the next Send.

    The clipboard-restore thread records its skip 0.6 s after the paste it belongs
    to, and every caller drains `take_warnings()` on the line after the paste — so
    the line used to sit in the queue and be shown against the *following* paste.
    The fix is a per-frame drain on the UI thread; this pins the drain itself.
    """

    def test_a_late_warning_is_drained_by_the_next_frame(self):
        from unittest import mock as _mock

        import flow.ui as ui
        from flow import inject as _inject

        pill = ui.Pill.__new__(ui.Pill)  # the method under test needs no Tk window
        pill.bubble = _mock.Mock()
        pill._flash = 0
        with _inject._WARNINGS_LOCK:
            _inject._WARNINGS.append("clipboard left alone - you copied during restore")
        pill._pump_warnings()
        pill.bubble.note.assert_called_once()
        self.assertTrue(pill._flash, "a warning deserves the same flash an error gets")
        pill.bubble.note.reset_mock()
        pill._pump_warnings()
        pill.bubble.note.assert_not_called()
