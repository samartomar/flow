"""Changing the design without relaunching Flow.

The switch used to be launch-time by construction (decisions.md 2026-09-03): a design's
whole window tree is built in its constructor, so the menu could only write
`profile.design` and promise it for next time. `switch_design` and `detach` are the
rebuild-the-world pattern that was missing, put at the one seam that already existed —
`__main__` speaks to a surface through a constructor, `mainloop()` and a teardown.

Two properties, and they are the whole feature:

  **`detach` is `quit_app` minus the session.** The window goes; the session, the
  hotkeys and the fonts stay, because the surface built next needs all three. The one
  piece of session state a surface owns — an open microphone — is handed back, because
  the new surface starts disarmed and a device left open under a window that is not
  pumping it is the failure of 2026-09-04 in full.

  **A second `tk.Tk` in one process really works.** Nothing here cached a font, a
  variable or an interpreter at module scope, and the last test in this file is the
  proof rather than the argument: a real `Pill`, detached, and a real `CompactPill`
  built on the same session, both ways round.
"""

import gc
import io
import contextlib
import sys
import tkinter as tk
import types
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import flow.ui as ui  # noqa: E402
import flow.ui_compact as uc  # noqa: E402
from test_ui_compact import pill as compact_pill  # noqa: E402


def shipped_pill(**kw):
    """A shipped pill with just enough of one to be torn down.

    `__new__`, like every UI fixture in this suite: `quit_app` and `detach` read half a
    dozen attributes and touch no drawing at all, so a whole window would be a Tk
    dependency bought for nothing. Modelled on `test_tray.py`'s, minus the mocked
    `quit_app` — that method is the subject here.
    """
    p = ui.Pill.__new__(ui.Pill)
    p.session = mock.Mock(mode=ui.DICTATE)
    p.hotkeys = mock.Mock()
    p.armed = False
    p._alive = True
    p._tray = None
    p._flash = 0
    p.destroy = mock.Mock()
    #: The real one asks Tk what is still pending; there is no interpreter here.
    p._cancel_pending = mock.Mock()
    for name, value in kw.items():
        setattr(p, name, value)
    return p


def detachable_compact(**kw):
    """`test_ui_compact.pill` with the three calls a teardown makes stubbed."""
    p = compact_pill()
    p.armed = False
    p.hotkeys = mock.Mock()
    p._alive = True
    p._tray = None
    p._flash = 0
    p.destroy = mock.Mock()
    p._cancel_pending = mock.Mock()
    for name, value in kw.items():
        setattr(p, name, value)
    return p


#: Both surfaces, under the name each test reads them by, so every property below is
#: asserted twice rather than once for the design somebody happened to be thinking of.
SURFACES = (("current", shipped_pill), ("compact", detachable_compact))


class TestSwitchDesignHandsOverTheName(unittest.TestCase):
    def test_it_stores_the_choice_sets_switch_to_and_detaches(self):
        for name, build in SURFACES:
            other = "compact" if name == "current" else "current"
            with self.subTest(design=name):
                p = build()
                p.session.profile = mock.Mock(design=name)
                p.detach = mock.Mock()
                p.switch_design(other)
                self.assertEqual(p.session.profile.design, other)
                p.session.profile.save.assert_called_once_with()
                self.assertEqual(p.switch_to, other)
                p.detach.assert_called_once_with()

    def test_the_design_already_running_is_refused(self):
        # The row marked `(current)`. Rebuilding the surface already on screen would
        # blank it and redraw the same thing, and `__main__`'s loop refuses the same
        # name a second time — so this is belt and braces on purpose.
        for name, build in SURFACES:
            with self.subTest(design=name):
                p = build()
                p.session.profile = mock.Mock(design=name)
                p.detach = mock.Mock()
                p.switch_design(name)
                self.assertIsNone(p.switch_to)
                p.detach.assert_not_called()
                p.session.profile.save.assert_not_called()

    def test_a_name_nobody_can_build_is_refused_too(self):
        for name, build in SURFACES:
            with self.subTest(design=name):
                p = build()
                p.session.profile = mock.Mock(design=name)
                p.detach = mock.Mock()
                p.switch_design("kandinsky")
                self.assertIsNone(p.switch_to)
                p.detach.assert_not_called()

    def test_a_save_that_failed_is_visible_and_the_switch_happens_anyway(self):
        # The two halves are separable and both matter: the design the user just chose
        # is on screen a frame later whatever the disk did, and the reason the *next*
        # launch will not remember it is said now rather than discovered then.
        #
        # Printed, and only printed. Both menus used to answer on their own surface —
        # a note in the bubble, a red flash on the pill — and this is the one row whose
        # window is gone before another frame is drawn.
        for name, build in SURFACES:
            other = "compact" if name == "current" else "current"
            with self.subTest(design=name):
                p = build()
                p.session.profile = mock.Mock(design=name)
                p.session.profile.save.return_value = False
                p.detach = mock.Mock()
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    p.switch_design(other)
                self.assertIn("could not save", out.getvalue())
                self.assertEqual(p._flash, 0)
                self.assertEqual(p.switch_to, other)
                p.detach.assert_called_once_with()

    def test_no_profile_switches_and_says_it_will_not_be_remembered(self):
        # `--no-profile`. The choice has nowhere to live past this process — but this
        # process is exactly what the switch is about now, so it happens, and the note
        # is about the next launch rather than about the press.
        for name, build in SURFACES:
            other = "compact" if name == "current" else "current"
            with self.subTest(design=name):
                p = build()
                p.session.profile = None
                p.detach = mock.Mock()
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    p.switch_design(other)
                self.assertIn("--no-profile", out.getvalue())
                self.assertIn("not remembered", out.getvalue())
                self.assertEqual(p.switch_to, other)
                p.detach.assert_called_once_with()

    def test_the_class_knows_which_design_it_is(self):
        # What the `(current)` marker and the refusal above both read. A class fact,
        # not a profile field: `--no-profile` stores nothing at all.
        self.assertEqual(ui.Pill.DESIGN, "current")
        self.assertEqual(uc.CompactPill.DESIGN, "compact")

    def test_switch_to_is_a_class_default(self):
        # `__main__` reads it off whatever came back from the constructor, and every
        # `__new__`-built fixture in this suite has to find a real value rather than
        # recurse through `tk.Misc.__getattr__`.
        self.assertIsNone(ui.Pill.switch_to)
        self.assertIsNone(uc.CompactPill.switch_to)


