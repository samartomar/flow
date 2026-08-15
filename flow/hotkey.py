"""System-wide hotkeys via `RegisterHotKey` (stdlib ctypes).

tkinter can only see keystrokes when it has focus, and the whole point of a dictation
pill is that focus is somewhere else. `RegisterHotKey` needs a message loop on the
thread that registered, so registration lives on its own thread and presses are handed
back through a queue for the UI thread to drain — Tk must only ever be touched from the
thread that created it.

This is why no `keyboard`/`pynput` dependency is needed (R16).
"""

from __future__ import annotations

import ctypes
import queue
import threading
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# Declared for the same reason as in inject.py: an undeclared ctypes signature passes
# and returns 32-bit ints, which silently corrupts 64-bit WPARAM/LPARAM values.
user32.RegisterHotKey.argtypes = [
    wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT
]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT
]
user32.GetMessageW.restype = ctypes.c_int
user32.PostThreadMessageW.argtypes = [
    wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
]
user32.PostThreadMessageW.restype = wintypes.BOOL
kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x0001, 0x0002, 0x0004, 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012

VK_SPACE, VK_RETURN, VK_ESCAPE = 0x20, 0x0D, 0x1B


_MOD_NAMES = ((MOD_CONTROL, "ctrl"), (MOD_ALT, "alt"), (MOD_SHIFT, "shift"), (MOD_WIN, "win"))
#: Letters are named by their letter. Without this the mode binding printed as
#: "ctrl+alt+vk0x4d" in the startup diagnostics, which is a key nobody can find.
#:
#: Digits joined them when combos became rebindable: nothing shipped binds one, but
#: `ctrl+alt+1` is a combo somebody may now write into their profile, and a key that can
#: be *asked* for and not named back would put "vk0x31" in the one line that exists to
#: tell them what registered. Wider than `KEYS` on purpose — this names whatever the OS
#: accepted, and `KEYS` is only what a person may type.
_VK_NAMES = {
    0x20: "space", 0x0D: "enter", 0x1B: "esc", 0xDC: "backslash", 0xBA: "semicolon",
    **{code: chr(code) for code in range(0x30, 0x3A)},
    **{code: chr(code) for code in range(0x41, 0x5B)},
}

#: name -> bit, read off the table `describe` writes with so the two cannot drift.
_MOD_BITS = {name: bit for bit, name in _MOD_NAMES}


def describe(mods: int, vk: int) -> str:
    parts = [name for bit, name in _MOD_NAMES if mods & bit]
    parts.append(_VK_NAMES.get(vk, f"vk{vk:#x}"))
    return "+".join(parts)


class Hotkeys:
    """Registers combos and reports presses by name.

    Each action gets an ordered list of alternatives, because a combo can already be
    owned by another process — measured on this machine, where ctrl+alt+space was taken
    and would otherwise have been a dead shortcut with no explanation.

    `overrides` is the `hotkeys` table from the profile, and it goes in *front* of those
    alternatives rather than in place of them: a person who picks a combo another app
    already owns must still end up with a working Flow, and the fallbacks are the only
    thing that can give them one. Anything unusable in there is refused and named in
    `ignored`, never applied and never silently dropped.
    """

    def __init__(self, bindings: dict[str, list[tuple[int, int]]],
                 overrides: dict | None = None) -> None:
        #: What the OS will be asked for, in order. A copy, because it is the shipped
        #: table with this person's choices inserted into it — mutating the caller's
        #: `DEFAULT_BINDINGS` would make the second `Hotkeys` of a process inherit the
        #: first one's overrides.
        self.bindings, self.ignored = overridden(overrides, bindings)
        self.presses: queue.Queue[str] = queue.Queue()
        self.failed: list[str] = []
        #: action name -> the combo that actually registered, e.g. "ctrl+alt+space"
        self.chosen: dict[str, str] = {}
        self._ids: dict[int, str] = {}
        self._tid: int | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="hotkeys")

    def start(self, timeout: float = 2.0) -> bool:
        self._thread.start()
        return self._ready.wait(timeout)

    def stop(self) -> None:
        if self._tid is not None:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)

    def drain(self) -> list[str]:
        out = []
        while True:
            try:
                out.append(self.presses.get_nowait())
            except queue.Empty:
                return out

    def _run(self) -> None:
        self._tid = kernel_thread_id()
        next_id = 1
        for name, alternatives in self.bindings.items():
            for mods, vk in alternatives:
                if user32.RegisterHotKey(None, next_id, mods | MOD_NOREPEAT, vk):
                    self._ids[next_id] = name
                    self.chosen[name] = describe(mods, vk)
                    next_id += 1
                    break
            else:
                # Every alternative is owned by another app. Report it rather than
                # leaving the user wondering why a shortcut silently does nothing.
                self.failed.append(name)
        self._ready.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                name = self._ids.get(msg.wParam)
                if name:
                    self.presses.put(name)
        for i in self._ids:
            user32.UnregisterHotKey(None, i)


