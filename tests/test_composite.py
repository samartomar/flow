"""The shipped surface, composited: one bitmap for a window full of canvases.

decisions.md 2026-09-04 said this surface *could not* be composited, and named the
one thing that would reopen it — the hand editor leaving the window. It left, so
this is the rest: `paint.TeeCanvas` over the row, `paint.recorder` over the two
panel `Frame`s, one `GdiCanvas` sized to the whole window, and a present at the end
of `_frame`.

What is pinned here is everything about that which is not a picture. **The picture
is settled by `scripts/shots.py` and a look at the PNGs**, exactly as every other
drawing test in this suite leaves it: an assertion that a curve is smooth is not an
assertion a headless test can make.

So: the wiring (which canvas each window gets, in which mode), the arithmetic
(where the bitmap is sized, where the row is replayed, where the editor's window is
placed), and the two rules that decide whether a frame costs anything at all — the
row's own `_draw_key` skip, and the dirty flag the panels raise on their own
schedule.

**Lite and a Mac get the canvas itself**, and that is asserted rather than assumed:
`painter_for`'s rule is what keeps `tests/test_lite.py` and every fixture in this
suite running the code they ran before.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import flow.ui as ui  # noqa: E402
from flow import paint  # noqa: E402
from flow.session import DICTATE  # noqa: E402


class FakeGdi:
    """A `GdiCanvas` that keeps a list instead of a bitmap.

    Everything `TeeCanvas` asks of a painter, and nothing else — so the replay
    order, the offsets and the present can be asserted on a machine with no GDI+
    and without putting anything on the screen.
    """

    antialiased = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.presents: list = []
        self.sizes: list = []
        self.closed = 0
        self.constant_alpha = 240
        #: The translation in force, so a replayed call records where it landed.
        self.at = (0, 0)
        self._stack: list = []

    def __getattr__(self, name):
        def call(*a, **kw):
            self.calls.append((name, self.at, a, kw))
        return call

    def offset(self, dx, dy):
        self._stack.append(self.at)
        self.at = (self.at[0] + dx, self.at[1] + dy)
        return len(self._stack)

    def restore(self, _token) -> None:
        self.at = self._stack.pop()

    def delete(self, *a, **kw) -> None:
        self.calls.append(("delete", self.at, a, kw))

    def resize(self, w, h) -> None:
        self.sizes.append((w, h))

    def close(self) -> None:
        self.closed += 1

    def present(self, win, at=None) -> bool:
        self.presents.append(at)
        return True

    def drawn(self, method: str) -> list:
        return [(c[1], c[2]) for c in self.calls if c[0] == method]


class Recorder:
    """`tests/test_scale.py`'s canvas stand-in: what the real widget was handed."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name):
        def call(*a, **kw):
            self.calls.append((name, a, kw))
            return f"item-{len(self.calls)}"
        return call

    def last(self, name: str) -> tuple:
        for call in reversed(self.calls):
            if call[0] == name:
                return call
        raise AssertionError(f"{name} was never called")


# -- the tee ------------------------------------------------------------------


