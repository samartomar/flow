"""The modifier-only chord: hold ctrl+win to dictate, let go to send.

Push-to-talk. The press-down warms the models and opens the microphone, the hold is the
utterance, and the release stops capture and sends what was said. It used to be a
toggle that fired one word at the release, and the three moments here are the change.


`RegisterHotKey` cannot express this, which is the whole reason the code under test
exists — it takes a virtual key and there is no VK for "nothing". So the chord runs on a
`WH_KEYBOARD_LL` hook, and that is a decision (R16 said no global hooks) narrowed rather
than reversed. Three properties are what the narrowing rests on, and each is asserted
here rather than left to the comment that claims it:

  **It never learns which key you pressed.** A key outside the chord sets a boolean. The
  suite proves the shape of that by driving keys through and checking that what changes
  is *whether* the chord fires, never a record of what was typed — see
  `TestDItLearnsNothingAboutTheKeysItRejects`.

  **It never swallows anything.** Every event reaches `CallNextHookEx`, including the one
  that fires the chord. Ctrl and Win have real jobs and Flow does not get to keep them.

  **It sends nothing when Windows meant something else.** ctrl+win is a *prefix* in
  Windows itself — ctrl+win+d makes a virtual desktop, ctrl+win+left and +right switch
  between them. Every one presses a third key, and under push-to-talk that third key
  *stops* a capture rather than merely declining to start one, because the press-down
  already opened the microphone. `TestCWindowsOwnsCtrlWinToo` states what this costs and
  what survives it; the promise that survives is that no desktop switch ever pastes.

The hook is never installed. `Chord._on_key` is the callback the OS would call, so the
suite calls it directly with the structure Windows would pass — which tests the state
machine that is actually hard, and asks nothing of the developer's keyboard.
"""

import ctypes
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Windows-only, and the guard is `tests/test_hotkey.py`'s word for word: `flow.hotkey`
# calls `ctypes.WinDLL("user32", use_last_error=True)` at module scope, so the failure
# would be the `import` below rather than anything a decorator could reach.
if sys.platform != "win32":  # pragma: no cover - the CI legs that are not Windows
    raise unittest.SkipTest("Windows-only: flow.hotkey binds user32 at import")

import queue  # noqa: E402

import flow.hotkey as hotkey  # noqa: E402
from flow.hotkey import (  # noqa: E402
    CHORD_NAMES,
    VK_LCONTROL,
    VK_LMENU,
    VK_LSHIFT,
    VK_LWIN,
    VK_RCONTROL,
    VK_RWIN,
    WM_KEYDOWN,
    WM_KEYUP,
    WM_SYSKEYDOWN,
    WM_SYSKEYUP,
    Chord,
    describe_chord,
    parse_chord,
)
from flow.profile import CHORD_DEFAULT  # noqa: E402

VK_D, VK_LEFT, VK_A = 0x44, 0x25, 0x41


class _Keyboard:
    """Drives `Chord._on_key` the way the OS would, and remembers what was passed on.

    `CallNextHookEx` is stubbed rather than called for real, for one reason and one
    convenience. The reason: what this suite is checking is that *every* event reaches
    it, and a real call returns a number that says nothing about whether it happened. The
    convenience: the callback runs with `self._hook` still None, because nothing here
    installs a hook, and a NULL hook handle is exactly the argument a stub should not
    have to care about.
    """

    def __init__(self, chord):
        self.chord = chord
        self.passed = []

    def _event(self, message, vk):
        # The real `KBDLLHOOKSTRUCT`, by address, because `_on_key` casts the LPARAM and
        # a fake that skipped the cast would not exercise the line most likely to be
        # wrong on a 64-bit build.
        block = hotkey._KBDLLHOOKSTRUCT(vkCode=vk, scanCode=0, flags=0, time=0,
                                        dwExtraInfo=None)
        # Held for the duration of the call: a struct that went out of scope here would
        # be freed under the pointer the callback is about to read.
        self._block = block
        with mock.patch.object(hotkey, "user32") as fake:
            fake.CallNextHookEx.return_value = 0
            self.chord._on_key(0, message, ctypes.addressof(block))
            self.passed.append((message, vk, fake.CallNextHookEx.called))

    def down(self, *vks):
        for vk in vks:
            self._event(WM_KEYDOWN, vk)
        return self

    def up(self, *vks):
        for vk in vks:
            self._event(WM_KEYUP, vk)
        return self

    def sys_down(self, *vks):
        for vk in vks:
            self._event(WM_SYSKEYDOWN, vk)
        return self

    def sys_up(self, *vks):
        for vk in vks:
            self._event(WM_SYSKEYUP, vk)
        return self


