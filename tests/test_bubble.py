"""The draft bubble under a draft nobody expected — the long-draft incident, fix side.

Live at the desk on 2026-08-02 a very long dictation took down five layers in a chain,
and this module pins the first link. `Bubble._render` measured and laid out the *whole*
draft on every partial, so two things grew together: the time one render costs, and the
window it sizes. Measured on the real canvas before the fix — 2.4 ms at 1 000 characters,
32.7 ms at 10 000, **476.7 ms at 50 000** — and at 50 000 the bubble measured itself
**15 153 px tall inside a 672 px work area**, which is where the Send chip was when the
spoken exits had already died with the microphone.

What this layer can and cannot see: the cost curve is Tk's own text wrapping and needs a
real canvas (`scratchpad/render_cost.py`, recorded in LOOP_PLAN's Evidence line). What is
worth having *permanently* is the property behind the curve — how much text `_render`
hands the canvas, and how tall it says it is — and a measuring fake can see both without a
desktop.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
#: `tests/` on the path in its own right, so `MeasuringCanvas` can be borrowed rather than
#: copied. A second fake that wraps text slightly differently is a second thing to keep
#: true, and the drift would be invisible: both would pass.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import flow.ui as ui  # noqa: E402
#: `WORK` joins `MeasuringCanvas` in being borrowed rather than copied, and for the same
#: reason: it is now a real input to `_render` — the window is fitted to the desktop before
#: anything reads the height — so two files disagreeing about how tall the desktop is would
#: be two layout answers, both passing.
from test_editor import WORK, MeasuringCanvas  # noqa: E402

WORD = "release notes about the migration on Tuesday with Sameer and the rollback plan "


def draft(n: int) -> str:
    """`n` characters of ordinary dictated prose — wrapping is what is being measured."""
    return (WORD * (n // len(WORD) + 1))[:n]


def bubble(text: str = "", **kw):
    """A bubble with a measuring canvas and no Tk, built the way test_editor builds one."""
    b = ui.Bubble.__new__(ui.Bubble)
    b.pill = mock.Mock()
    b.pill.accent = "#7dd3fc"
    b.pill.work = WORK
    b.pill.session = mock.Mock(
        mode="dictate", editing=False, can_rescue=False, can_take_reply=False,
        auto_ask_in=None,
    )
    b.canvas = MeasuringCanvas()
    b._text, b._sent, b._reply, b._partial, b._note = text, "", "", "", ""
    b._editor = None
    b._act = None
    b._h = 120
    b.reposition = lambda *a, **kw: None
    for name, value in kw.items():
        setattr(b, name, value)
    return b


def drawn_body(b) -> str:
    """What actually reached the canvas as the draft, ignoring probes and furniture.

    The probes are `create_text` calls too — `_render` measures before it draws — so the
    body is taken from the last item carrying it, which is the one on screen.
    """
    hits = [i for i in b.canvas.items if i["text"] and i["text"] in (b._sent or b._text)]
    return hits[-1]["text"] if hits else ""


class TestTheLayoutStopsGrowingWithTheDraft(unittest.TestCase):
    """Invariant 7 extended to rendering: a long session costs what a short one costs."""

    def test_the_body_handed_to_the_canvas_is_bounded(self):
        # The defect, stated as a number: at 50 000 characters the canvas was handed
        # 50 000 characters, and it wrapped every one of them before anything was drawn.
        for n in (10_000, 50_000):
            with self.subTest(chars=n):
                b = bubble(draft(n))
                b._render()
                self.assertLessEqual(
                    len(drawn_body(b)), ui.BODY_TAIL_CHARS,
                    f"a {n}-character draft laid out {len(drawn_body(b))} characters",
                )

    def test_a_draft_that_fits_is_drawn_whole(self):
        # The other half, and the one that makes this a window rather than a truncation:
        # nothing changes for the drafts people actually dictate.
        b = bubble(draft(400))
        b._render()
        self.assertEqual(drawn_body(b), b._text)

    def test_the_window_is_the_end_of_the_draft(self):
        # Tail-following, which is the whole of "like a terminal" for an append-only
        # stream: the newest words are the ones on screen.
        b = bubble(draft(50_000))
        b._text = b._text[:-20] + "the last words here"
        b._render()
        self.assertTrue(drawn_body(b).endswith("the last words here"))

    def test_no_word_is_cut_in_half(self):
        b = bubble(draft(50_000))
        b._render()
        shown = drawn_body(b)
        self.assertTrue(b._text.endswith(shown))
        self.assertLess(len(shown), len(b._text))
        # The character before the window is whitespace, so it opens on a whole word.
        self.assertTrue(b._text[-len(shown) - 1].isspace())

    def test_an_append_is_on_screen_without_scrolling(self):
        b = bubble(draft(50_000))
        b._render()
        b._text += " and one more thing about the rollback"
        b._render()
        self.assertIn("one more thing about the rollback", drawn_body(b))


class TestTheChipsNeverLeaveTheScreen(unittest.TestCase):
    """The visual rescue has to be reachable, especially when the spoken one is not."""

    def test_the_height_stops_tracking_the_draft(self):
        ten = bubble(draft(10_000))
        ten._render()
        fifty = bubble(draft(50_000))
        fifty._render()
        self.assertEqual(ten._h, fifty._h)

    def test_at_fifty_thousand_the_chip_row_is_inside_the_work_area(self):
        b = bubble(draft(50_000))
        b._render()
        left, top, right, bottom = WORK
        # `reposition` clamps the bubble inside the work area with 8 px of air at each
        # edge, so a bubble taller than that cannot be placed with its chips on screen —
        # which is exactly what happened, 15 153 px of it.
        self.assertLessEqual(
            b._h, bottom - top - 16,
            f"a 50k draft sizes the bubble to {b._h} px in a {bottom - top} px work area",
        )
        chip_top = b._h - ui.PAD - ui.CHIP_H
        self.assertGreater(chip_top, 0)

    def test_the_body_slot_is_capped_and_the_note_still_clears_the_chips(self):
        # The cap must not be paid for by the note, which is the defect test_editor's
        # `TestALongNoteDoesNotLandOnTheChips` exists for.
        b = bubble(draft(50_000))
        b._note = ("ask failed (codex failed to start: [WinError 2] The system cannot "
                   "find the file specified)")
        b._render()
        _top, note_bottom = b.canvas.band("WinError 2")
        self.assertLessEqual(note_bottom, b._h - ui.PAD - ui.CHIP_H)


class TestWhatWasLeftOutIsSaidSoFar(unittest.TestCase):
    """A window with nothing above it reads as the whole draft, which would be a lie."""

    def _elision(self, b) -> str:
        return next((i["text"] for i in b.canvas.items
                     if i["text"].startswith("…") and "earlier lines" in i["text"]), "")

    def test_a_windowed_draft_says_how_much_is_above_it(self):
        b = bubble(draft(50_000))
        b._render()
        self.assertRegex(self._elision(b), r"^… \d+ earlier lines$")

    def test_a_draft_that_fits_says_nothing(self):
        b = bubble(draft(400))
        b._render()
        self.assertEqual(self._elision(b), "")

    def test_the_count_grows_with_the_draft(self):
        counts = []
        for n in (10_000, 50_000):
            b = bubble(draft(n))
            b._render()
            counts.append(int(self._elision(b).split()[1]))
        self.assertLess(counts[0], counts[1])


class TestTheSentCardIsTheSameSlot(unittest.TestCase):
    """`_render` draws `self._sent or self._text` in one place, so it gets one rule."""

    def test_a_long_sent_card_is_windowed_too(self):
        b = bubble()
        b._sent = draft(50_000)
        b._sent_at = 0.0
        b._sent_left = None
        b._render()
        self.assertLessEqual(len(drawn_body(b)), ui.BODY_TAIL_CHARS)
        self.assertLessEqual(b._h, WORK[3] - WORK[1] - 16)


class TestTheArtifactReplyPathIsUnchanged(unittest.TestCase):
    """The decision says the draft path *joins* the artifact path, not that both move.

    A reply is bounded where it is produced — `refine.ASK_ARTIFACT_MAX_CHARS` — and it is
    read rather than dictated into, so it keeps its full-text probe. Asserted here so
    "both paths changed" cannot happen quietly.
    """

    def test_a_long_reply_is_drawn_whole(self):
        reply = draft(4_000)
        b = bubble()
        b._reply = reply
        b._render()
        drawn = [i["text"] for i in b.canvas.items if i["text"] == reply]
        self.assertTrue(drawn, "the reply was windowed or truncated")

    def test_the_reply_still_sizes_the_bubble(self):
        short = bubble()
        short._reply = draft(200)
        short._render()
        long_ = bubble()
        long_._reply = draft(4_000)
        long_._render()
        self.assertGreater(long_._h, short._h)


#: The four corners of the work area a pill can be dragged to. The bubble anchors above and
#: to the right of the pill, so these are the four directions the anchor can point off.
def corners(pill_w: int = None, pill_h: int = None):
    left, top, right, bottom = WORK
    pill_w = ui.PILL_W if pill_w is None else pill_w
    pill_h = ui.PILL_H if pill_h is None else pill_h
    return {
        "top-left": (left, top),
        "top-right": (right - pill_w, top),
        "bottom-left": (left, bottom - pill_h),
        "bottom-right": (right - pill_w, bottom - pill_h),
    }


def placed(b, x: int, y: int) -> tuple[int, int, int, int]:
    """Render with the pill at (x, y) and return the window rect `reposition` computes.

    The real `reposition` rather than the fixture's stub, and the geometry string it builds
    rather than a recomputation of it: what is being pinned is where the window is *put*.
    """
    b.pill.x, b.pill.y = x, y
    b.reposition = ui.Bubble.reposition.__get__(b)
    box: list[str] = []
    b.geometry = box.append
    b._render()
    size, _, offset = box[-1].partition("+")
    w, _, h = size.partition("x")
    px, _, py = offset.partition("+")
    return int(px), int(py), int(px) + int(w), int(py) + int(h)


class TestTheWindowIsInsideTheWorkAreaWhereverThePillIs(unittest.TestCase):
    """Item 37 bounded the draft's size; nothing bounded the window's placement.

    Measured on a real `tk.Tk` before the fix, with the pill put at each corner of the work
    area and the rect read back from `GetWindowRect` as well as from Tk — 12 of 36
    placements left the desktop, all of them on the reply path and all off the **bottom**:
    a 4 000-character answer sized the window **1 459 px** and a 12 000-character artifact
    **4 179 px**, both pinned at `top + 8` on a 672 px work area, so the chip row landed at
    screen y **1 427** and **4 147**.

    Worth saying plainly, because the decision reads the owner's screenshot the other way
    round: the **top** edge was never the breach. `max(top + EDGE_AIR, …)` has held it at
    every corner in every state. The finding stands exactly as the decision states it — the
    bubble leaves the screen by position and takes the chips with it — and the edge it
    leaves by is the bottom.
    """

    def states(self):
        return [
            ("1k draft", {"_text": draft(1_000)}),
            ("50k draft", {"_text": draft(50_000)}),
            ("4k reply", {"_reply": draft(4_000)}),
            ("12k artifact reply", {"_reply": draft(12_000)}),
        ]

    def test_every_edge_is_inside_the_work_area_at_every_corner(self):
        left, top, right, bottom = WORK
        for label, state in self.states():
            for corner, (px, py) in corners().items():
                with self.subTest(state=label, corner=corner):
                    x1, y1, x2, y2 = placed(bubble(**state), px, py)
                    self.assertGreaterEqual(y1, top, "the top edge left the work area")
                    self.assertLessEqual(y2, bottom, "the bottom edge left the work area")
                    self.assertGreaterEqual(x1, left)
                    self.assertLessEqual(x2, right)

    def test_the_chip_row_is_inside_it_too(self):
        # The property the height bound exists for, and the one a placed-only clamp would
        # fake: the row is drawn from `self._h`, so a window bounded without bounding the
        # height would put the chips below its own bottom edge and look fixed.
        _left, top, _right, bottom = WORK
        for label, state in self.states():
            for corner, (px, py) in corners().items():
                with self.subTest(state=label, corner=corner):
                    b = bubble(**state)
                    _x1, y1, _x2, _y2 = placed(b, px, py)
                    chip_top = y1 + b._h - ui.PAD - ui.CHIP_H
                    chip_bottom = y1 + b._h - ui.PAD
                    self.assertGreaterEqual(chip_top, top)
                    self.assertLessEqual(chip_bottom, bottom, "the chips are off screen")

    def test_a_reply_taller_than_the_desktop_no_longer_sizes_the_window_past_it(self):
        b = bubble(_reply=draft(12_000))
        b._render()
        self.assertLessEqual(b._h, WORK[3] - WORK[1] - 2 * ui.EDGE_AIR)

    def test_a_reply_that_fits_is_untouched(self):
        # The other direction, so the bound cannot pass this by firing for everything: a
        # short answer still sizes the window to itself, nowhere near the desktop.
        b = bubble(_reply=draft(200))
        b._render()
        self.assertLess(b._h, WORK[3] - WORK[1] - 2 * ui.EDGE_AIR)

    def test_the_air_is_one_number_and_both_places_use_it(self):
        # `EDGE_AIR` is what makes the clamp a proof rather than a best effort — the height
        # is fitted to `work - 2 * air` and the position is clamped by `air`, and the two
        # have to be the same number. A literal in either place is how they drift apart.
        _left, top, _right, bottom = WORK
        b = bubble(_reply=draft(12_000))
        x1, y1, _x2, y2 = placed(b, *corners()["bottom-right"])
        self.assertEqual(y1, top + ui.EDGE_AIR)
        self.assertEqual(y2, bottom - ui.EDGE_AIR)


if __name__ == "__main__":
    unittest.main()
