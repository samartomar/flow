"""Everything I need to see about Flow on a Mac, in one PNG.

Diagnosing this platform from a Windows machine has cost several rounds of "send me a
photo, now send me the log, now run the other probe". This collapses that: it drives the
real windows, screenshots them, renders the numbers beside them, and writes **one image**
carrying both. One file to send back, and the geometry in it is pixel-exact rather than
a phone photo of a screen at an angle.

    uv run --with pillow python scripts/mac_report.py

Pillow is a `--with`, not a dependency, for `scripts/shots.py`'s reason: it is fetched
into the run and never enters the venv, so R16 still holds at three.

**macOS will ask for Screen Recording** the first time, because a screenshot of other
windows is what that permission governs. Grant it to the terminal and run again — the
capture comes back black otherwise, which the report says out loud rather than leaving
you to wonder why the picture is empty.

Three bands, top to bottom:

  **the numbers** - platform, Tk build, what each work-area method answers, where the
  stack is therefore placed, and whether the native engine is ready. This is the half
  a screenshot cannot carry and a log cannot show.

  **the whole screen** - scaled down, because the question "is it clear of the Dock and
  centred" is about where the window sits *in* the display, and a crop of the window
  cannot answer it. A neutral backdrop covers the desktop first, `scripts/shots.py`'s
  trick and for a second reason here: this image gets sent to somebody, and a full-screen
  capture of a working machine carries whatever happened to be open on it.

  **the stack, close up** - at full resolution, because "is there a title bar on it" is
  about a 22 px band that a scaled-down screen loses.
"""

import subprocess
import sys
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import flow.ui as ui  # noqa: E402
from ui_probe import FakeSession  # noqa: E402

OUT = Path.home() / "flow-mac-report.png"
PAD = 24
BG = (14, 16, 22)
FG = (230, 232, 238)
DIM = (150, 156, 170)
GOOD = (120, 210, 160)
BAD = (240, 140, 140)


