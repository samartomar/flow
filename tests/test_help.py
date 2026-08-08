"""The help sheet has to describe *this* machine, or it is worse than no help sheet.

Two failures are possible and only one of them is obvious. The obvious one is stale
content: `ctrl+alt+space` is the first alternative in `DEFAULT_BINDINGS` and was already
owned by another app on the development machine, so a shipped sheet would name a combo
that does nothing here. The quieter one is a sheet that documents a command the router
does not have - the product telling somebody who went looking for help to say a sentence
that will be typed into their draft. So every example in the sheet is routed, and the
family it is filed under is asserted rather than described.

The sheet moved out of a text file and into Flow's own window at the owner's review
(2026-08-02, "which is not help"). The route check below is the same check it was before
the move, unchanged and deliberately so: it never looked at the rendering, which is what
made the move a presentation change rather than a rewrite.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


def rendered(**kw) -> str:
    """Every row flattened, for the assertions that are about content and not layout.

    Kept here rather than in `help.py`: the window draws rows, so a flat rendering in the
    module would be a second representation with no reader but this file.
    """
    return "\n".join(f"{left}  {right}" for _kind, left, right in helpfile.rows(**kw))


class TestItNamesWhatRegistered(unittest.TestCase):
    def test_the_combo_that_registered_is_the_one_shown(self):
        self.assertIn("ctrl+shift+space", rendered(hotkeys=FakeHotkeys(REGISTERED)))

    def test_and_the_default_it_fell_back_from_appears_nowhere(self):
        # The whole reason this is generated. ctrl+alt+space is `DEFAULT_BINDINGS`'
        # first alternative and is taken on this machine; a sheet naming it would send
        # the user to a key that cannot arm the mic.
        self.assertNotIn("ctrl+alt+space", rendered(hotkeys=FakeHotkeys(REGISTERED)))

    def test_an_action_that_could_not_register_is_named_as_unavailable(self):
        text = rendered(hotkeys=FakeHotkeys(REGISTERED, failed=["cancel"]))
        line = next(ln for ln in text.splitlines() if "cancel" in ln)
        self.assertIn("owned by another app", line)

    def test_no_hotkeys_at_all_is_a_sentence_rather_than_a_hole(self):
        # `--no-hotkeys` is a supported way to run, and an empty section reads as a bug
        # in the help rather than as a choice the user made at launch.
        self.assertIn("--no-hotkeys", rendered(hotkeys=None))


class TestTheSheetOutlivesTheAdapter(unittest.TestCase):
    """It names no agent CLI, and that is why a new entry costs it nothing.

    Asserted rather than assumed. Every other surface that touches a CLI name — the pin,
    the startup lines, the pill's marker, the menu's picker — had to be extended when the
    adapter grew, and this one did not. A sheet that had picked up "codex" in an example
    would have gone stale the first time somebody ran Flow with something else.
    """

    def test_no_candidate_is_named_anywhere_in_it(self):
        from flow.refine import CANDIDATES

        text = rendered(hotkeys=FakeHotkeys(REGISTERED))
        for cli in CANDIDATES:
            with self.subTest(cli=cli.name):
                self.assertNotIn(cli.name, text)


class TestTheLineSaidWhenVoiceGoesDown(unittest.TestCase):
    """One sentence, built from the same source the sheet is built from.

    It lives here rather than in `session.py` for the reason the sheet does: the combos
    are whatever `RegisterHotKey` accepted this launch, and a note written where the
    defaults are visible is a note that will one day name a key nobody can press. The
    session emits it; this decides what it says.
    """

    def test_it_names_the_combo_that_registered(self):
        note = helpfile.exits_note(FakeHotkeys({"send": "ctrl+shift+enter"}))
        self.assertIn("ctrl+shift+enter", note)

    def test_and_not_the_default_it_may_have_fallen_back_from(self):
        self.assertNotIn("ctrl+alt+enter",
                         helpfile.exits_note(FakeHotkeys({"send": "ctrl+shift+enter"})))

    def test_it_says_the_voice_is_the_thing_that_is_down(self):
        # The note arrives while nothing else is happening on screen. If it does not say
        # why it is there, it reads as an error somebody has to diagnose.
        self.assertIn("voice is down", helpfile.exits_note(FakeHotkeys(REGISTERED)))

    def test_with_no_combo_it_names_the_chip_instead_of_trailing_off(self):
        # Lite, `--no-hotkeys`, and the case where every alternative for `send` was
        # taken. A sentence missing its useful half is worse than no sentence.
        for hotkeys in (None, FakeHotkeys({}), FakeHotkeys({"toggle": "ctrl+alt+space"})):
            with self.subTest(hotkeys=hotkeys):
                note = helpfile.exits_note(hotkeys)
                self.assertIn("Send chip", note)
                self.assertIn("voice is down", note)

    def test_it_names_the_two_exits_that_need_no_microphone(self):
        # Edit and Copy: one puts the words under a keyboard, the other puts them on the
        # clipboard. Neither needs a decode, which is the whole point of saying them here.
        note = helpfile.exits_note(FakeHotkeys(REGISTERED))
        self.assertIn("edit", note)
        self.assertIn("copy", note)

    def test_it_stays_one_glance_long(self):
        # It is drawn at the bubble's foot at 8 pt, where a line holds ~63 characters.
        # Two lines is a note; four is a paragraph nobody reads mid-incident.
        for hotkeys in (None, FakeHotkeys(REGISTERED)):
            with self.subTest(hotkeys=hotkeys):
                self.assertLessEqual(len(helpfile.exits_note(hotkeys)), 126)

    def test_every_action_that_registered_gets_a_line(self):
        text = rendered(hotkeys=FakeHotkeys(REGISTERED))
        for action, combo in REGISTERED.items():
            with self.subTest(action=action):
                self.assertIn(combo, text)

    def test_the_combo_is_the_column_somebody_reads_first(self):
        # The action names are this codebase's words for its own bindings; the combo is
        # the thing a user presses. So the combo is the left column and the sentence is
        # the right one, rather than the other way round.
        rows = helpfile.rows(hotkeys=FakeHotkeys(REGISTERED))
        self.assertIn(("pair", "ctrl+shift+space", "start and stop listening"), rows)


class TestItNamesTheWordsCurrentlyConfigured(unittest.TestCase):
    def test_a_stored_trigger_is_what_the_sheet_shows(self):
        text = rendered(send_words=("goose", "enter goose"))
        self.assertIn("goose", text)
        self.assertIn("enter goose", text)

    def test_and_the_shipped_default_is_not_still_advertised(self):
        # Said as its own check because the failure is silent: the user renamed the
        # trigger, the sheet kept naming the old word, and the old word no longer works.
        # Nowhere at all, not merely absent from the two rows that list it - the prose
        # around them used to illustrate whole-utterance matching with "boom goes the
        # dynamite", which is exactly the kind of sentence that survives a rename and
        # then teaches somebody a word that has stopped working.
        text = rendered(send_words=("goose", "enter goose"))
        self.assertNotIn(SEND_WORD, text)

    def test_with_nothing_passed_it_shows_the_shipped_pair(self):
        text = rendered()
        self.assertIn(SEND_WORD, text)
        self.assertIn(SEND_ENTER_WORD, text)

    def test_the_workshop_line_is_the_one_the_session_resolved(self):
        self.assertIn(r"workshop: D:\dev\products\widget",
                      rendered(workspace_note=r"workshop: D:\dev\products\widget"))

    def test_an_unset_workshop_still_says_something_true(self):
        self.assertIn("workshop: not set", rendered())


class TestEveryExampleIsRealSpeech(unittest.TestCase):
    """The check that stops the sheet from documenting a command nobody has.

    Unchanged across the move into a window, which is the point: it reads `COMMANDS` and
    `plan()`, and neither of those is a rendering.
    """

    def routed(self, utterance: str, triggers=(SEND_WORD, SEND_ENTER_WORD)) -> str:
        p = plan(utterance, helpfile.EXAMPLE_DRAFT, triggers)
        return f"{p.kind}/{p.op}"

    def test_each_example_routes_to_the_family_it_is_filed_under(self):
        for say, _does, route in helpfile.COMMANDS:
            with self.subTest(say=say):
                self.assertEqual(self.routed(say), route)

    def test_every_example_appears_in_the_rendered_sheet(self):
        text = rendered()
        for say, does, _route in helpfile.COMMANDS:
            with self.subTest(say=say):
                self.assertIn(say, text)
                self.assertIn(does, text)

    def test_the_take_verbs_come_from_the_grammar_and_all_of_them_work(self):
        text = rendered()
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


class TestNothingRunsOffTheEdge(unittest.TestCase):
    """The window draws one line per row and does not wrap, so the budget is a rule.

    Enforced here rather than discovered on screen: a wrapped row would need a height
    that depends on its content, and the scroll offset is counted in whole rows.
    """

    def test_no_row_of_the_shipped_content_is_truncated(self):
        # The truncation mark is the signal. Anything this file writes itself should fit;
        # a mark appearing here means a string grew past the column it is drawn in.
        for kind, left, right in helpfile.rows(hotkeys=FakeHotkeys(REGISTERED)):
            with self.subTest(row=(kind, left)):
                self.assertNotIn("…", left)
                self.assertNotIn("…", right)

    def test_a_heading_that_carries_a_second_column_clears_the_gutter(self):
        for kind, left, right in helpfile.rows(hotkeys=FakeHotkeys(REGISTERED)):
            if kind == "head" and right:
                with self.subTest(head=left):
                    self.assertLessEqual(len(left), helpfile.MAX_HEAD)

    def test_the_one_row_carrying_a_users_own_text_is_cut_to_fit(self):
        # The workshop path is the only string here that nobody in this repo wrote, and
        # a deep project path is longer than the window. Cut and marked, the way
        # `edits.removed_text` cuts, rather than allowed to run off the edge.
        note = "workshop: " + "D:\\dev\\" + "verylongsegment\\" * 8
        rows = helpfile.rows(workspace_note=note)
        shown = next(left for kind, left, _r in rows if left.startswith("workshop:"))
        self.assertLessEqual(len(shown), helpfile.MAX_NOTE)
        self.assertTrue(shown.endswith("…"))

    def test_a_gap_row_stays_empty_rather_than_becoming_an_ellipsis(self):
        # `fit` cuts to a limit and the gap's limit is zero, which is exactly the shape
        # that turns "" into "…" if the empty case is not handled first.
        for kind, left, right in helpfile.rows():
            if kind == "gap":
                self.assertEqual((left, right), ("", ""))


class RecordingCanvas:
    """Enough of a Tk canvas to see what the help window draws, without a desktop.

    Same fixture idea as `test_indicator.py`'s: a real window would need a display, and
    the questions here - what text was drawn, and what a click on the chip does - are
    answerable from the calls.
    """

    def __init__(self) -> None:
        self.texts: list[str] = []
        self.bindings: dict = {}

    def configure(self, **kw) -> None: ...

    def delete(self, *a) -> None:
        self.texts.clear()

    def create_polygon(self, *a, **kw) -> None: ...

    def create_rectangle(self, *a, **kw) -> None: ...

    def create_text(self, x, y, text="", **kw) -> None:
        self.texts.append(text)

    def tag_bind(self, tag, sequence, func) -> None:
        self.bindings[(tag, sequence)] = func

    def bind(self, sequence, func) -> None:
        self.bindings[sequence] = func

    def pack(self, **kw) -> None: ...


class FakeWindow:
    """A `HelpWindow` with the Toplevel taken out from under it.

    Every method under test is about rows, scrolling and drawing; none of them needs a
    window handle. Building it this way keeps the check in the unit suite, where
    `test_resilience.py` already pays for the one case that genuinely needs a desktop.
    """

    #: The work area this machine actually reports (`SPI_GETWORKAREA`, measured), which
    #: is the case the scrolling exists for. A test on an imagined 1080p desktop would be
    #: testing a window that never has to scroll.
    WORK = (0, 0, 1280, 672)

    def __init__(self, rows, work=WORK, accent="#f59e0b") -> None:
        import flow.ui as ui

        self.win = ui.HelpWindow.__new__(ui.HelpWindow)
        self.win.pill = mock.Mock(work=work, accent=accent)
        self.win.canvas = RecordingCanvas()
        self.win._rows = list(rows)
        self.win._top = 0
        self.win._drag_y = None
        self.win._drag_px = 0
        self.win._h = 200
        self.geometry: list[str] = []
        self.win.geometry = self.geometry.append
        self.win._render()

    @property
    def drawn(self) -> str:
        return "\n".join(self.win.canvas.texts)


class TestTheWindowShowsTheGeneratedContent(unittest.TestCase):
    def rows(self, **kw):
        return helpfile.rows(hotkeys=FakeHotkeys(REGISTERED), **kw)

    def test_the_title_is_drawn(self):
        self.assertIn(helpfile.TITLE, FakeWindow(self.rows()).drawn)

    def test_a_hotkey_line_carries_the_combo_that_actually_registered(self):
        drawn = FakeWindow(self.rows()).drawn
        self.assertIn("ctrl+shift+space", drawn)
        self.assertNotIn("ctrl+alt+space", drawn)

    def test_a_renamed_trigger_word_reaches_the_window(self):
        drawn = FakeWindow(self.rows(send_words=("goose", "enter goose"))).drawn
        self.assertIn("goose", drawn)
        self.assertIn("enter goose", drawn)
        self.assertNotIn(SEND_WORD, drawn)

    def test_the_commands_are_drawn_with_what_they_do_beside_them(self):
        drawn = FakeWindow(self.rows()).drawn
        for say, does, _route in helpfile.COMMANDS[:4]:
            with self.subTest(say=say):
                self.assertIn(say, drawn)
                self.assertIn(does, drawn)

    def test_the_close_chip_is_bound_and_closes_it(self):
        import flow.ui as ui

        w = FakeWindow(self.rows())
        closed: list[bool] = []
        w.win.withdraw = lambda: closed.append(True)
        w.win.canvas.bindings[(ui.chip_tag("Close"), "<Button-1>")](None)
        self.assertEqual(closed, [True])

    def test_it_is_bounded_rather_than_growing_with_the_content(self):
        import flow.ui as ui

        w = FakeWindow(self.rows() * 4, work=(0, 0, 3840, 4000))
        self.assertLessEqual(w.win._h, ui.HELP_MAX_H)

    def test_and_the_work_area_bounds_it_before_that_number_usually_does(self):
        import flow.ui as ui

        small = FakeWindow(self.rows(), work=(0, 0, 1280, 672))
        self.assertLessEqual(small.win._h, 672 - ui.HELP_MARGIN)

    def test_a_display_with_room_shows_more_of_it_without_being_asked(self):
        # The best outcome is a sheet nobody has to scroll. The window takes the room it
        # is given rather than sitting at a fixed height and hiding the rest.
        #
        # **1440 rather than 1200, and that is a fact about the sheet rather than about
        # the test.** With every combo registered it measures 1174 px since item 71 added
        # the colour legend, and a 1200-tall desktop has 1152 after `HELP_MARGIN` — 22 px
        # short. So the sheet has outgrown a 1200-tall display, and it scrolls there.
        # Recorded by moving the check rather than by trimming the legend: the content is
        # what somebody came for, and a test that shrank it would be the tail wagging.
        small = FakeWindow(self.rows(), work=(0, 0, 1280, 672))
        big = FakeWindow(self.rows(), work=(0, 0, 1920, 1440))
        self.assertGreater(big.win._h, small.win._h)
        self.assertEqual(big.win._max_top(), 0, "it still scrolls with room to spare")

    def test_the_window_is_placed_inside_the_work_area(self):
        w = FakeWindow(self.rows(), work=(0, 0, 1280, 800))
        self.assertTrue(w.geometry, "the window was never positioned")
        size, _, offset = w.geometry[-1].partition("+")
        x, _, y = offset.partition("+")
        self.assertGreaterEqual(int(x), 0)
        self.assertGreaterEqual(int(y), 0)


class TestScrollingWithoutAKeyboard(unittest.TestCase):
    """It never holds the focus, so everything here has to work without one."""

    def window(self, work=FakeWindow.WORK) -> FakeWindow:
        # The measured work area, where 22 rows are below the fold. On a taller desktop
        # only one row is, which would make every assertion here a coin toss.
        return FakeWindow(helpfile.rows(hotkeys=FakeHotkeys(REGISTERED)), work=work)

    def test_the_content_is_taller_than_the_window_so_there_is_something_to_scroll(self):
        w = self.window()
        self.assertGreater(w.win._max_top(), 0, "nothing is off screen to reach")

    def test_the_wheel_moves_the_page_and_stops_at_the_top(self):
        w = self.window()
        w.win._wheel(mock.Mock(delta=-120))
        self.assertEqual(w.win._top, 3)
        w.win._wheel(mock.Mock(delta=120))
        self.assertEqual(w.win._top, 0)
        w.win._wheel(mock.Mock(delta=120))
        self.assertEqual(w.win._top, 0, "scrolled above the first row")

    def test_it_stops_at_the_bottom_rather_than_running_into_empty_space(self):
        w = self.window()
        for _ in range(40):
            w.win._wheel(mock.Mock(delta=-120))
        self.assertEqual(w.win._top, w.win._max_top())

    def test_dragging_scrolls_too_because_the_wheel_may_never_arrive(self):
        # WM_MOUSEWHEEL goes to the focused window, and this one is never focused. The
        # drag is delivered by hit-test, so it works whatever the OS setting says.
        import flow.ui as ui

        w = self.window()
        w.win._grab(mock.Mock(y=200))
        w.win._drag(mock.Mock(y=200 - 3 * ui.HELP_LINE_H))
        self.assertEqual(w.win._top, 3)

    def test_a_slow_drag_keeps_its_remainder_instead_of_losing_it(self):
        # Sub-row movements accumulate. Dropping them would make a careful drag do
        # nothing at all, which reads as the window being stuck.
        import flow.ui as ui

        w = self.window()
        w.win._grab(mock.Mock(y=300))
        step = ui.HELP_LINE_H // 3 + 1
        for i in range(1, 4):
            w.win._drag(mock.Mock(y=300 - i * step))
        self.assertGreaterEqual(w.win._top, 1)

    def test_the_footer_names_the_drag_only_when_there_is_more_to_see(self):
        self.assertIn("drag", self.window().drawn)
        short = FakeWindow([("note", "one line", "")])
        self.assertNotIn("drag", short.drawn)

    def test_a_short_sheet_scrolls_nowhere(self):
        short = FakeWindow([("note", "one line", "")])
        short.win._wheel(mock.Mock(delta=-120))
        self.assertEqual(short.win._top, 0)


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


@unittest.skipUnless(sys.platform == "win32", "Windows-only: os.startfile")
class TestTheMenuReachesIt(unittest.TestCase):
    """The two entries, and the inversion.

    Before this item, both entries shelled out: the sheet to `~/.flow/commands.txt` and
    the guide to a URL. That was pinned green first - `os.startfile` called with a path
    ending `commands.txt`, and the file left behind. Now only one of them shells out, and
    both halves of that are asserted, because removing one path must not quietly remove
    the other.
    """

    def setUp(self) -> None:
        self.started: list[str] = []
        self.shown: list[list] = []
        self.notes: list[str] = []

    def _help_menu(self, hotkeys=None, folder=None) -> FakeMenu:
        import tkinter as tk

        import flow.ui as ui

        built: list[FakeMenu] = []

        def make(*a, **kw):
            built.append(FakeMenu())
            return built[-1]

        self.pill = pill = ui.Pill.__new__(ui.Pill)
        pill.session = mock.Mock(mode=ui.DICTATE, speaker=None, profile=None,
                                 send_words=("goose", "enter goose"), workspace=None)
        pill.settings_path = (folder or Path.cwd()) / "lexicon.txt"
        pill.hotkeys = hotkeys
        pill.bubble = mock.Mock()
        pill.bubble.note = self.notes.append
        pill._clis = []
        pill._flash = 0
        pill.armed = False  # the Listen row reads it for its label
        # None rather than a stand-in, so the lazy construction in `_open_commands` is
        # the path under test — the window is built on first use and kept.
        pill._help = None
        self.window = mock.Mock()
        self.window.show = self.shown.append
        with mock.patch.object(tk, "Menu", make), \
                mock.patch.object(tk, "StringVar", mock.Mock()), \
                mock.patch.object(ui, "available", return_value=[]), \
                mock.patch.object(ui, "foreground_hwnd", return_value=0), \
                mock.patch.object(ui, "toplevel_hwnd", return_value=0), \
                mock.patch.object(ui, "_user32"):
            pill._menu(mock.Mock(x_root=0, y_root=0))
        return built[0].cascades["Help"]

    def _tap(self, label: str, hotkeys=None, folder=None) -> None:
        import flow.ui as ui

        command = self._help_menu(hotkeys or FakeHotkeys(REGISTERED),
                                  folder=folder).commands[label]
        # Both patched over the tap, not over the build: the window is constructed and
        # the shell is called when the entry is chosen, which is after `_menu` returned.
        with mock.patch.object(ui, "HelpWindow", return_value=self.window), \
                mock.patch.object(helpfile.os, "startfile", self.started.append):
            command()

    def test_help_is_a_submenu_with_both_entries(self):
        self.assertEqual(sorted(self._help_menu().commands),
                         ["Commands & shortcuts", "Open the guide"])

    def test_the_sheet_no_longer_shells_out_to_anything(self):
        # The inversion. This assertion was true the other way round before the item,
        # and pinned green against the old tree before it was changed.
        self._tap("Commands & shortcuts")
        self.assertEqual(self.started, [])

    def test_and_writes_no_file_into_the_settings_folder(self):
        import tempfile

        folder = Path(tempfile.mkdtemp())
        self._tap("Commands & shortcuts", folder=folder)
        self.assertEqual(list(folder.iterdir()), [])

    def test_it_hands_the_window_the_freshly_generated_rows(self):
        self._tap("Commands & shortcuts")
        self.assertEqual(len(self.shown), 1)
        flat = " ".join(f"{left} {right}" for _k, left, right in self.shown[0])
        self.assertIn("ctrl+shift+space", flat)
        self.assertIn("enter goose", flat)

    def test_a_second_open_regenerates_rather_than_reusing(self):
        # The property the whole file exists for, kept across the move: a hotkey that
        # registered differently, or a trigger word changed since, has to show up.
        self._tap("Commands & shortcuts")
        self._tap("Commands & shortcuts", hotkeys=FakeHotkeys({"toggle": "ctrl+alt+\\"}))
        self.assertIn("ctrl+alt+\\",
                      " ".join(left for _k, left, _r in self.shown[-1]))

    def test_the_window_is_built_once_and_then_kept(self):
        # Lazy, because most sessions never open Help and a second Toplevel is a handle
        # and a paint. Kept, because building a new one per open would drop the scroll
        # position and blink.
        import flow.ui as ui

        self._help_menu(FakeHotkeys(REGISTERED))
        built = mock.Mock(return_value=self.window)
        with mock.patch.object(ui, "HelpWindow", built):
            self.pill._open_commands()
            self.pill._open_commands()
        self.assertEqual(built.call_count, 1)
        self.assertEqual(len(self.shown), 2, "the second open showed nothing")

    def test_the_guide_still_shells_out_to_the_readme(self):
        # Deliberately not moved. A long-form guide belongs where links work, and a
        # browser is the right application for a browser's content - which is the same
        # argument that took the command sheet out of Notepad.
        self._tap("Open the guide")
        self.assertEqual(self.started, [helpfile.GUIDE_URL])

    def test_a_shell_that_refuses_the_guide_says_so_instead_of_raising(self):
        # The menu is how somebody reaches Quit. An exception out of a menu command takes
        # the whole thing down, which is the one failure worse than no help.
        command = self._help_menu(FakeHotkeys(REGISTERED)).commands["Open the guide"]
        with mock.patch.object(helpfile.os, "startfile",
                               side_effect=OSError("no handler")):
            command()
        self.assertIn("no handler", " | ".join(self.notes))


class TestTheTextFilePathIsGone(unittest.TestCase):
    """Removed, not kept as a second surface: two surfaces is two things to keep true."""

    def test_the_module_no_longer_writes_or_opens_a_file(self):
        for gone in ("write", "open_file", "sheet", "FILENAME"):
            with self.subTest(gone=gone):
                self.assertFalse(hasattr(helpfile, gone))

    def test_and_nothing_in_the_ui_imports_one(self):
        import flow.ui as ui

        self.assertFalse(hasattr(ui, "write_help_sheet"))
        self.assertFalse(hasattr(ui, "open_help_file"))


if __name__ == "__main__":
    unittest.main()


class TestTheWelcomeCard(unittest.TestCase):
    """Item 71. Every line on it was a `print()` before this.

    Flow says the combos it registered, the trigger word and that a pause sends a
    question — into a console a GUI user does not have open. Three outside users met the
    app without any of it (decisions.md 2026-08-03), and a first launch is the one moment
    somebody is willing to read six lines.
    """

    def rows(self, **kw):
        return helpfile.welcome_rows(**kw)

    def text(self, **kw) -> str:
        return "\n".join(f"{left} {right}" for _k, left, right in self.rows(**kw))

    def test_it_names_the_combo_that_actually_registered(self):
        # The same defect the sheet exists to prevent, one surface along: greeting
        # somebody with a key that does nothing is worse than not greeting them.
        said = self.text(hotkeys=FakeHotkeys(REGISTERED))
        self.assertIn(REGISTERED["toggle"], said)
        self.assertNotIn("ctrl+alt+space", said)

    def test_with_no_hotkeys_it_names_the_pill_instead_of_trailing_off(self):
        said = self.text(hotkeys=None)
        self.assertIn("click the pill", said)
        self.assertIn("no combo this launch", said)

    def test_it_names_the_configured_trigger_word(self):
        self.assertIn("tango", self.text(send_words=("tango", "enter tango")))
        self.assertNotIn("boom", self.text(send_words=("tango", "enter tango")))

    def test_it_says_a_pause_sends_and_where_to_stop_that(self):
        # The load-bearing console line, on a surface a GUI user actually sees.
        said = self.text()
        self.assertIn("a pause sends the question", said)
        self.assertIn(helpfile.AUTO_ASK_OFF_LABEL, said)

    def test_it_carries_the_colour_legend(self):
        said = self.text()
        for phrase in ("green pill", "blue pill", "amber window", "violet window"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, said)

    def test_the_legend_matches_the_colours_the_app_actually_draws(self):
        # Three pill colours since item 63, not five, and the two that left became
        # window identities. A legend describing a palette the app no longer has is
        # worse than none.
        import flow.ui as ui

        said = self.text()
        self.assertEqual(len(set(ui.ACCENT.values())), 3)
        for gone in ("amber pill", "violet pill"):
            self.assertNotIn(gone, said)

    def test_the_sheet_carries_the_legend_permanently(self):
        # A legend is exactly the thing somebody wants a *second* time, and the welcome
        # card is shown once by design.
        said = "\n".join(f"{left} {right}"
                         for _k, left, right in helpfile.rows())
        self.assertIn("What the colours mean", said)
        self.assertIn("violet window", said)

    def test_every_row_fits_the_columns_the_window_draws_in(self):
        # The window does not wrap: a row is one line, so its height is fixed and the
        # scroll offset is computed from it.
        limits = {"pair": (helpfile.MAX_LEFT, helpfile.MAX_RIGHT),
                  "note": (helpfile.MAX_NOTE, 0),
                  "head": (helpfile.MAX_NOTE, helpfile.MAX_RIGHT), "gap": (0, 0)}
        for kind, left, right in self.rows(hotkeys=FakeHotkeys(REGISTERED)):
            with self.subTest(row=left[:24]):
                self.assertLessEqual(len(left), limits[kind][0])
                self.assertLessEqual(len(right), limits[kind][1])

    def test_it_points_at_the_menu_for_everything_else(self):
        said = self.text()
        self.assertIn("right-click", said.lower())


class TestItIsShownOnceAndOnlyOnce(unittest.TestCase):
    """`profile.welcomed`, written before anybody has read a word.

    A card shown twice is worse than one shown once, and a crash between showing and
    saving would do exactly that.
    """

    def pill(self, profile):
        import flow.ui as ui

        p = ui.Pill.__new__(ui.Pill)
        p.session = mock.Mock(profile=profile,
                              send_words=("boom", "enter boom"))
        p.hotkeys = None
        p.lite = False
        p._help = mock.Mock()
        return p

    def profile(self):
        from flow.profile import Profile

        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        return Profile(Path(d.name) / "profile.json")

    def test_a_first_launch_shows_it(self):
        p = self.profile()
        pill = self.pill(p)
        pill._welcome()
        pill._help.show.assert_called_once()
        self.assertEqual(pill._help.show.call_args.kwargs["chip"], "Dismiss")

    def test_and_the_next_launch_does_not(self):
        p = self.profile()
        self.pill(p)._welcome()
        again = self.pill(type(p)(p.path))
        again._welcome()
        again._help.show.assert_not_called()

    def test_the_flag_is_written_before_the_card_is_shown(self):
        # A crash between showing and saving would show it twice, which is the one
        # outcome worse than showing it once.
        p = self.profile()
        pill = self.pill(p)
        pill._help.show.side_effect = RuntimeError("the card blew up")
        with self.assertRaises(RuntimeError):
            pill._welcome()
        self.assertTrue(type(p)(p.path).welcomed)

    def test_no_profile_means_no_card(self):
        # `--no-profile` has nowhere to remember it, and a welcome on every launch is an
        # advertisement rather than an introduction. The Help sheet still has all of it.
        pill = self.pill(None)
        pill._welcome()
        pill._help.show.assert_not_called()

    def test_an_older_profile_is_welcomed_once(self):
        # Absent means not welcomed, like `converse_seen`: a person who has been using
        # Flow for a week still has not been told what the colours mean.
        from flow.profile import Profile

        p = self.profile()
        p.path.write_text('{"schema": 1}', encoding="utf-8")
        self.assertFalse(Profile(p.path).welcomed)

    def test_the_flag_survives_a_round_trip(self):
        from flow.profile import Profile

        p = self.profile()
        p.welcomed = True
        self.assertTrue(p.save())
        self.assertTrue(Profile(p.path).welcomed)
