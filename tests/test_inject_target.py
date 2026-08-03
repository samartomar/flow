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

import contextlib
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows-only: ctypes.WinDLL, bound at import.
#
# The guard has to be here rather than on the classes below, because `flow.inject` calls
# `ctypes.WinDLL("user32", use_last_error=True)` at module scope — so the failure is the
# `from` on the next line, before any test exists to decorate. Deliberate over there: the
# whole module is Win32, and a lazily-bound user32 would only move the same import error
# to the first paste.
if sys.platform != "win32":  # pragma: no cover - the CI legs that are not Windows
    raise unittest.SkipTest("Windows-only: flow.inject binds user32 at import")

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


def all_inserted(*events):
    """A `SendInput` that accepts everything, which is what the real one returns.

    The audit named this module's mocks as a finding in their own right, and it was
    right to: every one of them was `return_value=1`, so a four-event Ctrl-V burst
    reported **one** event inserted and the tests called that a success. That is not a
    lax fake, it is a fake of the failure — one of four is precisely the partial paste
    DESKTOP-02 is about, and the suite was green on it for the life of the file.
    """
    return len(events)


def none_inserted(*_events):
    """A `SendInput` the OS refused outright. Zero is what UIPI denial looks like."""
    return 0


def only(n: int):
    """A `SendInput` that accepts `n` of however many events it was given."""
    return lambda *events: min(n, len(events))


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
             mock.patch("flow.inject._send", side_effect=all_inserted) as sent:
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
             mock.patch("flow.inject._send", side_effect=all_inserted):
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
             mock.patch("flow.inject._send", side_effect=all_inserted):
            from flow.inject import paste

            ok = paste(text, restore_clipboard=False)
        written = put.call_args.args[0] if put.call_args else None
        return ok, written, take_warnings()

    def test_what_lands_on_the_clipboard_is_the_prepared_payload(self):
        ok, written, warnings = self._paste("deploy it\n", CMD)
        self.assertTrue(ok)
        self.assertEqual(written, "deploy it")
        self.assertEqual(warnings, [])

    def test_a_multi_line_paste_into_a_legacy_console_is_refused(self):
        # This asserted warn-**and-proceed** until 2026-08-03, and it was the audit's
        # DESKTOP-01: the warning it checked for is delivered through a queue the UI
        # drains on its next frame, while the Ctrl-V it did not prevent had already run
        # the first line. A message that arrives after the thing it warns about is not a
        # warning. The clipboard write survives the inversion on purpose — see the class
        # below for why that is the whole recovery.
        ok, written, warnings = self._paste("one\ntwo\n", CMD)
        self.assertFalse(ok)
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
             mock.patch("flow.inject._send", side_effect=all_inserted):
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
             mock.patch("flow.inject._send", side_effect=all_inserted) as sent:
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
             mock.patch("flow.inject._send", side_effect=all_inserted):
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
             mock.patch("flow.inject._send", side_effect=all_inserted):
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


