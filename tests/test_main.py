"""The entry point, and the body it chooses before it does anything else.

This used to pin a refusal: on anything but Windows, one sentence and exit 2, because
`inject.py`, `hotkey.py` and `ui.py` each called `ctypes.WinDLL("user32")` at import time
and a Mac's first impression of the product would otherwise be a ctypes traceback about a
DLL it has never heard of.

The refusal is gone and this class is what inverts it (decisions.md, "Flow Lite"): a
non-Windows launch runs **Lite** and says so. The two halves of the new rule are both
asserted here — the *platform* decides what can be imported, and `lite` decides what
happens — because they are what makes a Lite launch testable on Windows at all.

`no_win32()` survives for the first check only. `None` in `sys.modules` makes an import
of a name raise, which is the shape `ctypes.WinDLL` has on darwin, and the thing still
worth proving is that `flow.__main__` can be *read into memory* without any of the three.
It no longer models a Mac launch: `ui` is one of the three, and Lite draws a pill.
"""

import contextlib
import importlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

#: The three modules that reach for Win32. `inject` and `hotkey` still bind it at import
#: and are never imported in Lite; `ui` binds it behind a `sys.platform` check, because a
#: body without hands still has a window. Nothing else in the package does: `session`,
#: `asr`, `lexicon`, `refine` and `audio` are portable, which is why the decision could
#: say the brain ships everywhere and the hands do not.
WIN32_MODULES = ("flow.inject", "flow.hotkey", "flow.ui")


@contextlib.contextmanager
def no_win32():
    """Re-import `flow.__main__` with the Win32 modules unimportable."""
    names = (*WIN32_MODULES, "flow.__main__")
    saved = {n: sys.modules[n] for n in names if n in sys.modules}
    absent = [n for n in names if n not in sys.modules]
    for n in WIN32_MODULES:
        sys.modules[n] = None
    sys.modules.pop("flow.__main__", None)
    try:
        yield
    finally:
        sys.modules.update(saved)
        for n in absent:
            sys.modules.pop(n, None)


def run_main(mod, platform: str, argv=()) -> tuple[int, str]:
    out = io.StringIO()
    with mock.patch.object(sys, "platform", platform):
        with contextlib.redirect_stdout(out):
            code = mod.main(list(argv))
    return code, out.getvalue()


#: Enough of a launch to be real and none of it heavy. `Session` and the transcriber are
#: the two that would open a microphone and reach for a 141 MB model; `Pill.mainloop` is
#: the one that would never return. Everything between them — the CLI lookup, the
#: lexicon, the workspace, every startup line — runs for real, which is the point.
def launch(platform: str, argv=(), **patches):
    import flow.asr
    import flow.ui

    import flow.__main__ as mod

    out = io.StringIO()
    with mock.patch.object(sys, "platform", platform), \
            mock.patch.object(mod, "Session") as session, \
            mock.patch.object(flow.asr, "WhisperTranscriber"), \
            mock.patch.object(flow.ui, "Pill") as pill:
        with contextlib.redirect_stdout(out):
            code = mod.main(["--no-profile", "--no-speak", "--no-lexicon", *argv])
    return code, out.getvalue(), pill, session


class TestNonWindowsRunsLite(unittest.TestCase):
    def test_the_entry_point_imports_at_all_without_win32(self):
        # Still the check that keeps the Win32 imports inside `main()`: an import at
        # module scope would explode on a Mac before any body could be chosen.
        with no_win32():
            importlib.import_module("flow.__main__")

    def test_a_mac_gets_lite_rather_than_a_refusal(self):
        code, out, pill, session = launch("darwin")
        self.assertEqual(code, 0)
        self.assertIn("Flow Lite on darwin", out)
        self.assertNotIn("Windows-only", out)
        self.assertTrue(pill.call_args.kwargs["lite"])
        self.assertTrue(session.call_args.kwargs["lite"])

    def test_it_names_whichever_platform_it_found(self):
        _code, out, _pill, _session = launch("linux")
        self.assertIn("linux", out)

    def test_no_hotkey_is_registered_and_no_paste_handler_is_built(self):
        # The two halves of "no hands", asserted where they are decided rather than
        # where they would be felt. `on_send` is the paste closure, and in Lite it
        # closes over names that were never imported — so handing one over would be a
        # handler that fails on its first call.
        _code, out, pill, _session = launch("darwin")
        # The registration report is `hotkey  <action> <combo>` per line. Matched on the
        # line rather than on the word, because the Lite banner says "no global hotkeys"
        # and an assertion that cannot tell those apart is asserting nothing.
        self.assertEqual(
            [ln for ln in out.splitlines() if ln.startswith("hotkey")], [])
        self.assertIsNone(pill.call_args.kwargs["hotkeys"])
        self.assertIsNone(pill.call_args.kwargs["on_send"])

    def test_the_mode_line_does_not_name_a_window_lite_cannot_see(self):
        _code, out, _pill, _session = launch("darwin")
        self.assertIn("Send copies the draft", out)
        self.assertNotIn("focused window", out)

    def test_every_lite_startup_line_is_ascii_like_the_rest(self):
        # `say()` documents why: a redirected stdout on a legacy console code page
        # cannot encode an en-dash, so a line carrying one crashes instead of printing.
        _code, out, _pill, _session = launch("darwin")
        out.encode("cp437")
        out.encode("ascii")

    def test_the_flags_are_parsed_now_that_there_is_nothing_to_refuse(self):
        # The inverse of what this asserted before. The guard sat above argparse because
        # being told a flag is wrong when the platform is the problem answers the smaller
        # question — and the platform is no longer a problem, so argparse goes first and
        # a bad flag is simply a bad flag.
        with mock.patch.object(sys, "platform", "darwin"):
            with contextlib.redirect_stderr(io.StringIO()) as err:
                with self.assertRaises(SystemExit) as caught:
                    importlib.import_module("flow.__main__").main(["--not-a-flag"])
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("unrecognized arguments", err.getvalue())


