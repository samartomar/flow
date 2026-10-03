"""`flow.hold`: the chord's decisions, tested on every platform.

**Why this file exists when `test_chord.py` already tests the chord.** Because
`test_chord.py` skips at its `import` line on anything that is not Windows Ã¢â‚¬â€
`flow.hotkey` calls `ctypes.WinDLL("user32")` at module scope Ã¢â‚¬â€ and the chord's state
machine is where the behaviour is. So the part of Flow hardest to get right, the part
with the most rules in it, is the part the macOS CI leg has never once executed. Its own
docstring says the hook "is never installed" and the suite drives `Chord._on_key`
directly, which means it was never really testing Windows; it was testing a state
machine that happened to be reachable only from Windows.

This file tests that machine directly, on both legs, with no hook and no platform check
anywhere. There is deliberately no `skipUnless` here: if this module ever grows a
platform dependency, the suite that exists to catch exactly that will be the thing that
stops importing, and it will stop on **both** legs rather than quietly going quiet on
one.

**Two halves.** The first states the behaviour `hotkey.Chord` already has, so that
extracting it into this module can be proved not to have changed anything Ã¢â‚¬â€ these are
the assertions `test_chord.py` makes today, re-made against the machine that will
produce them. The second covers what the machine has that `Chord` does not: the timing
rules, the latch, and the double tap.
"""


import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flow.hold as hold  # noqa: E402
from flow.hold import (  # noqa: E402
    BREAK, DOUBLE_TAP, EFFECTS, GESTURE_DEFAULT, GESTURES, IDLE, LATCH,
    MOD_DOWN, MOD_NAMES, MOD_UP, OTHER_DOWN, OTHER_UP, START, STOP, TOGGLE, Hold,
)

#: One long hold, so that "a sentence" is the default in these tests rather than a tap.
#: Comfortably past `TAP_MAX_MS`, and the reason every rule here about taps has to say
#: so explicitly Ã¢â‚¬â€ the point of that number is that a sentence is not a tap.
SENTENCE_SEC = 2.0


def machine(**kw) -> Hold:
    return Hold(**kw)


def flatten(groups) -> tuple:
    return tuple(effect for group in groups for effect in group)


def meaningful(groups) -> tuple:
    """The effects an adapter would act on, which is everything except `IDLE`.

    `IDLE` is the machine saying it has nothing to do, which is what most keystrokes on
    a machine earn. `Chord` puts a word on its queue only when there is one, so an
    adapter reads the answer the same way Ã¢â‚¬â€ and these tests are about the words, with
    `TestG` holding the shape of the quiet ones.
    """
    return tuple(effect for effect in flatten(groups) if effect != IDLE)


def hold_chord(m, t=0.0, length=SENTENCE_SEC):
    """One press-and-release of both modifiers, and everything it had to say."""
    return meaningful((m.feed(MOD_DOWN, "ctrl", t), m.feed(MOD_DOWN, "win", t),
                       m.feed(MOD_UP, "win", t + length),
                       m.feed(MOD_UP, "ctrl", t + length)))


