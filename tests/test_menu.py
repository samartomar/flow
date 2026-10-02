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
        #: (label, variable) — a checkbutton's tick is the variable's value, not a
        #: second label the way a radio's is, so it is recorded separately.
        self.checks: list[tuple[str, object]] = []
        self.cascades: dict = {}
        self.order: list[str] = []

    def add_command(self, label="", command=None, **kw) -> None:
        self.commands[label] = command
        self.order.append(label)

    def add_radiobutton(self, label="", value="", command=None, **kw) -> None:
        self.commands[label] = command
        self.radios.append((label, value))
        self.order.append(label)

    def add_checkbutton(self, label="", command=None, variable=None, **kw) -> None:
        self.commands[label] = command
        self.checks.append((label, variable))
        self.order.append(label)

    def add_separator(self) -> None: ...

    def delete(self, first=0, last=None) -> None:
        """Empty it, whatever range was asked for.

        The one call is `delete(0, "end")` — a menu rebuilt on open, and the
        Design submenu refreshed rather than replaced — so a fake that clears
        everything answers it exactly. A range that meant something else would
        be a fake with more opinions than the code it stands in for.
        """
        self.commands.clear()
        self.radios.clear()
        self.checks.clear()
        self.cascades.clear()
        self.order.clear()

    def add_cascade(self, label="", menu=None, **kw) -> None:
        self.cascades[label] = menu
        self.order.append(label)

    def configure(self, **kw) -> None: ...

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
              workspace=None, voices=(), recent=(), notes=None,
              can_take_reply=True, armed=False, gesture=None,
              mic=False, mode=None) -> FakeMenu:
        import tkinter as tk

        import flow.ui as ui

        built: list[FakeMenu] = []

        def make(*a, **kw):
            built.append(FakeMenu())
            return built[-1]

        self.pill = pill = ui.Pill.__new__(ui.Pill)
        pill.session = mock.Mock(
            mode=mode or (ui.CONVERSE if converse else ui.DICTATE),
            speaker=speaker, profile=profile, muted=False, auto_ask=True, cli=None,
            send_words=(SEND_WORD, SEND_ENTER_WORD), workspace=workspace,
        )
        pill.session.voices.return_value = list(voices)
        #: A real list, because `_recent_menu` asks for one by type — `getattr(..., None)
        #: or []` is not a guard when the attribute is a Mock, which is exactly what this
        #: fixture hands it.
        pill.session.recent = list(recent)
        #: A real `Notes` for the same reason, and `_notes_menu` asks by type too. The
        #: default is None — a Mock — so the row is absent unless a test asks for it.
        pill.session.notes = notes
        pill.session.can_take_reply = can_take_reply
        pill.settings_path = self.folder / "lexicon.txt"
        #: No chord by default — `--no-chord`, or a hook the OS refused — which is the
        #: state the rows that describe one are absent in. A test that wants those rows
        #: asks for a gesture, and gets the live `Chord` they read it off.
        pill.hotkeys = None if gesture is None else mock.Mock(
            chord=mock.Mock(gesture=gesture, **{"describe.return_value": "Ctrl+Win"}))
        pill.mic_view_on = mic
        pill._mic_at = None
        pill._sync_shell = mock.Mock()
        #: A monitor to be placed against, for the rows that re-place the window when
        #: they are chosen — the mic view's width and position both change with its tick.
        pill.full = (0, 0, 1920, 1080)
        pill.work = (0, 0, 1920, 1040)
        pill.x, pill.y = 0, 0
        pill.bubble = mock.Mock()
        pill.card = mock.Mock()
        pill.card.note = self.notes.append
        pill.bubble.note = self.notes.append
        #: `surface` is the same line shown with no draft behind it, which is how the
        #: menu answers a tap that has nothing to act on.
        pill.bubble.surface = self.notes.append
        pill._clis = []
        pill._flash = 0
        #: The Listen row reads it for its label and `_toggle` flips it on a tap; the
        #: draw is a mock because the tap repaints a pill this skeleton does not have.
        pill.armed = armed
        pill._draw = mock.Mock()
        with mock.patch.object(tk, "Menu", make), \
                mock.patch.object(tk, "StringVar", FakeVar), \
                mock.patch.object(tk, "BooleanVar", FakeVar), \
                mock.patch.object(ui, "available", return_value=list(clis)), \
                mock.patch.object(ui, "foreground_hwnd", return_value=0), \
                mock.patch.object(ui, "toplevel_hwnd", return_value=0), \
                mock.patch.object(ui, "_user32"):
            pill._menu(mock.Mock(x_root=0, y_root=0))
        return built[0]


