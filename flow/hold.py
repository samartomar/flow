"""The hold, with no operating system in it.

`hotkey.Chord` is where the chord lives, and its state machine is welded to a
`WH_KEYBOARD_LL` callback: `Chord._feed` reads a virtual key, compares it against
`_CHORD_VKS`, and mutates five attributes on the object the OS holds a pointer to. That
is the right shape for the input path of every keystroke on a machine, and it has one
cost that is easy to forget — **`tests/test_chord.py` skips at the `import` line on
anything that is not Windows**, because `flow.hotkey` calls `ctypes.WinDLL` at module
scope. So the whole of the chord's behaviour, which is the part that is genuinely hard
to get right, is the part CI cannot see on a Mac. `test_chord.py`'s own docstring says
the hook "is never installed" and the suite calls the callback directly — which means
the suite was never really about Windows at all.

**This module is that callback's brain, with the Win32 left off.** It imports nothing
but the standard library, so `tests/test_hold.py` runs on every leg. What it does not
do is decide *which* platform's keys to watch: `Chord` still owns that, still owns the
hook, and still answers `CallNextHookEx` on every event.

**Why this shape and not a dataclass of named events.** A state machine fed by named
events (`MOD_DOWN`, `OTHER_DOWN`, …) rather than by virtual keys is the thing that lets
a second platform feed it later without a second machine. A `CGEventTap` on macOS
reports the same physical facts — a chord modifier went down, something else went down,
a modifier came up — under different names and different numeric codes, and the shape of
the *decisions* does not change. Everything platform-specific stays on the far side of
`Chord._feed`.

**The three moments, and why the order between them is the feature.** A hold is not one
event: press warms the models and opens the microphone, the hold is the utterance,
release stops it and sends. The warm is a separate moment precisely so that a model
load cannot land inside the first sentence. See `hotkey.Chord.warm_action`.
"""

from __future__ import annotations

#: The modifier names a chord may be written from, in the order they are printed so
#: that "win+ctrl" and "ctrl+win" report as the same thing. Duplicated from
#: `hotkey.CHORD_NAMES` rather than imported, for the reason `profile.CHORD_DEFAULT` is
#: spelled there and not read from `flow/hotkey.py`: this module has to load on a Mac,
#: and the list here is the one both sides will be checked against.
MOD_NAMES = ("ctrl", "alt", "shift", "win")

#: The two gestures a hold can be. `"hold"` is push-to-talk: press to start capturing,
#: speak while it is down, release to send. `"toggle"` is the original: a clean
#: press-and-release starts hands-free listening and the next one stops it.
#:
#: Both ship because they are good at different things and neither replaces the other. A
#: hold is better for a sentence — no decision about when you are finished, and it cannot
#: leave a microphone running. A toggle is the only one of the two that survives a

# **Timing numbers, and whose measurements they are.** The windows below — a tap, a
# double tap, a post-stop cooldown, key-bounce suppression — are the ones a push-to-talk
# gesture needs and `Chord` had none of, because a chord of two modifiers cannot be
# confused with ordinary typing and none of them can fire by accident. The values come
# from Fireflies Desktop's shipped `dictation-hold-machine`, which measured them on real
# hardware; they are **not** measurements taken on any Flow user's machine, and this
# repository's own warrant for a hardcoded list is a measurement of its own
# (`inject_mac.TERMINAL_IDS` is documented as coming from vendor docs rather than from a
# measurement here, and says so for that reason). They are defensible defaults, and the
# ones that can be re-measured should be.
#
# **Two of them are off by default, and that is a finding rather than an omission.**
#
#   - `ECHO_UP_MS` suppresses the key bounce some keyboards emit, where one physical tap
#     produces a down, an up, and a second up. Universal bounce suppression would break
#     `test_chord.py::test_holding_it_three_times_is_three_utterances`, which holds the
#     chord three times in a tight loop and expects three utterances — a real re-tap can
#     follow a release in about 20 ms, and the loop is faster than that. Fireflies guards
#     this per-source for the same reason: only its Globe/Fn key is known to bounce, so
#     only Fn is guarded. `echo_guard` is therefore a constructor flag, off unless a
#     caller knows its source bounces.
#   - `POST_STOP_COOLDOWN_MS` keeps a stopped machine from immediately re-arming. Applied
#     to the latch path only, never to `hold` or `toggle`, for the same reason: three
#     quick holds are three holds.

#: A press shorter than this is a tap rather than a hold, which is the only thing that
#: can tell a deliberate press-and-release from somebody brushing two modifiers while
#: reaching for a third. Fireflies uses the same number for both its chord and its Fn
#: binding; the two are within a few milliseconds of each other there.
TAP_MAX_MS = 400

#: Two taps further apart than this are two presses, not a double tap.
DOUBLE_TAP_WINDOW_MS = 500