class TestAGapIsWhatPairsNotHowLongTheKeysWereDown(unittest.TestCase):
    """The defect the owner reported: "sometimes it catches, sometimes it does not."

    A double tap whose window is measured press-to-press charges the user for their own
    press duration. Two 200 ms taps with a 150 ms pause between them measure 550 ms and
    never pair, inside a 500 ms window — so whether the gesture worked depended on how
    fast the person could press two modifiers, which is not a thing anybody controls
    deliberately. `Hold` now measures release-to-press: the pause alone.

    **Found by reading Fireflies' shipped code, not by guessing.** `app.asar`'s
    `dictation-focus.js` stores `lastTapUpAt` on the release and compares the next press
    to it. Its `DOUBLE_TAP_WINDOW_MS` (500) and `MIN_DOUBLE_TAP_GAP_MS` (20) are the same
    numbers this module already had, which is why a note claiming "it matches" was
    believed for as long as it was: the constants were never the difference, the
    measurement point was, and only reading the shipped source showed it.
    """

    def machine(self):
        latched, doubled = [], []
        return Hold(mods=frozenset({"ctrl", "win"}),
                    on_latch=lambda: latched.append(1),
                    on_double_tap=lambda: doubled.append(1)), latched, doubled

    def test_a_slow_pair_with_a_normal_pause_still_pairs(self):
        # The case that failed. Press-to-press: 200 + 150 + 200 = 550 ms, over the
        # window, so this gesture could not land at *any* pause length.
        m, _latched, doubled = self.machine()
        hold_chord(m, t=0.0, length=0.200)
        second = hold_chord(m, t=0.200 + 0.150, length=0.200)

        self.assertIn(DOUBLE_TAP, second)
        self.assertEqual(doubled, [1])

    def test_and_a_genuinely_slow_pause_does_not_pair(self):
        # The other direction, or the fix would be "everything is a double tap".
        m, _latched, doubled = self.machine()
        hold_chord(m, t=0.0, length=0.200)
        late = 0.200 + hold.DOUBLE_TAP_WINDOW_SEC + 0.2
        second = hold_chord(m, t=late, length=0.200)

        self.assertNotIn(DOUBLE_TAP, second)
        self.assertEqual(doubled, [])

    def test_a_key_bounce_is_still_not_a_second_tap(self):
        # The guard a wider window could have broken. A second down 10 ms after the up is
        # the keyboard talking to itself; pairing it would turn bounce into hands-free.
        m, _latched, doubled = self.machine()
        hold_chord(m, t=0.0, length=0.100)
        effects = meaningful((m.feed(MOD_DOWN, "ctrl", 0.110),
                              m.feed(MOD_DOWN, "win", 0.110),
                              m.feed(MOD_UP, "win", 0.110),
                              m.feed(MOD_UP, "ctrl", 0.110)))

        self.assertNotIn(DOUBLE_TAP, effects)
        self.assertEqual(doubled, [])

    def test_how_long_the_keys_were_down_is_not_in_the_number(self):
        # The property, as one sweep of press durations at a fixed 150 ms pause. The slow
        # end of this range is what the owner could not make work.
        for length in (0.05, 0.10, 0.15, 0.20, 0.30):
            with self.subTest(length=length):
                m, _latched, doubled = self.machine()
                hold_chord(m, t=0.0, length=length)
                second = hold_chord(m, t=length + 0.150, length=length)
                self.assertIn(DOUBLE_TAP, second)

    def test_and_the_whole_window_is_still_reachable(self):
        # The widening is not "anything goes": a pause of exactly the window still pairs
        # and one millisecond past it does not. Both sides, because a window that only
        # ever refuses is indistinguishable from no gesture at all.
        window = hold.DOUBLE_TAP_WINDOW_SEC
        for pause, pairs in ((window - 0.001, True), (window, True),
                             (window + 0.001, False)):
            with self.subTest(pause=pause):
                m, _latched, doubled = self.machine()
                hold_chord(m, t=0.0, length=0.05)
                second = hold_chord(m, t=0.05 + pause, length=0.05)
                self.assertEqual(DOUBLE_TAP in second, pairs, doubled)


class TestTheModuleHasNoPlatformInIt(unittest.TestCase):
    """The reason this suite runs everywhere, asserted rather than assumed."""

    def test_it_imports_without_any_win32_having_been_bound(self):
        # If `flow.hold` grew `ctypes.WinDLL`, this file would stop importing on macOS
        # and take every test below with it Ã¢â‚¬â€ silently, because a suite that skips looks
        # green. So the check lives here, in the file that would break.
        self.assertNotIn("ctypes", vars(hold))


