"""What the compact surface says when it has something to say.

Four defects, one theme, and the theme is the 2026-09-04 decision: *a surface
that removes words takes on the obligation to answer, in whatever vocabulary
it has left, the questions the words were answering.* `_pump_events` handled
six event kinds and dropped four on the floor — a spoken send trigger did
nothing at all, and a rejected utterance, an applied correction and every one
of Send's refusals were silence on a pill whose only other channel is a
colour. P2 is that nothing spoken is ever lost silently; a note nobody can see
is the silent half.

Beside them, three things that were wrong for the same underlying reason — a
rule living in one of the two places that need it:

- the menu's mode radios went straight at `session.toggle_mode`, so the
  "a pending paste belongs to the mode it was spoken in" rule that the tap
  obeys was bypassed by the other way of changing mode;
- `_design_menu` built a fresh submenu per right-click, which `delete` unlinks
  and never destroys;
- `_talk_start` cleared the panel's blocks at the press, so a hold that heard
  nothing destroyed the answer that was on screen.

And `Session.provider`, the public read the surface's two `_provider()` calls
should always have been.

The fixtures are test_ui_compact's own — `__new__` plus class defaults, never
`__init__` — and the menu fakes are test_menu's.
"""

import unittest
from pathlib import Path
from unittest import mock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import flow.ui_compact as uc  # noqa: E402
from flow.session import (  # noqa: E402
    CONVERSE, DICTATE, REFINE, Event, Session,
)
from test_ui_compact import Canvas, panel_pill, pill  # noqa: E402
from test_menu import FakeMenu, FakeVar  # noqa: E402


def said(p) -> list:
    """Every sentence the notice strip was asked to show, in order."""
    return [call.args[0] for call in p._say.call_args_list]


def saying_pill(**attrs):
    """A pill whose strip records rather than resizing a window it has not got."""
    p = pill(**attrs)
    p._say = mock.Mock()
    return p


class TestTheSpokenSendTriggerPresses(unittest.TestCase):
    """`session.py:2231, 2332` emit `send` when the trigger word is spoken —
    "boom", or "enter boom" for a paste that presses Enter after itself
    (`edits.enter_word`). The shipped surface routes it to `_send`
    (ui.py:4558); here it fell through the event loop and the word was inert.
    """

    def sending(self, sent, text="the plan for Tuesday"):
        p = pill(on_send=lambda t, target=None, **kw: sent.append((t, kw)) or "")
        p.session.send.return_value = text
        return p

    def test_a_send_event_pastes_the_draft(self):
        sent = []
        p = self.sending(sent)
        p.session.events.return_value = [Event("send", "plain")]
        p._pump_events()
        p.session.send.assert_called_once_with()
        self.assertEqual(sent, [("the plan for Tuesday", {})])

    def test_a_plain_trigger_passes_no_submit_kwarg_at_all(self):
        # ui.py:3803-3806's idiom, kept: `extra = {"submit": True} if submit
        # else {}`, so a handler written before the flag — `send_check.py`'s
        # two-argument fixture — still takes the call.
        sent = []
        p = self.sending(sent)
        p.on_send = lambda t, target=None: sent.append((t, {})) or ""
        p.session.events.return_value = [Event("send", "plain")]
        p._pump_events()
        self.assertEqual(sent, [("the plan for Tuesday", {})])

    def test_enter_boom_asks_for_the_enter(self):
        sent = []
        p = self.sending(sent)
        p.session.events.return_value = [Event("send", "enter")]
        p._pump_events()
        self.assertEqual(sent, [("the plan for Tuesday", {"submit": True})])

    def test_the_trigger_and_a_waiting_release_do_not_both_send(self):
        # `_send`'s first line is what stops it, the same line ui.py:3795 is:
        # a hold owns one send and whoever gets there first has it.
        sent = []
        p = self.sending(sent)
        p._send_pending = True
        p.session.events.return_value = [Event("send", "plain")]
        p._pump_events()
        self.assertFalse(p._send_pending)
        self.assertEqual(len(sent), 1)

    def test_in_a_panel_mode_the_trigger_asks_and_pastes_nothing(self):
        # `session.send()` returns "" in REFINE and CONVERSE and starts the
        # CLI call instead — no special casing here, exactly as the shipped
        # `_send` has none.
        sent = []
        p = self.sending(sent, text="")
        p.session.mode = CONVERSE
        p.session.events.return_value = [Event("send", "plain")]
        p._pump_events()
        p.session.send.assert_called_once_with()
        self.assertEqual(sent, [])

    def test_with_no_handler_the_enter_variant_says_the_step_that_is_yours(self):
        # States.dc.html's last case, plus ui.py's `COPIED_ENTER` argument: the
        # clipboard cannot press Enter, and refusing the enter-variant would
        # make a decode that dropped the word the working case.
        p = saying_pill()
        p.on_send = None
        p.session.send.return_value = "the words"
        with mock.patch.object(uc, "_copy_to_clipboard", return_value=""):
            p.session.events.return_value = [Event("send", "enter")]
            p._pump_events()
        self.assertEqual(said(p), [uc.COPIED_ENTER_TEXT])

    def test_a_plain_one_with_no_handler_says_the_ordinary_line(self):
        p = saying_pill()
        p.on_send = None
        p.session.send.return_value = "the words"
        with mock.patch.object(uc, "_copy_to_clipboard", return_value=""):
            p.session.events.return_value = [Event("send", "plain")]
            p._pump_events()
        self.assertEqual(said(p), [uc.COPIED_TEXT])


