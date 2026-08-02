"""How the self-drive harness delivers audio, which is a property worth pinning.

Rule 2's same-check tripwire fired twice on `spoken: 'capitalize sameer'` — 2026-08-01 and
2026-08-02, both rerun green, both after sustained CPU load — and the owner's call was to
fix rather than quarantine it (decisions.md, "Five words from the owner"). The fix is a
*seam*: that one check submits its cached WAV as a final utterance instead of letting the
gate and the block pump assemble one.

**This module asserts the seam and deliberately not the flake.** A check that waits for a
marginal decode to flip would be the variance itself promoted to a gate — red only
sometimes, which is exactly the property being removed. What is testable, always and
cheaply, is which delivery path each correction case takes; that is what changed, and it is
what a future tidy would undo.

Nothing here starts a decoder or a Tk root. The scenario is run with both delivery methods
recorded, so what is measured is the routing rather than the outcome.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import selfdrive  # noqa: E402


class RecordedDriver:
    """Stands in for `Driver`, remembering which way each utterance was delivered.

    A real `Driver` builds a `Session` with the real two-tier decoder behind it, which is
    minutes of model load for a question about routing. The two delivery methods are the
    whole of what this needs to see.
    """

    #: (name, method) in the order the scenario asked for them, across all instances.
    calls: list[tuple[str, str]] = []

    def __init__(self, *a, **kw) -> None:
        self.session = mock.Mock()
        self.session.draft.text = "a draft that changed"

    def speak(self, text: str, name: str, timeout: float = 90.0) -> None:
        self.calls.append((name, "speak"))

    def speak_decoded(self, text: str, name: str, timeout: float = 90.0) -> None:
        self.calls.append((name, "speak_decoded"))

    def notes(self) -> list[str]:
        return []


def routes() -> dict[str, str]:
    """Run `scenario_corrections` against the recorder and return name -> method."""
    RecordedDriver.calls = []
    with mock.patch.object(selfdrive, "Driver", RecordedDriver):
        selfdrive.scenario_corrections(lambda *a, **kw: None)
    return dict(RecordedDriver.calls)


class TestTheMarginalCheckDecodesWithoutTheRoom(unittest.TestCase):
    """One check bypasses the gate; the other four do not, and the count does not move."""

    def test_the_capitalize_case_submits_its_cached_wav_directly(self):
        # The tripwire's check. Before this item it went through `speak` like the rest,
        # so the array the decoder saw was assembled by `blocks()` padding and the gate's
        # own boundary decisions — a different slice on a loaded machine than on an idle
        # one, which is what a marginal decode notices.
        self.assertEqual(routes().get("cmd_cap"), "speak_decoded")

    def test_the_other_four_still_travel_the_acoustic_path(self):
        # The loop is what this harness is *for*. One check asking a narrower question is
        # not the harness being made cheaper, and the difference has to be visible.
        taken = routes()
        acoustic = {n: m for n, m in taken.items() if n != "cmd_cap"}
        self.assertEqual(sorted(acoustic), ["cmd_del_last", "cmd_ins", "cmd_lower",
                                            "cmd_repl_all"])
        for name, method in acoustic.items():
            with self.subTest(case=name):
                self.assertEqual(method, "speak", "a second check left the gate")

    def test_the_check_count_is_unchanged(self):
        # Five correction cases, five reports, so the gate stays 64-shaped. A seam that
        # quietly dropped a case would still pass both checks above.
        reports: list = []
        RecordedDriver.calls = []
        with mock.patch.object(selfdrive, "Driver", RecordedDriver):
            selfdrive.scenario_corrections(lambda *a, **kw: reports.append(a))
        self.assertEqual(len(reports), 5)
        self.assertEqual(len(RecordedDriver.calls), 5)

    def test_the_direct_path_is_the_sessions_own_final_submit(self):
        # What must *not* be removed along with the room: the decoder, the router and the
        # apply. `submit_final` is the seam `Session._finalise` itself uses, so everything
        # downstream of it is the shipped path — this pins that the shortcut starts there
        # and not somewhere further along, where it would be testing much less.
        source = Path(selfdrive.__file__).read_text(encoding="utf-8")
        body = source.partition("def speak_decoded")[2].partition("\n    def ")[0]
        self.assertIn("submit_final", body,
                      "the direct path must go in at the session's own final seam")
        self.assertNotIn("draft.set", body, "it may not shortcut past the router")


class TestTheLearningScenarioIsNotTouched(unittest.TestCase):
    """It says "sameer" too, and it is a different check about a different thing.

    `scenario_learning` exists to prove that a correction said *twice* becomes a decode
    bias — recorded, promoted, then reaching the decoder as a hotword. Its whole subject is
    speech arriving repeatedly, so it keeps the acoustic path. Asserted here because a
    shared word is exactly the kind of thing that gets tidied together later.
    """

    def test_it_still_speaks_through_the_microphone(self):
        seen: list[tuple[str, str]] = []

        class Recorder(RecordedDriver):
            def speak(self, text: str, name: str, timeout: float = 90.0) -> None:
                seen.append((name, "speak"))

            def speak_decoded(self, text: str, name: str, timeout: float = 90.0) -> None:
                seen.append((name, "speak_decoded"))

        with mock.patch.object(selfdrive, "Driver", Recorder), \
                mock.patch.object(selfdrive, "Profile", create=True):
            try:
                selfdrive.scenario_learning(lambda *a, **kw: None)
            except Exception:
                pass  # it reaches for a real Profile and Lexicon; the routing is recorded
        self.assertTrue(seen, "the learning scenario spoke nothing")
        for name, method in seen:
            with self.subTest(case=name):
                self.assertEqual(method, "speak", "the learning check left the gate")


if __name__ == "__main__":
    unittest.main()
