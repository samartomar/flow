"""Draw Flow's icon — the pill's level bars ending in a text cursor — into the files Flow
ships: `flow/assets/flow.ico` (the tray, the windows, the .exe) and `flow/assets/flow.svg`
(the same drawing, for anything that scales).

Chosen by the owner on 2026-09-23 from four sketches ("level to cursor"): it is what Flow
does — the meter the pill shows while it hears you, turning into a caret where the words
land — and it stays readable at the tray's 16 px, where the others blurred.

    uv run python scripts/make_icon.py            # write both files
    uv run python scripts/make_icon.py --check    # exit 1 if they would change

No image library: numpy (already a dependency) and the stdlib. Each shape is a rounded
rectangle, rasterised by supersampling its signed distance, and composited in order.
**Not one drawing scaled.** From 40 px up the 64-unit drawing scales cleanly; at the
sizes the tray and the taskbar use — 16, 20, 24 and 32 px — its bars land between pixels
and smear, so each of those is laid out again on whole pixels (`PIXEL`).

**BMP inside the icon for every size but 256, PNG for 256** — the layout every Windows
reader accepts, Tk's `iconbitmap` included, which parses the file itself.
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
ICO = ROOT / "flow" / "assets" / "flow.ico"
SVG = ROOT / "flow" / "assets" / "flow.svg"

#: The pill's own colours (flow/ui.py): the shell, the text white, Ask's violet.
SHELL = "#1A1D23"
BAR = "#E6E8ED"
CARET = "#B48EF5"

#: (x, y, width, height, radius, colour) on a 64-unit square — the drawing the sketch was.
LARGE = (
    (0, 0, 64, 64, 14, SHELL),
    (11, 26, 6, 12, 3, BAR),
    (21, 18, 6, 28, 3, BAR),
    (31, 23, 6, 18, 3, BAR),
    (45, 12, 6, 40, 3, CARET),
)

#: The drawing again, laid out in whole pixels, for the sizes Windows actually shows it
#: at in the tray and on the taskbar — 16, 20, 24 and 32 px are 100%, 125%, 150% and
#: 200% display scaling. Scaled from 64 units, their bars land between pixels and smear.
PIXEL = {
    16: (
        (0, 0, 16, 16, 3.5, SHELL),
        (2, 6, 2, 4, 1, BAR),
        (5, 4, 2, 8, 1, BAR),
        (8, 5, 2, 6, 1, BAR),
        (12, 2, 2, 12, 1, CARET),
    ),
    20: (
        (0, 0, 20, 20, 4.5, SHELL),
        (3, 8, 2, 4, 1, BAR),
        (7, 5, 2, 10, 1, BAR),
        (11, 7, 2, 6, 1, BAR),
        (15, 3, 2, 14, 1, CARET),
    ),
    24: (
        (0, 0, 24, 24, 5, SHELL),
        (3, 9, 3, 6, 1.5, BAR),
        (7, 6, 3, 12, 1.5, BAR),
        (11, 8, 3, 8, 1.5, BAR),
        (18, 3, 3, 18, 1.5, CARET),
    ),
    32: (
        (0, 0, 32, 32, 7, SHELL),
        (6, 13, 3, 6, 1.5, BAR),
        (11, 9, 3, 14, 1.5, BAR),
        (16, 11, 3, 10, 1.5, BAR),
        (23, 6, 3, 20, 1.5, CARET),
    ),
}

SIZES = (16, 20, 24, 32, 40, 48, 64, 256)

#: Samples per pixel along each axis.
SUPERSAMPLE = 8


def _rgb(colour: str) -> np.ndarray:
    return np.array([int(colour[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float64) / 255


def _coverage(size: int, unit: float, x, y, w, h, r) -> np.ndarray:
    """How much of each pixel a rounded rectangle covers, 0..1."""
    n = SUPERSAMPLE
    ticks = (np.arange(size * n) + 0.5) / n  # sample centres, in pixels
    px, py = np.meshgrid(ticks, ticks)
    cx, cy = (x + w / 2) * unit, (y + h / 2) * unit
    bx, by, rr = w / 2 * unit, h / 2 * unit, r * unit
    qx = np.abs(px - cx) - (bx - rr)
    qy = np.abs(py - cy) - (by - rr)
    outside = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0))
    inside = np.minimum(np.maximum(qx, qy), 0)
    hit = (outside + inside - rr) <= 0
    return hit.reshape(size, n, size, n).mean(axis=(1, 3))


def render(size: int) -> np.ndarray:
    """The icon at `size` px, as straight-alpha RGBA uint8, rows top to bottom."""
    shapes, unit = (PIXEL[size], 1.0) if size in PIXEL else (LARGE, size / 64)
    rgb = np.zeros((size, size, 3))  # premultiplied
    alpha = np.zeros((size, size))
    for x, y, w, h, r, colour in shapes:
        cov = _coverage(size, unit, x, y, w, h, r)
        rgb = _rgb(colour) * cov[..., None] + rgb * (1 - cov[..., None])
        alpha = cov + alpha * (1 - cov)
    straight = np.where(alpha[..., None] > 0, rgb / np.maximum(alpha[..., None], 1e-9), 0)
    out = np.dstack([straight, alpha])
    return np.clip(np.round(out * 255), 0, 255).astype(np.uint8)


def png(pixels: np.ndarray) -> bytes:
    """RGBA rows as a PNG: filter 0 on every row, so a reader needs no unfiltering."""
    h, w, _ = pixels.shape

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    raw = b"".join(b"\x00" + pixels[row].tobytes() for row in range(h))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def dib(pixels: np.ndarray) -> bytes:
    """RGBA rows as an icon's BMP: a 32-bit BGRA image bottom-up, then an all-clear AND
    mask — the alpha channel is the transparency, the mask is only there because the
    format requires one."""
    h, w, _ = pixels.shape
    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    bgra = pixels[::-1][..., [2, 1, 0, 3]].tobytes()
    mask_row = ((w + 31) // 32) * 4
    return header + bgra + bytes(mask_row * h)


def ico(sizes=SIZES) -> bytes:
    images = []
    for size in sizes:
        pixels = render(size)
        images.append((size, png(pixels) if size >= 256 else dib(pixels)))
    out = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    for size, data in images:
        side = 0 if size >= 256 else size  # 0 means 256 in an icon directory
        out += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    return out + b"".join(data for _, data in images)


def svg() -> str:
    parts = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{c}"/>'
             for x, y, w, h, r, c in LARGE]
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" '
            'height="64">\n  <title>Flow</title>\n  ' + "\n  ".join(parts) + "\n</svg>\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the committed files differ from what this draws")
    args = ap.parse_args(argv)
    want = {ICO: ico(), SVG: svg().encode("utf-8")}
    if args.check:
        stale = [p for p, data in want.items() if not p.is_file() or p.read_bytes() != data]
        for p in stale:
            print(f"out of date: {p.relative_to(ROOT)}")
        return 1 if stale else 0
    for path, data in want.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f"wrote {path.relative_to(ROOT)} ({len(data):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