class TestEnterIsEarnedByACompletePaste(unittest.TestCase):
    """DESKTOP-02: the Ctrl-V result was computed, returned, and thrown away.

    `_send` has always returned `SendInput`'s count and both call sites ignored it, so a
    Ctrl-V that inserted nothing — UIPI denial against an elevated window is the ordinary
    way — was followed by Enter anyway. Into a shell, that runs whatever was already
    sitting on the prompt. It is the exact failure P7 exists to prevent, arriving one
    layer below where P7 looks: P7 asks what the target is and strips the newline, and
    this is the keystroke going in after the payload did not.

    The recovery is the one `paste()` already promises in its docstring for the UIPI
    case: the text stays on the clipboard, so Ctrl-V by hand works.
    """

    def _paste(self, sender, *, submit=True, hwnd=0x22, live=None):
        take_warnings()
        live = hwnd if live is None else live
        with mock.patch("flow.inject.foreground_hwnd", return_value=live), \
                mock.patch("flow.inject.classify",
                           side_effect=lambda h: CMD if h == 0x22 else EDITOR), \
                mock.patch("flow.inject.get_clipboard_text", return_value=None), \
                mock.patch("flow.inject.set_clipboard_text", return_value=True) as put, \
                mock.patch("flow.inject._send", side_effect=sender) as sent:
            from flow.inject import paste

            ok = paste("deploy it", hwnd=hwnd, submit=submit, restore_clipboard=False)
        return ok, sent, put, take_warnings()

    def test_a_refused_paste_sends_no_enter(self):
        ok, sent, _put, warnings = self._paste(none_inserted)
        self.assertFalse(ok)
        self.assertEqual(sent.call_count, 1, "Enter followed a paste that did not land")
        self.assertEqual(len(warnings), 1)
        self.assertIn("0 of 4", warnings[0])

    def test_every_partial_count_is_a_failed_paste(self):
        for n in (1, 2, 3):
            with self.subTest(inserted=n):
                ok, sent, _put, warnings = self._paste(only(n))
                self.assertFalse(ok)
                self.assertEqual(sent.call_count, 1)
                self.assertIn(f"{n} of 4", warnings[0])

    def test_the_warning_says_the_text_is_still_recoverable(self):
        # The payload is deliberately left on the clipboard rather than restored: the
        # whole recovery for a refused keystroke is the user pressing Ctrl-V themselves,
        # and a restore would take the thing they need to press it on.
        _ok, _sent, put, warnings = self._paste(none_inserted)
        self.assertEqual(put.call_args.args[0], "deploy it")
        self.assertIn("Ctrl-V", warnings[0])

    def test_a_complete_paste_still_submits(self):
        ok, sent, _put, warnings = self._paste(all_inserted)
        self.assertTrue(ok)
        self.assertEqual(sent.call_count, 2, "the Enter burst never went")
        self.assertEqual(warnings, [])

    def test_a_complete_paste_without_submit_sends_one_burst(self):
        ok, sent, _put, warnings = self._paste(all_inserted, submit=False)
        self.assertTrue(ok)
        self.assertEqual(sent.call_count, 1)
        self.assertEqual(warnings, [])


class TestTheTargetIsCheckedAgainBeforeEnter(unittest.TestCase):
    """The paste's refusals ran a queue-latency ago, and Enter is the irreversible half.

    `resolve()` is asked before the clipboard is touched, which is right — the answer
    decides the payload. But between that check and the Enter burst sit a clipboard
    write, a `SendInput`, and however long Windows took to deliver it. A window that
    takes the foreground inside that gap receives a bare Enter, and the paste it would be
    submitting is not there.
    """

    def _submit_with(self, live_at_paste, live_at_enter):
        take_warnings()
        answers = iter((live_at_paste, live_at_enter, live_at_enter))
        with mock.patch("flow.inject.foreground_hwnd",
                        side_effect=lambda: next(answers, live_at_enter)), \
                mock.patch("flow.inject.classify",
                           side_effect=lambda h: CMD if h == 0x22 else EDITOR), \
                mock.patch("flow.inject.get_clipboard_text", return_value=None), \
                mock.patch("flow.inject.set_clipboard_text", return_value=True), \
                mock.patch("flow.inject._send", side_effect=all_inserted) as sent:
            from flow.inject import paste

            ok = paste("deploy it", hwnd=0x22, submit=True, restore_clipboard=False)
        return ok, sent, take_warnings()

    def test_a_window_that_arrives_after_the_paste_gets_no_enter(self):
        ok, sent, warnings = self._submit_with(0x22, 0x33)
        self.assertTrue(ok, "the paste itself did land, and saying otherwise is a lie")
        self.assertEqual(sent.call_count, 1, "a bare Enter went to the wrong window")
        self.assertEqual(len(warnings), 1)
        self.assertIn("not submitted", warnings[0])

    def test_the_refusal_names_who_took_the_focus(self):
        _ok, _sent, warnings = self._submit_with(0x22, 0x33)
        self.assertIn("Code.exe", warnings[0])

    def test_the_window_staying_put_submits(self):
        ok, sent, warnings = self._submit_with(0x22, 0x22)
        self.assertTrue(ok)
        self.assertEqual(sent.call_count, 2)
        self.assertEqual(warnings, [])