def kernel_thread_id() -> int:
    return kernel32.GetCurrentThreadId()


VK_BACKSLASH, VK_SEMICOLON = 0xDC, 0xBA
VK_M = 0x4D  # P9 mode toggle
VK_Q = 0x51  # quit

#: Ordered alternatives per action. ctrl+alt+space is first because it is the most
#: natural, but it was already taken on the development machine, so toggle in
#: particular needs somewhere to fall back to.
DEFAULT_BINDINGS: dict[str, list[tuple[int, int]]] = {
    "toggle": [
        (MOD_CONTROL | MOD_ALT, VK_SPACE),
        (MOD_CONTROL | MOD_SHIFT, VK_SPACE),
        (MOD_CONTROL | MOD_ALT, VK_BACKSLASH),
        (MOD_WIN | MOD_ALT, VK_SPACE),
    ],
    "send": [
        (MOD_CONTROL | MOD_ALT, VK_RETURN),
        (MOD_CONTROL | MOD_SHIFT, VK_RETURN),
    ],
    "cancel": [
        (MOD_CONTROL | MOD_ALT, VK_ESCAPE),
        (MOD_CONTROL | MOD_SHIFT, VK_ESCAPE),
    ],
    # P9: dictate <-> converse. "One action" is the acceptance criterion, so it gets a
    # binding of its own rather than a menu item only.
    "mode": [
        (MOD_CONTROL | MOD_ALT, VK_M),
        (MOD_CONTROL | MOD_SHIFT, VK_M),
    ],
    # Quit used to be Escape, bound on the pill itself. Once the windows stopped taking
    # focus — WS_EX_NOACTIVATE, which is what makes a paste land in the right window —
    # a Tk key binding could never fire again, and the app went on documenting a
    # shortcut that did nothing. `RegisterHotKey` does not need focus, so it lives here
    # now, and if every alternative is taken the startup diagnostics say so.
    "quit": [
        (MOD_CONTROL | MOD_ALT, VK_Q),
        (MOD_CONTROL | MOD_SHIFT, VK_Q),
    ],
}


# -- rebinding, by hand, in the file ----------------------------------------
#
# The table above is five opinions, and the standing answer to "let me change them" has
# been a settings dialog, which this project does not build. So the answer is the file
# somebody already owns: an optional `hotkeys` object in `~/.flow/profile.json`, read
# once at launch. No new surface, no new dependency, and nothing to discover in a menu.
#
# **Why the meaning is judged here and not in `flow/profile.py`.** That module validates
# every other field it loads, and it stops at "this is a table" for this one — because it
# is imported on every launch including Lite, and `flow.hotkey` binds `user32` at import
# and therefore cannot be imported on a Mac at all. A validator that knew what a combo
# meant would have to live on both sides of that line or drag Win32 across it. So the
# profile checks the shape, this file checks the meaning, and there is exactly one table
# of key names rather than two that could disagree.
#
# It also puts the report where it belongs. An override that was thrown away has to be
# said out loud (P2), and the place a person looks when a shortcut is dead is the block
# of `hotkey  <action>  <combo>` lines — so a refusal is printed there, in the same
# breath as the combos that did register, rather than in a log nobody correlates.

#: What may sit after the modifiers, and deliberately nothing else.
#:
#: Every named key here is one `DEFAULT_BINDINGS` already binds, which is the whole rule:
#: this is a way to *rearrange* what Flow ships, not a general hotkey engine. Letters and
#: digits come along because they cost nothing and are what people reach for; F-keys,
#: media keys and the numpad do not, because each is a `VK_` constant nobody has pressed
#: on this machine and an untested binding is worse than an absent one.
#:
#: `\` is spellable both ways. It is the one shipped key whose name is longer than the
#: key, and a person copying `ctrl+alt+\` out of the guide should not have to know that
#: Flow calls it "backslash" — while a person writing JSON should not have to remember
#: that a lone backslash needs escaping in it.
KEYS: dict[str, int] = {
    "space": VK_SPACE,
    "enter": VK_RETURN,
    "esc": VK_ESCAPE,
    "backslash": VK_BACKSLASH,
    "\\": VK_BACKSLASH,
    **{chr(code).lower(): code for code in range(0x41, 0x5B)},
    **{chr(code): code for code in range(0x30, 0x3A)},
}

#: One refused override, one line, in the shape of the `hotkey` lines beside it.
#:
#: It names the action, the combo as written, and what is wrong with it — and stops
#: there. It does not go on to list the five action names, because the very next lines
#: printed *are* the five action names with their combos: a typo'd action is answered by
#: the block it sits in, and a startup line that teaches a vocabulary is one nobody
#: finishes reading.
IGNORED_LINE = "hotkey  {name} in profile.json ignored: {combo} - {reason}"

