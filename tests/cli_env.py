"""Make the agent CLI a fact the test declares, not one the machine happens to have.

Found the honest way, on 2026-08-02: the release workflow ran the suite on a clean
GitHub runner for the first time and **14 tests failed that had never failed here**. All
of them mock the process layer — `subprocess.Popen`, or `refine._invoke` — and then
assert on the prompt that reached it. None of them ever reached it on the runner, because
`refine.available()` filters `CANDIDATES` through `shutil.which`, and a runner has
neither `codex` nor `claude`. The code refused correctly and the mock sat untouched, so
the failures were real and the tests were wrong: they were reading the developer's PATH
as a premise.

Patching `shutil.which` rather than `available` is deliberate. `flow/session.py` does
`from .refine import available`, so it holds its own reference — replacing the attribute
on `flow.refine` would fix `_invoke_any` and leave `Session._provider()` still looking at
the real PATH. `which` is inside the one function both of them call, so patching it moves
every consumer at once, and the fake defers to the real one for anything it is not
pretending about — `speak.HOSTS` resolves its PowerShell exactly as it otherwise would.

What this does *not* do is stub the CLI's behaviour. The process layer is still mocked by
whichever test uses it; this only settles the question of which CLI the code believes it
may call, which is the question a PATH was accidentally answering.
"""

import contextlib
import os
import shutil
from unittest import mock

import flow.refine as refine

#: Captured at import, before any patch is in place, so the fake can defer to it.
_REAL_WHICH = shutil.which

#: Absolute **on the platform the suite is running on**, which it has to be and was not.
#:
#: The same lesson as the docstring above, one predicate along, and found the same way —
#: by CI on a machine that is not this one. This was the Windows literal everywhere, which
#: nothing minded until `refine.trusted()` began requiring `os.path.isabs` (item 47).
#: `ntpath.isabs("C:\\fake\\codex.exe")` is True and `posixpath.isabs` of the same string
#: is **False**, so on the Linux and macOS legs every test that carefully declared a CLI
#: got no CLI: `trusted()` refused the fake, `resolve()` returned None, the code refused
#: correctly, and the mocked `Popen` sat untouched. 25 tests, and not one of them was
#: about paths.
#:
#: The suffix stays `.exe` on every platform on purpose. It is a fake, and `SHIM_SUFFIXES`
#: is the only thing that reads it — a per-platform suffix would quietly change what the
#: `.cmd` refusal tests are testing.
#:
#: Chosen by asking `refine.trusted` rather than by reading `sys.platform`, which is not
#: pedantry: the property this needs is "acceptable to the predicate that will judge it",
#: and a platform check is a *guess* about what that predicate will say.
#:
#: It asked `os.path.isabs` until 2026-08-15, which was the same guess one step closer —
#: and the guess broke on a venv built with a newer Python. `ntpath.isabs("/x/pwsh")` is
#: True on 3.12 and **False on 3.13+**, where a single leading slash is correctly read as
#: "the current drive" rather than as a location. Every test that hand-wrote a `/`-rooted
#: fake path got no CLI on 3.14 for exactly the reason the Linux leg got none in 2026-08:
#: `trusted()` refused the fake, `resolve()` returned None, and the mocked `Popen` sat
#: untouched. Seven tests, and not one of them was about paths.
#:
#: So this now asks the function itself, which cannot drift from it by construction — and
#: `fake_exe` is the one spelling of "where a declared CLI pretends to live" in the suite,
#: because two spellings is how one of them goes stale.
_FAKE_DIR = next(
    d for d in ("C:\\fake", "/fake") if refine.trusted(os.path.join(d, "probe.exe"))
)


def fake_exe(name: str) -> str:
    """Where a declared CLI pretends to live. Absolute, and never the working directory."""
    return os.path.join(_FAKE_DIR, f"{name}.exe")


@contextlib.contextmanager
def no_off_path_installs():
    """No entry's off-PATH probe fires, whatever this machine happens to have installed.

    The same lesson as this module's docstring, one seam along. `kiro-cli` is found by an
    AppData probe as well as by PATH — because the MSI's PATH entry does not reach a shell
    that predates it — so on a machine with it installed, a test that carefully declared
    what PATH holds would still be answered by the developer's disk. Patched at `resolve`'s
    own helper rather than at `os.path.isfile`, which half the suite uses for its own
    reasons.
    """
    with mock.patch.object(refine, "probed", return_value=None):
        yield


@contextlib.contextmanager
def cli_on_path(name: str = "codex"):
    """Run the block with `name` appearing on PATH, and nothing else changed."""

    def which(cmd, *args, **kwargs):
        if cmd == name:
            return fake_exe(name)
        return _REAL_WHICH(cmd, *args, **kwargs)

    with mock.patch("shutil.which", which), no_off_path_installs():
        yield


@contextlib.contextmanager
def no_cli_on_path():
    """The other half: no agent CLI is installed, whatever this machine has."""

    def which(cmd, *args, **kwargs):
        if cmd in [c.name for c in refine.CANDIDATES]:
            return None
        return _REAL_WHICH(cmd, *args, **kwargs)

    with mock.patch("shutil.which", which), no_off_path_installs():
        yield
