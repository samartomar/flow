"""Rebinding the five global combos from `profile.json`, and refusing to guess.

The shipped table is five opinions, and one of them was wrong on the machine this app
was built on: `ctrl+alt+space` was already owned by another program, which is why every
action has a fallback list at all. The people who ask for rebinding are asking about the
same collision on a machine nobody here can see — so the answer is the file they already
own, read once at launch, with no dialog and no new surface.

Three properties are worth more than the parsing, and each is a way this could be worse
than not shipping it:

  **A chosen combo cannot leave an action dead.** The override goes in *front* of the
  shipped alternatives, never in place of them. Somebody who picks a combo their IDE
  already owns still gets a working Flow, and finds out from the startup block which
  combo they actually got.

  **Nothing is thrown away quietly** (P2). A typo'd action name, an unreadable combo, a
  value that is not even a string: each is refused by name, with what was wrong with it,
  on the same lines that report what did register. A shortcut that silently does nothing
  is the defect `Hotkeys.failed` was built for, and a rebind that silently does nothing
  is the same defect wearing a feature's name.

  **The report stays true.** `Hotkeys.chosen` is what `RegisterHotKey` accepted and not
  what anyone asked for, and the Help sheet and the startup block both read from it. An
  override that was taken has to disappear from both, which is checked here rather than
  assumed, because the whole value of that sheet is that it describes this machine.

Registration is driven against a modelled `user32` rather than the real one: the suite
must not hand global combos to the OS on a developer's desk, and the behaviour under
test is *which call is the first to succeed*, which a fake that says yes to everything
could not show.
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Windows-only: ctypes.WinDLL, bound at import.
#
# The guard has to be here rather than on the classes below, and the argument is
# `tests/test_inject_target.py`'s word for word: `flow.hotkey` calls
# `ctypes.WinDLL("user32", use_last_error=True)` at module scope, so the failure would be
# the `import` two lines down, before any test exists to decorate. Deliberate over there
# — the module is Win32 end to end, and a lazily bound `user32` would only move the same
# import error to the first press.
if sys.platform != "win32":  # pragma: no cover - the CI legs that are not Windows
    raise unittest.SkipTest("Windows-only: flow.hotkey binds user32 at import")

import flow.hotkey as hotkey  # noqa: E402
from flow.hotkey import (  # noqa: E402
    BAD_BLOCK_LINE,
    DEFAULT_BINDINGS,
    KEYS,
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_SHIFT,
    MOD_WIN,
    Hotkeys,
    describe,
    overridden,
    parse,
)


class TestACombosMeaningIsReadOffWhatSomebodyTyped(unittest.TestCase):
    """`parse`, on the strings the guide prints and the shapes a hand-edit produces."""

    def test_the_three_shapes_the_guide_prints(self):
        for text, expected in (
            ("ctrl+alt+space", (MOD_CONTROL | MOD_ALT, KEYS["space"])),
            ("ctrl+shift+M", (MOD_CONTROL | MOD_SHIFT, KEYS["m"])),
            ("win+alt+space", (MOD_WIN | MOD_ALT, KEYS["space"])),
        ):
            with self.subTest(text=text):
                self.assertEqual(parse(text), (expected, ""))

    def test_case_and_spacing_are_the_writers_business(self):
        # This is JSON somebody typed by hand into a file with no editor support. A
        # shortcut that depends on where the spaces went is a bug report waiting to be
        # filed, and the person filing it would be right.
        canonical, _reason = parse("ctrl+alt+space")
        for text in ("CTRL+ALT+SPACE", "Ctrl+Alt+Space", "  ctrl + alt + space  ",
                     "cTrL+aLt+sPaCe", "ctrl+alt+space\n", "ctrl +alt+ space"):
            with self.subTest(text=text):
                self.assertEqual(parse(text)[0], canonical)

    def test_every_key_a_person_may_write_is_a_key_the_report_can_name(self):
        # The round trip that keeps the startup block honest. A key that can be *asked*
        # for and not named back would print as "vk0x31" in the one line whose whole job
        # is telling somebody which combo they got.
        for name, vk in KEYS.items():
            with self.subTest(key=name):
                binding, reason = parse(f"ctrl+alt+{name}")
                self.assertEqual(binding, (MOD_CONTROL | MOD_ALT, vk), reason)
                self.assertNotIn("vk0x", describe(*binding))

    def test_the_named_keys_are_exactly_the_ones_the_shipped_table_binds(self):
        # The bound on the vocabulary, asserted so it stays a bound. This is a way to
        # rearrange what Flow ships, not a general hotkey engine: every F-key, media key
        # and numpad code is a `VK_` constant nobody has ever pressed on this machine,
        # and an untested binding is worse than an absent one because it fails silently.
        named = {name for name in KEYS if len(name) > 1 or not name.isalnum()}
        self.assertEqual(named, {"space", "enter", "esc", "backslash", "\\"})

    def test_and_the_shipped_table_can_be_written_out_in_full(self):
        # Nobody needs to — it is what Flow already does unprompted. But a vocabulary
        # that cannot express its own defaults is one where somebody who overrode an
        # action could never write down what they had before.
        for action, alternatives in DEFAULT_BINDINGS.items():
            for mods, vk in alternatives:
                with self.subTest(action=action, combo=describe(mods, vk)):
                    self.assertEqual(parse(describe(mods, vk))[0], (mods, vk))

    def test_a_backslash_is_spellable_both_ways(self):
        # The one shipped key whose name is longer than the key. Somebody copying
        # `ctrl+alt+\` out of the guide should not have to learn that Flow calls it
        # "backslash", and somebody writing JSON should not have to remember that a lone
        # backslash needs escaping in it.
        self.assertEqual(parse("ctrl+alt+\\")[0], parse("ctrl+alt+backslash")[0])

    def test_a_digit_is_a_key_even_though_nothing_ships_bound_to_one(self):
        binding, _reason = parse("ctrl+alt+7")
        self.assertEqual(describe(*binding), "ctrl+alt+7")


class TestACombosThatCannotBeReadNamesTheWrongPart(unittest.TestCase):
    """Each refusal says which half of the string it could not use.

    Reasons and not a bare `None`, because the caller has to *say* what went wrong, and a
    reason assembled at the call site is one that will one day disagree with the check
    that produced it.
    """

    def test_an_unknown_modifier_is_named(self):
        self.assertEqual(parse("hyper+space"),
                         (None, "'hyper' is not ctrl, alt, shift or win"))

    def test_an_unknown_key_is_named(self):
        self.assertEqual(parse("ctrl+alt+f13"),
                         (None, "'f13' is not a key Flow can bind"))

    def test_nothing_at_all_is_told_apart_from_a_wrong_key(self):
        for blank in ("", "   ", "\t", "\n"):
            with self.subTest(blank=blank):
                self.assertEqual(parse(blank), (None, "blank"))

    def test_two_keys_is_a_different_misunderstanding_from_a_bad_modifier(self):
        # This person knows the syntax and asked for a chord Windows cannot register.
        # Telling them "'a' is not a modifier" would send them looking for a modifier.
        self.assertEqual(parse("ctrl+a+b"),
                         (None, "'a' is a key, and a combo takes one"))

    def test_a_value_that_is_not_a_string_at_all(self):
        for bad in (5, True, None, 3.5, ["ctrl", "alt", "space"], {"mods": "ctrl"}):
            with self.subTest(bad=bad):
                self.assertEqual(parse(bad), (None, "not text"))

    def test_modifiers_with_no_key_after_them(self):
        for text in ("ctrl+alt", "ctrl+alt+", "+", "ctrl", "shift+win"):
            with self.subTest(text=text):
                self.assertEqual(parse(text)[1], "needs a key after the modifiers")

    def test_a_key_with_no_modifier_is_refused_rather_than_registered(self):
        # The one mistake in here nobody could diagnose. `RegisterHotKey` would take
        # `space` happily, and the result is Flow owning the bare space bar system-wide
        # from the moment it launches — the app that broke their typing gives no sign of
        # being involved, and the person who wrote it into their profile is looking for a
        # dictation bug.
        self.assertEqual(parse("space"),
                         (None, "needs ctrl, alt, shift or win in front of it"))
        self.assertIsNone(parse("a")[0])

    def test_nothing_here_raises_whatever_is_in_the_file(self):
        # The file has no validation between a person and it, and a launch that dies
        # over a typo'd shortcut is a worse outcome than any shortcut being wrong.
        for bad in ("+++", "ctrl++space", "ctrl+alt+space+", "\\", "ctrl+\\+alt",
                    "—", "ctrl+alt+é", " + + ", "ctrl+alt+space+enter"):
            with self.subTest(bad=bad):
                binding, reason = parse(bad)
                self.assertIsNone(binding)
                self.assertTrue(reason)


class TestAnOverrideGoesInFrontAndTheFallbacksStay(unittest.TestCase):
    """`overridden` — the merge, which is the whole behaviour of the feature."""

    def test_a_chosen_combo_is_the_first_thing_tried(self):
        merged, ignored = overridden({"toggle": "ctrl+shift+1"})
        self.assertEqual(ignored, [])
        self.assertEqual(merged["toggle"][0], (MOD_CONTROL | MOD_SHIFT, KEYS["1"]))

    def test_and_every_shipped_alternative_is_still_behind_it(self):
        # The property that makes this safe to offer at all: a person who picks a combo
        # another program owns must still end up with a working Flow.
        merged, _ignored = overridden({"toggle": "ctrl+shift+1"})
        self.assertEqual(merged["toggle"][1:], DEFAULT_BINDINGS["toggle"])

    def test_an_action_nobody_overrode_is_untouched(self):
        merged, _ignored = overridden({"toggle": "ctrl+shift+1"})
        for action in ("send", "cancel", "mode", "quit"):
            with self.subTest(action=action):
                self.assertEqual(merged[action], DEFAULT_BINDINGS[action])

    def test_no_overrides_at_all_is_the_shipped_table(self):
        # Almost everybody, on every launch. The absent case is the ordinary one.
        for nothing in (None, {}):
            with self.subTest(nothing=nothing):
                merged, ignored = overridden(nothing)
                self.assertEqual(merged, DEFAULT_BINDINGS)
                self.assertEqual(ignored, [])

    def test_the_shipped_table_is_not_mutated_by_a_merge(self):
        # `DEFAULT_BINDINGS` is module state. Inserting into it rather than into a copy
        # would make one person's override survive into the next `Hotkeys` of the
        # process, which the suite creates several of.
        before = {action: list(alts) for action, alts in DEFAULT_BINDINGS.items()}
        overridden({"toggle": "ctrl+shift+1", "quit": "win+alt+Q"})
        self.assertEqual(DEFAULT_BINDINGS, before)

    def test_an_action_name_nobody_has_is_refused_with_its_reason(self):
        _merged, ignored = overridden({"togle": "ctrl+alt+space"})
        self.assertEqual(ignored, [
            "hotkey  'togle' in profile.json ignored: 'ctrl+alt+space' - "
            "no action has that name"
        ])

    def test_and_a_refusal_costs_the_other_four_actions_nothing(self):
        # Per entry, for the reason `profile._counter` is per entry: one unusable row in
        # a hand-edited file must not cost every other choice its author made.
        merged, ignored = overridden({"togle": "ctrl+alt+space",
                                      "send": "ctrl+shift+enter"})
        self.assertEqual(len(ignored), 1)
        self.assertEqual(merged["send"][0], (MOD_CONTROL | MOD_SHIFT, KEYS["enter"]))
        self.assertEqual(merged["toggle"], DEFAULT_BINDINGS["toggle"])

    def test_an_action_written_with_odd_case_and_spacing_still_lands(self):
        merged, ignored = overridden({"  ToGGle  ": "ctrl+shift+1"})
        self.assertEqual(ignored, [])
        self.assertEqual(merged["toggle"][0], (MOD_CONTROL | MOD_SHIFT, KEYS["1"]))

    def test_an_unreadable_combo_leaves_its_action_on_the_shipped_list(self):
        merged, ignored = overridden({"toggle": "ctrl+alt+f13"})
        self.assertEqual(merged["toggle"], DEFAULT_BINDINGS["toggle"])
        self.assertEqual(len(ignored), 1)
        self.assertIn("is not a key Flow can bind", ignored[0])

    def test_a_value_that_is_not_a_string_is_refused_rather_than_coerced(self):
        _merged, ignored = overridden({"cancel": 5})
        self.assertEqual(ignored, [
            "hotkey  'cancel' in profile.json ignored: '5' - not text"
        ])

    def test_all_five_actions_can_be_rebound_at_once(self):
        chosen = {"toggle": "win+alt+space", "send": "ctrl+shift+enter",
                  "cancel": "ctrl+shift+esc", "mode": "ctrl+shift+M",
                  "quit": "ctrl+shift+Q"}
        merged, ignored = overridden(chosen)
        self.assertEqual(ignored, [])
        for action, combo in chosen.items():
            with self.subTest(action=action):
                self.assertEqual(describe(*merged[action][0]), parse_name(combo))


def parse_name(combo: str) -> str:
    """The combo as `describe` would write it, which is the form the report uses."""
    binding, _reason = parse(combo)
    return describe(*binding)


class FakeUser32:
    """`user32`, answering `RegisterHotKey` from a set of combos somebody else owns.

    Modelled rather than stubbed, because the behaviour under test is a *fallback*: what
    matters is which call is the first to succeed, and a fake that said yes to everything
    could not tell a shipped primary from a chosen one. It also refuses a combo already
    handed out in this run, exactly as Windows does — two actions pointed at one combo is
    a thing a hand-edited file can now ask for, and the answer has to be a fallback
    rather than a second registration nobody gets presses from.

    `GetMessageW` returns 0 so the message loop ends immediately: every test here is
    about what registration decided, and none of them presses a key.
    """

    def __init__(self, taken=()) -> None:
        self.taken = {parse(combo)[0] for combo in taken}
        #: Every combo the OS was asked for, in order — the fallback walk itself.
        self.asked: list[tuple[int, int]] = []
        self.live: dict[int, tuple[int, int]] = {}

    def RegisterHotKey(self, _hwnd, ident, mods, vk):
        combo = (mods & ~MOD_NOREPEAT, vk)
        self.asked.append(combo)
        if combo in self.taken or combo in self.live.values():
            return 0
        self.live[ident] = combo
        return 1

    def UnregisterHotKey(self, _hwnd, ident):
        return self.live.pop(ident, None) is not None

    def GetMessageW(self, *_args):
        return 0

    def PostThreadMessageW(self, *_args):
        return 1


class Registered(unittest.TestCase):
    """One launch's worth of registration against a machine this test describes."""

    def register(self, overrides=None, taken=()) -> tuple[Hotkeys, FakeUser32]:
        fake = FakeUser32(taken)
        with mock.patch.object(hotkey, "user32", fake):
            keys = Hotkeys(DEFAULT_BINDINGS, overrides)
            self.assertTrue(keys.start(timeout=5.0), "the hotkey thread did not start")
            # Joined inside the patch, so the loop's exit and its `UnregisterHotKey`
            # calls cannot land on the real user32 after the mock is undone.
            keys._thread.join(timeout=5.0)
        return keys, fake


