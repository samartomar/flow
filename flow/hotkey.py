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
        #: The modifier-only `Chord`, once one has been installed, or None.
        #:
        #: It hangs here rather than being tracked separately because the pill already
        #: calls `hotkeys.stop()` on the way out and there is exactly one thing that
        #: should own the teardown of "global key input". A chord left installed after
        #: the window is gone is a hook the OS still calls into a dead interpreter.
        self.chord = None
        self._ids: dict[int, str] = {}
        self._tid: int | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="hotkeys")

    def start(self, timeout: float = 2.0) -> bool:
        self._thread.start()
        return self._ready.wait(timeout)

    def stop(self) -> None:
        if self.chord is not None:
            self.chord.stop()
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


# -- the modifier-only chord ------------------------------------------------
#
# `RegisterHotKey` cannot express "ctrl+win, and no third key". It takes a virtual key
# and there is no VK for "nothing" — so every combo above the fold has to end in a key
# somebody presses with their other hand. That third key is the whole complaint: ctrl,
# shift and win sit together at the bottom-left and are one *shape*, while ctrl+shift+z
# is a shape plus a reach.
#
# Which leaves the low-level keyboard hook, and R16 said no to exactly that — no
# `keyboard`, no `pynput`, nothing sitting on the global input path. This narrows R16
# rather than reversing it, and the narrowing is the thing to check when reading:
#
#   **It never learns which key you pressed.** `vkCode` is compared against `_CHORD_VKS`
#   — eleven modifier constants — and against nothing else. A key that is not in that set
#   sets a *boolean*. It is not stored, not logged, not compared to anything, and does
#   not leave the callback. That is a materially smaller claim than "Flow can see your
#   keystrokes", and it is small enough to audit in one sitting, which is the point.
#
#   **It is allocation-free on the hot path.** This callback runs on the input path of
#   every keystroke on the machine, and a slow one makes *all* typing feel late — the
#   worst possible failure for a dictation tool, because it would look like the OS. So
#   the steady state is integer comparisons and attribute writes. The one allocation is
#   `presses.put`, which happens when the chord actually fires.
#
#   **It never swallows anything.** `CallNextHookEx` is called on every event, including
#   the ones that fire the chord. Ctrl and Win are real keys with real jobs and Flow does
#   not get to keep them.
#
# **Why the "some other key" flag is correctness and not only privacy.** Windows already
# uses ctrl+win as a *prefix*: ctrl+win+d makes a virtual desktop, ctrl+win+left and
# +right switch between them. Every one of those presses a third key, so requiring a
# clean release — both modifiers held, nothing else touched, then let go — is what keeps
# switching desktops from also starting dictation. It is the same flag serving both ends.
#
# Start never opens on the release either, and that is Windows' own rule rather than
# something arranged here: the Start menu comes up on a Win keyup only when Win was
# pressed alone, and holding Ctrl is already enough to suppress it.

WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0100, 0x0101, 0x0104, 0x0105

VK_SHIFT, VK_CONTROL, VK_MENU = 0x10, 0x11, 0x12
VK_LWIN, VK_RWIN = 0x5B, 0x5C
VK_LSHIFT, VK_RSHIFT = 0xA0, 0xA1
VK_LCONTROL, VK_RCONTROL = 0xA2, 0xA3
VK_LMENU, VK_RMENU = 0xA4, 0xA5

#: vk -> which modifier name it is. The hook reads `vkCode` against this and nothing
#: else; see the block above for why that sentence is the design and not a detail.
#:
#: Both the generic constants (`VK_CONTROL`) and the sided ones (`VK_LCONTROL`) are in
#: here because the hook is fed the *sided* code for a physical press, while an injected
#: keystroke — `SendInput`, which `flow/inject.py` itself uses — may carry the generic
#: one. Listening for only one of the two would make the chord's behaviour depend on
#: whether a human or a program pressed it.
_CHORD_VKS: dict[int, str] = {
    VK_CONTROL: "ctrl", VK_LCONTROL: "ctrl", VK_RCONTROL: "ctrl",
    VK_LWIN: "win", VK_RWIN: "win",
    VK_SHIFT: "shift", VK_LSHIFT: "shift", VK_RSHIFT: "shift",
    VK_MENU: "alt", VK_LMENU: "alt", VK_RMENU: "alt",
}

