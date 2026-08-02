"""The right-click menu after the split, and the one setting it gained.

Two things are pinned here and they are separate promises. The **shape**: what was one
tap stays one tap, and everything somebody sets once moves under Settings — a flat list
that grows with every feature is one nobody scans, and the menu is also a native modal
loop that stalls the UI thread while it is open, so it cannot become a page. The
**trigger word**: a curated list rather than a text box, because a word typed into a
dialog cannot be measured before it is live, and every word offered here has already been
through the gate in `test_triggers.py`.

The alternatives were argued and rejected on the record (docs/decisions.md, "First public
feedback"): free text breaches the no-settings-dialog stance a fourth time, and
speak-to-set writes configuration through the accented decoder this product exists to
work around.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.edits import (  # noqa: E402
    SEND_ENTER_WORD,
    SEND_WORD,
    SEND_WORD_PRESETS,
    enter_word,
)
from flow.profile import Profile  # noqa: E402
from flow.speak import Voice  # noqa: E402


class FakeVar:
    """A `tk.StringVar` with no interpreter behind it, so the tick is readable."""

    def __init__(self, value="", **kw) -> None:
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


class FakeMenu:
    """Records what was built. Radio entries keep their value, which is the tick."""

    def __init__(self, *a, **kw) -> None:
        self.commands: dict = {}
        self.radios: list[tuple[str, str]] = []
        self.cascades: dict = {}
        self.order: list[str] = []

    def add_command(self, label="", command=None, **kw) -> None:
        self.commands[label] = command
        self.order.append(label)

    def add_radiobutton(self, label="", value="", command=None, **kw) -> None:
        self.commands[label] = command
        self.radios.append((label, value))
        self.order.append(label)

    def add_separator(self) -> None: ...

    def add_cascade(self, label="", menu=None, **kw) -> None:
        self.cascades[label] = menu
        self.order.append(label)

    def tk_popup(self, *a) -> None: ...

    def grab_release(self) -> None: ...


class Menu(unittest.TestCase):
    """Builds the real `Pill._menu` against fakes, and hands back the top-level menu."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        self.notes: list[str] = []

    def profile(self) -> Profile:
        return Profile(self.folder / "profile.json")

    def build(self, profile=None, *, speaker=None, converse=False, clis=(),
              workspace=None, voices=()) -> FakeMenu:
        import tkinter as tk

        import flow.ui as ui

        built: list[FakeMenu] = []

        def make(*a, **kw):
            built.append(FakeMenu())
            return built[-1]

        self.pill = pill = ui.Pill.__new__(ui.Pill)
        pill.session = mock.Mock(
            mode=ui.State.DRAFT if converse else ui.DICTATE,
            speaker=speaker, profile=profile, muted=False, auto_ask=True, cli=None,
            send_words=(SEND_WORD, SEND_ENTER_WORD), workspace=workspace,
        )
        pill.session.voices.return_value = list(voices)
        pill.settings_path = self.folder / "lexicon.txt"
        pill.hotkeys = None
        pill.bubble = mock.Mock()
        pill.bubble.note = self.notes.append
        pill._clis = []
        pill._flash = 0
        with mock.patch.object(tk, "Menu", make), \
                mock.patch.object(tk, "StringVar", FakeVar), \
                mock.patch.object(ui, "available", return_value=list(clis)), \
                mock.patch.object(ui, "foreground_hwnd", return_value=0), \
                mock.patch.object(ui, "toplevel_hwnd", return_value=0), \
                mock.patch.object(ui, "_user32"):
            pill._menu(mock.Mock(x_root=0, y_root=0))
        return built[0]