def _chord(mods=("ctrl", "win")):
    presses = queue.Queue()
    return Chord(presses, frozenset(mods)), presses


def _drained(presses):
    out = []
    while not presses.empty():
        out.append(presses.get_nowait())
    return out


#: One clean hold, start to finish, as the queue sees it.
HOLD = ["warm", "talk", "talk-end"]


def _fired(presses):
    """Everything one gesture put on the queue, in order.

    Named `_fired` still, but it no longer means "the one word a release emits" — under
    push-to-talk a hold is three moments, and the order between them *is* the feature.
    Filtering any of them out would hide the two things most worth asserting: that the
    warm arrives before the capture rather than with it, and that a hold Windows took
    over is stopped on the third key rather than at the release.
    """
    return _drained(presses)


class TestAWhatAChordMeansIsReadOffWhatSomebodyTyped(unittest.TestCase):
    """`parse_chord`, on the string the guide prints and the shapes a hand-edit makes."""

    def test_the_shipped_chord_parses_to_the_two_modifiers_it_names(self):
        self.assertEqual(parse_chord("ctrl+win"), (frozenset({"ctrl", "win"}), ""))

    def test_the_shipped_default_is_a_chord_this_parser_accepts(self):
        # The one assertion that would catch the two files disagreeing. `CHORD_DEFAULT`
        # lives in `flow/profile.py` because that module imports on a Mac and
        # `flow.hotkey` cannot — a split that buys platform reach and costs exactly this
        # risk, so the risk is bought back here.
        mods, reason = parse_chord(CHORD_DEFAULT)
        self.assertIsNotNone(mods, reason)

    def test_case_and_spacing_are_the_writers_business(self):
        # Same rule as `parse`, and for the same reason: this is JSON somebody typed by
        # hand, and a setting that depends on where the spaces went is a bug report
        # waiting to be filed.
        canonical, _reason = parse_chord("ctrl+win")
        for text in ("CTRL+WIN", "Ctrl+Win", "  ctrl + win  ", "cTrL+wIn",
                     "ctrl+win\n", "win+ctrl"):
            with self.subTest(text=text):
                self.assertEqual(parse_chord(text)[0], canonical)

    def test_one_modifier_is_refused_because_a_bare_tap_is_a_thing_hands_do(self):
        # The refusal worth explaining. A single-modifier "chord" fires every time that
        # key is tapped and released cleanly, and a bare Ctrl tap is a thing hands do
        # constantly while thinking — so it would be a dictation app that starts
        # recording at random, from a setting nobody would connect to the symptom.
        for text in ("ctrl", "win", "shift", "ctrl+ctrl", "ctrl + CTRL"):
            with self.subTest(text=text):
                mods, reason = parse_chord(text)
                self.assertIsNone(mods)
                self.assertIn("two modifiers", reason)

    def test_four_modifiers_are_refused_because_that_is_not_a_shape(self):
        mods, reason = parse_chord("ctrl+alt+shift+win")
        self.assertIsNone(mods)
        self.assertIn("cannot be held", reason)

    def test_a_key_is_not_a_modifier_and_is_named_as_the_thing_that_was_wrong(self):
        # The likeliest hand-edit by far: somebody reads "chord" and writes the combo
        # they already know. The reason has to point at the word that broke it, because
        # the fix is deleting that word and nothing else.
        mods, reason = parse_chord("ctrl+win+space")
        self.assertIsNone(mods)
        self.assertIn("space", reason)
        self.assertIn("not a modifier", reason)

    def test_the_shapes_that_are_not_strings_at_all(self):
        for value in (None, 3, ["ctrl", "win"], {"ctrl": "win"}, True):
            with self.subTest(value=value):
                self.assertEqual(parse_chord(value), (None, "not a string"))

    def test_an_empty_string_is_refused_here_and_meant_off_at_the_call_site(self):
        # `_chord` in `flow/__main__.py` never reaches the parser with a blank, because
        # blank is how somebody turns the chord off in the file. Refused rather than
        # accepted anyway, so that the two places cannot drift into disagreeing about
        # what an empty setting means.
        self.assertEqual(parse_chord("")[1], "empty")
        self.assertEqual(parse_chord("  +  ")[1], "empty")

    def test_every_chord_that_parses_can_be_written_back_out(self):
        # The round trip that keeps the startup line honest: the block says `chord
        # toggle ctrl+win`, and a chord that could be asked for but not named would put
        # something else there.
        for a in CHORD_NAMES:
            for b in CHORD_NAMES:
                if a == b:
                    continue
                with self.subTest(chord=f"{a}+{b}"):
                    mods, _ = parse_chord(f"{a}+{b}")
                    self.assertEqual(parse_chord(describe_chord(mods))[0], mods)

    def test_the_report_spells_a_chord_the_same_way_round_every_time(self):
        # "win+ctrl" and "ctrl+win" are the same chord, and the startup block has to
        # call them the same thing or the line stops being something to compare against
        # the guide.
        self.assertEqual(describe_chord(parse_chord("win+ctrl")[0]), "ctrl+win")