class TestWhatStaysOneTap(Menu):
    """Seven rows, not eleven — and the split is state to read, not verbs to act on.

    Six until 2026-09-22, when Open Flow joined them: Flow Home is where every setting
    lives now, and the Classic pill keeps its Settings cascade beside it only for as long
    as this design is still shipped."""

    def test_the_top_level_is_exactly_seven_rows(self):
        top = self.build(self.profile())
        self.assertEqual(
            top.order,
            ["Listening", "Dictate", "Draft", "Open Flow", "Settings", "Help", "Quit Flow"],
        )

    def test_open_flow_opens_home(self):
        top = self.build(self.profile())
        home = self.pill.session.home = mock.Mock()
        home.open.return_value = ""
        top.commands["Open Flow"]()
        home.open.assert_called_once_with("home")

    def test_and_the_four_cascades_are_the_only_things_added(self):
        top = self.build(self.profile())
        self.assertEqual(sorted(top.cascades), ["Dictate", "Draft", "Help", "Settings"])

    def test_the_once_only_settings_left_the_top_level(self):
        # The list this replaces carried all of these inline, in one column, above Quit.
        top = self.build(self.profile())
        for label in ("Open settings folder", "Voice", "Agent CLI", "Trigger word"):
            with self.subTest(label=label):
                self.assertNotIn(label, top.commands)
                self.assertNotIn(label, top.cascades)

    def test_never_offer_left_the_menu_entirely(self):
        # It moved to the draft panel's own right-click menu (`Bubble._context_menu`),
        # not to a different corner of this one.
        top = self.build(self.profile())
        self.assertNotIn("Never offer", top.cascades)
        self.assertNotIn("Never offer", top.cascades["Settings"].cascades)

    def test_send_left_the_menu_entirely(self):
        # Three other ways in — a chip, a hotkey, a spoken word — and it is the one
        # irreversible act in the app; a browsing surface is a bad place for a fourth.
        top = self.build(self.profile())
        self.assertNotIn("Send", top.commands)

    def test_quit_is_last_and_named_for_the_app_it_quits(self):
        self.assertEqual(self.build(self.profile()).order[-1], "Quit Flow")

    def test_the_mode_cascade_names_the_state_it_is_already_in(self):
        # Not "Converse mode" while in Dictate — a verb about to happen. The row
        # itself says where you are; what is inside it is the choice.
        self.assertIn("Dictate", self.build(self.profile()).cascades)
        self.assertIn("Converse", self.build(self.profile(), converse=True).cascades)

    def test_the_mode_radios_offer_all_three_and_choose_directly(self):
        # A three-mode world cannot choose by flipping: one blind toggle from
        # Dictate lands on Refine. Every radio goes straight at its target.
        top = self.build(self.profile())
        radios = top.cascades["Dictate"].radios
        self.assertEqual([label for label, _v in radios],
                         ["Dictate", "Refine", "Converse"])
        top.cascades["Dictate"].commands["Converse"]()
        self.pill.session.toggle_mode.assert_called_once_with(to="converse")

    def test_the_mode_cascade_names_refine_when_in_it(self):
        self.assertIn("Refine", self.build(self.profile(), mode="refine").cascades)

    def test_copy_sits_above_clear_inside_draft(self):
        # One saves the words and one destroys them; the order is which hand reaches
        # which first during an incident, and this menu is where an incident ends.
        order = self.build(self.profile()).cascades["Draft"].order
        self.assertLess(order.index("Copy"), order.index("Clear"))


