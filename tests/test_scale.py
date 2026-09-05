"""Design pixels in, device pixels out — the shipped surface at native resolution.

`flow/ui.py` is written in the pixels §02's mocks are drawn in, and until now those
were the screen's pixels too, because the process was DPI-*unaware* and Windows was
stretching the result by the scale factor with a bilinear filter. `flow/ui_compact.py`
settled the rule for the other surface: every size stays in design pixels and is
converted at the point it meets Tk geometry or the screen. This file pins that rule
here — `dev`/`design`, the `paint.ScaledCanvas` that applies it to every drawing call,
and the four sites in `Pill` where a Win32 rectangle and a constant of this file's meet.

**`SCALE` is module state**, rebound by `apply_scale` and read by everything, so every
test that moves it puts it back in `tearDown`. A leak would not fail here — it would
fail somewhere else, in a file that never mentions scale.

The picture itself is not asserted here, for the reason no drawing test in this suite
asserts one: "it renders sharp" is settled by `scripts/shots.py` and a look at the PNG.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flow.ui as ui  # noqa: E402
from flow import paint  # noqa: E402
from flow.session import DICTATE  # noqa: E402


class Recorder:
    """A canvas that records what it was actually handed, in whatever units.

    The point of `ScaledCanvas` is that the caller writes design pixels and the widget
    receives device ones, so the only way to test it is to be the widget.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        #: What `bbox` and `coords` answer with, in device pixels.
        self.box = (30, 60, 90, 120)
        self.points = [3.0, 6.0, 9.0, 12.0]

    def __getattr__(self, name):
        def call(*a, **kw):
            self.calls.append((name, a, kw))
            return f"item-{len(self.calls)}"
        return call

    def bbox(self, *a):
        self.calls.append(("bbox", a, {}))
        return self.box

    def coords(self, *a):
        self.calls.append(("coords", a, {}))
        return self.points

    def last(self, name: str) -> tuple:
        for call in reversed(self.calls):
            if call[0] == name:
                return call
        raise AssertionError(f"{name} was never called")


class ScaleCase(unittest.TestCase):
    """Every case here moves module state, so every case puts it back."""

    def setUp(self):
        self.addCleanup(ui.apply_scale, 1.0)


class TestTheTwoConversions(ScaleCase):
    def test_at_one_they_are_both_the_identity(self):
        ui.apply_scale(1.0)
        for v in (0, 4, 34, 205, 400):
            with self.subTest(v=v):
                self.assertEqual(ui.dev(v), v)
                self.assertEqual(ui.design(v), v)

    def test_at_three_a_row_is_three_rows_of_screen(self):
        ui.apply_scale(3.0)
        self.assertEqual(ui.dev(ui.PILL_H), 102)
        self.assertEqual(ui.dev(ui.BUBBLE_W), 1200)
        self.assertEqual(ui.design(102), ui.PILL_H)

    def test_it_rounds_rather_than_floors(self):
        # 34 px at 150 % is 51 and not 50: half a pixel of drift at the bottom edge is
        # a hairline outside the window, which is exactly what a floor would leave.
        ui.apply_scale(1.5)
        self.assertEqual(ui.dev(34), 51)
        self.assertEqual(ui.dev(ui.PILL_DRAG_SLOP), 6)

    def test_a_zero_offset_survives(self):
        # `dev` converts offsets as well as sizes, and the compact surface learned this
        # the hard way: floored at one, a closed panel moved its capsule a pixel every
        # time it was drawn.
        ui.apply_scale(3.0)
        self.assertEqual(ui.dev(0), 0)

    def test_a_scale_that_cannot_be_had_is_one(self):
        # `paint.scale_for` answers 1.0 when it cannot ask, and a machine that answered
        # zero or a negative would divide by nothing in `design`.
        for bad in (0, 0.0, -2.0, None):
            with self.subTest(bad=bad):
                ui.apply_scale(bad)
                self.assertEqual(ui.SCALE, 1.0)


