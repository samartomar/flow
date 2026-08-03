"""Repairing a mis-heard command by hand, instead of saying it again.

Until now the only way to fix text the decoder got wrong was to say it again, into the
same decoder that got it wrong — an unwinnable loop for the speaker this product is for,
and the reason the owner reports correcting text *after* Send. The live sheet scored
55/73/55% against P3's >= 95%, so the escape hatch is not an edge case.

Three things make a keyboard editor harder than a text box, and all three are pinned
here rather than in the code that hopes for them:

**Invariant 10.** Flow's windows sit outside the activation chain so a paste can never
land on Flow itself. Taking keyboard focus into the bubble runs straight at that, so the
refusal is asserted *while the editor holds the focus* — which is the arrangement that
would break it if anything could.

**The microphone.** Typing while the mic is open appends the room to the text being
typed. Capture is suspended for the duration, and invariant 4 says a suspension has to be
audible as a note or it is just deafness.

**The countdown.** The editor commits once, on close, so converse mode sees a settled
draft and guaranteed silence — and would ask a half-typed question with no press.
"""

import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.audio import BLOCK  # noqa: E402
from flow.session import AUTO_ASK_SEC, CONVERSE, Session, State  # noqa: E402

LOUD = np.full(BLOCK, 0.2, dtype=np.float32)


class FakeMic:
    def __init__(self) -> None:
        self._blocks: list[np.ndarray] = []
        self.level_db = -60.0
        self.dropped = 0

    def start(self) -> None: ...

    def stop(self) -> None: ...

    @property
    def active(self) -> bool:
        return True

    def restart(self) -> None: ...

    def drain(self) -> list[np.ndarray]:
        out, self._blocks = self._blocks, []
        return out


class FakeAsr:
    loading = False

    def __init__(self, said: str = "") -> None:
        self.said = said

    def load(self, final=None) -> None: ...

    def text(self, audio, *, final=False, hotwords="") -> str:
        return self.said if final else ""


class Held:
    """A CLI call the test decides the duration of. Same shape as test_races.py's."""

    def __init__(self, result) -> None:
        self.result = result
        self.started = threading.Event()
        self.release = threading.Event()

    def __call__(self, text, *args, **kwargs):
        self.started.set()
        self.release.wait(5.0)
        return self.result


def session(**kw) -> Session:
    return Session(asr=kw.pop("asr", None) or FakeAsr(), mic=FakeMic(), **kw)


def notes(s) -> str:
    return " | ".join(e.text for e in s.events() if e.kind == "note")


class TestTheEditIsAnOrdinaryDraftChange(unittest.TestCase):
    """Written through `Draft.set()`, so undo and the revision come for free."""

    def test_opening_the_editor_hands_back_what_is_on_screen(self):
        s = session()
        s.draft.set("deploy the roleback plan")
        self.assertEqual(s.begin_edit(), "deploy the roleback plan")
        self.assertTrue(s.editing)

    def test_committing_moves_the_revision_and_pushes_undo(self):
        s = session()
        s.draft.set("deploy the roleback plan")
        was = s.draft.revision
        s.begin_edit()
        s.commit_edit("deploy the rollback plan")
        self.assertEqual(s.draft.text, "deploy the rollback plan")
        self.assertGreater(s.draft.revision, was)
        s.draft.undo()
        self.assertEqual(s.draft.text, "deploy the roleback plan")

    def test_cancelling_leaves_the_draft_exactly_as_it_was(self):
        s = session()
        s.draft.set("deploy the roleback plan")
        was = s.draft.revision
        s.begin_edit()
        s.cancel_edit()
        self.assertEqual(s.draft.text, "deploy the roleback plan")
        self.assertEqual(s.draft.revision, was)
        self.assertFalse(s.editing)

    def test_committing_the_same_text_is_not_a_change(self):
        # Opening the editor and closing it without typing must not push an undo entry
        # nobody asked for, or bump a revision a rewrite is checking against.
        s = session()
        s.draft.set("deploy the rollback plan")
        was = s.draft.revision
        s.begin_edit()
        s.commit_edit("deploy the rollback plan")
        self.assertEqual(s.draft.revision, was)

    def test_a_second_open_while_one_is_running_is_refused_and_says_so(self):
        s = session()
        s.draft.set("something")
        s.begin_edit()
        s.events()
        self.assertIsNone(s.begin_edit())
        self.assertIn("already", notes(s))

    def test_committing_when_nothing_is_open_does_nothing(self):
        s = session()
        s.draft.set("untouched")
        s.commit_edit("clobbered")
        self.assertEqual(s.draft.text, "untouched")