class TestListenIsTheMouseOnlyWayIn(Menu):
    """The one action the menu did not carry, and the session type that missed it.

    A VM console with the guest's keyboard captured (Hyper-V's viewer was the report)
    swallows every hotkey before Flow can see it, and the mouse is what remains. The
    pill click still toggles there, but it is an unlabeled control; this row is the
    labeled one — a checkbox now rather than a verb that flips, so the label is always
    "Listening" and the state is the tick, not the text.
    """

    def test_it_is_the_first_row_armed_or_not(self):
        self.assertEqual(self.build(self.profile()).order[0], "Listening")
        self.assertEqual(self.build(self.profile(), armed=True).order[0], "Listening")

    def test_the_tick_is_the_state_and_the_label_never_changes(self):
        off = self.build(self.profile())
        on = self.build(self.profile(), armed=True)
        label_off, var_off = off.checks[0]
        label_on, var_on = on.checks[0]
        self.assertEqual((label_off, label_on), ("Listening", "Listening"))
        self.assertFalse(var_off.get())
        self.assertTrue(var_on.get())

    def test_a_tap_arms_capture_through_the_same_toggle_the_pill_click_uses(self):
        top = self.build(self.profile())
        self.pill.session.reset_mock()  # the menu build itself asked the session things
        top.commands["Listening"]()
        self.pill.session.start.assert_called_once_with()
        self.assertTrue(self.pill.armed)

    def test_a_tap_while_armed_pauses_rather_than_restarting(self):
        top = self.build(self.profile(), armed=True)
        self.pill.session.reset_mock()
        top.commands["Listening"]()
        self.pill.session.pause.assert_called_once_with()
        self.pill.session.start.assert_not_called()
        self.assertFalse(self.pill.armed)

    def test_a_capture_that_cannot_start_is_said_and_the_pill_stays_disarmed(self):
        # The pill click's refusal handling, inherited rather than reimplemented: no
        # microphone means a flash and a sentence, never a green pill hearing nothing.
        top = self.build(self.profile())
        self.pill.session.start.side_effect = RuntimeError("no capture device")
        surfaced: list[str] = []
        self.pill.bubble.surface = surfaced.append
        top.commands["Listening"]()
        self.assertFalse(self.pill.armed)
        self.assertIn("no capture device", " ".join(surfaced))


class TestCopyDraftIsTheExitThatNeedsNothing(Menu):
    """The tap that would have ended the long-draft incident.

    Lite built `Pill._copy` for a body with no hands; full mode gets it as the universal
    exit — no model, no decode, no target window — which is exactly what is left when the
    render stall has taken the microphone and the spoken triggers with it.
    """

    def _tap(self, draft: str, copy=None):
        top = self.build(self.profile())
        self.pill.session.reset_mock()  # the menu build itself asked the session things
        self.pill.session.draft = mock.Mock(text=draft)
        self.pill.lite = False
        self.pill._copy = copy if copy is not None else mock.Mock(return_value="")
        top.cascades["Draft"].commands["Copy"]()
        return self.pill

    def test_the_draft_goes_to_the_clipboard_verbatim(self):
        copy = mock.Mock(return_value="")
        self._tap("line one\nline two  ", copy)
        copy.assert_called_once_with("line one\nline two  ")

    def test_it_does_not_go_through_send(self):
        # `send()` clears the draft and hands it to the paste layer. Copy changes
        # nothing, which is what makes it safe to reach for mid-incident.
        pill = self._tap("a draft")
        pill.session.send.assert_not_called()
        self.assertEqual(pill.session.draft.text, "a draft")

    def test_it_asks_the_session_for_nothing_at_all(self):
        # The whole point, asserted on the collaborator rather than on the outcome: this
        # path reads the draft and copies it. Nothing it calls can need a model, a
        # decode or a CLI, because it calls nothing.
        pill = self._tap("a draft")
        self.assertEqual(pill.session.method_calls, [])

    def test_an_empty_draft_says_so_rather_than_copying_nothing(self):
        copy = mock.Mock(return_value="")
        self._tap("", copy)
        copy.assert_not_called()
        self.assertTrue(self.notes, "an empty draft copied silently")

    def test_a_refusing_clipboard_is_reported(self):
        self._tap("a draft", mock.Mock(return_value="could not copy: busy"))
        self.assertIn("could not copy", " | ".join(self.notes))