class TestTheTeeDrawsBothWays(unittest.TestCase):
    """One call, two destinations, in two different units.

    The real canvas keeps every item — which is the whole reason this is a tee and
    not a swap, because the eighteen `tag_bind` sites and the item-based hover
    tooltips hit-test against those items — and the display list keeps the same
    call in the design pixels `GdiCanvas` draws in.
    """

    def setUp(self):
        self.rec = Recorder()
        self.gdi = FakeGdi()
        self.tee = paint.TeeCanvas(paint.ScaledCanvas(self.rec, 3.0), self.gdi)

    def test_the_widget_is_handed_device_pixels(self):
        self.tee.create_line(0, 10, 20, 10, fill="#3ECF8E")
        self.assertEqual(self.rec.last("create_line")[1], (0, 30, 60, 30))

    def test_and_the_display_list_keeps_the_design_ones(self):
        # Replayed into a `GdiCanvas` whose world transform is the same factor, so
        # a display list already in device pixels would be scaled twice.
        self.tee.create_line(0, 10, 20, 10, fill="#3ECF8E")
        self.tee.replay(self.gdi)
        self.assertEqual(self.gdi.drawn("create_line"), [((0, 0), (0, 10, 20, 10))])

    def test_a_delete_by_tag_forgets_only_that_tag(self):
        # `Bubble._render` deletes `body` and leaves the chip row standing, which is
        # what makes a partial repaint possible — and what forces the list to be
        # retained rather than forwarded.
        self.tee.create_text(0, 0, text="draft", tags="body")
        self.tee.create_text(0, 0, text="Send", tags="chips")
        self.tee.delete("body")
        self.tee.replay(self.gdi)
        self.assertEqual([kw.get("text") for _n, _at, _a, kw in self.gdi.calls
                          if _n == "create_text"], ["Send"])

    def test_anything_that_is_not_a_draw_falls_through(self):
        self.tee.tag_bind("chips", "<Button-1>", None)
        self.assertEqual(self.rec.last("tag_bind")[0], "tag_bind")

    def test_the_opacity_is_reachable_without_the_bitmap(self):
        # Where `-alpha` went. Through the tee, because `_apply_idle_dim` holds the
        # tee and a `recorder` has no painter at all to reach past it into.
        self.tee.constant_alpha = 140
        self.assertEqual(self.gdi.constant_alpha, 140)
        self.assertEqual(self.tee.constant_alpha, 140)
        self.assertEqual(paint.recorder(self.rec).constant_alpha, 255)


class TestTheWindowIsCompositedAsOne(unittest.TestCase):
    """The panels are `Frame`s inside the pill's window, so one bitmap carries
    all three display lists — each under its own placement offset."""

    def setUp(self):
        self.gdi = FakeGdi()
        self.row = paint.TeeCanvas(Recorder(), self.gdi)
        self.band = paint.recorder(Recorder())

    def test_the_others_are_replayed_under_their_offsets(self):
        self.band.create_text(0, 0, text="draft")
        self.row.create_text(0, 0, text="OFF")
        self.row.present(object(), at=(10, 20), others=[(self.band, 0, 0)],
                         at_self=(0, 115))
        self.assertEqual(self.gdi.drawn("create_text"),
                         [((0, 0), (0, 0)), ((0, 115), (0, 0))])

    def test_the_band_is_drawn_before_the_row(self):
        # Tk's own stacking: the panel takes the top of the window and the row is
        # its foot, so the row is replayed last and wins any overlap.
        self.band.create_text(0, 0, text="draft")
        self.row.create_text(0, 0, text="OFF")
        self.row.present(object(), at=(0, 0), others=[(self.band, 0, 0)])
        said = [kw.get("text") for n, _at, _a, kw in self.gdi.calls
                if n == "create_text"]
        self.assertEqual(said, ["draft", "OFF"])

    def test_the_bitmap_is_cleared_first_rather_than_painted_over(self):
        self.row.present(object())
        self.assertEqual(self.gdi.calls[0][0], "delete")

    def test_it_is_told_where_the_window_is(self):
        # `winfo_*` lags a `geometry` call by a frame or two, which composites the
        # bitmap somewhere else on the desktop rather than merely late.
        self.row.present(object(), at=(1320, 1842))
        self.assertEqual(self.gdi.presents, [(1320, 1842)])

    def test_a_present_settles_every_list_it_carried(self):
        self.assertTrue(self.row.dirty and self.band.dirty)
        self.row.present(object(), others=[(self.band, 0, 0)])
        self.assertFalse(self.row.dirty)
        self.assertFalse(self.band.dirty, "the band would present again forever")


# -- what the pill does with it -----------------------------------------------


