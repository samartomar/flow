"""Where the compact surface is on a desk with more than one screen, and how
big its pixels are.

Two families of defect, and both are arithmetic rather than drawing.

**The screen.** `self.full` and `self.work` were read once, in `__init__`, off
the monitor under the pointer — rectangles in *virtual-screen* coordinates,
where a display to the right of the primary starts at x=1920 and one above it
has a negative top. Everything that keeps this surface reachable then clamped
against `winfo_screenwidth()` instead, which on Windows is the primary
monitor's width and nothing else's. So opening the panel on a second monitor
threw the whole window back onto the first, a monitor above the primary was
clamped to a top belonging to somebody else's display, and a drag stopped dead
at the seam — "Drag it anywhere" (Main.dc.html) with a fence across it.

**The pixels.** `dev()` and `design()` exist because every length in
`ui_compact.py` is written in `design/compact/gen.py`'s units and none of the
things it is compared against are. Two hit tests were still comparing across
that boundary, and at the 300 % this machine runs at both of them mean the
gesture lands somewhere the pointer is not.

Headless, on `test_ui_compact`'s own fixtures: the rectangles are stated, not
measured, which is the contract `_shell_xy` exists for.
"""

import unittest
from pathlib import Path
from unittest import mock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import flow.ui as ui  # noqa: E402
import flow.ui_compact as uc  # noqa: E402
from flow.session import CONVERSE  # noqa: E402
from test_ui_compact import Canvas, panel_pill, pill, session  # noqa: E402

#: A two-monitor desk, the one the reports came from: a primary at the origin
#: and a second to the right of it, each with a 48 px taskbar. The right-hand
#: pair is the whole of the first defect — every coordinate in it is greater
#: than `winfo_screenwidth()` on the primary.
LEFT = ((0, 0, 1920, 1080), (0, 0, 1920, 1032))
RIGHT = ((1920, 0, 3840, 1080), (1920, 0, 3840, 1032))
#: And a monitor stood *above* the primary, which is the case that made the
#: `max(0, ...)` floor visibly wrong rather than merely unprincipled: its whole
#: coordinate space is negative.
ABOVE = ((0, -1080, 1920, 0), (0, -1080, 1920, 0))


def screen_pill(monitor=RIGHT, *, x=2820, y=900, k=1.0, **attrs):
    """A pill standing on `monitor` at `(x, y)`, with the real `_sync_shell`.

    `panel_pill`'s anchor is stated rather than read back, which is the real
    contract: `_shell_xy` is where the window was last *given*, and `winfo_*`
    lags a `geometry` call by a frame or two.
    """
    p = panel_pill(mode=CONVERSE, x=x, y=y, **attrs)
    p.full, p.work = monitor
    p.k = k
    return p


class TestThePanelStaysOnTheMonitorThePillIsOn(unittest.TestCase):
    """The reported defect: open the panel on the right-hand screen and the
    window jumps to the primary one.

    `_sync_shell` clamped x with `winfo_screenwidth()`, which answers for the
    primary display alone. A pill at x=2820 satisfies `x + 400 > 1920`
    trivially — every pixel of that monitor does — so the clamp fired on every
    open and parked the window at 1520, a screen away from its own capsule.
    """

    def test_the_band_opens_where_the_capsule_is_standing(self):
        p = screen_pill(RIGHT, x=2820, y=900)
        p._open_panel()
        p.geometry.assert_called_once_with("400x234+2820+700")
        # Said as the property rather than only as the number: the window is
        # inside the monitor it was on, which is what the number is for.
        self.assertGreaterEqual(p._shell_xy[0], RIGHT[1][0])
        self.assertLessEqual(p._shell_xy[0] + uc.PANEL_W, RIGHT[1][2])

    def test_the_band_grows_left_off_that_monitors_right_edge(self):
        # The same rule `test_the_band_grows_left_rather_than_off_the_right_edge`
        # pins on the primary — the mic moves before the panel clips — now
        # measured against the edge the pill is actually near.
        p = screen_pill(RIGHT, x=3700, y=900)
        p._open_panel()
        self.assertEqual(p._shell_xy[0], RIGHT[1][2] - uc.PANEL_W)

    def test_a_monitor_above_the_primary_clamps_to_its_own_top(self):
        # `y = max(0, ...)` is the primary's top edge wearing a constant. On a
        # display stood above it, zero is 1080 px below the bottom of the
        # screen the pill is on — so the clamp did not keep the band on
        # screen, it threw it off one.
        p = screen_pill(ABOVE, x=900, y=-1000)
        p._open_panel()
        self.assertEqual(p._shell_xy[1], ABOVE[1][1])

    def test_a_band_that_fits_keeps_its_negative_y(self):
        # And the clamp does not fire merely because the number is negative,
        # which is the other half of the same mistake.
        p = screen_pill(ABOVE, x=900, y=-80)
        p._open_panel()
        self.assertEqual(p._shell_xy[1], -280)


