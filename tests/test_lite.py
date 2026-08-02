"""Flow Lite: the definition first, and then the body that has to obey it.

One module for both halves on purpose. The fence — *features land in full Flow first, and
reach Lite only if they survive without hands* — is a rule about how features travel, so
the place it can go wrong is the gap between what product.md promises and what the pill
does. Kept together, a definition that drifts from the build fails beside it.

This half reads `docs/product.md`, the idiom `test_workshop.py`'s `TestP9SaysWhatItNowIs`
already established: the product definition is a file the suite is allowed to hold to its
word, because a promise nothing checks is the one that goes stale first.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PRODUCT = Path(__file__).resolve().parent.parent / "docs" / "product.md"

#: The four things Lite is *not*, from the decision entry. Stated as exclusions rather
#: than as "not yet": each one is what buys the only property Lite has that full Flow does
#: not — nothing to grant beyond the microphone.
EXCLUSIONS = ("injection", "global hotkeys", "auto-paste", "target-window awareness")


def product() -> str:
    return PRODUCT.read_text(encoding="utf-8")


def section(body: str, title: str) -> str:
    """One `##` section's text, up to the next one at the same level.

    Anchored on the heading rather than on a phrase, so a test about the Lite section
    cannot be satisfied by a sentence somewhere else in the file that happens to use the
    same words.
    """
    m = re.search(rf"^##+ .*{re.escape(title)}.*$", body, re.M | re.I)
    if m is None:
        return ""
    rest = body[m.end():]
    nxt = re.search(r"^## ", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


class TestProductMdKnowsThereAreTwoBodies(unittest.TestCase):
    def setUp(self):
        self.body = product()

    def test_environments_says_which_half_is_portable_and_which_is_not(self):
        # The whole distribution argument in one paragraph: the brain and ear are Python
        # with cross-platform wheels, the hands are Win32. Without it, "Lite" reads as a
        # cut-down edition rather than as the part that was always portable.
        env = section(self.body, "Environments")
        self.assertTrue(env, "product.md has no Environments section")
        low = env.lower()
        self.assertIn("portable", low)
        self.assertIn("win32", low)
        self.assertIn("macos", low)

    def test_the_lite_section_names_every_one_of_the_four_exclusions(self):
        # Four, by name. A Lite section that lists three is a definition somebody will
        # build the fourth against, which is exactly what a fence is for.
        lite = section(self.body, "Flow Lite").lower()
        self.assertTrue(lite, "product.md has no Flow Lite section")
        for item in EXCLUSIONS:
            self.assertIn(item, lite, f"the Lite definition does not exclude {item!r}")

    def test_lite_says_what_it_is_and_not_only_what_it_is_not(self):
        lite = section(self.body, "Flow Lite").lower()
        for part in ("brain", "ear", "clipboard"):
            self.assertIn(part, lite)
        # The one property the exclusions buy, and the reason they are worth paying.
        self.assertIn("microphone", lite)

    def test_the_fence_reads_in_the_load_bearing_direction(self):
        # The direction is the whole sentence. "Features land in Lite first and reach full
        # Flow if they survive" uses every word this could grep for and means the
        # opposite, so the assertion is on the order the two names appear in.
        #
        # Unwrapped first: the file is hard-wrapped at 88 characters, so a sentence-level
        # assertion that respects the line breaks is asserting the margin, not the prose.
        flat = " ".join(self.body.split())
        fence = next(
            (s for s in re.split(r"(?<=[.])\s+", flat) if "survive without hands" in s),
            "",
        )
        self.assertTrue(fence, "the fence sentence is not in product.md")
        self.assertLess(
            fence.index("full Flow"), fence.lower().index("lite"),
            f"the fence points the wrong way: {fence!r}",
        )
        self.assertIn("first", fence)

    def test_the_clipboard_hop_is_named_as_the_measurement(self):
        # The port decision waits on a number, and a definition that does not say which
        # number leaves it waiting on an impression.
        self.assertIn("clipboard hop", self.body.lower())

    def test_lite_names_the_two_requirements_it_cannot_meet(self):
        # Named, not implied. P7 is Flow's promise that a paste arrives unexecuted, and
        # Lite is not doing the pasting; P9's loop ends in the terminal, and Lite ends on
        # the clipboard. A body that quietly claims all nine would be the definition
        # lying on the build's behalf.
        lite = section(self.body, "Flow Lite")
        self.assertIn("P7", lite)
        self.assertIn("P9", lite)

    def test_the_p_table_is_not_renumbered_and_gains_no_row(self):
        # Lite is a body that meets a subset of the requirements, not a tenth requirement.
        # A "P10: also works without hands" would make the fence a thing to satisfy rather
        # than a rule about how the other nine travel.
        rows = re.findall(r"^\| (P\d+) \|", self.body, re.M)
        self.assertEqual(rows, [f"P{n}" for n in range(1, 10)])

    def test_the_non_goals_are_untouched(self):
        # Lite subtracts a body, not a scope. If a non-goal moved while this section was
        # being written, it moved for the wrong reason.
        goals = section(self.body, "Non-goals")
        for lead in ("Multilingual output", "Cloud ASR or any API key",
                     "Writing code by voice", "General voice control",
                     "Being an AI itself"):
            self.assertIn(lead, goals)


if __name__ == "__main__":
    unittest.main()