class TestATheHoldIsTheUtterance(unittest.TestCase):
    """What `test_chord.py` calls `TestB`, re-made against the machine.

    The three moments and the order between them are the feature: press warms the
    models and opens the microphone, the hold is the utterance, release stops it and
    sends. `Chord` turns one `START` into the warm and then the capture; the machine
    says `START` once and the adapter expands it, because a machine that emitted `talk`
    would carry Flow's vocabulary and could not be tested against anything else.
    """

    def test_a_clean_hold_starts_and_then_sends(self):
        self.assertEqual(hold_chord(machine()), (START, STOP))

    def test_nothing_starts_until_the_chord_is_complete(self):
        # One modifier is not a hold. A bare Ctrl tap is a thing hands do constantly
        # while thinking, and opening a microphone on it is the defect `parse_chord`
        # refuses single-modifier chords to avoid.
        m = machine()
        self.assertEqual(m.feed(MOD_DOWN, "ctrl"), (IDLE,))
        self.assertFalse(m.talking)

    def test_it_ends_on_the_first_release_and_not_again_on_the_second(self):
        # The reason `armed` is latched rather than recomputed. Two modifiers go up as
        # two events, and a chord that asked "are they all up now?" would either end
        # twice Ã¢â‚¬â€ sending the same utterance into the window twice Ã¢â‚¬â€ or need the
        # releases in a particular order.
        m = machine()
        m.feed(MOD_DOWN, "ctrl")
        m.feed(MOD_DOWN, "win")
        self.assertEqual(m.feed(MOD_UP, "win"), (STOP,))
        self.assertEqual(m.feed(MOD_UP, "ctrl"), (IDLE,))

    def test_the_order_the_two_go_down_in_does_not_matter(self):
        for first, second in (("ctrl", "win"), ("win", "ctrl")):
            with self.subTest(first=first):
                m = machine()
                self.assertEqual(
                    meaningful((m.feed(MOD_DOWN, first), m.feed(MOD_DOWN, second),
                                m.feed(MOD_UP, second), m.feed(MOD_UP, first))),
                    (START, STOP))

    def test_a_repeated_keydown_does_not_reopen_the_microphone(self):
        # The OS repeats a held key in some configurations, and a second `START`
        # mid-utterance is something the UI could not tell apart from the user having
        # spoken into a microphone reopened under them.
        m = machine()
        m.feed(MOD_DOWN, "ctrl")
        m.feed(MOD_DOWN, "win")
        self.assertEqual(m.feed(MOD_DOWN, "ctrl"), (IDLE,))
        self.assertEqual(m.feed(MOD_DOWN, "win"), (IDLE,))
        self.assertEqual(m.feed(MOD_UP, "win"), (STOP,))

    def test_holding_it_three_times_is_three_utterances(self):
        # Obvious, and the one that catches a flag that latches on and never clears.
        # Also the test that forces `echo_guard` off by default: three holds in a tight
        # loop are three holds, and bounce suppression applied unconditionally would
        # swallow the second and the third.
        m = machine()
        out = []
        for _ in range(3):
            out += list(hold_chord(m, length=0.01))
        self.assertEqual(out, [START, STOP] * 3)

    def test_a_key_pressed_before_the_chord_formed_is_not_the_chords_business(self):
        # Holding Ctrl to click a link, tapping a key, then adding Win must still work
        # Ã¢â‚¬â€ otherwise every chord after an accidental keystroke is dead.
        m = machine()
        m.feed(MOD_DOWN, "ctrl")
        m.feed(OTHER_DOWN)
        self.assertEqual(m.feed(MOD_DOWN, "win"), (START,))

    def test_a_modifier_still_held_when_the_chord_forms_is_part_of_the_shape(self):
        # ctrl+shift+win is a different chord from ctrl+win, and telling them apart
        # means asking what is *held*, not what was pressed.
        m = machine()
        m.feed(MOD_DOWN, "ctrl")
        m.feed(MOD_DOWN, "shift")
        self.assertEqual(m.feed(MOD_DOWN, "win"), (IDLE,))
        self.assertFalse(m.talking)

    def test_releasing_the_extra_modifier_frees_the_chord_for_the_next_hold(self):
        m = machine()
        m.feed(MOD_DOWN, "ctrl")
        m.feed(MOD_DOWN, "shift")
        m.feed(MOD_DOWN, "win")
        # Let the whole chord go, the way a hand does, before pressing again.
        m.feed(MOD_UP, "shift")
        m.feed(MOD_UP, "win")
        m.feed(MOD_UP, "ctrl")
        self.assertFalse(m.extra["shift"])
        self.assertEqual(hold_chord(m, t=1.0), (START, STOP))


class TestBBothGesturesShipAndNeitherReplacesTheOther(unittest.TestCase):
    """What `test_chord.py` calls `TestBB`, against the machine.

    A hold is better for a sentence Ã¢â‚¬â€ no decision about when you are finished, and it
    cannot leave a microphone running. A toggle is the only one of the two that
    survives a paragraph or hands that cannot hold two keys down. Shipping only the hold
    takes the second case away from everybody who has it.
    """

    def test_hold_is_what_ships(self):
        self.assertEqual(GESTURE_DEFAULT, "hold")
        self.assertEqual(machine().gesture, "hold")

    def test_a_toggle_chord_fires_one_word_on_a_clean_release(self):
        m = machine(gesture="toggle")
        self.assertEqual(hold_chord(m), (TOGGLE,))

    def test_a_toggle_chord_does_nothing_at_all_on_the_press(self):
        # Warming on the press-down would load the models every time somebody reached
        # for the chord, which is the cost the hold gesture accepts on purpose and this
        # one has no reason to.
        m = machine(gesture="toggle")
        self.assertEqual(m.feed(MOD_DOWN, "ctrl"), (IDLE,))
        self.assertEqual(m.feed(MOD_DOWN, "win"), (IDLE,))

    def test_a_toggle_chord_still_refuses_what_the_os_meant(self):
        # The original rule, unchanged and still doing its job: `ctrl+win+d` makes a
        # virtual desktop and starts nothing. Under `hold` this is a break; here it is
        # silence.
        m = machine(gesture="toggle")
        m.feed(MOD_DOWN, "ctrl")
        m.feed(MOD_DOWN, "win")
        self.assertEqual(m.feed(OTHER_DOWN), (IDLE,))
        self.assertEqual(m.feed(MOD_UP, "win"), (IDLE,))
        self.assertEqual(m.feed(MOD_UP, "ctrl"), (IDLE,))

    def test_it_never_emits_a_word_the_other_gesture_owns(self):
        # The two vocabularies are disjoint, which is what lets one dispatch table serve
        # both without a mode flag at the far end.
        m = machine(gesture="toggle")
        for _ in range(3):
            hold_chord(m, length=0.01)
        self.assertEqual(set(flatten([hold_chord(machine(gesture="toggle"))]))
                         & {START, STOP}, set())

    def test_switching_gesture_is_one_assignment_and_takes_effect_at_once(self):
        # The reason `gesture` is a plain attribute read on every event rather than
        # something baked in at construction: switching by rebuilding would mean
        # unhooking and re-installing a `WH_KEYBOARD_LL` hook, which the OS may refuse
        # Ã¢â‚¬â€ and being refused *while changing a setting* leaves somebody with no chord.
        m = machine()
        self.assertEqual(hold_chord(m), (START, STOP))
        m.gesture = "toggle"
        self.assertEqual(hold_chord(m, t=5.0), (TOGGLE,))

    def test_an_unknown_gesture_falls_back_rather_than_disabling_the_chord(self):
        # It arrives from a hand-edited profile. A typo must cost the setting, not the
        # shortcut Ã¢â‚¬â€ a chord that silently did nothing would be unattributable.
        for name in ("Hold", "push-to-talk", "", None, 7):
            with self.subTest(name=name):
                self.assertEqual(machine(gesture=name).gesture, GESTURE_DEFAULT)



