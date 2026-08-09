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
              can_take_reply=True, armed=False) -> FakeMenu:
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
        #: A real list, because `_recent_menu` asks for one by type — `getattr(..., None)
        #: or []` is not a guard when the attribute is a Mock, which is exactly what this
        #: fixture hands it.
        pill.session.recent = list(recent)
        #: A real `Notes` for the same reason, and `_notes_menu` asks by type too. The
        #: default is None — a Mock — so the row is absent unless a test asks for it.
        pill.session.notes = notes
        pill.session.can_take_reply = can_take_reply
        pill.settings_path = self.folder / "lexicon.txt"
        pill.hotkeys = None
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
    """Six rows now, not eleven — and the split is state to read, not verbs to act on."""

    def test_the_top_level_is_exactly_six_rows(self):
        top = self.build(self.profile())
        self.assertEqual(
            top.order, ["Listening", "Dictate", "Draft", "Settings", "Help", "Quit Flow"]
        )

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

    @unittest.skipUnless(sys.platform == "win32", "Windows-only: Windows path case-folding")
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

    @unittest.skipUnless(sys.platform == "win32", "Windows-only: Windows path case-folding")
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


class TestTheVoiceMenuStaysOnScreen(Menu):
    """A long engine must not push a short one off the bottom.

    Grouping by engine was not enough on its own. With the natural voices installed the
    submenu was **50 rows** — past the bottom of the screen, scroll arrows at both ends,
    and Piper's two down below the fold, so the shorter and better list was the one you
    had to hunt for. Seen in a screenshot, which is the only way this kind of thing gets
    noticed.

    So: short sections inline, long ones behind gender cascades, and Piper first because
    `speak._legacy` puts it first — the menu and the resolver agree on what is best.
    """

    PIPER = [
        Voice("Piper en_GB-cori-high", "NotSet", "en-GB", engine="piper",
              path="/v/c.onnx", sample_rate=22050),
        Voice("Piper en_GB-alan-medium", "NotSet", "en-GB", engine="piper",
              path="/v/a.onnx", sample_rate=22050),
    ]
    #: Enough to cross VOICE_INLINE_MAX, alternating so both cascades are populated.
    EDGE = [
        Voice("Natural en-US-V%02dNeural" % i, "Female" if i % 2 else "Male", "en-US",
              engine="edge", path="en-US-V%02dNeural" % i, sample_rate=24000)
        for i in range(20)
    ]

    def sub(self, voices) -> FakeMenu:
        menu = self.build(self.profile(), speaker=mock.Mock(voice=None), voices=voices)
        return menu.cascades["Settings"].cascades["Voice"]

    def test_a_long_engine_becomes_two_rows_instead_of_twenty(self):
        sub = self.sub(self.PIPER + self.EDGE)
        self.assertIn("Microsoft Natural — Female", sub.cascades)
        self.assertIn("Microsoft Natural — Male", sub.cascades)
        # None of its voices are inline; all of them are reachable.
        self.assertFalse([r for r in sub.radios if r[1].startswith("Natural ")])
        inside = (sub.cascades["Microsoft Natural — Female"].radios
                  + sub.cascades["Microsoft Natural — Male"].radios)
        self.assertEqual(len(inside), len(self.EDGE))

    def test_a_short_engine_stays_inline_and_comes_first(self):
        sub = self.sub(self.PIPER + self.EDGE)
        # Nesting a list you can already read costs a click and buys nothing.
        self.assertIn(("Piper en_GB-cori-high (en-GB)", "Piper en_GB-cori-high"),
                      sub.radios)
        self.assertLess(sub.order.index("Piper"),
                        sub.order.index("Microsoft Natural — Female"))

    def test_with_no_extras_it_is_the_flat_list_it_always_was(self):
        # The default install. Nine Windows voices is under the threshold, so nothing
        # nests and the menu looks exactly as it did before any of this.
        windows = [Voice("Microsoft V%d" % i, "Male", "en-GB") for i in range(9)]
        sub = self.sub(windows)
        self.assertEqual(sub.cascades, {})
        self.assertEqual(len(sub.radios), len(windows) + 1)  # + Engine default

    def test_a_voice_with_no_gender_still_appears_in_a_nested_engine(self):
        # `VOICE_GENDER_GROUPS` ends in a catch-all precisely so that a voice declaring
        # nothing cannot fall out of the menu and become unselectable.
        odd = self.EDGE + [Voice("Natural en-US-MysteryNeural", "NotSet", "en-US",
                                 engine="edge", path="x", sample_rate=24000)]
        sub = self.sub(odd)
        self.assertIn("Microsoft Natural — Other", sub.cascades)
        self.assertIn(("Natural en-US-MysteryNeural (en-US)",
                       "Natural en-US-MysteryNeural"),
                      sub.cascades["Microsoft Natural — Other"].radios)

    def test_choosing_a_nested_voice_reaches_the_session(self):
        sub = self.sub(self.PIPER + self.EDGE)
        inner = sub.cascades["Microsoft Natural — Female"]
        label = inner.radios[0][0]
        inner.commands[label]()
        self.pill.session.set_voice.assert_called_once_with(inner.radios[0][1])


if __name__ == "__main__":
    unittest.main()


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
