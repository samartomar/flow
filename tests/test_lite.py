"""Flow Lite: the definition first, and then the body that has to obey it.

One module for both halves on purpose. The fence — *features land in full Flow first, and
reach Lite only if they survive without hands* — is a rule about how features travel, so
the place it can go wrong is the gap between what product.md promises and what the pill
does. Kept together, a definition that drifts from the build fails beside it.

This half reads `docs/product.md`, the idiom `test_workshop.py`'s `TestP9SaysWhatItNowIs`
already established: the product definition is a file the suite is allowed to hold to its
word, because a promise nothing checks is the one that goes stale first.
"""

import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow import help as helpmod  # noqa: E402
from flow.audio import BLOCK  # noqa: E402
from flow.session import Session  # noqa: E402

PRODUCT = Path(__file__).resolve().parent.parent / "docs" / "product.md"

DRAFT = "Ship the release notes on Tuesday."

#: The four things Lite is *not*, from the decision entry. Stated as exclusions rather
#: than as "not yet": each one is what buys the only property Lite has that full Flow does
#: not — nothing to grant beyond the microphone.
EXCLUSIONS = ("injection", "global hotkeys", "auto-paste", "target-window awareness")


def product() -> str:
    return PRODUCT.read_text(encoding="utf-8")


def section(body: str, title: str) -> str:
    """One `##` section's text, up to the next one at the same level.

    Anchored on the heading rather than on a phrase, so a test about the Lite section
    cannot be satisfied by a sentence somewhere else in the file that happens to use the
    same words.
    """
    m = re.search(rf"^##+ .*{re.escape(title)}.*$", body, re.M | re.I)
    if m is None:
        return ""
    rest = body[m.end():]
    nxt = re.search(r"^## ", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


class TestProductMdKnowsThereAreTwoBodies(unittest.TestCase):
    def setUp(self):
        self.body = product()

    def test_environments_says_which_half_is_portable_and_which_is_not(self):
        # The whole distribution argument in one paragraph: the brain and ear are Python
        # with cross-platform wheels, the hands are Win32. Without it, "Lite" reads as a
        # cut-down edition rather than as the part that was always portable.
        env = section(self.body, "Environments")
        self.assertTrue(env, "product.md has no Environments section")
        low = env.lower()
        self.assertIn("portable", low)
        self.assertIn("win32", low)
        self.assertIn("macos", low)

    def test_the_lite_section_names_every_one_of_the_four_exclusions(self):
        # Four, by name. A Lite section that lists three is a definition somebody will
        # build the fourth against, which is exactly what a fence is for.
        lite = section(self.body, "Flow Lite").lower()
        self.assertTrue(lite, "product.md has no Flow Lite section")
        for item in EXCLUSIONS:
            self.assertIn(item, lite, f"the Lite definition does not exclude {item!r}")

    def test_lite_says_what_it_is_and_not_only_what_it_is_not(self):
        lite = section(self.body, "Flow Lite").lower()
        for part in ("brain", "ear", "clipboard"):
            self.assertIn(part, lite)
        # The one property the exclusions buy, and the reason they are worth paying.
        self.assertIn("microphone", lite)

    def test_the_fence_reads_in_the_load_bearing_direction(self):
        # The direction is the whole sentence. "Features land in Lite first and reach full
        # Flow if they survive" uses every word this could grep for and means the
        # opposite, so the assertion is on the order the two names appear in.
        #
        # Unwrapped first: the file is hard-wrapped at 88 characters, so a sentence-level
        # assertion that respects the line breaks is asserting the margin, not the prose.
        flat = " ".join(self.body.split())
        fence = next(
            (s for s in re.split(r"(?<=[.])\s+", flat) if "survive without hands" in s),
            "",
        )
        self.assertTrue(fence, "the fence sentence is not in product.md")
        self.assertLess(
            fence.index("full Flow"), fence.lower().index("lite"),
            f"the fence points the wrong way: {fence!r}",
        )
        self.assertIn("first", fence)

    def test_the_clipboard_hop_is_named_as_the_measurement(self):
        # The port decision waits on a number, and a definition that does not say which
        # number leaves it waiting on an impression.
        self.assertIn("clipboard hop", self.body.lower())

    def test_lite_names_the_two_requirements_it_cannot_meet(self):
        # Named, not implied. P7 is Flow's promise that a paste arrives unexecuted, and
        # Lite is not doing the pasting; P9's loop ends in the terminal, and Lite ends on
        # the clipboard. A body that quietly claims all nine would be the definition
        # lying on the build's behalf.
        lite = section(self.body, "Flow Lite")
        self.assertIn("P7", lite)
        self.assertIn("P9", lite)

    def test_the_p_table_is_not_renumbered_and_gains_no_row(self):
        # Lite is a body that meets a subset of the requirements, not a tenth requirement.
        # A "P10: also works without hands" would make the fence a thing to satisfy rather
        # than a rule about how the other nine travel.
        rows = re.findall(r"^\| (P\d+) \|", self.body, re.M)
        self.assertEqual(rows, [f"P{n}" for n in range(1, 10)])

    def test_the_non_goals_are_untouched(self):
        # Lite subtracts a body, not a scope. If a non-goal moved while this section was
        # being written, it moved for the wrong reason.
        goals = section(self.body, "Non-goals")
        for lead in ("Multilingual output", "Cloud ASR or any API key",
                     "Writing code by voice", "General voice control",
                     "Being an AI itself"):
            self.assertIn(lead, goals)


# ---------------------------------------------------------------------------
# and the body that obeys it
# ---------------------------------------------------------------------------


class FakeMic:
    def __init__(self) -> None:
        self.level_db = -60.0

    def start(self) -> None: ...

    def stop(self) -> None: ...

    @property
    def active(self) -> bool:
        return True

    def restart(self) -> None: ...

    def drain(self) -> list[np.ndarray]:
        return []


class FakeAsr:
    loading = False

    def load(self, final=None) -> None: ...

    def text(self, audio, *, final=False, hotwords="") -> str:
        return ""


def session(**kw) -> Session:
    return Session(asr=FakeAsr(), mic=FakeMic(), **kw)


class Pill:
    """A pill whose clipboard is a list — `test_triggers.Pressed`, one body over.

    Built at the same layer and for the same reason: what a spoken trigger *means* in
    Lite is decided in `Pill._send`, which the router reaches through the same `send`
    event the full body uses. A check that stopped at the session would be asserting an
    event was emitted, not that anything was copied.

    `lite` is set here rather than left to a default, and that is not tidiness:
    `tk.Misc.__getattr__` forwards an unknown attribute to `self.tk`, so on an instance
    whose `__init__` has not run a missing one recurses instead of defaulting (item 32
    found this the hard way). The attribute has to exist.
    """

    def __init__(self, s: Session, lite: bool = True, injector: bool = True) -> None:
        import flow.ui as ui

        self.copied: list[str] = []
        self.pasted: list[tuple[str, bool]] = []
        self.flushes = 0
        self.pill = ui.Pill.__new__(ui.Pill)
        self.pill.session = s
        self.pill.lite = lite
        # `injector` is what `__main__` decides by importing a paste module or not, and
        # it is no longer the same question as `lite`. A Mac is Lite — no global hotkeys,
        # no window handles — and still pastes, through System Events. `injector=False`
        # is the case with nothing to paste with: `--lite` on Windows, `--no-paste`, or a
        # platform Flow has no injector for.
        self.pill.on_send = self._on_send if injector else None
        self.pill.paste_target = 0x22
        self.pill.bubble = mock.Mock()
        self.pill._flash = 0
        self.pill.clipboard_clear = self.copied.clear
        self.pill.clipboard_append = self.copied.append
        self.pill.update_idletasks = self._flush
        self.session = s

    def _flush(self) -> None:
        self.flushes += 1

    def _on_send(self, text: str, target=None, submit: bool = False) -> str:
        self.pasted.append((text, submit))
        return ""

    def say(self, utterance: str) -> None:
        self.session._route(utterance)
        while events := self.session.events():
            for ev in events:
                if ev.kind == "send":
                    self.pill._send(submit=ev.text == "enter")
                elif ev.kind == "note":
                    self.pill.bubble.note(ev.text)

    def notes(self) -> str:
        return " | ".join(str(c.args[0]) for c in self.pill.bubble.note.call_args_list)


class TestSendInLiteIsACopy(unittest.TestCase):
    """Lite with nothing to paste with — `--lite` on Windows, or `--no-paste`.

    Lite used to mean this by definition. It does not any more: a Mac is Lite in every
    other respect and pastes through System Events, so the copy is now the fallback for
    *no injector* rather than the behaviour of a mode. See `TestLiteWithAnInjector`.
    """

    def setUp(self):
        self.s = session()
        self.p = Pill(self.s, injector=False)
        self.s.draft.set(DRAFT)

    def test_the_draft_goes_to_the_clipboard_and_nowhere_else(self):
        # `on_send` is the paste closure, and in Lite `__main__` does not even build one.
        # Asserting it is untouched is asserting the injection path is unreachable rather
        # than merely unused.
        self.p.pill._send()
        self.assertEqual(self.p.copied, [DRAFT])
        self.assertEqual(self.p.pasted, [])

    def test_the_note_hands_the_paste_back_to_the_user(self):
        self.p.pill._send()
        self.assertIn("copied", self.p.notes())
        self.assertIn("paste where you need it", self.p.notes())

    def test_the_words_stay_on_screen_the_way_a_paste_leaves_them(self):
        # R5 is not weakened by the body change: a copy that goes wrong has to be as
        # recoverable as a paste that does, so the sent card is drawn either way.
        self.p.pill._send()
        self.p.pill.bubble.show_sent.assert_called_once_with(DRAFT)

    def test_a_clipboard_that_refuses_is_said_out_loud(self):
        import tkinter as tk

        def refuse(_text=None):
            raise tk.TclError("clipboard busy")

        self.p.pill.clipboard_append = refuse
        self.p.pill._send()
        args = self.p.pill.bubble.show_sent.call_args.args
        self.assertEqual(args[0], DRAFT, "the words are still recoverable")
        self.assertIn("clipboard busy", args[1])
        self.assertTrue(self.p.pill._flash, "a failed handoff has to be looked at")

    def test_the_flush_is_not_skipped(self):
        # Tk owns the selection while the interpreter lives; without a flush the copy can
        # be a promise to a clipboard nobody comes back to read.
        self.p.pill._send()
        self.assertEqual(self.p.flushes, 1)

    def test_full_mode_still_pastes_and_never_copies(self):
        p = Pill(session(), lite=False)
        p.session.draft.set(DRAFT)
        p.pill._send(submit=True)
        self.assertEqual(p.pasted, [(DRAFT, True)])
        self.assertEqual(p.copied, [])


class TestTheEnterVariantCollapses(unittest.TestCase):
    """The one question the fence asks of Lite, answered and pinned.

    A refusal was the alternative and it is the wrong answer on `edits.enter_word`'s own
    argument: a decode that drops a word from "enter boom" yields "boom", so a refusing
    enter-variant would make the *degraded* decode the working case and the fuller
    utterance the broken one. That is the inversion the word order exists to prevent, and
    it must not come back one layer up.
    """

    def setUp(self):
        self.s = session()
        self.p = Pill(self.s, injector=False)
        self.s.draft.set(DRAFT)

    def test_it_copies_rather_than_refusing(self):
        self.p.pill._send(submit=True)
        self.assertEqual(self.p.copied, [DRAFT])

    def test_and_says_what_did_not_happen(self):
        self.p.pill._send(submit=True)
        self.assertIn("Enter is yours to press", self.p.notes())

    def test_both_spoken_triggers_reach_it_through_the_router(self):
        # End to end from the utterance, because the collapse has to survive the route,
        # not just the method call. The grammar keeps both words in Lite: somebody who
        # learned "enter boom" in the full body will still say it.
        for said, expect in (("boom", "paste where you need it"),
                             ("enter boom", "Enter is yours to press")):
            with self.subTest(said=said):
                s = session()
                p = Pill(s, injector=False)
                s.draft.set(DRAFT)
                p.say(said)
                self.assertEqual(p.copied, [DRAFT])
                self.assertIn(expect, p.notes())


class TestLiteHasNoTarget(unittest.TestCase):
    def _pill(self, lite: bool):
        import flow.ui as ui

        pill = ui.Pill.__new__(ui.Pill)
        pill.lite = lite
        pill.paste_target = None
        # `_track_target` writes the app name onto the session for `_app_note` to read
        # later. A stand-in rather than a mock, because what the tests below check is the
        # *value* that lands there — and on a `Pill` built by `__new__`, a missing
        # attribute is not an AttributeError but a `tkinter` lookup that recurses until
        # the interpreter gives up, which is a confusing way to learn this line exists.
        pill.session = type("S", (), {"target_app": ""})()
        return pill

    def test_the_foreground_is_never_asked_about_in_lite(self):
        # No target-window awareness (product.md). Read off `lite` rather than off the
        # platform, which is what makes `--lite` on Windows the same code a Mac runs
        # instead of a rehearsal of it.
        import flow.ui as ui

        pill = self._pill(lite=True)
        with mock.patch.object(ui, "foreground_hwnd", return_value=0x99) as asked:
            pill._track_target()
        self.assertIsNone(pill.paste_target)
        asked.assert_not_called()

    @unittest.skipUnless(sys.platform == "win32",
                         "full mode resolves the foreground window through inject.py, "
                         "which binds user32 at import")
    def test_full_mode_still_tracks_it(self):
        import flow.ui as ui

        pill = self._pill(lite=False)
        with mock.patch.object(ui, "foreground_hwnd", return_value=0x99), \
                mock.patch.object(ui, "owned_by_flow", return_value=False):
            pill._track_target()
        self.assertEqual(pill.paste_target, 0x99)

    def test_the_app_behind_the_window_is_named_for_the_per_app_note(self):
        import flow.ui as ui

        pill = self._pill(lite=False)
        with mock.patch.object(ui, "foreground_hwnd", return_value=0x99),                 mock.patch.object(ui, "owned_by_flow", return_value=False),                 mock.patch.object(ui, "classify") as named:
            named.return_value = type("T", (), {"process": "code.exe"})()
            pill._track_target()
        self.assertEqual(pill.session.target_app, "code.exe")

    def test_it_is_resolved_on_the_edge_and_not_once_a_frame(self):
        # `classify` opens a process handle and this runs at 30 fps. Paying that every
        # frame is a cost paid forever to answer a question whose answer moves a few
        # times an hour — so it is asked when the window changes and remembered between.
        import flow.ui as ui

        pill = self._pill(lite=False)
        with mock.patch.object(ui, "foreground_hwnd", return_value=0x99),                 mock.patch.object(ui, "owned_by_flow", return_value=False),                 mock.patch.object(ui, "classify") as named:
            named.return_value = type("T", (), {"process": "code.exe"})()
            for _ in range(10):
                pill._track_target()
            self.assertEqual(named.call_count, 1)
            named.return_value = type("T", (), {"process": "slack.exe"})()
            with mock.patch.object(ui, "foreground_hwnd", return_value=0xAB):
                pill._track_target()
            self.assertEqual(named.call_count, 2)
        self.assertEqual(pill.session.target_app, "slack.exe")

    def test_lite_never_names_an_app_because_it_never_has_a_target(self):
        # No target-window awareness at all (product.md), which reads downstream as an
        # app with no note configured — the behaviour every launch had before per-app
        # notes existed, rather than a gap.
        import flow.ui as ui

        pill = self._pill(lite=True)
        with mock.patch.object(ui, "classify") as named:
            pill._track_target()
        named.assert_not_called()
        self.assertEqual(pill.session.target_app, "")


class TestTheWindowsOnlyTkAttributes(unittest.TestCase):
    """`-transparentcolor` and `-toolwindow` exist only on Windows.

    Asking for either off-Windows is a `TclError` before the pill is ever drawn, and the
    keyed colour is invisible only *because* something keys it out — without the
    attribute it is a magenta rectangle where the app should be.
    """

    class FakeWindow:
        def __init__(self) -> None:
            self.asked: list[str] = []

        def overrideredirect(self, _flag) -> None: ...

        def attributes(self, name, _value=None) -> None:
            self.asked.append(name)

    def test_lite_asks_for_neither_and_takes_an_opaque_background(self):
        import flow.ui as ui

        win = self.FakeWindow()
        bg = ui._shell_window(win, lite=True, alpha=0.94)
        self.assertEqual(bg, ui.SHELL)
        self.assertNotIn("-transparentcolor", win.asked)
        self.assertNotIn("-toolwindow", win.asked)
        self.assertIn("-topmost", win.asked)

    def test_full_mode_asks_for_both_and_keeps_the_keyed_colour(self):
        import flow.ui as ui

        win = self.FakeWindow()
        bg = ui._shell_window(win, lite=False, alpha=0.94)
        self.assertEqual(bg, ui.TRANSPARENT)
        self.assertIn("-transparentcolor", win.asked)
        self.assertIn("-toolwindow", win.asked)


class TestOpeningAThingWithoutStartfile(unittest.TestCase):
    """`os.startfile` does not exist off Windows, and it is the whole of two menu entries."""

    def test_windows_still_uses_the_shell_it_always_did(self):
        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch("os.startfile", create=True) as shell:
            helpmod.open_path("C:/somewhere")
        shell.assert_called_once_with("C:/somewhere")

    def test_darwin_and_linux_get_their_own_openers(self):
        for platform, opener in (("darwin", "open"), ("linux", "xdg-open")):
            with self.subTest(platform=platform):
                with mock.patch.object(sys, "platform", platform), \
                        mock.patch("subprocess.run") as run:
                    helpmod.open_path("/somewhere")
                self.assertEqual(run.call_args.args[0], [opener, "/somewhere"])

    def test_a_failure_still_arrives_as_the_oserror_the_menu_reports(self):
        # Both callers catch OSError and put the reason on the bubble. A
        # CalledProcessError escaping instead would take the pill's menu handler with it.
        with mock.patch.object(sys, "platform", "darwin"), \
                mock.patch("subprocess.run",
                           side_effect=subprocess.CalledProcessError(1, "open")):
            with self.assertRaises(OSError):
                helpmod.open_path("/somewhere")


class TestTheSheetDropsWhatLiteDoesNotHave(unittest.TestCase):
    """Absent, not disabled-looking. A greyed-out row is still a row about hands."""

    @staticmethod
    def flat(**kw) -> str:
        return " | ".join(f"{left} {right}" for _kind, left, right
                          in helpmod.rows(**kw))

    def test_lite_offers_the_plain_word_and_not_the_enter_variant(self):
        text = self.flat(lite=True, send_words=("tango", "enter tango"))
        self.assertIn("tango", text)
        self.assertNotIn("enter tango", text)

    def test_full_mode_still_offers_both(self):
        text = self.flat(send_words=("tango", "enter tango"))
        self.assertIn("enter tango", text)

    def test_lite_has_no_hotkey_section_because_it_registers_none(self):
        hotkeys = mock.Mock(chosen={"toggle": "ctrl+shift+space"}, failed=[])
        text = self.flat(lite=True, hotkeys=hotkeys)
        self.assertNotIn("ctrl+shift+space", text)
        self.assertIn("Click the pill", text)

    def test_and_it_does_not_tell_you_to_paste_into_a_window_it_cannot_see(self):
        text = self.flat(lite=True)
        self.assertNotIn("the window you were in", text)

    def test_every_lite_row_still_fits_the_column_budget(self):
        # The window draws one line per row and does not wrap, so a Lite-only row that
        # runs off the edge is a defect the suite has to catch rather than the screen.
        limits = {"pair": (helpmod.MAX_LEFT, helpmod.MAX_RIGHT),
                  "note": (helpmod.MAX_NOTE, 0),
                  "head": (helpmod.MAX_NOTE, helpmod.MAX_RIGHT), "gap": (0, 0)}
        for kind, left, right in helpmod.rows(lite=True):
            with self.subTest(row=(kind, left)):
                # A heading that carries a right column has to clear the same gutter a
                # pair does, and it is drawn bold, so it gets the tighter budget.
                cap = helpmod.MAX_HEAD if kind == "head" and right else limits[kind][0]
                self.assertLessEqual(len(left), cap or len(left))
                self.assertLessEqual(len(right), limits[kind][1] or len(right))


class TestTheModeNoteNamesTheRightBody(unittest.TestCase):
    def note_for(self, lite: bool) -> str:
        s = session(lite=lite)
        s.toggle_mode()  # into converse
        s.events()
        s.toggle_mode()  # and back
        return " | ".join(e.text for e in s.events() if e.kind == "note")

    def test_lite_says_it_copies(self):
        note = self.note_for(lite=True)
        self.assertIn("copies", note)
        self.assertNotIn("focused window", note)

    def test_full_mode_still_says_it_pastes(self):
        self.assertIn("focused window", self.note_for(lite=False))


if __name__ == "__main__":
    unittest.main()