class TestCOperatingSystemsOwnCtrlWinToo(unittest.TestCase):
    """What `test_chord.py` calls `TestC`, against the machine.

    `ctrl+win` is a prefix in Windows itself Ã¢â‚¬â€ ctrl+win+d makes a virtual desktop,
    ctrl+win+left and +right switch between them. Under the old toggle gesture this
    needed no code: nothing had started, so refusing to fire was the whole behaviour.
    Push-to-talk opens the microphone on the press-down, so a desktop switch now
    genuinely starts capturing, and the promise has to be restated rather than quietly
    kept:

      **A third key stops the capture on the keystroke, and sends nothing.** Not at the
    release, which would record every desktop switch for as long as the user held the
    keys; and never as a send, which is the half that would put words in a window.
    """

    def test_a_third_key_breaks_the_hold_and_sends_nothing(self):
        m = machine()
        m.feed(MOD_DOWN, "ctrl")
        m.feed(MOD_DOWN, "win")
        self.assertEqual(m.feed(OTHER_DOWN), (BREAK,))
        self.assertEqual(m.feed(MOD_UP, "win"), (IDLE,))
        self.assertEqual(m.feed(MOD_UP, "ctrl"), (IDLE,))

    def test_the_break_happens_on_the_third_key_not_on_the_release(self):
        m = machine()
        m.feed(MOD_DOWN, "ctrl")
        m.feed(MOD_DOWN, "win")
        m.feed(OTHER_DOWN)
        self.assertFalse(m.talking)

    def test_switching_desktop_twice_breaks_once(self):
        m = machine()
        m.feed(MOD_DOWN, "ctrl")
        m.feed(MOD_DOWN, "win")
        self.assertEqual(m.feed(OTHER_DOWN), (BREAK,))
        self.assertEqual(m.feed(OTHER_DOWN), (IDLE,))
        self.assertEqual(m.feed(MOD_UP, "win"), (IDLE,))

    def test_ordinary_typing_never_starts_one(self):
        m = machine()
        for _ in range(5):
            self.assertEqual(m.feed(OTHER_DOWN), (IDLE,))
            self.assertEqual(m.feed(OTHER_UP), (IDLE,))
        self.assertFalse(m.talking)

    def test_one_modifier_alone_never_starts_however_long_it_is_held(self):
        m = machine()
        self.assertEqual(m.feed(MOD_DOWN, "ctrl"), (IDLE,))
        self.assertEqual(m.feed(MOD_UP, "ctrl", 30.0), (IDLE,))
        self.assertFalse(m.armed)

    def test_shift_arriving_last_is_a_break_like_any_other_third_key(self):
        m = machine()
        m.feed(MOD_DOWN, "ctrl")
        m.feed(MOD_DOWN, "win")
        self.assertEqual(m.feed(MOD_DOWN, "shift"), (BREAK,))


class TestDItLearnsNothingAboutTheKeysItRejects(unittest.TestCase):
    """The narrowing of R16, asserted against the machine rather than about it.

    The claim being defended is not "Flow is trustworthy" Ã¢â‚¬â€ it is that a key outside the
    chord changes one boolean and leaves nothing behind. So the test is a state
    comparison: feed different things, and check the object cannot tell them apart.
    """

    def test_two_different_keys_leave_the_machine_in_identical_states(self):
        # If a virtual key were recorded anywhere, "a" and "d" would have to produce
        # different states. They must not.
        states = []
        for _ignored in range(3):
            m = machine()
            m.feed(MOD_DOWN, "ctrl")
            m.feed(MOD_DOWN, "win")
            m.feed(OTHER_DOWN)
            m.feed(OTHER_UP)
            m.feed(MOD_UP, "win")
            m.feed(MOD_UP, "ctrl")
            states.append(vars(m).copy())


