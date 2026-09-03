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
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cli_env import fake_exe, no_off_path_installs  # noqa: E402

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
        # Not the Lite banner any more: a Mac pastes, which is the one thing Lite was
        # defined by. It is still Lite in every other respect and the `lite` kwargs below
        # are what say so.
        self.assertIn("Flow on darwin", out)
        self.assertIn("Send pastes", out)
        self.assertNotIn("Windows-only", out)
        self.assertTrue(pill.call_args.kwargs["lite"])
        self.assertTrue(session.call_args.kwargs["lite"])

    def test_it_names_whichever_platform_it_found(self):
        _code, out, _pill, _session = launch("linux")
        self.assertIn("linux", out)

    def test_no_hotkey_is_registered_but_a_paste_handler_is(self):
        """"No hands" was two halves and is now one.

        The hotkeys stay unregistered: there is no `RegisterHotKey` here and the pill is
        the gesture. The paste closure is built, because `inject_mac` gives it something
        to close over — `osascript` rather than `SendInput`. Handing one over used to be
        a handler that would fail on its first call; it is not any more.
        """
        _code, out, pill, _session = launch("darwin")
        # The registration report is `hotkey  <action> <combo>` per line. Matched on the
        # line rather than on the word, because the Lite banner says "no global hotkeys"
        # and an assertion that cannot tell those apart is asserting nothing.
        self.assertEqual(
            [ln for ln in out.splitlines() if ln.startswith("hotkey")], [])
        self.assertIsNone(pill.call_args.kwargs["hotkeys"])
        self.assertIsNotNone(pill.call_args.kwargs["on_send"])

    def test_no_paste_puts_the_clipboard_back(self):
        # The one way to get the old behaviour on a Mac, and it has to keep working:
        # somebody who does not want Flow synthesising keystrokes should not have to
        # choose between that and using Flow.
        _code, out, pill, _session = launch("darwin", ["--no-paste"])
        self.assertIsNone(pill.call_args.kwargs["on_send"])
        self.assertIn("Send copies the draft", out)

    def test_the_mode_line_says_it_pastes(self):
        _code, out, _pill, _session = launch("darwin")
        self.assertIn("Send pastes into the focused window", out)

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


class TestTheStartupBlockNamesTheCopy(unittest.TestCase):
    """The version among the diagnostics, and the check that must not run itself.

    Every other line in that block is a fact *about* a copy — which hotkeys registered,
    which models, which CLI — and the download link always serves the newest zip, so
    nothing on disk says which one arrived. A report quoting a hotkey or a decode time
    is a report about a version nobody wrote down.

    The second half is the one that would fail silently. `--check-update` reaching GitHub
    when somebody types it is the feature; anything reaching GitHub on its own would make
    `docs/architecture.md` § "What leaves the machine" an approximation, and no other
    test in this suite would notice. `test_version.py` counts the call sites; this runs
    a launch with the opener booby-trapped.
    """

    def test_the_block_names_the_version_this_copy_carries(self):
        from flow.version import version

        _code, out, _pill, _session = launch("darwin")
        self.assertIn(f"version: {version()}", out)

    def test_and_says_out_loud_that_nothing_checks_for_updates(self):
        # Unprompted, like the trace line: a check somebody has to go looking for the
        # absence of is a claim they have no way to believe.
        _code, out, _pill, _session = launch("darwin")
        self.assertIn("nothing checks for updates on its own", out)

    def test_and_a_launch_opens_no_connection_of_its_own(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("a launch asked GitHub something")):
            code, _out, _pill, _session = launch("darwin")
        self.assertEqual(code, 0)


class TestCtrlCIsAQuitAndNotAnAbandonment(unittest.TestCase):
    """What happens to the session when the interrupt does not land in the frame pump.

    Nearly every ctrl+C is caught by `Pill._tick` and never reaches here, because that
    callback is where the main thread spends its time. The one that lands at the entry
    to a Tkinter callback — before Tkinter's own `try`, so it is not reported and
    swallowed — comes out of `mainloop`, and that is the exit that used to skip teardown
    completely: `main()` has no `with` around the session and never had one.

    Run on darwin so the assertion is about the entry point rather than about Windows;
    the `try` it covers is the same code on both.
    """

    def _interrupted(self):
        import flow.asr
        import flow.ui

        import flow.__main__ as mod

        with mock.patch.object(sys, "platform", "darwin"), \
                mock.patch.object(mod, "Session"), \
                mock.patch.object(flow.asr, "WhisperTranscriber"), \
                mock.patch.object(flow.ui, "Pill") as pill:
            pill.return_value.mainloop.side_effect = KeyboardInterrupt
            with contextlib.redirect_stdout(io.StringIO()):
                code = mod.main(["--no-profile", "--no-speak", "--no-lexicon"])
        return code, pill.return_value

    def test_it_tears_down_rather_than_leaving_the_mic_and_the_cli_behind(self):
        _code, pill = self._interrupted()
        pill.quit_app.assert_called_once()

    def test_the_interrupt_does_not_escape_main(self):
        # It used to, and the traceback landed on the launching terminal with the pill
        # already gone from the screen — an error report for a successful quit.
        code, _pill = self._interrupted()
        self.assertEqual(code, 0)