class TestTheNoticeStripStaysOffTheTaskbar(unittest.TestCase):
    """The strip is the one thing on this surface that grows *downward*, from
    a capsule already stood `PANEL_BOTTOM_OFFSET` above the taskbar — so it is
    the one thing that can leave the bottom of the work area, and nothing
    clamped it."""

    def notice(self, p):
        p._notice = uc.COPIED_FRAMES
        p._notice_w = uc.PILL_W
        p._sync_shell()

    def test_the_window_is_shifted_up_rather_than_run_under_the_taskbar(self):
        p = screen_pill(LEFT, x=900, y=1010)
        self.notice(p)
        h = uc.PILL_H + uc.NOTICE_H
        self.assertEqual(p._shell_xy[1] + h, LEFT[1][3])
        # The capsule moved, and the tracked anchor says so. Off-screen is a
        # bigger lie than a capsule that shifted 30 px to keep its sentence
        # readable — but an anchor that still claimed the old position would
        # grow the *next* band from a capsule that is not there.
        self.assertEqual(p._capsule_y, p._shell_xy[1])

    def test_a_strip_with_room_leaves_the_capsule_exactly_where_it_was(self):
        p = screen_pill(LEFT, x=900, y=400)
        self.notice(p)
        self.assertEqual(p._shell_xy, (900, 400))
        self.assertEqual(p._capsule_y, 400)


class TestTheDragCrossesTheSeam(unittest.TestCase):
    """"Drag it anywhere" (Main.dc.html) — including onto the other screen.

    `_move_window` clamped to `self.work`, one monitor's rectangle, so the
    pointer crossed the seam and the window stopped against the edge of the
    display it started on. The bound is every monitor there is
    (`_virtual_desktop`), refreshed by `_sync_monitor`; `work` catches up
    within four frames and is what the *placement* clamps use.
    """

    def dragged(self, to, desktop=None, work=LEFT[1]):
        p = pill()
        p.geometry = mock.Mock()
        p.work = work
        p.desktop = desktop
        p._shell_w, p._shell_h = uc.PILL_W, uc.PILL_H
        p._move_window(*to)
        return p._shell_xy

    def test_a_pill_dragged_onto_the_second_monitor_is_not_pulled_back(self):
        self.assertEqual(self.dragged((2500, 500), (0, 0, 3840, 1080)),
                         (2500, 500))

    def test_the_union_is_still_a_bound_and_not_an_open_field(self):
        # The tray is the escape hatch, not the drag's excuse: a pill thrown
        # past every monitor there is would need it (decided 2026-09-03).
        self.assertEqual(self.dragged((9000, 9000), (0, 0, 3840, 1080)),
                         (3840 - uc.PILL_W, 1080 - uc.PILL_H))

    def test_with_no_virtual_desktop_to_ask_it_clamps_to_the_one_screen(self):
        # A fixture, a Mac, a machine where `GetSystemMetrics` is not there:
        # `_sync_monitor` never answered, so the bound is the screen the pill
        # already knows about rather than nothing at all.
        self.assertEqual(self.dragged((2500, 500), None),
                         (1920 - uc.PILL_W, 500))


