"""Which call on Aqua knows where the Dock is.

`_tk_work_area` measures the usable area by maximising a probe window and reading back
where the window manager put it. On Windows that agrees with `SystemParametersInfoW`
exactly. On macOS it came back as the whole screen — `state("zoomed")` neither raised
nor maximised — so the pill was placed 24 px above 878 and landed inside the Dock band.

Three Aqua-specific candidates are asked here instead of guessed at:

  **wm maxsize** - Tk's Aqua port answers this from `[NSScreen visibleFrame]`, so it
  should already be the screen minus the menu bar and the Dock. It gives a *size* and
  no origin, which is why it is not enough on its own. (It is useless on Windows, where
  it answers with the whole screen even with a taskbar present - which is why the
  maximise probe exists at all.)

  **a window asked for +0+0** - Aqua will not put a titled window under the menu bar, so
  where it actually lands is the top of the usable area.

  **wm attributes -fullscreen** - the whole screen including the menu bar, as a control:
  if this and `zoomed` agree, `zoomed` is being treated as fullscreen.

Between the first two, `bottom = top + maxsize_height` is the Dock's top edge.

    uv run python scripts/mac_area_probe.py
"""

import sys
import tkinter as tk

root = tk.Tk()
root.withdraw()
sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
print(f"  platform                 {sys.platform}  tk {tk.TkVersion} "
      f"patch {root.tk.call('info', 'patchlevel')}")
print(f"  screen                   {sw} x {sh}")

mw, mh = root.maxsize()
print(f"  wm maxsize               {mw} x {mh}   (lost: {sw - mw} w, {sh - mh} h)")


def probe(name, setup):
    win = tk.Toplevel(root)
    win.attributes("-alpha", 0.0)
    win.geometry("200x120+80+80")
    note = "ok"
    try:
        setup(win)
        win.update_idletasks()
    except tk.TclError as exc:
        note = f"FAILED ({exc})"
    x, y = win.winfo_rootx(), win.winfo_rooty()
    w, h = win.winfo_width(), win.winfo_height()
    print(f"  {name:<24} ({x}, {y}, {x + w}, {y + h})   {note}")
    win.destroy()
    return x, y, w, h


probe("zoomed (today's probe)", lambda w: w.state("zoomed"))
_x, top, _w, _h = probe("asked for +0+0", lambda w: w.geometry("200x120+0+0"))
probe("fullscreen (control)", lambda w: w.attributes("-fullscreen", True))

print(f"\n  so the usable area is    (0, {top}, {mw}, {top + mh})")
print(f"  and the Dock starts at   y = {top + mh}   ({sh - (top + mh)} px tall)")
root.destroy()