def pill(*, composited=True, band=0, work=(0, 0, 3840, 2016), x=1320, y=1842):
    """A `Pill` with just enough of one to run `_sync_shell` and `_present`.

    `test_scale.shell`'s fixture with a painter on it — same work area, which is
    what `SPI_GETWORKAREA` really answers on the 300 % machine this was written
    against.
    """
    p = ui.Pill.__new__(ui.Pill)
    p.composited = composited
    p.gdi = FakeGdi()
    p.canvas = paint.TeeCanvas(Recorder(), p.gdi) if composited else mock.Mock()
    p.session = mock.Mock(mode=DICTATE)
    p.bubble = mock.Mock(width=ui.BUBBLE_W, _visible=bool(band), _h=band,
                         canvas=paint.recorder(Recorder()))
    p.bubble.__dict__["_visible"] = bool(band)
    p.card = mock.Mock(width=ui.BUBBLE_W, _visible=False, _h=band,
                       canvas=paint.recorder(Recorder()))
    p.card.__dict__["_visible"] = False
    p.work = p.full = work
    p.x, p.y = x, y
    p._docked_w = ui.BUBBLE_W
    p._shell_h = ui.PILL_H + band
    p._hidden = False
    p._alive = True
    p.geometry = mock.Mock()
    p.window_geometry = mock.Mock(return_value=(0, 0, 0))
    return p


class TestTheBitmapIsTheWindow(unittest.TestCase):
    """`UpdateLayeredWindow` is *handed* a size rather than asked for one, so a
    bitmap left at the old shape would be the window's shape — and the `geometry`
    call above it would be undone by the next present."""

    def setUp(self):
        self.addCleanup(ui.apply_scale, 1.0)

    def test_a_band_opening_resizes_it_to_the_whole_window(self):
        p = pill(band=100)
        p._shell_h = ui.PILL_H  # not caught up yet; `_sync_shell` is what moves it
        p._sync_shell()
        self.assertEqual(p.gdi.sizes[-1], (ui.BUBBLE_W, ui.PILL_H + 100))

    def test_in_design_pixels_whatever_the_display_is(self):
        # The painter carries the scale in its own world transform, so handing it
        # device pixels would square the factor — the same rule `place` follows one
        # line up (`test_scale`: "the canvas is still asked in design pixels").
        ui.apply_scale(3.0)
        p = pill(band=100)
        p._shell_h = ui.PILL_H
        p._sync_shell()
        self.assertEqual(p.gdi.sizes[-1], (ui.BUBBLE_W, ui.PILL_H + 100))

    def test_a_frame_that_only_moved_still_resizes(self):
        # Unconditional, because the comparison it sits under is about the position
        # as well: a window dragged between two frames must not skip the call that
        # keeps the bitmap and the shell the same shape.
        p = pill()
        p._sync_shell()
        self.assertEqual(p.gdi.sizes[-1], (ui.BUBBLE_W, ui.PILL_H))

    def test_a_tk_drawn_surface_is_never_asked(self):
        p = pill(composited=False, band=100)
        p._shell_h = ui.PILL_H
        p._sync_shell()
        p.canvas.resize.assert_not_called()