class TestWhatRegisteredIsWhatIsReported(Registered):
    """`Hotkeys.chosen` is what the OS accepted, and an override does not change that."""

    def test_a_chosen_combo_is_what_the_os_is_asked_for_first(self):
        keys, fake = self.register({"toggle": "ctrl+shift+1"})
        self.assertEqual(fake.asked[0], (MOD_CONTROL | MOD_SHIFT, KEYS["1"]))
        self.assertEqual(keys.chosen["toggle"], "ctrl+shift+1")

    def test_and_the_shipped_primary_is_not_reported_once_it_is_beaten(self):
        keys, _fake = self.register({"toggle": "ctrl+shift+1"})
        self.assertNotIn("ctrl+alt+space", keys.chosen.values())

    def test_a_chosen_combo_another_app_owns_falls_back_and_flow_still_works(self):
        keys, _fake = self.register({"toggle": "ctrl+shift+1"}, taken=("ctrl+shift+1",))
        self.assertEqual(keys.chosen["toggle"], "ctrl+alt+space")
        self.assertEqual(keys.failed, [])

    def test_and_the_combo_that_was_asked_for_is_reported_nowhere(self):
        # The defect item 30 exists to prevent, one layer along: everything downstream —
        # the startup block, the Help sheet, the voice-is-down note — reads `chosen`, so
        # a combo that lost has to be absent from it rather than merely deprioritised.
        keys, _fake = self.register({"toggle": "ctrl+shift+1"}, taken=("ctrl+shift+1",))
        self.assertNotIn("ctrl+shift+1", keys.chosen.values())

    def test_every_alternative_taken_including_the_chosen_one_is_still_named(self):
        keys, _fake = self.register(
            {"send": "ctrl+shift+1"},
            taken=("ctrl+shift+1", "ctrl+alt+enter", "ctrl+shift+enter"),
        )
        self.assertEqual(keys.failed, ["send"])
        self.assertNotIn("send", keys.chosen)

    def test_two_actions_pointed_at_one_combo_do_not_both_get_it(self):
        keys, _fake = self.register({"toggle": "ctrl+shift+1", "send": "ctrl+shift+1"})
        self.assertEqual(keys.chosen["toggle"], "ctrl+shift+1")
        self.assertEqual(keys.chosen["send"], "ctrl+alt+enter")

    def test_a_refused_override_rides_on_the_object_that_reports_the_rest(self):
        keys, _fake = self.register({"toggle": "ctrl+alt+f13"})
        self.assertEqual(len(keys.ignored), 1)
        self.assertEqual(keys.chosen["toggle"], "ctrl+alt+space")

    def test_all_five_actions_still_register_with_nothing_overridden(self):
        keys, _fake = self.register()
        self.assertEqual(list(keys.chosen), ["toggle", "send", "cancel", "mode", "quit"])
        self.assertEqual(keys.failed, [])
        self.assertEqual(keys.ignored, [])