class TestTheMonitorIsReAsked(unittest.TestCase):
    """`Pill._sync_monitor` (flow/ui.py:4233) has re-asked every fourth frame
    since the placement work; this surface asked once in `__init__` and never
    again, which is what made every clamp above a clamp to a stale rectangle.

    Keyed on the *window* rather than the pointer, because this pill is
    dragged by hand and stays where it is put — and during a drag the pointer
    is already on the far monitor while the capsule is still on this one.
    """

    def pill(self, monitor=LEFT, **kw):
        p = screen_pill(monitor, **kw)
        # The real method back, the way `panel_pill` puts back `_sync_shell`:
        # `pill()` mocks it because a bare fixture has no window to ask
        # through.
        p._sync_monitor = uc.CompactPill._sync_monitor.__get__(p)
        p.winfo_screenheight = mock.Mock(return_value=1080)
        p._frame_no = 0
        return p

    def test_every_fourth_frame_and_not_the_three_between(self):
        p = self.pill(LEFT, x=100, y=400)
        with mock.patch.object(uc, "_monitor_at", return_value=RIGHT) as at, \
                mock.patch.object(uc, "_virtual_desktop",
                                  return_value=(0, 0, 3840, 1080)):
            p._sync_monitor()
            self.assertEqual((p.full, p.work), RIGHT)
            for _ in range(3):
                p._sync_monitor()
            self.assertEqual(at.call_count, 1)
            p._sync_monitor()
        self.assertEqual(at.call_count, 2)
        self.assertEqual(p.desktop, (0, 0, 3840, 1080))

    def test_it_asks_about_the_capsules_centre_in_device_pixels(self):
        # Not the window's corner: the window is 400 px wide with the band up
        # and the capsule is 120, so a corner near a seam answers for the
        # monitor next door. `k=3` because the point is a device length and
        # `_shell_w` is a design one.
        p = self.pill(LEFT, x=300, y=1200, k=3.0)
        with mock.patch.object(uc, "_monitor_at", return_value=LEFT) as at, \
                mock.patch.object(uc, "_virtual_desktop", return_value=LEFT[0]):
            p._sync_monitor()
        x, y, sw, sh, win = at.call_args.args
        self.assertEqual((x, y), (300 + uc.PILL_W * 3 // 2,
                                  1200 + uc.PILL_H * 3 // 2))
        self.assertEqual((sw, sh), (1920, 1080))
        self.assertIs(win, p)

    def test_a_frame_drives_it(self):
        p = self.pill(LEFT, x=100, y=400)
        with mock.patch.object(uc, "_monitor_at", return_value=RIGHT), \
                mock.patch.object(uc, "_virtual_desktop",
                                  return_value=(0, 0, 3840, 1080)):
            p._frame()
        self.assertEqual((p.full, p.work), RIGHT)

    def test_the_trays_quit_does_not_leave_it_asking_a_dead_window(self):
        # `_drain_tray` is one line above the call to this and its Quit
        # destroys the window, so a sync that asked Tk anyway would print
        # "application has been destroyed" at somebody who has just quit.
        p = self.pill(LEFT, x=100, y=400)
        p._alive = False
        p.winfo_screenwidth = mock.Mock(
            side_effect=AssertionError("asked a destroyed window"))
        p._sync_monitor()
        self.assertEqual(p._frame_no, 0)

    def test_no_win32_collapses_to_the_one_screen_rather_than_raising(self):
        # Off Windows there is no `MonitorFromPoint` and no `rcWork`, so the
        # two rectangles become the one Tk can measure — the same degradation
        # `__init__` already accepted through `_pointer_monitor`, and a frame
        # is not a place to handle a Win32 failure.
        p = self.pill(RIGHT, x=2820, y=900)
        with mock.patch.object(uc.ctypes, "windll", ui._NoHands(),
                               create=True), \
                mock.patch.object(ui, "_tk_work_area",
                                  return_value=(0, 0, 1920, 1032)):
            p._sync_monitor()
        self.assertEqual(p.full, p.work)
        self.assertEqual(p.work, (0, 0, 1920, 1032))
        # `GetSystemMetrics` answered 0, so the union is the screen Tk knows.
        self.assertEqual(p.desktop, (0, 0, 1920, 1080))


class Mouse:
    """The two read-only Win32 calls `_outside_click_now` makes, with the
    cursor put where a test wants it."""

    def __init__(self, x, y, down=True) -> None:
        self.x, self.y, self.down = x, y, down

    def GetAsyncKeyState(self, _vk) -> int:
        return 0x8000 if self.down else 0

    def GetCursorPos(self, ref) -> int:
        ref._obj.x, ref._obj.y = self.x, self.y
        return 1


class TestTheClickOutsidePollMeasuresInDevicePixels(unittest.TestCase):
    """`GetCursorPos` answers in device pixels and so does the tracked anchor,
    but `_shell_w`/`_shell_h` are the design sizes everything in this module
    is written in. The rect being tested was therefore the window divided by
    `k` — at 300 % a third of it — so a click in the right or lower part of an
    open panel read as a click *outside* and closed the panel under the
    pointer. This machine runs at 300 %."""

    def panel(self, k=3.0, x=300, y=1200):
        p = screen_pill(LEFT, x=x, y=y, k=k)
        p._outside_click_now = uc.CompactPill._outside_click_now.__get__(p)
        p._panel_open = True
        p._shell_w, p._shell_h = uc.PANEL_W, uc.PANEL_H + uc.PILL_H
        return p

    def clicked(self, p, x, y) -> bool:
        with mock.patch.object(uc, "_user32", Mouse(x, y)):
            return p._outside_click_now()

    def test_a_click_in_the_panels_right_half_is_not_outside_it(self):
        p = self.panel()
        # 300 + 3*400 = 1500 is the window's real right edge; 1400 is inside
        # it and 700 — the old, unscaled edge — is barely a third of the way
        # across the panel the user is looking at.
        self.assertFalse(self.clicked(p, 1400, 1300))

    def test_a_click_in_the_panels_lower_half_is_not_outside_it_either(self):
        p = self.panel()
        self.assertFalse(self.clicked(p, 900, 1800))

    def test_a_click_past_the_real_edge_still_closes_it(self):
        # The poll has to keep working, not merely stop firing: a rect that is
        # too big is the same defect facing the other way.
        p = self.panel()
        self.assertTrue(self.clicked(p, 1600, 1300))
        p = self.panel()
        self.assertTrue(self.clicked(p, 900, 1950))

    def test_the_anchor_is_the_tracked_one_and_not_winfo(self):
        # `winfo_rootx` lags a `geometry` call by a frame or two, and this
        # runs thirty times a second.
        p = self.panel()
        self.clicked(p, 1400, 1300)
        p.winfo_rootx.assert_not_called()
        p.winfo_rooty.assert_not_called()


class TestThePaletteRowUnderThePointer(unittest.TestCase):
    """`_on_box_click` divided a *device* y by *design* row heights. At 300 %
    that is the click's y taken at face value against rows a third of their
    real size — so every tap below the first chose a workspace three rows
    above the one under the pointer, or none at all. `_on_press` and
    `_panel_click` already convert; this was the hit test left behind."""

    ROWS = ["~/dev/products/flow", "~/work/riverflow"]

    def palette(self, k):
        p = panel_pill(mode=CONVERSE)
        p.k = k
        p._palette = uc._Palette(self.ROWS)
        p._box_kind = "palette"
        return p

    def click(self, p, design_y):
        """A tap `design_y` design pixels down the box, in the device pixels
        Tk actually reports."""
        p._on_box_click(mock.Mock(y=round(design_y * p.k)))

    def test_the_second_row_is_chosen_at_300_percent(self):
        p = self.palette(3.0)
        self.click(p, uc.PALETTE_FIELD_H + uc.PALETTE_ROW_H + 15)
        p.session.set_workspace.assert_called_once_with("~/work/riverflow")

    def test_the_pinned_row_is_chosen_at_300_percent(self):
        # The row that clears the workspace is the last one, so it is the row
        # an unconverted y overshoots first and hardest.
        p = self.palette(3.0)
        self.click(p, uc.PALETTE_FIELD_H + 2 * uc.PALETTE_ROW_H + 15)
        p.session.set_workspace.assert_called_once_with(None)

    def test_a_tap_in_the_query_field_chooses_nothing(self):
        p = self.palette(3.0)
        self.click(p, uc.PALETTE_FIELD_H - 5)
        p.session.set_workspace.assert_not_called()

    def test_the_same_taps_still_land_at_100_percent(self):
        p = self.palette(1.0)
        self.click(p, uc.PALETTE_FIELD_H + uc.PALETTE_ROW_H + 15)
        p.session.set_workspace.assert_called_once_with("~/work/riverflow")


class TestTheBoxIsKeptOnScreen(unittest.TestCase):
    """The 360 px box (Workspace.dc.html's `.box`) opened at the 120 px pill's
    own x, so a pill parked near the right edge put two thirds of the palette
    off the display — and its top was floored at 0, which is the primary
    monitor's edge rather than the one it is on."""

    def opened(self, p, kind="setup"):
        """`_open_box` with the window it builds replaced: a Toplevel needs a
        desktop, and everything under test here is the arithmetic around it."""
        box = mock.Mock()
        p.session.mic = mock.Mock(device_name="Yeti Nano")
        p.session._provider = lambda: "claude"
        p.session.pastes = True
        with mock.patch.object(uc.tk, "Toplevel", return_value=box), \
                mock.patch.object(uc.tk, "Canvas", return_value=mock.Mock()), \
                mock.patch.object(uc, "_shell_window", return_value="#0E1116"), \
                mock.patch.object(uc.paint, "painter_for",
                                  return_value=Canvas()):
            p._open_box(kind)
        return box

    def test_a_pill_at_the_right_edge_keeps_the_whole_box_on_screen(self):
        p = screen_pill(LEFT, x=1800, y=400)
        self.opened(p)
        self.assertEqual(p._box_x, LEFT[1][2] - uc.BOX_W)
        self.assertLessEqual(p._box_x + uc.BOX_W, p.work[2])

    def test_the_box_follows_the_pill_onto_the_second_monitor(self):
        p = screen_pill(RIGHT, x=2820, y=900)
        self.opened(p)
        self.assertEqual(p._box_x, 2820)
        self.assertGreaterEqual(p._box_x, RIGHT[1][0])

    def test_the_top_is_the_work_areas_and_not_zero(self):
        p = screen_pill(ABOVE, x=900, y=-1050)
        box = self.opened(p)
        top = p._box_foot - p._box_height()
        self.assertEqual(top, ABOVE[1][1])
        self.assertIn(f"+900+{ABOVE[1][1]}", box.geometry.call_args.args[0])

    def test_it_anchors_off_the_tracked_position_not_winfo(self):
        # The comment two lines below this read "tracked, not read back" while
        # the code above it called `winfo_rootx()`.
        p = screen_pill(LEFT, x=900, y=400)
        self.opened(p)
        p.winfo_rootx.assert_not_called()
        p.winfo_rooty.assert_not_called()
        self.assertEqual(p._box_x, 900)


class TestHidingRemembersWhereItReallyWas(unittest.TestCase):
    """The tray is the escape hatch (decided 2026-09-03), so where it puts the
    pill back matters: `_home` came from `winfo_*`, which lags a `geometry`
    call by a frame or two."""

    def tray_pill(self, **kw):
        p = screen_pill(LEFT, **kw)
        p.withdraw = mock.Mock()
        p.deiconify = mock.Mock()
        p.lift = mock.Mock()
        return p

    def hide(self, p):
        icon = mock.Mock()
        icon.start.return_value = True
        with mock.patch.object(uc.tray, "available", return_value=True), \
                mock.patch.object(uc.tray, "Tray", return_value=icon):
            return p.hide_to_tray()

    def test_home_is_the_tracked_anchor(self):
        p = self.tray_pill(x=2820, y=900)
        self.assertTrue(self.hide(p))
        self.assertEqual(p._home, (2820, 900))
        p.winfo_rootx.assert_not_called()
        p.winfo_rooty.assert_not_called()

    def test_coming_back_restores_the_anchor_with_the_window(self):
        # `_shell_xy` is what the next `_sync_shell` grows its band from and
        # what the click-outside poll hit-tests against. A window put back at
        # `_home` while those described somewhere else is a pill whose next
        # panel opens off its own capsule.
        p = self.tray_pill(x=2820, y=900)
        self.hide(p)
        p._shell_xy, p._capsule_y = (0, 0), 0
        p.show_from_tray()
        p.geometry.assert_called_with("+2820+900")
        self.assertEqual(p._shell_xy, (2820, 900))
        self.assertEqual(p._capsule_y, 900)

    def test_a_panel_that_was_up_keeps_its_capsule_offset(self):
        p = self.tray_pill(x=2820, y=900)
        p._open_panel()          # the capsule is now 200 px down the window
        self.hide(p)
        p.show_from_tray()
        self.assertEqual(p._capsule_y,
                         p._shell_xy[1] + uc.PANEL_H)


class TestTheMonitorHelperIsSharedRatherThanCopied(unittest.TestCase):
    """`_pointer_monitor` was the only way to ask which monitor a coordinate
    is on, and it only ever asked about the cursor. It is `_monitor_at` keyed
    on a point now, with `_pointer_monitor` reading the cursor and calling it
    — the shipped surface's answer is unchanged, which is the condition for
    the compact one borrowing it (BUILD_BRIEF: a shared helper moves, it does
    not get copied)."""

    def test_the_pointer_answer_is_the_monitor_at_the_cursor(self):
        with mock.patch.object(ui, "_monitor_at",
                               return_value=RIGHT) as at:
            self.assertEqual(ui._pointer_monitor(1280, 720), RIGHT)
        self.assertEqual(at.call_args.args[2:], (1280, 720, None))

    def test_both_still_degrade_rather_than_raise(self):
        with mock.patch.object(ui.ctypes, "windll", ui._NoHands(),
                               create=True):
            for name, rect in (("pointer", ui._pointer_monitor(1280, 720)),
                               ("point", ui._monitor_at(2500, 500, 1280, 720))):
                with self.subTest(name=name):
                    full, work = rect
                    self.assertEqual(full, work)
                    self.assertGreater(full[2], full[0])


if __name__ == "__main__":
    unittest.main()
