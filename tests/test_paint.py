"""`flow.paint` — the antialiased stand-in for `tk.Canvas`.

What can be pinned here is the part that is not Windows: the colour and point
conversions every call goes through, and the choice `painter_for` makes. The
rendering itself is proven by photograph (`scripts/compact_shots.py`), for the
reason every drawing test in this suite is: a claim that a curve is smooth is
not a claim a headless assertion can settle.
"""

import ctypes
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow import paint  # noqa: E402


class TestTheColourConversion(unittest.TestCase):
    def test_a_hex_colour_becomes_opaque_argb(self):
        self.assertEqual(paint._argb("#3ECF8E"), 0xFF3ECF8E)
        self.assertEqual(paint._argb("#000000"), 0xFF000000)

    def test_the_alpha_rides_in_the_top_byte(self):
        self.assertEqual(paint._argb("#FFFFFF", 0), 0x00FFFFFF)
        self.assertEqual(paint._argb("#1A1D23", 128), 0x801A1D23)

    def test_a_name_tk_would_resolve_is_refused(self):
        # Guessed rather than raised is how a colour ends up spelled two ways,
        # and this app's palette is hex constants in one place precisely so
        # that cannot happen.
        for bad in ("white", "grey20", "#abc"):
            with self.subTest(colour=bad):
                with self.assertRaises(ValueError):
                    paint._argb(bad)


class TestThePointSpellings(unittest.TestCase):
    """Tk takes a point list three ways and this app uses all three."""

    def test_loose_coordinates(self):
        self.assertEqual(paint._points((0, 1, 2, 3)), [(0, 1), (2, 3)])

    def test_one_flat_list(self):
        self.assertEqual(paint._points(([0, 1, 2, 3],)), [(0, 1), (2, 3)])

    def test_a_list_of_pairs(self):
        self.assertEqual(paint._points(([(0, 1), (2, 3)],)), [(0, 1), (2, 3)])

    def test_an_odd_trailing_value_is_dropped_not_raised(self):
        # A repaint is not the place to raise over a coordinate, and half a
        # point is not a point.
        self.assertEqual(paint._points((0, 1, 2)), [(0, 1)])


class TestWhichPainterAWindowGets(unittest.TestCase):
    def test_lite_draws_on_the_canvas(self):
        # Lite is the mode that asks nothing of the platform, and a layered
        # window is the largest ask this surface makes of it.
        canvas = object()
        with mock.patch.object(paint, "available", return_value=True):
            self.assertIs(paint.painter_for(canvas, 120, 34, lite=True),
                          canvas)

    def test_a_machine_that_cannot_layer_draws_on_the_canvas(self):
        canvas = object()
        with mock.patch.object(paint, "available", return_value=False):
            self.assertIs(paint.painter_for(canvas, 120, 34, lite=False),
                          canvas)

    def test_a_gdi_plus_that_will_not_give_a_bitmap_falls_back(self):
        canvas = object()
        with mock.patch.object(paint, "available", return_value=True), \
                mock.patch.object(paint, "GdiCanvas", side_effect=OSError):
            self.assertIs(paint.painter_for(canvas, 120, 34, lite=False),
                          canvas)

    @unittest.skipUnless(sys.platform == "win32", "layered windows are Win32")
    def test_windows_gets_the_antialiased_one(self):
        got = paint.painter_for(object(), 120, 34, lite=False)
        self.assertTrue(getattr(got, "antialiased", False))
        self.assertIsInstance(got, paint.GdiCanvas)
        got.close()

    @unittest.skipUnless(sys.platform == "win32", "layered windows are Win32")
    def test_the_window_opacity_rides_on_the_blend(self):
        # `-alpha` cannot coexist with `UpdateLayeredWindow`, so the number it
        # carried moves to `SourceConstantAlpha` — the same opacity, on the
        # mode this surface actually uses.
        got = paint.painter_for(object(), 120, 34, lite=False, alpha=0.94)
        self.assertEqual(got.constant_alpha, round(0.94 * 255))
        got.close()