#: The floor on the gap between the first tap's release and the second tap's press.
#: Key bounce after a release is typically under 15 ms; a real second tap can follow in
#: about 20. Anything under this is the keyboard talking to itself.
MIN_DOUBLE_TAP_GAP_MS = 20

#: How long a stopped machine refuses to re-arm on the latch path. The hold and toggle
#: paths are not gated by it — see above.
POST_STOP_COOLDOWN_MS = 300

#: How long after a tap's release a second up for the same tap is treated as its echo.
ECHO_UP_MS = 300

# -- the effects, which are words rather than actions ---------------------------
#
# Named as strings so the machine carries none of Flow's vocabulary. `hotkey.Chord`
# maps each one onto the action name it was built with, and that mapping is the only
# place `talk` and `toggle` exist. A machine that emitted `talk` could not be tested
# against a machine that called it something else.

#: The chord formed and nothing unwanted was held: warm, then capture. Two moments, in
#: that order, and the order is the feature.
START = "start"

#: A clean release of a chord that was talking: stop capture and send.
STOP = "stop"

#: Something landed mid-hold, so the operating system meant something else. Not a send
#: under any circumstance — what happens to the audio is the session's decision, and it
#: differs from `STOP` for exactly that reason.
BREAK = "break"

#: A clean press-and-release under the toggle gesture.
TOGGLE = "toggle"

#: A tap shorter than `TAP_MAX_MS`: hands-free is now running and survives the release.
LATCH = "latch"

#: Two taps inside `DOUBLE_TAP_WINDOW_MS`.
DOUBLE_TAP = "double_tap"

#: Nothing happened. Not a failure — most keystrokes on a machine are this.
IDLE = "idle"