class TestTheFontSpecs(ScaleCase):
    """A pixel size is this file's to scale; a point size is Tk's already."""

    def test_a_pixel_size_is_multiplied(self):
        self.assertEqual(paint.scale_font(ui.FONT_BODY, 3.0),
                         (ui.FONT_SANS, -39))
        self.assertEqual(paint.scale_font(ui.FONT_NOTE, 3.0),
                         (ui.FONT_SANS, -33))

    def test_a_style_rides_along(self):
        self.assertEqual(paint.scale_font(ui.FONT_PARTIAL, 2.0),
                         (ui.FONT_SANS, -22, "italic"))

    def test_a_point_size_is_left_to_tk(self):
        # Measured on the 300 % display: `tk scaling` is 3.996 once the process is
        # DPI-aware against 1.333 while it is not, so an 11 pt face already comes back
        # three times as large. Scaling it here would square the factor.
        self.assertEqual(paint.scale_font(("Segoe UI", 11, "bold"), 3.0),
                         ("Segoe UI", 11, "bold"))

    def test_anything_that_is_not_a_sized_spec_is_returned_untouched(self):
        for spec in ("TkDefaultFont", (), ("IBM Plex Sans",), None):
            with self.subTest(spec=spec):
                self.assertEqual(paint.scale_font(spec, 3.0), spec)

    def test_the_editor_asks_the_module_for_its_own(self):
        # The one widget on the surface that is not a canvas, so it converts its own.
        ui.apply_scale(3.0)
        self.assertEqual(ui.scaled_font(ui.FONT_BODY), (ui.FONT_SANS, -39))


class TestTheScaledCanvasIsTransparentAtOne(ScaleCase):
    def test_ui_does_not_wrap_at_all(self):
        # Not "wrapped with a factor of one": a 100 % display, a Mac and every test
        # that builds a real Tk canvas run the code they ran before, with no proxy in
        # the path to be wrong.
        ui.apply_scale(1.0)
        bare = Recorder()
        self.assertIs(ui._scaled(bare), bare)

    def test_and_wraps_above_it(self):
        ui.apply_scale(3.0)
        self.assertIsInstance(ui._scaled(Recorder()), paint.ScaledCanvas)

    def test_a_proxy_at_one_changes_nothing(self):
        rec = Recorder()
        paint.ScaledCanvas(rec, 1.0).create_line(4, 8, 12, 16, width=2)
        self.assertEqual(rec.last("create_line"), ("create_line", (4, 8, 12, 16),
                                                   {"width": 2}))


class TestTheScaledCanvasScalesWhatItDraws(ScaleCase):
    def setUp(self):
        super().setUp()
        self.rec = Recorder()
        self.c = paint.ScaledCanvas(self.rec, 3.0)

    def test_every_coordinate_of_every_create(self):
        self.c.create_line(1, 2, 3, 4)
        self.c.create_rectangle(1, 2, 3, 4)
        self.c.create_oval(1, 2, 3, 4)
        self.c.create_arc(1, 2, 3, 4)
        self.c.create_text(1, 2, text="x")
        for name in ("create_line", "create_rectangle", "create_oval",
                     "create_arc", "create_text"):
            with self.subTest(call=name):
                self.assertEqual(self.rec.last(name)[1][:2], (3, 6))

    def test_a_point_list_keeps_its_shape(self):
        # `_round_rect` hands `create_polygon` one flat list; other callers pass the
        # coordinates loose, and Tk accepts pairs as well. All three appear in this app.
        self.c.create_polygon([1, 2, 3, 4], smooth=True)
        self.assertEqual(self.rec.last("create_polygon")[1], ([3, 6, 9, 12],))
        self.c.create_line([(1, 2), (3, 4)])
        self.assertEqual(self.rec.last("create_line")[1], ([(3, 6), (9, 12)],))

    def test_a_stroke_width_is_a_length_too(self):
        # `width` is a stroke on a line, an outline on a box, a wrap column on a string
        # and a box on an embedded widget — one name, four jobs, all of them pixels.
        self.c.create_line(0, 0, 4, 0, width=2)
        self.assertEqual(self.rec.last("create_line")[2]["width"], 6)

    def test_a_wrap_column_is_a_length_too(self):
        self.c.create_text(0, 0, text="x", width=ui.BUBBLE_W - 2 * ui.PAD)
        self.assertEqual(self.rec.last("create_text")[2]["width"],
                         3 * (ui.BUBBLE_W - 2 * ui.PAD))

    def test_a_pixel_font_is_scaled_with_it(self):
        self.c.create_text(0, 0, text="x", font=ui.FONT_BODY)
        self.assertEqual(self.rec.last("create_text")[2]["font"],
                         (ui.FONT_SANS, -39))

    def test_an_embedded_window_takes_its_box_in_device_pixels(self):
        # This was the hand editor's slot; the editor is a `Toplevel` of its own now, so
        # nothing in `ui.py` embeds a widget. Kept because the proxy still forwards the
        # call and a length left unscaled is the defect either way.
        self.c.create_window(ui.PAD, 20, width=100, height=50)
        name, args, kw = self.rec.last("create_window")
        self.assertEqual(args, (3 * ui.PAD, 60))
        self.assertEqual((kw["width"], kw["height"]), (300, 150))

    def test_the_widget_and_its_place_take_device_pixels(self):
        self.c.configure(width=ui.BUBBLE_W, height=100)
        self.assertEqual(self.rec.last("configure")[2],
                         {"width": 1200, "height": 300})
        self.c.place(x=0, y=34, width=ui.BUBBLE_W, height=ui.PILL_H)
        self.assertEqual(self.rec.last("place")[2],
                         {"x": 0, "y": 102, "width": 1200, "height": 102})

    def test_an_item_reconfigured_is_scaled_the_same_way(self):
        self.c.itemconfigure("chip", width=2, font=ui.FONT_NOTE)
        self.assertEqual(self.rec.last("itemconfigure")[2],
                         {"width": 6, "font": (ui.FONT_SANS, -33)})

    def test_a_move_is_a_distance(self):
        self.c.move("body", 0, -4)
        self.assertEqual(self.rec.last("move")[1], ("body", 0, -12))


