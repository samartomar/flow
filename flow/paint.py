"""An antialiased stand-in for `tk.Canvas`, presented with per-pixel alpha.

`design/compact/` is drawn in a browser, and a browser antialiases. Tk 8.6's
canvas does not — every curve it draws is a hard-edged stair — and the windows
this app puts on screen are colour-keyed (`-transparentcolor`), which makes
transparency **binary**: a pixel is either wholly the pill or wholly
see-through, so the silhouette has no partial coverage available to be smooth
with. Beside the artboard the difference is not subtle, and it is not a paint
bug that can be fixed by drawing more carefully. It is the window.

`GdiCanvas` is the answer: the same drawing calls, rendered by GDI+ into a
premultiplied BGRA bitmap and handed to `UpdateLayeredWindow`, which is
Windows' per-pixel-alpha presentation path. The window keeps its handle, its
styles and its Tk event bindings; what changes is that the desktop composites
our bitmap instead of showing what Tk painted.

**It deliberately wears `tk.Canvas`'s own vocabulary** — `create_line`,
`create_polygon`, `create_arc`, `create_text`, `delete` — rather than a
vocabulary of its own. The drawing code in `ui_compact.py` is already a display
list written in those calls; making the painter speak them means the surface is
drawn by one body of code whichever backend renders it, and it means the real
`tk.Canvas` is the fallback rather than something that has to be kept in step
with one. On a Mac, on Linux, and in Lite, `painter_for` hands back the canvas
itself and every line of drawing code is unchanged.

No new dependency: `ctypes` and `gdiplus.dll` are both already on the machine,
and R16's three-package install is untouched.
"""

from __future__ import annotations

import ctypes
import os
import sys
import tkinter as tk
from ctypes import wintypes

_GWL_EXSTYLE = -20
_WS_EX_LAYERED = 0x00080000
_ULW_ALPHA = 0x02
_AC_SRC_OVER, _AC_SRC_ALPHA = 0x00, 0x01
#: PixelFormat32bppPARGB. Premultiplied, which is what `UpdateLayeredWindow`
#: consumes — handing it plain ARGB gives a dark fringe everywhere the alpha is
#: partial, and on an antialiased edge that is every pixel that matters.
_PARGB = 0xE200B
#: SmoothingModeAntiAlias, PixelOffsetModeHighQuality, and
#: TextRenderingHintAntiAliasGridFit: the three settings this module exists for.
_SMOOTH_AA, _OFFSET_HQ, _TEXT_AA = 4, 2, 3
#: GDI+ font styles, and the two Tk spellings that map onto them.
_STYLE_BOLD, _STYLE_ITALIC = 1, 2
#: GDI+'s `UnitPixel`: what a pen width and a font size are given in here.
_UNIT_PIXEL = 2
#: Pixels per point at 96 dpi, which is how a Tk **positive** font size is
#: turned into the design pixels this canvas draws in — see `_font`.
_PX_PER_POINT = 96.0 / 72.0
#: What stands in for a family the machine does not have. Both are shipped with
#: Windows, and the split is load-bearing rather than tidy: a monospaced family
#: replaced by a proportional one breaks every caller that positions glyphs on
#: a fixed pitch, which on this surface is the status label.
_MONO_HINT = "mono"
_MONO_FALLBACK, _UI_FALLBACK = "Consolas", "Segoe UI"
#: Steps per span when flattening Tk's smoothing. Twelve puts the error well
#: under a pixel at the radii this app draws and costs nothing worth counting.
_SMOOTH_STEPS = 12


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
                ("SourceConstantAlpha", ctypes.c_byte),
                ("AlphaFormat", ctypes.c_byte)]