class TestAFrameCostsNothingWhenNothingMoved(unittest.TestCase):
    """The row's `_draw_key` skip and the panels' own repaint schedules are what
    make an idle frame free — measured at 0.03 ms on the 300 % machine against
    6 ms for a frame that actually composites a band."""

    def test_a_dirty_row_presents(self):
        p = pill()
        p.canvas.dirty = True
        p._present()
        self.assertEqual(p.gdi.presents, [(p.x, p.y)])

    def test_and_a_settled_one_does_not(self):
        p = pill()
        p.canvas.dirty = False
        p._present()
        self.assertEqual(p.gdi.presents, [])

    def test_a_dirty_band_presents_even_with_the_row_unchanged(self):
        # The case that was got wrong first: the draft panel repaints when the
        # draft changes, which is not when the pill's own key changes. Keyed off
        # the row alone, it composited the row with the panel missing.
        p = pill(band=100)
        p.canvas.dirty = False
        p.bubble.canvas.dirty = True
        p._present()
        self.assertEqual(p.gdi.presents, [(p.x, p.y)])

    def test_a_hidden_band_is_not_consulted_and_not_drawn(self):
        # Parked panels keep whatever their last render left on them. Reading their
        # dirty flag would present on every frame for as long as one stayed hidden.
        p = pill(band=0)
        p.canvas.dirty = False
        p.bubble.canvas.dirty = True
        p._present()
        self.assertEqual(p.gdi.presents, [])

    def test_the_row_is_replayed_at_the_foot_of_the_window(self):
        # `place`d at `y = h - PILL_H` with the band above it — and the row is the
        # canvas that owns the painter, so its own offset has to be said.
        p = pill(band=100)
        p.canvas.dirty = True
        p.canvas.create_text(0, 0, text="OFF")
        p.bubble.canvas.create_text(0, 0, text="draft")
        p._present()
        self.assertEqual(p.gdi.drawn("create_text"),
                         [((0, 0), (0, 0)), ((0, 100), (0, 0))])

    def test_a_parked_window_composites_nothing(self):
        # `hide_to_tray` moves the window off every monitor. A present would put it
        # back, because `UpdateLayeredWindow` is given a position too.
        p = pill()
        p._hidden = True
        p.canvas.dirty = True
        p._present()
        self.assertEqual(p.gdi.presents, [])

    def test_a_tk_drawn_surface_never_presents(self):
        p = pill(composited=False)
        p._present()  # must not raise, and must not reach for a painter
        self.assertEqual(p.gdi.presents, [])


class TestTheIdleDimMovesToTheBlend(unittest.TestCase):
    """`attributes("-alpha", …)` is `SetLayeredWindowAttributes`, which is the
    *other* of Windows' two layered modes — and a window put into it refuses
    `UpdateLayeredWindow` from then on. Left as it was, the 8 s idle fade would
    have taken the whole surface off the screen and kept it off."""

    def dimmed(self, *, composited):
        p = pill(composited=composited)
        p.attributes = mock.Mock()
        p._drawn_alpha = 1.0
        p._disarmed_since = 0.0  # long ago: the dim is due
        p._hover_since = None
        p.canvas.dirty = False
        p._apply_idle_dim()
        return p

    def test_composited_it_is_written_to_the_blend(self):
        p = self.dimmed(composited=True)
        self.assertEqual(p.gdi.constant_alpha, round(ui.IDLE_DIM_ALPHA * 255))
        p.attributes.assert_not_called()

    def test_and_the_frame_is_marked_so_it_actually_arrives(self):
        # The dim moves on its own clock, and nothing else about the picture has
        # changed — so `_draw_key` skips the repaint and only this can say the
        # bitmap must go out again.
        self.assertTrue(self.dimmed(composited=True).canvas.dirty)

    def test_tk_drawn_it_is_still_the_window_attribute(self):
        p = self.dimmed(composited=False)
        p.attributes.assert_called_once_with("-alpha", ui.IDLE_DIM_ALPHA)

    def test_an_unchanged_target_writes_nothing_either_way(self):
        p = pill()
        p.attributes = mock.Mock()
        p._drawn_alpha = 1.0
        p._disarmed_since = None  # armed: no dim
        p._hover_since = None
        p.canvas.dirty = False
        p._apply_idle_dim()
        self.assertFalse(p.canvas.dirty)
        p.attributes.assert_not_called()


class TestTheSurfaceGivesTheBitmapBack(unittest.TestCase):
    """A `GdiCanvas` holds a DIB and a GDI+ graphics for a window that is about to
    stop existing — and a design switch builds the next surface in the same
    interpreter, so the process ending is not the answer."""

    def _pill(self):
        p = pill()
        p.destroy = mock.Mock()
        p._cancel_pending = mock.Mock()
        p._tray = None
        p.hotkeys = None
        p.armed = False
        p.session = mock.Mock()
        return p

    def test_a_quit_closes_it(self):
        p = self._pill()
        with mock.patch.object(ui, "_unload_fonts"):
            p.quit_app()
        self.assertEqual(p.gdi.closed, 1)

    def test_a_detach_closes_it_too(self):
        # The one thing `detach` shares with a quit rather than omits — the surface
        # being built next makes its own.
        p = self._pill()
        p.detach()
        self.assertEqual(p.gdi.closed, 1)

    def test_a_surface_with_no_painter_is_not_a_failure(self):
        # Lite, a Mac, and every fixture in this suite built with `__new__`.
        p = ui.Pill.__new__(ui.Pill)
        p._close_painter()  # a missing canvas must not recurse into `self.tk`


