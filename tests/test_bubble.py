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
    #: A real int, not the auto-created Mock the attribute would otherwise be —
    #: `reposition` does arithmetic on it now that the pill's width can dock.
    b.pill.pill_w = ui.PILL_W
    b.pill.work = WORK
    b.pill.session = mock.Mock(
        mode="dictate", editing=False, can_rescue=False, can_take_reply=False,
        auto_ask_in=None,
    )
    b.canvas = MeasuringCanvas()
    b._text, b._sent, b._partial, b._note = text, "", "", ""
    b._editor = None
    b._act = None
    b._h = 120
    #: Real bools, not whatever `tk.Misc.__getattr__` would answer for a missing
    #: attribute: `_frozen` is `_pointer_in and _visible`, and a test that wants to
    #: freeze this window has to be able to.
    b._visible, b._pointer_in = True, False
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
        #
        # 400 characters until the panel became a fixed shape (`PANEL_H`). "Fits" is a
        # smaller number now — the window no longer grows to whatever the draft asks for,
        # so what fits is what fits in 184 px, and more drafts window. The window still
        # says so, which is what the class next door asserts.
        #
        # 40 rather than the ~200 the same panel holds on a real desktop: this fixture
        # has no Plex face installed, Tk substitutes, and the substitute measures several
        # times taller per line. The number is the fixture's, not the product's — the
        # shots in `scripts/shots.py` show three full lines in the same 184 px.
        b = bubble(draft(40))
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

    def test_the_body_cannot_outgrow_a_window_frozen_under_the_hand(self):
        # Reported from a real session, with a picture: the draft drawn straight
        # through the note and the chip row. `_frozen` holds the geometry while the
        # pointer is inside — right, so nothing moves under a hand reaching for a
        # chip — and nothing held the *content*, so a body measured for `BODY_MAX_H`
        # went into whatever height the window had when the hand arrived. Measured on
        # the real canvas: entered at 182 px, the body reached 355.
        b = bubble(draft(300))
        b._render()
        entered_at = b._h
        b._pointer_in = True
        b._text = draft(30_000)
        b._render()
        self.assertEqual(b._h, entered_at, "the window resized under the hand")
        self.assertLessEqual(
            b.canvas.band(b._text[-40:])[1], b._h - ui.PAD - ui.CHIP_H,
            f"the body runs past the chip row of a {b._h} px window")

    def test_and_there_is_no_room_to_take_back_any_more(self):
        """This asserted the window grew once the hand left. It cannot: `PANEL_H`.

        The freeze was built to stop the window resizing under a hand reaching for a
        chip, and a fixed shape makes that unreachable rather than guarded — the stronger
        version of the same guarantee. What still catches up is the *content*, which is
        what the caller actually wanted to see.
        """
        b = bubble(draft(300))
        b._render()
        b._pointer_in = True
        b._text = draft(30_000)
        b._render()
        frozen_h, frozen_body = b._h, drawn_body(b)
        b._pointer_in = False
        b._render()
        self.assertEqual(b._h, frozen_h)
        # The body does not move either, and that is not a weaker check than it looks:
        # the draft is windowed to its *tail*, so a 300-character draft and a 30 000-
        # character one lay out the same last lines. Freezing had one observable effect
        # and it was the height.
        self.assertEqual(drawn_body(b), frozen_body)

    def test_five_chips_at_once_stay_inside_the_bubble(self):
        # Draft held, `can_rescue` true, dictate mode: Refine, Continue, Edit, Was a
        # command and Send all on screen together. Measured on the real canvas before
        # the fix at 377 px of chip width against a 366 px budget (`BUBBLE_W` less
        # `PAD`), which put Send's box at x=392 — 12 px past the window's right edge,
        # roughly half the label clipped.
        b = bubble(draft(400))
        b.pill.session.can_rescue = True
        b._render()
        sends = [i for i in b.canvas.items if i["text"] == "Send"]
        self.assertTrue(sends, "the Send chip was not drawn")
        right_edge = sends[0]["x"] + ui.chip_w("Send", "Send") / 2
        self.assertLessEqual(
            right_edge, ui.BUBBLE_W,
            f"Send's right edge sits at {right_edge}, past BUBBLE_W ({ui.BUBBLE_W})",
        )


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
        # See the sibling test for why 40 and not 400: a substituted font measures taller.
        b = bubble(draft(40))
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