class TestTheHelpSheetStaysTrueWithoutBeingTold(Registered):
    """`help.rows` reads `chosen`, so rebinding reaches it with no code of its own.

    Checked rather than assumed, because that sheet's entire value is that it describes
    the machine somebody is sitting at — it is regenerated on every open for exactly this
    reason, and a rebind it did not know about would make it wrong in the one place it
    promises never to be.
    """

    def flat(self, keys) -> str:
        from flow.help import rows

        return " | ".join(f"{left} {right}" for _kind, left, right in rows(hotkeys=keys))

    def test_the_sheet_lists_the_chosen_combo_and_never_the_shipped_one(self):
        keys, _fake = self.register({"toggle": "ctrl+shift+1"})
        text = self.flat(keys)
        self.assertIn("ctrl+shift+1", text)
        self.assertNotIn("ctrl+alt+space", text)

    def test_and_it_lists_the_fallback_when_the_chosen_one_was_taken(self):
        keys, _fake = self.register({"toggle": "ctrl+shift+1"}, taken=("ctrl+shift+1",))
        text = self.flat(keys)
        self.assertIn("ctrl+alt+space", text)
        self.assertNotIn("ctrl+shift+1", text)

    def test_and_the_voice_is_down_note_names_the_rebound_send_key(self):
        # The line Flow says at the moment the microphone is the problem, which is the
        # one moment a wrong combo costs somebody their draft.
        from flow.help import exits_note

        keys, _fake = self.register({"send": "ctrl+shift+enter"})
        self.assertIn("ctrl+shift+enter still sends", exits_note(keys))