class _GdiplusStartupInput(ctypes.Structure):
    _fields_ = [("GdiplusVersion", ctypes.c_uint32),
                ("DebugEventCallback", ctypes.c_void_p),
                ("SuppressBackgroundThread", ctypes.c_int),
                ("SuppressExternalCodecs", ctypes.c_int)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class _RectF(ctypes.Structure):
    _fields_ = [("x", ctypes.c_float), ("y", ctypes.c_float),
                ("w", ctypes.c_float), ("h", ctypes.c_float)]


_user32 = _gdi32 = _gdiplus = None
_token = None


def _start():
    """Load the libraries and start GDI+ once. The token, or None."""
    global _user32, _gdi32, _gdiplus, _token
    if _token is not None:
        return _token
    if sys.platform != "win32":
        return None
    try:
        # `use_last_error` so a refusal can say why: without it
        # `GetLastError` reads whatever some later call left behind,
        # which is how a failing `UpdateLayeredWindow` reported
        # success-with-error-0 and looked like nothing at all.
        _user32 = ctypes.WinDLL('user32', use_last_error=True)
        _gdi32 = ctypes.windll.gdi32
        _gdiplus = ctypes.windll.gdiplus
        token = ctypes.c_void_p()
        inp = _GdiplusStartupInput(1, None, 0, 0)
        if _gdiplus.GdiplusStartup(ctypes.byref(token), ctypes.byref(inp),
                                   None) != 0:
            return None
    except (AttributeError, OSError):
        return None
    _token = token
    return _token


#: `DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2`. The context, not the older
#: `SetProcessDpiAwareness` enum: v2 is the one that also scales the non-client
#: area and keeps child windows in step on a DPI change.
_PER_MONITOR_V2 = -4


def make_dpi_aware() -> bool:
    """Tell Windows this process draws in real pixels. True if it took.

    Must run **before any window exists** — awareness is fixed for the process
    the moment the first one is created, and after that this is a no-op that
    reports failure.

    Until this is called, a process is *DPI-unaware*: on a 300 % display
    Windows tells it the screen is a third of its real size, lets it draw a
    third-size image, and stretches the result by three with a bilinear
    filter. Everything Flow drew was arriving on screen as an upscaled
    thumbnail of itself — which is most of what "it does not look clean" was,
    far more than any antialiasing.

    Reported rather than assumed, and false is survivable: a Windows too old
    for the v2 context, or a process something else already declared for, goes
    on drawing at `scale_for` = 1 exactly as before.
    """
    if sys.platform != "win32":
        return False
    try:
        user32 = ctypes.windll.user32
        fn = user32.SetProcessDpiAwarenessContext
        # The context is a `DPI_AWARENESS_CONTEXT` — a pointer-sized handle
        # whose values happen to be small negative numbers. Declared, because
        # ctypes defaults an int argument to 32 bits: on 64-bit Windows the
        # -4 arrived as a truncated handle the call did not recognise, and it
        # answered False with nothing to say about why.
        fn.argtypes = [ctypes.c_void_p]
        fn.restype = ctypes.c_int
        return bool(fn(ctypes.c_void_p(_PER_MONITOR_V2)))
    except (AttributeError, OSError):
        return False


def scale_for(win) -> float:
    """How many device pixels a design pixel is worth on `win`'s monitor.

    1.0 on a plain display, 3.0 on the 300 % one this was written against, and
    1.0 whenever the answer cannot be had — including every DPI-unaware
    process, where Windows is doing the scaling itself and a second factor on
    top would square it.
    """
    if sys.platform != "win32":
        return 1.0
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetAncestor(win.winfo_id(), 2)
        dpi = user32.GetDpiForWindow(hwnd)
    except (AttributeError, OSError):
        return 1.0
    return (dpi / 96.0) if dpi else 1.0


def available() -> bool:
    """Whether this machine can present a layered window at all.

    Reported rather than assumed, the discipline `_no_activate` keeps for its
    own style. False is not a failure — it is a Mac, a Linux desktop, or a
    machine whose GDI+ would not start — and the caller draws on the real
    canvas instead.
    """
    return _start() is not None


#: GDI+'s copy of the bundled type, and the files already in it.
#:
#: `ui._load_fonts` registers the five IBM Plex files with
#: `AddFontResourceExW(FR_PRIVATE)`, which GDI and Tk both honour — and GDI+
#: does not. Measured here: after that registration
#: `GdipCreateFontFamilyFromName("IBM Plex Sans", None, …)` answers 14,
#: FontFamilyNotFound, and so do "IBM Plex Mono" and "IBM Plex Sans Medm". So
#: every string this module drew fell to the stand-ins below, and the compact
#: surface was composited in Segoe UI and Consolas — the whole surface in a
#: typeface the canvas it is drawn from has never seen.
#:
#: A private collection is GDI+'s own answer to the same question, and it
#: resolves the same GDI-truncated names `flow/ui.py` already spells
#: (`FONT_SANS_MEDIUM` is "IBM Plex Sans Medm"), so nothing downstream changes.
#: Never released: GDI+ frees a private collection at `GdiplusShutdown`, which
#: this module never calls — the process ends and the whole of GDI+ goes with
#: it, exactly as `_token` does.
_collection = None
_font_files: set = set()


def load_fonts(paths) -> int:
    """Put font files into GDI+'s private collection. How many went in.

    Idempotent: a path already added is skipped, so this can be called from a
    module import that runs more than once without growing the collection.
    Nothing here raises. A file that is missing, or that GDI+ refuses, is
    skipped and not counted — a font is a fact about the machine, and a
    machine that is short one is not a reason for a repaint to fail. `_font`
    already substitutes like for like for whatever did not arrive.
    """
    global _collection
    if _start() is None:
        return 0
    added = 0
    for path in paths:
        try:
            path = str(path)
            if path in _font_files or not os.path.isfile(path):
                continue
            if _collection is None:
                coll = ctypes.c_void_p()
                if _gdiplus.GdipNewPrivateFontCollection(
                        ctypes.byref(coll)) != 0:
                    return added
                _collection = coll
            if _gdiplus.GdipPrivateAddFontFile(_collection,
                                               ctypes.c_wchar_p(path)) != 0:
                continue
        except (AttributeError, OSError, TypeError, ValueError):
            continue
        _font_files.add(path)
        added += 1
    return added


def _family(name: str, out) -> int:
    """Resolve `name` to a GDI+ font family in `out`. 0 when it took.

    The private collection first and the installed one second, because the
    families this app names live in the private one and the fallbacks
    (Consolas, Segoe UI) live in the installed one — asked the other way round,
    a machine that happens to have some *other* "IBM Plex Sans" installed would
    beat the file we shipped.
    """
    if _collection is not None:
        if _gdiplus.GdipCreateFontFamilyFromName(ctypes.c_wchar_p(name),
                                                 _collection, out) == 0:
            return 0
    return _gdiplus.GdipCreateFontFamilyFromName(ctypes.c_wchar_p(name), None,
                                                 out)


def _argb(colour: str, alpha=255) -> int:
    """A Tk colour as the 0xAARRGGBB integer GDI+ takes.

    Only `#rrggbb` is understood, which is every colour this app names: the
    palette is written as hex constants in one place precisely so a colour
    cannot be spelled two ways. A name Tk would resolve ("white") raises here
    rather than being guessed at.
    """
    c = colour.lstrip("#")
    if len(c) != 6:
        raise ValueError(f"not a #rrggbb colour: {colour!r}")
    return (alpha << 24) | int(c, 16)


def _points(args) -> list:
    """Tk's several ways of spelling a point list, as `[(x, y), ...]`.

    `create_line(x1, y1, x2, y2)`, `create_line([x1, y1, x2, y2])` and
    `create_line([(x1, y1), (x2, y2)])` are all legal Tk and all appear in this
    app, so all three arrive here.
    """
    if len(args) == 1:
        args = args[0]
    flat = []
    for a in args:
        if isinstance(a, (tuple, list)):
            flat.extend(a)
        else:
            flat.append(a)
    return [(flat[i], flat[i + 1]) for i in range(0, len(flat) - 1, 2)]


def _tk_smooth(pts, closed=True, steps: int = _SMOOTH_STEPS) -> list:
    """Tk's `smooth=True` curve through `pts`, flattened to a point list.

    Tk draws a smoothed polygon as a chain of **quadratic Beziers whose ends
    are the midpoints of consecutive control-point segments** and whose control
    point is the vertex between them. That is a quadratic B-spline, and it
    pulls *inside* the control polygon.

    GDI+'s own `AddPathClosedCurve` is a cardinal spline, which passes
    *through* the control points and bulges outside them. Substituting one for
    the other renders the same twelve points as two different shapes: it took
    the radius off every corner of the shipped pill, and ballooned the compact
    panel's Send chip out of its row. So the curve is computed here rather
    than delegated, and every `_round_rect` in this app — both surfaces — comes
    out as the shape Tk would have drawn.
    """
    n = len(pts)
    if n < 3:
        return list(pts)
    out = []
    span = range(n) if closed else range(1, n - 1)
    for i in span:
        p0, p1, p2 = pts[(i - 1) % n], pts[i], pts[(i + 1) % n]
        start = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
        end = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
        for s in range(steps + 1):
            t = s / steps
            u = 1 - t
            out.append((u * u * start[0] + 2 * u * t * p1[0] + t * t * end[0],
                        u * u * start[1] + 2 * u * t * p1[1] + t * t * end[1]))
    return out


class GdiCanvas:
    """`tk.Canvas`'s drawing calls, rendered antialiased and composited whole.

    One per window, resized with it. Nothing is on screen until `present`,
    which is also why this surface cannot flicker: the frame is handed over
    complete rather than painted in front of the user.
    """

    #: What the caller can ask to tell the two backends apart. A real
    #: `tk.Canvas` has no such attribute, so `getattr(c, "antialiased", False)`
    #: is the honest question.
    antialiased = True

    def __init__(self, w: int, h: int, alpha: float = 1.0,
                 scale: float = 1.0) -> None:
        # Started here rather than left to the caller. `painter_for` happens
        # to ask `available()` first, but an invariant that holds because of
        # the order two functions are written in is not an invariant — and the
        # failure is an `AttributeError` on a None module handle, several
        # calls away from the cause.
        if _start() is None:
            raise OSError("GDI+ is not available on this machine")
        self._buf = self._bitmap = self._g = None
        self._w = self._h = 0
        #: Device pixels per design pixel. Every drawing call stays in the
        #: units `design/compact/gen.py` is written in; the bitmap is this much
        #: larger and a world transform does the rest, so a 120x34 capsule on a
        #: 300 % display is rendered as 360x102 real pixels rather than drawn
        #: small and stretched by the compositor.
        self.scale = max(0.1, float(scale))
        self._fonts: dict = {}
        #: The window-wide opacity, as `-alpha` used to carry it. It moves
        #: here because the two cannot coexist — see `present` — and this is
        #: where `BLENDFUNCTION.SourceConstantAlpha` already means exactly it.
        self.constant_alpha = max(0, min(255, round(alpha * 255)))
        #: The string format both `measure` and `create_text` use. GDI+'s
        #: default adds roughly a sixth of an em of padding either side of a
        #: run and reports it in the measurement, so a caller that measures a
        #: prefix to place something over the text — the palette's `.hit`
        #: tint — lands progressively further off with every character. The
        #: generic typographic format has no such padding, and using the same
        #: one for both calls is what makes them agree.
        generic = ctypes.c_void_p()
        _gdiplus.GdipStringFormatGetGenericTypographic(ctypes.byref(generic))
        # 0x800 is MeasureTrailingSpaces: without it a label ending in a
        # space measures as though it did not. 0x1000 is NoWrap, and it is not
        # optional for a label: GDI+ breaks a string that measures a rounding
        # error wider than the rectangle it is given, and a single-line label
        # in a fixed row has nowhere to break to — it came out as
        # "LI STENI NG".
        #
        # **Two formats, because `tk.Canvas` has two kinds of string.** A
        # `create_text` with no `width` is a label and may never wrap; one
        # *with* a width is a wrap column, and the shipped surface's draft,
        # note, partial and answer are all written that way. Composited under
        # the label format they ran off the side of the panel in one line, so
        # the wrapping one is what a width selects — see `create_text`.
        self._fmt, self._fmt_wrap = None, None
        for name, extra in (("_fmt", 0x800 | 0x1000), ("_fmt_wrap", 0x800)):
            fmt = ctypes.c_void_p()
            _gdiplus.GdipCloneStringFormat(generic, ctypes.byref(fmt))
            flags = ctypes.c_int()
            _gdiplus.GdipGetStringFormatFlags(fmt, ctypes.byref(flags))
            _gdiplus.GdipSetStringFormatFlags(fmt, flags.value | extra)
            setattr(self, name, fmt)
        # `generic` is GDI+'s own cached object, not ours: it is cloned from
        # and never deleted, which is what the single-format version did too.
        #: Whether the style has been put into the per-pixel-alpha mode. A
        #: hint, not a fact — `present` re-takes it if a frame is refused.
        self._took_over = False
        self.resize(w, h)

    # -- lifecycle ---------------------------------------------------------

    def resize(self, w: int, h: int) -> None:
        """Size the bitmap for a window `w` x `h` **design** pixels across."""
        w, h = max(1, int(w)), max(1, int(h))
        if (w, h) == (self._w, self._h):
            return
        self._release()
        self._w, self._h = w, h
        pw, ph = self.device_size
        self._buf = ctypes.create_string_buffer(pw * ph * 4)
        bitmap = ctypes.c_void_p()
        _gdiplus.GdipCreateBitmapFromScan0(pw, ph, pw * 4, _PARGB, self._buf,
                                           ctypes.byref(bitmap))
        g = ctypes.c_void_p()
        _gdiplus.GdipGetImageGraphicsContext(bitmap, ctypes.byref(g))
        # The whole of the DPI story, in one call: the caller keeps drawing in
        # design pixels and GDI+ lays them down at device resolution. Curves
        # are re-tessellated at the larger size and glyphs are hinted for it,
        # which is the difference between a sharp pill and a magnified one.
        if self.scale != 1.0:
            _gdiplus.GdipScaleWorldTransform(g, ctypes.c_float(self.scale),
                                             ctypes.c_float(self.scale), 0)
        _gdiplus.GdipSetSmoothingMode(g, _SMOOTH_AA)
        _gdiplus.GdipSetPixelOffsetMode(g, _OFFSET_HQ)
        _gdiplus.GdipSetTextRenderingHint(g, _TEXT_AA)
        self._bitmap, self._g = bitmap, g

    @property
    def device_size(self) -> tuple:
        """The bitmap's real size in device pixels, which is what Windows is
        handed and what the window must be sized to."""
        return (max(1, round(self._w * self.scale)),
                max(1, round(self._h * self.scale)))

    def _release(self) -> None:
        for handle, drop in ((self._g, "GdipDeleteGraphics"),
                             (self._bitmap, "GdipDisposeImage")):
            if handle is not None:
                getattr(_gdiplus, drop)(handle)
        self._g = self._bitmap = None

    def close(self) -> None:
        self._release()
        for fam, font in self._fonts.values():
            _gdiplus.GdipDeleteFont(font)
            _gdiplus.GdipDeleteFontFamily(fam)
        self._fonts.clear()
        for name in ("_fmt", "_fmt_wrap"):
            fmt = getattr(self, name, None)
            if fmt is not None:
                _gdiplus.GdipDeleteStringFormat(fmt)
                setattr(self, name, None)

    def offset(self, dx: float, dy: float):
        """Draw at `(dx, dy)` until the returned token is passed to `restore`.

        One window here holds several canvases — the pill row, the draft
        panel, the conversation card — each `place`d at its own y. The bitmap
        covers the whole window, so each canvas's display list is replayed
        under its own translation; without it, compositing the pill alone
        blanked everything the other canvases had drawn.
        """
        state = ctypes.c_uint()
        _gdiplus.GdipSaveGraphics(self._g, ctypes.byref(state))
        _gdiplus.GdipTranslateWorldTransform(self._g, ctypes.c_float(dx),
                                             ctypes.c_float(dy), 0)
        return state

    def restore(self, state) -> None:
        _gdiplus.GdipRestoreGraphics(self._g, state)

    def delete(self, *_a, **_kw) -> None:
        """`delete("all")` — back to fully transparent.

        Every pixel a frame does not draw is a pixel the desktop shows
        through, which is the whole difference from a keyed window: there is
        no background colour standing in for "nothing here".
        """
        _gdiplus.GdipGraphicsClear(self._g, ctypes.c_uint(0))

    # -- the primitives ----------------------------------------------------

    def _fill_path(self, path, colour) -> None:
        brush = ctypes.c_void_p()
        _gdiplus.GdipCreateSolidFill(ctypes.c_uint(_argb(colour)),
                                     ctypes.byref(brush))
        _gdiplus.GdipFillPath(self._g, brush, path)
        _gdiplus.GdipDeleteBrush(brush)

    def _stroke_path(self, path, colour, width=None) -> None:
        """Trace `path` in `colour`, `width` **design** pixels wide.

        Unit 2 is Pixel, which is a width in *device* pixels that the world
        transform does not touch — measured here rather than assumed: at
        `scale` 3, pens of 1, 1.5 and 2 all rendered the same two device rows.
        So every stroke on a 300 % display came out a third of its weight, and
        `glyphs.STROKE` — 1.5, whose own docstring says it should land as
        "four or five pixels on the owner's 300 % display" — drew a hairline.

        Converted here, and to exactly the rule `ScaledCanvas` keeps for the
        Tk path so the two backends draw the same picture: **an explicit width
        is a design length and scales; an absent one is Tk's own default and
        is one device pixel.** That split is not tidiness — `_panel_chrome`'s
        three hairlines are drawn without a width on purpose, and they are
        hairlines at every scale, while a glyph's stroke is part of the
        drawing and grows with it.
        """
        pen = ctypes.c_void_p()
        w = 1.0 if width is None else float(width) * self.scale
        _gdiplus.GdipCreatePen1(ctypes.c_uint(_argb(colour)),
                                ctypes.c_float(w), 2, ctypes.byref(pen))
        _gdiplus.GdipDrawPath(self._g, pen, path)
        _gdiplus.GdipDeletePen(pen)

    @staticmethod
    def _floats(pts):
        arr = (ctypes.c_float * (len(pts) * 2))()
        for i, (x, y) in enumerate(pts):
            arr[i * 2], arr[i * 2 + 1] = x, y
        return arr

    def create_polygon(self, *args, **kw) -> None:
        pts = _points(args)
        path = ctypes.c_void_p()
        _gdiplus.GdipCreatePath(0, ctypes.byref(path))
        if kw.get("smooth"):
            pts = _tk_smooth(pts, closed=True)
        arr = self._floats(pts)
        _gdiplus.GdipAddPathLine2(path, arr, len(pts))
        _gdiplus.GdipClosePathFigure(path)
        if kw.get("fill"):
            self._fill_path(path, kw["fill"])
        if kw.get("outline"):
            self._stroke_path(path, kw["outline"], kw.get("width"))
        _gdiplus.GdipDeletePath(path)

    def create_line(self, *args, **kw) -> None:
        pts = _points(args)
        if len(pts) < 2:
            return
        path = ctypes.c_void_p()
        _gdiplus.GdipCreatePath(0, ctypes.byref(path))
        _gdiplus.GdipAddPathLine2(path, self._floats(pts), len(pts))
        self._stroke_path(path, kw.get("fill", "#000000"), kw.get("width"))
        _gdiplus.GdipDeletePath(path)

    def round_rect(self, x1, y1, x2, y2, r, **kw) -> None:
        """A rounded rectangle from true quarter-circles.

        `_round_rect` in `ui_compact` reaches for this when its target has it,
        and falls back to Tk's smoothed polygon when it does not. The polygon
        is not good enough here: Tk's `smooth=True` is a B-spline that pulls
        *inside* its control points, GDI+'s closed cardinal spline pushes
        outside them, and on a 26 px chip at radius 13 the difference is a
        Send button visibly ballooning out of its own row.

        `r` takes the shapes `_round_rect` takes: one radius, or a
        `(tl, tr, br, bl)` mix for a surface that squares off on a seam.
        """
        tl, tr, br, bl = ((r, r, r, r) if isinstance(r, (int, float))
                          else tuple(r))
        path = ctypes.c_void_p()
        _gdiplus.GdipCreatePath(0, ctypes.byref(path))
        f = ctypes.c_float
        corners = ((x1, y1, tl, 180), (x2 - 2 * tr, y1, tr, 270),
                   (x2 - 2 * br, y2 - 2 * br, br, 0), (x1, y2 - 2 * bl, bl, 90))
        prev = None
        for cx, cy, rad, start in corners:
            if rad <= 0:
                # A corner with no radius is a point, and an arc of diameter
                # zero is a GDI+ error rather than a corner. Which point it is
                # depends on which corner asked.
                pt = {180: (x1, y1), 270: (x2, y1),
                      0: (x2, y2), 90: (x1, y2)}[start]
                if prev is not None:
                    arr = (ctypes.c_float * 4)(prev[0], prev[1], pt[0], pt[1])
                    _gdiplus.GdipAddPathLine2(path, arr, 2)
                prev = pt
                continue
            _gdiplus.GdipAddPathArc(path, f(cx), f(cy), f(2 * rad), f(2 * rad),
                                    f(start), f(90))
            prev = None
        _gdiplus.GdipClosePathFigure(path)
        if kw.get("fill"):
            self._fill_path(path, kw["fill"])
        if kw.get("outline"):
            self._stroke_path(path, kw["outline"], kw.get("width"))
        _gdiplus.GdipDeletePath(path)

    def create_rectangle(self, x1, y1, x2, y2, **kw) -> None:
        self.create_polygon((x1, y1), (x2, y1), (x2, y2), (x1, y2), **kw)

    def create_oval(self, x1, y1, x2, y2, **kw) -> None:
        path = ctypes.c_void_p()
        _gdiplus.GdipCreatePath(0, ctypes.byref(path))
        f = ctypes.c_float
        _gdiplus.GdipAddPathEllipse(path, f(x1), f(y1), f(x2 - x1), f(y2 - y1))
        if kw.get("fill"):
            self._fill_path(path, kw["fill"])
        if kw.get("outline"):
            self._stroke_path(path, kw["outline"], kw.get("width"))
        _gdiplus.GdipDeletePath(path)

    def create_arc(self, x1, y1, x2, y2, **kw) -> None:
        path = ctypes.c_void_p()
        _gdiplus.GdipCreatePath(0, ctypes.byref(path))
        f = ctypes.c_float
        # Tk measures angles anticlockwise from three o'clock; GDI+ measures
        # them clockwise from the same place. Every angle in this app is
        # written the way Tk takes it, so the conversion belongs here and not
        # at the forty call sites.
        _gdiplus.GdipAddPathArc(path, f(x1), f(y1), f(x2 - x1), f(y2 - y1),
                                f(-kw.get("start", 0)),
                                f(-kw.get("extent", 90)))
        if kw.get("style") == tk.PIESLICE and kw.get("fill"):
            _gdiplus.GdipClosePathFigure(path)
            self._fill_path(path, kw["fill"])
        if kw.get("outline"):
            self._stroke_path(path, kw["outline"], kw.get("width"))
        _gdiplus.GdipDeletePath(path)

    # -- text --------------------------------------------------------------

    def _font(self, spec):
        """A GDI+ font for a Tk font tuple `(family, -pixels[, style])`, kept.

        Cached because building one asks GDI+ for family metrics, and a frame
        draws a dozen strings from three or four fonts.
        """
        spec = tuple(spec)
        got = self._fonts.get(spec)
        if got is not None:
            return got
        family, size = spec[0], spec[1]
        # Tk spells a **pixel** size as a negative number and a **point** size
        # as a positive one, and both are used here: the panels are drawn in
        # pixel sizes (`FONT_BODY` is `-14`), the Help sheet and the chip
        # labels in points. A point taken for a pixel is three-quarters of the
        # size it should be, which photographed as a whole Help sheet at
        # three-quarters of its height.
        #
        # Converted here rather than handed to GDI+'s own `UnitPoint`, and that
        # is measured rather than assumed: under `UnitPoint` an 11 pt face came
        # back **three times** too large, because GDI+ resolves points against
        # the graphics' dpi *and* the world transform, and this canvas already
        # carries the display scale in that transform. 96/72 design pixels per
        # point is the same arithmetic Tk's own `tk scaling` does — 1.333
        # unaware, 3.996 measured at 300 % aware, against 96 * 3 / 72 — so the
        # two backends put the same glyphs in the same box.
        size = abs(size) if size < 0 else size * _PX_PER_POINT
        style = 0
        if len(spec) > 2:
            style |= _STYLE_BOLD if "bold" in spec[2] else 0
            style |= _STYLE_ITALIC if "italic" in spec[2] else 0
        fam = ctypes.c_void_p()
        if _family(family, ctypes.byref(fam)) != 0:
            # An absent family is a fact about the machine, not something to
            # raise inside a repaint: Tk substitutes silently and so does this.
            #
            # Absent from *both* collections, now: `load_fonts` puts the
            # bundled faces where GDI+ can see them, and `_family` asks there
            # first — without which this branch was taken by every string on
            # the surface, because `FR_PRIVATE` is invisible to GDI+.
            #
            # **Like for like, though.** None of the IBM Plex faces this app
            # names are installed here, and substituting a monospaced one with
            # a proportional one is not a cosmetic difference: `_bar_label`
            # places every character itself at a fixed 7 px pitch, because Tk
            # has no letter-spacing. Under a proportional fallback the narrow
            # glyphs left holes and the wide ones closed up, and LISTENING
            # rendered as "LI STENI NG".
            stand_in = (_MONO_FALLBACK if _MONO_HINT in family.lower()
                        else _UI_FALLBACK)
            _gdiplus.GdipCreateFontFamilyFromName(
                ctypes.c_wchar_p(stand_in), None, ctypes.byref(fam))
        font = ctypes.c_void_p()
        _gdiplus.GdipCreateFont(fam, ctypes.c_float(size), style, _UNIT_PIXEL,
                                ctypes.byref(font))
        self._fonts[spec] = (fam, font)
        return fam, font

    def measure(self, text: str, spec, width=None) -> tuple:
        """`(width, height)` of `text` in `spec`, in pixels.

        `width` is `create_text`'s wrap column: given one, the string is
        measured as it will be *drawn* — broken across lines inside that
        column — which is what makes the box a wrapped paragraph occupies
        agree with the box it is laid out in.
        """
        _fam, font = self._font(spec)
        wrap = width is not None and width > 0
        layout = _RectF(0, 0, float(width) if wrap else 8192.0,
                        8192.0 if wrap else 512.0)
        box = _RectF()
        _gdiplus.GdipMeasureString(self._g, ctypes.c_wchar_p(text), -1, font,
                                   ctypes.byref(layout),
                                   self._fmt_wrap if wrap else self._fmt,
                                   ctypes.byref(box), None, None)
        return box.w, box.h

    def create_text(self, x, y, **kw) -> None:
        text = kw.get("text", "")
        if not text:
            return
        spec = kw.get("font") or ("Segoe UI", -12)
        _fam, font = self._font(spec)
        # Tk's `width` on a text item is a **wrap column**, and this app writes
        # its paragraphs with one: the draft, the note, the partial and the
        # card's answer all pass `BUBBLE_W - 2 * PAD`. Measured and drawn in
        # that column, so a wrapped paragraph occupies the box the layout
        # above it reserved rather than running off the side in one line.
        wrap = kw.get("width")
        wrap = (float(wrap) if isinstance(wrap, (int, float)) and wrap > 0
                else None)
        w, h = self.measure(text, spec, wrap)
        # Tk's anchors, because every call site is written in them: "w" is the
        # left edge on the vertical centre, "nw" the top-left corner, "e" the
        # right edge, and "center" — the default — is centred both ways.
        #
        # Tested for as whole words, not as substrings. "center" *contains*
        # both "n" and "e", so a substring test reads Tk's default as
        # top-anchored and right-anchored at once, which is why Send's label
        # sat below and left of the chip it belongs in.
        anchor = kw.get("anchor", "center")
        sides = set() if anchor in ("center", "centre") else set(anchor)
        tx = x if "w" in sides else (x - w if "e" in sides else x - w / 2)
        ty = y if "n" in sides else (y - h if "s" in sides else y - h / 2)
        brush = ctypes.c_void_p()
        _gdiplus.GdipCreateSolidFill(ctypes.c_uint(_argb(kw.get("fill",
                                                                "#FFFFFF"))),
                                     ctypes.byref(brush))
        # Generous slack as well as NoWrap: the flag stops the break, and the
        # room stops the last glyph being clipped by a rounding error. A
        # wrapped string keeps its column exactly — the slack is what it would
        # break *into*, and a paragraph two pixels wider than its layout is a
        # different set of line breaks from the one Tk measured.
        layout = _RectF(tx, ty, wrap if wrap else w + 8, h + 4)
        _gdiplus.GdipDrawString(self._g, ctypes.c_wchar_p(text), -1, font,
                                ctypes.byref(layout),
                                self._fmt_wrap if wrap else self._fmt, brush)
        _gdiplus.GdipDeleteBrush(brush)

    # -- presentation ------------------------------------------------------

    def present(self, win, at=None) -> bool:
        """Composite this frame onto the desktop under `win`'s handle.

        `WS_EX_LAYERED` is set here rather than at construction because a Tk
        window exists before it is mapped, and the style has to go on the
        handle that is actually on screen. Everything else about the window —
        its geometry, `WS_EX_NOACTIVATE`, its Tk bindings — is untouched: this
        replaces what Windows paints in it, not what it is.
        """
        hwnd = _user32.GetAncestor(win.winfo_id(), 2)  # GA_ROOT
        if not self._took_over:
            self._take_over(hwnd)
            self._took_over = True
        screen = _user32.GetDC(0)
        memdc = _gdi32.CreateCompatibleDC(screen)
        bi = _BITMAPINFOHEADER()
        bi.biSize = ctypes.sizeof(bi)
        pw, ph = self.device_size
        bi.biWidth, bi.biHeight = pw, -ph  # negative: top-down
        bi.biPlanes, bi.biBitCount, bi.biCompression = 1, 32, 0
        bits = ctypes.c_void_p()
        hbmp = _gdi32.CreateDIBSection(memdc, ctypes.byref(bi), 0,
                                       ctypes.byref(bits), None, 0)
        ctypes.memmove(bits, self._buf, pw * ph * 4)
        old = _gdi32.SelectObject(memdc, hbmp)
        size = wintypes.SIZE(pw, ph)
        src = wintypes.POINT(0, 0)
        # `at` when the caller knows where the window is going, because
        # `winfo_*` lags a `geometry` call by a frame or two — the same
        # staleness `_open_box` records for its own anchor, and the reason a
        # box presented at open composited itself somewhere off screen.
        dst = wintypes.POINT(*(at if at is not None
                               else (win.winfo_rootx(), win.winfo_rooty())))
        blend = _BLENDFUNCTION(_AC_SRC_OVER, 0, self.constant_alpha,
                               _AC_SRC_ALPHA)
        ok = _user32.UpdateLayeredWindow(hwnd, screen, ctypes.byref(dst),
                                         ctypes.byref(size), memdc,
                                         ctypes.byref(src), 0,
                                         ctypes.byref(blend), _ULW_ALPHA)
        if not ok:
            # A layered window keeps whichever of the two modes it was put in
            # first, and Tk re-applies `-alpha` when it *maps* a window — so a
            # takeover done before the window was on screen is undone by the
            # mapping, and every present after it is refused. Retried rather
            # than cached, because "has Tk touched this window since?" is not
            # a question with a stable answer: a box is built, presented and
            # mapped in that order, which is exactly the case that failed.
            self._take_over(hwnd)
            ok = _user32.UpdateLayeredWindow(hwnd, screen, ctypes.byref(dst),
                                             ctypes.byref(size), memdc,
                                             ctypes.byref(src), 0,
                                             ctypes.byref(blend), _ULW_ALPHA)
        _gdi32.SelectObject(memdc, old)
        _gdi32.DeleteObject(hbmp)
        _gdi32.DeleteDC(memdc)
        _user32.ReleaseDC(0, screen)
        return bool(ok)

    @staticmethod
    def _take_over(hwnd) -> None:
        """Put the window into the per-pixel-alpha mode, whatever it was in.

        Tk's `-alpha` calls `SetLayeredWindowAttributes`, which is the *other*
        layered mode, and a window in that mode refuses `UpdateLayeredWindow`
        outright — it photographed as the key colour standing in a solid
        rectangle where the pill should be. Clearing `WS_EX_LAYERED` and
        setting it again is what resets the choice. The opacity `-alpha` was
        carrying is not lost: it is `constant_alpha`, on the blend.
        """
        ex = _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        _user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, ex & ~_WS_EX_LAYERED)
        _user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, ex | _WS_EX_LAYERED)