class TestARejectionIsNeverSilent(unittest.TestCase):
    """P2: "Never loses words silently". A `drop` is an utterance Flow threw
    away (`session.py:1688`), and on a surface with no panel it had no way of
    being noticed at all."""

    def test_a_drop_is_said_on_the_strip(self):
        p = saying_pill()
        p.session.events.return_value = [
            Event("drop", "dropped 3 words — too quiet to be sure")]
        p._pump_events()
        self.assertEqual(said(p), ["dropped 3 words — too quiet to be sure"])

    def test_a_drop_is_not_an_error(self):
        # Grey, not red: Flow declined to guess, which is not a failure.
        p = saying_pill()
        p.session.events.return_value = [Event("drop", "dropped 3 words")]
        p._pump_events()
        self.assertEqual(p._flash, 0)


class TestACorrectionSaysWhatItChanged(unittest.TestCase):
    """`edit` is the one feedback a spoken correction gets (`session.py:2321`,
    `describe_change`). The shipped surface notes it with a way back; this one
    has no chip to offer and says the fact, which is the half it can do."""

    def test_an_edit_is_said_on_the_strip(self):
        p = saying_pill()
        p.session.events.return_value = [
            Event("edit", "changed “thursday” to “Tuesday”")]
        p._pump_events()
        self.assertEqual(said(p), ["changed “thursday” to “Tuesday”"])


