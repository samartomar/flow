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


def drawn_reply(b) -> str:
    """What actually reached the canvas as the answer, ignoring probes and furniture."""
    hits = [i["text"] for i in b.canvas.items if i["text"] and i["text"] in b._reply]
    return hits[-1] if hits else ""


def more_line(b) -> str:
    return next((i["text"] for i in b.canvas.items
                 if i["text"].startswith("…") and "more lines" in i["text"]), "")


class TestTheAnswerShowsItsHead(unittest.TestCase):
    """P10, shape (b). An artifact is read from the top, so the window holds the top.

    Item 42 fitted the window to the desktop, which made the chips reachable and left a
    12 000-character answer clipped by the window edge with **no sign anything was missing**
    — the same silence the draft had before item 37 gave it `… N earlier lines`. The reply
    gets the same treatment pointing the other way.
    """

    def test_a_long_reply_shows_its_first_lines(self):
        reply = draft(12_000)
        b = bubble(_reply=reply)
        b._render()
        shown = drawn_reply(b)
        self.assertTrue(reply.startswith(shown), "the reply was windowed from the wrong end")
        self.assertLess(len(shown), len(reply))

    def test_it_is_not_the_tail(self):
        # Both directions, so a window cannot pass this by being a window: the last words
        # of a 12k answer must *not* be what is drawn.
        reply = draft(12_000)[:-20] + "the very last words"
        b = bubble(_reply=reply)
        b._render()
        self.assertNotIn("the very last words", drawn_reply(b))

    def test_no_word_is_cut_in_half(self):
        b = bubble(_reply=draft(12_000))
        b._render()
        shown = drawn_reply(b)
        self.assertTrue(b._reply[len(shown)].isspace(),
                        "the window closed mid-word")

    def test_a_reply_that_fits_is_drawn_whole_and_says_nothing(self):
        # Item 37's guard, kept: nothing changes for the answers people actually get.
        reply = draft(200)
        b = bubble(_reply=reply)
        b._render()
        self.assertEqual(drawn_reply(b), reply)
        self.assertEqual(more_line(b), "")

    def test_the_count_is_measured_and_exact(self):
        # The draft's `… N earlier lines` is an *estimate* from a characters-per-line
        # average, because laying the head out to count it exactly is the cost item 37
        # exists to avoid — on every partial. A reply is laid out once, and it already
        # carries a full-text probe, so here N can be the truth and is: total lines minus
        # shown lines, both off the canvas.
        b = bubble(_reply=draft(12_000))
        b._render()
        line = more_line(b)
        self.assertRegex(line, r"^… \d+ more lines$")
        # Read what was drawn *before* adding probes of our own: the probes are
        # `create_text` calls too, and one carrying the whole reply would be picked up as
        # the drawn body by anything looking for the last match.
        shown_text = drawn_reply(b)
        full = b.canvas.create_text(
            ui.PAD, ui.PAD, anchor="nw", text=b._reply, font=("Segoe UI", 10),
            width=ui.BUBBLE_W - 2 * ui.PAD,
        )
        one = b.canvas.create_text(
            ui.PAD, ui.PAD, anchor="nw", text="M", font=("Segoe UI", 10),
            width=ui.BUBBLE_W - 2 * ui.PAD,
        )
        shown = b.canvas.create_text(
            ui.PAD, ui.PAD, anchor="nw", text=shown_text, font=("Segoe UI", 10),
            width=ui.BUBBLE_W - 2 * ui.PAD,
        )
        h = lambda i: b.canvas.bbox(i)[3] - b.canvas.bbox(i)[1]  # noqa: E731
        expected = round(h(full) / h(one)) - round(h(shown) / h(one))
        self.assertEqual(int(line.split()[1]), expected)

    def test_the_count_grows_with_the_answer(self):
        counts = []
        for n in (6_000, 12_000):
            b = bubble(_reply=draft(n))
            b._render()
            counts.append(int(more_line(b).split()[1]))
        self.assertLess(counts[0], counts[1])

    def test_the_reply_still_sizes_the_bubble(self):
        short = bubble(_reply=draft(200))
        short._render()
        long_ = bubble(_reply=draft(4_000))
        long_._render()
        self.assertGreater(long_._h, short._h)

    def test_the_window_is_inside_the_work_area_at_every_corner(self):
        # Item 42's guarantee, re-asserted: a second windowing rule is a second way to get
        # the height wrong.
        left, top, right, bottom = WORK
        for corner, (px, py) in corners().items():
            with self.subTest(corner=corner):
                x1, y1, x2, y2 = placed(bubble(_reply=draft(12_000)), px, py)
                self.assertGreaterEqual(y1, top)
                self.assertLessEqual(y2, bottom)
                self.assertGreaterEqual(x1, left)
                self.assertLessEqual(x2, right)