#: The shipped chord — two modifiers, one hand, no reach, which is the entire reason
#: this code path exists rather than a sixth entry in `DEFAULT_BINDINGS` — lives in
#: `flow/profile.py` as `CHORD_DEFAULT`, because that module can be imported on a Mac
#: and this one cannot. What a chord *means* is judged here; what it defaults to is
#: written there, the same split `hotkeys` already uses.

#: Modifier names a chord may be written from, in the order `describe_chord` prints them
#: so that "win+ctrl" and "ctrl+win" report as the same thing.
CHORD_NAMES = ("ctrl", "alt", "shift", "win")

#: The two gestures a chord can be. `"hold"` is push-to-talk — press to start capturing,
#: speak while it is down, release to send what was said. `"toggle"` is the original:
#: a clean press-and-release starts hands-free listening, and the next one stops it.
#:
#: Both ship because they are good at different things and neither replaces the other.
#: A hold is the better gesture for a sentence — it needs no decision about when you are
#: finished, and it cannot leave a microphone running. A toggle is the only one of the
#: two that survives a paragraph, a long thought with pauses in it, or a pair of hands
#: that cannot hold two keys down for a minute. Shipping only the hold, which is what
#: this did first, took the second case away from everybody who had it.
GESTURES = ("hold", "toggle")
GESTURE_DEFAULT = "hold"

#: Said when the hook cannot be installed. Shaped like the `hotkey` lines beside it,
#: because that block is where somebody looks when a shortcut is dead — and unlike a
#: taken combo, this one has a working answer to point at.
CHORD_UNAVAILABLE = ("chord   unavailable (keyboard hook refused); "
                     "the toggle hotkey still works")

#: Said when the `chord` value in profile.json could not be read. Same shape as
#: `IGNORED_LINE` and for the same reason: a setting that silently reverts is
#: indistinguishable from one that never saved (P2).
CHORD_IGNORED_LINE = "chord   in profile.json ignored: {combo} - {reason}"


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


_HOOKPROC = ctypes.WINFUNCTYPE(
    wintypes.LPARAM, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)

user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int, _HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD
]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.CallNextHookEx.argtypes = [
    wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
]
user32.CallNextHookEx.restype = wintypes.LPARAM


def parse_chord(text) -> tuple[frozenset, str]:
    """`{"ctrl", "win"}` for "ctrl+win", or `None` and why not.

    Two returns for the reason `parse` has two: the caller has to print what was wrong,
    and a reason assembled at the call site is one that will eventually disagree with the
    check that produced it.

    **One modifier is refused**, and it is the refusal worth explaining. A single-modifier
    "chord" fires every time that key is tapped and released cleanly — and a bare Ctrl tap
    is a thing hands do constantly while thinking. The result would be a dictation app
    that starts recording at random, which is a defect nobody would attribute to a
    setting they typed.

    **Four is refused for the opposite reason**: ctrl+alt+shift+win is not a shape, and a
    chord that cannot be held is a chord that never fires.
    """
    if not isinstance(text, str):
        return None, "not a string"
    parts = [p.strip().lower() for p in text.split("+") if p.strip()]
    if not parts:
        return None, "empty"
    seen = set()
    for part in parts:
        if part not in CHORD_NAMES:
            return None, f"{_echo(part)} is not a modifier"
        seen.add(part)
    if len(seen) < 2:
        return None, "a chord needs two modifiers"
    if len(seen) > 3:
        return None, "a chord of four modifiers cannot be held"
    return frozenset(seen), ""


def describe_chord(mods) -> str:
    return "+".join(name for name in CHORD_NAMES if name in mods)


