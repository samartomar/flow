"""Ask a Mac the two questions Windows answers with one API call, and print what it says.

Flow places its windows against a *work area* — the desktop minus whatever the OS keeps
for itself. On Windows that is one call (`SystemParametersInfoW(SPI_GETWORKAREA)`) and
one more for the monitor under the pointer. Off Windows there is neither, so `ui.py`
falls back to what Tk will admit to, and the first Mac to run it put the pill under the
Dock.

This exists so the fix is a measurement rather than a third guess. It prints every
number Tk can be asked for, next to what Flow currently computes from them, and it also
checks the two window attributes the pill depends on — the borderless frame and the
no-activate policy — because a Mac reported those wrong in the same breath.

    uv run python scripts/mac_probe.py

Nothing is opened that the user has to close: the probe window is withdrawn before it
would be seen, except for the two seconds the visible check needs.
"""

import sys
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flow.ui as ui  # noqa: E402


def row(label: str, value) -> None:
    print(f"  {label:<34} {value}")


def main() -> None:
    root = tk.Tk()
    root.withdraw()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()

    print(f"platform: {sys.platform}   tk {tk.TkVersion}")
    print("\nwhat Tk says about the screen")
    row("winfo_screenwidth/height", f"{sw} x {sh}")
    try:
        row("wm_maxsize()", root.wm_maxsize())
    except Exception as exc:
        row("wm_maxsize()", f"FAILED: {exc}")
    row("winfo_vrootwidth/height",
        f"{root.winfo_vrootwidth()} x {root.winfo_vrootheight()}")
    row("winfo_vrootx/y", f"{root.winfo_vrootx()}, {root.winfo_vrooty()}")
    row("winfo_fpixels('1i') (dpi)", root.winfo_fpixels("1i"))

    # The measurement that would settle it: zoom a window and read where it landed.
    # Supported on Windows and, depending on the build, on Aqua. If it works, its
    # numbers are the work area *including* the origin, which `wm_maxsize` cannot give.
    print("\nthe measurement that would settle it")
    probe = tk.Toplevel(root)
    probe.geometry("200x120+80+80")
    try:
        probe.state("zoomed")
        probe.update_idletasks()
        x, y = probe.winfo_rootx(), probe.winfo_rooty()
        w, h = probe.winfo_width(), probe.winfo_height()
        row("zoomed geometry (l,t,r,b)", (x, y, x + w, y + h))
    except Exception as exc:
        row("state('zoomed')", f"UNSUPPORTED: {exc}")
    # Asking for a position past the bottom edge: a window manager that clamps reveals
    # the bottom of the usable area by where it puts the window instead.
    try:
        probe.state("normal")
        probe.geometry(f"200x120+40+{sh + 500}")
        probe.update_idletasks()
        row("asked y=%d, landed at" % (sh + 500), probe.winfo_rooty())
    except Exception as exc:
        row("clamp test", f"FAILED: {exc}")
    probe.destroy()

    print("\nwhat Flow computes from the above")
    row("_work_area()", ui._work_area(sw, sh))
    row("_tk_work_area()", ui._tk_work_area(root, sw, sh))
    full, work = ui._pointer_monitor(sw, sh, root)
    row("_pointer_monitor() full", full)
    row("_pointer_monitor() work", work)
    row("pill would be placed at",
        ui.bottom_centre(ui.PILL_W, ui.PILL_H, full, work, ui.PANEL_BOTTOM_OFFSET))
    row("a 420x300 panel at",
        ui.bottom_centre(ui.BUBBLE_W, 300, full, work, ui.PANEL_BOTTOM_OFFSET))
    row("hidden panels park at", ui.park_spot(ui.BUBBLE_W, 300,
                                              ui._virtual_desktop(sw, sh)))

    print("\nthe two window attributes the pill depends on")
    win = tk.Toplevel(root)
    win.geometry("260x60+60+60")
    ok = []
    for label, call in (
        ("overrideredirect(True)", lambda: win.overrideredirect(True)),
        ("-topmost", lambda: win.attributes("-topmost", True)),
        ("-alpha 0.94", lambda: win.attributes("-alpha", 0.94)),
    ):
        try:
            call()
            win.update()
            row(label, "OK")
        except tk.TclError as exc:
            row(label, f"FAILED: {exc}")
    row("MacWindowStyle plain/noActivates",
        "OK" if ui._mac_window_style(win) else "FAILED (or not a Mac)")

    tk.Label(win, text="Any title bar on this?  (2s)", bg="#101216",
             fg="#e6e8ee").pack(fill="both", expand=True)
    win.update()
    row("visible for 2s at", (win.winfo_rootx(), win.winfo_rooty()))
    win.after(2000, root.destroy)
    root.mainloop()
    print("\nPaste all of the above back. The line that matters most is whether the")
    print("window above had a title bar, and what `zoomed geometry` says.")
    print(f"(unused: {ok})" if ok else "")


if __name__ == "__main__":
    main()
