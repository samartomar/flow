"""The compact panel's band, which grows with its text.

`.shots/11-compact-refine-panel.png` is the photograph this file exists for.
The band was a fixed 200 px of fixed rows: `RESULT_Y = 108`, the result's first
line at 124, an 18 px line box, and the footer chips at 156 — so the second
line of a refined prompt ran at 142-160, straight through Copy and Send. Both
blocks were cut to two lines as well, which meant a ten-line Ask answer showed
two, and the Refine result — the text Send is about to paste — could not be
read before it was sent. And `_fit` collapsed the text with `text.split()`, so
Refine.dc.html's own worked example, a lead line and three bullets, displayed
as one run-on paragraph while Send pasted the real shape.

The artboards grow with their text (`design/compact/gen.py`: `.shell` has no
height, every block is padding around its own content). So does the band now:
`CompactPill._panel_layout` computes the height and every row from the panel's
state, `PANEL_H` is its floor rather than its size, and one piece of arithmetic
answers for the drawing, the window, and the hit tests.

The fixtures are `test_ui_compact`'s own — the fake `Canvas` has no `measure`,
so `_line_height` falls back to the nominal 18 px `LINE_NOMINAL` names.
"""

import unittest
from pathlib import Path
from unittest import mock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import flow.ui_compact as uc  # noqa: E402
from flow.session import CONVERSE, Event, REFINE, State  # noqa: E402
from test_ui_compact import Canvas, panel_pill, pill, session  # noqa: E402

# Keep the imported names honest: `Canvas`, `pill` and `session` are the
# fixtures this module is required to share rather than re-declare, and the
# panels below reach them through `panel_pill`.
assert Canvas is not None and pill is not None and session is not None

#: A ten-line answer, one line to a line: the Ask case the fixed band showed
#: two of. Each is short enough that `LINE_CHARS` never re-wraps it, so the
#: line count in the layout is the line count written here.
TEN_LINES = "\n".join(f"answer line {i}, short enough not to wrap"
                      for i in range(10))
#: Refine.dc.html's own worked example: a lead line, a blank, and three
#: bullets, one of them indented the way spoken "tab" resolves it.
BULLETS = ("Strip every control from the push-to-talk pill in flow/ui.py.\n"
           "\n"
           "- fix the tests\n"
           "    - keep the 34 px height\n"
           "- update docs/product.md to match")


def open_panel(mode=CONVERSE, *, heard="", result="", final=True, y=400,
               failed=False, state=State.IDLE):
    """A pill with the band up, its blocks filled, and a window to measure."""
    p = panel_pill(state, mode=mode, y=y)
    p._panel_open = True
    p._panel_mode = mode
    p._panel_heard = heard
    p._panel_heard_final = final
    p._panel_result = result
    p._panel_failed = failed
    return p


def text_span(item, line_h: int) -> tuple:
    """The `(top, bottom)` a recorded `create_text` occupies.

    The fake canvas keeps the call, not a rendered box, so the box is rebuilt
    the way the painter would: a multi-line run is one line box per line at
    the band's own `line_h`, and the anchor says whether the y it was given is
    the top edge or the vertical centre (`GdiCanvas.create_text`'s own rule).
    """
    (_x, y), text, _fill, font, anchor, _w = item
    size = abs(font[1]) if font and len(font) > 1 else 12
    h = (len(text.split("\n")) - 1) * line_h + size + 4
    if anchor not in ("center", "centre") and "n" in set(anchor):
        return (y, y + h)
    return (y - h / 2, y + h / 2)


def rows(p, layout) -> list:
    """The band's rows top to bottom as `(name, top, bottom)` — what the
    layout says it laid out, in the order the artboards stack them."""
    out = [("strip", 0, uc.STRIP_H)]
    if layout.heard_tag_y is not None:
        out.append(("heard tag", layout.heard_tag_y - 8,
                    layout.heard_tag_y + 8))
    if layout.heard:
        n = len(layout.heard.split("\n"))
        out.append(("heard", layout.heard_y, layout.heard_y + n * layout.line_h))
    if layout.result_tag_y is not None:
        out.append(("result tag", layout.result_tag_y - 8,
                    layout.result_tag_y + 8))
    if layout.result:
        n = len(layout.result.split("\n"))
        out.append(("result", layout.result_y,
                    layout.result_y + n * layout.line_h))
    out.append(("footer", layout.footer_y, layout.footer_y + uc.CHIP_H))
    return out


