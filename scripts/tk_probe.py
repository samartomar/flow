"""Probe the exact tkinter window attributes the pill depends on (risk 3).

Cheap to run, and it gates stage 6: if -transparentcolor or -topmost misbehaves on
this Win 11 build, the pill needs a different visual approach and it is much better to
know that before writing it.
"""

import tkinter as tk

root = tk.Tk()
root.geometry("160x40+100+100")

checks = {
    "overrideredirect (borderless)": lambda: root.overrideredirect(True),
    "-topmost (always on top)": lambda: root.attributes("-topmost", True),
    "-alpha 0.92 (translucency)": lambda: root.attributes("-alpha", 0.92),
    "-transparentcolor (true rounded corners)": lambda: root.attributes(
        "-transparentcolor", "#ff00ff"
    ),
    "-toolwindow (keep off taskbar/alt-tab)": lambda: root.attributes(
        "-toolwindow", True
    ),
}

print(f"tk version: {tk.TkVersion}")
for label, fn in checks.items():
    try:
        fn()
        root.update()
        print(f"  OK      {label}")
    except tk.TclError as exc:
        print(f"  FAILED  {label}  -> {exc}")

# Confirm the values actually stuck rather than being silently ignored.
for attr in ("-topmost", "-alpha", "-transparentcolor"):
    try:
        print(f"  readback {attr} = {root.attributes(attr)!r}")
    except tk.TclError as exc:
        print(f"  readback {attr} failed: {exc}")

root.destroy()
print("done")
