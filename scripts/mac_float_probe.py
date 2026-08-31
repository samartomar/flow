"""Which window configuration on Aqua stays visible and still takes a click.

Two faults reported from a Mac, and they are the same fault: click the app you want to
dictate into and Flow's window disappears, and clicking Send does nothing. That is what a
borderless `overrideredirect` NSWindow does when its application is no longer frontmost —
the window server orders it out, and a click on a background app's window is spent
activating that app rather than pressing what was under the cursor.

macOS has an answer for exactly this and it is what FluidVoice's overlay is: an NSPanel
with the *nonactivating* style, which floats above other apps and accepts a click without
taking focus. Tk 9 exposes it as `wm attributes -class` and `-stylemask`, which is how
Flow's own crash named them — Tk 8.6 refused `-transparentcolor` and listed what this
build does accept, and those two were in the list.

**This probe assumes nothing about their vocabulary.** It asks for a deliberately
nonsense value first, because Tk answers that with the legal ones. So a run is useful
even if every guess below is wrong.

    uv run python scripts/mac_float_probe.py

It prints what it is doing, waits while you click another application, records which
windows survived that, and then logs which buttons a click actually reached. Paste the
whole output back — no judgement calls, no photographs.
"""

import sys
import tkinter as tk

AWAY_SEC = 8
CLICK_SEC = 25
W, H = 360, 62

root = tk.Tk()
root.withdraw()
log: list[str] = []


def vocabulary(name: str) -> None:
    """Ask for a nonsense value; Tk's complaint enumerates the real ones."""
    try:
        root.wm_attributes(name, "there-is-no-such-value")
        print(f"  {name:<12} accepted nonsense - it is not validated on this build")
    except tk.TclError as exc:
        print(f"  {name:<12} {exc}")


print(f"platform {sys.platform}, tk {tk.TkVersion} "
      f"patch {root.tk.call('info', 'patchlevel')}\n")
print("What this build will accept:")
for attribute in ("-class", "-stylemask"):
    vocabulary(attribute)


def window(n: int, title: str, setup) -> tk.Toplevel:
    """One variant, built while unmapped because a class cannot be changed after.

    Whatever `setup` raises is printed and the window is still shown - a variant that
    could not be configured is a *result*, and it should be on screen wearing the reason
    so that what is seen and what is printed cannot come apart.
    """
    win = tk.Toplevel(root)
    win.withdraw()
    note = "ok"
    try:
        setup(win)
    except tk.TclError as exc:
        note = f"FAILED ({exc})"
    win.geometry(f"{W}x{H}+40+{40 + n * (H + 16)}")
    win.configure(bg="#12141a")
    tk.Label(win, text=f"{n}  {title}", bg="#12141a", fg="#e6e8ee",
             font=("Helvetica", 12)).pack(side="left", padx=10)
    tk.Button(win, text=f"click {n}", highlightbackground="#12141a",
              command=lambda: log.append(f"button {n} was reached")).pack(
        side="right", padx=10)
    win.deiconify()
    win.attributes("-topmost", True)
    print(f"  {n} {title:<44} {note}")
    return win


def panel(win, *flags):
    win.wm_attributes("-class", "nspanel")
    if flags:
        win.wm_attributes("-stylemask", " ".join(flags))


print("\nVariants:")
made = {
    1: window(1, "overrideredirect (what Flow does today)",
              lambda w: w.overrideredirect(True)),
    2: window(2, "nspanel, nonactivatingpanel",
              lambda w: panel(w, "nonactivatingpanel")),
    3: window(3, "nspanel, nonactivatingpanel + utility",
              lambda w: panel(w, "nonactivatingpanel", "utility")),
    4: window(4, "overrideredirect + nspanel, nonactivatingpanel",
              lambda w: (w.overrideredirect(True), panel(w, "nonactivatingpanel"))),
}


def survey() -> None:
    """What is still on screen now that this app is not the frontmost one."""
    print(f"\nAfter {AWAY_SEC}s in the background:")
    for n, win in made.items():
        try:
            print(f"  {n}  viewable={bool(win.winfo_viewable())} "
                  f"mapped={bool(win.winfo_ismapped())} "
                  f"at ({win.winfo_rootx()}, {win.winfo_rooty()})")
        except tk.TclError as exc:
            print(f"  {n}  gone ({exc})")
    print(f"\nNow click every button once, in any order. {CLICK_SEC}s.")
    root.after(CLICK_SEC * 1000, finish)


def finish() -> None:
    print("\nButtons a click actually reached:")
    for n in made:
        hit = f"button {n} was reached" in log
        print(f"  {n}  {'reached' if hit else 'NOTHING GOT THROUGH'}")
    print("\nThe variant that is both still visible above and reached here is the one "
          "Flow should\nbe built from. Paste all of this back.")
    root.destroy()


print(f"""
Four windows are on screen down the left.

  **Click another application now** - Finder, a browser, anything - and leave Flow in
  the background. This is the whole test: these windows are meant to survive that, and
  today's configuration does not.

Recording in {AWAY_SEC}s.""")
root.after(AWAY_SEC * 1000, survey)
root.mainloop()