class TestWindowsStillGetsHands(unittest.TestCase):
    """The full body is the default here, and `--lite` is the way to ask for the other."""

    def test_a_windows_launch_says_nothing_about_lite(self):
        _code, out, pill, session = launch("win32", ["--no-hotkeys"])
        self.assertNotIn("Flow Lite", out)
        self.assertIn("focused window", out)
        self.assertFalse(pill.call_args.kwargs["lite"])
        self.assertFalse(session.call_args.kwargs["lite"])
        self.assertIsNotNone(pill.call_args.kwargs["on_send"])

    def test_the_flag_gets_the_same_body_a_mac_would(self):
        # The whole reason Lite is testable here: `--lite` on Windows is not a rehearsal
        # of the Mac path, it is the Mac path.
        _code, out, pill, _session = launch("win32", ["--lite"])
        self.assertIn("Flow Lite on win32", out)
        self.assertTrue(pill.call_args.kwargs["lite"])
        self.assertIsNone(pill.call_args.kwargs["hotkeys"])

    def test_no_paste_is_accepted_rather_than_refused_in_lite(self):
        # A launcher shared between two machines should not fail on a flag that has
        # simply run out of things to suppress.
        code, out, _pill, _session = launch("win32", ["--lite", "--no-paste"])
        self.assertEqual(code, 0)
        self.assertIn("nothing to suppress", out)

    def test_help_still_prints_and_exits_zero(self):
        from flow.__main__ import main

        out = io.StringIO()
        with mock.patch.object(sys, "platform", "win32"):
            with contextlib.redirect_stdout(out):
                with self.assertRaises(SystemExit) as caught:
                    main(["--help"])
        self.assertEqual(caught.exception.code, 0)
        self.assertIn("usage: flow", out.getvalue())
        self.assertIn("--lite", out.getvalue())
        self.assertNotIn("Windows-only", out.getvalue())


class TestThePinKnowsWhyItRefused(unittest.TestCase):
    """Three ways `--cli` can fail, and they are three different sentences.

    An inert entry may well be installed, so "not on PATH" would be a lie about the one
    thing the user can check for themselves — which is why the `verified` refusal sits
    above the PATH one rather than after it.
    """

    def run_main(self, argv):
        import flow.__main__ as mod

        out = io.StringIO()
        with mock.patch.object(sys, "platform", "win32"), \
                contextlib.redirect_stdout(out):
            code = mod.main(["--no-profile", "--no-speak", "--no-lexicon", *argv])
        return code, out.getvalue()

    def test_an_unverified_pin_says_why_and_does_not_blame_the_path(self):
        code, out = self.run_main(["--cli", "gemini"])
        self.assertEqual(code, 2)
        self.assertIn("never been run", out)
        self.assertNotIn("not on PATH", out)

    def test_a_name_nobody_knows_lists_the_ones_it_does(self):
        code, out = self.run_main(["--cli", "kiro"])
        self.assertEqual(code, 2)
        self.assertIn("not a known CLI", out)
        self.assertIn("codex", out)

    def test_a_verified_pin_that_is_absent_still_blames_the_path(self):
        import flow.__main__ as mod

        out = io.StringIO()
        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch("shutil.which", lambda *a, **kw: None), \
                contextlib.redirect_stdout(out):
            code = mod.main(["--no-profile", "--no-speak", "--no-lexicon",
                             "--cli", "claude"])
        self.assertEqual(code, 2)
        self.assertIn("not on PATH", out.getvalue())

    def test_an_installed_but_inert_cli_is_named_at_startup(self):
        # Silence would make an installed-and-unused CLI look exactly like one Flow could
        # not find, and the person who installed it is the one who can end that.
        import flow.asr
        import flow.ui

        import flow.__main__ as mod

        out = io.StringIO()
        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch("shutil.which", lambda cmd, *a, **kw:
                           "/somewhere/gemini" if cmd == "gemini" else None), \
                mock.patch.object(mod, "Session"), \
                mock.patch.object(flow.asr, "WhisperTranscriber"), \
                mock.patch.object(flow.ui, "Pill"), \
                contextlib.redirect_stdout(out):
            code = mod.main(["--no-profile", "--no-speak", "--no-lexicon", "--lite"])
        self.assertEqual(code, 0)
        self.assertIn("found gemini, not yet verified", out.getvalue())


if __name__ == "__main__":
    unittest.main()