class TestBTheHoldIsTheUtterance(unittest.TestCase):
    """The whole feature: press both, speak while they are down, let go to send.

    Three moments, and the order between them is the point. The press-down warms the
    models and opens the microphone; the release stops it and sends what was said. The
    old gesture put one word on this queue at the release and nothing at the press, and
    the difference is a reload that used to land inside the user's first sentence.
    """

    def test_a_clean_hold_warms_then_captures_then_sends(self):
        chord, presses = _chord()
        _Keyboard(chord).down(VK_LCONTROL, VK_LWIN).up(VK_LWIN, VK_LCONTROL)
        self.assertEqual(_fired(presses), HOLD)

    def test_the_warm_lands_before_the_capture_and_not_beside_it(self):
        # The whole reason the warm exists. A warm that arrived with `talk` would be the
        # preload `Session.start` already does, and the hold would still be spent
        # waiting. Asserted at the press, before any release exists.
        chord, presses = _chord()
        _Keyboard(chord).down(VK_LCONTROL, VK_LWIN)
        self.assertEqual(_fired(presses), ["warm", "talk"])

    def test_nothing_starts_until_the_chord_is_complete(self):
        # One modifier is not a hold. A bare Ctrl tap is a thing hands do constantly
        # while thinking, and opening a microphone on it would be the defect
        # `parse_chord` refuses single-modifier chords to avoid.
        chord, presses = _chord()
        _Keyboard(chord).down(VK_LCONTROL)
        self.assertEqual(_fired(presses), [])

    def test_it_ends_on_the_first_release_and_not_again_on_the_second(self):
        # The reason `_armed` is latched rather than recomputed. Two modifiers go up as
        # two events, and a chord that asked "are they all up now?" would either end
        # twice — sending the same utterance into the window twice — or need the
        # releases in a particular order.
        chord, presses = _chord()
        keys = _Keyboard(chord).down(VK_LCONTROL, VK_LWIN)
        keys.up(VK_LWIN)
        self.assertEqual(_fired(presses), HOLD)
        keys.up(VK_LCONTROL)
        self.assertEqual(_fired(presses), [])

    def test_the_order_the_two_go_down_in_does_not_matter(self):
        for first, second in ((VK_LCONTROL, VK_LWIN), (VK_LWIN, VK_LCONTROL)):
            with self.subTest(first=first):
                chord, presses = _chord()
                _Keyboard(chord).down(first, second).up(first, second)
                self.assertEqual(_fired(presses), HOLD)

    def test_a_repeated_keydown_does_not_reopen_the_microphone(self):
        # The OS repeats a held key in some configurations, and `_armed` is what stops a
        # second `talk` arriving mid-utterance — which the UI could not tell apart from
        # the user having spoken into a microphone reopened under them.
        chord, presses = _chord()
        keys = _Keyboard(chord).down(VK_LCONTROL, VK_LWIN)
        keys.down(VK_LCONTROL, VK_LWIN, VK_LCONTROL)
        self.assertEqual(_fired(presses), ["warm", "talk"])

    def test_holding_it_three_times_is_three_utterances(self):
        # Obvious, and the one that would catch a flag that latches on and never clears.
        chord, presses = _chord()
        keys = _Keyboard(chord)
        for _ in range(3):
            keys.down(VK_LCONTROL, VK_LWIN).up(VK_LWIN, VK_LCONTROL)
        self.assertEqual(_fired(presses), HOLD * 3)

    def test_either_side_of_the_keyboard_works(self):
        chord, presses = _chord()
        _Keyboard(chord).down(VK_RCONTROL, VK_RWIN).up(VK_RWIN, VK_RCONTROL)
        self.assertEqual(_fired(presses), HOLD)

    def test_a_generic_modifier_code_works_because_injected_keys_carry_one(self):
        # A physical press arrives sided (`VK_LCONTROL`); a synthesised one may carry the
        # generic `VK_CONTROL`. `flow/inject.py` synthesises keys itself, so a hook that
        # listened for only one of the two would behave differently depending on whether
        # a human or a program pressed the chord.
        chord, presses = _chord()
        _Keyboard(chord).down(hotkey.VK_CONTROL, VK_LWIN).up(VK_LWIN, hotkey.VK_CONTROL)
        self.assertEqual(_fired(presses), HOLD)

    def test_the_alt_bearing_chords_arrive_as_sys_keys_and_still_work(self):
        # Windows sends WM_SYSKEYDOWN rather than WM_KEYDOWN while Alt is held. A chord
        # containing alt that only watched the plain messages would never fire at all.
        chord, presses = _chord(("ctrl", "alt"))
        _Keyboard(chord).sys_down(VK_LCONTROL, VK_LMENU).sys_up(VK_LMENU, VK_LCONTROL)
        self.assertEqual(_fired(presses), HOLD)

    def test_it_puts_the_words_it_was_built_with(self):
        # The chord is a second way in, not a second thing to handle: it writes into
        # `Hotkeys.presses`, so everything downstream drains one stream and cannot tell a
        # chord from a registered combo.
        presses = queue.Queue()
        chord = Chord(presses, frozenset({"ctrl", "win"}), action="go",
                      warm_action="heat", end_action="stop", break_action="drop")
        keys = _Keyboard(chord)
        keys.down(VK_LCONTROL, VK_LWIN).up(VK_LWIN, VK_LCONTROL)
        self.assertEqual(_fired(presses), ["heat", "go", "stop"])
        keys.down(VK_LCONTROL, VK_LWIN).down(VK_D).up(VK_D, VK_LWIN, VK_LCONTROL)
        self.assertEqual(_fired(presses), ["heat", "go", "drop"])

    def test_the_default_words_are_the_ones_the_ui_dispatches_on(self):
        # A tripwire on four strings that live in two files: `Pill._frame` matches each
        # by literal, and a rename here that missed it would land as a chord that opens
        # a microphone nothing ever closes.
        chord, _presses = _chord()
        ui = (Path(__file__).resolve().parent.parent
              / "flow" / "ui.py").read_text(encoding="utf-8")
        for word in (chord.warm_action, chord.action,
                     chord.end_action, chord.break_action):
            with self.subTest(word=word):
                self.assertIn('name == "%s"' % word, ui)