class TestTheNotesAWordlessPillMustAnswer(unittest.TestCase):
    """`SAID_NOTES`: the notes no colour can carry, and the ones deliberately
    left to the ring and the glyph.

    Send's refusals are why this exists. Press the `send` hotkey with an empty
    draft on this surface and *nothing whatsoever happened* — the session said
    "nothing to send - the draft is empty" into a channel that did not exist.
    """

    REFUSALS = (
        "nothing to send - the draft is empty",
        "nothing to ask - say a question first",
        "nothing to refine - the draft is empty",
        "still waiting on the last answer",
        "still rewriting - one moment",
    )

    def note(self, text):
        p = saying_pill()
        p.session.events.return_value = [Event("note", text)]
        p._pump_events()
        return said(p)

    def test_every_send_refusal_is_said(self):
        for text in self.REFUSALS:
            with self.subTest(note=text):
                self.assertEqual(self.note(text), [text])

    def test_the_truncations_are_said(self):
        # R11 caps what the CLI is handed (`session.py:3265, 3596`): from
        # outside, a capped refine looks like the CLI ignoring most of the
        # request, and a capped ask is an answer to a question nobody asked.
        for text in (
                "only the last 4000 characters went to the CLI — the text "
                "before that is left as it is",
                "only the last 4000 characters of the question went — the CLI "
                "never saw the start of it"):
            with self.subTest(note=text[:24]):
                self.assertEqual(self.note(text), [text])

    def test_a_discarded_rewrite_is_said(self):
        text = "discarded a stale rewrite — the draft moved on"
        self.assertEqual(self.note(text), [text])

    def test_a_hold_stopped_for_you_is_said(self):
        text = ("stopped after 5 min — the chord was still held. What you "
                "said is here; press Send when you want it")
        self.assertEqual(self.note(text), [text])

    def test_a_mode_note_is_not_said(self):
        # The glyph's hue already carries it, and a 400 px strip on every tap
        # is how the strip that matters gets ignored.
        self.assertEqual(
            self.note("dictate mode - Send pastes into the focused window"),
            [])

    def test_progress_notes_are_not_said(self):
        for text in ("no more speech - asking · in ~/dev/products/flow",
                     "new conversation", "brought back the last prompt",
                     "agent CLI: claude"):
            with self.subTest(note=text):
                self.assertEqual(self.note(text), [])

    def test_the_list_is_prefixes_and_says_which(self):
        self.assertEqual(uc.SAID_NOTES,
                         ("nothing to", "still ", "only the last",
                          "discarded", "stopped after"))

    def test_a_conversation_event_needs_nothing(self):
        # Nothing of the conversation is on this screen to clear.
        p = saying_pill()
        p.session.events.return_value = [Event("conversation", "")]
        p._pump_events()
        self.assertEqual(said(p), [])


class TestOneSeamForEveryModeChange(unittest.TestCase):
    """"A pending paste belongs to the mode it was spoken in"
    (ui.py:4363-4369). The tap obeyed it and the menu's radios did not, so
    choosing Ask with a Type paste waiting sent the words to the CLI as a
    question instead of pasting them."""

    def menu(self, mode=DICTATE):
        p = pill(mode=mode)
        p.session.profile = mock.Mock(design="compact")
        m = FakeMenu()
        with mock.patch.object(uc.tk, "StringVar", FakeVar), \
                mock.patch.object(uc, "_dark_menu", FakeMenu):
            p._populate_menu(m)
        return p, m

    def test_a_menu_choice_drops_a_pending_send(self):
        p, m = self.menu()
        p._send_pending = True
        m.commands["Ask"]()
        self.assertFalse(p._send_pending)
        p.session.toggle_mode.assert_called_once_with(to=CONVERSE)

    def test_a_menu_choice_drops_a_pending_ask(self):
        # The mirror: a release in Ask still waiting on its decode must not
        # fire an ask into a session that is now in Type.
        p, m = self.menu(mode=CONVERSE)
        p._ask_pending = True
        m.commands["Type"]()
        self.assertFalse(p._ask_pending)
        p.session.toggle_mode.assert_called_once_with(to=DICTATE)

    def test_the_tap_drops_both_through_the_same_seam(self):
        p = pill(mode=DICTATE)
        p._send_pending = p._ask_pending = True
        p._on_press()
        p._on_release()
        self.assertFalse(p._send_pending)
        self.assertFalse(p._ask_pending)
        p.session.toggle_mode.assert_called_once_with()

    def test_the_no_cli_way_back_drops_them_too(self):
        p = pill(mode=REFINE)
        p.session.provider = ""
        p._send_pending = p._ask_pending = True
        p._cycle_mode()
        self.assertFalse(p._send_pending)
        self.assertFalse(p._ask_pending)
        p.session.toggle_mode.assert_called_once_with(to=DICTATE)

    def test_the_words_themselves_are_never_dropped(self):
        # Only the arm goes. `toggle_mode`'s own promise is that the draft
        # survives a mode switch, and the pill never touches it.
        p, m = self.menu()
        p._last_draft = "the deploy failed after the migration"
        m.commands["Refine"]()
        self.assertEqual(p._last_draft,
                         "the deploy failed after the migration")