@unittest.skipUnless(sys.platform == "win32", "Windows-only: ctypes.WinDLL")
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


@unittest.skipUnless(sys.platform == "win32", "Windows-only: kernel32 NeedCurrentDirectoryForExePath")
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
        # `kiro` is the useful case rather than a made-up one: it is a real thing on this
        # machine, it is the IDE launcher, and the CLI beside it is called `kiro-cli`. The
        # list is what turns a wrong name into the right one.
        code, out = self.run_main(["--cli", "kiro"])
        self.assertEqual(code, 2)
        self.assertIn("not a known CLI", out)
        self.assertIn("codex", out)
        self.assertIn("kiro-cli", out)

    def test_a_verified_pin_that_is_found_off_path_is_accepted(self):
        # kiro-cli is on PATH after the MSI, and not in a shell that predates it. The pin
        # must agree with the probe, or `--cli kiro-cli` would be refused on the machine
        # the entry was verified on.
        import flow.asr
        import flow.ui

        import flow.__main__ as mod

        out = io.StringIO()
        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch("shutil.which", lambda *a, **kw: None), \
                mock.patch("os.path.isfile",
                           lambda p: str(p).endswith("kiro-cli.exe")), \
                mock.patch.object(mod, "Session"), \
                mock.patch.object(flow.asr, "WhisperTranscriber"), \
                mock.patch.object(flow.ui, "Pill"), \
                contextlib.redirect_stdout(out):
            code = mod.main(["--no-profile", "--no-speak", "--no-lexicon", "--lite",
                             "--cli", "kiro-cli"])
        self.assertEqual(code, 0)
        self.assertIn("refine CLI: kiro-cli", out.getvalue())

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
        # `no_off_path_installs` because this test declares what is installed, and a
        # machine that happens to have kiro-cli would otherwise answer instead — the
        # exact lesson `cli_env.py` was written for, one seam along.
        with mock.patch.object(sys, "platform", "win32"), no_off_path_installs(), \
                mock.patch("shutil.which", lambda cmd, *a, **kw:
                           fake_exe("gemini") if cmd == "gemini" else None), \
                mock.patch.object(mod, "Session"), \
                mock.patch.object(flow.asr, "WhisperTranscriber"), \
                mock.patch.object(flow.ui, "Pill"), \
                contextlib.redirect_stdout(out):
            code = mod.main(["--no-profile", "--no-speak", "--no-lexicon", "--lite"])
        self.assertEqual(code, 0)
        self.assertIn("found gemini, not yet verified", out.getvalue())
        self.assertIn("refine CLI: NONE", out.getvalue())


@unittest.skipUnless(sys.platform == "win32", "Windows-only: Windows path case-folding")
class TestACwdLaunchFeedsTheRecents(unittest.TestCase):
    """Item 36, asserted at the wiring: main() records a resolved --cwd.

    The profile-level add-once contract lives in `test_profile.py`; what only this can
    catch is a launch that resolves the workspace and never records it. The profile is
    real and lives in a temp dir, and the trace is patched out, so a test launch
    cannot write to the real `~/.flow` (Rule 5).
    """

    def setUp(self) -> None:
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = Path(d.name)
        self.ws = self.dir / "acme"
        self.ws.mkdir()

    def launch(self, argv) -> int:
        import flow.asr
        import flow.diag
        import flow.profile
        import flow.refine
        import flow.ui

        import flow.__main__ as mod

        out = io.StringIO()
        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch.object(flow.profile, "DEFAULT_PATH",
                                  self.dir / "profile.json"), \
                mock.patch.object(flow.diag, "Diag"), \
                mock.patch.object(mod, "Session"), \
                mock.patch.object(flow.asr, "WhisperTranscriber"), \
                mock.patch.object(flow.ui, "Pill"), \
                contextlib.redirect_stdout(out):
            return mod.main(["--no-speak", "--no-lexicon", "--lite", *argv])

    def profile_on_disk(self):
        from flow.profile import Profile

        return Profile(self.dir / "profile.json")

    def test_the_same_flag_across_relaunches_joins_exactly_once(self):
        self.assertEqual(self.launch(["--cwd", str(self.ws)]), 0)
        self.assertEqual(self.launch(["--cwd", str(self.ws)]), 0)
        self.assertEqual(self.profile_on_disk().workspaces, [str(self.ws)])

    def test_no_flag_and_a_typo_both_record_nothing(self):
        # A path that never resolved would be a stale recents entry from birth.
        self.assertEqual(self.launch(["--cwd", str(self.ws)]), 0)
        self.assertEqual(self.launch([]), 0)
        self.assertEqual(self.launch(["--cwd", str(self.dir / "typo")]), 0)
        self.assertEqual(self.profile_on_disk().workspaces, [str(self.ws)])