class TestBBBothGesturesShipAndNeitherReplacesTheOther(unittest.TestCase):
    """`Chord.gesture`, and the switch that should have been there from the start.

    Shipping push-to-talk *instead of* the toggle took a working gesture away from
    everybody who had it. They are good at different things: a hold needs no decision
    about when you are finished and cannot leave a microphone running, and a toggle is
    the only one of the two that survives a paragraph, a long thought with pauses in it,
    or hands that cannot hold two keys down for a minute.
    """

    def toggler(self):
        chord, presses = _chord()
        chord.gesture = "toggle"
        return chord, presses

    def test_hold_is_what_ships(self):
        self.assertEqual(hotkey.GESTURE_DEFAULT, "hold")
        self.assertEqual(_chord()[0].gesture, "hold")

    def test_a_toggle_chord_fires_one_word_on_a_clean_release(self):
        chord, presses = self.toggler()
        _Keyboard(chord).down(VK_LCONTROL, VK_LWIN).up(VK_LWIN, VK_LCONTROL)
        self.assertEqual(_fired(presses), ["toggle"])

    def test_a_toggle_chord_does_nothing_at_all_on_the_press(self):
        # It has no press-down half. Warming here would load 605 MB of models every time
        # somebody reached for `ctrl+win+arrow`, which is the cost the hold gesture
        # accepts on purpose and this one has no reason to.
        chord, presses = self.toggler()
        _Keyboard(chord).down(VK_LCONTROL, VK_LWIN)
        self.assertEqual(_fired(presses), [])

    def test_a_toggle_chord_still_refuses_what_windows_meant(self):
        # The original rule, unchanged and still doing its job: `ctrl+win+d` makes a
        # desktop and starts nothing. Under `hold` this is a break; here it is silence.
        chord, presses = self.toggler()
        keys = _Keyboard(chord).down(VK_LCONTROL, VK_LWIN)
        keys.down(VK_D).up(VK_D).up(VK_LWIN, VK_LCONTROL)
        self.assertEqual(_fired(presses), [])

    def test_it_never_emits_a_word_the_other_gesture_owns(self):
        # The two vocabularies are disjoint, which is what lets one dispatch table serve
        # both without a mode flag at the far end.
        chord, presses = self.toggler()
        keys = _Keyboard(chord)
        for _ in range(3):
            keys.down(VK_LCONTROL, VK_LWIN).up(VK_LWIN, VK_LCONTROL)
        self.assertEqual(set(_fired(presses)) & set(HOLD), set())

    def test_switching_gesture_is_one_assignment_and_takes_effect_at_once(self):
        # The reason `gesture` is a plain attribute the callback reads rather than
        # something baked in at construction: switching by rebuilding would mean
        # unhooking and re-installing a `WH_KEYBOARD_LL` hook, which the OS may refuse —
        # and being refused *while changing a setting* leaves somebody with no chord.
        chord, presses = _chord()
        keys = _Keyboard(chord)
        keys.down(VK_LCONTROL, VK_LWIN).up(VK_LWIN, VK_LCONTROL)
        self.assertEqual(_fired(presses), HOLD)
        chord.gesture = "toggle"
        keys.down(VK_LCONTROL, VK_LWIN).up(VK_LWIN, VK_LCONTROL)
        self.assertEqual(_fired(presses), ["toggle"])

    def test_an_unknown_gesture_falls_back_rather_than_disabling_the_chord(self):
        # It arrives from a hand-edited profile. A typo must cost the setting, not the
        # shortcut — a chord that silently did nothing would be unattributable.
        for name in ("Hold", "push-to-talk", "", None, 7):
            with self.subTest(name=name):
                presses = queue.Queue()
                chord = Chord(presses, frozenset({"ctrl", "win"}), gesture=name)
                self.assertEqual(chord.gesture, hotkey.GESTURE_DEFAULT)

    def test_the_menu_offers_exactly_the_gestures_that_exist(self):
        # `flow/ui.py` cannot import `flow.hotkey` — that module binds user32 at import —
        # so the menu keeps its own labels. This is the assertion that stops the two
        # lists drifting into a row that selects a gesture the hook does not know.
        import flow.ui as ui

        self.assertEqual(tuple(ui.GESTURE_LABELS), hotkey.GESTURES)


