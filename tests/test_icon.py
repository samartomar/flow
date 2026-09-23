"""Flow's icon: the pill's level bars ending in a text cursor (decisions.md 2026-09-23,
"Flow gets an icon").

Pinned: the file is what `scripts/make_icon.py` draws, it carries every size Windows asks
for, its small sizes really are the drawing (a violet caret, white bars, the dark shell,
clear corners), and every surface that shows an icon takes this one — the tray, the pill's
windows, Flow Home's page and its rail, and the .exe.
"""

import ctypes
import struct
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from flow import ICON  # noqa: E402

SIZES = {16, 20, 24, 32, 40, 48, 64, 256}


def entries(data: bytes) -> dict:
    """size -> (kind, bytes) for each image in an .ico."""
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    assert (reserved, kind) == (0, 1), "not an icon file"
    out = {}
    for i in range(count):
        w, h, _c, _r, _p, _b, size, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)
        side = w or 256
        blob = data[offset:offset + size]
        out[side] = ("png" if blob.startswith(b"\x89PNG") else "dib", blob)
    return out


def dib_pixel(blob: bytes, side: int, x: int, y: int) -> tuple:
    """RGBA of pixel (x, y), counted from the top left, in a 32-bit icon DIB."""
    header = struct.unpack_from("<IiiHH", blob, 0)
    assert header[0] == 40 and header[1] == side and header[2] == 2 * side
    assert header[4] == 32
    row = side - 1 - y  # stored bottom-up
    b, g, r, a = blob[40 + (row * side + x) * 4: 40 + (row * side + x) * 4 + 4]
    return r, g, b, a


class TestTheFileIsTheDrawing(unittest.TestCase):

    def test_it_is_what_the_script_draws(self):
        import make_icon

        self.assertEqual(make_icon.main(["--check"]), 0,
                         "flow/assets/flow.ico or flow.svg is out of date - run "
                         "scripts/make_icon.py")

    def test_every_size_windows_asks_for(self):
        found = entries(ICON.read_bytes())
        self.assertEqual(set(found), SIZES)

    def test_bmp_below_256_and_png_at_256(self):
        # The layout every Windows reader takes, Tk's `iconbitmap` included, which
        # parses the file itself.
        found = entries(ICON.read_bytes())
        for side, (kind, _blob) in found.items():
            with self.subTest(side=side):
                self.assertEqual(kind, "png" if side == 256 else "dib")

    def test_at_tray_size_it_is_bars_and_a_violet_caret(self):
        _kind, blob = entries(ICON.read_bytes())[16]
        caret = dib_pixel(blob, 16, 12, 8)
        bar = dib_pixel(blob, 16, 5, 8)
        shell = dib_pixel(blob, 16, 1, 8)
        corner = dib_pixel(blob, 16, 0, 0)
        self.assertEqual(caret, (0xB4, 0x8E, 0xF5, 255))
        self.assertEqual(bar, (0xE6, 0xE8, 0xED, 255))
        self.assertEqual(shell, (0x1A, 0x1D, 0x23, 255))
        self.assertEqual(corner[3], 0, "the rounded corner is clear")

    def test_the_small_sizes_are_drawn_on_whole_pixels(self):
        # A bar's edge on a whole pixel means no half-covered column beside it: every
        # pixel across a bar's middle row is either bar or shell, nothing in between.
        import make_icon

        for side in (16, 20, 24, 32):
            with self.subTest(side=side):
                px = make_icon.render(side)
                row = px[side // 2]
                colours = {tuple(p[:3]) for p in row if p[3] == 255}
                self.assertLessEqual(colours, {(0x1A, 0x1D, 0x23), (0xE6, 0xE8, 0xED),
                                               (0xB4, 0x8E, 0xF5)})


@unittest.skipUnless(sys.platform == "win32", "the tray is Windows only")
class TestTheTrayWearsIt(unittest.TestCase):

    def _tray(self):
        from flow import tray

        return tray, tray.Tray.__new__(tray.Tray)

    def test_it_loads_the_file_at_the_trays_own_size(self):
        tray, t = self._tray()
        t._hicon = 0
        fake = mock.Mock()
        fake.GetSystemMetrics.return_value = 24
        fake.LoadImageW.return_value = 0x1234
        with mock.patch.object(ctypes.windll, "user32", fake):
            handle = t._load_icon()
        self.assertEqual(handle, 0x1234)
        self.assertEqual(t._hicon, 0x1234)
        args = fake.LoadImageW.call_args.args
        self.assertEqual(args[1], str(ICON))
        self.assertEqual(args[3:], (24, 24, tray._LR_LOADFROMFILE))

    def test_the_stock_icon_is_still_the_fallback(self):
        tray, t = self._tray()
        t._hicon = 0
        fake = mock.Mock()
        fake.GetSystemMetrics.return_value = 16
        fake.LoadImageW.side_effect = [0, 0x77]
        with mock.patch.object(ctypes.windll, "user32", fake):
            handle = t._load_icon()
        self.assertEqual(handle, 0x77)
        self.assertEqual(t._hicon, 0, "a stock icon is not ours to destroy")
        self.assertEqual(fake.LoadImageW.call_args.args[-1], tray._LR_SHARED)


class TestEverySurfaceTakesIt(unittest.TestCase):

    def test_the_pills_set_it_on_their_windows(self):
        from flow import ui

        root = mock.Mock()
        ui.set_icon(root)
        root.iconbitmap.assert_called_once_with(default=str(ICON))

    def test_a_refused_icon_costs_the_icon_and_nothing_else(self):
        import tkinter as tk

        from flow import ui

        root = mock.Mock()
        root.iconbitmap.side_effect = tk.TclError("bitmap not defined")
        ui.set_icon(root)  # does not raise

    def test_both_pills_call_it(self):
        for name in ("ui.py", "ui_compact.py"):
            with self.subTest(name=name):
                src = (ROOT / "flow" / name).read_text(encoding="utf-8")
                self.assertIn("super().__init__()\n        set_icon(self)", src)

    def test_flow_home_serves_it_and_the_page_uses_it(self):
        from flow.home.server import FILES

        self.assertEqual(FILES["/flow.ico"], (ICON, "image/x-icon"))
        self.assertEqual(FILES["/flow.svg"][0], ICON.with_suffix(".svg"))
        static = ROOT / "flow" / "home" / "static"
        self.assertIn('<link rel="icon" href="/flow.ico">',
                      (static / "index.html").read_text(encoding="utf-8"))
        self.assertIn('url("/flow.svg")', (static / "app.css").read_text(encoding="utf-8"))

    def test_the_exe_is_built_with_it_and_ships_it(self):
        spec = (ROOT / "packaging" / "flow.spec").read_text(encoding="utf-8")
        self.assertIn('icon=os.path.join(ROOT, "flow", "assets", "flow.ico")', spec)
        self.assertIn('(os.path.join(ROOT, "flow", "assets", "flow.ico"), '
                      'os.path.join("flow", "assets"))', spec)


if __name__ == "__main__":
    unittest.main()