#: `drawn_reply`, `more_line`, and the three classes that used them — the head window, the
#: head/tail asymmetry's reply half, and the exits carrying the whole answer — moved to
#: `tests/test_card.py` on 2026-08-03 with the code they were about. P10 is not weakened
#: by that: it is asserted on the window that now draws an answer. What stays here is the
#: draft half of the asymmetry, because a draft still windows its tail and that is the
#: statement the two functions exist to keep apart.


class TestTheDraftStillWindowsItsTail(unittest.TestCase):
    """The half of the asymmetry this window still owns.

    `body_window` and `head_window` are separate functions rather than one function with
    a direction flag, because a flag is a thing somebody flips — and the two now live on
    two different windows, which is the strongest version of that argument yet.
    """

    def test_the_draft_windows_its_tail(self):
        b = bubble(draft(50_000))
        b._text = b._text[:-20] + "the last words here"
        b._render()
        self.assertTrue(drawn_body(b).endswith("the last words here"))

    def test_what_is_above_it_is_said(self):
        b = bubble(draft(50_000))
        b._render()
        earlier = next((i["text"] for i in b.canvas.items
                        if i["text"].startswith("…")), "")
        self.assertIn("earlier lines", earlier)

    def test_the_functions_are_separate(self):
        self.assertNotEqual(ui.head_window(draft(500), 100),
                            ui.body_window(draft(500), 100)[0])
        self.assertTrue(draft(500).startswith(ui.head_window(draft(500), 100)))
        self.assertTrue(draft(500).endswith(ui.body_window(draft(500), 100)[0]))

    def test_this_window_has_no_way_to_show_an_answer_at_all(self):
        # The deletion, asserted. A `show_reply` that came back would be the two surfaces
        # becoming one again, and it would come back looking like a convenience.
        self.assertFalse(hasattr(ui.Bubble, "show_reply"))
        self.assertFalse(hasattr(ui.Bubble, "_reply_slot"))
        self.assertFalse(hasattr(ui.Bubble, "_take_reply"))


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


def geometry_of(b, x: int, y: int) -> str:
    """Render with the pill at (x, y) and return the geometry string itself.

    The real `reposition` rather than the fixture's stub, and the string it built rather
    than a recomputation of it: a check that re-derives the formula it is checking passes
    whatever the formula says.
    """
    b.pill.x, b.pill.y = x, y
    b.reposition = ui.Bubble.reposition.__get__(b)
    box: list[str] = []
    b.geometry = box.append
    b._render()
    return box[-1]


