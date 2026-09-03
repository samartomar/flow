"""Which window configuration on Aqua is bare, stays up, and still takes a click.

Reported from a Mac: click the app you want to dictate into and Flow's window vanishes,
and clicking Send does nothing.

**The first run of this probe found the cause, and it was not the one it was written to
test.** Four variants, two with `overrideredirect` and two without. The two without were
the two whose buttons a click reached, and the two without were the two still on screen
after clicking another app. `overrideredirect` on Aqua makes a window both deaf and
fugitive, and it is the one line Flow uses on every window it owns.

The NSPanel class this was really written to test never applied at all - Tk answered
`cannot change the class after the mac window is created`, even on a withdrawn window -
so the panel was never the variable.

That leaves the question `overrideredirect` was there to answer: it is what takes the
title bar off. Tk's own complaint listed the way out. Asked for a nonsense style bit it
enumerated the real ones - `titled, closable, miniaturizable, resizable,
fullsizecontentview, utility, nonactivatingpanel, docmodal` - and a style mask *without*
`titled` is a window with no title bar that was never made deaf to begin with.

**A title bar is measured here, not looked at.** Ask for a window at a known y; how far
below that the client area lands is the decoration on it, and zero means bare. Same
arithmetic `_aqua_work_area` uses to find the menu bar. `winfo_viewable` is not trusted
for the disappearing - it reported all four windows healthy while two of them were gone
from the screen - so that one bit is the only thing left worth a human glance.

    uv run python scripts/mac_float_probe.py

Click another application when it says to, note which numbers vanish, then click every
button. Paste the output.
"""

import sys
import tkinter as tk

AWAY_SEC = 8
CLICK_SEC = 25
ASK_Y = 220
W, H = 420, 58

root = tk.Tk()
root.withdraw()
log: list[int] = []
decor: dict[int, int] = {}


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


def mask(win, *flags):
    """A style mask with no `titled` bit is a window with no title bar."""
    win.wm_attributes("-stylemask", " ".join(flags))


def window(n: int, title: str, setup, cls=None) -> tk.Toplevel:
    """One variant, configured while unmapped, then measured for decoration.

    Whatever `setup` raises is printed and the window is still shown - a variant that
    could not be configured is a *result*, and it belongs on screen wearing its reason so
    that what is seen and what is printed cannot come apart.
    """
    win = tk.Toplevel(root, class_=cls) if cls else tk.Toplevel(root)
    win.withdraw()
    note = "ok"
    try:
        setup(win)
    except tk.TclError as exc:
        note = f"FAILED ({exc})"
    asked = ASK_Y + n * (H + 14)
    win.geometry(f"{W}x{H}+40+{asked}")
    win.configure(bg="#12141a")
    tk.Label(win, text=f"{n}  {title}", bg="#12141a", fg="#e6e8ee",
             font=("Helvetica", 11)).pack(side="left", padx=10)
    tk.Button(win, text=f"click {n}", highlightbackground="#12141a",
              command=lambda: log.append(n)).pack(side="right", padx=10)
    win.deiconify()
    win.attributes("-topmost", True)
    win.update_idletasks()
    decor[n] = win.winfo_rooty() - asked
    print(f"  {n} {title:<44} title bar {decor[n]:>3} px   {note}")
    return win


print("\nVariants (title bar measured, not looked at):")
made = {
    1: window(1, "nothing asked for (the control)", lambda w: None),
    2: window(2, "overrideredirect (what Flow does today)",
              lambda w: w.overrideredirect(True)),
    3: window(3, "stylemask {} - no bits at all", lambda w: mask(w)),
    4: window(4, "stylemask {fullsizecontentview}",
              lambda w: mask(w, "fullsizecontentview")),
    5: window(5, "stylemask {} on a Toplevel made as NSPanel",
              lambda w: mask(w), cls="NSPanel"),
    6: window(6, "stylemask {nonactivatingpanel} as NSPanel",
              lambda w: mask(w, "nonactivatingpanel"), cls="NSPanel"),
}


def survey() -> None:
    print(f"\nAfter {AWAY_SEC}s in the background, Tk claims:")
    for n, win in made.items():
        try:
            print(f"  {n}  viewable={bool(win.winfo_viewable())}")
        except tk.TclError as exc:
            print(f"  {n}  gone ({exc})")
    print("  (Tk said all four were healthy last time while two were off the screen,\n"
          "   so please say which numbers you can actually still see.)")
    print(f"\nNow click every button once, in any order. {CLICK_SEC}s.")
    root.after(CLICK_SEC * 1000, finish)


def finish() -> None:
    print("\nResults:")
    for n in made:
        print(f"  {n}  title bar {decor.get(n, -1):>3} px   "
              f"{'CLICK REACHED IT' if n in log else 'nothing got through'}")
    print("\nWanted: title bar 0 px, still on screen, and the click reaching it.\n"
          "Paste all of this back, with which numbers stayed visible.")
    root.destroy()


print(f"""
Six windows are on screen down the left.

  **Click another application now** - Finder, a browser, anything - and leave Flow in
  the background. Note which numbers disappear.

Recording in {AWAY_SEC}s.""")
root.after(AWAY_SEC * 1000, survey)
root.mainloop()
