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
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from clipboard_env import sealed_clipboard  # noqa: E402
from flow.audio import BLOCK  # noqa: E402
from flow.diag import FIELDS  # noqa: E402
from flow.lexicon import NUL_PATH, Lexicon  # noqa: E402
from flow.profile import MAX_PAIRS, Profile  # noqa: E402
from flow.session import (  # noqa: E402
    AUTO_ASK_SEC,
    CONVERSE,
    Session,
    State,
    typed_pairs,
)

LOUD = np.full(BLOCK, 0.2, dtype=np.float32)

#: One class below calls `inject.paste()`, which reads the real clipboard. See
#: `clipboard_env.py`. It asserts on the return value rather than on the warnings, so it
#: survived the failure that module documents — by one assertion it does not make.
_CLIPBOARD = sealed_clipboard()


def setUpModule():
    _CLIPBOARD.start()


def tearDownModule():
    _CLIPBOARD.stop()


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


def tmp_profile() -> Profile:
    """A profile on a scratch path. `test_profile.py`'s helper, borrowed verbatim so the
    learning tests here and there are looking at the same object."""
    return Profile(Path(tempfile.mkdtemp()) / "profile.json")


class RecordingDiag:
    """`NullDiag`'s shape, keeping what it was handed. In memory rather than through
    `Diag` and a temporary file, because what is being asserted is what the *session*
    wrote — the file format has `test_diag.py`."""

    path = None

    def __init__(self) -> None:
        self.records: list[dict] = []

    def write(self, kind: str, /, **fields) -> None:
        self.records.append({"kind": kind, **fields})


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
        b._text, b._sent, b._partial, b._note = text, "", "", ""
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


# `TestTheUseThisChip` was here. The chip moved to `ConversationCard` with the answer it
# acts on (item 63), and so did its tests — `tests/test_card.py`. Item 21's floor is
# unchanged: a chip cannot be misheard, and it is still gated on both halves, the answer
# being on screen and the session still having one to give.


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
        b._text, b._sent, b._partial, b._note = session.draft.text, "", "", ""
        b._editor, b._previous_focus, b._h, b._visible = None, 0, 120, True
        b._sent_at = time.perf_counter()
        #: `after` needs an interpreter and a `__new__`-built window has none. Stubbed
        #: rather than guarded in the code: `_edit` schedules one repaint a frame later
        #: because a `tk.Text` cannot report its own layout until Tk has run, and that
        #: is a real requirement of the real widget rather than something to soften.
        b.after = lambda *a, **kw: None
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


def _tags(value) -> tuple:
    """Tk accepts a tag as a string or a tuple; this fake has to take both."""
    if value is None:
        return ()
    return (value,) if isinstance(value, str) else tuple(value)