class TestEnterHasItsOwnCount(unittest.TestCase):
    """The second burst is checked like the first, and the failure is a different one.

    A refused paste means nothing arrived. A refused *Enter* means the text is sitting in
    the target unsubmitted, which is recoverable by pressing a key and is not a reason to
    report the Send as failed — so this warns and still returns True.
    """

    def test_a_partial_enter_warns_without_calling_the_paste_a_failure(self):
        take_warnings()
        bursts = iter((4, 1))
        with mock.patch("flow.inject.foreground_hwnd", return_value=0x22), \
                mock.patch("flow.inject.classify", side_effect=lambda h: CMD), \
                mock.patch("flow.inject.get_clipboard_text", return_value=None), \
                mock.patch("flow.inject.set_clipboard_text", return_value=True), \
                mock.patch("flow.inject._send",
                           side_effect=lambda *e: next(bursts, len(e))):
            from flow.inject import paste

            ok = paste("deploy it", hwnd=0x22, submit=True, restore_clipboard=False)
        warnings = take_warnings()
        self.assertTrue(ok, "the text is in the window; only the Enter is missing")
        self.assertEqual(len(warnings), 1)
        self.assertIn("1 of 2", warnings[0])


class TestABareTerminalIsRefusedRatherThanWarned(unittest.TestCase):
    """DESKTOP-01: the warning arrived after the lines it warned about had run.

    A terminal without bracketed paste hands each line to the shell as it arrives, so an
    interior newline in a multiline payload is a command executing at the moment of the
    Ctrl-V. Flow's warning goes into `take_warnings()`, which the pill drains on its next
    30 ms frame and paints into the bubble — by which time the shell has run the first
    line and is working on the second. Warn-and-proceed was never a mitigation here; it
    was a description written after the fact.

    So it inverts. The payload still reaches the clipboard, and that is the entire
    recovery: pasting it by hand is the same keystroke Flow declined to synthesise, and
    doing it deliberately is exactly the difference. Flow does not get to decide the user
    may never paste a script into cmd.exe — only that it will not do it *for* them
    without their hand on the key.
    """

    def _paste(self, text, target, **kw):
        take_warnings()
        with mock.patch("flow.inject.resolve", return_value=target), \
                mock.patch("flow.inject.get_clipboard_text", return_value=None), \
                mock.patch("flow.inject.set_clipboard_text",
                           return_value=True) as put, \
                mock.patch("flow.inject._send", side_effect=all_inserted) as sent:
            from flow.inject import paste

            ok = paste(text, restore_clipboard=False, **kw)
        written = put.call_args.args[0] if put.call_args else None
        return ok, written, sent, take_warnings()

    def test_multiline_into_a_bare_console_never_reaches_ctrl_v(self):
        ok, _written, sent, warnings = self._paste("one\ntwo\n", CMD)
        self.assertFalse(ok)
        sent.assert_not_called()
        self.assertIn("not pasted", warnings[0])

    def test_the_payload_is_left_where_a_hand_can_reach_it(self):
        _ok, written, _sent, warnings = self._paste("one\ntwo\n", CMD)
        self.assertEqual(written, "one\ntwo")
        self.assertIn("Ctrl-V", warnings[0])

    def test_the_refusal_names_the_terminal_and_the_reason(self):
        # A second bare terminal, so the refusal is shown reading the target rather than
        # matching one name. `BASH` is the wrong fixture for this and picking it was the
        # instrument's own mistake: mintty is *in* `BRACKETED_PASTE`, so it is the
        # untouched case one class over, not a refusal.
        console = Target("ConsoleWindowClass", "powershell.exe")
        _ok, _written, _sent, warnings = self._paste("one\ntwo\n", console)
        self.assertIn("powershell.exe", warnings[0])
        self.assertIn("each line", warnings[0])

    def test_mintty_brackets_and_so_is_not_refused(self):
        ok, _written, sent, warnings = self._paste("one\ntwo\n", BASH)
        self.assertTrue(ok)
        self.assertEqual(sent.call_count, 1)
        self.assertEqual(warnings, [])

    def test_a_bracketing_terminal_is_untouched(self):
        # Windows Terminal hands the whole block to the shell as literal text, so there
        # is nothing to fail closed about. Refusing here would be Flow taking a working
        # path away on a hazard that does not exist in it.
        ok, written, sent, warnings = self._paste("one\ntwo\n", WT)
        self.assertTrue(ok)
        self.assertEqual(written, "one\ntwo")
        self.assertEqual(sent.call_count, 1)
        self.assertEqual(warnings, [])

    def test_a_single_line_into_a_bare_console_is_untouched(self):
        # The common case, and the one the whole feature exists for: one dictated
        # sentence into cmd.exe, trailing newline stripped by P7, Ctrl-V sent.
        ok, written, sent, warnings = self._paste("deploy the thing\n", CMD)
        self.assertTrue(ok)
        self.assertEqual(written, "deploy the thing")
        self.assertEqual(sent.call_count, 1)
        self.assertEqual(warnings, [])

    def test_multiline_into_an_editor_is_untouched(self):
        ok, written, sent, warnings = self._paste("a\nparagraph\n", EDITOR)
        self.assertTrue(ok)
        self.assertEqual(written, "a\nparagraph\n", "an editor keeps its newline too")
        self.assertEqual(sent.call_count, 1)
        self.assertEqual(warnings, [])

    def test_the_refusal_holds_even_when_submit_was_asked_for(self):
        # `submit=True` is the enter-variant trigger, and it is the worst version of this
        # case rather than an exception to it: the payload would run its interior lines on
        # arrival and then be submitted on top.
        ok, _written, sent, _warnings = self._paste("one\ntwo\n", CMD, submit=True)
        self.assertFalse(ok)
        sent.assert_not_called()

    def test_trailing_newlines_alone_are_not_multiline(self):
        # "one\n\n\n" is a single line with P7's strip applied. Treating it as multiline
        # would refuse the ordinary dictated sentence, which is the failure mode a
        # fail-closed rule has to be checked against.
        ok, written, _sent, warnings = self._paste("one\n\r\n\n", CMD)
        self.assertTrue(ok)
        self.assertEqual(written, "one")
        self.assertEqual(warnings, [])