class TestRecentIsAHistoryAndNotAFile(Menu):
    """Decision part 3, and the reference's lesson: recovery is a history.

    "Was a command" reaches one utterance back, and only while the draft it landed in is
    still there. This reaches the session — and reaches it in memory, which is the whole
    bargain: the words-never-stored stance holds by construction, and the cost is that
    quitting loses it.
    """

    SOME = [("said", "the deploy failed after the migration"),
            ("asked", "how do I widen a column"),
            ("answer", "Use ALTER TABLE, then reindex.")]

    def test_an_empty_ring_offers_no_submenu_at_all(self):
        # Absent rather than inert, the way the trigger submenu is under --no-profile: a
        # submenu that opens onto nothing is a control lying about having something.
        self.assertNotIn("Recent", self.build(self.profile()).cascades["Draft"].cascades)

    def test_the_entries_are_listed_newest_first_with_their_role(self):
        top = self.build(self.profile(), recent=list(reversed(self.SOME)))
        labels = top.cascades["Draft"].cascades["Recent"].order
        self.assertEqual(len(labels), 3)
        self.assertTrue(labels[0].startswith("answer: "), labels[0])
        self.assertTrue(labels[-1].startswith("said: "), labels[-1])

    def test_a_long_entry_is_cut_to_a_row(self):
        # A native menu row the width of the screen is a menu nobody reads down.
        long = "x" * 400
        top = self.build(self.profile(), recent=[("said", long)])
        label = top.cascades["Draft"].cascades["Recent"].order[0]
        self.assertLess(len(label), 80)
        self.assertTrue(label.endswith("…"))

    def test_a_tap_copies_the_whole_thing_and_not_the_row(self):
        import flow.ui as ui

        long = "y" * 400
        top = self.build(self.profile(), recent=[("said", long)])
        recent = top.cascades["Draft"].cascades["Recent"]
        copied: list[str] = []
        with mock.patch.object(ui.Pill, "_copy",
                               lambda _s, t: copied.append(t) or ""):
            recent.commands[recent.order[0]]()
        self.assertEqual(copied, [long])
        self.assertIn("400", " ".join(self.notes))

    def test_a_clipboard_refusal_is_said_rather_than_swallowed(self):
        import flow.ui as ui

        top = self.build(self.profile(), recent=self.SOME)
        recent = top.cascades["Draft"].cascades["Recent"]
        with mock.patch.object(ui.Pill, "_copy", lambda _s, _t: "could not copy: nope"):
            recent.commands[recent.order[0]]()
        self.assertIn("could not copy", " ".join(self.notes))

    def test_it_goes_through_the_one_clipboard_borrow_this_app_has(self):
        # Not a second `clipboard_clear`/`append` pair. Item 50 made the borrow one
        # transaction at a time on purpose, and a second caller would be outside it.
        import inspect

        import flow.ui as ui

        body = inspect.getsource(ui.Pill._copy_recent)
        self.assertIn("self._copy(", body)
        self.assertNotIn("clipboard_", body)