class TestETheTimingRulesThatChordNeverHad(unittest.TestCase):
    """What the machine has that `hotkey.Chord` does not, and why it is here at all.

    A chord of two modifiers cannot be confused with ordinary typing and cannot fire by
    accident, so `Chord` never needed a timer. A single key, or a modifier-only chord on
    a platform where the OS has its own idea of what that key means, does Ã¢â‚¬â€ and that is
    the shape the macOS side will need.

    **Nothing here is wired to a gesture.** Every callback defaults to `None`, so a
    machine built by any current caller latches nothing and double-taps nothing. That is
    the point: a gesture nobody chose must not fire, and the machinery can be tested
    without being reachable.
    """

    def test_a_sentence_always_sends_and_never_latches(self):
        latched = []
        m = machine(on_latch=lambda: latched.append(1))
        self.assertEqual(hold_chord(m, length=hold.TAP_MAX_SEC / 1000 + 0.5),
                         (START, STOP))
        self.assertEqual(latched, [])

    def test_a_short_release_still_sends_because_it_may_have_been_a_sentence(self):
        # The rule the machine is most careful about. A quick release may still have
        # been a deliberate sentence, and a machine that stopped sending because the
        # release was fast would lose somebody's first word on the strength of a number
        # nobody measured on their machine. So `STOP` is unconditional and the tap
        # paths are additive.
        latched = []
        m = machine(on_latch=lambda: latched.append(1))
        self.assertEqual(hold_chord(m, length=0.05), (START, STOP, LATCH))
        self.assertEqual(latched, [1])

    def test_a_quick_release_on_a_machine_nobody_asked_latches_nothing(self):
        m = machine()
        self.assertEqual(hold_chord(m, length=0.05), (START, STOP))

    def test_two_taps_inside_the_window_are_one_double_tap_and_not_two_latches(self):
        latched, doubled = [], []
        m = machine(on_latch=lambda: latched.append(1),
                    on_double_tap=lambda: doubled.append(1))
        first = hold_chord(m, t=100.0, length=0.05)
        # Half a window later. The window is press to press, so the gap is between
        # the two `armed_at` values and nothing here depends on how long each tap is
        # held -- see `_mod_up` for why that changed.
        second = hold_chord(m, t=100.0 + hold.DOUBLE_TAP_WINDOW_SEC / 2, length=0.05)
        self.assertEqual(first, (START, STOP, LATCH))
        self.assertEqual(second, (START, STOP, DOUBLE_TAP))
        self.assertEqual(doubled, [1])
        self.assertEqual(latched, [1])

    def test_two_taps_further_apart_than_the_window_are_two_separate_taps(self):
        latched, doubled = [], []
        m = machine(on_latch=lambda: latched.append(1),
                    on_double_tap=lambda: doubled.append(1))
        hold_chord(m, t=0.0, length=0.05)
        gap = hold.DOUBLE_TAP_WINDOW_SEC + 1.0
        self.assertEqual(hold_chord(m, t=gap, length=0.05), (START, STOP, LATCH))
        self.assertEqual(doubled, [])
        self.assertEqual(latched, [1, 1])

    def test_the_very_first_tap_of_a_session_still_latches(self):
        # `stopped_at` starts one whole cooldown in the negative for exactly this. A
        # machine that has never stopped has to answer "has enough time passed since we
        # stopped" with yes, and starting the clock at zero would answer no Ã¢â‚¬â€ so the
        # first tap of every session would silently never latch.
        latched = []
        m = machine(on_latch=lambda: latched.append(1))
        hold_chord(m, t=0.0, length=0.05)
        self.assertEqual(latched, [1])

    def test_three_quick_taps_are_two_latches_and_not_one(self):
        # **The bug this pins.** A double tap used to leave `last_tap_at` pointing at its
        # own second tap, so a third tap 120 ms later read as another double tap and
        # latched nothing. A person trying to switch hands-free listening off does
        # exactly that — tap, tap, tap — and got one latch and no way out of it without
        # a half-second pause nobody had been told about.
        #
        # **Run for both callbacks, because the two callers were not the same bug.**
        # The first attempt cleared the window inside the `on_double_tap` branch, which
        # is only entered when that callback exists — so this passed with it set and
        # the product stayed stuck, because `hotkey.Chord` registers `on_latch` alone.
        # Both halves now clear; this asserts both, so neither can regress alone.
        for callbacks in ({"on_latch": lambda: None},
                          {"on_latch": lambda: None, "on_double_tap": lambda: None}):
            with self.subTest(double_tap=("on_double_tap" in callbacks)):
                latched = []
                m = machine(**{**callbacks,
                              "on_latch": lambda: latched.append(1)})
                gap = hold.MIN_DOUBLE_TAP_GAP_SEC + 0.1
                # **From a non-zero base, deliberately.** `last_tap_at` is 0.0 to mean
                # "never tapped", and a press at exactly t=0.0 is indistinguishable
                # from that sentinel. `time.monotonic()` is never zero in production, so
                # this is not a bug — but a test that starts at zero asserts that a
                # coincidence the machine can never hit.
                base = 100.0
                first = hold_chord(m, t=base, length=0.05)
                second = hold_chord(m, t=base + 0.05 + gap, length=0.05)
                third = hold_chord(m, t=base + 0.10 + gap * 2, length=0.05)
                # The pair is consumed either way; `DOUBLE_TAP` only when someone is
                # listening for it.
                self.assertEqual(first, (START, STOP, LATCH))
                self.assertEqual(third, (START, STOP, LATCH))
                self.assertEqual(second[:2], (START, STOP))
                if "on_double_tap" in callbacks:
                    self.assertEqual(second, (START, STOP, DOUBLE_TAP))
                else:
                    self.assertEqual(second, (START, STOP))
                # Two latches: hands-free on, then off.
                self.assertEqual(latched, [1, 1])

    def test_a_double_tap_does_not_leave_the_window_armed_for_the_next_one(self):
        # The same defect stated as the property it breaks, because it is the property
        # that matters rather than the count: a *pair* is two taps, and after it the
        # machine owes nobody another gesture until somebody presses again. Both
        # callers again — `Chord` registers `on_latch` only.
        for callbacks in ({"on_latch": lambda: None},
                          {"on_latch": lambda: None, "on_double_tap": lambda: None}):
            with self.subTest(double_tap=("on_double_tap" in callbacks)):
                m = machine(**callbacks)
                gap = hold.MIN_DOUBLE_TAP_GAP_SEC + 0.1
                base = 100.0  # non-zero: 0.0 is the "never tapped" sentinel — see above
                hold_chord(m, t=base, length=0.05)
                hold_chord(m, t=base + 0.05 + gap, length=0.05)
                self.assertEqual(m.last_tap_at, 0.0)

    def test_the_window_still_reopens_for_a_genuine_second_pair(self):
        # Closing the window must not close it for good: two double taps, one after the
        # other, are two gestures. This is the test that keeps the fix from becoming a
        # machine that latches exactly once per session.
        doubled = []
        m = machine(on_latch=lambda: None, on_double_tap=lambda: doubled.append(1))
        gap = hold.MIN_DOUBLE_TAP_GAP_SEC + 0.1
        base = 100.0
        hold_chord(m, t=base, length=0.05)
        hold_chord(m, t=base + 0.05 + gap, length=0.05)
        after = base + 1.0  # past the window, so this is a fresh first tap of a second pair
        hold_chord(m, t=after, length=0.05)
        hold_chord(m, t=after + 0.05 + gap, length=0.05)
        self.assertEqual(doubled, [1, 1])



