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
import shutil
from unittest import mock

import flow.refine as refine

#: Captured at import, before any patch is in place, so the fake can defer to it.
_REAL_WHICH = shutil.which


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
            return f"C:\\fake\\{name}.exe"
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