class TeeCanvas:
    """Every drawing call to the real `tk.Canvas` *and* to a `GdiCanvas`.

    `ui_compact` could simply swap its canvas for a `GdiCanvas`, because it
    hit-tests with explicit rectangles. `ui.py` cannot: it hit-tests through
    canvas *items* — eighteen `tag_bind` sites plus item-based hover tooltips —
    and a bitmap has no items to bind to. Rewriting that interaction layer
    across 7 400 lines is the port this avoids.

    So the real canvas stays, invisible under the composited bitmap, and keeps
    every item it ever had: `tag_bind`, `tag_raise`, `find_withtag` and the
    tooltips all work exactly as they did, because they are still talking to
    the same widget. What is added is a **retained display list** — every
    create is recorded, every delete forgets, and `present` replays the whole
    list into GDI+ and composites it.

    Retained rather than forwarded, and that is forced: two of this app's four
    canvases repaint *partially* (`delete("body")`, `delete("chips")`), so
    the items a frame does not touch have to survive somewhere the bitmap can
    be rebuilt from. A `GdiCanvas` keeps no items, so this keeps them for it.

    Anything not a drawing call — `pack`, `bind`, `winfo_*`, `tag_bind` —
    falls through to the real canvas untouched.
    """

    #: The calls that put something on screen, and so into the display list.
    _DRAWS = ("create_line", "create_rectangle", "create_polygon",
              "create_oval", "create_arc", "create_text", "create_window",
              "create_image")

    antialiased = True

    def __init__(self, canvas, gdi) -> None:
        self._c = canvas
        self._gdi = gdi
        #: Whether anything has been drawn or deleted since the last present.
        #: The canvases sharing a window redraw on their own schedule — the
        #: draft panel repaints when the draft changes, which is not when the
        #: pill's own key changes — so the compositor cannot key off the pill
        #: alone. It composited the row and left the panel off the bitmap.
        self.dirty = True
        #: `(item_id, tags, method, args, kwargs)` in z-order — the order Tk
        #: itself stacks them in, kept in step by `tag_raise` / `tag_lower`.
        self._items: list = []

    def __getattr__(self, name):
        # Everything this class does not itself define is the real canvas's.
        return getattr(self._c, name)

    def _record(self, method, a, kw):
        item = getattr(self._c, method)(*a, **kw)
        tags = kw.get("tags") or ()
        if isinstance(tags, str):
            tags = (tags,)
        self._items.append((item, tuple(tags), method, a, dict(kw)))
        self.dirty = True
        return item

    def __init_subclass__(cls, **kw):  # pragma: no cover - not subclassed
        super().__init_subclass__(**kw)

    def delete(self, *tags) -> None:
        self._c.delete(*tags)
        self.dirty = True
        if not tags or "all" in tags:
            self._items.clear()
            return
        wanted = set(tags)
        self._items = [it for it in self._items
                       if it[0] not in wanted and not (set(it[1]) & wanted)]

    def _matching(self, spec) -> list:
        return [it for it in self._items
                if it[0] == spec or spec in it[1]]

    def tag_raise(self, spec, above=None) -> None:
        self._c.tag_raise(spec) if above is None else self._c.tag_raise(spec,
                                                                       above)
        moved = self._matching(spec)
        if not moved:
            return
        rest = [it for it in self._items if it not in moved]
        if above is None:
            self._items = rest + moved
            return
        at = max((i for i, it in enumerate(rest)
                  if it[0] == above or above in it[1]), default=len(rest) - 1)
        self._items = rest[:at + 1] + moved + rest[at + 1:]

    def tag_lower(self, spec, below=None) -> None:
        self._c.tag_lower(spec) if below is None else self._c.tag_lower(spec,
                                                                       below)
        moved = self._matching(spec)
        if not moved:
            return
        rest = [it for it in self._items if it not in moved]
        if below is None:
            self._items = moved + rest
            return
        at = min((i for i, it in enumerate(rest)
                  if it[0] == below or below in it[1]), default=0)
        self._items = rest[:at] + moved + rest[at:]

    def measure(self, text: str, spec, width=None) -> tuple:
        return (self._gdi.measure(text, spec, width) if self._gdi
                else (0, 0))

    @property
    def constant_alpha(self) -> int:
        """The window-wide opacity, 0-255, as `BLENDFUNCTION` carries it.

        Forwarded rather than reached through, because this is where
        `-alpha` went: `flow/ui.py`'s idle dim writes it every time the
        fade moves, and a caller holding `tee._gdi` to do that would be
        holding the one thing a `recorder` does not have. 255 without a
        painter, which is what "no window-wide fade" means.
        """
        return self._gdi.constant_alpha if self._gdi is not None else 255

    @constant_alpha.setter
    def constant_alpha(self, value: int) -> None:
        if self._gdi is not None:
            self._gdi.constant_alpha = max(0, min(255, int(value)))

    def resize(self, w: int, h: int) -> None:
        if self._gdi:
            self._gdi.resize(w, h)

    def close(self) -> None:
        if self._gdi:
            self._gdi.close()

    def replay(self, gdi) -> None:
        """Draw this canvas's display list into `gdi`, in z-order."""
        for _item, _tags, method, a, kw in self._items:
            draw = getattr(gdi, method, None)
            if draw is None:
                # `create_window` and `create_image` have no GDI+ equivalent
                # here; nothing in this app draws either onto a composited
                # canvas, and a missing one is a gap to see rather than an
                # exception raised inside a repaint.
                continue
            try:
                draw(*a, **kw)
            except Exception:
                continue

    def present(self, win, at=None, others=(), at_self=None) -> bool:
        """Composite this canvas — and any `others` — as one bitmap.

        `others` is `(tee, dx, dy)` for every other canvas sharing this
        window, drawn under its own translation and *before* this one, which
        is the stacking Tk gives them: the panel is placed above the pill row
        and the row is the window's foot.

        `at_self` is this canvas's own translation, for the case the shipped
        surface is: the canvas that owns the bitmap is **not** the one at the
        window's origin. `flow/ui.py`'s pill row is `place`d at
        `y = h - PILL_H` with the panel band above it, and the row is what
        holds the painter — so the alternative would have been to composite
        from whichever panel happened to be up, which is a different object
        on every frame and none at all when the row is alone.
        """
        self._gdi.delete("all")
        for tee, dx, dy in others:
            token = self._gdi.offset(dx, dy)
            try:
                tee.replay(self._gdi)
            finally:
                self._gdi.restore(token)
        if at_self and tuple(at_self) != (0, 0):
            token = self._gdi.offset(*at_self)
            try:
                self.replay(self._gdi)
            finally:
                self._gdi.restore(token)
        else:
            self.replay(self._gdi)
        self.dirty = False
        for tee, _dx, _dy in others:
            tee.dirty = False
        return self._gdi.present(win, at)