class TestARewriteCannotSurviveTheEdit(unittest.TestCase):
    """Invariant 11, reached through the keyboard instead of through speech."""

    def test_a_rewrite_in_flight_across_an_edit_is_discarded(self):
        s = session()
        s.draft.set("widen the column")
        held = Held(("widen the column and use the users table", "codex"))
        with mock.patch("flow.session.refine", held):
            s._start_refine("make it formal")
            self.assertTrue(held.started.wait(2.0))
            s.begin_edit()
            s.commit_edit("widen the id column")
            held.release.set()
            s.wait_idle(timeout=5.0)
        self.assertEqual(s.draft.text, "widen the id column")
        self.assertIn("stale", notes(s))


class TestTheMicrophoneIsShutAndSaysSo(unittest.TestCase):
    """Invariant 4: nothing is dropped *silently*. A suspension is not a silence."""

    def test_blocks_arriving_while_the_editor_is_open_are_not_heard(self):
        s = session()
        s.start()
        s.draft.set("a draft")
        s.begin_edit()
        for _ in range(8):
            s.mic._blocks.append(LOUD)
        s.tick()
        self.assertFalse(s.gate.speaking, "the gate opened on the room while typing")
        self.assertEqual(s._utter, [])
        s.close()

    def test_the_suspension_is_announced_and_the_resumption_too(self):
        s = session()
        s.draft.set("a draft")
        s.begin_edit()
        self.assertIn("microphone", notes(s).lower())
        s.commit_edit("a draft, edited")
        self.assertIn("listening", notes(s).lower())

    def test_the_meter_reads_deaf_and_the_indicator_says_which_deafness(self):
        s = session()
        s.draft.set("a draft")
        s.mic.level_db = -20.0
        s.begin_edit()
        self.assertFalse(s.hearing)
        self.assertIn("editing", s.activity.label)
        s.commit_edit("a draft")
        self.assertTrue(s.hearing)
        self.assertEqual(s.level_db, -20.0)

    def test_speech_already_in_flight_is_committed_not_dropped(self):
        # The speaker branch's precedent: words captured before the editor opened are
        # genuinely the user's, and the undo stack holds words, not sound.
        s = session()
        s.start()
        s._utter = [LOUD]
        s.begin_edit()
        self.assertEqual(s._utter, [], "the words in flight went nowhere")
        s.close()


class TestTheCountdownIsHeld(unittest.TestCase):
    """The premature-fire class this item must not ship."""

    def test_nothing_is_asked_while_the_editor_is_open(self):
        s = session()
        s.toggle_mode()
        self.assertEqual(s.mode, CONVERSE)
        s.draft.set("what is a rollback")
        s._after_draft_change()
        s.begin_edit()
        self.assertIsNone(s.auto_ask_in, "the countdown is still running")
        s._settled_at = time.perf_counter() - (AUTO_ASK_SEC + 1.0)
        with mock.patch("flow.session.ask", return_value=("an answer", "codex")) as asked:
            s.tick()
            asked.assert_not_called()
        self.assertEqual(s.draft.text, "what is a rollback")
        s.close()

    def test_the_countdown_starts_again_from_the_commit_not_from_before_it(self):
        s = session()
        s.toggle_mode()
        s.draft.set("what is a rollback")
        s._after_draft_change()
        s.begin_edit()
        s._settled_at = time.perf_counter() - (AUTO_ASK_SEC + 1.0)
        s.commit_edit("what is a rollback in postgres")
        left = s.auto_ask_in
        self.assertIsNotNone(left, "the countdown never came back")
        self.assertGreater(left, AUTO_ASK_SEC - 1.0)
        s.close()

    def test_a_cancel_releases_the_hold_as_well(self):
        s = session()
        s.toggle_mode()
        s.draft.set("what is a rollback")
        s._after_draft_change()
        s.begin_edit()
        s.cancel_edit()
        self.assertIsNotNone(s.auto_ask_in)
        s.close()