@contextlib.contextmanager
def profile_carrying(hotkeys):
    """A `~/.flow` of this test's own, with `hotkeys` in the profile (Rule 5)."""
    with tempfile.TemporaryDirectory() as tmp:
        import flow.diag
        import flow.profile

        path = Path(tmp) / "profile.json"
        path.write_text(json.dumps({"schema": 1, "hotkeys": hotkeys}), encoding="utf-8")
        with mock.patch.object(flow.profile, "DEFAULT_PATH", path), \
                mock.patch.object(flow.diag, "DEFAULT_PATH", Path(tmp) / "diag.jsonl"):
            yield


class TestTheStartupBlockSaysWhatItRefusedAndWhatItRegistered(unittest.TestCase):
    """End to end, because the exact text is the deliverable.

    A person whose shortcut does nothing reads this block and nothing else — the Help
    sheet is behind a right-click they have no reason to try, and the guide is a page
    away. So the wording is asserted to the character here, the way `--stats` and
    `--version` are: "prints something about hotkeys" is not a behaviour anybody can act
    on.
    """

    def launch(self, hotkeys) -> str:
        import flow.asr
        import flow.ui

        import flow.__main__ as mod

        out = io.StringIO()
        fake = FakeUser32()
        with profile_carrying(hotkeys), \
                mock.patch.object(hotkey, "user32", fake), \
                mock.patch.object(mod, "Session"), \
                mock.patch.object(flow.asr, "WhisperTranscriber"), \
                mock.patch.object(flow.ui, "Pill") as pill, \
                contextlib.redirect_stdout(out):
            self.assertEqual(mod.main(["--no-speak", "--no-lexicon"]), 0)
            keys = pill.call_args.kwargs["hotkeys"]
            if keys is not None:
                keys._thread.join(timeout=5.0)
        return out.getvalue()

    def hotkey_lines(self, hotkeys) -> list[str]:
        return [ln for ln in self.launch(hotkeys).splitlines()
                if ln.startswith("hotkey")]

    def test_an_unreadable_override_is_named_before_the_combos_that_registered(self):
        lines = self.hotkey_lines({"toggle": "ctrl+alt+f13"})
        self.assertEqual(lines[0],
                         "hotkey  'toggle' in profile.json ignored: 'ctrl+alt+f13' - "
                         "'f13' is not a key Flow can bind")

    def test_and_the_line_under_it_is_the_combo_that_registered_instead(self):
        # The refusal and its consequence, in that order, so the block reads as what
        # happened. It is also why the refusal does not go on to list the five action
        # names: the next five lines are the five action names.
        lines = self.hotkey_lines({"toggle": "ctrl+alt+f13"})
        self.assertEqual(lines[1], "hotkey  toggle   ctrl+alt+space")

    def test_a_refusal_is_said_once_and_not_once_per_action(self):
        lines = self.hotkey_lines({"toggle": "ctrl+alt+f13"})
        self.assertEqual(sum(1 for ln in lines if "ignored" in ln), 1)

    def test_a_usable_override_registers_and_draws_no_complaint(self):
        lines = self.hotkey_lines({"toggle": "ctrl+shift+1"})
        self.assertEqual(lines[0], "hotkey  toggle   ctrl+shift+1")
        self.assertNotIn("ignored", " ".join(lines))

    def test_a_block_that_is_not_a_table_is_named_rather_than_shrugged_off(self):
        # `Profile` degrades the whole field here — there are no entries to refuse one at
        # a time — so this line is the only thing standing between a person and a
        # silently ignored file.
        lines = self.hotkey_lines("ctrl+alt+space")
        self.assertEqual(lines[0], BAD_BLOCK_LINE)
        self.assertEqual(lines[1], "hotkey  toggle   ctrl+alt+space")

    def test_a_launch_with_no_hotkeys_block_prints_only_what_registered(self):
        lines = self.hotkey_lines({})
        self.assertEqual(len(lines), 5)
        self.assertNotIn("ignored", " ".join(lines))

    def test_a_block_typed_by_hand_survives_the_whole_way_to_registration(self):
        # The one path nobody rehearses: JSON with no editor helping, written by somebody
        # who has just read the guide. Case and spacing are theirs to get wrong on both
        # sides of the colon, and the normalisation that fixes it happens two modules
        # apart from the file — `profile.json` carries the strings as typed, and this is
        # the only test that watches them come out the far end as combos.
        lines = self.hotkey_lines({"  ToGGle ": "  CTRL + Shift + 1  ",
                                   "QUIT": "Win+Alt+q"})
        self.assertEqual(lines[0], "hotkey  toggle   ctrl+shift+1")
        self.assertEqual(lines[4], "hotkey  quit     alt+win+Q")
        self.assertNotIn("ignored", " ".join(lines))