class TestDetachIsQuitAppMinusTheSession(unittest.TestCase):
    def test_it_stops_the_icon_and_destroys_the_window(self):
        for name, build in SURFACES:
            with self.subTest(design=name):
                p = build(_tray=mock.Mock())
                p.detach()
                p._tray.stop.assert_called_once_with()
                p.destroy.assert_called_once_with()
                self.assertFalse(p._alive)

    def test_it_leaves_the_session_and_the_hotkeys_running(self):
        # The three lines it does not run. Stopping the hotkeys would be a switch that
        # silently cost somebody push-to-talk; closing the session would throw away the
        # draft the switch exists to carry across.
        for name, build in SURFACES:
            with self.subTest(design=name):
                p = build(_tray=mock.Mock())
                with mock.patch.object(ui, "_unload_fonts") as unload:
                    p.detach()
                p.session.close.assert_not_called()
                p.hotkeys.stop.assert_not_called()
                unload.assert_not_called()

    def test_an_armed_surface_hands_the_microphone_back(self):
        # The new surface is built disarmed, and a device left open under a window
        # that is not pumping it is 2026-09-04's chord bug exactly: the mic was open,
        # the ring was green, and nothing ever read a sample.
        for name, build in SURFACES:
            with self.subTest(design=name):
                p = build(armed=True)
                p.detach()
                p.session.pause.assert_called_once_with()

    def test_a_disarmed_one_is_left_alone(self):
        # `pause()` on a session that was never started is not free — it clears the
        # gate, the utterance and the mic queue — and nothing here asked for that.
        for name, build in SURFACES:
            with self.subTest(design=name):
                p = build(armed=False)
                p.detach()
                p.session.pause.assert_not_called()

    def test_the_pending_frames_go_before_the_window_does(self):
        # A second interpreter is about to pump this thread's notifier, and a timer
        # whose Tcl command was deleted with this window surfaces there as "invalid
        # command name" against a Flow with nothing wrong with it.
        for name, build in SURFACES:
            with self.subTest(design=name):
                p = build()
                p.detach()
                p._cancel_pending.assert_called_once_with()

    def test_it_is_idempotent(self):
        for name, build in SURFACES:
            with self.subTest(design=name):
                p = build(_tray=mock.Mock())
                p.detach()
                p.detach()
                p.destroy.assert_called_once_with()

    def test_the_compact_surface_closes_its_painters(self):
        # Its own line rather than a shared one: a `GdiCanvas` holds a DIB and a GDI+
        # graphics for a window that is about to stop existing.
        p = detachable_compact()
        p.paint = mock.Mock()
        p._box_paint = mock.Mock()
        p.detach()
        p.paint.close.assert_called_once_with()
        p._box_paint.close.assert_called_once_with()


