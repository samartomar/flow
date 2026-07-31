"""Tests for terminal-safe paste (P7).

The failure this prevents is the loudest one Flow can cause: a draft ending in a
newline, pasted into a shell, runs. Everything here is about the target — what has
focus decides what is safe to send, and where nothing can be guaranteed the user is
told rather than surprised.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.inject import (  # noqa: E402
    BRACKETED_PASTE,
    TERMINAL_CLASSES,
    TERMINAL_PROCESSES,
    Target,
    prepare,
    take_warnings,
)

WT = Target("CASCADIA_HOSTING_WINDOW_CLASS", "WindowsTerminal.exe")
CMD = Target("ConsoleWindowClass", "cmd.exe")
BASH = Target("mintty", "mintty.exe")
EDITOR = Target("Chrome_WidgetWin_1", "Code.exe")
UNKNOWN = Target()


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


class TestPasteUsesTheTarget(unittest.TestCase):
    def _paste(self, text, target):
        take_warnings()  # start clean
        with mock.patch("flow.inject.foreground_target", return_value=target), \
             mock.patch("flow.inject.get_clipboard_text", return_value=None), \
             mock.patch("flow.inject.set_clipboard_text", return_value=True) as put, \
             mock.patch("flow.inject._send", return_value=1):
            from flow.inject import paste

            ok = paste(text, restore_clipboard=False)
        return ok, put.call_args.args[0], take_warnings()

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


if __name__ == "__main__":
    unittest.main()