class TestFTheEchoGuardIsOffUntilSomebodySaysItsSourceBounces(unittest.TestCase):
    """A per-source guard, and the test that makes it one.

    Some keyboards emit a second key-up for one physical press. Left alone that is one
    more release, which is harmless for a hold Ã¢â‚¬â€ `armed` is already false Ã¢â‚¬â€ but it is
    how a latched machine gets told to stop twice. Suppressing it unconditionally would
    cost more than it saves: a real re-tap can follow a release in about 20 ms, and
    `TestA::test_holding_it_three_times_is_three_utterances` holds the chord three times
    faster than that. So it is a flag, and Fireflies guards only its Globe/Fn key for
    the same reason.
    """

    def test_the_guard_is_off_by_default(self):
        self.assertFalse(machine().echo_guard)

    def test_with_the_guard_a_bounced_release_does_not_end_a_second_hold(self):
        m = machine(echo_guard=True)
        m.feed(MOD_DOWN, "ctrl")
        m.feed(MOD_DOWN, "win")
        self.assertEqual(m.feed(MOD_UP, "win"), (STOP,))
        # The bounce: the same release arriving again a few milliseconds later.
        self.assertEqual(m.feed(MOD_UP, "win", 0.105), (IDLE,))
        self.assertEqual(m.feed(MOD_UP, "ctrl"), (IDLE,))
        self.assertFalse(m.armed)

    def test_the_guard_does_not_swallow_a_real_second_hold(self):
        m = machine(echo_guard=True)
        self.assertEqual(hold_chord(m, length=0.01), (START, STOP))
        # Long enough after that release to be a person, not a keyboard.
        self.assertEqual(hold_chord(m, t=1.0, length=0.01), (START, STOP))


