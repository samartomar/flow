"""Which of five ways of asking Aqua for a frameless window actually works.

Reported from a Mac: the pill sat there with a title bar and three traffic lights on it,
while the panels above it were correctly frameless. The difference between them is that
`Pill` **is** the root window — `class Pill(tk.Tk)` — and `Bubble`/`ConversationCard` are
`Toplevel`s. Aqua creates the root's `NSWindow` before Tk can restyle it, so what works
for a Toplevel does not necessarily work for `.`.

Two wrong guesses have already been spent on this, so this asks the machine instead.
It opens five small windows in a row down the left of the screen, each labelled with the
technique that made it, and each *saying* whether it is a root window or a Toplevel.

    uv run python scripts/mac_frame_probe.py

**Look at them and tell me which ones have no title bar.** That is the whole output; the
console text is only there to say what you are looking at. It closes itself after 20
seconds.
"""

import sys
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

HOLD_SEC = 20
W, H = 420, 64


def style(win) -> str:
    """`::tk::unsupported::MacWindowStyle`, reporting rather than assuming."""
    try:
        win.tk.call("::tk::unsupported::MacWindowStyle", "style",
                    win._w, "plain", "noActivates")
        return "ok"
    except tk.TclError as exc:
        return f"FAILED ({exc})"


def label(win, text: str, y: int) -> None:
    win.geometry(f"{W}x{H}+40+{y}")
    tk.Label(win, text=text, bg="#12141a", fg="#e6e8ee",
             font=("Helvetica", 13)).pack(fill="both", expand=True)
    win.configure(bg="#12141a")


def main() -> None:
    notes = []

    # 1. The root, styled the way Flow does it today. This is the one that came back
    #    with traffic lights on it.
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    notes.append(("1 root: overrideredirect then MacWindowStyle", style(root)))
    label(root, "1  ROOT  overrideredirect + MacWindowStyle", 60)

    # 2. The root again, but restyled while unmapped. Aqua builds the NSWindow when the
    #    window is first mapped, so a style asked for afterwards may never be applied to
    #    anything — withdrawing and remapping is the documented way to force a rebuild.
    two = tk.Toplevel(root)  # stands in for a root; see 3 for the real second root
    two.withdraw()
    two.overrideredirect(True)
    notes.append(("2 toplevel: withdraw, overrideredirect, deiconify", style(two)))
    label(two, "2  TOPLEVEL  withdraw -> style -> deiconify", 150)
    two.deiconify()
    two.attributes("-topmost", True)

    # 3. A Toplevel with nothing but overrideredirect — what the bubble and card do, and
    #    what already works in the app. The control.
    three = tk.Toplevel(root)
    three.overrideredirect(True)
    three.attributes("-topmost", True)
    label(three, "3  TOPLEVEL  overrideredirect only  (the control)", 240)

    # 4. A Toplevel with the style and no overrideredirect, to find out which of the two
    #    is actually doing the work.
    four = tk.Toplevel(root)
    notes.append(("4 toplevel: MacWindowStyle only", style(four)))
    label(four, "4  TOPLEVEL  MacWindowStyle only", 330)
    four.attributes("-topmost", True)

    # 5. The root, withdrawn and remapped. If this one is bare, the fix is three lines
    #    and `Pill` can stay a `tk.Tk`. If it is not, the pill has to become a Toplevel
    #    under a hidden root, which is a real change to how the app starts.
    root.withdraw()
    root.overrideredirect(True)
    notes.append(("5 root: withdraw -> overrideredirect -> deiconify", style(root)))
    root.deiconify()
    root.attributes("-topmost", True)
    root.geometry(f"{W}x{H}+40+60")

    print(f"platform {sys.platform}, tk {tk.TkVersion}\n")
    for name, got in notes:
        print(f"  {name:<52} {got}")
    print(f"""
Five windows are on screen now, down the left. Window 1 is the root as Flow builds
it today and window 5 is the same root after a withdraw/deiconify - if 5 is bare and
1 is not, the fix is three lines. If neither root is bare, `Pill` has to stop being
`tk.Tk`, which is a larger change.

Say which numbers have no title bar. Closing in {HOLD_SEC}s.""")
    root.after(HOLD_SEC * 1000, root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()
