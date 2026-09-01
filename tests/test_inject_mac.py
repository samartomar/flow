"""`flow.inject_mac`: the paste path that made Flow useful on a Mac.

Off Windows Flow ran in Lite, where Send copies the draft and stops — and the owner's
verdict on that was the reason this module exists: "it seems on mac there is no actual
send it copies in clipboard that is making this no useful on mac". Every window fault had
been fixed by then and the thing they all led to still handed you a clipboard.

No `osascript` runs here. What is asserted is the shape of what would be run, the order
things happen in, and what the user is told when the OS says no — which is the part that
cannot be tested on the machine this was written on and is the part most likely to be
wrong.
"""

import subprocess
import unittest
from unittest import mock

import flow.inject_mac as inject_mac


class Ran:
    """Records the child processes `paste` would start, and answers for them."""

    def __init__(self, front="TextEdit", clipboard="old text", fail=None, reason="",
                 bundle="com.apple.TextEdit"):
        self.calls: list[tuple[list[str], str | None]] = []
        self.front, self.clipboard, self.bundle = front, clipboard, bundle
        self.fail, self.reason = fail, reason

    def __call__(self, argv, stdin=None):
        self.calls.append((argv, stdin))
        tool = argv[0]
        if self.fail is not None and self.fail in " ".join(argv):
            return False, self.reason
        if tool == "pbpaste":
            return True, self.clipboard
        if tool == "osascript" and "frontmost" in argv[-1]:
            return True, f"{self.front}|{self.bundle}"
        return True, ""

    @property
    def tools(self) -> list[str]:
        return [argv[0] for argv, _stdin in self.calls]

    def script(self) -> str:
        """The keystroke script, which is the last osascript that is not the query."""
        for argv, _stdin in reversed(self.calls):
            if argv[0] == "osascript" and "frontmost" not in argv[-1]:
                return argv[-1]
        return ""

    def copied(self) -> list[str]:
        return [stdin for argv, stdin in self.calls if argv[0] == "pbcopy"]


class Paste(unittest.TestCase):
    def setUp(self):
        inject_mac.take_warnings()
        self.addCleanup(inject_mac.take_warnings)

    def run_paste(self, ran=None, **kw):
        ran = ran or Ran()
        with mock.patch.object(inject_mac, "_run", ran), \
                mock.patch.object(inject_mac, "_restore_later"):
            ok = inject_mac.paste("hello", **kw)
        return ok, ran

    def test_it_copies_then_sends_command_v(self):
        ok, ran = self.run_paste()
        self.assertTrue(ok)
        self.assertEqual(ran.copied(), ["hello"])
        self.assertIn('keystroke "v" using command down', ran.script())

    def test_the_clipboard_is_written_before_the_keystroke_is_attempted(self):
        """The order is the decision, and `inject.py` made the same one.

        A keystroke can be refused; a clipboard write mostly cannot. Doing the fragile
        half second means a refusal still leaves the words somewhere the user can reach
        with their own Cmd-V, which is exactly what the permission note promises them.
        """
        _ok, ran = self.run_paste()
        # Against the keystroke script specifically, not against the first `osascript`:
        # the frontmost query is one too, and it runs first on purpose so a refusal
        # costs no clipboard at all.
        copied = next(i for i, t in enumerate(ran.tools) if t == "pbcopy")
        typed = next(i for i, (argv, _s) in enumerate(ran.calls)
                     if argv[0] == "osascript" and "frontmost" not in argv[-1])
        self.assertLess(copied, typed)

    def test_submit_presses_return_by_key_code_and_not_as_a_character(self):
        # `keystroke return` sends the character, and an app that tells them apart gets a
        # newline in the box instead of a send.
        _ok, ran = self.run_paste(submit=True)
        self.assertIn("key code 36", ran.script())
        self.assertNotIn("keystroke return", ran.script())

    def test_the_paste_and_the_return_travel_in_one_script(self):
        # Each `osascript` is a process launch, and the gap between them is where another
        # window could come forward and take the Return.
        _ok, ran = self.run_paste(submit=True)
        self.assertEqual(len([a for a, _s in ran.calls if a[0] == "osascript"]), 2)
        self.assertIn('keystroke "v"', ran.script())
        self.assertIn("key code 36", ran.script())

    def test_no_submit_presses_nothing(self):
        _ok, ran = self.run_paste()
        self.assertNotIn("key code", ran.script())

    def test_it_refuses_to_paste_into_flow_itself(self):
        # The one outcome that would destroy the text being sent. `ui._bare_window` is
        # what should make it impossible; this is the belt to those braces.
        ok, ran = self.run_paste(Ran(front="Python"))
        self.assertFalse(ok)
        self.assertEqual(ran.copied(), [])
        self.assertIn("had the focus", inject_mac.take_warnings()[0])

    def test_a_refused_keystroke_names_the_permission_and_the_terminal(self):
        """The only message most people will ever see from this module.

        Accessibility is granted to the *responsible* process — the terminal — so a note
        naming Flow or Python sends the reader to a list Flow is not in.
        """
        ok, _ran = self.run_paste(Ran(fail="System Events", reason="(-1719)"))
        self.assertFalse(ok)
        note = inject_mac.take_warnings()[0]
        self.assertIn("Accessibility", note)
        self.assertIn("terminal", note)
        self.assertIn("Cmd-V", note)

    def test_every_refusal_code_is_recognised(self):
        for code in inject_mac.DENIED_CODES:
            with self.subTest(code=code):
                self.assertTrue(inject_mac.denied(f"System Events got an error ({code})"))
        self.assertFalse(inject_mac.denied("some other failure"))

    def test_a_failure_that_is_not_the_permission_says_what_it_was(self):
        # Invariant 4: a send that did nothing must never do it quietly.
        ok, _ran = self.run_paste(Ran(fail="System Events", reason="osascript exploded"))
        self.assertFalse(ok)
        self.assertIn("osascript exploded", inject_mac.take_warnings()[0])

    def test_a_clipboard_that_refuses_stops_before_the_keystroke(self):
        # Sending Cmd-V after a failed copy pastes whatever was there before, which is
        # somebody else's text going into the window they were working in.
        ok, ran = self.run_paste(Ran(fail="pbcopy", reason="no pasteboard"))
        self.assertFalse(ok)
        self.assertEqual(ran.script(), "")
        self.assertIn("clipboard", inject_mac.take_warnings()[0])

    def test_empty_text_does_nothing_at_all(self):
        with mock.patch.object(inject_mac, "_run") as ran:
            self.assertFalse(inject_mac.paste(""))
        ran.assert_not_called()

    def test_the_old_clipboard_is_read_and_scheduled_to_go_back(self):
        ran = Ran(clipboard="something the user had")
        with mock.patch.object(inject_mac, "_run", ran), \
                mock.patch.object(inject_mac, "_restore_later") as later:
            inject_mac.paste("hello")
        later.assert_called_once_with("something the user had")

    def test_restore_can_be_turned_off_and_then_nothing_is_read(self):
        ran = Ran()
        with mock.patch.object(inject_mac, "_run", ran), \
                mock.patch.object(inject_mac, "_restore_later") as later:
            inject_mac.paste("hello", restore_clipboard=False)
        self.assertNotIn("pbpaste", ran.tools)
        later.assert_not_called()

    def test_hwnd_is_accepted_and_ignored(self):
        # It exists for the signature `__main__.on_send` is written against. macOS has no
        # window handle to aim at and does not need one: Flow's windows never take focus.
        ok, _ran = self.run_paste(hwnd=0x22)
        self.assertTrue(ok)