@unittest.skipUnless(sys.platform == "win32", "layered windows are Win32")
class TestTheSurfaceItDrawsOn(unittest.TestCase):
    """The bitmap side, which needs GDI+ but not a window."""

    def setUp(self):
        self.c = paint.GdiCanvas(60, 20)
        self.addCleanup(self.c.close)

    def test_it_wears_the_canvas_vocabulary(self):
        # The whole design of this module: `ui_compact` draws through one set
        # of calls and never learns which backend took them.
        for name in ("delete", "create_line", "create_polygon",
                     "create_rectangle", "create_oval", "create_arc",
                     "create_text"):
            with self.subTest(call=name):
                self.assertTrue(callable(getattr(self.c, name, None)))

    def test_drawing_does_not_raise(self):
        self.c.delete("all")
        self.c.create_polygon([(0, 0), (10, 0), (10, 10)], fill="#1A1D23")
        self.c.create_polygon([0, 0, 10, 0, 10, 10], smooth=True,
                              fill="#1A1D23", outline="#0B0D10")
        self.c.round_rect(0, 0, 40, 16, 8, fill="#22262E", outline="#0B0D10")
        self.c.round_rect(0, 0, 40, 16, (8, 8, 0, 0), fill="#22262E")
        self.c.create_line(0, 0, 20, 10, fill="#3ECF8E", width=1)
        self.c.create_arc(0, 0, 12, 12, start=180, extent=180,
                          outline="#E6E8ED", width=1.4)
        self.c.create_oval(0, 0, 10, 10, outline="#656B78")
        self.c.create_text(4, 8, text="flow", font=("Segoe UI", -12),
                           fill="#E6E8ED", anchor="w")

    def test_measuring_a_prefix_places_it_where_the_prefix_ends(self):
        # What the palette's `.hit` tint needs, and what a Tk measurement
        # could not give it once GDI+ was drawing the glyphs.
        font = ("Consolas", -12)
        whole, _h = self.c.measure("~/dev/flow", font)
        prefix, _h = self.c.measure("~/dev/", font)
        rest, _h = self.c.measure("flow", font)
        self.assertGreater(prefix, 0)
        self.assertAlmostEqual(prefix + rest, whole, delta=1.0)

    def test_an_empty_string_draws_nothing_rather_than_failing(self):
        self.c.create_text(0, 0, text="", font=("Segoe UI", -12),
                           fill="#E6E8ED")

    def test_resizing_is_idempotent_and_keeps_drawing(self):
        self.c.resize(60, 20)
        self.c.resize(120, 34)
        self.c.delete("all")
        self.c.create_rectangle(0, 0, 10, 10, fill="#1A1D23")

    def test_closing_twice_is_safe(self):
        c = paint.GdiCanvas(10, 10)
        c.close()
        c.close()