class TestHeadForRepliesAndTailForDrafts(unittest.TestCase):
    """The asymmetry is deliberate, and it is stated here so nobody unifies it later.

    They point opposite ways for different reasons. A draft grows at the end and the newest
    words are the ones being worked on, so its window follows the **tail**. An artifact is
    read from its first line and that is where triage happens, so its window holds the
    **head**. `body_window` and `head_window` are separate functions rather than one
    function with a direction flag, because a flag is a thing somebody flips.
    """

    def test_the_draft_still_windows_its_tail(self):
        b = bubble(draft(50_000))
        b._text = b._text[:-20] + "the last words here"
        b._render()
        self.assertTrue(drawn_body(b).endswith("the last words here"))

    def test_the_reply_windows_its_head(self):
        reply = "the first words here" + draft(12_000)[20:]
        b = bubble(_reply=reply)
        b._render()
        self.assertTrue(drawn_reply(b).startswith("the first words here"))

    def test_the_two_lines_say_opposite_things(self):
        # `… N earlier lines` above a draft, `… N more lines` below an answer. The wording
        # is the only thing telling a reader which way the window points.
        d = bubble(draft(50_000))
        d._render()
        r = bubble(_reply=draft(12_000))
        r._render()
        earlier = next((i["text"] for i in d.canvas.items
                        if i["text"].startswith("…")), "")
        self.assertIn("earlier lines", earlier)
        self.assertIn("more lines", more_line(r))

    def test_the_functions_are_separate(self):
        # Not a style point: one function with a direction argument is one call site away
        # from a draft that windows its head, which is the defect item 37 fixed.
        self.assertNotEqual(ui.head_window(draft(500), 100),
                            ui.body_window(draft(500), 100)[0])
        self.assertTrue(draft(500).startswith(ui.head_window(draft(500), 100)))
        self.assertTrue(draft(500).endswith(ui.body_window(draft(500), 100)[0]))