# -- which canvas each window gets --------------------------------------------


class TestWhoIsCompositedAndWhoIsNot(unittest.TestCase):
    """`painter_for`'s rule, at the three windows that ask it."""

    def test_the_pill_gets_a_tee_so_its_items_survive(self):
        # A `GdiCanvas` has no items to `tag_bind`, and this file hit-tests through
        # them. The tee is what buys the bitmap without the interaction rewrite.
        canvas = object()
        gdi = FakeGdi()
        with mock.patch.object(paint, "available", return_value=True), \
                mock.patch.object(paint, "GdiCanvas", return_value=gdi):
            got = paint.painter_for(canvas, ui.BUBBLE_W, ui.PILL_H, lite=False,
                                    tee=True)
        self.assertIsInstance(got, paint.TeeCanvas)
        self.assertTrue(getattr(got, "antialiased", False))

    def test_lite_gets_the_canvas_itself_even_asking_for_a_tee(self):
        # Lite is the mode that asks nothing of the platform, and a layered window
        # is the largest ask this surface makes of it. `tests/test_lite.py` builds a
        # real one, so this is not hypothetical.
        canvas = object()
        with mock.patch.object(paint, "available", return_value=True):
            self.assertIs(paint.painter_for(canvas, 400, 34, lite=True, tee=True),
                          canvas)

    def test_a_machine_that_cannot_layer_gets_it_too(self):
        canvas = object()
        with mock.patch.object(paint, "available", return_value=False):
            self.assertIs(paint.painter_for(canvas, 400, 34, lite=False, tee=True),
                          canvas)

    def test_the_panels_record_only_where_the_pill_composites(self):
        canvas = object()
        self.assertIsInstance(ui._recorder(canvas, mock.Mock(composited=True)),
                              paint.TeeCanvas)
        self.assertIs(ui._recorder(canvas, mock.Mock(composited=False)), canvas)

    def test_a_recorder_owns_no_bitmap_of_its_own(self):
        # They are `Frame`s inside somebody else's window: their lists are replayed
        # by the pill's painter and they have nothing to present.
        rec = paint.recorder(Recorder())
        rec.resize(10, 10)  # both are no-ops rather than an AttributeError
        rec.close()
        self.assertEqual(rec.measure("x", ("Segoe UI", -12)), (0, 0))


# -- the editor's own window --------------------------------------------------


def bubble(*, editing=True, y=27, height=59):
    """A `Bubble` with an editor open, built the way `test_editor.py` builds one."""
    b = ui.Bubble.__new__(ui.Bubble)
    b.pill = mock.Mock(x=1320, y=1395, composited=True)
    b._editor = object()
    b._edit_box = mock.Mock()
    b._edit_slot = (y, height) if editing else None
    return b