class TestWhatRunsOnArrivalIsAskedInOnePlace(unittest.TestCase):
    """`prepare` and `paste` must not each decide this, or they will drift apart.

    `prepare` describes the hazard for the two probe scripts that print it; `paste` acts
    on it. One predicate underneath both, so a terminal added to `BRACKETED_PASTE` cannot
    stop the warning while leaving the refusal, or the reverse.
    """

    def test_the_predicate_agrees_with_the_warning(self):
        from flow.inject import prepare, runs_on_arrival

        for text, target in (("one\ntwo", CMD), ("one\ntwo", BASH), ("one\ntwo", WT),
                             ("one", CMD), ("a\nb", EDITOR), ("", CMD)):
            with self.subTest(text=text, target=target):
                payload, warning = prepare(text, target)
                self.assertEqual(bool(warning), runs_on_arrival(payload, target))

    def test_an_unknown_window_is_not_a_terminal_and_not_refused(self):
        from flow.inject import runs_on_arrival

        self.assertFalse(runs_on_arrival("one\ntwo", UNKNOWN))


class FakeClipboard:
    """A clipboard with a sequence counter that moves when it is written.

    The counter is the point. `clipboard_sequence` is Flow's only way to ask "does this
    still hold what I put there", and the DESKTOP-04 defect is invisible to it: when send
    B overwrites send A's payload the counter *does* move, but it moved because of Flow.
    A fake that let the two be told apart would not be reproducing the bug.
    """

    def __init__(self, text="what the user had"):
        self.text = text
        self.seq = 1
        self.writes: list[str] = []

    def get(self):
        return self.text

    def put(self, text):
        self.text = text
        self.seq += 1
        self.writes.append(text)
        return True

    def sequence(self):
        return self.seq

    def patches(self, delay=0.05):
        return (
            mock.patch("flow.inject.resolve", return_value=EDITOR),
            mock.patch("flow.inject.RESTORE_DELAY_SEC", delay),
            mock.patch("flow.inject.get_clipboard_text", side_effect=self.get),
            mock.patch("flow.inject.set_clipboard_text", side_effect=self.put),
            mock.patch("flow.inject.clipboard_sequence", side_effect=self.sequence),
            mock.patch("flow.inject._send", side_effect=all_inserted),
        )


def restore_threads():
    return [t for t in threading.enumerate() if t.name == "clipboard-restore"]


def settle(timeout=5.0):
    """Wait for every restore worker to finish. Not a sleep — they are joinable."""
    for t in restore_threads():
        t.join(timeout)