class TestTheExitsCarryTheWholeAnswer(unittest.TestCase):
    """A head window that also truncated Copy would be this item causing the loss it signals.

    `Use this` goes through `session.take_reply()`, which reads `session.reply`. Neither it
    nor the clipboard path has ever read the bubble's rendered string, and neither may start.
    """

    def test_take_reply_reads_the_session_not_the_drawn_window(self):
        from flow.session import Session

        class FakeAsr:
            def load(self, final=None) -> None: ...

            def text(self, a, *, final=False, hotwords="") -> str:
                return ""

        class FakeMic:
            level_db = -60.0

            def start(self) -> None: ...

            def stop(self) -> None: ...

            @property
            def active(self) -> bool:
                return True

            def restart(self) -> None: ...

            def drain(self) -> list:
                return []

        whole = draft(12_000)
        s = Session(asr=FakeAsr(), mic=FakeMic())
        s.reply = whole
        self.assertTrue(s.take_reply())
        self.assertEqual(s.draft.text, whole, "the exit carried a window, not the answer")

    def test_the_bubble_draws_less_than_the_session_holds(self):
        # The two halves of the same sentence, side by side: the card shows a window and
        # the answer behind it is whole.
        b = bubble(_reply=draft(12_000))
        b._render()
        self.assertLess(len(drawn_reply(b)), len(b._reply))
        self.assertEqual(len(b._reply), 12_000)


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
        #
        # Asserted against `reposition` directly rather than through a state that happens to
        # fill the desktop: item 45 gave the reply a head window, so nothing renders to
        # exactly `work_h` any more and a check that relied on one would have been pinning a
        # coincidence.
        _left, top, _right, bottom = WORK
        b = bubble()
        b._h = bottom - top  # taller than the fit allows, which is what a clamp is for
        box: list[str] = []
        b.geometry = box.append
        b.pill.x, b.pill.y = corners()["bottom-right"]
        ui.Bubble.reposition(b)
        self.assertEqual(box[-1].partition("+")[2], f"{892}+{top + ui.EDGE_AIR}")
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
#: **The reply rows were re-captured for item 45 and the change is a height, not a
#: placement.** The head window sizes a long answer to 643 px where the full-text probe
#: sized it to 656, so every `380x656…` here became `380x643…` with the offsets untouched.
#: Recorded rather than silently re-baselined: a regression table that is quietly rewritten
#: whenever it fails is a table that pins nothing. The draft rows — which are what item 44's
#: fallback is actually about — are byte-identical to the day they were captured.
GEOMETRY_BEFORE = {
    ("1k draft", "bottom-left"): "380x414+8+208",
    ("1k draft", "bottom-right"): "380x414+892+208",
    ("1k draft", "mid-left"): "380x414+8+8",
    ("50k draft", "bottom-left"): "380x414+8+208",
    ("50k draft", "bottom-right"): "380x414+892+208",
    ("50k draft", "mid-left"): "380x414+8+8",
    ("4k reply", "top-left"): "380x643+8+8",
    ("4k reply", "top-middle"): "380x643+336+8",
    ("4k reply", "top-right"): "380x643+892+8",
    ("4k reply", "bottom-left"): "380x643+8+8",
    ("4k reply", "bottom-right"): "380x643+892+8",
    ("4k reply", "mid-left"): "380x643+8+8",
    ("12k artifact reply", "top-left"): "380x643+8+8",
    ("12k artifact reply", "top-middle"): "380x643+336+8",
    ("12k artifact reply", "top-right"): "380x643+892+8",
    ("12k artifact reply", "bottom-left"): "380x643+8+8",
    ("12k artifact reply", "bottom-right"): "380x643+892+8",
    ("12k artifact reply", "mid-left"): "380x643+8+8",
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

    def states(self):
        return [
            ("1k draft", {"_text": draft(1_000)}),
            ("50k draft", {"_text": draft(50_000)}),
            ("4k reply", {"_reply": draft(4_000)}),
            ("12k artifact reply", {"_reply": draft(12_000)}),
        ]

    def test_a_pill_along_the_top_opens_the_bubble_below_it(self):
        # The defect, stated as geometry: the bubble's top must not be above the pill's
        # bottom. Red at all three positions before this item, where it sat at y=8 with the
        # pill occupying y=0..40.
        _left, top, _right, _bottom = WORK
        for label, state in self.states()[:2]:  # the draft sizes; a reply cannot fit below
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
        # A full reply is as tall as the desktop, so there is no room on either side. This
        # is the case the fallback deliberately does not fix, and it is pinned so nobody
        # reads its absence as an oversight.
        _left, top, _right, _bottom = WORK
        for name, (px, py) in along_the_top().items():
            with self.subTest(at=name):
                _x1, y1, _x2, _y2 = placed(bubble(_reply=draft(12_000)), px, py)
                self.assertEqual(y1, top + ui.EDGE_AIR)

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