@unittest.skipUnless(sys.platform == "win32", "Windows-only: ctypes.WinDLL")
class TestFlowStillCannotPasteIntoItself(unittest.TestCase):
    """Invariant 10, asserted in the arrangement the editor creates.

    The refusal is a live process-id check on whatever actually has the foreground, not
    a property of the window style — which is why deliberately taking the focus cannot
    weaken it. That is the claim; this is the proof, and if it ever fails the editor is
    the thing that goes, not the invariant.
    """

    def test_resolve_refuses_while_the_editor_holds_the_foreground(self):
        import flow.inject as inject

        editor_hwnd, aimed_at = 0x1111, 0x2222
        with mock.patch.object(inject, "foreground_hwnd", return_value=editor_hwnd), \
                mock.patch.object(inject, "owned_by_flow",
                                  side_effect=lambda h: h == editor_hwnd), \
                mock.patch.object(inject, "_process_name", return_value="python.exe"):
            target = inject.resolve(aimed_at)
        self.assertTrue(target.is_flow)

    def test_and_the_paste_itself_refuses_and_names_what_happened(self):
        import flow.inject as inject

        editor_hwnd, aimed_at = 0x1111, 0x2222
        inject.take_warnings()
        with mock.patch.object(inject, "foreground_hwnd", return_value=editor_hwnd), \
                mock.patch.object(inject, "owned_by_flow",
                                  side_effect=lambda h: h == editor_hwnd), \
                mock.patch.object(inject, "_process_name", return_value="python.exe"), \
                mock.patch.object(inject, "set_clipboard_text") as wrote:
            self.assertFalse(inject.paste("deploy it\n", hwnd=aimed_at))
            wrote.assert_not_called()
        self.assertIn("Flow had the focus", " | ".join(inject.take_warnings()))

    def test_the_editor_never_becomes_the_window_send_is_aimed_at(self):
        # `_track_target` keeps the last foreground that was not Flow's own, so the
        # window the user was dictating into survives the whole edit.
        import flow.ui as ui

        pill = ui.Pill.__new__(ui.Pill)
        pill.paste_target = 0x2222
        with mock.patch.object(ui, "foreground_hwnd", return_value=0x1111), \
                mock.patch.object(ui, "owned_by_flow", return_value=True):
            for _ in range(10):
                pill._track_target()
        self.assertEqual(pill.paste_target, 0x2222)