def recorder(canvas):
    """A `TeeCanvas` that records and forwards but owns no bitmap.

    For the canvases that share a window with the one doing the compositing:
    they need their display list kept so the compositor can replay it, and
    they have nothing of their own to present.
    """
    return TeeCanvas(canvas, None)


def _tee_draw(method):
    def call(self, *a, **kw):
        return self._record(method, a, kw)
    call.__name__ = method
    return call


for _m in TeeCanvas._DRAWS:
    setattr(TeeCanvas, _m, _tee_draw(_m))


def scale_font(spec, k: float):
    """A Tk font spec `k` times as large — for the sizes that are in pixels.

    Tk spells a **pixel** size as a negative number and a **point** size as a
    positive one, and only the first needs help. A point is a physical unit, so
    Tk's own `tk scaling` already carries it: measured here on the 300 % display,
    `tk scaling` is 3.996 once the process is DPI-aware against 1.333 while it
    is not, and an 11 pt face comes back with a 60 px linespace against 15 px
    for the 13 px one beside it. Scaling a point size here as well would square
    the factor.

    Anything that is not a `(family, size, ...)` sequence — a named font, a
    plain family string, a font object — is returned untouched: it either
    carries no number to scale or is not this function's to interpret.
    """
    if not isinstance(spec, (tuple, list)) or len(spec) < 2:
        return spec
    size = spec[1]
    if not isinstance(size, (int, float)) or isinstance(size, bool) or size >= 0:
        return spec
    return (spec[0], -round(-size * k), *spec[2:])


