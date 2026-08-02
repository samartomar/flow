"""The entry point, and the one thing it has to do before it does anything else.

Flow is Windows-only and always has been — `inject.py`, `hotkey.py` and `ui.py` each
call `ctypes.WinDLL("user32")` at import time, which is 96 Win32 call sites' worth of
reason. What was new when the repo went public is the audience: someone on a Mac can now
clone it, and the first thing the product would say to them was a ctypes traceback from
an import they never asked for.

The failure is reproduced here rather than described. `None` in `sys.modules` makes an
import of a name raise, which is the same shape as `ctypes.WinDLL` not existing on
darwin — so `no_win32()` below imports Flow the way a Mac would, on this machine, and
the guard either speaks first or the import explodes exactly as it would there.
"""

import contextlib
import importlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

#: The three modules that touch Win32 at import time. Nothing else in the package does:
#: `session`, `asr`, `lexicon`, `refine` and `audio` are all portable, which is why the
#: distribution decision could say the brain ports and the body does not.
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


class TestTheNonWindowsGuard(unittest.TestCase):
    def test_the_entry_point_imports_at_all_without_win32(self):
        # The guard is worth nothing if an import above it has already run: this is
        # the assertion that keeps the three Win32 imports inside `main()`, below the
        # check, where a Mac never reaches them.
        with no_win32():
            importlib.import_module("flow.__main__")

    def test_and_a_mac_gets_one_sentence_instead_of_a_stack(self):
        with no_win32():
            mod = importlib.import_module("flow.__main__")
            code, out = run_main(mod, "darwin")
        lines = [ln for ln in out.splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1, out)
        self.assertIn("Windows-only", lines[0])
        self.assertIn("darwin", lines[0])
        self.assertEqual(code, 2)

    def test_it_names_whichever_platform_it_found(self):
        with no_win32():
            mod = importlib.import_module("flow.__main__")
            _code, out = run_main(mod, "linux")
        self.assertIn("linux", out)

    def test_the_refusal_is_ascii_like_every_other_startup_line(self):
        # `say()` documents why: a redirected stdout on a legacy console code page
        # cannot encode an en-dash, so a message with one crashes instead of printing.
        # This message is the last one that may crash — it is the only thing its reader
        # is ever going to see.
        with no_win32():
            mod = importlib.import_module("flow.__main__")
            _code, out = run_main(mod, "darwin")
        out.encode("cp437")
        out.encode("ascii")

    def test_the_flags_are_not_parsed_before_the_refusal(self):
        # It sits above argparse deliberately. A Mac user typing a flag that does not
        # exist should be told the true problem, not the smaller one.
        with no_win32():
            mod = importlib.import_module("flow.__main__")
            code, out = run_main(mod, "darwin", ["--not-a-flag"])
        self.assertEqual(code, 2)
        self.assertIn("Windows-only", out)


class TestItDoesNotFireHere(unittest.TestCase):
    """Windows is the platform this runs on, so the guard has to be invisible."""

    def test_help_still_prints_and_exits_zero(self):
        from flow.__main__ import main

        out = io.StringIO()
        with mock.patch.object(sys, "platform", "win32"):
            with contextlib.redirect_stdout(out):
                with self.assertRaises(SystemExit) as caught:
                    main(["--help"])
        self.assertEqual(caught.exception.code, 0)
        self.assertIn("usage: flow", out.getvalue())
        self.assertNotIn("Windows-only", out.getvalue())


if __name__ == "__main__":
    unittest.main()