class TestCWindowsOwnsCtrlWinToo(unittest.TestCase):
    """`ctrl+win` is a Windows prefix, and push-to-talk changed what that costs.

    Under the old toggle gesture this class asserted that `ctrl+win+d` did nothing at
    all: nothing had started, so refusing to fire at the release was the whole
    behaviour. Push-to-talk opens the microphone on the press-down, so a desktop switch
    now genuinely starts capturing — and the promise has to be restated rather than
    quietly kept:

      **A third key stops the capture on the keystroke, and sends nothing.** Not at the
      release, which would record every desktop switch for as long as the user held the
      keys; and never as a send, which is the half that would put words in a window.

    What is captured in the fifty milliseconds before the third key is whatever the gate
    let through, which is nothing — nobody has begun speaking yet. `Session.talk_end`
    commits it regardless rather than applying a minimum-length rule, on the grounds
    that an empty utterance costs nothing and a threshold eventually eats a real word.
    """

    def test_ctrl_win_d_makes_a_virtual_desktop_and_sends_nothing(self):
        chord, presses = _chord()
        keys = _Keyboard(chord).down(VK_LCONTROL, VK_LWIN)
        keys.down(VK_D).up(VK_D).up(VK_LWIN, VK_LCONTROL)
        fired = _fired(presses)
        self.assertEqual(fired, ["warm", "talk", "talk-break"])
        self.assertNotIn("talk-end", fired)

    def test_ctrl_win_left_switches_desktop_and_sends_nothing(self):
        chord, presses = _chord()
        keys = _Keyboard(chord).down(VK_LCONTROL, VK_LWIN)
        keys.down(VK_LEFT).up(VK_LEFT).up(VK_LWIN, VK_LCONTROL)
        self.assertEqual(_fired(presses), ["warm", "talk", "talk-break"])

    def test_the_break_happens_on_the_third_key_not_on_the_release(self):
        # The timing is the whole difference. Waiting for the release would leave the
        # microphone open across every desktop switch in a long hold.
        chord, presses = _chord()
        keys = _Keyboard(chord).down(VK_LCONTROL, VK_LWIN)
        self.assertEqual(_fired(presses), ["warm", "talk"])
        keys.down(VK_LEFT)
        self.assertEqual(_fired(presses), ["talk-break"])

    def test_switching_desktop_twice_breaks_once(self):
        # `_talking` is cleared by the first break, so the second arrow finds nothing to
        # stop. A second break would ask the session to close a microphone it has
        # already closed.
        chord, presses = _chord()
        keys = _Keyboard(chord).down(VK_LCONTROL, VK_LWIN)
        keys.down(VK_LEFT).up(VK_LEFT).down(VK_LEFT).up(VK_LEFT)
        keys.up(VK_LWIN, VK_LCONTROL)
        self.assertEqual(_fired(presses), ["warm", "talk", "talk-break"])

    def test_an_extra_modifier_is_a_different_chord_and_never_starts_one(self):
        # ctrl+shift+win is not ctrl+win. Nothing starts, so nothing needs breaking.
        chord, presses = _chord()
        keys = _Keyboard(chord).down(VK_LSHIFT, VK_LCONTROL, VK_LWIN)
        keys.up(VK_LWIN, VK_LCONTROL, VK_LSHIFT)
        self.assertEqual(_fired(presses), [])

    def test_the_extra_modifier_blocks_it_whenever_it_went_down(self):
        # Both orders, because the first version of this got one of them wrong: an
        # unwanted modifier pressed *before* the chord formed was forgotten when arming
        # reset the verdict. Held state and press history are different questions, and
        # this is the pair that tells them apart. The one order that is not here is
        # shift arriving last — that is a break, and it has its own test below.
        for order in ((VK_LSHIFT, VK_LCONTROL, VK_LWIN),
                      (VK_LCONTROL, VK_LSHIFT, VK_LWIN)):
            with self.subTest(order=order):
                chord, presses = _chord()
                keys = _Keyboard(chord).down(*order)
                keys.up(*reversed(order))
                self.assertEqual(_fired(presses), [])

    def test_shift_arriving_last_is_a_break_like_any_other_third_key(self):
        chord, presses = _chord()
        keys = _Keyboard(chord).down(VK_LCONTROL, VK_LWIN, VK_LSHIFT)
        keys.up(VK_LSHIFT, VK_LWIN, VK_LCONTROL)
        self.assertEqual(_fired(presses), ["warm", "talk", "talk-break"])

    def test_releasing_the_extra_modifier_first_frees_the_chord_for_the_next_hold(self):
        # `_extra` is held state, so it has to clear on release. If it latched, one
        # accidental Shift would kill the chord for the life of the process — a defect
        # whose only symptom is that the feature stops working and never comes back.
        chord, presses = _chord()
        keys = _Keyboard(chord).down(VK_LSHIFT).up(VK_LSHIFT)
        keys.down(VK_LCONTROL, VK_LWIN).up(VK_LWIN, VK_LCONTROL)
        self.assertEqual(_fired(presses), HOLD)

    def test_one_modifier_alone_never_starts_however_long_it_is_held(self):
        for vk in (VK_LCONTROL, VK_LWIN):
            with self.subTest(vk=vk):
                chord, presses = _chord()
                _Keyboard(chord).down(vk, vk, vk).up(vk)
                self.assertEqual(_fired(presses), [])

    def test_ordinary_typing_never_starts_one(self):
        chord, presses = _chord()
        keys = _Keyboard(chord)
        for vk in (VK_A, VK_D, VK_LEFT):
            keys.down(vk).up(vk)
        self.assertEqual(_fired(presses), [])

    def test_a_key_pressed_before_the_chord_formed_is_not_the_chords_business(self):
        # Typing, then reaching for the chord, is somebody starting a new gesture — not
        # a dirty hold. The history resets when the chord forms; only what is still
        # *held* survives into the verdict.
        chord, presses = _chord()
        keys = _Keyboard(chord).down(VK_A).up(VK_A)
        keys.down(VK_LCONTROL, VK_LWIN).up(VK_LWIN, VK_LCONTROL)
        self.assertEqual(_fired(presses), HOLD)