class TestAHotkeysBlockIsInertWhereNothingIsRegistered(unittest.TestCase):
    """A profile can now rebind the five combos. Two bodies never ask for one.

    Lite registers nothing with the OS — that is the only property it has that full Flow
    does not, and the whole reason it can run on a Mac — and `--no-hotkeys` is the flag
    for asking Windows for nothing. So a `hotkeys` block is not "applied and then
    suppressed" in either: it is never read, because there is no registration for it to
    be the front of.

    Which leaves two ways to get this wrong, and this is where both would show. The block
    could be *reported* — a launch announcing a rebinding that did not happen is worse
    than one that says nothing, and Lite's own banner already promises "no global
    hotkeys". Or the reading itself could be what breaks: `flow.hotkey` binds `user32` at
    import and is not importable off Windows at all, so a profile field that reached for
    it on the way past would turn a hand-edited shortcut into a Mac that will not start.

    The profile is real and lives in a temp dir, and the trace is patched out, so a test
    launch cannot write to the real `~/.flow` (Rule 5).
    """

    #: One of each: a combo that would have worked, an action that does not exist, and a
    #: value that is not even a string. Every one of them has something to say — and none
    #: of it may be said here.
    OVERRIDES = {"toggle": "ctrl+shift+1", "togle": "nonsense", "send": 5}

    def setUp(self) -> None:
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = Path(d.name)

    def launch(self, hotkeys, argv=(), platform="win32") -> tuple[int, str]:
        import flow.asr
        import flow.diag
        import flow.profile
        import flow.ui

        import flow.__main__ as mod

        path = self.dir / "profile.json"
        path.write_text(json.dumps({"schema": 1, "hotkeys": hotkeys}), encoding="utf-8")
        out = io.StringIO()
        # `refine.resolve` is stubbed, and not only for speed. It calls
        # `shutil.which`, and `shutil.which` reads `sys.platform` - which this
        # helper has just lied about. On a real macOS runner that sends the stdlib
        # down its Windows branch, where `_winapi` is None: `AttributeError:
        # 'NoneType' object has no attribute 'NeedCurrentDirectoryForExePath'`,
        # raised from a line no part of Flow wrote. Which agent CLI happens to be
        # installed has nothing to do with what this class asserts.
        #
        # Stubbed at `resolve` rather than at its callers, which was the first
        # attempt and was whack-a-mole: `main` reaches the same line through
        # `available()` *and* `unverified()`, and patching one left the other. It is
        # the single choke point - the only `shutil.which` in the module, and what
        # every lookup goes through.
        with mock.patch.object(sys, "platform", platform), \
                mock.patch.object(flow.refine, "resolve", return_value=None), \
                mock.patch.object(flow.profile, "DEFAULT_PATH", path), \
                mock.patch.object(flow.diag, "Diag"), \
                mock.patch.object(mod, "Session"), \
                mock.patch.object(flow.asr, "WhisperTranscriber"), \
                mock.patch.object(flow.ui, "Pill") as pill, \
                contextlib.redirect_stdout(out):
            code = mod.main(["--no-speak", "--no-lexicon", *argv])
        self.assertIsNone(pill.call_args.kwargs["hotkeys"])
        return code, out.getvalue()

    def said(self, out: str) -> list[str]:
        """The registration report, matched on the line rather than on the word.

        Lite's banner says "no global hotkeys" in prose, so an assertion that cannot tell
        that apart from a `hotkey` line is asserting nothing.
        """
        return [ln for ln in out.splitlines() if ln.startswith("hotkey")]

    def test_a_lite_launch_with_overrides_starts_and_says_nothing_about_them(self):
        code, out = self.launch(self.OVERRIDES, ["--lite"])
        self.assertEqual(code, 0)
        self.assertEqual(self.said(out), [])

    def test_and_an_unusable_block_does_not_stop_a_lite_launch_either(self):
        code, out = self.launch("ctrl+alt+space", ["--lite"])
        self.assertEqual(code, 0)
        self.assertEqual(self.said(out), [])

    def test_a_mac_launch_reads_the_field_without_reaching_for_win32(self):
        # The import that is not there: `flow.hotkey` cannot be loaded on darwin, so a
        # profile field that needed it to be understood would be a hand-edited shortcut
        # that stops Flow from starting on the platform Lite exists for.
        code, out = self.launch(self.OVERRIDES, ["--lite"], platform="darwin")
        self.assertEqual(code, 0)
        self.assertIn("on darwin", out)

    @unittest.skipUnless(sys.platform == "win32", "Windows-only: ctypes.WinDLL")
    def test_no_hotkeys_reads_no_override_because_it_registers_none(self):
        code, out = self.launch(self.OVERRIDES, ["--no-hotkeys"])
        self.assertEqual(code, 0)
        self.assertEqual(self.said(out), [])

    @unittest.skipUnless(sys.platform == "win32", "Windows-only: ctypes.WinDLL")
    def test_and_an_unusable_block_is_not_named_under_that_flag_either(self):
        code, out = self.launch("ctrl+alt+space", ["--no-hotkeys"])
        self.assertEqual(code, 0)
        self.assertEqual(self.said(out), [])


