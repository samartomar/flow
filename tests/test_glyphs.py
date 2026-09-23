"""One glyph language, asserted as a language rather than as twenty drawings.

`flow/glyphs.py` exists because the two surfaces drew the same marks twice and
differently: the shipped row's gear was a filled disc with its hub punched out
in `SHELL`, its speaker a filled wedge, its command marks 2 px strokes with a
filled pencil nib; the compact surface drew everything the way
`design/compact/gen.py` does, in 1.4 px round-capped strokes with no fills at
all. Side by side they read as two products.

So what is pinned here is not where each line goes — that is the drawing, and
it will move — but the four rules that make twenty marks one hand: nothing is
filled but a dot the size of the stroke, every item carries the caller's tags
(they are the hit regions), every point lands inside the box the caller laid
out, and one stroke weight is used unless the call site overrides it. Plus the
two variants that have to *add* rather than replace — the mic's slash and the
speaker's mute — and the mode glyph, which raises on a fourth mode rather than
falling through to whichever branch is last, because falling through is exactly
how a speech bubble once ended up over a mode that pastes.

The canvas is `test_ui_compact`'s own recording fake, widened here rather than
there: the compact pill's tests unpack its tuples positionally, so the extra
fields this needs live in a subclass.
"""

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from flow import glyphs  # noqa: E402
from test_ui_compact import Canvas  # noqa: E402


class Recording(Canvas):
    """`test_ui_compact.Canvas`, plus what it does not keep: the tags every item
    was given, and the outline and width of the ovals and rectangles.

    Subclassed rather than widened in place, because the compact pill's tests
    unpack `ovals`, `rects`, `lines` and `arcs` positionally and a new field
    would break every one of them.
    """

    def __init__(self) -> None:
        super().__init__()
        #: `(kind, flat coordinates, keywords)` per item, in draw order.
        self.items: list[tuple] = []

    def _keep(self, kind, coords, kw) -> None:
        flat = []
        for a in coords:
            flat.extend(a if isinstance(a, (list, tuple)) else [a])
        self.items.append((kind, [float(v) for v in flat], kw))

    def create_line(self, *a, **kw) -> None:
        self._keep("line", a, kw)
        super().create_line(*a, **kw)

    def create_arc(self, *a, **kw) -> None:
        self._keep("arc", a, kw)
        super().create_arc(*a, **kw)

    def create_oval(self, x1, y1, x2, y2, **kw) -> None:
        self._keep("oval", (x1, y1, x2, y2), kw)
        super().create_oval(x1, y1, x2, y2, **kw)

    def create_rectangle(self, x1, y1, x2, y2, **kw) -> None:
        self._keep("rect", (x1, y1, x2, y2), kw)
        super().create_rectangle(x1, y1, x2, y2, **kw)

    def create_polygon(self, *a, **kw) -> None:
        self._keep("poly", a, kw)
        super().create_polygon(*a, **kw)


#: The whole set, with whatever extra argument each one takes. `mode` is the
#: exception and has a class of its own: its third mark is chosen by a name.
GLYPHS = (
    ("mic", {}),
    ("mic-slashed", {"slash": True}),
    ("folder", {}),
    ("copy", {}),
    ("close", {}),
    ("cancel", {}),
    ("search", {}),
    ("gear", {}),
    ("speaker", {}),
    ("speaker-muted", {"muted": True}),
    ("mode-dictate", {}),
    ("mode-refine", {}),
    ("mode-converse", {}),
    ("refine", {}),
    ("continue_", {}),
    ("edit", {}),
    ("command", {}),
    ("take", {}),
    ("new", {}),
    ("send", {}),
    ("agent", {}),
    ("terminal", {}),
    ("into_baseline", {}),
)

#: A box that is not at the origin and not the default size, so an anchor the
#: drawing forgot to add and a scale it forgot to apply both show up as points
#: outside the box rather than as points that happen to look right.
X, Y, SIZE = 7.0, 11.0, 24.0


def draw(name: str, c, **kw) -> tuple:
    """One glyph by its table name, into `c`. Returns the box it drew in."""
    kind, _, variant = name.partition("-")
    fn = getattr(glyphs, kind)
    args = (c, X, Y, "#ABCDEF")
    if kind == "mode":
        args += (variant,)
    fn(*args, size=SIZE, tags=("mark", "row"), **kw)
    height = SIZE * glyphs.MIC_ASPECT if kind == "mic" else SIZE
    return X, Y, X + SIZE, Y + height