class TestTwoSendsAreOneClipboardTransaction(unittest.TestCase):
    """DESKTOP-04 as the validation corrected it: Flow racing itself, not a stale timer.

    The sequence stamp already stops an old restore from landing on a newer one, and it
    already keeps a copy the user made during the pause. What it cannot see is the other
    send being Flow's. Send B read the clipboard to find out what it owed back, at a
    moment when the clipboard held **send A's payload**, so B faithfully restored Flow's
    own text and the user's real clipboard was gone for good — no warning, because from
    B's point of view nothing anomalous had happened.

    The fix is that there is one borrowing, not one per send: a send arriving while a
    restore is pending inherits what is already owed instead of asking the clipboard.
    """

    def _send_twice(self, delay=0.2):
        clip = FakeClipboard()
        with contextlib.ExitStack() as stack:
            for p in clip.patches(delay):
                stack.enter_context(p)
            from flow.inject import paste

            paste("send A text", restore_clipboard=True)
            paste("send B text", restore_clipboard=True)
            settle()
        return clip

    def test_the_users_clipboard_comes_back_and_not_flows(self):
        clip = self._send_twice()
        self.assertEqual(clip.text, "what the user had")
        self.assertNotIn("send A text", clip.writes[-1:])

    def test_flows_own_payload_is_never_restored(self):
        # The sharp assertion, and the one that fails loudest against the old code: the
        # last thing written must not be something Flow put there itself.
        clip = self._send_twice()
        self.assertNotIn(clip.writes[-1], ("send A text", "send B text"))

    def test_both_payloads_still_reached_the_clipboard_in_order(self):
        # The fix must not become "the second send does not paste".
        clip = self._send_twice()
        self.assertEqual(clip.writes[:2], ["send A text", "send B text"])

    def test_a_burst_of_five_restores_once(self):
        clip = FakeClipboard()
        with contextlib.ExitStack() as stack:
            for p in clip.patches(0.2):
                stack.enter_context(p)
            from flow.inject import paste

            for i in range(5):
                paste(f"payload {i}", restore_clipboard=True)
            settle()
        self.assertEqual(clip.text, "what the user had")
        self.assertEqual(clip.writes.count("what the user had"), 1,
                         "the restore ran more than once")


class TestOneRestoreWorkerWhateverTheSendRate(unittest.TestCase):
    """DESKTOP-09: every send parked its own sleeping thread.

    Measured by the audit at 300 threads for 300 rapid pastes, alive together until
    their 600 ms delays expired. A generation the single worker re-reads when it wakes
    does the same job — and it is the same mechanism as the class above rather than a
    second one, which is why the two findings are one item.
    """

    def test_a_hundred_rapid_sends_keep_one_worker(self):
        clip = FakeClipboard()
        peak = 0
        with contextlib.ExitStack() as stack:
            for p in clip.patches(3.0):  # long enough that none can retire mid-burst
                stack.enter_context(p)
            from flow.inject import paste

            for i in range(100):
                paste(f"payload {i}", restore_clipboard=True)
                peak = max(peak, len(restore_threads()))
            with mock.patch("flow.inject.RESTORE_DELAY_SEC", 0.0):
                paste("last", restore_clipboard=True)
                settle()
        self.assertLessEqual(peak, 1, f"{peak} restore threads were alive at once")

    def test_and_the_one_worker_retires(self):
        clip = FakeClipboard()
        with contextlib.ExitStack() as stack:
            for p in clip.patches(0.0):
                stack.enter_context(p)
            from flow.inject import paste

            paste("deploy it", restore_clipboard=True)
            settle()
        self.assertEqual(restore_threads(), [])


class TestARefusedSendGivesTheTransactionUp(unittest.TestCase):
    """A refusal keeps the payload on the clipboard, so there is nothing owed back.

    Items 48 and 49 both refuse *after* writing, deliberately: the recovery is the user
    pressing Ctrl-V. Once that has been said, restoring would take away the thing they
    were told to press it on — so the transaction is released rather than left pending,
    or the next send an hour later would put back an hour-old clipboard.
    """

    def _refused_then_ordinary(self, refuse_with):
        clip = FakeClipboard()
        with contextlib.ExitStack() as stack:
            for p in clip.patches(0.0):
                stack.enter_context(p)
            stack.enter_context(mock.patch("flow.inject.resolve",
                                           side_effect=[CMD, EDITOR, EDITOR]))
            from flow.inject import paste

            take_warnings()
            self.assertFalse(paste(refuse_with, restore_clipboard=True))
            settle()
            after_refusal = clip.text
            paste("an ordinary send", restore_clipboard=True)
            settle()
            take_warnings()
        return after_refusal, clip

    def test_a_refused_payload_stays_and_nothing_is_restored_over_it(self):
        after, _clip = self._refused_then_ordinary("one\ntwo")
        self.assertEqual(after, "one\ntwo")

    def test_the_next_send_borrows_fresh_rather_than_an_old_debt(self):
        # The stale-debt case: if the refusal left the user's original owed, this send
        # would restore a clipboard from before the refusal — over text the user was
        # explicitly told to paste by hand.
        _after, clip = self._refused_then_ordinary("one\ntwo")
        self.assertEqual(clip.text, "one\ntwo",
                         "an abandoned debt was restored over the refused payload")