class MeasuringCanvas:
    """A canvas that answers `bbox`, which is what a layout test needs.

    `RecordingCanvas` in test_indicator.py records what `_draw` puts on the pill and
    never measures anything, because the pill's geometry is fixed. The bubble's is not:
    it sizes itself to wrapped text, so a fake that cannot wrap cannot catch a bug about
    wrapping. Line height and character width are the real canvas's values for the
    fonts this draws in — Segoe UI at the point sizes item 61 shipped with, IBM Plex
    Sans at the pixel sizes `FONT_BODY`/`FONT_NOTE` moved to (decisions.md 2026-08-09,
    measured live: `IBM Plex Sans` at -14 reports an 18 px line and a 6.7 px average
    character, at -11 a 14 px line and a 5.4 px average) — the exact numbers do not
    matter, only that more text means more lines.
    """

    LINE_H = {8: 13, 10: 17, -14: 18, -11: 14}
    CHAR_W = {8: 6, 10: 7, -14: 7, -11: 5}

    def __init__(self) -> None:
        self.items: list[dict] = []
        #: (tag, sequence, callback) per `tag_bind`. Recorded since item 72, whose whole
        #: subject is whether a binding exists at all.
        self.bindings: list[tuple] = []

    def delete(self, *specs, **kw) -> None:
        """Tag-aware, since item 66 made the tag the whole point.

        `_render` deletes the `body` tag and leaves the chip row standing, so a fake
        that cleared everything on any `delete` would report a card with no body on it
        and, worse, would make the persistence being tested invisible.
        """
        if not specs or "all" in specs:
            self.items.clear()
            return
        wanted = set(specs)
        self.items[:] = [i for i in self.items if not wanted & set(i["tags"])]

    def configure(self, **kw) -> None: ...

    def create_polygon(self, *a, **kw) -> None: ...

    def create_oval(self, *a, **kw) -> None: ...

    def create_arc(self, *a, **kw) -> None: ...

    def create_line(self, *a, **kw) -> None: ...

    def create_rectangle(self, x1, y1, x2, y2, **kw):
        """Recorded, unlike the other shapes: the editor's scroll bar is rectangles, and
        whether it is drawn at all is the assertion."""
        self.items.append({
            "x": x1, "y": y1, "text": "", "anchor": "nw", "h": y2 - y1, "lines": 0,
            "fill": kw.get("fill"), "tags": _tags(kw.get("tags")),
        })
        return len(self.items) - 1

    def tag_bind(self, tag=None, sequence=None, func=None, *a, **kw) -> None:
        self.bindings.append((tag, sequence, func))

    def tag_raise(self, *a, **kw) -> None: ...

    def itemconfigure(self, *a, **kw) -> None: ...

    def create_window(self, *a, **kw) -> None:
        """The embedded editor's slot. Recorded as nothing: this fake measures text, and
        a `tk.Text` measures itself — see `FakeBox`."""
        ...

    def create_text(self, x, y, text="", **kw):
        size = (kw.get("font") or ("", 10))[1]
        width = kw.get("width")
        per_line = max(1, int(width / self.CHAR_W.get(size, 7))) if width else 10**6
        lines = max(1, -(-len(text) // per_line))
        item = {
            "x": x, "y": y, "text": text, "anchor": kw.get("anchor", "center"),
            "h": lines * self.LINE_H.get(size, 17), "lines": lines,
            # Recorded because one surface draws the same slot in two colours to say
            # whose words they are — the answer in REPLY, the question in MUTED — and a
            # fake that dropped the colour could not see them swap.
            "fill": kw.get("fill"),
            "tags": _tags(kw.get("tags")),
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
        b.pill.band_h = lambda: ui.PANEL_MAX_H
        b.canvas = MeasuringCanvas()
        b._text, b._sent, b._partial, b._note = text, "", "", note
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

    def test_the_bubble_grows_to_make_room_rather_than_clipping(self):
        """The other way to stop an overlap is to cut the text off, and for an error
        message that is the same defect wearing a different hat.

        Briefly untrue, while the panel was a fixed height — the room came out of the
        body instead. The band is snug around its content again (`_settled_h`), so this
        is back to what it always asserted, and the foot still does not move: the shell
        grows upward.
        """
        short = self._bubble("ok")
        short._render()
        long_ = self._bubble(self.ERROR)
        long_._render()
        # `assertGreaterEqual`, not `assertGreater`, and the reason is `_settled_h`: the
        # band steps by a whole body line, so a note that grew by 14 px can land in the
        # same 17 px bucket as the one before it. That is the point of the snap — the
        # window stops changing size for every small thing — and the property this test
        # is really about is the next two lines, which is that the note is drawn whole.
        # The sibling test above asserts it clears the chips.
        self.assertGreaterEqual(long_._h, short._h)
        drawn = next(i for i in long_.canvas.items if "WinError 2" in i["text"])
        self.assertEqual(drawn["text"], self.ERROR, "the note must not be truncated")

    def test_a_one_line_note_still_sits_where_it_always_did(self):
        b = self._bubble("saved")
        b._render()
        _top, bottom = b.canvas.band("saved")
        self.assertLessEqual(bottom, b._h - 14 - 26)


class TestThePrimaryChipHasAFixedAddress(unittest.TestCase):
    """Send does not move when the chip set beside it does.

    The reported shape: "Send moves when the chip set does". `can_rescue` flips and "Was
    a command" appears, so Send slides; the clip fix shrank the gaps and Send slid
    342 → 326. The most irreversible control in the app was the one with no reliable
    position, under a hand already travelling toward where it had been a moment earlier.

    The fix puts the slack in the gap *before* the primary rather than spreading it, so
    the secondaries absorb every change and the right edge is arithmetic:
    `BUBBLE_W - PAD`.
    """

    def _bubble(self, **session):
        import flow.ui as ui

        b = ui.Bubble.__new__(ui.Bubble)
        b.pill = mock.Mock()
        fields = dict(mode="dictate", can_rescue=False, editing=False,
                      auto_ask_in=None, can_take_reply=False)
        fields.update(session)
        b.pill.session = mock.Mock(**fields)
        b.pill.accent = "#000000"
        b.pill.work = WORK
        b.pill.band_h = lambda: ui.PANEL_MAX_H
        b.canvas = MeasuringCanvas()
        b._text = "Meeting on Tuesday afternoon."
        b._sent = b._partial = b._note = ""
        b._editor = None
        b._act = None
        b._h = 120
        b.reposition = lambda *a, **kw: None
        return b

    def _right_edge(self, b, label):
        import flow.ui as ui

        it = next(i for i in b.canvas.items if i["text"] == label)
        return it["x"] + ui.chip_w(label, label) / 2

    def test_send_lands_on_the_same_pixel_whatever_is_beside_it(self):
        import flow.ui as ui

        edges = set()
        for rescue in (False, True):
            b = self._bubble(can_rescue=rescue)
            b._render()
            edges.add(self._right_edge(b, "Send"))
        self.assertEqual(len(edges), 1, f"Send moved: {edges}")
        self.assertAlmostEqual(edges.pop(), ui.BUBBLE_W - ui.PAD, delta=1)

    def test_a_waiting_row_does_not_reflow_it_either(self):
        # Dimming greys the fill; a row that also reflowed would undo the whole point.
        import flow.ui as ui

        from flow.session import Activity

        b = self._bubble()
        b._render()
        settled = self._right_edge(b, "Send")
        b._act = Activity("refining", True)
        b._dot = 0  # the marching-dot phase, normally advanced by the frame pump
        b._chips_drawn = None
        b._render()
        self.assertAlmostEqual(self._right_edge(b, "Send"), settled, delta=1)

    def test_the_secondaries_still_start_at_the_left_pad(self):
        # Pinned right is not centred or spread: the row still reads left to right.
        import flow.ui as ui

        b = self._bubble()
        b._render()
        it = next(i for i in b.canvas.items if i["text"] == "Refine")
        self.assertAlmostEqual(it["x"] - ui.chip_w("Refine", "Refine") / 2,
                               ui.PAD, delta=1)


class TestTheWayBackSitsBesideTheFact(unittest.TestCase):
    """An edit note carries an Undo; every other kind of note does not.

    The design pass asked for the fact and the way back together (decisions.md
    2026-08-09). The fact arrived as a sentence — `changed “thursday” to “Tuesday”` in
    place of `local: replace('thursday' -> 'Tuesday')` — and this is the other half.

    Which notes get one is the part worth pinning. Notes are how this window says a
    dozen unrelated things: an error, a workshop path, the exits list, "nothing sent
    yet". An Undo beside any of those is a button that would either do nothing or undo
    something the sentence above it is not about, so the *event kind* decides, not the
    presence of text.
    """

    def _bubble(self):
        import flow.ui as ui

        b = ui.Bubble.__new__(ui.Bubble)
        b.pill = mock.Mock()
        b.pill.session = mock.Mock(
            mode="dictate", can_rescue=False, editing=False, auto_ask_in=None,
            can_take_reply=False,
        )
        b.pill.accent = "#000000"
        b.pill.work = WORK
        b.pill.band_h = lambda: ui.PANEL_MAX_H
        b.canvas = MeasuringCanvas()
        b._text = "Meeting on Tuesday afternoon."
        b._sent = b._partial = b._note = ""
        b._note_undo = False
        b._editor = None
        b._act = None
        b._h = 120
        b._visible = True
        b.reposition = lambda *a, **kw: None
        b._render = ui.Bubble._render.__get__(b)
        return b

    def _labels(self, b):
        return [i["text"] for i in b.canvas.items]

    def test_an_edit_note_offers_a_way_back(self):
        import flow.ui as ui

        b = self._bubble()
        ui.Bubble.note(b, "changed “thursday” to “Tuesday”", undoable=True)
        self.assertIn(ui.UNDO_LABEL, self._labels(b))

    def test_an_error_does_not(self):
        import flow.ui as ui

        b = self._bubble()
        ui.Bubble.note(b, "could not start capture: the device is in exclusive use")
        self.assertNotIn(ui.UNDO_LABEL, self._labels(b))

    def test_pressing_it_goes_through_the_session(self):
        # Through `Session.undo_edit`, not `draft.undo()` — the button and the spoken
        # word are one behaviour, and a second implementation is the one that rots.
        import flow.ui as ui

        b = self._bubble()
        ui.Bubble.note(b, "removed “the standup line”", undoable=True)
        tag = ui.chip_tag(ui.UNDO_LABEL)
        pressed = [cb for t, seq, cb in b.canvas.bindings
                   if t == tag and seq == "<Button-1>"]
        self.assertEqual(len(pressed), 1, b.canvas.bindings)
        pressed[0](None)
        b.pill.session.undo_edit.assert_called_once_with()

    def test_the_note_gives_up_the_width_rather_than_wrapping_under_it(self):
        import flow.ui as ui

        long_note = "changed “" + "thursday " * 12 + "” to “Tuesday”"
        wide = self._bubble()
        ui.Bubble.note(wide, long_note)
        narrow = self._bubble()
        ui.Bubble.note(narrow, long_note, undoable=True)
        self.assertGreaterEqual(narrow._h, wide._h)


class TestALongPartialDoesNotLandOnTheNote(unittest.TestCase):
    """The same defect as the class above, on the element beside it.

    The note was measured on 2026-08-02 and the partial was not. It reserved a flat 34 px
    and advanced the cursor 28 — one line — while being drawn wrapped to the full body
    column, so a partial past three lines was height the window had never been sized for.
    Reported live on 2026-08-09 against a one-line draft: the note was printed straight
    through the partial's last two lines and the fifth ran into the chips.

    The one-line draft is load-bearing in the fixture, not incidental. The note is
    anchored to the panel's foot, so a *long* draft makes the window tall enough to
    absorb the overrun and the bug disappears — which is why the state that reproduces it
    is a short draft under a long partial, and why `scripts/shots.py` captures exactly
    that pair.
    """

    #: Five lines at this width. Four is enough to reach the note; five also reaches the
    #: chips, so one fixture covers both edges.
    PARTIAL = ("part key towel control sipped space voice the ask button puts the drop "
               "to the agency ally and the reply goes on so pause up the four second "
               "the question no auto ask found open code not just yet verified see "
               "nest you voice natural yes and the workshop is not set so ask runs "
               "without a project mode dictate send pastes into the focused window")

    def _bubble(self, partial: str, note: str = "local: replace('x' -> 'y')"):
        import flow.ui as ui

        b = ui.Bubble.__new__(ui.Bubble)
        b.pill = mock.Mock()
        b.pill.session = mock.Mock(
            mode="dictate", can_rescue=False, editing=False, auto_ask_in=None,
            can_take_reply=False,
        )
        b.pill.accent = "#000000"
        b.pill.work = WORK
        b.pill.band_h = lambda: ui.PANEL_MAX_H
        b.canvas = MeasuringCanvas()
        b._text = "seconds, send the question. No auto-ask to press it yourself."
        b._sent, b._partial, b._note = "", partial, note
        b._editor = None
        b._act = None
        b._h = 120
        b.reposition = lambda *a, **kw: None
        return b

    def test_the_partial_clears_the_note(self):
        b = self._bubble(self.PARTIAL)
        b._render()
        _p_top, p_bottom = b.canvas.band("part key towel")
        n_top, _n_bottom = b.canvas.band("local: replace")
        self.assertLessEqual(
            p_bottom, n_top,
            f"the partial runs to y={p_bottom} and the note starts at y={n_top}",
        )

    def test_the_partial_clears_the_chip_row(self):
        b = self._bubble(self.PARTIAL, note="")
        b._render()
        _top, bottom = b.canvas.band("part key towel")
        chips_top = b._h - 14 - 26  # `_lay_out`: y2 = _h - PAD, y1 = y2 - 26
        self.assertLessEqual(
            bottom, chips_top,
            f"the partial runs to y={bottom} and the chips start at y={chips_top}",
        )

    def test_the_bubble_grows_rather_than_clipping(self):
        # Grows in whole-line steps rather than continuously (`_settled_h`), and upward,
        # so a partial arriving while you speak moves the top edge and leaves every
        # control where it was.
        one = self._bubble("part key towel control")
        one._render()
        many = self._bubble(self.PARTIAL)
        many._render()
        self.assertGreater(many._h, one._h)

    def test_a_partial_past_the_cap_keeps_its_tail(self):
        # Bounded like the draft is, and windowed the same way round: this is the
        # sentence still being spoken, so the words that just arrived are the ones worth
        # the room. A head-first window would freeze the display at the utterance's
        # opening and never show what is being said now.
        import flow.ui as ui

        b = self._bubble(self.PARTIAL * 6)
        b._render()
        # The probes are `create_text` calls too, so the last item carrying partial text
        # is the one that reached the screen — the same rule `test_bubble.drawn_body` uses.
        shown = [i["text"] for i in b.canvas.items
                 if i["text"] and i["text"] in b._partial][-1]
        self.assertTrue(b._partial.endswith(shown), "the tail must be what survives")
        self.assertLess(len(shown), len(b._partial))
        top, bottom = b.canvas.band(shown)
        self.assertLessEqual(bottom - top, ui.PARTIAL_MAX_H)


class FakeBox:
    """A `tk.Text` that answers the two questions the viewport asks it, and no others."""

    def __init__(self, first=0.0, last=1.0, lines=60, height=200) -> None:
        self._view = (first, last)
        self._lines = lines
        self._height = height
        self.scrolled: list = []
        self.moved: list = []
        #: Every range `count` was asked about, so a test can assert which. Asking
        #: for the whole document is the defect, not an implementation detail.
        self.counted: list[tuple] = []

    def yview(self):
        return self._view

    def yview_scroll(self, n, what):
        self.scrolled.append((n, what))

    def yview_moveto(self, fraction):
        self.moved.append(fraction)

    def winfo_height(self):
        return self._height

    def count(self, start, end, what):
        self.counted.append((start, end, what))
        if (start, end) == ("1.0", "end-1c"):
            return (self._lines,)  # the whole document: what Tk lays out quadratically
        first, last = self._view
        shown = max(0.0, min(1.0, last - first))
        return (max(1, round(self._lines * shown)),)

    def update_idletasks(self):
        ...


class TestTheEditorSaysWhatItIsHolding(unittest.TestCase):
    """Item 67. Twenty visible lines of a draft that may be ten times that, silently.

    The hint used to be suppressed while editing, on the reasoning that "the box holds
    the whole draft and scrolls itself, so a line about what is above the fold would be
    about nothing". That was right about the words and wrong about the person: nothing
    on screen said there was more, and there was no bar to see it in.

    The number comes off the widget, but off its *viewport* — scaled up by how much of
    the draft that is, exactly the bargain the draft's own `… N earlier lines` makes.
    Counting the whole document was tried and is what froze Flow for a minute on a
    30 000-character draft; see `_hidden_lines` for the curve.
    """

    def bubble(self, first=0.0, last=0.3, lines=60, height=200):
        import flow.ui as ui

        b = ui.Bubble.__new__(ui.Bubble)
        b.pill = mock.Mock()
        b.pill.accent = "#000000"
        b.pill.work = WORK
        b.pill.band_h = lambda: ui.PANEL_MAX_H
        b.pill.session = mock.Mock(mode="dictate", editing=True, can_rescue=False,
                                   can_take_reply=False, auto_ask_in=None)
        b.canvas = MeasuringCanvas()
        b._text, b._sent, b._partial, b._note = "a draft", "", "", ""
        b._act, b._h, b._bar_y = None, 200, 0
        b._editor = FakeBox(first, last, lines, height)
        b.reposition = lambda *a, **kw: None
        b.after = lambda *a, **kw: None
        return b

    def test_it_counts_what_is_outside_the_box(self):
        # 30% of 60 display lines on screen, so 42 are not.
        self.assertEqual(self.bubble(0.0, 0.3, 60)._hidden_lines(), 42)

    def test_a_draft_that_fits_has_nothing_outside_it(self):
        self.assertEqual(self.bubble(0.0, 1.0, 3)._hidden_lines(), 0)

    def test_a_widget_that_cannot_answer_yet_says_nothing_rather_than_guessing(self):
        b = self.bubble()
        b._editor = object()
        self.assertEqual(b._hidden_lines(), 0)

    def test_it_never_asks_the_widget_to_lay_out_the_whole_draft(self):
        # The hang, reported from a real session with a transcript in the draft.
        # `count -displaylines` over the whole document is not linear: 8.5 ms at
        # 1 000 characters, 1.1 s at 8 000, 54.8 s at 32 000 — on the UI thread,
        # inside `_render`, and again on every keystroke via `<KeyRelease>`.
        # Windows offered to end the process. The viewport is a dozen lines
        # whatever the draft is, so that is what may be counted.
        b = self.bubble(0.0, 0.3, 60)
        b._hidden_lines()
        b._render()
        self.assertNotIn(("1.0", "end-1c", "displaylines"), b._editor.counted)
        self.assertTrue(b._editor.counted, "it should still be measuring something")
        for start, end, _what in b._editor.counted:
            self.assertTrue(start.startswith("@") and end.startswith("@"),
                            f"counted {start}..{end}, which is not a viewport")

    def test_a_box_with_no_height_yet_claims_nothing(self):
        # Pre-layout, the whole draft is inside a one-pixel viewport and scaling up
        # from it invents a number. This is the render `_edit` fires before Tk has
        # sized the widget; the one it schedules 20 ms later is the real answer.
        self.assertEqual(self.bubble(0.0, 0.3, 60, height=1)._hidden_lines(), 0)

    def test_the_hint_is_drawn_while_editing(self):
        b = self.bubble(0.0, 0.3, 60)
        b._render()
        said = [i["text"] for i in b.canvas.items if "more lines in here" in i["text"]]
        self.assertEqual(len(said), 1, [i["text"] for i in b.canvas.items])
        self.assertIn("42", said[0])
        self.assertIn("drag the bar", said[0])

    def test_and_not_when_the_whole_draft_is_visible(self):
        b = self.bubble(0.0, 1.0, 3)
        b._render()
        self.assertEqual([i for i in b.canvas.items
                          if "more lines in here" in i["text"]], [])

    def test_the_bar_is_drawn_only_when_there_is_something_to_reach(self):
        # Same rule as the help sheet's thumb and the draft's elision line: furniture on
        # a window with nothing off screen is the second thing somebody reads.
        full = self.bubble(0.0, 1.0, 3)
        full._render()
        self.assertEqual([i for i in full.canvas.items if "editbar" in i["tags"]], [])
        part = self.bubble(0.0, 0.3, 60)
        part._render()
        self.assertTrue([i for i in part.canvas.items if "editbar" in i["tags"]])

    def test_the_wheel_scrolls_the_box(self):
        # Bound explicitly rather than left to Tk's class binding, which needs the focus.
        b = self.bubble()
        b._wheel_edit(mock.Mock(delta=-120))
        self.assertEqual(b._editor.scrolled, [(3, "units")])

    def test_the_drag_scrolls_it_too_and_leaves_selection_alone(self):
        # The bar is on the canvas, not inside the box: a drag inside a text box
        # *selects*, and trading an editing gesture for a reading one is not an upgrade.
        b = self.bubble(0.2, 0.5, 60)
        b._bar_grab(mock.Mock(y=10))
        b._bar_drag(mock.Mock(y=40), top=0, height=300)
        self.assertEqual(len(b._editor.moved), 1)
        self.assertGreater(b._editor.moved[0], 0.2)

    def test_the_hint_keeps_its_row_whether_or_not_it_says_anything(self):
        # It sits *above* the box and can only be measured once the box is laid out, so
        # a layout that depended on the measurement would be deciding the box's position
        # from the box's position. Measured first, it read `… 2484 more lines` for a
        # 60-line draft and drew a bar on a draft that fitted.
        full, part = self.bubble(0.0, 1.0, 3), self.bubble(0.0, 0.3, 60)
        full._render()
        part._render()
        self.assertEqual(full._h, part._h)


class TestStartingFromTheClipboard(unittest.TestCase):
    """`Session.paste_draft`: the undo snapshot is the whole reason it goes through
    `Draft.set` rather than assigning `text`."""

    def test_it_becomes_the_draft(self):
        s = session()
        self.assertEqual(s.paste_draft("  a paragraph from somewhere else  "), "")
        self.assertEqual(s.draft.text, "a paragraph from somewhere else")

    def test_the_previous_draft_is_one_undo_back(self):
        # The history exists; this is the one path that would have been tempted to skip
        # it, because "there was nothing there anyway" is true right up until it is not.
        s = session()
        s.draft.set("what was already there")
        s.paste_draft("something pasted over it")
        self.assertTrue(s.draft.undo())
        self.assertEqual(s.draft.text, "what was already there")

    def test_it_works_on_an_empty_draft(self):
        # The state it exists for: nothing said yet, no bubble on screen.
        s = session()
        self.assertEqual(s.draft.text, "")
        self.assertEqual(s.paste_draft("a paragraph"), "")
        self.assertEqual(s.draft.text, "a paragraph")

    def test_an_empty_clipboard_is_refused_with_a_reason_rather_than_a_note(self):
        # Returned, not emitted: the caller is the only thing that knows whether there
        # is a window on screen to put a note on.
        s = session()
        self.assertIn("clipboard", s.paste_draft("   "))
        self.assertEqual([e for e in s.events() if e.kind == "note"], [])

    def test_it_is_refused_while_the_editor_is_open(self):
        # The draft is two things at once until the box closes — the same reason a
        # spoken result is held back there.
        s = session()
        s.draft.set("being edited")
        s.begin_edit()
        self.assertIn("edit", s.paste_draft("something else").lower())
        self.assertEqual(s.draft.text, "being edited")

    def test_the_revision_moves_so_a_rewrite_in_flight_is_discarded(self):
        # Invariant 11 comes free with `Draft.set`, which is why this does not assign.
        s = session()
        s.draft.set("widen the column")
        was = s.draft.revision
        s.paste_draft("something entirely different")
        self.assertGreater(s.draft.revision, was)

    def test_it_joins_recent(self):
        s = session()
        s.paste_draft("a paragraph from somewhere else")
        self.assertEqual(s.recent[0], ("said", "a paragraph from somewhere else"))


class TestClickingTheDraftOpensEdit(unittest.TestCase):
    """Item 72. `help.exits_note` has promised this since item 38 and nothing
    was bound.

    That note is the one line shown at the moment the microphone dies with a draft still
    held — every spoken rescue needs a decode, a decode needs the models, the models need
    the mic — and it names three exits. One of them, "click the draft to edit", did
    nothing at all.
    """

    def bubble(self, text="a draft", sent=""):
        import flow.ui as ui

        b = ui.Bubble.__new__(ui.Bubble)
        b.pill = mock.Mock()
        b.pill.accent = "#000000"
        b.pill.work = WORK
        b.pill.band_h = lambda: ui.PANEL_MAX_H
        b.pill.session = mock.Mock(mode="dictate", editing=False, can_rescue=False,
                                   can_take_reply=False, auto_ask_in=None)
        b.canvas = MeasuringCanvas()
        b._text, b._sent, b._partial, b._note = text, sent, "", ""
        b._editor, b._act, b._h, b._bar_y = None, None, 120, 0
        b._sent_at = time.perf_counter()
        b.reposition = lambda *a, **kw: None
        b.after = lambda *a, **kw: None
        return b

    def tagged(self, b):
        return [i for i in b.canvas.items if "draft" in i["tags"]]

    def test_the_body_text_carries_the_binding(self):
        b = self.bubble()
        b._render()
        self.assertEqual(len(self.tagged(b)), 1)
        self.assertEqual(self.tagged(b)[0]["text"], "a draft")

    def test_the_note_that_promises_it_still_does(self):
        # The promise and the binding, checked together: either alone can rot.
        from flow.help import exits_note

        self.assertIn("click the draft to edit", exits_note(None))

    def test_the_sent_card_is_not_a_hit_region(self):
        # Those words have already gone, and `Bring it back` is the action there.
        b = self.bubble(text="", sent="already gone")
        b._render()
        self.assertEqual(self.tagged(b), [])

    def test_an_empty_draft_offers_nothing_to_click(self):
        b = self.bubble(text="")
        b._render()
        self.assertEqual(self.tagged(b), [])

    def test_it_goes_through_the_same_edit_the_chip_does(self):
        # Not a second way in. `_edit` is where the foreground dance, the refusal and
        # the verification live, and a click that bypassed them would be an editor
        # that silently collects nothing.
        import flow.ui as ui

        b = self.bubble()
        with mock.patch.object(ui.Bubble, "_edit") as edit:
            b._render()
            bound = [c for c in b.canvas.bindings if c[0] == "draft"]
            self.assertTrue(bound, "nothing was bound to the draft")
            bound[-1][2](None)
        edit.assert_called_once()


class TestOnlyAMishearingIsExtractedFromTheDiff(unittest.TestCase):
    """`typed_pairs` — the evidence bar between "the decoder got this wrong" and "I
    changed my mind".

    A spoken correction is labelled: the user named the operation, the target and the
    replacement out loud. A typed edit is a diff, and a diff will happily report a pair
    for any two words `difflib` happened to align. So the refusals below are the feature,
    and each one is a way of asking the same question — is this the decoder's mistake, or
    the author's second thought.
    """

    def pairs(self, before, after):
        return typed_pairs(before, after)

    def test_a_one_word_fix_yields_its_pair(self):
        self.assertEqual(
            self.pairs("deploy the roleback plan", "deploy the rollback plan"),
            [("roleback", "rollback")],
        )

    def test_a_two_token_span_is_kept_when_the_counts_match(self):
        # One term misheard as two words is the shape "kubectl" arrives in, and both
        # sides having the same count is what makes the alignment a fact rather than a
        # guess about which half was wrong.
        self.assertEqual(
            self.pairs("run the cube cuttle command now please",
                       "run the kube ctl command now please"),
            [("cube cuttle", "kube ctl")],
        )

    def test_an_unequal_span_is_left_alone(self):
        # "some ear" -> "Sameer" is a real mishearing and it still teaches nothing here.
        # Two tokens against one means difflib chose the boundary, and a pair built on a
        # chosen boundary is a guess wearing evidence's clothes. The spoken route still
        # learns this one, which is the point of keeping both.
        self.assertEqual(
            self.pairs("tell some ear about it now please",
                       "tell Sameer about it now please"),
            [],
        )

    def test_a_case_only_change_teaches_nothing(self):
        # Deliberate, and the one place the typed path is stricter than the spoken one.
        # `learn_pair` keeps "priya" -> "Priya" because "capitalize priya" *names* the
        # word; typed, the identical diff is produced by a capital that a newly typed
        # full stop forced, and nothing distinguishes them. See `typed_pairs`.
        self.assertEqual(self.pairs("hi priya is here now ok",
                                    "hi Priya is here now ok"), [])
        self.assertEqual(self.pairs("the RELEASE NOTES are done now",
                                    "the release notes are done now"), [])

    def test_a_punctuation_only_change_teaches_nothing(self):
        self.assertEqual(self.pairs("deploy the plan now please ok",
                                    "deploy the plan, now please ok"), [])

    def test_pure_insertions_and_deletions_teach_nothing(self):
        # Words added were never a correction of anything, and words taken away were not
        # corrected *to* anything.
        self.assertEqual(self.pairs("deploy the plan", "deploy the rollback plan"), [])
        self.assertEqual(self.pairs("deploy the rollback plan", "deploy the plan"), [])

    def test_numbers_are_not_vocabulary(self):
        self.assertEqual(self.pairs("the release is in 2024 for sure",
                                    "the release is in 2025 for sure"), [])

    def test_addresses_are_not_vocabulary(self):
        # A URL, a path and an email are things nobody dictates and hopes. Each would
        # otherwise pass every other test here, being long and phonetically near itself.
        for before, after in (
            ("see example.com for the full details",
             "see exampel.com for the full details"),
            ("open flow/sesion.py and read it now",
             "open flow/session.py and read it now"),
            ("mail semir@corp.com about the plan now",
             "mail samir@corp.com about the plan now"),
        ):
            with self.subTest(before=before):
                self.assertEqual(self.pairs(before, after), [])

    def test_short_tokens_teach_nothing(self):
        # "ot" -> "to" is a typo being fixed, not a word being learned, and two-letter
        # tokens sit within any phonetic bar worth having of each other.
        self.assertEqual(self.pairs("give it ot me now please ok",
                                    "give it to me now please ok"), [])

    def test_a_swap_that_sounds_like_nothing_teaches_nothing(self):
        # The single most important refusal: an edit is not evidence about the decoder
        # unless the two words could plausibly have been confused by ear.
        self.assertEqual(self.pairs("the cat sat on the mat today",
                                    "the meeting sat on the mat today"), [])

    def test_a_rewrite_teaches_nothing_even_when_it_contains_a_real_pair(self):
        # "roleback" -> "rollback" is in here and would be kept on its own. Past the
        # threshold the whole edit is dropped rather than mined, because in a rewrite the
        # surviving alignment is an artefact of difflib rather than a fact about speech.
        self.assertEqual(
            self.pairs("we should ship the roleback plan on friday morning",
                       "lets postpone the rollback until every reviewer signs it off"),
            [],
        )

    def test_a_small_fix_in_a_long_draft_still_counts(self):
        # The other side of the same threshold: the budget must not make ordinary
        # repairs unreachable, so two independent one-word fixes in a long sentence are
        # both kept.
        self.assertEqual(
            self.pairs(
                "semir and priya reviewed the roleback plan on friday last week ok",
                "Samir and priya reviewed the rollback plan on friday last week ok"),
            [("semir", "Samir"), ("roleback", "rollback")],
        )

    def test_composing_into_an_empty_draft_is_not_a_repair(self):
        self.assertEqual(self.pairs("", "a brand new sentence here"), [])
        self.assertEqual(self.pairs("deploy the rollback plan", ""), [])


class TestTypingAFixTeachesTheSameWaySayingItDoes(unittest.TestCase):
    """The seam, and the whole reason it exists.

    Flow's recorded worst defect is the register gap: a correction phrased as a
    description rather than a command does not route, the first Indian-L1 volunteer went
    0/10, and the guide's own answer to that is "use the Edit box". Until now that box
    taught nothing, so the profile learned fastest for the speakers who needed it least
    and not at all for the ones the feature exists for.
    """

    def session_with_profile(self):
        s = session(profile=tmp_profile())
        s.draft.set("deploy the roleback plan")
        return s, s.profile

    def typed(self, s, text):
        s.begin_edit()
        s.commit_edit(text)

    def test_committing_a_change_feeds_the_candidates(self):
        s, p = self.session_with_profile()
        self.typed(s, "deploy the rollback plan")
        self.assertEqual(dict(p.pairs), {"roleback -> rollback": 1})

    def test_cancelling_feeds_nothing(self):
        # The typed text is discarded on Esc, so there is nothing to have learned from —
        # and a repair the user took back is not a repair.
        s, p = self.session_with_profile()
        s.begin_edit()
        s.cancel_edit()
        self.assertFalse(p.pairs)

    def test_an_unchanged_commit_feeds_nothing(self):
        s, p = self.session_with_profile()
        self.typed(s, "deploy the roleback plan")
        self.assertFalse(p.pairs)

    def test_two_typed_sightings_promote_exactly_like_two_spoken_ones(self):
        s, p = self.session_with_profile()
        self.typed(s, "deploy the rollback plan")
        self.assertEqual(p.learned_terms(), [], "one sighting is not a pattern")
        s.draft.set("the roleback is staged")
        self.typed(s, "the rollback is staged")
        self.assertEqual(p.learned_terms(), ["rollback"])

    def test_a_spoken_sighting_and_a_typed_one_pool_into_a_promotion(self):
        """Deliberate: the two routes share one counter, so a mixed pair reaches two.

        This is the case that decides whether the feature helps the person it is for. A
        speaker the router half-understands fixes a word by voice sometimes and by hand
        the rest of the time, and separate counters would mean neither tally ever
        reaches `PROMOTE_AFTER` — the one user whose corrections are split between the
        routes would be the one who learns nothing. Two sightings of the same word going
        wrong in front of the same person is the pattern being counted, and how they
        reported it is not part of it.
        """
        s, p = self.session_with_profile()
        s.draft.set("tell semir about the plan")
        s._route("change semir to Samir")
        self.assertEqual(p.learned_terms(), [], "one sighting is not a pattern")
        s.draft.set("tell semir about the plan")
        self.typed(s, "tell Samir about the plan")
        self.assertEqual(p.learned_terms(), ["Samir"])

    def test_the_cap_on_pairs_holds_against_typing(self):
        # R8: a profile is a summary, not a log. The editor is a much faster way to
        # produce pairs than speech is, so the bound has to hold on this route too.
        s, p = self.session_with_profile()
        for n in range(MAX_PAIRS + 20):
            s.draft.set(f"the servic{n} is down")
            self.typed(s, f"the service{n} is down")
        self.assertLessEqual(len(p.pairs), MAX_PAIRS)

    def test_a_dismissed_pair_is_never_learned_again_by_typing(self):
        """"Never offer" is an answer, and typing the same fix must not re-ask it.

        Honoured on this route and not on the spoken one, and the line is how strong the
        evidence is. Dismissing replies to a *guess* the menu made from a word-level
        diff; a typed edit is another guess of exactly that kind, so the answer covers
        it. A spoken "change X to Y" is not a guess — the user named both halves — and
        discarding an instruction over an inference declined last week would be Flow
        overruling the sentence it was just given.
        """
        s, p = self.session_with_profile()
        p.dismiss_pair("roleback", "rollback")
        self.typed(s, "deploy the rollback plan")
        s.draft.set("the roleback is staged")
        self.typed(s, "the rollback is staged")
        self.assertFalse(p.pairs, "a dismissed pair came back through the editor")
        self.assertEqual(p.offered_pairs(), [])

    def test_nothing_is_applied_to_the_draft_that_was_just_typed(self):
        # Learning biases the next decode and never rewrites text. The user has already
        # fixed this draft by hand; a correction correcting itself would be Flow arguing
        # with the person who just typed.
        s, p = self.session_with_profile()
        for _ in range(3):
            s.draft.set("deploy the roleback plan")
            self.typed(s, "deploy the rollback plan")
        s.draft.set("deploy the roleback plan again")
        s.begin_edit()
        self.assertEqual(s.commit_edit("deploy the roleback plan again"), None)
        self.assertEqual(s.draft.text, "deploy the roleback plan again")

    def test_it_learns_from_what_the_box_opened_on_not_from_the_live_draft(self):
        """An utterance landing behind the editor must not become a rewrite.

        The user typed against the text on screen. Diffing against the draft as it stands
        at commit would read their untouched sentences as deletions and the arrived words
        as new writing — which trips the rewrite threshold and throws away the very fix
        they opened the box to make.
        """
        s, p = self.session_with_profile()
        s.begin_edit()
        # Something lands behind the box while they type.
        s.draft.set("deploy the roleback plan and then tell everybody it is done")
        s.commit_edit("deploy the rollback plan")
        self.assertEqual(dict(p.pairs), {"roleback -> rollback": 1})

    def test_learning_is_skipped_when_there_is_no_profile(self):
        s = session()
        s.draft.set("deploy the roleback plan")
        self.typed(s, "deploy the rollback plan")
        self.assertEqual(s.draft.text, "deploy the rollback plan")

    def test_the_trace_counts_the_pairs_without_carrying_them(self):
        """How many, never which. The 2026-08-01 decision shipped inferred pairs with
        their own accuracy recorded as unmeasured, and a count is what makes "how often
        does a hand repair look like a mishearing" answerable — while staying an integer,
        which cannot be read back into a word. `n` is already on `diag.FIELDS`; nothing
        new was named to carry this."""
        diag = RecordingDiag()
        s = session(profile=tmp_profile(), diag=diag)
        s.draft.set("deploy the roleback plan")
        self.typed(s, "deploy the rollback plan")
        commits = [r for r in diag.records if r.get("route") == "commit"]
        self.assertEqual([r["n"] for r in commits], [1])
        self.assertNotIn("roleback", str(diag.records))
        self.assertTrue(FIELDS.issuperset(commits[0]), "a field is not on the allow-list")

    def test_an_edit_that_teaches_nothing_says_so_in_the_trace(self):
        diag = RecordingDiag()
        s = session(profile=tmp_profile(), diag=diag)
        s.draft.set("the cat sat on the mat today")
        self.typed(s, "the meeting sat on the mat today")
        commits = [r for r in diag.records if r.get("route") == "commit"]
        self.assertEqual([r["n"] for r in commits], [0])


class TestTheTypedRouteReachesTheSameOfferMenu(unittest.TestCase):
    """P2: a typed pair is not a second kind of pair.

    It lands in the same `Profile.pairs` counter, so it is promoted by the same rule,
    bounded by the same cap and offered by the same `offered_pairs` the right-click menu
    reads. There is deliberately no new surface and no new announcement: crossing the
    threshold has been silent since decisions.md 2026-08-01 ("Inferred pairs: never
    silent - offered for one-tap declaration instead"), where "never silent" scopes to
    the *substitution* — a hotword biases toward a spelling and rewrites nothing, so it
    was never the half that needed telling. Matching that precedent is the requirement;
    announcing typed pairs alone would say the two routes are different things.
    """

    def test_a_typed_pair_is_offered_in_the_menu_like_a_spoken_one(self):
        s = session(profile=tmp_profile())
        for draft, fixed in (("tell semir today", "tell Samir today"),
                             ("semir is here now", "Samir is here now")):
            s.draft.set(draft)
            s.begin_edit()
            s.commit_edit(fixed)
        self.assertEqual(s.profile.offered_pairs(), [("semir", "Samir")])

    def test_a_pair_already_in_the_lexicon_stops_being_offered(self):
        s = session(profile=tmp_profile())
        for draft, fixed in (("tell semir today", "tell Samir today"),
                             ("semir is here now", "Samir is here now")):
            s.draft.set(draft)
            s.begin_edit()
            s.commit_edit(fixed)
        self.assertEqual(
            s.profile.offered_pairs(declared=[("semir", "Samir")]), [])

    def test_the_term_reaches_the_decode_bias(self):
        # The end of the whole chain: what a learned pair is actually *for*.
        s = session(profile=tmp_profile())
        for draft, fixed in (("tell semir today", "tell Samir today"),
                             ("semir is here now", "Samir is here now")):
            s.draft.set(draft)
            s.begin_edit()
            s.commit_edit(fixed)
        lx = Lexicon(NUL_PATH, learned=s.profile.learned_terms)
        self.assertIn("Samir", lx.terms())


class TestTypingAFixTeachesInLiteToo(unittest.TestCase):
    """Lite has the editor, so Lite has the learning.

    The fence says a feature reaches Lite only if it survives without hands, and this one
    never needed them: the seam is `commit_edit`, the same call on both builds. What Lite
    changes is the foreground dance around it, which is the part a Mac has no
    `SetForegroundWindow` for — so this drives the box the way Lite really does, with the
    verification skipped, rather than proving something about a code path Lite never runs.
    """

    def _typed(self, session_, typed_text):
        import flow.ui as ui

        b = ui.Bubble.__new__(ui.Bubble)
        b.pill = mock.Mock(session=session_, accent="#000000")
        b.canvas = mock.Mock()
        b.lite = True
        b._text, b._sent, b._partial, b._note = session_.draft.text, "", "", ""
        b._editor, b._previous_focus, b._h, b._visible = None, 0, 120, True
        b._sent_at = time.perf_counter()
        b.after = lambda *a, **kw: None
        box = mock.MagicMock()
        box.get.return_value = typed_text
        fake_tk = mock.MagicMock()
        fake_tk.Text.return_value = box
        with mock.patch.object(ui, "tk", fake_tk), \
                mock.patch.object(ui.Bubble, "_render"):
            b._edit()
            b._commit_edit()
        return b

    def test_the_editor_opens_without_asking_windows_for_anything(self):
        import flow.ui as ui

        s = session(profile=tmp_profile())
        s.draft.set("deploy the roleback plan")
        with mock.patch.object(ui, "foreground_hwnd") as fg, \
                mock.patch.object(ui, "toplevel_hwnd") as top:
            self._typed(s, "deploy the rollback plan")
        fg.assert_not_called()
        top.assert_not_called()

    def test_a_fix_typed_in_lite_teaches_the_same_pair(self):
        s = session(profile=tmp_profile())
        s.draft.set("deploy the roleback plan")
        self._typed(s, "deploy the rollback plan")
        self.assertEqual(s.draft.text, "deploy the rollback plan")
        self.assertEqual(dict(s.profile.pairs), {"roleback -> rollback": 1})
        self.assertFalse(s.editing, "the editor was left open")

    def test_escape_in_lite_teaches_nothing(self):
        import flow.ui as ui

        s = session(profile=tmp_profile())
        s.draft.set("deploy the roleback plan")
        b = ui.Bubble.__new__(ui.Bubble)
        b.pill = mock.Mock(session=s, accent="#000000")
        b.canvas, b.lite = mock.Mock(), True
        b._text, b._sent, b._partial, b._note = s.draft.text, "", "", ""
        b._editor, b._previous_focus, b._h, b._visible = None, 0, 120, True
        b._sent_at = time.perf_counter()
        b.after = lambda *a, **kw: None
        box = mock.MagicMock()
        box.get.return_value = "deploy the rollback plan"
        fake_tk = mock.MagicMock()
        fake_tk.Text.return_value = box
        with mock.patch.object(ui, "tk", fake_tk), \
                mock.patch.object(ui.Bubble, "_render"):
            b._edit()
            b._cancel_edit()
        self.assertEqual(s.draft.text, "deploy the roleback plan")
        self.assertFalse(s.profile.pairs)