class TestTheDesignSubmenuIsBuiltOnce(unittest.TestCase):
    """`_on_menu` rebuilds the menu on every open, and `delete` unlinks a
    cascade entry without destroying the submenu behind it — so every
    right-click leaked a `tk.Menu` on a surface that is never closed."""

    def clicking(self):
        p = pill(mode=DICTATE)
        p.session.profile = mock.Mock(design="compact")
        p._menu = FakeMenu()
        p.no_activate = False
        built = []

        def factory(*a, **kw):
            m = FakeMenu()
            built.append(m)
            return m

        return p, built, factory

    def open_twice(self, p, factory):
        with mock.patch.object(uc.tk, "StringVar", FakeVar), \
                mock.patch.object(uc, "_dark_menu", factory):
            p._on_menu(mock.Mock(x_root=10, y_root=10))
            p._on_menu(mock.Mock(x_root=10, y_root=10))

    def test_two_right_clicks_build_one_submenu(self):
        p, built, factory = self.clicking()
        self.open_twice(p, factory)
        self.assertEqual(len(built), 1)
        self.assertIs(p._design_sub, built[0])

    def test_the_second_open_shows_the_cascade_again(self):
        # Kept once is not kept away: the entry is re-added to the rebuilt
        # menu, so the row is there on every open.
        p, built, factory = self.clicking()
        self.open_twice(p, factory)
        self.assertIs(p._menu.cascades["Design"], p._design_sub)

    def test_the_rows_are_refreshed_not_doubled(self):
        # The refresh is what the `(current)` marker needs — and a submenu
        # that was added to twice would show every design twice.
        p, built, factory = self.clicking()
        self.open_twice(p, factory)
        self.assertEqual(p._design_sub.order, ["Current", "Compact   (current)"])

    def test_a_kept_submenu_still_moves_its_marker(self):
        # The rows are read off the surface on every open rather than frozen
        # when the submenu was first built. `DESIGN` is what the marker follows
        # now — the surface you are looking at, not the field the profile
        # stores — and no live pill changes it mid-process, so the fixture
        # moves it by hand to prove the refresh is a refresh.
        p, built, factory = self.clicking()
        with mock.patch.object(uc.tk, "StringVar", FakeVar), \
                mock.patch.object(uc, "_dark_menu", factory):
            p._on_menu(mock.Mock(x_root=10, y_root=10))
            p.DESIGN = "current"
            p._on_menu(mock.Mock(x_root=10, y_root=10))
        self.assertEqual(p._design_sub.order, ["Current   (current)", "Compact"])

    def test_the_default_is_on_the_class(self):
        # The same RecursionError guard every other attribute here carries:
        # `_design_menu` reads it on a `__new__`-built fixture.
        self.assertTrue(hasattr(uc.CompactPill, "_design_sub"))
        self.assertIsNone(uc.CompactPill._design_sub)