class TestTheEditorTravelsWithThePanel(unittest.TestCase):
    """It is a `Toplevel` of its own now — the cost decisions.md named when it said
    what would reopen this port — so it is not carried by the panel's `place`, and
    every move of the shell has to be answered with a `geometry` call."""

    def setUp(self):
        self.addCleanup(ui.apply_scale, 1.0)

    def asked(self, b) -> str:
        return b._edit_box.geometry.call_args.args[0]

    def test_it_is_placed_over_the_well_in_device_pixels(self):
        ui.apply_scale(3.0)
        b = bubble()
        b._place_editor(27, 59)
        # The well is `(PAD, y)` to `(BUBBLE_W - PAD - EDIT_GUTTER, y + height)` on
        # a canvas whose origin is the pill's own, so this is that rectangle.
        self.assertEqual(
            self.asked(b),
            f"{ui.dev(ui.BUBBLE_W - 2 * ui.PAD - ui.EDIT_GUTTER)}x{ui.dev(59)}"
            f"+{1320 + ui.dev(ui.PAD)}+{1395 + ui.dev(27)}")

    def test_at_one_it_is_the_design_rectangle(self):
        b = bubble()
        b._place_editor(27, 59)
        self.assertEqual(
            self.asked(b),
            f"{ui.BUBBLE_W - 2 * ui.PAD - ui.EDIT_GUTTER}x59"
            f"+{1320 + ui.PAD}+{1395 + 27}")

    def test_it_is_lifted_because_both_windows_are_topmost(self):
        b = bubble()
        b._place_editor(27, 59)
        b._edit_box.lift.assert_called_once()

    def test_a_drag_re_places_it_from_the_remembered_slot(self):
        # `Pill._bind_drag`'s drag calls `reposition()` and nothing else, so the
        # slot has to survive between renders or the box stays where the panel was.
        b = bubble()
        b.pill.x, b.pill.y = 200, 300
        b._place_editor()
        self.assertTrue(self.asked(b).endswith(f"+{200 + ui.PAD}+{300 + 27}"))

    def test_with_no_box_open_it_does_nothing(self):
        b = bubble()
        b._edit_box = None
        b._place_editor(27, 59)  # must not raise: `reposition` runs on every render

    def test_and_nothing_before_the_first_render_has_measured_a_slot(self):
        b = bubble(editing=False)
        b._place_editor()
        b._edit_box.geometry.assert_not_called()


class TestTheCanvasKeepsTheWellAndNotTheWidget(unittest.TestCase):
    """The `create_window` that embedded the `tk.Text` is a rectangle now. It is
    drawn rather than left empty because the box is a `geometry` call behind: a
    resize lands on the canvas a frame before the window follows it, and what shows
    through in between should be the same rectangle arriving early."""

    def test_the_well_is_where_the_widget_was(self):
        from test_editor import WORK, MeasuringCanvas

        b = ui.Bubble.__new__(ui.Bubble)
        b.pill = mock.Mock(x=0, y=0)
        b.pill.session = mock.Mock(mode="dictate", editing=True, can_rescue=False,
                                   can_take_reply=False, auto_ask_in=None)
        b.pill.accent = "#000000"
        b.pill.work = WORK
        b.pill.band_h = lambda: ui.PANEL_MAX_H
        b.canvas = MeasuringCanvas()
        b._text, b._sent, b._partial, b._note = "a draft", "", "", ""
        b._act, b._h, b._bar_y = None, 200, 0
        b._editor = object()
        b._edit_box = mock.Mock()
        b.reposition = lambda *a, **kw: None
        b.after = lambda *a, **kw: None
        b._render()
        placed = b._edit_box.geometry.call_args.args[0]
        # The rectangle the canvas drew and the window that was placed over it are
        # the same slot, which is the only thing holding the two together.
        y, height = b._edit_slot
        self.assertIn(f"x{ui.dev(height)}+", placed)
        wells = [i for i in b.canvas.items
                 if i["x"] == ui.PAD and i["y"] == y and i["fill"] == ui.SHELL]
        self.assertEqual(len(wells), 1, "the editor's well was not drawn")
        self.assertEqual(wells[0]["h"], height)