class TestTheBubbleCarriesIt(unittest.TestCase):
    """The chip and the box, driven without a desktop the way `_open_settings` is."""

    def _bubble(self, text="a draft", editing=False):
        import flow.ui as ui

        b = ui.Bubble.__new__(ui.Bubble)
        b.pill = mock.Mock()
        b.pill.session = mock.Mock(
            mode="dictate", can_rescue=False, editing=editing, auto_ask_in=None,
        )
        b.pill.accent = "#000000"
        b.canvas = mock.Mock()
        b._text, b._sent, b._reply, b._partial, b._note = text, "", "", "", ""
        b._editor = None
        b._sent_at = time.perf_counter()
        b._h = 120
        return b

    def _keys(self, bubble) -> list[str]:
        import flow.ui as ui

        laid: list[str] = []
        with mock.patch.object(ui.Bubble, "_lay_out",
                               lambda _self, specs: laid.extend(k for k, _l, _c in specs)):
            bubble._chips()
        return laid

    def test_a_draft_offers_an_edit_chip(self):
        self.assertIn("Edit", self._keys(self._bubble()))

    def test_the_sent_card_does_not(self):
        b = self._bubble()
        b._sent, b._text = "already gone", ""
        self.assertNotIn("Edit", self._keys(b))

    def test_with_no_draft_there_is_nothing_to_edit(self):
        self.assertNotIn("Edit", self._keys(self._bubble(text="")))

    def test_while_editing_the_row_offers_done_and_cancel_instead(self):
        keys = self._keys(self._bubble(editing=True))
        self.assertIn("Done", keys)
        self.assertIn("Cancel", keys)
        self.assertNotIn("Edit", keys)
        self.assertNotIn("Refine", keys)


class TestTheUseThisChip(unittest.TestCase):
    """The floor for item 21, whatever the spoken form does: a chip cannot be misheard.

    Gated the way "Was a command" is — only while there is something to act on. A chip
    that is always present but usually does nothing teaches people to ignore it.
    """

    def _bubble(self, reply="an answer", can_take=True):
        import flow.ui as ui

        b = ui.Bubble.__new__(ui.Bubble)
        b.pill = mock.Mock()
        b.pill.session = mock.Mock(
            mode="dictate", can_rescue=False, editing=False, auto_ask_in=None,
            can_take_reply=can_take,
        )
        b.pill.accent = "#000000"
        b.canvas = mock.Mock()
        b._text, b._sent, b._partial, b._note = "a draft", "", "", ""
        b._reply = reply
        b._editor, b._sent_at, b._h = None, time.perf_counter(), 120
        return b

    def _keys(self, bubble) -> list[str]:
        import flow.ui as ui

        laid: list[str] = []
        with mock.patch.object(ui.Bubble, "_lay_out",
                               lambda _self, specs: laid.extend(k for k, _l, _c in specs)):
            bubble._chips()
        return laid

    def test_a_reply_on_screen_offers_it(self):
        self.assertIn("Use this", self._keys(self._bubble()))

    def test_no_reply_no_chip(self):
        self.assertNotIn("Use this", self._keys(self._bubble(reply="")))

    def test_and_not_when_the_session_has_nothing_to_give(self):
        # Both halves are asked: the card can still be showing an answer the session has
        # already handed over, and offering to take it twice is offering nothing.
        self.assertNotIn("Use this", self._keys(self._bubble(can_take=False)))

    def test_the_sent_card_offers_only_put_it_back(self):
        b = self._bubble()
        b._sent, b._text = "already gone", ""
        self.assertEqual(self._keys(b), ["Put it back"])

    def test_tapping_it_takes_the_reply_and_clears_the_card(self):
        b = self._bubble()
        b.pill.session.take_reply.return_value = True
        with mock.patch.object(type(b), "_render"):
            b._take_reply()
        b.pill.session.take_reply.assert_called_once()
        self.assertEqual(b._reply, "", "the answer is on screen twice now")

    def test_a_refused_take_leaves_the_answer_where_it_is(self):
        b = self._bubble()
        b.pill.session.take_reply.return_value = False
        with mock.patch.object(type(b), "_render"):
            b._take_reply()
        self.assertEqual(b._reply, "an answer")