class TestQuitAppStillQuits(unittest.TestCase):
    """The half that did not change, pinned beside the half that did — the whole risk
    of splitting a teardown in two is that the smaller one quietly becomes both."""

    def test_it_closes_the_session_and_stops_the_hotkeys(self):
        for name, build in SURFACES:
            with self.subTest(design=name):
                p = build(_tray=mock.Mock(), armed=True)
                with mock.patch.object(ui, "_unload_fonts"):
                    p.quit_app()
                p._tray.stop.assert_called_once_with()
                p.hotkeys.stop.assert_called_once_with()
                p.session.close.assert_called_once_with()
                p.destroy.assert_called_once_with()
                self.assertFalse(p._alive)

    def test_the_shipped_one_unloads_the_fonts(self):
        # `_load_fonts` is idempotent now, so this is the only call that ever undoes
        # it — and a switch must not reach it.
        p = shipped_pill()
        with mock.patch.object(ui, "_unload_fonts") as unload:
            p.quit_app()
        unload.assert_called_once_with()

    def test_quitting_does_not_ask_for_a_new_surface(self):
        for name, build in SURFACES:
            with self.subTest(design=name):
                p = build()
                with mock.patch.object(ui, "_unload_fonts"):
                    p.quit_app()
                self.assertIsNone(p.switch_to)


def tk_available() -> bool:
    try:
        root = tk.Tk()
        root.destroy()
        del root
        gc.collect()
        return True
    except Exception:
        return False


HAVE_TK = tk_available()


def fake_session():
    """`scripts/shots.py`'s hand-written `Session` stand-in.

    Hand-written rather than a Mock, which is why it is worth reaching for: a Mock
    answers every attribute, so a window that started reading something new would
    still build and this test would go on passing about nothing. Pillow is stubbed
    because `shots.py` imports `ImageGrab` for its captures and nothing here captures
    anything — it is a `--with` on that script's own command line, not a dependency.
    """
    if "PIL" not in sys.modules:
        pil = types.ModuleType("PIL")
        pil.ImageGrab = types.ModuleType("PIL.ImageGrab")
        sys.modules["PIL"] = pil
    sys.path.insert(0, str(REPO / "scripts"))
    import shots

    return shots.FakeSession()


@unittest.skipUnless(sys.platform == "win32", "Windows-only: ctypes.WinDLL")
@unittest.skipUnless(HAVE_TK, "no display available")
class TestASecondTkInOneProcess(unittest.TestCase):
    """The proof the switch rests on: `tk.Tk()` may be created again after a
    `destroy()`, and neither module holds anything that assumed one interpreter.

    Both directions, because the two constructors are not symmetric — the shipped one
    registers the bundled fonts and asks for a 1 ms timer, the compact one builds a
    painter and a tray icon — and a switch is only real if it survives being made
    twice in a row.
    """

    def build(self, cls, session):
        # `lite=True`: the layered window and the notification icon are the platform's,
        # not this test's, and `painter_for` hands back the plain canvas under it.
        # `tray.available` off for the same reason — `CompactPill.__init__` raises its
        # icon at launch, and a test has no business putting one in somebody's tray.
        with mock.patch.object(uc.tray, "available", return_value=False), \
                mock.patch.object(ui.tray, "available", return_value=False):
            win = cls(session, lite=True)
        win.update_idletasks()
        return win

    def round_trip(self, first, second):
        session = fake_session()
        session.draft.text = "the words that have to survive the switch"
        one = self.build(first, session)
        self.addCleanup(gc.collect)
        one.detach()
        self.assertFalse(one._alive)
        two = self.build(second, session)
        self.addCleanup(two.detach)
        # A live interpreter with a window in it, built after another one was torn
        # down — which is the thing that was said to be impossible.
        self.assertTrue(two.winfo_exists())
        # And the words are still there, which is what the switch is *for*.
        self.assertIs(two.session, session)
        self.assertEqual(two.session.draft.text,
                         "the words that have to survive the switch")

    def test_shipped_then_compact(self):
        self.round_trip(ui.Pill, uc.CompactPill)

    def test_compact_then_shipped(self):
        self.round_trip(uc.CompactPill, ui.Pill)

    def test_the_fonts_are_registered_once_however_many_pills_are_built(self):
        # `AddFontResourceExW` counts its callers, and only `quit_app` ever removes
        # one — so a `_load_fonts` that ran per surface would leave a registration
        # behind on every path but process exit.
        ui._load_fonts()
        before = list(ui._loaded_fonts)
        ui._load_fonts()
        self.assertEqual(ui._loaded_fonts, before)


if __name__ == "__main__":
    unittest.main()