class TestTheRestingBandIsTheArtboards(unittest.TestCase):
    """A panel with nothing in it yet keeps the proportions `Refine.dc.html`
    and `Ask.dc.html` were drawn at — 200 px of band on a 34 px foot."""

    def test_an_empty_panel_is_the_floor_and_the_window_is_400x234(self):
        p = panel_pill(mode=CONVERSE, x=100, y=400)
        p._open_panel()
        self.assertEqual(p._panel_layout().band_h, uc.PANEL_H)
        p.geometry.assert_called_once_with("400x234+100+200")

    def test_a_one_line_exchange_still_sits_in_the_floor(self):
        p = open_panel(CONVERSE, heard="where does the pill decide?",
                       result="PILL_HOLD_SEC, 0.30 s.")
        self.assertEqual(p._panel_layout().band_h, uc.PANEL_H)

    def test_the_footer_sits_at_the_bottom_of_whatever_band_there_is(self):
        # Pinned to the bottom edge, not to a row number: that is what makes
        # the chips travel with the band instead of being overrun by it.
        layout = open_panel(CONVERSE)._panel_layout()
        self.assertEqual(layout.footer_y,
                         layout.band_h - uc.FOOT_PAD - uc.CHIP_H)
        self.assertEqual((layout.copy, layout.send),
                         (uc.COPY_RECT, uc.SEND_RECT))


class TestTheBandGrowsWithItsText(unittest.TestCase):
    """Ask.dc.html's card and Refine.dc.html's bullets both grow the panel;
    the fixed 200 px band showed two lines of either."""

    def test_a_ten_line_answer_grows_the_band(self):
        p = open_panel(CONVERSE, result=TEN_LINES)
        layout = p._panel_layout()
        self.assertEqual(len(layout.result.split("\n")), 10)
        self.assertGreater(layout.band_h, uc.PANEL_H)
        # Ten lines of body plus the block's own air, all of it above the foot.
        self.assertEqual(layout.band_h,
                         layout.result_y + 10 * layout.line_h
                         + uc.FOOT_PAD + uc.CHIP_H + uc.FOOT_PAD)

    def test_the_footer_and_both_chips_move_down_with_it(self):
        short = open_panel(CONVERSE, result="one line")._panel_layout()
        tall = open_panel(CONVERSE, result=TEN_LINES)._panel_layout()
        grew = tall.band_h - short.band_h
        self.assertEqual(tall.footer_y - short.footer_y, grew)
        self.assertEqual(tall.copy[1] - short.copy[1], grew)
        self.assertEqual(tall.send[1] - short.send[1], grew)
        # And the chips keep their own height and their column.
        self.assertEqual(tall.copy[3] - tall.copy[1], uc.CHIP_H)
        self.assertEqual((tall.copy[0], tall.send[2]),
                         (short.copy[0], short.send[2]))

    def test_the_window_grows_with_the_band(self):
        p = open_panel(CONVERSE, result=TEN_LINES, y=400)
        p._sync_shell()
        band = p._panel_layout().band_h
        p.geometry.assert_called_once_with(
            f"400x{band + uc.PILL_H}+100+{400 - band}")
        # The capsule never moved: the band grew upward off it (README, "the
        # pill never hides and never moves").
        self.assertEqual(p._capsule_y, 400)

    def test_the_ask_card_bar_spans_the_answer_it_belongs_to(self):
        p = open_panel(CONVERSE, result=TEN_LINES)
        p._draw()
        layout = p._panel_layout()
        (bar,) = [r for r in p.canvas.rects if r[4] == uc.CARD_ACCENT]
        self.assertEqual((bar[1], bar[3]),
                         (layout.result_y, layout.result_y + 10 * layout.line_h))


class TestTheCapIsTheOnlyCut(unittest.TestCase):
    """Twelve lines is the artboards' scale — 216 px of answer, which with the
    heard block, the footer and the foot still stands on a 1080 display."""

    def test_a_long_answer_stops_at_the_cap_with_an_ellipsis(self):
        p = open_panel(CONVERSE, y=1000, result="\n".join(
            f"line {i} of a very long answer" for i in range(40)))
        result = p._panel_layout().result
        self.assertEqual(len(result.split("\n")), uc.RESULT_LINES_MAX)
        self.assertTrue(result.endswith("…"), result[-30:])

    def test_the_heard_block_stops_at_four(self):
        p = open_panel(REFINE, heard=" ".join(
            f"word{i}" for i in range(200)), result="the shaped prompt")
        heard = p._panel_layout().heard
        self.assertEqual(len(heard.split("\n")), uc.HEARD_LINES_MAX)
        self.assertTrue(heard.endswith("…"))

    def test_the_caps_are_higher_than_the_fixed_band_could_show(self):
        # The defect in one line: the old budget was two lines each.
        self.assertGreater(uc.RESULT_LINES_MAX, 2)
        self.assertGreater(uc.HEARD_LINES_MAX, 2)