def placed(b, x: int, y: int) -> tuple[int, int, int, int]:
    """The window rect `reposition` computes, as (x1, y1, x2, y2)."""
    size, _, offset = geometry_of(b, x, y).partition("+")
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

    #: The reply states left this table on 2026-08-03 with `show_reply`. They were the
    #: only ones that ever sized this window past the desktop -- a draft is capped at
    #: `BODY_MAX_H` -- so what is left is the two item 37 already bounded. The tall-window
    #: guarantees they were pinning are asserted on `ConversationCard` now, which is the
    #: window that can be that tall.
    def states(self):
        return [
            ("1k draft", {"_text": draft(1_000)}),
            ("50k draft", {"_text": draft(50_000)}),
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

    def test_the_longest_draft_still_does_not_size_the_window_past_the_desktop(self):
        b = bubble(draft(50_000))
        b._render()
        self.assertLessEqual(b._h, WORK[3] - WORK[1] - 2 * ui.EDGE_AIR)

    def test_and_a_short_one_still_sizes_the_window_to_itself(self):
        # The other direction, so the bound cannot pass this by firing for everything.
        b = bubble(draft(200))
        b._render()
        self.assertLess(b._h, WORK[3] - WORK[1] - 2 * ui.EDGE_AIR)

    def test_the_air_is_one_number_and_both_places_use_it(self):
        # `EDGE_AIR` is what makes the clamp a proof rather than a best effort — the height
        # is fitted to `work - 2 * air` and the position is clamped by `air`, and the two
        # have to be the same number. A literal in either place is how they drift apart.
        #
        # Asserted against `reposition` directly rather than through a state that happens to
        # fill the desktop: item 45 gave the reply a head window, so nothing renders to
        # exactly `work_h` any more and a check that relied on one would have been pinning a
        # coincidence.
        _left, top, right, bottom = WORK
        b = bubble()
        b._h = bottom - top  # taller than the fit allows, which is what a clamp is for
        box: list[str] = []
        b.geometry = box.append
        b.pill.x, b.pill.y = corners()["bottom-right"]
        ui.Bubble.reposition(b)
        self.assertEqual(box[-1].partition("+")[2],
                         f"{right - ui.BUBBLE_W - ui.EDGE_AIR}+{top + ui.EDGE_AIR}")
        b._h = bottom - top - 2 * ui.EDGE_AIR  # exactly the fit
        ui.Bubble.reposition(b)
        _size, _, offset = box[-1].partition("+")
        self.assertEqual(int(offset.partition("+")[2]) + b._h, bottom - ui.EDGE_AIR)


#: Three x positions along the top edge of the work area — the pill dragged where there is
#: no "above" left. Left, middle and right, because the anchor is horizontal as well as
#: vertical and a fallback that only worked in one corner would pass a single-point check.
def along_the_top() -> dict[str, tuple[int, int]]:
    left, top, right, _bottom = WORK
    return {
        "top-left": (left, top),
        "top-middle": ((left + right - ui.PILL_W) // 2, top),
        "top-right": (right - ui.PILL_W, top),
    }


#: Every geometry string `reposition` produced **before** item 44, captured by running the
#: harness against the tree as it stood. This is the regression half and it is a table rather
#: than a formula on purpose: a check that recomputes what it is checking cannot fail.
#:
#: The rows absent from it are the ones the fallback is *for* — a draft-sized window with the
#: pill along the top, where "above" has no room. Everything else must come through byte for
#: byte, including the reply-sized windows at the top, which are taller than either side of
#: the pill and so keep today's clamp.
#:
#: **The reply rows are gone, and that is the second time they moved rather than the first
#: time they were rewritten.** Item 45 re-captured them at 643 px where the full-text probe
#: had sized them 656; item 63 removed the path, because this window no longer draws an
#: answer. The draft rows below are byte-identical to the day they were captured, which is
#: the whole point of a table: one that gets quietly re-baselined pins nothing.
#: Re-baselined 2026-08-09 for the IBM Plex Sans migration: `FONT_BODY` reports an
#: 18 px line to the real canvas against Segoe UI's 17, so the same capped draft lays
#: out one pixel taller (414 → 415) and the bottom-anchored placements ride up one
#: pixel to match (208 → 207, the same bottom edge). Traced to the font swap, not a
#: silent re-pin.
#:
#: Re-baselined again the same day for docking (Phase 5): the pill and this window
#: meet at one hairline seam now, not the 10 px of air a shadow used to go in, so
#: every placement that resolved to "above" moves ten pixels closer to the pill —
#: 207 → 217 here. "mid-left" is unaffected because that placement was already
#: resolving to a *different* branch of `reposition`'s clamp, one the gap never
#: reached.
#:
#: Re-baselined a third time the same day: `BUBBLE_W` moved to 420 (Phase 6, the
#: two panels unified at the draft's own widest state). Width and the right-anchored
#: x shift with it everywhere (380→420, 892→852). The 1 000-character draft's height
#: drops too (415→398) — wider text wraps to fewer lines for the same character
#: count — while the 50 000-character one holds at 415, because that row is capped
#: by `BODY_MAX_H` rather than by how the text wraps, and a cap does not move with
#: the column it bounds.
#: Re-recorded when the panel became a fixed shape (`ui.PANEL_H`), and the new table says
#: the change out loud better than any prose could: **every row is the same 420x184**, at
#: three placements and across a draft that differs by fifty times its length. It used to
#: read 398 for a 1k draft and 415 for a 50k one — a window that changed size with the
#: text in it, which is the motion this table now proves is gone.
#:
#: Still a golden table and still doing its original job: any *further* change to
#: placement has to justify itself against these numbers.
GEOMETRY_BEFORE = {
    ("1k draft", "bottom-left"): "420x184+8+448",
    ("1k draft", "bottom-right"): "420x184+852+448",
    ("1k draft", "mid-left"): "420x184+8+152",
    ("50k draft", "bottom-left"): "420x184+8+448",
    ("50k draft", "bottom-right"): "420x184+852+448",
    ("50k draft", "mid-left"): "420x184+8+152",
}


class TestTheBubbleOpensBelowWhenAboveHasNoRoom(unittest.TestCase):
    """A fallback, not a mode — tooltip behaviour, and item 42's desk check found the need.

    With the pill dragged to the top of the work area there is no "above" left, so the
    bubble clamped to the top edge and was drawn **over the pill it is anchored to**.
    Nothing clipped and nothing was unreachable — item 42 guarantees that and this must not
    take it away — but an anchor pointing at something it covers is not an anchor.

    Above is tried first and used whenever it fits. Below is used only when above does not
    fit *and* below does. When **neither** fits — a window as tall as the desktop, which is
    what a full reply is — the arithmetic is today's exactly and the bubble clamps to the top
    over the pill. That case is not fixed here, deliberately: no anchor can place a window
    taller than the space either side of it, and pretending otherwise would be a third rule.
    """

    #: The reply states left this table on 2026-08-03 with `show_reply`. They were the
    #: only ones that ever sized this window past the desktop -- a draft is capped at
    #: `BODY_MAX_H` -- so what is left is the two item 37 already bounded. The tall-window
    #: guarantees they were pinning are asserted on `ConversationCard` now, which is the
    #: window that can be that tall.
    def states(self):
        return [
            ("1k draft", {"_text": draft(1_000)}),
            ("50k draft", {"_text": draft(50_000)}),
        ]

    def test_a_pill_along_the_top_opens_the_bubble_below_it(self):
        # The defect, stated as geometry: the bubble's top must not be above the pill's
        # bottom. Red at all three positions before this item, where it sat at y=8 with the
        # pill occupying y=0..40.
        _left, top, _right, _bottom = WORK
        for label, state in self.states():
            for name, (px, py) in along_the_top().items():
                with self.subTest(state=label, at=name):
                    _x1, y1, _x2, _y2 = placed(bubble(**state), px, py)
                    self.assertGreaterEqual(
                        y1, py + ui.PILL_H,
                        "the bubble is drawn over the pill it is anchored to",
                    )

    def test_every_other_placement_is_byte_identical(self):
        for (label, name), before in GEOMETRY_BEFORE.items():
            state = dict(self.states())[label]
            places = dict(along_the_top())
            places.update(corners())
            places["mid-left"] = (WORK[0], (WORK[1] + WORK[3]) // 2)
            with self.subTest(state=label, at=name):
                self.assertEqual(geometry_of(bubble(**state), *places[name]), before)

    def test_above_is_still_the_default_wherever_it_fits(self):
        # The other direction. A pill in its usual place has room above it, and the bubble
        # must still be there — a fallback that fired whenever it could would be a mode.
        b = bubble(_text=draft(1_000))
        _x1, y1, _x2, y2 = placed(b, *corners()["bottom-right"])
        self.assertLessEqual(y2, WORK[3] - ui.PILL_H,
                             "the bubble should sit above the pill, not below it")

    def test_when_neither_side_fits_the_clamp_is_todays(self):
        # A window as tall as the desktop has no room on either side of a pill. This is
        # the case the fallback deliberately does not fix, and it is pinned so nobody
        # reads its absence as an oversight. Driven against `reposition` directly now:
        # the state that used to produce a desktop-tall bubble was a full reply, and this
        # window has not drawn one since item 63. The card is where that height lives.
        _left, top, _right, bottom = WORK
        for name, (px, py) in along_the_top().items():
            with self.subTest(at=name):
                b = bubble(draft(1_000))
                b._h = bottom - top - 2 * ui.EDGE_AIR
                b.pill.x, b.pill.y = px, py
                box: list[str] = []
                b.geometry = box.append
                ui.Bubble.reposition(b)
                self.assertEqual(int(box[-1].rpartition("+")[2]), top + ui.EDGE_AIR)

    def test_the_work_area_guarantee_survives_the_second_anchor(self):
        # Item 42's property, re-asserted against the new placements: a second way to
        # choose y is a second way to leave the desktop.
        left, top, right, bottom = WORK
        for label, state in self.states():
            for name, (px, py) in along_the_top().items():
                with self.subTest(state=label, at=name):
                    x1, y1, x2, y2 = placed(bubble(**state), px, py)
                    self.assertGreaterEqual(y1, top)
                    self.assertLessEqual(y2, bottom)
                    self.assertGreaterEqual(x1, left)
                    self.assertLessEqual(x2, right)


if __name__ == "__main__":
    unittest.main()


class TestTheChipsSurviveARedraw(unittest.TestCase):
    """Item 66: a chip being aimed at must still be there when the click lands.

    `_render` used to delete the whole canvas — every chip and its binding — and
    reposition the window, on every partial decode, every countdown second and every
    activity frame. Three outside users reported chips that "genuinely failed clicks",
    and the click storm on real Tk put a number on it: **10 of 60** landed in a live
    session, where a partial, a note and the rescue chip all move without the user doing
    anything. 60 of 60 after.

    What is asserted here is the mechanism the storm measured, so the storm does not
    have to be run to notice a regression: the row is not rebuilt by a body redraw, the
    geometry does not change under the pointer, and a countdown does not resize its own
    chip.
    """

    def chips(self, b) -> list[int]:
        """The identity of every chip item on the canvas. Identity, because the question
        is whether they were *rebuilt* rather than whether they look the same."""
        return [id(i) for i in b.canvas.items if "chips" in i["tags"]]

    def test_a_body_redraw_leaves_the_row_standing(self):
        b = bubble(draft(400))
        b._render()
        was = self.chips(b)
        self.assertTrue(was, "no chips were drawn at all")
        for i in range(5):
            b._partial = draft(200 + i * 37)
            b._render()
        self.assertEqual(self.chips(b), was, "the chip row was rebuilt by a partial")

    def test_but_a_changed_row_is_rebuilt(self):
        # The other direction, so persistence cannot pass this by being a freeze: a chip
        # that should appear has to appear.
        b = bubble(draft(400))
        b._render()
        was = self.chips(b)
        b.pill.session.can_rescue = True
        b._render()
        self.assertNotEqual(self.chips(b), was)
        self.assertIn("Was a command", [i["text"] for i in b.canvas.items])

    def test_nothing_moves_or_resizes_under_the_pointer(self):
        # `_visible`, because a window nobody can see is a window nobody is pointing at
        # — the freeze is about a hand that has arrived, not about a hidden card.
        b = bubble(draft(400), _visible=True)
        b._render()
        h, placed_at = b._h, []
        b.reposition = lambda *a, **kw: placed_at.append(1)
        b._enter()
        for n in (4_000, 50_000):
            b._text = draft(n)
            b._note = "microphone overflowed - some audio was dropped"
            b._render()
            self.assertEqual(b._h, h, "the window resized under the hand")
        self.assertEqual(placed_at, [], "the window moved under the hand")

    def test_and_the_row_is_not_rebuilt_under_it_either(self):
        # A persistent row that still moves 118 px when `Was a command` appears is the
        # same lost click with a different cause — the storm read 30/60 with only the
        # geometry frozen.
        b = bubble(draft(400), _visible=True)
        b._render()
        was = self.chips(b)
        b._enter()
        b.pill.session.can_rescue = True
        b._render()
        self.assertEqual(self.chips(b), was)

    def test_leaving_catches_everything_up(self):
        # Otherwise the window keeps whatever it had when the pointer arrived until the
        # next event, which on a settled draft is never.
        b = bubble(draft(400), _visible=True)
        b._render()
        b._enter()
        # A note rather than a longer draft: the body is capped at `BODY_MAX_H`, so a
        # 400-character draft and a 50 000-character one measure the same window and a
        # check built on that would pass while proving nothing.
        b._note = "microphone overflowed - some audio was dropped, twice over now"
        b._render()
        frozen = b._h
        b._leave()
        # The window is a fixed shape now (`PANEL_H`), so "caught up" cannot mean "is a
        # different size" any more. What it means is that the note held back while the
        # hand was here is on the canvas once it has gone — which is the thing anybody
        # cared about, and was only ever inferred from the height.
        self.assertEqual(b._h, frozen)
        self.assertTrue(any("microphone overflowed" in i["text"]
                            for i in b.canvas.items if "text" in i),
                        "the note never caught up")

    def test_a_countdown_does_not_resize_its_own_chip(self):
        # Chip width followed the label, so `Ask` -> `Ask 4s` -> `Ask` moved the hit
        # region every second the countdown ran.
        widths = {ui.chip_w("Ask", label) for label in ("Ask", "Ask 1s", "Ask 10s")}
        self.assertEqual(len(widths), 1)
        self.assertEqual(ui.chip_w("Bring it back", "Bring it back"),
                         ui.chip_w("Bring it back", "Bring it back 4s"))

    def test_an_ordinary_chip_is_still_sized_by_its_label(self):
        # The reserve is per key, not a flat minimum: a row of chips all as wide as the
        # widest countdown would be a row nobody can tell apart.
        self.assertLess(ui.chip_w("Edit", "Edit"), ui.chip_w("Was a command",
                                                             "Was a command"))

    def test_the_gap_shrinks_only_far_enough_to_fit(self):
        # The five-chip row that motivated this function — Refine, Continue, Edit,
        # Was a command, Send, 345 px of chip width against the 366 px budget
        # `BUBBLE_W` used to leave — fits inside `BUBBLE_W`'s 420 with 57 px of slack
        # now (`test_five_chips_at_once_stay_inside_the_bubble` pins that directly), so
        # it no longer demonstrates a shrinking gap. A synthetic row wide enough to
        # outrun *any* reasonable window is what is left to prove the function still
        # shrinks rather than clips — "the row nobody has measured yet".
        widths = [ui.chip_w(k, l) for k, l in (
            ("Refine", "Refine"), ("Continue", "Continue"),
            ("Was a command", "Was a command"), ("Edit", "Edit"),
            ("Send", "Send"), ("Done", "Done"),
        )]
        gap = ui.chip_row_gap(widths, ui.BUBBLE_W - ui.PAD)
        self.assertLess(gap, ui.CHIP_GAP, "an overflowing row kept the ordinary gap")
        row_w = sum(widths) + gap * (len(widths) - 1)
        self.assertLessEqual(row_w, ui.BUBBLE_W - ui.PAD - ui.CHIP_ROW_RESERVE)

    def test_a_row_with_room_keeps_the_ordinary_gap(self):
        # Nothing about a row that already fits should change — three chips, as in
        # dictate mode with no rescue on offer, has plenty of the 366 px budget spare.
        widths = [ui.chip_w(k, l) for k, l in (
            ("Refine", "Refine"), ("Continue", "Continue"), ("Send", "Send"),
        )]
        self.assertEqual(ui.chip_row_gap(widths, ui.BUBBLE_W - ui.PAD), ui.CHIP_GAP)

    def test_the_row_is_drawn_above_the_body_it_outlived(self):
        # A canvas draws in creation order, so a row created before this render's body
        # sits underneath it and the body takes its clicks. The click storm read 0/60
        # with the persistence in and this line out.
        import inspect

        self.assertIn('tag_raise("chips")', inspect.getsource(ui.Bubble._render))
        self.assertIn('tag_raise("chips")',
                      inspect.getsource(ui.ConversationCard._render))