class TestEveryGlyphObeysTheLanguage(unittest.TestCase):
    """The four rules, over the whole set."""

    def each(self):
        for name, kw in GLYPHS:
            c = Recording()
            box = draw(name, c, **kw)
            yield name, c, box

    def test_every_glyph_draws_something(self):
        for name, c, _box in self.each():
            with self.subTest(glyph=name):
                self.assertTrue(c.items, "drew nothing at all")

    def test_nothing_is_filled_but_a_dot(self):
        """Strokes, not fills — gen.py's whole vocabulary is `fill="none"`.

        A line's colour is Tk's `fill`, so the rule is about the shapes that
        enclose an area: a polygon, a rectangle or an oval may only be filled
        if it is no bigger than the stroke, which is the eye and the antenna
        tip in `agent` and nothing else in the set.
        """
        for name, c, _box in self.each():
            for kind, coords, kw in c.items:
                if kind in ("line", "arc") or not kw.get("fill"):
                    continue
                with self.subTest(glyph=name, kind=kind):
                    w = max(coords[0::2]) - min(coords[0::2])
                    h = max(coords[1::2]) - min(coords[1::2])
                    self.assertLessEqual(max(w, h), glyphs.STROKE,
                                         "a fill bigger than the stroke")

    def test_every_item_carries_the_tags(self):
        """The tags are the hit regions. `ui._row_icons` binds `row-gear` and
        `row-mode` to a tag rather than to a rectangle, so an item a glyph drew
        without them is a piece of the control a click falls through."""
        for name, c, _box in self.each():
            for kind, _coords, kw in c.items:
                with self.subTest(glyph=name, kind=kind):
                    self.assertEqual(tuple(kw.get("tags", ())), ("mark", "row"))

    def test_every_point_is_inside_the_box(self):
        """The caller lays out a box and the glyph draws in it. A mark that
        overruns is a mark that collides with the one beside it — the row packs
        three icons at `ICON_GAP` = 8 and the command cluster packs four at 4."""
        for name, c, (x1, y1, x2, y2) in self.each():
            for kind, coords, _kw in c.items:
                with self.subTest(glyph=name, kind=kind):
                    self.assertGreaterEqual(min(coords[0::2]), x1 - 1e-9)
                    self.assertLessEqual(max(coords[0::2]), x2 + 1e-9)
                    self.assertGreaterEqual(min(coords[1::2]), y1 - 1e-9)
                    self.assertLessEqual(max(coords[1::2]), y2 + 1e-9)

    def test_one_stroke_weight_unless_the_call_site_says_otherwise(self):
        for name, c, _box in self.each():
            for kind, _coords, kw in c.items:
                if "width" not in kw:  # the dots, which are fills
                    continue
                with self.subTest(glyph=name, kind=kind):
                    self.assertEqual(kw["width"], glyphs.STROKE)
        for name, kw in GLYPHS:
            c = Recording()
            kind = name.partition("-")[0]
            fn = getattr(glyphs, kind)
            args = (c, X, Y, "#ABCDEF")
            if kind == "mode":
                args += (name.partition("-")[2],)
            fn(*args, size=SIZE, width=3.0, **kw)
            widths = {it[2]["width"] for it in c.items if "width" in it[2]}
            with self.subTest(glyph=name):
                self.assertEqual(widths, {3.0})

    def test_the_colour_is_the_caller_s_and_nothing_else(self):
        """Colour is not decided in `glyphs.py`. The shipped row's gold gear and
        the four hues of the command marks were settled arguments — "This is
        what you build this is what you promise" — and a drawing module that
        reached for one of its own would be quietly relitigating them."""
        for name, c, _box in self.each():
            for kind, _coords, kw in c.items:
                colours = {kw.get(k) for k in ("fill", "outline")} - {None, ""}
                with self.subTest(glyph=name, kind=kind):
                    self.assertEqual(colours, {"#ABCDEF"})

    def test_the_size_scales_the_whole_drawing(self):
        """One drawing at every size the two surfaces ask for — 14 px for the
        shipped row's icons, 16 for its command marks, 11-14 for the compact
        panel's. Doubling the box doubles every offset from the anchor.

        Except the dots, which are the size of the *stroke* and not of the box:
        a 32 px agent with a 1.5 px stroke has 1.5 px eyes, because the rule
        they live under is "no bigger than the stroke" and a dot that grew with
        the box would be a filled circle with a case for itself.
        """
        for name, kw in GLYPHS:
            small, large = Recording(), Recording()
            kind, _, variant = name.partition("-")
            fn = getattr(glyphs, kind)
            for c, size in ((small, 16.0), (large, 32.0)):
                args = (c, 0.0, 0.0, "#ABCDEF")
                if kind == "mode":
                    args += (variant,)
                fn(*args, size=size, **kw)
            with self.subTest(glyph=name):
                self.assertEqual(len(small.items), len(large.items))
                for (_k, a, akw), (_k2, b, _kw2) in zip(small.items,
                                                        large.items):
                    if akw.get("fill") and _k != "line":
                        continue  # a dot: sized by the stroke, not by the box
                    for one, two in zip(a, b):
                        self.assertAlmostEqual(two, one * 2, places=6)