class TestNothingOverlaps(unittest.TestCase):
    """The photographed defect, asserted: every row the band draws is below
    the one before it and clear of it, and every text item lands inside the
    row the layout put it in."""

    def check(self, p):
        layout = p._panel_layout()
        p._draw()
        ordered = rows(p, layout)
        for (name, _t, bottom), (nxt, top, _b) in zip(ordered, ordered[1:]):
            with self.subTest(gap=f"{name} -> {nxt}"):
                self.assertLessEqual(bottom, top,
                                     f"{name} runs into {nxt}")
        # Every drawn word sits in one of them. The result's second line
        # through the Copy chip is exactly what this catches.
        for item in p.canvas.texts:
            top, bottom = text_span(item, layout.line_h)
            with self.subTest(text=item[1][:24]):
                self.assertTrue(
                    any(t <= top and bottom <= b for _n, t, b in ordered),
                    f"{item[1][:24]!r} at {top}-{bottom} is in no row: "
                    f"{ordered}")
        # And the chips are the footer row, below everything above it.
        for rect in (layout.copy, layout.send):
            self.assertEqual((rect[1], rect[3]),
                             (layout.footer_y, layout.footer_y + uc.CHIP_H))
        self.assertLessEqual(ordered[-2][2], layout.footer_y)
        return layout

    def test_the_refine_panel_the_photograph_caught(self):
        # `.shots/11-compact-refine-panel.png`: the raw dictation, then a
        # refined prompt of more than one line, then Copy and Send.
        p = open_panel(REFINE, heard=(
            "make the pill not show any controls just the mic and when i let "
            "go it should paste in the window i was in before and also update "
            "the doc"), result=BULLETS)
        layout = self.check(p)
        self.assertGreater(layout.band_h, uc.PANEL_H)

    def test_the_ask_panel_with_a_long_answer(self):
        self.check(open_panel(CONVERSE, heard="where does the pill decide?",
                              result=TEN_LINES))

    def test_the_resting_panels_of_both_modes(self):
        for mode in (REFINE, CONVERSE):
            with self.subTest(mode=mode):
                self.check(open_panel(mode))

    def test_a_panel_mid_hold_with_only_a_partial(self):
        self.check(open_panel(CONVERSE, heard="where does the", final=False))

    def test_a_failed_refine_which_has_no_tag_to_make_room_for(self):
        self.check(open_panel(
            REFINE, heard="make the pill not show any controls", failed=True,
            result="refine failed (timed out after 20s) — draft unchanged"))


class TestFitKeepsTheShape(unittest.TestCase):
    """`_fit` used to be `text.split()`, which threw the newlines and the
    indentation away — Refine.dc.html's bullets drew as one paragraph while
    Send pasted the real thing."""

    def test_the_speakers_paragraphs_survive(self):
        out = uc._fit("a lead line\n\n- one\n- two", uc.LINE_CHARS, 12)
        self.assertEqual(out, "a lead line\n\n- one\n- two")

    def test_leading_indentation_survives(self):
        # Spoken "tab dash fix the tests" resolves to an indented bullet, and
        # the panel has to show the shape it is about to paste.
        out = uc._fit("do this:\n    - fix the tests", uc.LINE_CHARS, 12)
        self.assertEqual(out.split("\n")[1], "    - fix the tests")

    def test_an_indent_is_paid_for_out_of_its_own_line(self):
        # The indent is not free width: a wrapped indented line stays inside
        # the block rather than running off the right edge.
        out = uc._fit("        " + " ".join(["word"] * 30), 30, 12)
        for line in out.split("\n"):
            self.assertLessEqual(len(line), 30 + len("word"))

    def test_a_long_paragraph_still_wraps_to_the_line_budget(self):
        out = uc._fit(" ".join(["word"] * 40), 20, 12)
        self.assertGreater(len(out.split("\n")), 1)
        for line in out.split("\n"):
            self.assertLessEqual(len(line.rstrip("…")), 20 + len(" word"))

    def test_the_cap_counts_across_paragraphs_and_ellipsises(self):
        out = uc._fit("\n".join(f"line {i}" for i in range(10)),
                      uc.LINE_CHARS, 3)
        self.assertEqual(len(out.split("\n")), 3)
        self.assertTrue(out.endswith("…"))

    def test_nothing_to_say_is_no_lines_at_all(self):
        # Which is what lets an empty block cost the band nothing.
        self.assertEqual(uc._fit("", uc.LINE_CHARS, 4), "")
        self.assertEqual(uc._fit("\n\n", uc.LINE_CHARS, 4), "")