class TestASilentHoldKeepsTheAnswer(unittest.TestCase):
    """Ask.dc.html's "the next hold starts fresh" is about the thread, not
    about destroying a visible answer before a word has arrived.

    Hold to reply, hear nothing or change your mind, let go: `_talk_end` found
    nothing pending over a band emptied at the press and closed the panel, so
    the answer somebody was reading disappeared because they touched the
    button."""

    def answered(self):
        p = panel_pill(mode=CONVERSE)
        p._panel_open = True
        p._panel_mode = CONVERSE
        p._panel_heard = "where does the pill decide?"
        p._panel_heard_final = True
        p._panel_result = "PILL_HOLD_SEC, 0.30 s."
        return p

    def test_a_silent_hold_leaves_the_answer_on_screen(self):
        p = self.answered()
        p._talk_start()
        p.session.talk_end.return_value = False  # nothing was said
        p._talk_end(send=True)
        self.assertEqual(p._panel_result, "PILL_HOLD_SEC, 0.30 s.")
        self.assertEqual(p._panel_heard, "where does the pill decide?")

    def test_and_the_panel_stays_open_because_it_has_something_to_show(self):
        # `_talk_end`'s existing rule, which the clear-at-press had made
        # unreachable: the band goes down only when it is empty.
        p = self.answered()
        p._talk_start()
        p.session.talk_end.return_value = False
        p._talk_end(send=True)
        self.assertTrue(p._panel_open)

    def test_the_first_partial_of_a_real_reply_clears_it(self):
        p = self.answered()
        p._talk_start()
        self.assertTrue(p._hold_fresh)
        p.session.events.return_value = [Event("partial", "and what about")]
        p._pump_events()
        self.assertEqual(p._panel_result, "")
        self.assertEqual(p._panel_heard, "and what about")
        self.assertFalse(p._panel_heard_final)
        self.assertFalse(p._hold_fresh)

    def test_only_the_first_partial_clears(self):
        # The clear is the hold's, not every partial's: a result arriving
        # mid-hold is not something a later partial should wipe.
        p = self.answered()
        p._talk_start()
        p.session.events.return_value = [Event("partial", "and what")]
        p._pump_events()
        p._panel_result = "an answer that arrived since"
        p.session.events.return_value = [Event("partial", "and what about")]
        p._pump_events()
        self.assertEqual(p._panel_result, "an answer that arrived since")

    def test_a_hold_whose_words_only_land_in_the_draft_still_starts_fresh(self):
        # Short enough for no partial: `_ask` is the other end of the same
        # deferred clear.
        p = self.answered()
        p._talk_start()
        p.session.talk_end.return_value = True
        p._talk_end(send=True)
        # The decode lands on the draft, and the frame — not the event —
        # fires the ask once the decoder is idle (`_pump_send`).
        p.session.draft.text = "and what about the foot?"
        p.session.events.return_value = [
            Event("draft", "and what about the foot?")]
        p._pump_events()
        p._pump_send()
        self.assertEqual(p._panel_heard, "and what about the foot?")
        self.assertEqual(p._panel_result, "")
        self.assertFalse(p._hold_fresh)

    def test_a_hold_over_a_closed_band_starts_clean(self):
        # Esc dismissed the exchange. A hold that then hears nothing goes
        # straight back to grey (States.dc.html, third case) — it must not
        # raise the dismissed answer and leave it standing, which is what
        # keeping the blocks across a *closed* band did.
        p = self.answered()
        p._close_panel()
        p._talk_start()
        self.assertTrue(p._panel_open)
        self.assertEqual((p._panel_heard, p._panel_result), ("", ""))
        p.session.talk_end.return_value = False
        p._talk_end(send=True)
        self.assertFalse(p._panel_open)

    def test_an_answer_that_lands_mid_hold_is_not_wiped_by_the_next_word(self):
        # 4-20 s of CLI is long enough that somebody holds again before the
        # answer arrives. When it does, it is newer than the exchange the hold
        # was going to clear — so it stands, and the follow-up's own answer
        # replaces it when that lands.
        p = self.answered()
        p._talk_start()
        p.session.events.return_value = [Event("reply", "the late answer")]
        p._pump_events()
        self.assertFalse(p._hold_fresh)
        p.session.events.return_value = [Event("partial", "and also")]
        p._pump_events()
        self.assertEqual(p._panel_result, "the late answer")

    def test_a_failed_refine_is_cleared_by_the_next_holds_words(self):
        # The CLI's last line is a result like any other, and Send falls back
        # to the raw dictation while it stands (`_panel_text`). A new hold's
        # first partial retires both.
        p = panel_pill(mode=REFINE)
        p._panel_open = True
        p._panel_mode = REFINE
        p._panel_failed = True
        p._panel_result = "refine failed (timed out) — draft unchanged"
        p._talk_start()
        self.assertTrue(p._panel_failed)  # still standing while nothing is said
        p.session.events.return_value = [Event("partial", "try that again")]
        p._pump_events()
        self.assertFalse(p._panel_failed)
        self.assertEqual(p._panel_result, "")

    def test_the_flag_is_a_class_attribute(self):
        self.assertTrue(hasattr(uc.CompactPill, "_hold_fresh"))
        self.assertFalse(uc.CompactPill._hold_fresh)