class TestGItAnswersEventsItDoesNotRecognise(unittest.TestCase):
    """An adapter forwards everything it sees; the machine must not invent meaning."""

    def test_an_unknown_event_is_idle_rather_than_an_exception(self):
        m = machine()
        for event in ("", "nonsense", None, 7, "MOD_DOWN "):
            with self.subTest(event=event):
                self.assertEqual(m.feed(event), (IDLE,))

    def test_a_modifier_name_it_does_not_have_is_idle(self):
        m = machine()
        self.assertEqual(m.feed(MOD_DOWN, "hyper"), (IDLE,))
        self.assertEqual(m.feed(MOD_UP, "hyper"), (IDLE,))
        self.assertFalse(m.armed)

    def test_other_up_is_idle_because_the_chord_cannot_be_held_by_it(self):
        # Present so an adapter can forward every event without filtering, and so the
        # contract is a fixed shape rather than four special cases.
        self.assertEqual(machine().feed(OTHER_UP), (IDLE,))

    def test_it_always_answers_a_tuple_and_never_a_bare_string(self):
        # `Chord` puts each effect on its own queue, so an adapter walking the answer
        # must not have to know whether it got one effect or two.
        m = machine()
        for event in (MOD_DOWN, MOD_UP, OTHER_DOWN, OTHER_UP):
            with self.subTest(event=event):
                self.assertIsInstance(m.feed(event, "ctrl"), tuple)