class TestDItLearnsNothingAboutTheKeysItRejects(unittest.TestCase):
    """The narrowing of R16, asserted rather than asserted *about*.

    The claim being defended is not "Flow is trustworthy" — it is that a key outside the
    chord changes one boolean and leaves nothing behind. So the test is a state
    comparison: type different things, and check the object cannot tell them apart.
    """

    def test_two_different_keys_leave_the_object_in_identical_states(self):
        # If a virtual key were being recorded anywhere, typing `a` and typing `d` would
        # have to produce different objects. They must not.
        # Skipped by name, and the list is short on purpose: these are the per-instance
        # objects that can only ever compare unequal — a queue, a thread, a C callback.
        # *Everything else* is compared, which is what makes this a trap rather than a
        # restatement: a field added tomorrow to hold a virtual key would be compared by
        # default and would fail here.
        identity = {"presses", "_proc", "_thread", "_ready", "_hook", "_tid"}
        states = []
        for vk in (VK_A, VK_D, VK_LEFT):
            chord, _presses = _chord()
            keys = _Keyboard(chord).down(VK_LCONTROL, VK_LWIN)
            keys.down(vk).up(vk)
            states.append(vars(chord).copy())
        for other in states[1:]:
            for name, value in states[0].items():
                if name in identity:
                    continue
                with self.subTest(field=name):
                    self.assertEqual(value, other[name])

    def test_what_it_keeps_about_a_rejected_key_is_one_boolean(self):
        chord, _presses = _chord()
        keys = _Keyboard(chord).down(VK_LCONTROL, VK_LWIN)
        self.assertFalse(chord._other)
        keys.down(VK_A)
        self.assertIs(chord._other, True)

    def test_the_only_fields_it_has_are_the_ones_the_state_machine_needs(self):
        # A guard on the shape rather than on today's code: a future field holding a
        # keystroke would have to be added here first, which is the moment to argue
        # about it.
        chord, _presses = _chord()
        _Keyboard(chord).down(VK_LCONTROL, VK_LWIN, VK_A).up(VK_A, VK_LWIN, VK_LCONTROL)
        self.assertEqual(
            set(vars(chord)),
            {"presses", "mods", "action", "warm_action", "end_action", "break_action",
             "toggle_action", "gesture", "installed", "_down", "_other", "_extra",
             "_armed", "_talking", "_hook", "_tid", "_ready", "_proc", "_thread"},
        )


