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

Every measurement comes from a window with the same decoration, which matters:
`maxsize` is a maximum *content* size, so it is short by whatever title bar its
window wears. Taking the origin from one window and the size from another counted
a 28 px title bar twice and put the answer 28 px too low.

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
_x, free, _w, _h = probe("asked for +80+300", lambda w: w.geometry("200x120+80+300"))
_x, clamped, _w, _h = probe("asked for +0+0", lambda w: w.geometry("200x120+0+0"))
probe("fullscreen (control)", lambda w: w.attributes("-fullscreen", True))

# `maxsize` is a maximum *content* size, so it is short by the decoration of the
# window that answered it - 735 from a titled window against 763 from an
# `overrideredirect` one on the same display. Every part of this comes from one
# probe so the title bar appears on both sides and cancels; mixing two windows
# counted it twice and put the answer 28 px too low.
title = free - 300
top = clamped - title
bottom = top + mh + title
print(f"\n  title bar                {title} px   (from +80+300, below any menu bar)")
print(f"  menu bar                 {top} px   (from +0+0, less that title bar)")
print(f"  so the usable area is    (0, {top}, {mw}, {bottom})")
print(f"  and the Dock starts at   y = {bottom}   ({sh - bottom} px tall)")
root.destroy()