class TestWhatStaysOneTap(Menu):
    """The split is by how often a tap is the answer, not by category."""

    ESSENTIALS = ("Send", "Converse mode", "Clear draft", "Quit")

    def test_the_essentials_are_still_at_the_top(self):
        top = self.build(self.profile())
        for label in self.ESSENTIALS:
            with self.subTest(label=label):
                self.assertIn(label, top.commands)

    def test_and_the_two_submenus_are_the_only_things_added(self):
        top = self.build(self.profile())
        self.assertEqual(sorted(top.cascades), ["Help", "Settings"])

    def test_the_once_only_settings_left_the_top_level(self):
        # The list this replaces carried all of these inline, in one column, above Quit.
        top = self.build(self.profile())
        for label in ("Open settings folder", "Voice", "Agent CLI", "Trigger word",
                      "Never offer"):
            with self.subTest(label=label):
                self.assertNotIn(label, top.commands)
                self.assertNotIn(label, top.cascades)

    def test_quit_is_last_so_it_is_where_it_has_always_been(self):
        self.assertEqual(self.build(self.profile()).order[-1], "Quit")

    def test_the_mode_toggle_names_the_mode_it_switches_to(self):
        self.assertIn("Converse mode", self.build(self.profile()).commands)
        self.assertIn("Dictate mode", self.build(self.profile(), converse=True).commands)


class TestWhatMovedInside(Menu):
    def settings(self, *a, **kw) -> FakeMenu:
        return self.build(*a, **kw).cascades["Settings"]

    def test_settings_carries_the_trigger_word_and_the_folder(self):
        s = self.settings(self.profile())
        self.assertIn("Trigger word", s.cascades)
        self.assertIn("Open settings folder", s.commands)

    def test_the_voice_entries_appear_only_when_there_is_a_speaker(self):
        self.assertNotIn("Mute replies", self.settings(self.profile()).commands)
        self.assertIn("Mute replies",
                      self.settings(self.profile(), speaker=mock.Mock()).commands)

    def test_the_auto_ask_toggle_appears_only_in_converse_mode(self):
        # It decides whether words leave the machine with no press, which is a question
        # that does not exist in dictate mode.
        self.assertNotIn("Ask only when I press it",
                         self.settings(self.profile()).commands)
        self.assertIn("Ask only when I press it",
                      self.settings(self.profile(), converse=True).commands)

    def test_the_cli_picker_appears_only_when_there_is_a_choice(self):
        # `Mock(name=...)` names the mock rather than setting the attribute, and the
        # picker builds its labels from `.name`.
        def cli(name):
            c = mock.Mock()
            c.name = name
            return c

        one = [cli("codex")]
        two = [cli("codex"), cli("claude")]
        self.assertNotIn("Agent CLI", self.settings(self.profile(), clis=one).cascades)
        self.assertIn("Agent CLI", self.settings(self.profile(), clis=two).cascades)


class TestTheTriggerWordIsAChoiceFromAList(Menu):
    def triggers(self, profile) -> FakeMenu:
        return self.build(profile).cascades["Settings"].cascades["Trigger word"]

    def test_every_shipped_preset_is_offered(self):
        sub = self.triggers(self.profile())
        self.assertEqual([label for label, _ in sub.radios], list(SEND_WORD_PRESETS))

    def test_the_current_word_is_the_one_ticked(self):
        p = self.profile()
        p.send_word, p.send_enter_word = "mango", "enter mango"
        self.triggers(p)
        self.assertEqual(self.pill._trigger_var.get(), "mango")

    def test_a_word_set_by_hand_is_listed_first_rather_than_dropped(self):
        # Otherwise the menu opens with nothing ticked, which reads as no word being
        # set — and profile.json stays the path for a fully custom word.
        p = self.profile()
        p.send_word, p.send_enter_word = "pelican", "enter pelican"
        sub = self.triggers(p)
        self.assertEqual(sub.radios[0], ("pelican", "pelican"))
        self.assertEqual(self.pill._trigger_var.get(), "pelican")

    def test_there_is_no_way_to_type_a_word_anywhere_in_the_menu(self):
        # The rejected design, asserted rather than trusted: every entry under Trigger
        # word is one of the measured presets, and nothing invites free text.
        p = self.profile()
        sub = self.triggers(p)
        self.assertTrue(all(label in SEND_WORD_PRESETS for label, _ in sub.radios))
        for label in sub.commands:
            with self.subTest(label=label):
                self.assertNotIn("...", label)

    def test_no_profile_means_no_submenu_rather_than_one_that_forgets(self):
        s = self.build(None).cascades["Settings"]
        self.assertNotIn("Trigger word", s.cascades)