class Hold:
    """One chord's worth of press/release state, and nothing else.

    **Plain attributes, mutated in place.** The reason `hotkey.Chord` uses dicts for its
    held state rather than a `set` is that this runs on the input path of every
    keystroke on the machine; the same reasoning applies, and `Chord` will keep owning
    that hot path anyway.

    **A rejected key changes one boolean.** `other` is True when something outside the
    chord went down, and it is the only thing this object learns about that key — never
    a name, a code, or a count. `tests/test_hold.py` asserts that by comparing whole
    states after different rejected keys, which is a trap rather than a restatement: a
    field added tomorrow that could hold one would be compared by default and would fail
    there.
    """

    def __init__(self, mods=frozenset({"ctrl", "win"}), gesture: str | None = None,
                 *, echo_guard: bool = False, on_latch=None,
                 on_double_tap=None) -> None:
        self.mods = frozenset(mods)
        #: Which of `mods` are down right now, by name.
        self.down = {name: False for name in self.mods}
        #: The modifiers this chord does *not* want, and whether each is held.
        #:
        #: Tracked separately from `other` because the two answer different questions.
        #: `other` is "was something pressed *during* this hold", and it has to reset
        #: when the chord forms — otherwise holding Ctrl to click a link, tapping a key,
        #: then adding Win would be refused for a keystroke that had nothing to do with
        #: the chord. But a modifier that is *still down* when the chord forms is not
        #: history, it is part of the shape: ctrl+shift+win is a different chord from
        #: ctrl+win, and telling them apart means asking what is held, not what was
        #: pressed.
        #:
        #: Only modifiers get this treatment, and that is the privacy line holding: a
        #: modifier's identity is already the key it was looked up by, while every other
        #: key on the board still collapses to the single boolean `other`.
        self.extra = {name: False for name in MOD_NAMES if name not in self.mods}
        #: True once a key outside the chord went down while it was forming.
        self.other = False
        #: True while every modifier in `mods` is held. Latched rather than recomputed so
        #: that releasing them one at a time still ends exactly once.
        self.armed = False
        #: True between the press that started capturing and whatever ends it. Separate
        #: from `armed` because a chord that formed with an unwanted modifier already down
        #: arms without ever starting, and the end has to know whether there is anything
        #: to end.
        self.talking = False
        #: Read on every event rather than baked in at construction, so a caller can
        #: switch gesture with one assignment. `Chord` keeps its own attribute for this
        #: reason and mirrors it here.
        self.gesture = gesture if gesture in GESTURES else GESTURE_DEFAULT
        #: Whether to suppress the key bounce some keyboards emit on their own. Off by
        #: default — see the module docstring for why turning it on unconditionally would
        #: break three quick holds.
        self.echo_guard = echo_guard
        #: Called as `on_latch()` when a tap shorter than `TAP_MAX_MS` latches hands-free
        #: listening. `None` by default: the machine has the machinery and nothing
        #: dispatches to it yet. A gesture nobody chose must not fire, so the callback
        #: is what decides, not the machine.
        self.on_latch = on_latch
        #: Called as `on_double_tap()` for two taps inside `DOUBLE_TAP_WINDOW_MS`.
        #: `None` by default, for `on_latch`'s reason.
        self.on_double_tap = on_double_tap
        #: When the chord last armed. 0 means "not now", which is why every window in
        #: this module is compared as a difference rather than against zero.
        self.armed_at = 0.0
        #: When the last hold ended, for `MIN_DOUBLE_TAP_GAP_MS` and `DOUBLE_TAP_WINDOW_MS`.
        #: 0 means "never", which is why `_ended` reads the previous value before
        #: overwriting it rather than after.
        self.last_tap_at = 0.0
        #: When the machine last stopped, for `POST_STOP_COOLDOWN_MS`.
        #:
        #: **Negative by one whole window, and that is deliberate.** The cooldown asks
        #: "has enough time passed since we stopped", which on a machine that has never
        #: stopped has to be true. Starting this at `0.0` would make the answer
        #: `0 - 0 = 0 < POST_STOP_COOLDOWN_MS` — false — and the very first tap of a
        #: session would silently never latch. A clock that starts at zero is not a
        #: special case worth special-casing at the comparison; it is answered here
        #: once, where the field is declared.
        self.stopped_at = -POST_STOP_COOLDOWN_SEC
        #: Whether a tap is still owed its echo-suppressed release. Set when a hold ends,
        #: cleared by the release that would otherwise end a second one.
        self.echo_pending = False

    def feed(self, event: str, name: str | None = None,
             now: float = 0.0) -> tuple[str, ...]:
        """One physical fact, and the effects it has. Returns a tuple, never a string.

        `event` is one of `EVENTS`. `name` is the modifier's name for `MOD_DOWN` and
        `MOD_UP`, and is ignored by the other two. `now` is a monotonic reading in
        seconds, passed in rather than read here so that a test can drive the timing
        rules without sleeping.

        **A tuple, so two effects in one event stay two effects.** A `START` is the warm
        and then the capture, and the order between them is the feature; a machine
        returning one string per call would have to invent a combined word to say it.
        """
        if event == MOD_DOWN:
            return self._mod_down(name, now)
        if event == MOD_UP:
            return self._mod_up(name, now)
        if event == OTHER_DOWN:
            return self._other_down(now)
        if event == OTHER_UP:
            return (IDLE,)
        return (IDLE,)

    def _mod_down(self, name, now: float) -> tuple[str, ...]:
        if name is not None and name in self.extra:
            # A modifier this chord does not want, going down. Held state, not history.
            self.extra[name] = True
            self.other = True
            return self._break()

        if name is None or name not in self.down:
            return (IDLE,)

        self.down[name] = True
        if self.armed or not all(self.down.values()):
            return (IDLE,)

        # The chord has formed. A fresh hold gets a fresh verdict: whatever was pressed
        # before it formed is not this chord's business. What is still *held* is.
        self.armed = True
        self.armed_at = now
        self.other = any(self.extra.values())
        if self.other or self.gesture != "hold":
            # The toggle gesture has no press-down half, and warming on one would load
            # the models every time somebody reached for the chord.
            return (IDLE,)
        self.talking = True
        return (START,)

    def _mod_up(self, name, now: float) -> tuple[str, ...]:
        if name is not None and name in self.extra:
            self.extra[name] = False
            return (IDLE,)

        if name is None or name not in self.down:
            return (IDLE,)

        self.down[name] = False
        if not self.armed:
            return (IDLE,)

        # A release this soon after the one that ended a hold is the same release
        # arriving twice, not a second chord. Only reachable when the caller has said
        # its source bounces — see the module docstring.
        #
        # **The elapsed time is the whole test.** A guard that swallowed *every* release
        # while `echo_pending` was set would eat the next real hold, and the machine
        # would look like it had lost the ability to end a sentence. Bounce is a
        # property of milliseconds, so it is compared against `ECHO_UP_SEC` and a
        # release a second later is a person.
        if self.echo_guard and self.echo_pending and (
                now - self.last_tap_at) < ECHO_UP_SEC:
            self.echo_pending = False
            self.armed = False
            return (IDLE,)

        self.armed = False
        if self.talking:
            held_for = now - self.armed_at
            self.talking = False
            self.echo_pending = True
            # The *previous* tap's time, read before this one overwrites it: the
            # double-tap question is "how long since the last one", and a machine that
            # asked after writing would always read zero and never see a second tap.
            previous_tap = self.last_tap_at
            self.last_tap_at = now
            return self._ended(held_for, now, previous_tap)
        if self.gesture == "toggle" and not self.other:
            # The original gesture, unchanged: a clean release — both held, nothing else
            # touched — flips hands-free listening. `other` is the same rule doing the
            # same job it always did, which is why `ctrl+win+d` still makes a desktop
            # and starts nothing.
            return (TOGGLE,)
        return (IDLE,)

    def _other_down(self, now: float) -> tuple[str, ...]:
        # Every other key on the keyboard. One boolean, and nothing else about it is
        # read, kept or compared.
        self.other = True
        return self._break(now)

    def _break(self, now: float = 0.0) -> tuple[str, ...]:
        """Something landed mid-hold, so the OS meant something else. Stop capturing.

        Under the old toggle gesture this needed no code at all: nothing had started, so
        refusing to fire was the whole behaviour. Push-to-talk opens the microphone on
        the press-down, which means `ctrl+win+d` now has something to undo — and it
        must be undone here, on the keystroke, rather than left for the release. Holding
        the chord through three desktop switches would otherwise record all of them.

        Once per hold. `talking` is cleared first, so the arrow key that follows the
        first arrow key does not put a second break on the queue.
        """
        if self.talking:
            self.talking = False
            self.armed = False
            self.stopped_at = now
            return (BREAK,)
        return (IDLE,)

    def _ended(self, held_for: float, now: float, previous_tap: float) -> tuple[str, ...]:
        """A hold that ended, and whether it was long enough to be only a sentence.

        **It always sends.** A hold of `TAP_MAX_MS` or longer is the utterance and sends,
        and so does a shorter one — a quick release may still have been a deliberate
        sentence, and a machine that stopped sending because the release was fast would
        lose somebody's first word on the strength of a number nobody measured on their
        machine. The tap paths below are therefore additive: they report what the release
        also looked like, and never replace the send.

        They only run when a caller has passed a callback for them, which nothing does
        yet. The machinery is here and tested because the macOS side will need it, and
        shipping it unused is how it gets tested rather than how it gets trusted.
        """
        effects = [STOP]
        if held_for > TAP_MAX_SEC:
            return tuple(effects)
        if self.on_latch is None and self.on_double_tap is None:
            return tuple(effects)

        # A machine that has never tapped is not a machine whose last tap was "just
        # now" — the sentinel has to be further away than any window, or the first tap
        # of a session would read as a double tap of nothing.
        since = now - previous_tap if previous_tap else DOUBLE_TAP_WINDOW_SEC + 1.0
        if self.on_double_tap is not None and previous_tap and (
                MIN_DOUBLE_TAP_GAP_SEC <= since <= DOUBLE_TAP_WINDOW_SEC):
            self.on_double_tap()
            return tuple(effects + [DOUBLE_TAP])

        if self.on_latch is not None and since > DOUBLE_TAP_WINDOW_SEC and (
                now - self.stopped_at) >= POST_STOP_COOLDOWN_SEC:
            self.on_latch()
            effects.append(LATCH)
        return tuple(effects)