class TestAnEditorThatCannotHearIsClosed(unittest.TestCase):
    """A refused `SetForegroundWindow` reports itself by doing nothing.

    Measured on a real desktop: driven without a preceding click, the box opened with a
    cursor in it and the word typed into it went to the browser behind — Windows grants
    the foreground only to the process owning the last input event. A text box that
    silently collects nothing is worse than no editor, so the result is checked rather
    than assumed.
    """

    def _pill_and_bubble(self, took_focus: bool):
        import flow.ui as ui

        session = Session(asr=FakeAsr(), mic=FakeMic())
        session.draft.set("deploy the roleback plan")
        b = ui.Bubble.__new__(ui.Bubble)
        b.pill = mock.Mock(session=session, accent="#000000")
        b.canvas = mock.Mock()
        b._text, b._sent, b._reply, b._partial, b._note = session.draft.text, "", "", "", ""
        b._editor, b._previous_focus, b._h, b._visible = None, 0, 120, True
        b._sent_at = time.perf_counter()
        return session, b

    def _open(self, took_focus: bool):
        import flow.ui as ui

        session, b = self._pill_and_bubble(took_focus)
        with mock.patch.object(ui, "tk", mock.MagicMock()), \
                mock.patch.object(ui, "_user32"), \
                mock.patch.object(ui, "toplevel_hwnd", return_value=0x1111), \
                mock.patch.object(ui, "foreground_hwnd", return_value=0x1111), \
                mock.patch.object(ui, "owned_by_flow", return_value=took_focus), \
                mock.patch.object(ui.Bubble, "_render"):
            b._edit()
        return session, b

    def test_with_the_focus_taken_the_editor_stays_open(self):
        session, b = self._open(took_focus=True)
        self.assertTrue(session.editing)
        self.assertIsNotNone(b._editor)

    def test_without_it_the_editor_is_closed_and_the_reason_is_shown(self):
        session, b = self._open(took_focus=False)
        self.assertFalse(session.editing, "a box collecting nothing was left open")
        self.assertIsNone(b._editor)
        self.assertIn("focus", b._note)
        self.assertEqual(session.draft.text, "deploy the roleback plan")


if __name__ == "__main__":
    unittest.main()


#: The work area this machine reports, and the desktop every bubble fixture is laid out
#: against. It is a real input to `_render` now rather than only to `reposition`: the window
#: is fitted to it before anything reads the height, which is what keeps the chip row inside
#: the display when the reply path asks for 4 179 px of it. Lives here beside
#: `MeasuringCanvas` so `test_bubble.py` can borrow both — a second copy of a desktop the
#: two files have to agree about is the same drift risk as a second canvas.
WORK = (0, 0, 1280, 672)