class TestTheTapStoresBothWords(Menu):
    def tap(self, profile, word: str) -> None:
        sub = self.build(profile).cascades["Settings"].cascades["Trigger word"]
        sub.commands[word]()

    def test_it_writes_the_word_and_the_derived_enter_variant(self):
        p = self.profile()
        self.tap(p, "rocket")
        self.assertEqual((p.send_word, p.send_enter_word), ("rocket", "enter rocket"))

    def test_and_it_survives_a_reload_because_it_was_saved_on_the_tap(self):
        # Saved now rather than at the next Send: a choice made just before closing the
        # app is still a choice.
        p = self.profile()
        self.tap(p, "tango")
        again = Profile(p.path)
        self.assertEqual((again.send_word, again.send_enter_word),
                         ("tango", "enter tango"))

    def test_the_note_says_both_words_that_were_stored(self):
        self.tap(self.profile(), "falcon")
        said = " | ".join(self.notes)
        self.assertIn("falcon", said)
        self.assertIn("enter falcon", said)

    def test_the_enter_variant_is_derived_and_never_asked_for(self):
        # One rule with no special case, including for the word already current: the
        # note is what makes the overwrite visible rather than silent.
        p = self.profile()
        p.send_word, p.send_enter_word = "mango", "submit mango"
        self.tap(p, "mango")
        self.assertEqual(p.send_enter_word, enter_word("mango"))
        self.assertIn("enter mango", " | ".join(self.notes))

    def test_the_stored_word_is_what_the_router_then_uses(self):
        # The point of the setting, checked end to end rather than at the file: the
        # session reads the profile, so a tap changes what fires.
        from flow.session import Session

        p = self.profile()
        self.tap(p, "banana")
        s = Session.__new__(Session)
        s.profile = p
        self.assertEqual(Session.send_words.fget(s), ("banana", "enter banana"))

    def test_a_profile_that_cannot_be_saved_says_so_instead_of_pretending(self):
        p = self.profile()
        with mock.patch.object(Profile, "save", return_value=False):
            self.tap(p, "rocket")
        self.assertIn("could not save", " | ".join(self.notes))