class TestTheVariantsAddRatherThanReplace(unittest.TestCase):
    """"Off" has to be legible without remembering what "on" looked like."""

    @staticmethod
    def count(name, **kw) -> dict:
        c = Recording()
        draw(name, c, **kw)
        out = {}
        for kind, _coords, _kw in c.items:
            out[kind] = out.get(kind, 0) + 1
        return out

    def test_the_mics_slash_is_one_more_line_over_the_same_mic(self):
        plain, slashed = self.count("mic"), self.count("mic", slash=True)
        self.assertEqual(slashed["line"], plain["line"] + 1)
        self.assertEqual(slashed["arc"], plain["arc"])

    def test_the_speakers_mute_is_one_more_line_and_no_waves(self):
        # The slash takes the waves' place rather than the speaker's: an icon
        # that disappears when a setting is off is a setting nobody can find
        # their way back to.
        loud, quiet = self.count("speaker"), self.count("speaker", muted=True)
        self.assertEqual(quiet["line"], loud["line"] + 1)
        self.assertEqual(loud.get("arc"), 2)
        self.assertEqual(quiet.get("arc", 0), 0)


class TestTheModeGlyphReadsTheName(unittest.TestCase):
    def test_each_mode_is_its_own_mark(self):
        drawings = {}
        for name in glyphs.MODES:
            c = Recording()
            glyphs.mode(c, 0, 0, "#ABCDEF", name, size=16.0)
            drawings[name] = [(kind, tuple(coords)) for kind, coords, _kw
                              in c.items]
        self.assertEqual(len(drawings), 3)
        for a in glyphs.MODES:
            for b in glyphs.MODES:
                if a < b:
                    self.assertNotEqual(drawings[a], drawings[b], (a, b))

    def test_a_fourth_mode_raises_rather_than_drawing_the_third(self):
        # `mode != DICTATE` drew converse's bubble over refine, which pastes —
        # the defect the third mode was not supposed to introduce silently. A
        # fourth is a decision, not whichever branch happens to be last.
        with self.assertRaises(ValueError):
            glyphs.mode(Recording(), 0, 0, "#ABCDEF", "translate")


class TestTheTwoSurfacesShareTheDrawings(unittest.TestCase):
    """The point of the module: the same call, from both files."""

    def test_the_shipped_marks_are_these_marks(self):
        from flow import ui
        for wrapper, glyph in ((ui._glyph_refine, glyphs.refine),
                               (ui._glyph_continue, glyphs.continue_),
                               (ui._glyph_edit, glyphs.edit),
                               (ui._glyph_command, glyphs.command),
                               (ui._glyph_cancel, glyphs.cancel),
                               (ui._glyph_take, glyphs.take),
                               (ui._glyph_copy, glyphs.copy),
                               (ui._glyph_new, glyphs.new),
                               (ui._glyph_send, glyphs.send),
                               (ui._glyph_agent, glyphs.agent)):
            with self.subTest(mark=wrapper.__name__):
                direct, wrapped = Recording(), Recording()
                glyph(direct, 3.0, 4.0, "#ABCDEF", size=ui.MARK_GLYPH,
                      tags=("t",))
                wrapper(wrapped, 3.0, 4.0, "#ABCDEF", ("t",))
                self.assertEqual(direct.items, wrapped.items)

    def test_the_compact_mic_and_the_shipped_mic_are_one_drawing(self):
        # The whole complaint, in one assertion: the shipped row filled an oval
        # for its capsule and the compact surface stroked one, and nobody had
        # ever decided that they should differ.
        from flow import ui, ui_compact
        shipped, compact = Recording(), Recording()
        p = ui_compact.CompactPill.__new__(ui_compact.CompactPill)
        p.paint = compact
        p._mic_gone = False
        p._meter_level = 0.0
        p._glyph_tint = lambda: "#ABCDEF"
        p._draw_face(compact, 0, ui_compact.BARS)
        glyphs.mic(shipped, ui_compact.MIC_X, ui_compact.MIC_Y, "#ABCDEF")
        self.assertTrue(shipped.items)
        self.assertEqual(shipped.items, compact.items[:len(shipped.items)])
        # And the shipped surface reaches for the same function.
        self.assertIs(ui.glyphs, glyphs)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