class TestTheProviderIsAPublicSeam(unittest.TestCase):
    """`_cli_offered` and `_setup_rows` called `session._provider()` — a UI
    reading the session's implementation for a fact the session is happy to
    state. `Session.provider` is that fact, read-only, and cheap enough for a
    frame: a pin or `_available`'s `CLI_LOOKUP_SEC` cache is underneath it."""

    def test_the_property_answers_what_provider_answers(self):
        with mock.patch.object(Session, "_provider", return_value="claude"):
            s = Session.__new__(Session)
            self.assertEqual(s.provider, "claude")

    def test_no_cli_is_the_empty_string_not_none(self):
        # `_cli_offered` is `bool(...)` over this, and the setup box's
        # "none found" is `or`-ed onto it: both want a falsey string.
        with mock.patch.object(Session, "_provider", return_value=""):
            s = Session.__new__(Session)
            self.assertEqual(s.provider, "")

    def test_it_is_read_only(self):
        # The surface pulls facts; the session is never told one.
        with mock.patch.object(Session, "_provider", return_value="claude"):
            s = Session.__new__(Session)
            with self.assertRaises(AttributeError):
                s.provider = "codex"

    def test_the_cli_offered_check_goes_through_it(self):
        p = pill()
        p.session.provider = "claude"
        self.assertTrue(p._cli_offered())
        p.session.provider = ""
        self.assertFalse(p._cli_offered())

    def test_the_setup_box_names_it(self):
        p = panel_pill(mode=CONVERSE)
        p.session.mic = mock.Mock(device_name="Yeti Nano")
        p.session.provider = "claude"
        p.session.pastes = True
        self.assertEqual(p._setup_rows()[1], ("Agent CLI", "claude"))

    def test_the_surface_no_longer_reaches_for_the_private_one(self):
        # The two call sites, pinned as calls rather than as the word: a
        # comment may well go on naming the method this replaced, and a
        # rename of it must not be able to break the UI silently again.
        source = Path(uc.__file__).read_text(encoding="utf-8")
        self.assertNotIn("._provider()", source)


class TestTheStripIsTheChannelForAllOfIt(unittest.TestCase):
    """One strip, one mechanism: `_say` sizes itself to its sentence and
    counts down. The new kinds are callers of it, not four new surfaces."""

    def test_a_said_note_sizes_the_strip_to_its_words(self):
        p = panel_pill(x=100, y=400)
        p.paint = p.canvas = Canvas()
        p.session.events.return_value = [
            Event("note", "nothing to send - the draft is empty")]
        p._pump_events()
        self.assertEqual(p._notice, uc.COPIED_FRAMES)
        self.assertEqual(p._notice_text, "nothing to send - the draft is empty")
        self.assertGreater(p._notice_w, uc.PILL_W)

    def test_the_sentence_is_drawn_under_the_pill(self):
        p = panel_pill(x=100, y=400)
        p.paint = p.canvas = Canvas()
        p.session.events.return_value = [Event("drop", "dropped 3 words")]
        p._pump_events()
        p._draw()
        self.assertIn("dropped 3 words", [t[1] for t in p.canvas.texts])

    def test_it_is_dim_and_never_an_error_colour(self):
        # A rejection and a refusal are things to know, not failures of
        # Flow's — the same argument the muted-mic line was written under.
        p = panel_pill(x=100, y=400)
        p.paint = p.canvas = Canvas()
        p._notice, p._notice_text = 2, "nothing to send - the draft is empty"
        p._shell_h = uc.PILL_H + uc.NOTICE_H
        p._draw_notice(p.canvas)
        fills = {t[2] for t in p.canvas.texts}
        self.assertIn(uc.DIM, fills)
        self.assertNotIn(uc.ERROR, fills)


if __name__ == "__main__":
    unittest.main()