class TestTheBundledFacesReachGdiPlus(unittest.TestCase):
    """`ui._load_fonts` registers the five IBM Plex files with
    `AddFontResourceExW(FR_PRIVATE)`, which GDI and Tk honour and GDI+ does
    not: probed on this machine, `GdipCreateFontFamilyFromName("IBM Plex
    Sans", None, …)` answered 14 — FontFamilyNotFound — *after* that
    registration, so every string the compact surface composited fell to
    `_font`'s stand-ins. `load_fonts` is the collection GDI+ will look in.

    GDI+ is mocked here: what is under test is the bookkeeping — what gets
    added, what gets skipped, and which collection is asked first — none of
    which is a claim about rendering.
    """

    def setUp(self):
        self.gdiplus = mock.Mock()
        self.gdiplus.GdipNewPrivateFontCollection.return_value = 0
        self.gdiplus.GdipPrivateAddFontFile.return_value = 0
        self.gdiplus.GdipCreateFontFamilyFromName.return_value = 0
        # Module-level state, patched rather than reset: the collection is
        # process-wide and `flow.ui_compact` fills it at import, so a test
        # that assigned to it would be reading whatever the suite left behind.
        for patch in (mock.patch.object(paint, "_gdiplus", self.gdiplus),
                      mock.patch.object(paint, "_start", return_value=1),
                      mock.patch.object(paint, "_collection", None),
                      mock.patch.object(paint, "_font_files", set())):
            patch.start()
            self.addCleanup(patch.stop)
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def files(self, *names) -> list:
        out = []
        for name in names:
            path = Path(self.dir.name) / name
            path.write_bytes(b"not really a font, and GDI+ is a Mock")
            out.append(str(path))
        return out

    def test_it_answers_with_how_many_went_in(self):
        paths = self.files("A.ttf", "B.ttf")
        self.assertEqual(paint.load_fonts(paths), 2)
        self.assertEqual(self.gdiplus.GdipPrivateAddFontFile.call_count, 2)

    def test_one_collection_holds_them_all(self):
        paint.load_fonts(self.files("A.ttf", "B.ttf", "C.ttf"))
        self.gdiplus.GdipNewPrivateFontCollection.assert_called_once()

    def test_a_second_call_adds_nothing(self):
        # Idempotent, because the registration is a module import's side
        # effect and an import is not a thing to count on happening once.
        paths = self.files("A.ttf", "B.ttf")
        self.assertEqual(paint.load_fonts(paths), 2)
        self.assertEqual(paint.load_fonts(paths), 0)
        self.assertEqual(self.gdiplus.GdipPrivateAddFontFile.call_count, 2)

    def test_a_missing_file_is_skipped_and_counted_as_not_added(self):
        # A font is a fact about the machine, not a reason a repaint fails:
        # `_font` already substitutes like for like for whatever is absent.
        paths = self.files("A.ttf") + [str(Path(self.dir.name) / "gone.ttf")]
        self.assertEqual(paint.load_fonts(paths), 1)
        self.assertEqual(self.gdiplus.GdipPrivateAddFontFile.call_count, 1)

    def test_a_file_gdi_plus_refuses_is_skipped_not_raised(self):
        self.gdiplus.GdipPrivateAddFontFile.return_value = 7
        self.assertEqual(paint.load_fonts(self.files("A.ttf")), 0)

    def test_a_collection_that_cannot_be_made_is_not_an_exception(self):
        self.gdiplus.GdipNewPrivateFontCollection.return_value = 7
        self.assertEqual(paint.load_fonts(self.files("A.ttf")), 0)

    def test_a_machine_without_gdi_plus_adds_nothing(self):
        with mock.patch.object(paint, "_start", return_value=None):
            self.assertEqual(paint.load_fonts(self.files("A.ttf")), 0)
        self.gdiplus.GdipPrivateAddFontFile.assert_not_called()

    def test_the_private_collection_is_asked_before_the_installed_one(self):
        # The whole point of the collection: asked the other way round, a
        # machine with some other "IBM Plex Sans" installed would beat the
        # file this app ships.
        self.gdiplus.GdipCreateFontFamilyFromName.side_effect = [14, 0]
        collection = ctypes.c_void_p(1234)
        out = ctypes.c_void_p()
        with mock.patch.object(paint, "_collection", collection):
            self.assertEqual(paint._family("IBM Plex Sans", out), 0)
        first, second = self.gdiplus.GdipCreateFontFamilyFromName.call_args_list
        self.assertIs(first.args[1], collection)
        self.assertIsNone(second.args[1])

    def test_a_family_the_private_collection_has_never_asks_further(self):
        collection = ctypes.c_void_p(1234)
        with mock.patch.object(paint, "_collection", collection):
            self.assertEqual(paint._family("IBM Plex Mono", ctypes.c_void_p()),
                             0)
        self.gdiplus.GdipCreateFontFamilyFromName.assert_called_once()

    def test_with_no_collection_the_installed_one_is_the_only_one_asked(self):
        # Off Windows, or before `load_fonts` — `_font` still resolves Segoe
        # UI and Consolas, which are the machine's and never ours.
        self.assertEqual(paint._family("Segoe UI", ctypes.c_void_p()), 0)
        (call,) = self.gdiplus.GdipCreateFontFamilyFromName.call_args_list
        self.assertIsNone(call.args[1])


@unittest.skipUnless(sys.platform == "win32", "GDI+ is Win32")
class TestTheRealPlexFilesResolve(unittest.TestCase):
    """The other half, on the machine itself: the names `flow/ui.py` spells
    are the names the collection answers to, and the glyphs change."""

    def setUp(self):
        from flow import ui
        self.ui = ui
        paint.load_fonts(str(ui._FONT_DIR / f) for f in ui._FONT_FILES)

    def test_every_family_the_font_tuples_name_is_found(self):
        for name in (self.ui.FONT_SANS, self.ui.FONT_SANS_MEDIUM,
                     self.ui.FONT_SANS_SEMIBOLD, self.ui.FONT_MONO):
            with self.subTest(family=name):
                fam = ctypes.c_void_p()
                # GDI truncates "Medium"/"SemiBold" in its legacy name table
                # and the private collection carries the truncation through,
                # which is why these are the spellings and not the full ones.
                self.assertEqual(paint._family(name, ctypes.byref(fam)), 0)
                paint._gdiplus.GdipDeleteFontFamily(fam)

    def test_a_plex_string_no_longer_measures_like_its_stand_in(self):
        # The defect's signature: with the family unfound, `_font` fell to
        # Consolas and "IBM Plex Mono" measured to the pixel like Consolas —
        # 145.148 for both, before this. A different width is the layered
        # surface actually being drawn in the design's typeface.
        c = paint.GdiCanvas(400, 40)
        self.addCleanup(c.close)
        text = "LISTENING and a sentence"
        plex, _h = c.measure(text, (self.ui.FONT_MONO, -11))
        stand_in, _h = c.measure(text, ("Consolas", -11))
        self.assertNotAlmostEqual(plex, stand_in, delta=0.01)


if __name__ == "__main__":
    unittest.main()