class TestEItNeverSwallowsAKeystroke(unittest.TestCase):
    """Ctrl and Win have real jobs, and Flow does not get to keep them."""

    def test_every_event_reaches_the_next_hook(self):
        chord, _presses = _chord()
        keys = _Keyboard(chord).down(VK_LCONTROL, VK_LWIN, VK_A)
        keys.up(VK_A, VK_LWIN, VK_LCONTROL)
        self.assertTrue(keys.passed)
        for message, vk, passed_on in keys.passed:
            with self.subTest(message=message, vk=vk):
                self.assertTrue(passed_on)

    def test_including_the_release_that_fired_the_chord(self):
        # The one most likely to be lost to a `return 1` added in a hurry — and losing it
        # means the Ctrl release never reaches the app, which strands every ctrl-
        # shortcut in whatever window had focus.
        chord, presses = _chord()
        keys = _Keyboard(chord).down(VK_LCONTROL, VK_LWIN).up(VK_LWIN)
        self.assertEqual(_fired(presses), HOLD)
        self.assertTrue(keys.passed[-1][2])

    def test_a_negative_code_is_passed_on_without_being_looked_at(self):
        # `nCode < 0` means "pass it on without looking", and it is not advice. A hook
        # that inspected those events anyway is a hook that can fire on something the OS
        # explicitly said not to read.
        chord, presses = _chord()
        chord._down["ctrl"] = chord._down["win"] = True
        chord._armed = True
        block = hotkey._KBDLLHOOKSTRUCT(vkCode=VK_LWIN, scanCode=0, flags=0, time=0,
                                        dwExtraInfo=None)
        with mock.patch.object(hotkey, "user32") as fake:
            fake.CallNextHookEx.return_value = 0
            chord._on_key(-1, WM_KEYUP, ctypes.addressof(block))
            self.assertTrue(fake.CallNextHookEx.called)
        self.assertEqual(_fired(presses), [])
        self.assertTrue(chord._armed)