def mono(size: int):
    """A real monospace if this machine has one, so the numbers line up in columns."""
    for path in ("/System/Library/Fonts/Menlo.ttc",
                 "/System/Library/Fonts/SFNSMono.ttf",
                 "C:/Windows/Fonts/consola.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def facts(pill) -> list[tuple[str, str, tuple]]:
    """(label, value, colour). Everything a round trip has had to ask for separately."""
    sw, sh = pill.winfo_screenwidth(), pill.winfo_screenheight()
    rows: list[tuple[str, str, tuple]] = []

    def row(label, value, colour=FG):
        rows.append((label, str(value), colour))

    row("platform", f"{sys.platform}   tk {tk.TkVersion}")
    row("python", sys.version.split()[0])
    row("screen (as Tk sees it)", f"{sw} x {sh}")
    row("", "")

    row("_work_area()", ui._work_area(sw, sh))
    measured = ui._tk_work_area(pill, sw, sh)
    whole = (0, 0, sw, sh)
    row("_tk_work_area()", measured,
        BAD if measured == whole else GOOD)
    if measured == whole:
        row("", "the maximise probe was refused or ignored;", DIM)
        row("", "falling back to the whole screen, so the Dock is not excluded", DIM)
    full, work = ui._pointer_monitor(sw, sh, pill)
    row("monitor full / work", f"{full}  /  {work}")
    row("", "")

    row("place setting", ui.PLACE)
    row("pill placed at", (pill.x, pill.y))
    row("pill size", f"{ui.PILL_W} x {ui.PILL_H}")
    bottom_gap = work[3] - (pill.y + ui.PILL_H)
    row("gap below the pill", f"{bottom_gap} px to the work-area bottom",
        GOOD if 0 <= bottom_gap <= 60 else BAD)
    centred = abs((pill.x + pill.pill_w / 2) - (full[0] + full[2]) / 2)
    row("off centre by", f"{centred:.0f} px",
        GOOD if centred < 4 else BAD)
    row("", "")

    row("engine", "macOS on-device speech" if _native_ready()[0] else "whisper")
    ok, why = _native_ready()
    row("native available", "yes" if ok else f"no - {why}", GOOD if ok else DIM)
    row("chord", "none off Windows; hold the pill instead", DIM)
    return rows


def _native_ready() -> tuple[bool, str]:
    try:
        from flow.native import available

        return available(compile_if_missing=False, timeout=10.0)
    except Exception as exc:  # pragma: no cover - a report must not die reporting
        return False, f"{type(exc).__name__}: {exc}"


def panel(rows, width: int) -> Image.Image:
    """The numbers, as an image, so they travel in the same file as the picture."""
    font = mono(20)
    line = 30
    img = Image.new("RGB", (width, PAD * 2 + line * (len(rows) + 1)), BG)
    d = ImageDraw.Draw(img)
    d.text((PAD, PAD), "flow - macOS report", font=mono(24), fill=FG)
    for i, (label, value, colour) in enumerate(rows, start=1):
        y = PAD + line * i
        d.text((PAD, y), label, font=font, fill=DIM)
        d.text((PAD + 380, y), value, font=font, fill=colour)
    return img


def grab():
    """The whole screen, and whether it came back black.

    A black capture is what macOS returns before Screen Recording is granted, and it
    looks exactly like a bug in Flow. Said out loud instead.
    """
    from PIL import ImageGrab

    img = ImageGrab.grab()
    extremes = img.convert("L").getextrema()
    return img, extremes[1] > 12


def stack_box(pill, ratio: float) -> tuple[int, int, int, int]:
    """The pill and whatever is docked to it, in capture pixels, and nothing else.

    Read off the windows rather than guessed at with a margin. The first version
    reserved 320 px above the pill for "whatever might be docked" and 60 below it, which
    on a real desktop cropped in the taskbar and cut the pill's own bottom edge off - and
    the bottom edge is exactly where a title bar or a broken dock seam would show.
    """
    top, bottom = pill.y, pill.y + ui.PILL_H
    for panel in (pill.bubble, pill.card):
        try:
            if not panel.winfo_ismapped():
                continue
            top = min(top, panel.winfo_rooty())
            bottom = max(bottom, panel.winfo_rooty() + panel.winfo_height())
        except tk.TclError:
            continue
    edge = 14
    box = (pill.x - edge, top - edge, pill.x + pill.pill_w + edge, bottom + edge)
    return tuple(int(v * ratio) for v in box)


def backdrop(pill) -> None:
    """Cover the desktop, so the report is a picture of Flow and not of the machine.

    `scripts/shots.py` does this to keep its captures clean. Here it is also a privacy
    line: the whole point of this file is that the image gets sent to somebody, and a
    full-screen grab of a working machine carries every window that happened to be open.

    Topmost and then lowered under the pill, which is the order that file found: a plain
    `lift()` is refused and the desktop shows through, so it has to outrank everything
    and then step back behind Flow's own windows.
    """
    back = tk.Toplevel(pill)
    back.overrideredirect(True)
    back.configure(bg="#23262b")
    back.geometry(f"{pill.winfo_screenwidth()}x{pill.winfo_screenheight()}+0+0")
    back.attributes("-topmost", True)
    back.update_idletasks()
    back.lower(pill)


def main() -> None:
    session = FakeSession()
    pill = ui.Pill(session)
    pill.armed = True
    backdrop(pill)

    def report() -> None:
        rows = facts(pill)
        screen, lit = grab()
        ratio = screen.width / max(1, pill.winfo_screenwidth())

        head = panel(rows, 1400)
        shot = screen.copy()
        shot.thumbnail((1400, 900))
        close = screen.crop(stack_box(pill, ratio))
        if close.width > 1400:
            close.thumbnail((1400, 10_000))

        parts = [head, shot, close]
        out = Image.new("RGB", (1400, sum(p.height + PAD for p in parts) + PAD), BG)
        y = 0
        for part in parts:
            out.paste(part, ((1400 - part.width) // 2, y))
            y += part.height + PAD
        out.save(OUT)

        for label, value, _c in rows:
            if label or value:
                print(f"  {label:<24} {value}")
        print(f"\nwrote {OUT}  ({out.width}x{out.height})")
        if not lit:
            print("\nThe screen capture came back black. macOS needs Screen Recording\n"
                  "for the terminal: System Settings > Privacy & Security > Screen\n"
                  "Recording. Grant it, then run this again.")
        try:
            subprocess.run(["open", "-R", str(OUT)], check=False)
        except OSError:
            pass
        pill.quit_app()

    # Late enough that the bubble has been drawn and placed, which is most of what the
    # picture is of.
    pill.after(1200, report)
    pill.mainloop()


if __name__ == "__main__":
    main()