if __name__ == "__main__":
    unittest.main()

@unittest.skipUnless(sys.platform == "win32",
                     "Windows-only: launch() imports flow.hotkey, which binds user32 "
                     "at import time")
class TestTheModelIsLoadedBeforeItIsAskedFor(unittest.TestCase):
    """"loading the model" used to be the first thing a fresh Flow said back.

    Skipped off Windows, and the skip is not squeamishness: `launch("win32")` patches
    `sys.platform` but `main()` then really imports `flow.hotkey`, which calls
    `ctypes.WinDLL("user32")` at module scope. Nothing a patch can do about that — the
    import is real even when the platform is pretend.

    It said it in the bubble, while somebody was already speaking, because the load lands
    *inside* the first utterance rather than in front of it — first partial 1 230 ms
    against ~570 ms for the four behind it. The chord's press-down has warmed the models
    since push-to-talk shipped, which covers the second use and not the first.
    """

    def test_startup_warms_the_session(self):
        _code, _out, _pill, session = launch("win32")
        session.return_value.warm.assert_called_once()

    def test_it_happens_off_windows_too(self):
        # The load is the same load and the wait is the same wait; nothing about it is
        # platform-shaped.
        _code, _out, _pill, session = launch("darwin")
        session.return_value.warm.assert_called_once()

    def test_no_warm_leaves_it_for_the_first_word(self):
        # For a launcher that starts with the machine, where paying a model load at
        # login is the wrong trade — and for measuring the cold path on purpose.
        _code, _out, _pill, session = launch("win32", ["--no-warm"])
        session.return_value.warm.assert_not_called()


class TestTheDesignSwitch(unittest.TestCase):
    """`--design` / `profile.design` choose which surface is built.

    The switch is launch-time by construction (decisions.md 2026-09-03, "The compact
    design"): `main()` resolves the name once, before any window tree exists, and the
    menu writes the profile for the *next* launch. What is pinned here is the wiring —
    which class is constructed for which name, and that the flag is a remembered
    setting the way `--cli-model` is, not a one-run override.
    """

    def setUp(self) -> None:
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = Path(d.name)

    def launch(self, argv=()):
        import flow.asr
        import flow.diag
        import flow.profile
        import flow.ui
        import flow.ui_compact

        import flow.__main__ as mod

        out = io.StringIO()
        with mock.patch.object(sys, "platform", "darwin"), \
                mock.patch.object(flow.profile, "DEFAULT_PATH",
                                  self.dir / "profile.json"), \
                mock.patch.object(flow.diag, "Diag"), \
                mock.patch.object(mod, "Session"), \
                mock.patch.object(flow.asr, "WhisperTranscriber"), \
                mock.patch.object(flow.ui, "Pill") as pill, \
                mock.patch.object(flow.ui_compact, "CompactPill") as compact, \
                contextlib.redirect_stdout(out):
            code = mod.main(["--no-speak", "--no-lexicon", *argv])
        return code, out.getvalue(), pill, compact

    def test_the_default_launch_builds_the_shipped_pill(self):
        code, out, pill, compact = self.launch()
        self.assertEqual(code, 0)
        self.assertTrue(pill.called)
        self.assertFalse(compact.called)
        # Nothing to report when nothing was chosen: the shipped design is the default,
        # and a line naming it every launch would be noise about the ordinary case.
        self.assertNotIn("design:", out)

    def test_the_flag_builds_the_compact_pill_and_is_remembered(self):
        code, out, pill, compact = self.launch(["--design", "compact"])
        self.assertEqual(code, 0)
        self.assertTrue(compact.called)
        self.assertFalse(pill.called)
        self.assertIn("design: compact", out)
        from flow.profile import Profile
        self.assertEqual(Profile(self.dir / "profile.json").design, "compact")

    def test_the_remembered_choice_needs_no_flag(self):
        self.launch(["--design", "compact"])
        _code, _out, pill, compact = self.launch()
        self.assertFalse(pill.called)
        self.assertTrue(compact.called)