class TestWhatCannotComeBackIsNamed(unittest.TestCase):
    """DESKTOP-03, bounded: the limitation was honest in a comment and nowhere else.

    `set_clipboard_text` calls `EmptyClipboard()`, which destroys every format, and only
    `CF_UNICODETEXT` is captured — so a clipboard holding a screenshot or a file
    selection is erased by a Send and never restored. `inject.py` said so in a comment,
    which is the one place the user is guaranteed never to look.

    Preserving the formats is the fix this deliberately is not: enumerating and copying an
    arbitrary OLE data object is a great deal of ctypes for a path ending with Flow owning
    a copy of somebody's screenshot. Saying what is about to be lost, before losing it,
    costs one enumeration that copies no data at all.
    """

    def test_an_image_is_named(self):
        from flow.inject import CF_DIB, unrestorable

        self.assertEqual(unrestorable([CF_DIB]), "an image")

    def test_files_are_named(self):
        from flow.inject import CF_HDROP, unrestorable

        self.assertEqual(unrestorable([CF_HDROP]), "files")

    def test_both_at_once_read_as_a_sentence(self):
        from flow.inject import CF_BITMAP, CF_HDROP, unrestorable

        self.assertEqual(unrestorable([CF_BITMAP, CF_HDROP]), "an image and files")

    def test_an_ordinary_text_clipboard_says_nothing(self):
        # Measured on this machine, and it is the reason the rule can be this narrow:
        # a plain text clipboard reads CF_UNICODETEXT, CF_LOCALE, CF_TEXT, CF_OEMTEXT —
        # every one of them synthesised by Windows from the single format Flow saves. Put
        # the text back and they all come back with it, so there is nothing to warn about.
        from flow.inject import CF_LOCALE, CF_OEMTEXT, CF_TEXT, CF_UNICODETEXT, unrestorable

        self.assertEqual(
            unrestorable([CF_UNICODETEXT, CF_LOCALE, CF_TEXT, CF_OEMTEXT]), ""
        )

    def test_rich_text_alongside_plain_text_says_nothing(self):
        # A registered format — "HTML Format", "Rich Text Format" — travelling with
        # CF_UNICODETEXT is the ordinary result of copying from a browser or a word
        # processor, and the *content* does come back; only styling is lost. Warning here
        # would fire on almost every paste, and a warning that fires constantly is one
        # nobody reads by the time it matters.
        from flow.inject import CF_UNICODETEXT, unrestorable

        self.assertEqual(unrestorable([CF_UNICODETEXT, 49_384]), "")

    def test_a_registered_format_with_no_text_at_all_is_a_total_loss(self):
        # The other half of the same judgement: with no CF_UNICODETEXT there is nothing
        # for the restore to put back, so whatever that format held is simply gone.
        from flow.inject import unrestorable

        self.assertEqual(unrestorable([49_384]), "its contents")

    def test_an_empty_clipboard_says_nothing(self):
        from flow.inject import unrestorable

        self.assertEqual(unrestorable([]), "")