class TestTheSettingsMenuIsOnlyWhatHomeCannotMake(Menu):
    """The offload itself, pinned.

    Nine entries left this cascade on 2026-10-01 — chord, trigger word, panel size,
    design, agent CLI, effort, model, workspace and speak/mute — because Flow Home owns
    all nine and its Open Flow row sits one hover above. This is the test that says so,
    because the failure it guards is invisible: a duplicated setting is not broken, it is
    merely wrong in two places at once, and the second place is the one nobody edits.

    What stays is the three that are about *this window* rather than about a preference.
    """

    def settings(self, *a, **kw) -> FakeMenu:
        return self.build(*a, **kw).cascades["Settings"]

    def test_the_nine_that_moved_are_gone(self):
        # Everything this machine would have offered is asked for at once — a speaker, a
        # conversation, a second CLI — so a row cannot survive by being conditional.
        s = self.settings(self.profile(), speaker=mock.Mock(), clis=[], converse=True)
        for label in ("Trigger word", "Panel size", "Design", "Agent CLI",
                      "Effort", "Model", "Voice", "Mute replies", "Speak replies",
                      "Ask only when I press it", "Ask after a pause"):
            with self.subTest(label=label):
                self.assertNotIn(label, s.commands)
                self.assertNotIn(label, s.cascades)

    def test_the_chord_cascade_is_gone_though_the_chord_is_still_there(self):
        # The one that is easy to put back by accident, and this machine *does* have a
        # chord. Gesture is a Flow Home setting now; what is left of the chord in this
        # menu is the mic-view row underneath, which is a control rather than a setting.
        s = self.settings(self.profile())
        self.assertFalse([label for label in s.order if "Ctrl" in label],
                         "the chord cascade belongs to Flow Home now")

    def test_the_rows_that_stay_are_still_there(self):
        # Both of the others are conditional — the mic view only in push-to-talk, the
        # tray row only where there is a notification area — so the contract is "nothing
        # Home owns", not "exactly three".
        s = self.settings(self.profile())
        self.assertIn("Open settings folder", s.commands)
        self.assertLessEqual(len(s.order), 3)


class TestANewDraftFromTheClipboard(Menu):
    """The way in, opposite Copy draft — the path three users looked for.

    Every route into a draft was speech, which is exactly wrong for the first thing
    somebody does with a dictation tool they have just installed: they have a paragraph
    in front of them and want to work on it, not compose one.
    """

    def test_it_sits_beside_its_opposite(self):
        order = self.build(self.profile()).cascades["Draft"].order
        self.assertEqual(order[order.index("Copy") + 1], "New from clipboard")

    def test_clipboard_text_becomes_the_draft(self):
        import flow.ui as ui

        draft = self.build(self.profile()).cascades["Draft"]
        self.pill.session.paste_draft.return_value = ""
        with mock.patch.object(ui.Pill, "clipboard_get",
                               lambda _s: "a paragraph from somewhere else"):
            draft.commands["New from clipboard"]()
        self.pill.session.paste_draft.assert_called_once_with(
            "a paragraph from somewhere else")
        self.assertEqual(self.notes, [], "a success does not need a note of its own")

    def test_an_empty_clipboard_draws_a_note(self):
        import flow.ui as ui

        draft = self.build(self.profile()).cascades["Draft"]
        self.pill.session.paste_draft.return_value = "nothing on the clipboard"
        with mock.patch.object(ui.Pill, "clipboard_get", lambda _s: ""):
            draft.commands["New from clipboard"]()
        self.assertIn("nothing on the clipboard", " ".join(self.notes))

    def test_a_clipboard_holding_something_that_is_not_text_says_the_same_thing(self):
        # Tk raises `TclError` for an empty clipboard *and* for one holding an image or
        # a file list. Neither is a fault worth a stack trace, and from where the user
        # stands they are the same fact: there is nothing here to start from.
        import tkinter as tk

        import flow.ui as ui

        draft = self.build(self.profile()).cascades["Draft"]
        self.pill.session.paste_draft.return_value = "nothing on the clipboard"

        def boom(_self):
            raise tk.TclError("CLIPBOARD selection doesn't exist")

        with mock.patch.object(ui.Pill, "clipboard_get", boom):
            draft.commands["New from clipboard"]()
        self.pill.session.paste_draft.assert_called_once_with("")
        self.assertIn("nothing on the clipboard", " ".join(self.notes))

    def test_the_refusal_is_surfaced_rather_than_noted(self):
        # It runs with an empty draft and a hidden bubble, which is the state it exists
        # for — and `note()` only paints on a window that is already showing.
        import flow.ui as ui

        draft = self.build(self.profile()).cascades["Draft"]
        self.pill.session.paste_draft.return_value = "no"
        surfaced: list[str] = []
        self.pill.bubble.surface = surfaced.append
        with mock.patch.object(ui.Pill, "clipboard_get", lambda _s: ""):
            draft.commands["New from clipboard"]()
        self.assertEqual(surfaced, ["no"])