class TestTheWorkspaceIsARecentsList(Menu):
    """Item 36: where converse questions are asked from, as places already chosen.

    Recents rather than a browse dialog or a text field, because a path typed into a
    dialog is free text with separators and the no-settings-dialog stance stands. New
    paths enter once via `--cwd`; after that they are a tap. "(not set)" is a real
    entry because running without a project is a real choice.
    """

    def workspaces(self, profile, workspace=None):
        settings = self.build(profile, workspace=workspace).cascades["Settings"]
        return settings.cascades.get("Workspace")

    def test_recents_are_offered_radio_checked_with_not_set_last(self):
        p = self.profile()
        a, b = self.folder / "acme", self.folder / "globex"
        a.mkdir()
        b.mkdir()
        p.note_workspace(str(a))
        p.note_workspace(str(b))
        sub = self.workspaces(p, workspace=str(b))
        self.assertEqual([v for _l, v in sub.radios], [str(b), str(a), "(not set)"])
        self.assertEqual(sub.radios[-1][0], "(not set)")
        self.assertEqual(self.pill._workspace_var.get(), str(b))

    def test_no_workspace_means_the_not_set_row_is_the_one_ticked(self):
        # The row's value is the label itself, never "": measured on real Tk, an
        # empty radiobutton -value reads as *unset* and falls back to the label, so a
        # var holding "" matches no row and the tick silently never draws. What this
        # pins is the agreement — the var's no-workspace value IS a row's value.
        p = self.profile()
        a = self.folder / "acme"
        a.mkdir()
        p.note_workspace(str(a))
        sub = self.workspaces(p, workspace=None)
        self.assertEqual(self.pill._workspace_var.get(), "(not set)")
        self.assertIn(("(not set)", "(not set)"), sub.radios)

    def test_a_current_workspace_off_the_list_is_shown_rather_than_dropped(self):
        # The hand-set trigger word's rule, same reason: the menu must never open
        # with nothing ticked, and `--cwd` wins over the profile without joining it.
        p = self.profile()
        cur = self.folder / "current"
        cur.mkdir()
        sub = self.workspaces(p, workspace=str(cur))
        self.assertEqual(sub.radios[0], (str(cur), str(cur)))
        self.assertEqual(self.pill._workspace_var.get(), str(cur))

    def test_a_missing_folder_is_shown_and_marked_rather_than_hidden(self):
        # The stale-path honesty resolve_workspace applies at startup, extended to
        # the menu: a project on a detached drive is still a place the user knows.
        p = self.profile()
        gone = self.folder / "moved-away"
        p.note_workspace(str(gone))
        sub = self.workspaces(p)
        label, value = sub.radios[0]
        self.assertIn("missing", label)
        self.assertEqual(value, str(gone))

    def test_a_tap_hands_the_path_to_the_session(self):
        p = self.profile()
        a = self.folder / "acme"
        a.mkdir()
        p.note_workspace(str(a))
        sub = self.workspaces(p)
        sub.commands[str(a)]()
        self.pill.session.set_workspace.assert_called_once_with(str(a))

    def test_the_not_set_tap_hands_over_none(self):
        p = self.profile()
        a = self.folder / "acme"
        a.mkdir()
        p.note_workspace(str(a))
        sub = self.workspaces(p)
        sub.commands["(not set)"]()
        self.pill.session.set_workspace.assert_called_once_with(None)

    def test_no_profile_and_nothing_to_offer_both_mean_no_submenu(self):
        # An entry that silently forgets is worse than one that is not there — and a
        # menu of only "(not set)" is a control with nothing to switch between.
        self.assertIsNone(self.workspaces(None))
        self.assertIsNone(self.workspaces(self.profile()))

    def test_every_entry_is_a_stored_path_or_not_set_and_nothing_invites_typing(self):
        p = self.profile()
        a = self.folder / "a"
        a.mkdir()
        p.note_workspace(str(a))
        sub = self.workspaces(p)
        self.assertEqual([v for _l, v in sub.radios], [str(a), "(not set)"])
        for label in sub.commands:
            with self.subTest(label=label):
                self.assertNotIn("...", label)

    def test_a_long_path_is_cut_from_the_left_so_the_leaf_survives(self):
        # A path's discriminating half is its tail; the tap still gets the whole
        # path, because the label is presentation and the value is the choice.
        p = self.profile()
        deep = self.folder.joinpath(*["x" * 12] * 8)
        deep.mkdir(parents=True)
        p.note_workspace(str(deep))
        sub = self.workspaces(p)
        label, value = sub.radios[0]
        self.assertLessEqual(len(label), 60)
        self.assertTrue(label.startswith("…"))
        self.assertTrue(str(deep).endswith(label[1:]))
        self.assertEqual(value, str(deep))


class TestTheVoiceMenuCanTickEngineDefault(Menu):
    """Found while probing item 36: the Voice menu had the Workspace defect already.

    A menu radiobutton built with `value=""` reads back with its *label* as the value —
    measured on real Tk, an empty `-value` is treated as unset and falls back — so
    `_voice_var`, holding "" for the engine default, matched no row and the submenu
    opened with no tick anywhere until a voice was chosen. Same fix as Workspace: a
    non-empty sentinel as both label and value, the var defaulting to it, and the tap
    still handing the session None.
    """

    def voice_sub(self, *, chosen=None) -> FakeMenu:
        speaker = mock.Mock(voice=chosen)
        menu = self.build(self.profile(), speaker=speaker,
                          voices=[Voice("Microsoft George", "Male", "en-GB")])
        return menu.cascades["Settings"].cascades["Voice"]

    def test_no_voice_chosen_means_the_engine_default_row_is_the_one_ticked(self):
        # What this pins is the agreement the workspace test pins: the var's
        # no-choice value IS a row's value, and that value is never "".
        sub = self.voice_sub(chosen=None)
        self.assertEqual(self.pill._voice_var.get(), "Engine default")
        self.assertIn(("Engine default", "Engine default"), sub.radios)

    def test_a_chosen_voice_still_ticks_its_own_row(self):
        sub = self.voice_sub(chosen="Microsoft George")
        self.assertEqual(self.pill._voice_var.get(), "Microsoft George")
        self.assertIn(("Microsoft George (male, en-GB)", "Microsoft George"),
                      sub.radios)

    def test_the_engine_default_tap_still_hands_over_none(self):
        sub = self.voice_sub(chosen=None)
        sub.commands["Engine default"]()
        self.pill.session.set_voice.assert_called_once_with(None)


if __name__ == "__main__":
    unittest.main()