class TestTheScaledCanvasAnswersInDesignPixels(ScaleCase):
    """The probes measure text off the canvas, and the layout that reads them is
    written in this file's own pixels."""

    def setUp(self):
        super().setUp()
        self.rec = Recorder()
        self.c = paint.ScaledCanvas(self.rec, 3.0)

    def test_a_bbox_comes_back_divided(self):
        self.assertEqual(self.c.bbox("probe"), (10.0, 20.0, 30.0, 40.0))

    def test_a_bbox_of_nothing_is_still_nothing(self):
        # `bbox` answers None for a tag that matched no item, and a caller that unpacks
        # it is expecting to fail rather than to divide.
        self.rec.box = None
        self.assertIsNone(self.c.bbox("gone"))

    def test_coords_read_back_divided_and_written_multiplied(self):
        self.assertEqual(self.c.coords("item"), [1.0, 2.0, 3.0, 4.0])
        self.c.coords("item", 1, 2, 3, 4)
        self.assertEqual(self.rec.last("coords")[1], ("item", 3, 6, 9, 12))


class TestEverythingElseIsTheRealCanvas(ScaleCase):
    """The reason this is a proxy rather than a rewrite: the items are real Tk items at
    real device coordinates, which is where the mouse is, so the eighteen `tag_bind`
    sites and the item-based hover tooltips go on meaning what they meant."""

    def setUp(self):
        super().setUp()
        self.rec = Recorder()
        self.c = paint.ScaledCanvas(self.rec, 3.0)

    def test_the_bindings_and_the_stacking_pass_straight_through(self):
        handler = lambda _e: None  # noqa: E731
        self.c.tag_bind("chip-Send", "<Button-1>", handler)
        self.assertEqual(self.rec.last("tag_bind")[1],
                         ("chip-Send", "<Button-1>", handler))
        self.c.tag_raise("chips")
        self.assertEqual(self.rec.last("tag_raise")[1], ("chips",))
        self.c.delete("body")
        self.assertEqual(self.rec.last("delete")[1], ("body",))

    def test_a_missing_proxy_state_raises_rather_than_recursing(self):
        # `__getattr__` reaches for `self._c`, so an instance whose `__init__` never ran
        # would otherwise recurse until the stack ends — the same trap `Pill.lite`'s
        # class default exists for.
        with self.assertRaises(AttributeError):
            paint.ScaledCanvas.__new__(paint.ScaledCanvas).create_line(0, 0, 1, 1)


def shell(*, band=0, work=(0, 0, 3840, 2016), x=1320, y=1842):
    """A pill with just enough of one to run `_sync_shell`, and a window to lie about.

    `test_pill.docker`'s fixture, with the work area in the device pixels a DPI-aware
    process actually reads — 3840x2016 is what `SPI_GETWORKAREA` answers on the 300 %
    machine this was written against.
    """
    p = ui.Pill.__new__(ui.Pill)
    p.canvas = mock.Mock()
    p.session = mock.Mock(mode=DICTATE)
    p.bubble = mock.Mock(width=ui.BUBBLE_W, _visible=bool(band), _h=band)
    p.card = mock.Mock(width=ui.BUBBLE_W, _visible=False, _h=band)
    p.work = p.full = work
    p.x, p.y = x, y
    p._docked_w = ui.BUBBLE_W
    p._shell_h = ui.PILL_H
    p.geometry = mock.Mock()
    p.window_geometry = mock.Mock(return_value=(0, 0, 0))
    return p