class Running(unittest.TestCase):
    """`_run` itself, which must turn every way a child can fail into a sentence."""

    def test_a_missing_tool_is_a_reason_and_not_an_exception(self):
        with mock.patch.object(subprocess, "run", side_effect=OSError("no such file")):
            ok, why = inject_mac._run(["osascript", "-e", "x"])
        self.assertFalse(ok)
        self.assertIn("osascript", why)

    def test_a_wedged_child_is_given_up_on(self):
        # Finite by construction: a hung System Events must not hang the send.
        with mock.patch.object(subprocess, "run",
                               side_effect=subprocess.TimeoutExpired("osascript", 10)):
            ok, why = inject_mac._run(["osascript", "-e", "x"])
        self.assertFalse(ok)
        self.assertIn("did not answer", why)

    def test_a_nonzero_exit_carries_the_stderr(self):
        done = mock.Mock(returncode=1, stderr="it went wrong", stdout="")
        with mock.patch.object(subprocess, "run", return_value=done):
            ok, why = inject_mac._run(["osascript", "-e", "x"])
        self.assertFalse(ok)
        self.assertEqual(why, "it went wrong")

    def test_a_nonzero_exit_with_nothing_to_say_still_says_something(self):
        done = mock.Mock(returncode=1, stderr="", stdout="")
        with mock.patch.object(subprocess, "run", return_value=done):
            ok, why = inject_mac._run(["osascript", "-e", "x"])
        self.assertFalse(ok)
        self.assertTrue(why)


class Warnings(unittest.TestCase):
    def test_taking_them_clears_them(self):
        # `inject.py`'s rule: a warning read twice is a failure reported twice, and one
        # never read is the silence invariant 4 forbids.
        inject_mac.take_warnings()
        inject_mac._warn("something")
        self.assertEqual(inject_mac.take_warnings(), ["something"])
        self.assertEqual(inject_mac.take_warnings(), [])