class MeasuringCanvas:
    """A canvas that answers `bbox`, which is what a layout test needs.

    `RecordingCanvas` in test_indicator.py records what `_draw` puts on the pill and
    never measures anything, because the pill's geometry is fixed. The bubble's is not:
    it sizes itself to wrapped text, so a fake that cannot wrap cannot catch a bug about
    wrapping. Line height and character width are the Segoe UI values the real canvas
    reports for the two fonts this draws in; the exact numbers do not matter, only that
    more text means more lines.
    """

    LINE_H = {8: 13, 10: 17}
    CHAR_W = {8: 6, 10: 7}

    def __init__(self) -> None:
        self.items: list[dict] = []

    def delete(self, *a, **kw) -> None:
        self.items.clear()

    def configure(self, **kw) -> None: ...

    def create_polygon(self, *a, **kw) -> None: ...

    def create_oval(self, *a, **kw) -> None: ...

    def create_arc(self, *a, **kw) -> None: ...

    def create_line(self, *a, **kw) -> None: ...

    def create_rectangle(self, *a, **kw) -> None: ...

    def tag_bind(self, *a, **kw) -> None: ...

    def tag_raise(self, *a, **kw) -> None: ...

    def itemconfigure(self, *a, **kw) -> None: ...

    def create_text(self, x, y, text="", **kw):
        size = (kw.get("font") or ("", 10))[1]
        width = kw.get("width")
        per_line = max(1, int(width / self.CHAR_W.get(size, 7))) if width else 10**6
        lines = max(1, -(-len(text) // per_line))
        item = {
            "x": x, "y": y, "text": text, "anchor": kw.get("anchor", "center"),
            "h": lines * self.LINE_H.get(size, 17), "lines": lines,
        }
        self.items.append(item)
        return len(self.items) - 1

    def bbox(self, item):
        it = self.items[item]
        top = it["y"] if "n" in it["anchor"] else it["y"] - it["h"]
        return (it["x"], top, it["x"] + 10, top + it["h"])

    def band(self, needle: str) -> tuple[float, float]:
        """The vertical band the item containing `needle` occupies."""
        it = next(i for i in self.items if needle in i["text"])
        top = it["y"] if "n" in it["anchor"] else it["y"] - it["h"]
        return top, top + it["h"]


class TestALongNoteDoesNotLandOnTheChips(unittest.TestCase):
    """The bubble sizes itself to wrapped text everywhere except the note.

    Reported from a Hyper-V VM on 2026-08-02: an Ask failed, and the failure — the one
    sentence explaining why — was drawn across the Refine / Continue / Ask row, leaving
    fragments of both readable and neither legible. "can not see due to overlap".

    `_render` measures the draft with a probe and a `bbox`, and says so in a comment:
    *"Measure first: the window has to be sized to the wrapped text."* The note is the
    one thing it does not measure — it reserved a flat 18 px, one line's worth, and drew
    at a fixed offset from the bottom with `anchor="nw"`, so every line past the first
    grew downward into the chips.

    The error that found it is 84 characters, which is three lines at this width. Errors
    are the longest strings this ever shows and the ones it is least acceptable to hide.
    """

    ERROR = ("ask failed (codex failed to start: [WinError 2] "
             "The system cannot find the file specified)")

    def _bubble(self, note: str, text: str = "a draft"):
        import flow.ui as ui

        b = ui.Bubble.__new__(ui.Bubble)
        b.pill = mock.Mock()
        b.pill.session = mock.Mock(
            mode="dictate", can_rescue=False, editing=False, auto_ask_in=None,
            can_take_reply=False,
        )
        b.pill.accent = "#000000"
        #: `_render` fits the window to the desktop before anything reads the height, so a
        #: bubble that renders needs a real work area. A `Mock` here is not a default — it
        #: is an unpackable that raises, which is the loud failure this would rather have
        #: than a fixture silently laying out against a screen of no particular size.
        b.pill.work = WORK
        b.canvas = MeasuringCanvas()
        b._text, b._sent, b._reply, b._partial, b._note = text, "", "", "", note
        b._editor = None
        b._act = None
        b._h = 120
        b.reposition = lambda *a, **kw: None
        return b

    def test_the_error_clears_the_chip_row(self):
        b = self._bubble(self.ERROR)
        b._render()
        note_top, note_bottom = b.canvas.band("WinError 2")
        chips_top = b._h - 14 - 26  # `_lay_out`: y2 = _h - PAD, y1 = y2 - 26
        self.assertGreater(note_bottom, note_top)
        self.assertLessEqual(
            note_bottom, chips_top,
            f"the note runs to y={note_bottom} and the chips start at y={chips_top}",
        )

    def test_the_bubble_grew_to_make_room_rather_than_clipping(self):
        # The other way to stop an overlap is to cut the text off, and for an error
        # message that is the same defect wearing a different hat.
        short = self._bubble("ok")
        short._render()
        long_ = self._bubble(self.ERROR)
        long_._render()
        self.assertGreater(long_._h, short._h)
        drawn = next(i for i in long_.canvas.items if "WinError 2" in i["text"])
        self.assertEqual(drawn["text"], self.ERROR, "the note must not be truncated")

    def test_a_one_line_note_still_sits_where_it_always_did(self):
        b = self._bubble("saved")
        b._render()
        _top, bottom = b.canvas.band("saved")
        self.assertLessEqual(bottom, b._h - 14 - 26)
