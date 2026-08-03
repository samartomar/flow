"""Choosing which voice reads the replies (P9).

Flow spoke in whichever voice the engine defaulted to for its whole life, and on the
development machine that was `Microsoft David Desktop` — the oldest one installed, never
chosen by anybody. Two things came out of fixing that and both are pinned here.

The first is that "what is installed" depends on which PowerShell asks. `System.Speech`
is a .NET API with two implementations: Windows PowerShell 5.1 enumerated two voices on
that machine, PowerShell 7 enumerated five, and the three it adds are the OneCore ones —
the store Windows registers every modern voice in. A host that cannot see that store can
never be given a good voice, so the enumeration and the speech host must run under the
same executable or the menu offers names the host will refuse.

The second is that a request should not have to be exact. `--voice female` and
`--voice mark` are how people actually ask.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.speak import HOSTS, VOICE_PREFIX, Voice, host, pick  # noqa: E402

#: What `pwsh` reported on the development machine, in the order it reported it — the
#: legacy pair first, which is why order alone is not a safe way to choose.
INSTALLED = [
    Voice("Microsoft David Desktop", "Male", "en-US"),
    Voice("Microsoft Zira Desktop", "Female", "en-US"),
    Voice("Microsoft David", "Male", "en-US"),
    Voice("Microsoft Mark", "Male", "en-US"),
    Voice("Microsoft Zira", "Female", "en-US"),
]


class TestPick(unittest.TestCase):
    def test_no_request_means_no_opinion(self):
        # None is "let the engine decide", which is the behaviour Flow had before any
        # of this — not a failure, and not a silent substitution.
        self.assertIsNone(pick(None, INSTALLED))
        self.assertIsNone(pick("", INSTALLED))

    def test_an_exact_name_is_honoured_even_when_it_is_the_old_one(self):
        # The preference below must never override someone who named a voice: they have
        # heard it and decided, which beats any rule this module has.
        self.assertEqual(
            pick("Microsoft Zira Desktop", INSTALLED), "Microsoft Zira Desktop"
        )

    def test_a_gender_picks_the_newer_engine(self):
        # Both Ziras are female and the legacy one is listed first, so enumeration order
        # would hand back exactly the voice this feature exists to get away from.
        self.assertEqual(pick("female", INSTALLED), "Microsoft Zira")
        self.assertEqual(pick("male", INSTALLED), "Microsoft David")

    def test_part_of_a_name_is_enough(self):
        self.assertEqual(pick("mark", INSTALLED), "Microsoft Mark")
        self.assertEqual(pick("MARK", INSTALLED), "Microsoft Mark")

    def test_a_partial_match_also_prefers_the_newer_engine(self):
        self.assertEqual(pick("zira", INSTALLED), "Microsoft Zira")

    def test_a_voice_that_is_not_installed_resolves_to_nothing(self):
        # Never a substitution. A profile naming a voice that has since been removed
        # falls back to the default, and the caller is the one that says so out loud.
        self.assertIsNone(pick("Microsoft Aria (Natural)", INSTALLED))

    def test_no_voices_at_all(self):
        self.assertIsNone(pick("female", []))

    def test_english_is_preferred_when_a_gender_matches_several(self):
        voices = [
            Voice("Microsoft Hanako", "Female", "ja-JP"),
            Voice("Microsoft Zira", "Female", "en-US"),
        ]
        self.assertEqual(pick("female", voices), "Microsoft Zira")

    def test_a_non_english_voice_is_still_reachable_by_name(self):
        voices = [Voice("Microsoft Hanako", "Female", "ja-JP")]
        self.assertEqual(pick("hanako", voices), "Microsoft Hanako")
        # ...and is still the answer when it is the only one of its gender.
        self.assertEqual(pick("female", voices), "Microsoft Hanako")


class TestHost(unittest.TestCase):
    """*Which* host is chosen. That it arrives as a path is `test_speak.py`'s question.

    These three asserted the bare name until 2026-08-03, when SPEECH-04 made `host()`
    keep what the lookup returned. The preference order they pin has not moved at all —
    only what a chosen host is spelled as, which is why the edit is to the expectation
    and not to the case.
    """

    def test_the_modern_shell_is_preferred(self):
        with mock.patch("flow.speak.shutil.which", side_effect=lambda n: f"/x/{n}"), \
             mock.patch("flow.speak._HOST", None):
            self.assertEqual(host(), "/x/pwsh")

    def test_it_falls_back_to_the_one_every_windows_has(self):
        with mock.patch("flow.speak.shutil.which",
                        side_effect=lambda n: None if n == "pwsh" else "/x/powershell"), \
             mock.patch("flow.speak._HOST", None):
            self.assertEqual(host(), "/x/powershell")

    @unittest.skipUnless(sys.platform == "win32", "Windows-only: the PowerShell speech host")
    def test_with_neither_found_it_still_returns_something_runnable(self):
        # Guessing beats raising: `Speaker` already degrades to silent when the host
        # will not start, and `which` failing is not proof the shell is absent. What the
        # guess *is* changed with SPEECH-04 — `HOSTS[-1]` was a name, and a name reaching
        # `Popen` is resolved by a search that reads the current directory first, so the
        # branch that existed to be safe was the last one that was not.
        with mock.patch("flow.speak.shutil.which", return_value=None), \
             mock.patch("flow.speak._HOST", None):
            found = host()
        self.assertTrue(found.lower().endswith(f"{HOSTS[-1]}.exe"), found)
        self.assertNotEqual(found, HOSTS[-1], "a bare name is what CreateProcess searches")


class TestEnumeration(unittest.TestCase):
    """`installed_voices` parses the host's output, and must not trust it."""

    def _voices(self, stdout):
        with mock.patch("flow.speak._CACHE", None), \
             mock.patch("flow.speak.subprocess.run") as run:
            run.return_value = mock.Mock(stdout=stdout)
            from flow.speak import installed_voices

            return installed_voices(refresh=True)

    def test_it_reads_the_marked_lines(self):
        out = (f"{VOICE_PREFIX}Microsoft Mark|Male|en-US\n"
               f"{VOICE_PREFIX}Microsoft Zira|Female|en-US\n")
        self.assertEqual(
            self._voices(out),
            [Voice("Microsoft Mark", "Male", "en-US"),
             Voice("Microsoft Zira", "Female", "en-US")],
        )

    def test_unmarked_output_is_ignored(self):
        # PowerShell prints things nobody asked for — a profile banner, a warning about
        # an execution policy. None of them are voices.
        out = ("WARNING: something\n"
               f"{VOICE_PREFIX}Microsoft Mark|Male|en-US\n"
               "PS D:\\> \n")
        self.assertEqual(self._voices(out), [Voice("Microsoft Mark", "Male", "en-US")])

    def test_a_malformed_line_is_dropped_rather_than_half_read(self):
        out = (f"{VOICE_PREFIX}broken\n"
               f"{VOICE_PREFIX}|Male|en-US\n"
               f"{VOICE_PREFIX}Microsoft Mark|Male|en-US\n")
        self.assertEqual(self._voices(out), [Voice("Microsoft Mark", "Male", "en-US")])

    def test_no_engine_is_an_empty_list_and_not_a_crash(self):
        with mock.patch("flow.speak._CACHE", None), \
             mock.patch("flow.speak.subprocess.run", side_effect=OSError("no shell")):
            from flow.speak import installed_voices

            self.assertEqual(installed_voices(refresh=True), [])


class TestProfileRemembersTheVoice(unittest.TestCase):
    def test_it_survives_a_round_trip(self):
        import tempfile

        from flow.profile import Profile

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "profile.json"
            p = Profile(path)
            p.voice = "Microsoft Mark"
            self.assertTrue(p.save())
            self.assertEqual(Profile(path).voice, "Microsoft Mark")

    def test_a_profile_written_before_voices_existed_still_loads(self):
        # Additive, so no schema bump: an older file has no `voice` key and has to load
        # as "no opinion" rather than refusing and resetting someone's calibration.
        import json
        import tempfile

        from flow.profile import SCHEMA, Profile

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "profile.json"
            path.write_text(json.dumps({"schema": SCHEMA, "floor_db": -96.5}))
            p = Profile(path)
            self.assertIsNone(p.voice)
            self.assertEqual(p.floor_db, -96.5)


if __name__ == "__main__":
    unittest.main()