class TestTheEditorGoesWhenItIsClosed(unittest.TestCase):
    def test_both_the_box_and_its_window(self):
        # An empty always-on-top rectangle left over the panel is a worse failure
        # than the embedded widget this replaced.
        b = ui.Bubble.__new__(ui.Bubble)
        box, shell = mock.Mock(), mock.Mock()
        box.get.return_value = "edited"
        b._editor, b._edit_box, b._edit_slot = box, shell, (27, 59)
        b._previous_focus = 0
        self.assertEqual(b._close_editor(), "edited")
        box.destroy.assert_called_once()
        shell.destroy.assert_called_once()
        self.assertIsNone(b._editor)
        self.assertIsNone(b._edit_box)
        self.assertIsNone(b._edit_slot)

    def test_closing_one_that_was_never_opened_is_safe(self):
        b = ui.Bubble.__new__(ui.Bubble)
        b._editor, b._previous_focus = None, 0
        # `_edit_box` and `_edit_slot` are deliberately *not* set: they are class
        # defaults for the reason every other name in that block is one, and a
        # fixture built with `__new__` must find a real `None` rather than recurse
        # through `tk.Misc.__getattr__` into `self.tk`.
        self.assertEqual(b._close_editor(), "")


# -- the painter's two units --------------------------------------------------


@unittest.skipUnless(sys.platform == "win32", "layered windows are Win32")
class TestThePainterAgreesWithTkAboutSize(unittest.TestCase):
    """Two conversions the port found by photograph, both of them measured.

    Neither is about compositing as such — they are about the *same* drawing code
    reaching two backends and having to come out the same size in both.
    """

    def test_a_stroke_width_is_a_design_length(self):
        # A GDI+ pen in `UnitPixel` is not touched by the world transform: at scale
        # 3, pens of 1, 1.5 and 2 all rendered the same two device rows, so every
        # mark on the 300 % display came out a third of its weight. `ScaledCanvas`
        # multiplies a `width` for the Tk path; this is the same rule for the other.
        one = paint.GdiCanvas(20, 20, 1.0, 1.0)
        three = paint.GdiCanvas(20, 20, 1.0, 3.0)
        self.addCleanup(one.close)
        self.addCleanup(three.close)
        self.assertEqual(lit(one, width=2), lit(three, width=2) / 3)

    def test_an_absent_one_is_a_device_hairline(self):
        # `_panel_chrome`'s three hairlines are drawn without a width on purpose,
        # and Tk keeps them at one device pixel however the display is scaled.
        three = paint.GdiCanvas(20, 20, 1.0, 3.0)
        self.addCleanup(three.close)
        self.assertLessEqual(lit(three), 2)

    def test_a_point_size_is_not_a_pixel_size(self):
        # Tk spells points positive and pixels negative. Taken for pixels, the Help
        # sheet came out at three-quarters of its height — 96/72 of the number.
        c = paint.GdiCanvas(400, 200, 1.0, 1.0)
        self.addCleanup(c.close)
        _w, points = c.measure("Commands", ("Segoe UI", 11))
        _w, pixels = c.measure("Commands", ("Segoe UI", -11))
        self.assertAlmostEqual(points / pixels, 96 / 72, delta=0.12)

    def test_a_wrap_column_is_measured_as_it_will_be_drawn(self):
        # The shipped surface's draft, note, partial and answer all pass a `width`,
        # which on a Tk text item is a wrap column. Composited without it they ran
        # off the side of the panel in one line.
        c = paint.GdiCanvas(400, 200, 1.0, 1.0)
        self.addCleanup(c.close)
        text = "the quick brown fox jumps over the lazy dog again and again"
        flat_w, flat_h = c.measure(text, ui.FONT_BODY)
        wrapped_w, wrapped_h = c.measure(text, ui.FONT_BODY, 120)
        self.assertLessEqual(wrapped_w, 121)
        self.assertLess(wrapped_w, flat_w)
        self.assertGreater(wrapped_h, flat_h)


def lit(canvas, **kw) -> int:
    """How many device rows a horizontal line through the middle actually covers."""
    canvas.delete("all")
    canvas.create_line(0, 10, 20, 10, fill="#FFFFFF", **kw)
    pw, ph = canvas.device_size
    buf, x = canvas._buf.raw, pw // 2
    return sum(1 for y in range(ph) if buf[(y * pw + x) * 4 + 3])


if __name__ == "__main__":
    unittest.main()