class TestTheBandFootSplitFollowsTheRealHeight(unittest.TestCase):
    """The foot is the holdable part and the band is the part with buttons on
    it — a split that was `PANEL_H` and is the band's own height now."""

    def test_a_press_at_the_old_panel_line_inside_a_taller_band_is_a_chip_press(self):
        p = open_panel(CONVERSE, result=TEN_LINES)
        self.assertGreater(p._panel_layout().band_h, uc.PANEL_H)
        p._on_press(mock.Mock(x=200, y=uc.PANEL_H, x_root=0, y_root=0))
        # Inside the band: hit-tested against the chips, and no hold begun.
        self.assertIsNone(p._press_at)
        self.assertTrue(p._panel_open)

    def test_the_copy_chip_of_a_tall_band_is_reachable(self):
        p = open_panel(CONVERSE, result=TEN_LINES)
        rect = p._panel_layout().copy
        with mock.patch.object(uc, "_copy_to_clipboard",
                               return_value="") as copy:
            p._on_press(mock.Mock(x=rect[0] + 4, y=rect[1] + 4,
                                  x_root=0, y_root=0))
        copy.assert_called_once_with(p, TEN_LINES)
        self.assertIsNone(p._press_at)

    def test_the_foot_below_a_tall_band_is_still_a_hold(self):
        p = open_panel(CONVERSE, result=TEN_LINES)
        band = p._panel_layout().band_h
        p._on_press(mock.Mock(x=60, y=band + 17, x_root=0, y_root=0))
        self.assertIsNotNone(p._press_at)


class TestTheWindowFollowsTheText(unittest.TestCase):
    """A band that changed height while it was open has to take its window
    with it, or the foot is drawn below the bottom of the window."""

    def test_a_reply_that_needs_more_room_resizes_the_window(self):
        p = panel_pill(State.ASKING, mode=CONVERSE, x=100, y=400)
        p._panel_open = True
        p._panel_mode = CONVERSE
        p._frame()
        p.geometry.reset_mock()
        p.session.events.return_value = [Event("reply", TEN_LINES)]
        p._frame()
        band = p._panel_layout().band_h
        self.assertGreater(band, uc.PANEL_H)
        p.geometry.assert_called_with(
            f"400x{band + uc.PILL_H}+100+{400 - band}")

    def test_a_partial_that_adds_lines_resizes_the_window(self):
        # A partial grows the heard block, and the blocks below it move down
        # by the same amount. Set up under an answer, because that is the only
        # arrangement in which four lines of heard can push the band past its
        # own floor.
        p = open_panel(REFINE, result=BULLETS, heard="make the pill", y=600)
        p._frame()
        before = p._panel_layout().band_h
        p.geometry.reset_mock()
        p.session.events.return_value = [Event("partial", " ".join(
            f"word{i}" for i in range(120)))]
        p._frame()
        after = p._panel_layout().band_h
        self.assertGreater(after, before)
        p.geometry.assert_called_with(
            f"400x{after + uc.PILL_H}+100+{600 - after}")

    def test_a_band_that_did_not_change_does_not_touch_the_window(self):
        p = open_panel(CONVERSE, result="the answer")
        p._frame()
        p.geometry.reset_mock()
        p._frame()
        p.geometry.assert_not_called()


class TestTheBandStaysOnTheScreen(unittest.TestCase):
    """It grows upward from the capsule, so what it can grow into is the room
    between the capsule's top edge and the work area's."""

    def test_a_band_that_would_not_fit_shrinks_its_result_lines(self):
        long_answer = "\n".join(f"line {i} of a very long answer"
                                for i in range(40))
        roomy = open_panel(CONVERSE, result=long_answer, y=1000)
        cramped = open_panel(CONVERSE, result=long_answer, y=300)
        self.assertEqual(len(roomy._panel_layout().result.split("\n")),
                         uc.RESULT_LINES_MAX)
        tight = cramped._panel_layout()
        self.assertLess(len(tight.result.split("\n")), uc.RESULT_LINES_MAX)
        # Shrunk, not clipped: the band fits above the capsule, and the cut
        # still says it happened.
        self.assertLessEqual(tight.band_h, 300)
        self.assertTrue(tight.result.endswith("…"))

    def test_it_never_shrinks_below_the_resting_band(self):
        # A pill parked against the top of the work area has no room at all;
        # the answer is the artboards' own proportions, not a band of nothing.
        p = open_panel(CONVERSE, result="\n".join(
            f"line {i}" for i in range(40)), y=0)
        layout = p._panel_layout()
        self.assertEqual(layout.band_h, uc.PANEL_H)
        self.assertGreaterEqual(len(layout.result.split("\n")), 1)

    def test_the_work_areas_top_is_what_it_measures_against(self):
        p = open_panel(CONVERSE, result="\n".join(
            f"line {i} of a very long answer" for i in range(40)), y=500)
        p.work = (0, 300, 1920, 1080)   # a band across the top of the display
        self.assertLessEqual(p._panel_layout().band_h, 200)
        p.work = (0, 0, 1920, 1080)
        self.assertGreater(p._panel_layout().band_h, 200)


if __name__ == "__main__":
    unittest.main()