class Chord:
    """Fires `action` when `mods` are held together and released with nothing else hit.

    Writes into a queue the caller owns — `Hotkeys.presses` in practice — so the session
    drains one stream and cannot tell a chord from a registered combo. The chord is a
    second *way in*, not a second thing to handle, and every consumer downstream already
    knows what "toggle" means.
    """

    def __init__(self, presses, mods=frozenset({"ctrl", "win"}),
                 action: str = "talk", warm_action: str = "warm",
                 end_action: str = "talk-end", break_action: str = "talk-break",
                 gesture: str = None, toggle_action: str = "toggle") -> None:
        self.presses = presses
        self.mods = mods
        #: Put when the chord forms: start capturing, the hold is the utterance.
        self.action = action
        #: Put immediately before `action`, so the models load during the hold rather
        #: than inside the first sentence. `Session.warm` carries that argument in full.
        self.warm_action = warm_action
        #: Put when a chord modifier is released and the hold was clean — stop, and send
        #: what was said.
        self.end_action = end_action
        #: Put when a third key lands *during* a hold that had already started. Windows
        #: owns `ctrl+win+d` and `ctrl+win+arrow`, so this is the common case and not the
        #: exotic one, and it has to stop the capture the press-down opened. Distinct
        #: from `end_action` because what happens to the audio differs: this one does not
        #: paste, and the session decides between dropping it and keeping it on screen
        #: based on how much of it there is.
        self.break_action = break_action
        #: Which gesture this chord *is* — `"hold"` for push-to-talk, `"toggle"` for the
        #: press-and-release that starts and stops hands-free listening.
        #:
        #: **A plain attribute, read inside the hook, so it can be changed at runtime.**
        #: Rebuilding the `Chord` to switch would mean tearing down a `WH_KEYBOARD_LL`
        #: hook and installing another one, which is the one operation in this file the
        #: OS is entitled to refuse — and being refused *while changing a setting* would
        #: leave somebody with no chord at all and no obvious way back. One string
        #: assignment cannot fail.
        #:
        #: The two are genuinely different gestures rather than one with a flag, and the
        #: reason they are both here is that they are good at different things: a hold is
        #: better for a sentence, and a toggle is the only one of the two that works for
        #: a paragraph, a phone call, or anybody who cannot hold two keys down.
        self.gesture = gesture if gesture in GESTURES else GESTURE_DEFAULT
        #: What a `"toggle"` chord puts, on the release and nowhere else. Kept separate
        #: from `action` so the two gestures do not have to agree about a word: a hold
        #: starts capture and a toggle flips it, and calling both "talk" would make the
        #: dispatch table lie about one of them.
        self.toggle_action = toggle_action
        self.installed = False
        #: Which of `mods` are down right now. A set is the honest shape and the wrong
        #: one here — this is touched on the input path of every keystroke on the
        #: machine, so it is a plain dict of name -> bool, written in place.
        self._down = {name: False for name in mods}
        #: True once a key outside `mods` went down while the chord was forming. The only
        #: thing this file ever learns about that key.
        self._other = False
        #: The modifiers this chord does *not* want, and whether each is held right now.
        #:
        #: Tracked separately from `_other` because the two answer different questions,
        #: and one flag answering both got it wrong in exactly one direction. `_other` is
        #: "was something pressed *during* this hold", and it has to reset when the chord
        #: forms — otherwise holding Ctrl to click a link, tapping a key, then adding Win
        #: would be refused for a keystroke that had nothing to do with the chord. But a
        #: modifier that is *still down* when the chord forms is not history, it is part
        #: of the shape: ctrl+shift+win is a different chord from ctrl+win, and telling
        #: them apart means asking what is held, not what was pressed.
        #:
        #: Only modifiers get this treatment, and that is the privacy line holding: a
        #: modifier's identity is already in `_CHORD_VKS`, while every other key on the
        #: board still collapses to the single boolean above.
        self._extra = {name: False for name in CHORD_NAMES if name not in mods}
        #: True while every modifier in `mods` is held. Latched rather than recomputed so
        #: that releasing them one at a time still fires exactly once.
        self._armed = False
        #: True between the press-down that started capturing and whatever ends it — a
        #: release, or a third key. Separate from `_armed` because a hold that formed
        #: with an unwanted modifier already down arms without ever starting, and the end
        #: has to know whether there is anything to end. Nothing about it is a keystroke:
        #: it is the same single boolean `_other` is, and for the same reason.
        self._talking = False
        self._hook = None
        self._tid = None
        self._ready = threading.Event()
        #: The callback is handed to the OS, which does not keep a Python reference to
        #: it. Without this attribute it would be collected while still installed, and
        #: the process would die inside a keystroke somewhere unrelated.
        self._proc = _HOOKPROC(self._on_key)
        self._thread = threading.Thread(target=self._run, daemon=True, name="chord")

    def start(self, timeout: float = 2.0) -> bool:
        self._thread.start()
        self._ready.wait(timeout)
        return self.installed

    def _install(self):
        """Ask for the hook, and treat every way of not getting one the same.

        `SetWindowsHookExW` answers NULL when the OS refuses — policy, another process,
        a desktop this one cannot reach into. It is *also* the call that would raise if
        this build ever ran somewhere the symbol is missing. Both are the same event to
        everyone upstream: there is no chord, the registered toggle still works, and the
        startup block says so on one line.
        """
        try:
            return user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)
        except (AttributeError, OSError, ValueError):
            return None

    def stop(self) -> None:
        if self._tid is not None:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)

    def describe(self) -> str:
        return describe_chord(self.mods)

    def _break(self) -> None:
        """A third key landed mid-hold, so Windows meant something else. Stop capturing.

        Under the old toggle gesture this needed no code at all: nothing had started, so
        refusing to fire was the whole behaviour. Push-to-talk opens the microphone on
        the press-down, which means `ctrl+win+d` now has something to undo — and it must
        be undone here, on the keystroke, rather than left for the release. Holding
        `ctrl+win` through three desktop switches would otherwise record all of them.

        Once per hold. `_talking` is cleared first, so the arrow key that follows the
        first arrow key does not put a second break on the queue.
        """
        if self._talking:
            self._talking = False
            self.presses.put(self.break_action)

    def _on_key(self, code, wparam, lparam):
        # Negative `code` means "pass it on without looking", and it is not advice.
        if code >= 0:
            vk = ctypes.cast(lparam, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents.vkCode
            name = _CHORD_VKS.get(vk)
            if wparam == WM_KEYDOWN or wparam == WM_SYSKEYDOWN:
                if name is not None and name in self._down:
                    self._down[name] = True
                    if not self._armed and all(self._down.values()):
                        # A fresh hold starts a fresh verdict: whatever was *pressed*
                        # before the chord formed is not this chord's business. What is
                        # still *held* is — see `_extra`.
                        self._armed = True
                        self._other = any(self._extra.values())
                        if not self._other and self.gesture == "hold":
                            # The hold has begun. Two puts and no other work — the rule
                            # about what this callback may do on the input path of every
                            # keystroke on the machine is unchanged.
                            #
                            # Nothing at all in the toggle gesture: it has no press-down
                            # half, and warming on one would load the models every time
                            # somebody reached for `ctrl+win+arrow`.
                            self._talking = True
                            self.presses.put(self.warm_action)
                            self.presses.put(self.action)
                elif name is not None:
                    # A modifier this chord does not want. Held state, not history.
                    self._extra[name] = True
                    self._other = True
                    self._break()
                else:
                    # Every other key on the keyboard. One boolean, and nothing else
                    # about it is read, kept or compared.
                    self._other = True
                    self._break()
            elif wparam == WM_KEYUP or wparam == WM_SYSKEYUP:
                if name is not None and name in self._down:
                    self._down[name] = False
                    if self._armed:
                        self._armed = False
                        if self._talking:
                            self._talking = False
                            self.presses.put(self.end_action)
                        elif self.gesture == "toggle" and not self._other:
                            # The original gesture, unchanged: a clean release — both
                            # held, nothing else touched — flips hands-free listening.
                            # `_other` is the same rule doing the same job it always
                            # did, which is why `ctrl+win+d` still makes a desktop and
                            # starts nothing.
                            self.presses.put(self.toggle_action)
                elif name is not None:
                    self._extra[name] = False
        return user32.CallNextHookEx(self._hook, code, wparam, lparam)

    def _run(self) -> None:
        self._tid = kernel_thread_id()
        try:
            # `hMod` NULL with a thread id of 0 is the documented shape for a low-level
            # hook: unlike the other WH_ hooks it is not injected into other processes,
            # so it needs no module handle and the callback stays on this thread.
            self._hook = self._install()
            self.installed = bool(self._hook)
        finally:
            # Set in `finally` and not after, because `start()` is *waiting* on it. An
            # exception on the line above would otherwise leave the launch blocked for
            # the full timeout and then report "unavailable" for a reason nobody could
            # find — the traceback goes to a daemon thread's stderr, which on a windowed
            # build is nowhere at all.
            self._ready.set()
        if not self._hook:
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass
        user32.UnhookWindowsHookEx(self._hook)
        self._hook = None