#: Said when the `hotkeys` value is not a table at all, so there were no entries to
#: refuse one at a time. `Profile` degrades it to nothing and records the field name;
#: this is what turns that into something a person can act on.
BAD_BLOCK_LINE = ("hotkey  profile.json ignored: hotkeys is not a table of "
                  "action -> combo")

#: How much of a hand-written name or combo a diagnostic line may quote back.
#:
#: The longest combo anybody can legally write is `ctrl+alt+shift+win+backslash` at 28
#: characters, so nothing valid is ever cut. What this is really bounding is the invalid
#: case: both halves come from a file somebody typed into, and a 400-character "action"
#: would push the rest of the startup block off the screen it exists for.
MAX_ECHO = 32


def _echo(text) -> str:
    """A hand-written value, quoted, bounded, and safe to print on any console.

    Not `repr()`, which is the obvious thing and the wrong one twice over. `repr` of a
    string keeps non-ASCII characters verbatim, and these lines go through `say()` to a
    stdout that may be a cp437 console — so `"ctrl+alt+é"` in a profile would raise
    `UnicodeEncodeError` and take the whole startup block down in place of the one line
    saying that combo could not be read. Anything unprintable becomes `?`: the point is
    to show the user which entry Flow is talking about, and a character their console
    cannot draw does not do that anyway.
    """
    flat = " ".join(str(text).split())
    flat = "".join(c if " " <= c <= "~" else "?" for c in flat)
    if len(flat) > MAX_ECHO:
        flat = flat[:MAX_ECHO - 3] + "..."
    return f"'{flat}'"


def parse(text) -> tuple[tuple[int, int] | None, str]:
    """`(mods, vk)` for a combo like "ctrl+alt+space", or `None` and why not.

    Two returns rather than an exception or a bare `None`, the same shape
    `profile.resolve_workspace` uses and for the same reason: the caller has to *say*
    what went wrong, and a reason assembled at the call site is a reason that will one
    day disagree with the check that produced it.

    Case and spacing are the writer's business — `"CTRL + Alt + Space"` is the same combo
    as `"ctrl+alt+space"`, because this is JSON somebody typed by hand and a shortcut that
    depends on where the spaces went is a bug report waiting to be filed.

    A combo with no modifier is refused rather than registered. `RegisterHotKey` would
    take it happily, and the result would be Flow owning the bare space bar system-wide
    from the moment it launched — the one mistake in here that a person could not
    diagnose, because the app that broke their typing gives no sign of being involved.
    """
    if not isinstance(text, str):
        return None, "not text"
    if not text.strip():
        return None, "blank"
    parts = [part.strip().lower() for part in text.split("+")]
    name = parts[-1]
    # A trailing "+" and a combo of modifiers only land here together, and they are the
    # same mistake: everything before the key was written and the key was not.
    if not name or name in _MOD_BITS:
        return None, "needs a key after the modifiers"
    if name not in KEYS:
        return None, f"{_echo(name)} is not a key Flow can bind"
    mods = 0
    for part in parts[:-1]:
        if part in _MOD_BITS:
            mods |= _MOD_BITS[part]
        elif part in KEYS:
            # "ctrl+a+b". Told apart from an unknown modifier because it is a different
            # misunderstanding: this person knows the syntax and asked for two keys.
            return None, f"{_echo(part)} is a key, and a combo takes one"
        else:
            return None, f"{_echo(part)} is not ctrl, alt, shift or win"
    if not mods:
        return None, "needs ctrl, alt, shift or win in front of it"
    return (mods, KEYS[name]), ""


def overridden(
    overrides: dict | None,
    bindings: dict[str, list[tuple[int, int]]] | None = None,
) -> tuple[dict[str, list[tuple[int, int]]], list[str]]:
    """The shipped candidates with each action's own override in front of them.

    Returns `(bindings, ignored)` — what to ask the OS for, and the lines to print about
    what was not asked for. Never raises: this reads a file a person edited with no
    validation between them and it, and a startup that dies over a typo'd shortcut is a
    worse outcome than any shortcut being wrong.

    The rest of each list is left exactly as shipped, duplicates and all. Dropping a
    combo from the fallbacks because the override happens to equal it would make the list
    behind a chosen combo differ from the list in the guide, and buys nothing: the only
    cost of the duplicate is one `RegisterHotKey` call that was going to fail anyway.
    """
    source = DEFAULT_BINDINGS if bindings is None else bindings
    out = {action: list(alternatives) for action, alternatives in source.items()}
    ignored: list[str] = []
    for name, combo in (overrides or {}).items():
        action = name.strip().lower() if isinstance(name, str) else ""
        if action not in out:
            ignored.append(IGNORED_LINE.format(
                name=_echo(name), combo=_echo(combo),
                reason="no action has that name"))
            continue
        binding, reason = parse(combo)
        if binding is None:
            ignored.append(IGNORED_LINE.format(
                name=_echo(name), combo=_echo(combo), reason=reason))
            continue
        out[action].insert(0, binding)
    return out, ignored
