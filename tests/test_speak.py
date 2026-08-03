"""Which PowerShell speaks, and where it came from (SPEECH-04).

`host()` is resolved once and used twice — the voice enumeration and the speech host must
be the same executable or the menu offers names the host will refuse, which `test_voice.py`
is about. This module is about the other property of that one answer: it names a file on
disk rather than a word, so nothing between the lookup and `CreateProcess` can be handed a
different program under the same name.

The distinction is not theoretical. Storing `"pwsh"` and passing it to `Popen` means the
lookup that decided PowerShell was available and the search that actually starts it are two
different searches, run at two different moments, under two different rule sets — `which`
honours `PATHEXT`, `CreateProcess` appends `.exe`, and until `main()` closes it, both look
in the current directory first.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

sys.path.insert(0, str(Path(__file__).resolve().parent))

import flow.speak as speak  # noqa: E402
from test_refine import in_planted_workspace  # noqa: E402


def fresh_host():
    """`host()` with its cache cleared, restored afterwards."""
    speak._HOST = None
    return speak.host()


class TestTheHostIsAPathAndNotAWord(unittest.TestCase):

    def setUp(self) -> None:
        cached = speak._HOST
        self.addCleanup(setattr, speak, "_HOST", cached)

    def test_host_stores_what_the_lookup_returned(self):
        found = str(Path(tempfile.gettempdir()) / "PowerShell" / "pwsh.exe")
        with mock.patch("shutil.which", lambda name, *a, **k: found if name == "pwsh"
                        else None):
            self.assertEqual(fresh_host(), found)

    def test_the_second_host_is_reached_the_same_way(self):
        # `powershell` is the guaranteed one — 5.1 ships with the OS — and it must arrive
        # as a path too, or the fallback quietly reintroduces exactly what the first
        # branch was fixed for.
        found = "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
        with mock.patch("shutil.which",
                        lambda name, *a, **k: found if name == "powershell" else None):
            self.assertEqual(fresh_host(), found)

    def test_a_workspace_copy_is_refused_and_the_real_one_used(self):
        real = "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"

        def which(name, *a, **k):
            return ".\\pwsh.EXE" if name == "pwsh" else real

        with mock.patch("shutil.which", which):
            self.assertEqual(fresh_host(), real)

    def test_nothing_found_falls_back_to_a_location_and_not_a_name(self):
        # This check was written asserting `HOSTS[-1]` — the bare name — and the planted
        # workspace probe below is what corrected it. A workspace holds *both* names, so
        # both lookups are refused and the fallback is the branch that runs; a bare name
        # there is handed straight to `CreateProcess`, which searches the current
        # directory. The safe branch was the only unsafe one left.
        with mock.patch("shutil.which", lambda *a, **k: None):
            found = fresh_host()
        self.assertTrue(os.path.isabs(found), found)
        self.assertTrue(found.lower().endswith("v1.0\\powershell.exe"), found)

    def test_the_fallback_follows_systemroot(self):
        # Addressed, but not hard-coded to C:. An install on another drive is unusual
        # rather than impossible, and the variable is what Windows itself reads.
        with mock.patch("shutil.which", lambda *a, **k: None), \
                mock.patch.dict(os.environ, {"SystemRoot": "E:\\Windows"}, clear=False):
            self.assertTrue(fresh_host().startswith("E:\\Windows"), fresh_host())

    def test_it_is_still_resolved_only_once(self):
        with mock.patch("shutil.which", lambda name, *a, **k: "C:\\ps\\pwsh.exe") as _:
            first = fresh_host()
        with mock.patch("shutil.which", lambda *a, **k: "C:\\other\\pwsh.exe"):
            self.assertEqual(speak.host(), first)


class TestNoPlantedPowerShellIsEverTheHost(unittest.TestCase):
    """The same probe `test_refine.py` uses, pointed at the speech host.

    Kept here rather than folded into that module's class because the failure is a
    different one: refine refuses a bad *answer*, and this asserts the answer is specific
    enough to refuse at all. A bare name has nothing to inspect.
    """

    def test_the_resolved_host_is_absolute_in_a_planted_workspace(self):
        out = in_planted_workspace("from flow import speak\nprint(speak.host())",
                                   guarded=False)
        self.assertNotIn(".\\pwsh", out)
        self.assertNotIn("planted-", out)
        self.assertTrue(os.path.isabs(out), out)


if __name__ == "__main__":
    unittest.main()