class TestHItAgreesWithTheChordItWasTakenFrom(unittest.TestCase):
    """The extraction's whole risk, stated as a test.

    `hold.Hold` is `hotkey.Chord._feed`'s five booleans with the Win32 taken off, and
    this class is the proof that taking it off changed nothing. It drives **both** with
    the same key sequence and requires the same words on the queue, so a difference in
    the rules cannot survive a change to either side.

    **This is the test that makes the rest of the plan possible.** Wiring `Chord` to
    delegate to `Hold` is then a mechanical change with a test already standing on both
    sides of it â€” and after it lands, this whole file runs on the macOS leg too, which
    is the point of the exercise.

    Skipped off Windows for the same reason `test_chord.py` is: `flow.hotkey` binds
    user32 at import, so the comparison cannot be made where there is no user32. It is
    named, and the reason says which mechanism â€” so a Mac reader knows this is a
    platform fact and not a test that quietly stopped running.
    """

    @unittest.skipUnless(sys.platform == "win32",
                         "Windows-only: flow.hotkey binds user32 at import")
    def test_the_two_agree_on_every_sequence_that_matters(self):
        import queue

        import flow.hotkey as hotkey
        from flow.hotkey import (
            VK_LCONTROL, VK_LMENU, VK_LSHIFT, VK_LWIN, WM_KEYDOWN, WM_KEYUP,
            WM_SYSKEYDOWN, WM_SYSKEYUP, Chord,
        )

        VK_D, VK_LEFT, VK_A = 0x44, 0x25, 0x41

        #: Every virtual key `SEQUENCES` uses, mapped to the modifier name
        #: `hotkey._CHORD_VKS` gives it. Built from `hotkey` itself rather than spelled
        #: out, so it cannot drift from the map `Chord` actually reads — a literal here
        #: would be a second table of the same thing, which is the failure this class
        #: exists to catch. Shift is in it because Shift is the one that matters:
        #: handing it over as an ordinary key would make the machine treat
        #: ctrl+shift+win as ctrl+win-plus-a-stray.
        NAMES = {vk: name for vk, name in hotkey._CHORD_VKS.items()
                 if vk in {VK_LCONTROL, VK_LMENU, VK_LSHIFT, VK_LWIN}}

        #: `(down_vks, up_vks)` pairs, as the sequences both sides are driven with.
        SEQUENCES = (
            # One modifier is not a hold.
            ((VK_LCONTROL,), (VK_LCONTROL,)),
            # The clean hold, both release orders.
            ((VK_LCONTROL, VK_LWIN), (VK_LWIN, VK_LCONTROL)),
            ((VK_LWIN, VK_LCONTROL), (VK_LCONTROL, VK_LWIN)),
            # A repeated keydown mid-hold.
            ((VK_LCONTROL, VK_LWIN, VK_LCONTROL, VK_LWIN), (VK_LWIN, VK_LCONTROL)),
            # A third key mid-hold: Windows meant something else.
            ((VK_LCONTROL, VK_LWIN, VK_D), (VK_D, VK_LWIN, VK_LCONTROL)),
            # Two third keys: the break still happens once.
            ((VK_LCONTROL, VK_LWIN, VK_D, VK_LEFT), (VK_LEFT, VK_LWIN, VK_LCONTROL)),
            # A key *before* the chord formed is not the chord's business.
            ((VK_LCONTROL, VK_A, VK_LWIN), (VK_LWIN, VK_LCONTROL)),
            # An unwanted modifier already held when it forms.
            ((VK_LCONTROL, VK_LSHIFT, VK_LWIN), (VK_LWIN, VK_LSHIFT, VK_LCONTROL)),
            # Releasing the unwanted modifier frees the chord for the next hold.
            ((VK_LCONTROL, VK_LSHIFT, VK_LWIN, VK_LWIN, VK_LCONTROL, VK_LWIN),
             (VK_LWIN, VK_LCONTROL)),
            # Ordinary typing, which must never start anything.
            ((VK_A, VK_D, VK_LEFT), (VK_LEFT, VK_D, VK_A)),
            # A chord that arms but never talks: nothing, and nothing again.
            ((VK_LCONTROL, VK_LSHIFT, VK_LWIN, VK_LWIN), (VK_LSHIFT, VK_LCONTROL)),
            # A chord modifier released without the other ever going down.
            ((VK_LCONTROL,), (VK_LCONTROL,)),
        )

        for gesture in hotkey.GESTURES:
            for down, up in SEQUENCES:
                with self.subTest(gesture=gesture, down=down):
                    self.assertEqual(
                        self._through_chord(hotkey, Chord, gesture, down, up,
                                            WM_KEYDOWN, WM_KEYUP),
                        self._through_hold(gesture, down, up, NAMES),
                    )

    @staticmethod
    def _drained(queue_) -> list:
        out = []
        while not queue_.empty():
            out.append(queue_.get_nowait())
        return out

    def _through_chord(self, hotkey, chord_cls, gesture, down, up,
                       wm_down, wm_up) -> list:
        """Drive the real `Chord` through its hook, and collect what it queued."""
        import ctypes
        import queue as queue_mod
        from unittest import mock

        presses = queue_mod.Queue()
        chord = chord_cls(presses, frozenset({"ctrl", "win"}), gesture=gesture)

        #: **The same readings both sides get, and the reason this comparison is
        #: still a comparison.** `Chord` now asks a clock for a tap verdict, so a
        #: harness that gave it none made every press zero-length — every press a tap —
        #: and the two sides would have been compared on different questions. A fixed
        #: clock is the honest minimum here: the sequences below are about *which*
        #: modifiers went down in which order, not how long a hand rested on them, and
        #: `test_chord.py` covers duration with a clock that moves.
        tick = iter([1000.0] * (len(down) + len(up)))
        chord.clock = lambda: next(tick)

        def event(message, vk):
            block = hotkey._KBDLLHOOKSTRUCT(vkCode=vk, scanCode=0, flags=0,
                                            time=0, dwExtraInfo=0)
            with mock.patch.object(hotkey, "user32") as fake:
                fake.CallNextHookEx.return_value = 0
                chord._on_key(0, message, ctypes.addressof(block))

        for vk in down:
            event(wm_down, vk)
        for vk in up:
            event(wm_up, vk)
        return self._drained(presses)

    def _through_hold(self, gesture, down, up, names) -> list:
        """Drive `hold.Hold` with the same sequence, mapped to modifier names.

        `names` maps *every* virtual key the sequences use to the modifier name
        `hotkey._CHORD_VKS` would have given it — including Shift, which is the one
        that matters. Handing Shift over as an ordinary key would make the machine
        treat ctrl+shift+win as ctrl+win-plus-a-stray, and the two sides would then
        disagree about a case where they in fact agree.

        **Configured exactly as `Chord` configures its own machine**, because the
        comparison is only worth anything if the two are the same machine. `on_latch` is
        set for the same reason `Chord` sets it — it is the switch that turns the tap
        arithmetic on — and the same fixed clock is passed to every event, so neither
        side sees a hold the other calls a tap. Left unset, the bare `Hold` returned
        early from `_ended` and the two disagreed about a case where they agree.
        """
        m = Hold(gesture=gesture, on_double_tap=lambda: None)
        words: list = []

        #: `Chord` puts the warm before the capture; `START` is that one moment, and
        #: the machine says it once rather than inventing a word for the pair.
        #: `DOUBLE_TAP` is in this table because the shipped gesture is two taps:
        #: `Chord` sends it to `toggle_action`, and a single tap reports nothing at all.
        expand = {START: ("warm", "talk"), STOP: ("talk-end",), BREAK: ("talk-break",),
                  TOGGLE: ("toggle",), DOUBLE_TAP: ("toggle",)}

        def put(effects):
            for effect in effects:
                if effect != IDLE:
                    words.extend(expand.get(effect, (effect,)))

        #: The same standing clock `_through_chord` hands the real `Chord`.
        now = 1000.0
        for vk in down:
            name = names.get(vk)
            put(m.feed(MOD_DOWN if name else OTHER_DOWN, name, now))
        for vk in up:
            name = names.get(vk)
            put(m.feed(MOD_UP if name else OTHER_UP, name, now))
        return words

