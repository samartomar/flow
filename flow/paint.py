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
#: Cardinal-spline tension. Tk's `smooth=True` polygon is a Bezier through the
#: midpoints of the control polygon; GDI+'s closed cardinal spline at the
#: default 0.5 is the same curve to within a fraction of a pixel, which is what
#: makes `_round_rect` render as itself rather than as an approximation.
_TENSION = 0.5


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


def available() -> bool:
    """Whether this machine can present a layered window at all.

    Reported rather than assumed, the discipline `_no_activate` keeps for its
    own style. False is not a failure — it is a Mac, a Linux desktop, or a
    machine whose GDI+ would not start — and the caller draws on the real
    canvas instead.
    """
    return _start() is not None


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

    def __init__(self, w: int, h: int, alpha: float = 1.0) -> None:
        # Started here rather than left to the caller. `painter_for` happens
        # to ask `available()` first, but an invariant that holds because of
        # the order two functions are written in is not an invariant — and the
        # failure is an `AttributeError` on a None module handle, several
        # calls away from the cause.
        if _start() is None:
            raise OSError("GDI+ is not available on this machine")
        self._buf = self._bitmap = self._g = None
        self._w = self._h = 0
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
        self._fmt = ctypes.c_void_p()
        _gdiplus.GdipStringFormatGetGenericTypographic(ctypes.byref(self._fmt))
        fmt = ctypes.c_void_p()
        _gdiplus.GdipCloneStringFormat(self._fmt, ctypes.byref(fmt))
        # 0x800 is MeasureTrailingSpaces: without it a label ending in a space
        # measures as though it did not.
        flags = ctypes.c_int()
        _gdiplus.GdipGetStringFormatFlags(fmt, ctypes.byref(flags))
        _gdiplus.GdipSetStringFormatFlags(fmt, flags.value | 0x800)
        self._fmt = fmt
        #: Whether the style has been put into the per-pixel-alpha mode. A
        #: hint, not a fact — `present` re-takes it if a frame is refused.
        self._took_over = False
        self.resize(w, h)

    # -- lifecycle ---------------------------------------------------------

    def resize(self, w: int, h: int) -> None:
        w, h = max(1, int(w)), max(1, int(h))
        if (w, h) == (self._w, self._h):
            return
        self._release()
        self._w, self._h = w, h
        self._buf = ctypes.create_string_buffer(w * h * 4)
        bitmap = ctypes.c_void_p()
        _gdiplus.GdipCreateBitmapFromScan0(w, h, w * 4, _PARGB, self._buf,
                                           ctypes.byref(bitmap))
        g = ctypes.c_void_p()
        _gdiplus.GdipGetImageGraphicsContext(bitmap, ctypes.byref(g))
        _gdiplus.GdipSetSmoothingMode(g, _SMOOTH_AA)
        _gdiplus.GdipSetPixelOffsetMode(g, _OFFSET_HQ)
        _gdiplus.GdipSetTextRenderingHint(g, _TEXT_AA)
        self._bitmap, self._g = bitmap, g

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
        if self._fmt is not None:
            _gdiplus.GdipDeleteStringFormat(self._fmt)
            self._fmt = None

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

    def _stroke_path(self, path, colour, width) -> None:
        pen = ctypes.c_void_p()
        # Unit 2 is Pixel: a 1 px hairline stays 1 px whatever DPI awareness
        # the process ends up with.
        _gdiplus.GdipCreatePen1(ctypes.c_uint(_argb(colour)),
                                ctypes.c_float(width), 2, ctypes.byref(pen))
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
        arr = self._floats(pts)
        if kw.get("smooth"):
            _gdiplus.GdipAddPathClosedCurve2(path, arr, len(pts),
                                             ctypes.c_float(_TENSION))
        else:
            _gdiplus.GdipAddPathLine2(path, arr, len(pts))
            _gdiplus.GdipClosePathFigure(path)
        if kw.get("fill"):
            self._fill_path(path, kw["fill"])
        if kw.get("outline"):
            self._stroke_path(path, kw["outline"], kw.get("width", 1))
        _gdiplus.GdipDeletePath(path)

    def create_line(self, *args, **kw) -> None:
        pts = _points(args)
        if len(pts) < 2:
            return
        path = ctypes.c_void_p()
        _gdiplus.GdipCreatePath(0, ctypes.byref(path))
        _gdiplus.GdipAddPathLine2(path, self._floats(pts), len(pts))
        self._stroke_path(path, kw.get("fill", "#000000"), kw.get("width", 1))
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
        tl, tr, br, bl = (r, r, r, r) if isinstance(r, (int, float))             else tuple(r)
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
            self._stroke_path(path, kw["outline"], kw.get("width", 1))
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
            self._stroke_path(path, kw["outline"], kw.get("width", 1))
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
            self._stroke_path(path, kw["outline"], kw.get("width", 1))
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
        family, size = spec[0], abs(spec[1])
        style = 0
        if len(spec) > 2:
            style |= _STYLE_BOLD if "bold" in spec[2] else 0
            style |= _STYLE_ITALIC if "italic" in spec[2] else 0
        fam = ctypes.c_void_p()
        if _gdiplus.GdipCreateFontFamilyFromName(ctypes.c_wchar_p(family), None,
                                                 ctypes.byref(fam)) != 0:
            # An absent family is a fact about the machine, not something to
            # raise inside a repaint: Tk substitutes silently, and so does
            # this — but into the UI font rather than into whatever GDI+ would
            # have picked.
            _gdiplus.GdipCreateFontFamilyFromName(
                ctypes.c_wchar_p("Segoe UI"), None, ctypes.byref(fam))
        font = ctypes.c_void_p()
        # Unit 2 is Pixel, so a Tk `-13` is thirteen pixels here too.
        _gdiplus.GdipCreateFont(fam, ctypes.c_float(size), style, 2,
                                ctypes.byref(font))
        self._fonts[spec] = (fam, font)
        return fam, font

    def measure(self, text: str, spec) -> tuple:
        """`(width, height)` of `text` in `spec`, in pixels."""
        _fam, font = self._font(spec)
        layout, box = _RectF(0, 0, 8192, 512), _RectF()
        _gdiplus.GdipMeasureString(self._g, ctypes.c_wchar_p(text), -1, font,
                                   ctypes.byref(layout), self._fmt,
                                   ctypes.byref(box), None, None)
        return box.w, box.h

    def create_text(self, x, y, **kw) -> None:
        text = kw.get("text", "")
        if not text:
            return
        spec = kw.get("font") or ("Segoe UI", -12)
        _fam, font = self._font(spec)
        w, h = self.measure(text, spec)
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
        # A hair of slack on the layout box: GDI+ will wrap a string that
        # measures a rounding error wider than the rectangle it is given, and
        # a wrapped label in a fixed row is a label with its tail cut off.
        layout = _RectF(tx, ty, w + 4, h + 2)
        _gdiplus.GdipDrawString(self._g, ctypes.c_wchar_p(text), -1, font,
                                ctypes.byref(layout), self._fmt, brush)
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
        bi.biWidth, bi.biHeight = self._w, -self._h  # negative: top-down
        bi.biPlanes, bi.biBitCount, bi.biCompression = 1, 32, 0
        bits = ctypes.c_void_p()
        hbmp = _gdi32.CreateDIBSection(memdc, ctypes.byref(bi), 0,
                                       ctypes.byref(bits), None, 0)
        ctypes.memmove(bits, self._buf, self._w * self._h * 4)
        old = _gdi32.SelectObject(memdc, hbmp)
        size = wintypes.SIZE(self._w, self._h)
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


def painter_for(canvas, w: int, h: int, lite: bool, alpha: float = 1.0):
    """What this window should draw on: a `GdiCanvas`, or the canvas itself.

    Lite draws on the canvas, and deliberately: Lite is the mode that asks
    nothing of the platform, and a layered window is the largest ask this
    surface makes of it.
    """
    if not lite and available():
        try:
            return GdiCanvas(w, h, alpha)
        except (AttributeError, OSError, ValueError):
            # A machine that has GDI+ but would not give us a bitmap. The
            # canvas still draws; it just draws Tk's stairs.
            pass
    return canvas
