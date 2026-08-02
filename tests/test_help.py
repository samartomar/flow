"""The help sheet has to describe *this* machine, or it is worse than no help sheet.

Two failures are possible and only one of them is obvious. The obvious one is a stale
file: `ctrl+alt+space` is the first alternative in `DEFAULT_BINDINGS` and was already
owned by another app on the development machine, so a shipped sheet would name a combo
that does nothing here. The quieter one is a sheet that documents a command the router
does not have - the product telling somebody who went looking for help to say a sentence
that will be typed into their draft. So every example in the sheet is routed, and the
family it is filed under is asserted rather than described.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow import help as helpfile  # noqa: E402
from flow.edits import SEND_ENTER_WORD, SEND_WORD, TAKE_VERBS, plan  # noqa: E402


class FakeHotkeys:
    """What `Hotkeys` looks like after `start()`: what registered, and what could not."""

    def __init__(self, chosen: dict, failed=()) -> None:
        self.chosen = chosen
        self.failed = list(failed)


REGISTERED = {"toggle": "ctrl+shift+space", "send": "ctrl+alt+enter",
              "mode": "ctrl+alt+M", "quit": "ctrl+alt+Q"}


class TestItNamesWhatRegistered(unittest.TestCase):
    def test_the_combo_that_registered_is_the_one_shown(self):
        text = helpfile.sheet(hotkeys=FakeHotkeys(REGISTERED))
        self.assertIn("ctrl+shift+space", text)

    def test_and_the_default_it_fell_back_from_appears_nowhere(self):
        # The whole reason this file is generated. ctrl+alt+space is `DEFAULT_BINDINGS`'
        # first alternative and is taken on this machine; a sheet naming it would send
        # the user to a key that cannot arm the mic.
        text = helpfile.sheet(hotkeys=FakeHotkeys(REGISTERED))
        self.assertNotIn("ctrl+alt+space", text)

    def test_an_action_that_could_not_register_is_named_as_unavailable(self):
        text = helpfile.sheet(hotkeys=FakeHotkeys(REGISTERED, failed=["cancel"]))
        line = next(ln for ln in text.splitlines() if ln.strip().startswith("cancel"))
        self.assertIn("NOT AVAILABLE", line)

    def test_no_hotkeys_at_all_is_a_sentence_rather_than_a_hole(self):
        # `--no-hotkeys` is a supported way to run, and an empty section reads as a bug
        # in the help rather than as a choice the user made at launch.
        text = helpfile.sheet(hotkeys=None)
        self.assertIn("--no-hotkeys", text)

    def test_every_action_that_registered_gets_a_line(self):
        text = helpfile.sheet(hotkeys=FakeHotkeys(REGISTERED))
        for action, combo in REGISTERED.items():
            with self.subTest(action=action):
                self.assertIn(combo, text)


class TestItNamesTheWordsCurrentlyConfigured(unittest.TestCase):
    def test_a_stored_trigger_is_what_the_sheet_shows(self):
        text = helpfile.sheet(send_words=("goose", "enter goose"))
        self.assertIn("goose", text)
        self.assertIn("enter goose", text)

    def test_and_the_shipped_default_is_not_still_advertised(self):
        # Said as its own check because the failure is silent: the user renamed the
        # trigger, the sheet kept naming the old word, and the old word no longer works.
        text = helpfile.sheet(send_words=("goose", "enter goose"))
        shown = [ln for ln in text.splitlines() if ln.startswith("  goose")
                 or ln.startswith("  enter goose")]
        self.assertEqual(len(shown), 2, text)
        # Nowhere at all, not merely absent from the two lines that list it. The prose
        # around them used to illustrate whole-utterance matching with "boom goes the
        # dynamite", which is exactly the kind of sentence that survives a rename and
        # then teaches somebody a word that no longer works.
        self.assertNotIn(SEND_WORD, text)

    def test_with_nothing_passed_it_shows_the_shipped_pair(self):
        text = helpfile.sheet()
        self.assertIn(SEND_WORD, text)
        self.assertIn(SEND_ENTER_WORD, text)

    def test_the_workshop_line_is_the_one_the_session_resolved(self):
        text = helpfile.sheet(workspace_note=r"workshop: D:\dev\products\widget")
        self.assertIn(r"workshop: D:\dev\products\widget", text)

    def test_an_unset_workshop_still_says_something_true(self):
        self.assertIn("workshop: not set", helpfile.sheet())


class TestEveryExampleIsRealSpeech(unittest.TestCase):
    """The check that stops the sheet from documenting a command nobody has."""

    def routed(self, utterance: str, triggers=(SEND_WORD, SEND_ENTER_WORD)) -> str:
        p = plan(utterance, helpfile.EXAMPLE_DRAFT, triggers)
        return f"{p.kind}/{p.op}"

    def test_each_example_routes_to_the_family_it_is_filed_under(self):
        for say, _does, route in helpfile.COMMANDS:
            with self.subTest(say=say):
                self.assertEqual(self.routed(say), route)

    def test_every_example_appears_in_the_rendered_sheet(self):
        text = helpfile.sheet()
        for say, does, _route in helpfile.COMMANDS:
            with self.subTest(say=say):
                self.assertIn(say, text)
                self.assertIn(does, text)

    def test_the_take_verbs_come_from_the_grammar_and_all_of_them_work(self):
        text = helpfile.sheet()
        for verb in TAKE_VERBS:
            with self.subTest(verb=verb):
                self.assertEqual(self.routed(f"{verb} that answer"), "take/")
                self.assertIn(f"{verb} that answer", text)

    def test_the_trigger_words_shown_are_the_ones_that_would_fire(self):
        # The sheet is rendered from a pair, and the same pair is what `plan()` is given
        # at runtime. Routed here so a sheet cannot show a word the router is not using.
        self.assertEqual(self.routed("goose", ("goose", "enter goose")), "send_trigger/")
        self.assertEqual(self.routed("enter goose", ("goose", "enter goose")),
                         "send_trigger/enter")

    def test_the_example_draft_is_what_makes_the_examples_legal(self):
        # Half these operations only route because their target is present. If the draft
        # drifts away from the examples, this says so instead of the sheet going quietly
        # wrong.
        for target in ("Tuesday", "Sameer", "release notes", "NASA"):
            with self.subTest(target=target):
                self.assertIn(target, helpfile.EXAMPLE_DRAFT)


class TestTheFileOnDisk(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())

    def test_it_lands_in_the_settings_folder_under_a_name_that_says_what_it_is(self):
        path = helpfile.write(self.folder)
        self.assertEqual(path, self.folder / "commands.txt")
        self.assertTrue(path.exists())

    def test_a_second_open_replaces_it_rather_than_growing_it(self):
        # Regenerated, not appended: a sheet that says two things about one hotkey is
        # the stale-file failure with extra steps.
        helpfile.write(self.folder, hotkeys=FakeHotkeys(REGISTERED))
        first = (self.folder / "commands.txt").read_text(encoding="utf-8")
        path = helpfile.write(self.folder, hotkeys=FakeHotkeys(REGISTERED))
        self.assertEqual(path.read_text(encoding="utf-8"), first)

    def test_it_overwrites_whatever_somebody_typed_into_it_and_says_so_first(self):
        path = helpfile.write(self.folder)
        path.write_text("my notes", encoding="utf-8")
        again = helpfile.write(self.folder)
        self.assertNotIn("my notes", again.read_text(encoding="utf-8"))
        self.assertIn("overwritten", again.read_text(encoding="utf-8").splitlines()[3])

    def test_a_folder_that_does_not_exist_yet_is_created(self):
        # First run, never calibrated: there is no ~/.flow/ until something writes one.
        path = helpfile.write(self.folder / "flow")
        self.assertTrue(path.exists())

    def test_the_sheet_is_ascii_so_any_console_code_page_can_open_it(self):
        helpfile.sheet(hotkeys=FakeHotkeys(REGISTERED)).encode("ascii")


class FakeMenu:
    """Records what was built, so the menu can be pinned without a desktop."""

    def __init__(self, *a, **kw) -> None:
        self.commands: dict = {}
        self.cascades: dict = {}

    def add_command(self, label="", command=None, **kw) -> None:
        self.commands[label] = command

    def add_radiobutton(self, label="", command=None, **kw) -> None:
        self.commands[label] = command

    def add_separator(self) -> None: ...

    def add_cascade(self, label="", menu=None, **kw) -> None:
        self.cascades[label] = menu

    def tk_popup(self, *a) -> None: ...

    def grab_release(self) -> None: ...


class TestTheMenuReachesIt(unittest.TestCase):
    """The two entries exist, and the tap does the two things it promises."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        self.opened: list = []
        self.notes: list[str] = []

    def _help_menu(self, hotkeys=None) -> FakeMenu:
        import tkinter as tk
        from unittest import mock

        import flow.ui as ui

        built: list[FakeMenu] = []

        def make(*a, **kw):
            built.append(FakeMenu())
            return built[-1]

        pill = ui.Pill.__new__(ui.Pill)
        pill.session = mock.Mock(mode=ui.DICTATE, speaker=None, profile=None,
                                 send_words=("goose", "enter goose"), workspace=None)
        pill.settings_path = self.folder / "lexicon.txt"
        pill.hotkeys = hotkeys
        pill.bubble = mock.Mock()
        pill.bubble.note = self.notes.append
        pill._clis = []
        pill._flash = 0
        with mock.patch.object(tk, "Menu", make), \
                mock.patch.object(tk, "StringVar", mock.Mock()), \
                mock.patch.object(ui, "available", return_value=[]), \
                mock.patch.object(ui, "foreground_hwnd", return_value=0), \
                mock.patch.object(ui, "toplevel_hwnd", return_value=0), \
                mock.patch.object(ui, "_user32"):
            pill._menu(mock.Mock(x_root=0, y_root=0))
        return built[0].cascades["Help"]

    def _tap(self, label: str, hotkeys=None) -> None:
        from unittest import mock

        import flow.ui as ui

        command = self._help_menu(hotkeys or FakeHotkeys(REGISTERED)).commands[label]
        with mock.patch.object(ui, "open_help_file", self.opened.append), \
                mock.patch.object(ui, "open_guide",
                                  lambda: self.opened.append(helpfile.GUIDE_URL)):
            command()

    def test_help_is_a_submenu_with_both_entries(self):
        self.assertEqual(sorted(self._help_menu().commands),
                         ["Commands & shortcuts", "Open the guide"])

    def test_the_tap_writes_the_sheet_and_opens_what_it_wrote(self):
        self._tap("Commands & shortcuts")
        written = self.folder / "commands.txt"
        self.assertEqual(self.opened, [written])
        text = written.read_text(encoding="utf-8")
        self.assertIn("ctrl+shift+space", text)
        self.assertIn("enter goose", text)

    def test_the_guide_entry_opens_the_public_readme(self):
        self._tap("Open the guide")
        self.assertEqual(self.opened, [helpfile.GUIDE_URL])

    def test_it_is_rewritten_on_the_second_tap_rather_than_read_back(self):
        # The one behaviour that makes this file worth generating: a hotkey that
        # registered differently on the next launch has to show up on the next open.
        self._tap("Commands & shortcuts")
        (self.folder / "commands.txt").write_text("stale", encoding="utf-8")
        self._tap("Commands & shortcuts")
        self.assertIn("ctrl+shift+space",
                      (self.folder / "commands.txt").read_text(encoding="utf-8"))

    def test_a_folder_that_cannot_be_written_says_so_instead_of_raising(self):
        # The menu is how somebody reaches Quit. An exception out of a menu command
        # takes the whole thing down, which is the one failure worse than no help.
        from unittest import mock

        import flow.ui as ui

        command = self._help_menu(FakeHotkeys(REGISTERED)).commands["Commands & shortcuts"]
        with mock.patch.object(ui, "write_help_sheet",
                               side_effect=OSError("access is denied")):
            command()
        self.assertIn("access is denied", " | ".join(self.notes))


if __name__ == "__main__":
    unittest.main()