class TestFTheHookIsTornDownByWhoeverOwnsGlobalKeyInput(unittest.TestCase):
    """A hook left installed is one the OS calls into a dead interpreter."""

    def test_stopping_the_hotkeys_stops_the_chord(self):
        # The pill already calls `hotkeys.stop()` on the way out, and there should be
        # exactly one thing that owns the teardown of "global key input". Hanging the
        # chord off `Hotkeys` is what makes that true without `flow/ui.py` learning a
        # second name.
        hotkeys = hotkey.Hotkeys(hotkey.DEFAULT_BINDINGS)
        chord, _presses = _chord()
        hotkeys.chord = chord
        with mock.patch.object(chord, "stop") as stop:
            with mock.patch.object(hotkey, "user32"):
                hotkeys.stop()
        self.assertTrue(stop.called)

    def test_hotkeys_without_a_chord_still_stop_cleanly(self):
        # The `--no-chord` and hook-refused paths both leave `chord` as None, and the
        # quit path must not care which one it is looking at.
        hotkeys = hotkey.Hotkeys(hotkey.DEFAULT_BINDINGS)
        self.assertIsNone(hotkeys.chord)
        with mock.patch.object(hotkey, "user32"):
            hotkeys.stop()

    def test_a_refused_hook_is_a_false_from_start_and_not_a_crash(self):
        # `SetWindowsHookExW` answers NULL when the OS refuses — policy, another process,
        # a desktop this one cannot reach into. Not fatal: the registered toggle is still
        # there, and `flow/__main__.py` has a line to print about it.
        chord, _presses = _chord()
        with mock.patch.object(chord, "_install", return_value=None):
            self.assertFalse(chord.start(timeout=5.0))
        self.assertFalse(chord.installed)

    def test_a_raising_install_is_the_same_event_as_a_refused_one(self):
        # The failure that would otherwise surface as a traceback on a daemon thread's
        # stderr — which on a windowed build is nowhere at all — while `start()` blocked
        # for the whole timeout waiting for a flag nobody was going to set.
        chord, _presses = _chord()
        with mock.patch.object(hotkey, "user32") as fake:
            fake.SetWindowsHookExW.side_effect = OSError("refused")
            self.assertFalse(chord.start(timeout=5.0))
        self.assertFalse(chord.installed)

    def test_the_callback_is_held_so_the_os_cannot_call_a_collected_one(self):
        # Without a reference on the instance the `WINFUNCTYPE` object is collected while
        # still installed, and the process dies inside a keystroke somewhere unrelated —
        # a crash with no connection to anything Flow was doing.
        chord, _presses = _chord()
        self.assertIsNotNone(chord._proc)
        self.assertIn("_proc", vars(chord))



if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