class TestTheShellIsAskedForInDevicePixels(ScaleCase):
    def asked(self, p) -> str:
        return p.geometry.call_args.args[0]

    def test_an_idle_row_at_three_is_three_rows_of_screen(self):
        ui.apply_scale(3.0)
        p = shell()
        p._sync_shell()
        self.assertTrue(self.asked(p).startswith("1200x102+"), self.asked(p))

    def test_and_the_canvas_is_still_asked_in_design_pixels(self):
        # The canvas converts its own (`paint.ScaledCanvas`), so converting here too
        # would square the factor on the one widget that draws the row.
        ui.apply_scale(3.0)
        p = shell(band=100)
        p._sync_shell()
        self.assertEqual(p.canvas.place.call_args.kwargs["width"], ui.BUBBLE_W)
        self.assertEqual(p.canvas.place.call_args.kwargs["height"], ui.PILL_H)
        self.assertEqual(p.canvas.configure.call_args.kwargs["width"], ui.BUBBLE_W)

    def test_a_band_grows_the_window_upward_in_device_pixels(self):
        ui.apply_scale(3.0)
        p = shell(band=100)
        p._sync_shell()
        self.assertTrue(self.asked(p).startswith("1200x402+"), self.asked(p))
        # The design height is what `_draw` measures the row against, and it stays
        # design: `_draw` compares it to `PILL_H`.
        self.assertEqual(p._shell_h, ui.PILL_H + 100)

    def test_the_window_is_compared_device_against_device(self):
        # `window_geometry` reads `winfo_*`, which on a DPI-aware process answers in
        # the pixels the window occupies. Compared against a design width, every frame
        # would disagree and ask for a `geometry` it already had.
        ui.apply_scale(3.0)
        p = shell()
        p._sync_shell()
        p.window_geometry = mock.Mock(return_value=(1200, p.x, p.y))
        p.geometry.reset_mock()
        for _ in range(5):
            p._sync_shell()
        p.geometry.assert_not_called()


class TestTheBandIsMeasuredAgainstTheRealDesktop(ScaleCase):
    def test_the_work_area_comes_back_to_design_pixels(self):
        # Left in device pixels the band would be offered three times the room it has,
        # and `PANEL_MAX_H` — the only thing standing between it and the top of the
        # screen — would never bite.
        ui.apply_scale(3.0)
        p = shell()
        p.work = (0, 0, 3840, 600)  # 200 design pixels tall, under the ceiling
        self.assertEqual(p.band_h(), 200 - 2 * ui.EDGE_AIR - ui.PILL_H)

    def test_and_the_ceiling_still_applies_on_a_tall_desktop(self):
        ui.apply_scale(3.0)
        self.assertEqual(shell().band_h(), ui.PANEL_MAX_H)

    def test_a_desktop_smaller_than_the_row_asks_for_nothing(self):
        ui.apply_scale(3.0)
        p = shell()
        p.work = (0, 0, 3840, 60)
        self.assertEqual(p.band_h(), 0)


class TestThePointerIsMeasuredInDevicePixels(ScaleCase):
    def pill(self):
        p = ui.Pill.__new__(ui.Pill)
        p._press_at = 1.0
        p._press_talking = False
        p._press_moved = False
        p._press_xy = (100, 100)
        return p

    def test_the_drag_slop_is_a_hand_tremor_and_not_a_design_pixel(self):
        # 4 px of tremor at 100 % is 12 px of screen at 300 %. Compared in design
        # pixels the hold would be cancelled by a third of the wobble it tolerates.
        ui.apply_scale(3.0)
        p = self.pill()
        p._on_motion(mock.Mock(x_root=108, y_root=100))
        self.assertFalse(p._press_moved)
        p._on_motion(mock.Mock(x_root=113, y_root=100))
        self.assertTrue(p._press_moved)

    def test_at_one_it_is_the_number_the_constant_says(self):
        ui.apply_scale(1.0)
        p = self.pill()
        p._on_motion(mock.Mock(x_root=104, y_root=100))
        self.assertFalse(p._press_moved)
        p._on_motion(mock.Mock(x_root=105, y_root=100))
        self.assertTrue(p._press_moved)

    def test_a_page_drag_scrolls_as_far_as_the_hand_moved(self):
        # The help sheet's press-and-drag, which exists because the wheel reaches an
        # unfocused window only through a Windows preference. `e.y` is device and
        # `HELP_LINE_H` is design, so the accumulator is kept in design pixels.
        ui.apply_scale(3.0)
        h = ui.HelpWindow.__new__(ui.HelpWindow)
        h._top, h._drag_y, h._drag_px = 0, None, 0
        h._rows = [("pair", f"row {i}", "") for i in range(40)]
        h._h = 400
        h._render = mock.Mock()
        h._grab(mock.Mock(y=300))
        h._drag(mock.Mock(y=300 - 3 * ui.HELP_LINE_H))
        self.assertEqual(h._top, 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