class TheStartupLine(unittest.TestCase):
    def test_it_is_ascii_like_every_other_startup_line(self):
        # `__main__.say` documents why: a redirected stdout on a legacy console code page
        # cannot encode an en-dash, so a line carrying one crashes instead of printing.
        for line in (inject_mac.permission_note(),):
            line.encode("ascii")
            line.encode("cp437")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

class TestATerminalNeverRunsWhatWasDictated(unittest.TestCase):
    """The guard `inject.py` has had since 2026-08-03, on the platform that had none.

    A draft ending in a newline does not paste into a shell — it *runs*. Windows resolves
    its target and strips that newline; `inject_mac` aimed at whatever was frontmost and
    pasted it verbatim, so somebody dictating into a Mac terminal could have their words
    execute. It was live for as long as the paste path was.
    """

    def setUp(self):
        inject_mac.take_warnings()
        self.addCleanup(inject_mac.take_warnings)

    def test_a_trailing_newline_is_stripped_for_a_terminal(self):
        payload, _why = inject_mac.prepare("ls -la\n", "Terminal", "com.apple.Terminal")
        self.assertEqual(payload, "ls -la")

    def test_and_kept_everywhere_else(self):
        # Stripping it in an editor would be Flow editing a draft to fit a guess.
        payload, _why = inject_mac.prepare("hello\n", "Notes", "com.apple.Notes")
        self.assertEqual(payload, "hello\n")

    def test_every_shipped_identifier_is_recognised(self):
        for bundle in inject_mac.TERMINAL_IDS:
            with self.subTest(bundle=bundle):
                self.assertTrue(inject_mac.is_terminal("", bundle))

    def test_a_terminal_not_on_the_list_is_still_caught_by_name(self):
        """The fallback, and the asymmetry that earns it: a list too eager costs a
        trailing newline somebody has to press Return for, and one too shy costs a line
        that runs."""
        self.assertTrue(inject_mac.is_terminal("Some New Term", "com.unknown.thing"))
        self.assertFalse(inject_mac.is_terminal("Notes", "com.apple.Notes"))

    def test_multiple_lines_into_a_terminal_are_reported(self):
        # Warned rather than refused: Windows refuses on a *measured* list of which
        # terminals bracket pastes, and nothing here has measured a single macOS one.
        _payload, why = inject_mac.prepare("a\nb\n", "iTerm2", "com.googlecode.iterm2")
        self.assertIn("iTerm2", why)
        self.assertIn("each line", why)

    def test_one_line_into_a_terminal_says_nothing(self):
        _payload, why = inject_mac.prepare("ls\n", "Terminal", "com.apple.Terminal")
        self.assertEqual(why, "")

    def test_the_paste_uses_the_stripped_payload(self):
        ran = Ran(front="Terminal", bundle="com.apple.Terminal")
        with mock.patch.object(inject_mac, "_run", ran), \
                mock.patch.object(inject_mac, "_restore_later"):
            self.assertTrue(inject_mac.paste("ls -la\n"))
        self.assertEqual(ran.copied(), ["ls -la"])

    def test_and_the_hazard_reaches_the_user(self):
        ran = Ran(front="Terminal", bundle="com.apple.Terminal")
        with mock.patch.object(inject_mac, "_run", ran), \
                mock.patch.object(inject_mac, "_restore_later"):
            inject_mac.paste("one\ntwo\n")
        self.assertTrue([w for w in inject_mac.take_warnings() if "each line" in w])

    def test_a_draft_that_was_only_a_newline_is_not_pasted(self):
        # Stripped to nothing is nothing to send, and an empty clipboard write followed
        # by a Cmd-V would paste whatever was there before.
        ran = Ran(front="Terminal", bundle="com.apple.Terminal")
        with mock.patch.object(inject_mac, "_run", ran):
            self.assertFalse(inject_mac.paste("\n"))
        self.assertEqual(ran.copied(), [])


class TestTheFrontmostQuery(unittest.TestCase):
    def test_it_asks_once_for_both_facts(self):
        # Each osascript is a process launch and this one is on the path of every send.
        ran = Ran()
        with mock.patch.object(inject_mac, "_run", ran):
            self.assertEqual(inject_mac.frontmost(),
                             ("TextEdit", "com.apple.TextEdit"))
        self.assertEqual(len([c for c, _s in ran.calls if c[0] == "osascript"]), 1)

    def test_the_separator_is_not_a_line_break(self):
        """AppleScript string literals cannot contain a raw line break, so joining the
        two facts with one is a script that does not compile."""
        ran = Ran()
        with mock.patch.object(inject_mac, "_run", ran):
            inject_mac.frontmost()
        self.assertIn(chr(38) + ' "|" ' + chr(38), ran.calls[0][0][-1])

    def test_a_refusal_answers_with_two_empty_strings(self):
        ran = Ran(fail="frontmost", reason="(-1719)")
        with mock.patch.object(inject_mac, "_run", ran):
            self.assertEqual(inject_mac.frontmost(), ("", ""))
