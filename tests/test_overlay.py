"""Panel size: how wide the draft bubble and the conversation card draw.

Three widths, chosen from a menu, remembered in the profile. The interesting part is
what the setting is *not* allowed to do, because the constants it moves were not chosen
by taste — each carries a measurement in its comment, and a size setting is exactly the
kind of change that quietly invalidates one.

  **It cannot go below 400.** 420 was the floor while the chips were a row of words —
  the bubble's five-chip row ran to 345 px and the card's to 377. The secondaries are
  marks on the pill row now (compact pass, 2026-09-01), so the floor is the row's own
  budget: app slot, mic, meter, four marks, three icons and the label, which
  `test_compact_pass.py` adds up. A panel narrower than that loses a mark, and the clamp is
  tested, not just written down.

  **It cannot change what today's users see.** `regular` has to reproduce the shipped
  numbers exactly. A size setting that also silently re-flowed everybody's draft would
  be two changes shipped as one, and only one of them was asked for.

  **The two windows cannot drift apart.** The bubble and the card are the same window at
  two moments, docked to the same pill, and a width that moved one without the other
  would be visible the first time somebody switched modes.

`apply_panel_width` rebinds module globals, which is a concession to twenty-odd read
sites across two window classes rather than a preference — so these tests put the module
back the way they found it, and one of them checks that a launch which never calls it is
the launch Flow always had.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import flow.ui as ui  # noqa: E402
from flow.profile import PANEL_DEFAULT, Profile  # noqa: E402

#: The shipped numbers, captured at import before any test moves them. Written as
#: literals as well, because a test that compared the module to itself would pass just
#: as happily after somebody changed all four.
SHIPPED = {"BUBBLE_W": 400, "CARD_W": 400,
           "BODY_CHARS_PER_LINE": 64, "BODY_TAIL_CHARS": 1806}


class PanelWidth(unittest.TestCase):
    """Restores the module afterwards: these globals outlive the test that moved them."""

    def setUp(self):
        self.addCleanup(ui.apply_panel_width, ui.PANEL_WIDTHS[ui.PANEL_DEFAULT])

    def widths(self) -> dict:
        return {name: getattr(ui, name) for name in SHIPPED}


class TestTheShippedWidthIsUntouched(PanelWidth):
    def test_the_module_starts_where_it_always_did(self):
        # Before anything calls `apply_panel_width` at all — the state of a launch that
        # never got as far as reading a profile, and of every test module that imports
        # `flow.ui` for some other reason.
        self.assertEqual(self.widths(), SHIPPED)

    def test_and_asking_for_regular_puts_it_back_exactly(self):
        # The promise to everybody who never opens this menu. A size setting that also
        # re-flowed their draft would be two changes shipped as one.
        ui.apply_panel_width(ui.PANEL_WIDTHS["large"])
        ui.apply_panel_width(ui.PANEL_WIDTHS["regular"])
        self.assertEqual(self.widths(), SHIPPED)

    def test_the_default_name_means_the_shipped_width(self):
        self.assertEqual(ui.PANEL_WIDTHS[ui.PANEL_DEFAULT], SHIPPED["BUBBLE_W"])


class TestTheFloorHoldsBecauseSendMustStayReachable(PanelWidth):
    def test_a_width_below_the_floor_is_clamped_to_it(self):
        # Below the floor the pill row loses its leftmost mark — Refine — before
        # anything else; see `Pill._draw_marks`.
        for asked in (0, 1, 100, 379, 399, -50):
            with self.subTest(asked=asked):
                ui.apply_panel_width(asked)
                self.assertEqual(ui.BUBBLE_W, SHIPPED["BUBBLE_W"])

    def test_no_offered_size_is_below_the_floor(self):
        # A guard on the menu rather than on the clamp: an entry that had to be clamped
        # would be a row somebody could pick that silently did nothing.
        for name, width in ui.PANEL_WIDTHS.items():
            with self.subTest(name=name):
                self.assertGreaterEqual(width, SHIPPED["BUBBLE_W"])

    def test_the_sizes_only_go_up(self):
        # Stated as a property because it is a design decision and not an accident:
        # there is no "small", and the reason is the chip row rather than restraint.
        self.assertEqual(min(ui.PANEL_WIDTHS.values()), SHIPPED["BUBBLE_W"])


class TestTheTwoWindowsMoveTogether(PanelWidth):
    def test_the_card_follows_the_bubble_at_every_size(self):
        # One window at two moments, docked to the same pill. A width that moved one
        # without the other is visible the first time somebody switches mode.
        for width in ui.PANEL_WIDTHS.values():
            with self.subTest(width=width):
                ui.apply_panel_width(width)
                self.assertEqual(ui.CARD_W, ui.BUBBLE_W)


class TestTheMeasurementsScaleWithTheColumn(PanelWidth):
    def test_a_wider_panel_lays_out_more_text(self):
        # `BODY_CHARS_PER_LINE` frozen at one width would under-feed the canvas at 640 px
        # put the bottom of the draft below the fold — the setting would make the thing
        # it exists to improve worse.
        seen = []
        for width in sorted(ui.PANEL_WIDTHS.values()):
            ui.apply_panel_width(width)
            seen.append((ui.BODY_CHARS_PER_LINE, ui.BODY_TAIL_CHARS))
        self.assertEqual(seen, sorted(seen))
        self.assertLess(seen[0][0], seen[-1][0])

    def test_the_tail_stays_the_same_number_of_lines(self):
        # What `BODY_TAIL_CHARS` really encodes is ~28 lines, which is what keeps render
        # cost flat (invariant 7). Holding lines rather than characters is what carries
        # that invariant across a width change instead of re-measuring it.
        lines = []
        for width in ui.PANEL_WIDTHS.values():
            ui.apply_panel_width(width)
            lines.append(round(ui.BODY_TAIL_CHARS / ui.BODY_CHARS_PER_LINE))
        self.assertEqual(len(set(lines)), 1, lines)

    def test_a_line_is_never_zero_characters(self):
        # The clamp exists because this number is divided by. It cannot be reached
        # through the menu; it can be reached by a future width and a smaller font.
        ui.apply_panel_width(0)
        self.assertGreaterEqual(ui.BODY_CHARS_PER_LINE, 1)


class TestANameIsTurnedIntoAWidth(PanelWidth):
    def test_every_offered_name_resolves_to_its_own_width(self):
        for name, width in ui.PANEL_WIDTHS.items():
            with self.subTest(name=name):
                self.assertEqual(ui.panel_width(name), width)

    def test_case_and_spacing_are_the_writers_business(self):
        # This is a value a hand-edit can put in `profile.json`, so it reads the way
        # every other hand-written value in that file does.
        for text in ("LARGE", "Large", "  large  ", "lArGe"):
            with self.subTest(text=text):
                self.assertEqual(ui.panel_width(text), ui.PANEL_WIDTHS["large"])

    def test_anything_unknown_is_the_shipped_width_rather_than_a_refusal(self):
        # Deliberately the opposite of how `hotkey.parse` treats a bad combo, and the
        # difference is what each costs when wrong. A hotkey that silently fell back
        # leaves somebody pressing keys that do nothing with no way to find out; a panel
        # that falls back is a window visibly not the size they asked for, with the
        # evidence on the screen.
        for value in ("enormous", "", None, 7, ["large"], {"large": 1}, True):
            with self.subTest(value=value):
                self.assertEqual(ui.panel_width(value), SHIPPED["BUBBLE_W"])


class TestTheProfileRemembersIt(PanelWidth):
    def test_the_two_modules_agree_on_the_default_name(self):
        # `flow/profile.py` spells the default itself rather than importing it, because
        # it is read on every launch including Lite's and `flow.ui` is not something it
        # may need. That buys platform reach and costs exactly this risk, so the risk is
        # bought back here.
        self.assertEqual(PANEL_DEFAULT, ui.PANEL_DEFAULT)
        self.assertIn(PANEL_DEFAULT, ui.PANEL_WIDTHS)

    def test_it_survives_a_save_and_a_load(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            p = Profile(path)
            p.panel = "large"
            self.assertTrue(p.save())
            again = Profile(path)
            self.assertTrue(again.load())
            self.assertEqual(again.panel, "large")
            self.assertNotIn("panel", again.faults)

    def test_a_fresh_profile_asks_for_the_shipped_width(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            p = Profile(Path(tmp) / "profile.json")
            self.assertEqual(ui.panel_width(p.panel), SHIPPED["BUBBLE_W"])

    def test_a_nonsense_value_in_the_file_is_named_and_still_launches(self):
        # Both halves matter. `faults` is how `--stats` and the startup block say a
        # setting degraded, and the launch has to survive it: a profile is not a thing
        # somebody can be locked out of the app by.
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            path.write_text(json.dumps({"schema": 1, "panel": 7}), encoding="utf-8")
            p = Profile(path)
            self.assertTrue(p.load())
            self.assertIn("panel", p.faults)
            self.assertEqual(ui.panel_width(p.panel), SHIPPED["BUBBLE_W"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