class TestEveryRefusalIsOneAsciiLine(unittest.TestCase):
    """`say()` prints these, and a redirected stdout uses the locale encoding.

    Both halves of every one of these lines are quoted back out of a file somebody typed
    into, which makes this the only place in Flow where user text reaches the console.
    A cp437 console cannot encode an accented letter, so an override written as
    `ctrl+alt+e` with an acute on the e would raise `UnicodeEncodeError` in place of the
    entire startup block — the one line saying that combo could not be read included.
    """

    def every_line(self) -> list[str]:
        lines = [BAD_BLOCK_LINE]
        for name, combo in (
            ("togle", "ctrl+alt+space"),      # no such action
            ("toggle", "ctrl+alt+f13"),       # no such key
            ("send", "hyper+enter"),          # no such modifier
            ("cancel", ""),                   # blank
            ("mode", "ctrl+a+b"),             # two keys
            ("quit", 5),                      # not text
            ("toggle", "ctrl+alt"),           # no key
            ("toggle", "space"),              # no modifier
            # The shapes only a hand-edit produces, which is the whole population here.
            ("toggle", "ctrl+alt+é"),
            ("—", "—"),
            ("toggle", "ctrl+alt+" + "x" * 400),
            ("t" * 400, "ctrl+alt+space"),
            ("toggle", "ctrl\t+\nalt+space"),
        ):
            _merged, ignored = overridden({name: combo})
            lines += ignored
        return lines

    def test_every_line_encodes_on_a_legacy_console_and_in_ascii(self):
        for line in self.every_line():
            with self.subTest(line=line):
                line.encode("cp437")
                line.encode("ascii")

    def test_and_every_one_of_them_is_a_single_line(self):
        for line in self.every_line():
            with self.subTest(line=line):
                self.assertNotIn("\n", line)
                self.assertNotIn("\t", line)

    def test_a_four_hundred_character_hand_edit_does_not_fill_the_screen(self):
        # The bound exists for the invalid case only: the longest combo anybody can
        # legally write is `ctrl+alt+shift+win+backslash` at 28 characters, so nothing
        # valid is ever cut.
        for name, combo in (("toggle", "ctrl+alt+" + "x" * 400),
                            ("t" * 400, "ctrl+alt+space")):
            with self.subTest(name=name[:8]):
                _merged, ignored = overridden({name: combo})
                self.assertLessEqual(len(ignored[0]), 160)
                self.assertNotIn("x" * 40, ignored[0])
                self.assertNotIn("t" * 40, ignored[0])

    def test_an_ordinary_mistake_fits_a_console_width(self):
        # Not a hard rule anywhere in this project, but these are read at a prompt and a
        # wrapped sentence is one somebody stops reading.
        for line in self.every_line():
            if "x" * 20 not in line and "t" * 20 not in line:
                with self.subTest(line=line):
                    self.assertLessEqual(len(line), 105)


if __name__ == "__main__":
    unittest.main()