#: Every effect the machine can produce, for a test to hold it to.
EFFECTS = (START, STOP, BREAK, TOGGLE, LATCH, DOUBLE_TAP, IDLE)

#: The windows above, in the seconds `feed` is given. Named in milliseconds because
#: that is how they were measured and how anyone comparing them to another product's
#: numbers will find them; converted once here rather than at each of the five places
#: that use one, because a comparison that mixes the two units fails *silently* — a
#: 400 ms tap read as 400 seconds is never a tap, and the machine that made that
#: mistake would look like it had no timing rules at all rather than like a unit bug.
_MS = 0.001
TAP_MAX_SEC = TAP_MAX_MS * _MS
DOUBLE_TAP_WINDOW_SEC = DOUBLE_TAP_WINDOW_MS * _MS
MIN_DOUBLE_TAP_GAP_SEC = MIN_DOUBLE_TAP_GAP_MS * _MS
POST_STOP_COOLDOWN_SEC = POST_STOP_COOLDOWN_MS * _MS
ECHO_UP_SEC = ECHO_UP_MS * _MS

# -- the events, which are facts and not decisions ------------------------------

#: One of the chord's own modifiers went down. `name` says which.
MOD_DOWN = "mod_down"

#: One of the chord's own modifiers came up.
MOD_UP = "mod_up"

#: A modifier this chord does not want went down. Carries no name, because the privacy
#: narrowing is that it does not need one — see `Hold.other`.
OTHER_DOWN = "other_down"

#: Something else went up. Present so an adapter can feed every event it sees without
#: filtering, and so the machine's contract is the same shape as the hook's.
OTHER_UP = "other_up"

EVENTS = (MOD_DOWN, MOD_UP, OTHER_DOWN, OTHER_UP)

#: paragraph, a long thought with pauses, or hands that cannot hold two keys for a
#: minute.
GESTURES = ("hold", "toggle")
GESTURE_DEFAULT = "hold"