class TestTheWarningComesBeforeTheDestruction(unittest.TestCase):
    """Order is the whole feature. Said afterwards it is a report, not a warning."""

    def _paste_over(self, formats):
        take_warnings()
        events: list[str] = []
        with mock.patch("flow.inject.resolve", return_value=EDITOR), \
                mock.patch("flow.inject.clipboard_formats", return_value=formats), \
                mock.patch("flow.inject.get_clipboard_text", return_value=None), \
                mock.patch("flow.inject.set_clipboard_text",
                           side_effect=lambda t: (events.append("write"), True)[1]), \
                mock.patch("flow.inject._warn",
                           side_effect=lambda line: events.append(f"warn:{line}")), \
                mock.patch("flow.inject._send", side_effect=all_inserted):
            from flow.inject import paste

            ok = paste("deploy it", restore_clipboard=True)
        take_warnings()
        return ok, events

    def test_the_image_warning_precedes_the_write(self):
        from flow.inject import CF_DIB

        ok, events = self._paste_over([CF_DIB])
        self.assertTrue(ok, "the user asked to send; this warns, it does not refuse")
        self.assertEqual(len(events), 2, events)
        self.assertTrue(events[0].startswith("warn:"), events)
        self.assertEqual(events[1], "write")

    def test_the_warning_says_what_and_says_it_will_not_come_back(self):
        from flow.inject import CF_HDROP

        _ok, events = self._paste_over([CF_HDROP])
        self.assertIn("files", events[0])
        self.assertIn("not be restored", events[0])

    def test_a_text_clipboard_produces_no_extra_line(self):
        from flow.inject import CF_UNICODETEXT

        _ok, events = self._paste_over([CF_UNICODETEXT])
        self.assertEqual(events, ["write"])


class TestTheClipboardSurvivesAFailedAllocation(unittest.TestCase):
    """`EmptyClipboard()` ran first, so a failure after it erased what it had.

    The audit's own sentence: "allocation/write failure after EmptyClipboard() can also
    erase the original before paste begins". It is the narrowest possible window and it
    costs nothing to close — the handle can be filled before the clipboard is opened at
    all, and then the destructive step and the replacement are adjacent.
    """

    def _write_with(self, alloc=1234, lock=5678, setdata=1, opens=True):
        calls: list[str] = []
        user32 = mock.Mock()
        kernel32 = mock.Mock()
        user32.OpenClipboard.side_effect = lambda h: (calls.append("open"), opens)[1]
        user32.EmptyClipboard.side_effect = lambda: calls.append("empty") or 1
        user32.SetClipboardData.side_effect = lambda f, h: (calls.append("set"), setdata)[1]
        user32.CloseClipboard.side_effect = lambda: calls.append("close") or 1
        kernel32.GlobalAlloc.side_effect = lambda f, n: (calls.append("alloc"), alloc)[1]
        kernel32.GlobalLock.side_effect = lambda h: (calls.append("lock"), lock)[1]
        kernel32.GlobalUnlock.side_effect = lambda h: 1
        kernel32.GlobalFree.side_effect = lambda h: calls.append("free") or 0
        with mock.patch("flow.inject.user32", user32), \
                mock.patch("flow.inject.kernel32", kernel32), \
                mock.patch("flow.inject.ctypes.memmove"):
            from flow.inject import set_clipboard_text

            ok = set_clipboard_text("deploy it")
        return ok, calls

    def test_a_failed_allocation_never_empties_the_clipboard(self):
        ok, calls = self._write_with(alloc=0)
        self.assertFalse(ok)
        self.assertNotIn("empty", calls, "the original was erased for a write that failed")

    def test_a_failed_lock_never_empties_the_clipboard(self):
        ok, calls = self._write_with(lock=0)
        self.assertFalse(ok)
        self.assertNotIn("empty", calls)
        self.assertIn("free", calls, "the handle leaked for the life of the process")

    def test_the_ordinary_write_still_empties_then_sets(self):
        ok, calls = self._write_with()
        self.assertTrue(ok)
        self.assertEqual([c for c in calls if c in ("empty", "set", "close")],
                         ["empty", "set", "close"])

    def test_the_buffer_is_filled_before_the_clipboard_is_even_opened(self):
        # The property that makes the window closed rather than merely narrow: by the
        # time anything destructive can run, the replacement already exists.
        _ok, calls = self._write_with()
        self.assertLess(calls.index("alloc"), calls.index("open"))
        self.assertLess(calls.index("lock"), calls.index("open"))

    def test_a_clipboard_that_will_not_open_frees_the_handle(self):
        ok, calls = self._write_with(opens=False)
        self.assertFalse(ok)
        self.assertIn("free", calls)
        self.assertNotIn("empty", calls)

    def test_a_refused_setclipboarddata_still_frees(self):
        ok, calls = self._write_with(setdata=0)
        self.assertFalse(ok)
        self.assertIn("free", calls)
        self.assertIn("close", calls, "the clipboard was left open for the process")