def _scale_coords(value, k: float):
    """Tk's several spellings of a point list, each `k` times further out.

    `create_line(x1, y1, x2, y2)`, `create_line([x1, y1, x2, y2])` and
    `create_line([(x1, y1), (x2, y2)])` are all legal Tk and all appear in this
    app — `_points` says so for the painter — so the shape is preserved rather
    than normalised: what Tk was handed is what Tk is handed.
    """
    if isinstance(value, (list, tuple)):
        return type(value)(_scale_coords(v, k) for v in value)
    return value * k


class ScaledCanvas:
    """A `tk.Canvas` addressed in design pixels and drawn in device ones.

    `flow/ui_compact.py` converts at the point a number meets Tk, because it
    has a few dozen such points. `flow/ui.py` has some hundreds — every
    `create_line`, every radius, every wrap column across 7 500 lines — and
    converting them one at a time is a change nobody could review and a rule
    the next drawing call would forget. So the conversion moves to the seam
    they all pass through: the canvas itself.

    Every coordinate, every `width` (a stroke on a line, an outline on a box, a
    wrap column on a string, a box on an embedded widget — one name, four jobs,
    all of them pixels), every `height` and every pixel-sized `font` is
    multiplied on the way in; `bbox` and `coords` are divided on the way back,
    so a probe that measures text answers in the units the layout is written
    in. Anything else — `tag_bind`, `tag_raise`, `delete`, `bind`, `winfo_*`,
    `pack` — is the real canvas's and is forwarded untouched.

    **Hit-testing keeps working, and that is the reason this is a proxy rather
    than a rewrite.** The items are real Tk items at real device coordinates,
    which is where the mouse is, so the eighteen `tag_bind` sites and the
    item-based hover tooltips go on meaning what they meant. `TeeCanvas` next
    door exists for the same reason and pays a much larger cost for it.

    At `k = 1` it is transparent, and `ui.py` does not wrap at all there — so a
    100 % display, a Mac, and every test that builds a real Tk canvas run
    exactly the code they ran before.
    """

    #: The calls that take coordinates. `create_bitmap` is absent because
    #: nothing in this app draws one; it would fall through `__getattr__`
    #: unscaled, which is a gap to notice rather than a wrong picture.
    _DRAWS = ("create_line", "create_rectangle", "create_polygon",
              "create_oval", "create_arc", "create_text", "create_window",
              "create_image")

    #: Item options that are lengths. `height` is only ever an embedded
    #: window's or the widget's own; `width` is the four jobs above.
    _LENGTHS = ("width", "height")

    #: `place`'s lengths. The `rel*` family is a fraction of the parent and
    #: must not be touched; `bordermode` and `anchor` are words.
    _PLACE_LENGTHS = ("x", "y", "width", "height")

    def __init__(self, canvas, k: float) -> None:
        self._c = canvas
        self._k = float(k)

    def __getattr__(self, name):
        # Everything this class does not define is the real canvas's. `_c` and
        # `_k` are named so an instance whose `__init__` has not run raises
        # `AttributeError` rather than recursing here forever.
        if name in ("_c", "_k"):
            raise AttributeError(name)
        return getattr(self._c, name)

    # -- in ----------------------------------------------------------------

    def _coords(self, args) -> tuple:
        return tuple(_scale_coords(a, self._k) for a in args)

    def _options(self, kw: dict) -> dict:
        if not kw:
            return kw
        out = dict(kw)
        for name in self._LENGTHS:
            value = out.get(name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                out[name] = value * self._k
        if "font" in out:
            out["font"] = scale_font(out["font"], self._k)
        return out

    @staticmethod
    def _merged(cnf, kw):
        """`cnf` and `kw` as one dict, or `None` for a query.

        Tk's `configure` is also its getter: a bare call answers with every
        option and a *string* `cnf` answers with one. Neither has a length in
        it to scale, and both would break on a dict unpacking, so they go
        straight through.
        """
        if cnf is not None and not isinstance(cnf, dict):
            return None
        return {**(cnf or {}), **kw}

    def itemconfigure(self, item, cnf=None, **kw):
        merged = self._merged(cnf, kw)
        if merged is None:
            return self._c.itemconfigure(item, cnf, **kw)
        return self._c.itemconfigure(item, **self._options(merged))

    itemconfig = itemconfigure

    def configure(self, cnf=None, **kw):
        merged = self._merged(cnf, kw)
        if merged is None:
            return self._c.configure(cnf, **kw)
        return self._c.configure(**self._options(merged))

    config = configure

    def place(self, cnf=None, **kw):
        merged = self._merged(cnf, kw)
        if merged is None:
            return self._c.place(cnf, **kw)
        k = self._k
        for name in self._PLACE_LENGTHS:
            value = merged.get(name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                merged[name] = round(value * k)
        return self._c.place(**merged)

    place_configure = place

    def move(self, item, dx, dy):
        return self._c.move(item, dx * self._k, dy * self._k)

    # -- out ---------------------------------------------------------------

    def bbox(self, *args):
        got = self._c.bbox(*args)
        if got is None:
            return None
        return tuple(v / self._k for v in got)

    def coords(self, item, *new):
        if new:
            return self._c.coords(item, *self._coords(new))
        return [v / self._k for v in self._c.coords(item)]


def _scaled_draw(method):
    def call(self, *a, **kw):
        return getattr(self._c, method)(*self._coords(a), **self._options(kw))
    call.__name__ = method
    return call


for _m in ScaledCanvas._DRAWS:
    setattr(ScaledCanvas, _m, _scaled_draw(_m))


def unkey(win) -> None:
    """Take a window off the colour key and off Tk's own alpha.

    Both are answers to the question `GdiCanvas` is now answering, and both
    get in its way. `-transparentcolor` keys a colour out of whatever is
    painted, so the surface's own background would be punched out of the
    bitmap we just antialiased; `-alpha` puts the window into
    `SetLayeredWindowAttributes` mode, and a window in that mode refuses
    `UpdateLayeredWindow` outright. The opacity `-alpha` carried is not lost:
    it moves to the blend's `SourceConstantAlpha`.

    Neither attribute exists off Windows, and neither is worth an exception:
    this only runs where `available()` has already said yes.
    """
    for attr, value in (("-transparentcolor", ""), ("-alpha", 1.0)):
        try:
            win.attributes(attr, value)
        except tk.TclError:
            pass


def painter_for(canvas, w: int, h: int, lite: bool, alpha: float = 1.0,
                scale: float = 1.0, tee: bool = False):
    """What this window should draw on: a `GdiCanvas`, or the canvas itself.

    Lite draws on the canvas, and deliberately: Lite is the mode that asks
    nothing of the platform, and a layered window is the largest ask this
    surface makes of it.

    `tee` wraps the pair in a `TeeCanvas` instead of replacing the canvas —
    what `ui.py` needs, because its hit-testing lives on canvas items that
    have to go on existing. `ui_compact` does not need it and does not pay
    for it.
    """
    if not lite and available():
        try:
            gdi = GdiCanvas(w, h, alpha, scale)
            return TeeCanvas(canvas, gdi) if tee else gdi
        except (AttributeError, OSError, ValueError):
            # A machine that has GDI+ but would not give us a bitmap. The
            # canvas still draws; it just draws Tk's stairs.
            pass
    return canvas
