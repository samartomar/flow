"""The compact pass of 2026-09-01, pinned.

The command marks left the band they had atop every panel and moved to the pill row's
empty middle; the row shrank to 34 px with 14 px icons; padding, chip heights, the
minimum panel height, the body font and the three panel widths all came down. What is
asserted here is the part that could silently regress: that the widest set of marks
still fits the narrowest panel, that the pill draws and dispatches them, that a mark
says its word in the label slot, and that a panel no longer reserves a band for marks
it does not draw.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import flow.ui as ui  # noqa: E402
from flow.session import DICTATE, State  # noqa: E402
from test_bubble import bubble, draft  # noqa: E402
from test_pill import pill  # noqa: E402

FOUR = [("Refine", "Refine", None), ("Continue", "Continue", None),
        ("Edit", "Edit", None), ("Was a command", "Was a command", None)]


def row_budget(width: int) -> tuple[float, float]:
    """(where the marks may start, where they must end) on a row `width` wide, with
    the app-name slot showing — the arithmetic `Pill._draw` and `_draw_marks` use."""
    shift = ui.APP_SLOT_W + ui.APP_SLOT_GAP
    icons_w = 3 * ui.ICON_SIZE + 2 * ui.ICON_GAP
    icons_x = width - ui.LABEL_PAD - ui.LABEL_SLOT_W - ui.LABEL_GAP - icons_w
    floor_x = ui.METER_X + ui.METER_W + shift + ui.MARK_AIR
    return floor_x, icons_x - ui.ICON_GAP


class TestTheWidestSetOfMarksFitsTheNarrowestRow(unittest.TestCase):
    def test_four_marks_fit_at_every_offered_width(self):
        need = 4 * ui.COMMAND_H + 3 * ui.COMMAND_GAP
        for name, width in ui.PANEL_WIDTHS.items():
            with self.subTest(name=name):
                floor_x, right = row_budget(width)
                self.assertGreaterEqual(right - need, floor_x,
                                        f"{name}: {right - floor_x:.0f} px for {need}")

    def test_the_row_is_shorter_than_it_was(self):
        self.assertLessEqual(ui.PILL_H, 34)
        self.assertLessEqual(ui.ICON_SIZE, 14)
        self.assertLessEqual(ui.PAD, 10)
        self.assertEqual(min(ui.PANEL_WIDTHS.values()), ui.PANEL_WIDTHS[ui.PANEL_DEFAULT])

    def test_the_ceiling_is_on_the_snap_grid(self):
        # `_settled_h` steps a line at a time from the minimum; a ceiling off that grid
        # is a height it clamps to a pixel short of, which is the 183 != 184 the old
        # numbers produced the moment a note pushed a panel to the top.
        self.assertEqual((ui.PANEL_MAX_H - ui.PANEL_MIN_H) % ui.BODY_LINE_H, 0)


def pill_with(marks, *, visible=True, converse=False):
    p = pill(State.DRAFT, mode=ui.CONVERSE if converse else DICTATE,
             _docked_w=ui.BUBBLE_W, _flash=0, _tint=0.0)
    surface = SimpleNamespace(_visible=visible, _marks=list(marks))
    p.__dict__["card" if converse else "bubble"] = surface
    return p


def binding(p, key, sequence):
    tag = ui.chip_tag(key)
    return next((f for t, seq, f in p.canvas.bindings if t == tag and seq == sequence),
                None)


class TestThePillDrawsTheMarks(unittest.TestCase):
    def test_every_published_mark_gets_a_hit_region(self):
        p = pill_with(FOUR)
        p._draw()
        for key, _l, _c in FOUR:
            self.assertIsNotNone(binding(p, key, "<Button-1>"), key)

    def test_a_click_runs_the_command_the_surface_published(self):
        pressed = []
        p = pill_with([("Refine", "Refine", lambda: pressed.append("refine")),
                       ("Edit", "Edit", lambda: pressed.append("edit"))])
        p._draw()
        binding(p, "Edit", "<Button-1>")(None)
        binding(p, "Refine", "<Button-1>")(None)
        self.assertEqual(pressed, ["edit", "refine"])

    def test_the_binding_reads_the_current_command_not_the_first(self):
        # One binding per tag for the life of the canvas (a `tag_bind` per repaint leaks
        # a Tcl command), so the dispatch has to look the command up at the click.
        first, second = [], []
        p = pill_with([("Copy", "Copy", lambda: first.append(1))], converse=True)
        p._draw()
        p.card._marks = [("Copy", "Copy", lambda: second.append(1))]
        p._draw()
        binding(p, "Copy", "<Button-1>")(None)
        self.assertEqual((first, second), ([], [1]))

    def test_a_hidden_surface_offers_nothing(self):
        p = pill_with(FOUR, visible=False)
        p._draw()
        self.assertIsNone(binding(p, "Refine", "<Button-1>"))

    def test_the_marks_sit_between_the_meter_and_the_icons(self):
        p = pill_with(FOUR)
        p.session.target_app = "code.exe"
        p._draw()
        floor_x, right = row_budget(ui.BUBBLE_W)
        # A mark's box is the one polygon on the row filled `CHIP`: the chrome is
        # `SHELL`, the bars take the accent, the gear its own colour.
        boxes = []
        for args, fill in p.canvas.polys:
            if fill != ui.CHIP:
                continue
            pts = args[0] if len(args) == 1 else args  # one list, or flat coordinates
            xs = [float(x) for x in list(pts)[0::2]]
            boxes.append((min(xs), max(xs)))
        self.assertEqual(len(boxes), 4, boxes)
        for left, right_edge in boxes:
            self.assertGreaterEqual(left, floor_x - 1)
            self.assertLessEqual(right_edge, right + 1)

    def test_a_mark_with_no_room_is_dropped_from_the_left(self):
        p = pill_with(FOUR)
        p._docked_w = 300  # narrower than any offered width: room for two marks
        p._draw()
        self.assertIsNone(binding(p, "Refine", "<Button-1>"),
                          "Refine should be the first to go")
        self.assertIsNotNone(binding(p, "Was a command", "<Button-1>"),
                             "the rightmost mark keeps its fixed address")


class TestAMarkSaysItsWordInTheLabelSlot(unittest.TestCase):
    def test_hovering_shows_the_word_and_leaving_takes_it_back(self):
        p = pill_with(FOUR)
        p._draw()
        self.assertEqual(p._bar_label(), "HELD")
        binding(p, "Refine", "<Enter>")(None)
        self.assertEqual(p._bar_label(), "REFINE")
        binding(p, "Refine", "<Leave>")(None)
        self.assertEqual(p._bar_label(), "HELD")

    def test_the_long_names_have_a_word_that_fits_the_slot(self):
        widest = max(len(w) for w in ui.BAR_LABELS.values())
        widest = max(widest, len(ui.LABEL_NO_INPUT), len(ui.LABEL_SPEAKING))
        for key in ui.COMMAND_GLYPHS:
            word = ui.Pill.MARK_WORDS.get(key, key.upper())
            self.assertLessEqual(len(word), widest, key)


class TestNoPanelReservesABandForMarksItDoesNotDraw(unittest.TestCase):
    def test_the_draft_starts_at_the_top_padding(self):
        b = bubble(draft(120))
        b._render()
        body = next(i for i in b.canvas.items if i["text"] == b._text)
        self.assertEqual(body["y"], ui.PAD)

    def test_the_sent_card_starts_at_the_top_padding_too(self):
        b = bubble(draft(120))
        b.show_sent(b._text)
        label = next(i for i in b.canvas.items if i["text"] == "sent")
        self.assertEqual(label["y"], ui.PAD)

    def test_a_wait_with_no_note_costs_no_extra_line(self):
        b = bubble(draft(120))
        b._render()
        plain = b._h
        b._act = SimpleNamespace(label="refining", waiting=True)
        b._dot = 0
        b._render()
        self.assertEqual(b._h, plain, "the activity row took a line of its own")
        self.assertTrue(any(i["text"] == "refining" for i in b.canvas.items),
                        "the wait was not drawn at all")

    def test_a_three_line_draft_is_a_short_panel(self):
        b = bubble(draft(3 * ui.BODY_CHARS_PER_LINE - 20))
        b._render()
        self.assertLessEqual(b._h, ui.PANEL_MIN_H + 4 * ui.BODY_LINE_H)


if __name__ == "__main__":
    unittest.main()
