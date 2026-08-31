"""The conversation card — converse mode's own surface.

Three outside users met converse mode on the draft bubble and every consequence of the
sharing arrived at once (decisions.md 2026-08-03). The sharpest was auto-ask: a pause
sent the question, the send cleared the draft, and the screen went blank with no record
of what had been asked. "The prompt vanished, uncommanded" is that sentence.

So the property this module exists to pin is the pinned question. Everything else here
— the bound on the window, the bound on one render, the chips staying inside it — is the
same discipline items 37, 42 and 45 already paid for on the bubble, restated for a
window that renders on every partial too.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling helpers

import flow.ui as ui  # noqa: E402
from flow.session import Event  # noqa: E402
from test_editor import WORK, MeasuringCanvas  # noqa: E402

WORD = "release notes about the migration on Tuesday with Sameer and the rollback plan "


def prose(n: int) -> str:
    return (WORD * (n // len(WORD) + 1))[:n]


def card(**kw):
    """A card with a measuring canvas and no Tk, built the way test_bubble builds one."""
    c = ui.ConversationCard.__new__(ui.ConversationCard)
    c.pill = mock.Mock()
    c.pill.accent = "#a78bfa"
    #: A real bool. The panels ask `pill.flashing` rather than comparing `pill.accent`
    #: to `ERROR`, because the pill's accent is interpolated now and spends most of a
    #: flash near red without ever equalling it — and an auto-created Mock is truthy,
    #: which would leave every card in this file permanently in an error state.
    c.pill.flashing = False
    #: A real int, not the auto-created Mock the attribute would otherwise be —
    #: `reposition` does arithmetic on it now that the pill's width can dock.
    c.pill.pill_w = ui.PILL_W
    c.pill.work = WORK
    # The panel band's height comes off the pill now that they share a window,
    # so a Mock pill would otherwise answer `panel_h()` with a Mock.
    c.pill.band_h = lambda: ui.PANEL_MAX_H
    c.pill.x, c.pill.y = 900, 560
    c.pill.session = mock.Mock(can_take_reply=True, auto_ask_in=None)
    c.canvas = MeasuringCanvas()
    c._history, c._heights = [], []
    c._top = 0
    c._drag_y, c._drag_px = None, 0
    c._question = c._answer = c._partial = c._note = ""
    c._visible = True
    c._h = ui.CARD_MIN_H
    c._pinned_h = 0
    c._countdown = None
    #: What `reposition` asked for. It used to be a `geometry` string, because this was
    #: a window; it is a `place` call now, because the card is a band inside the pill's
    #: one window. The record is kept because tests read the height back out of it.
    c.placed = []
    c.place = lambda **kw: c.placed.append(f"{kw['width']}x{kw['height']}+0+0")
    c.place_forget = lambda: None
    for name, value in kw.items():
        setattr(c, name, value)
    return c


def drawn(c) -> list[str]:
    """Every string that reached the canvas as visible text, probes excluded.

    `_render` measures before it draws and both go through `create_text`, so the drawn
    set is the items after the last `delete`. `MeasuringCanvas.delete` clears its list,
    which is what makes that separation free here.
    """
    return [i["text"] for i in c.canvas.items if i["text"]]


class TestTheQuestionSurvivesItsAnswer(unittest.TestCase):
    """The whole reason the card exists."""

    def test_a_question_is_on_screen_before_the_answer_is(self):
        c = card()
        c.ask("how do I widen a column")
        self.assertIn("how do I widen a column", drawn(c))

    def test_and_is_still_on_screen_once_the_answer_arrives(self):
        # The defect, inverted. On the bubble `show_reply` cleared the draft area, so
        # this text was gone by the time its answer was readable.
        c = card()
        c.ask("how do I widen a column")
        c.answer("Use ALTER TABLE.")
        body = drawn(c)
        self.assertIn("how do I widen a column", body)
        self.assertIn("Use ALTER TABLE.", body)

    def test_the_answer_is_drawn_in_the_reply_colour_and_the_question_is_not(self):
        c = card()
        c.ask("q")
        c.answer("a")
        colours = {i["text"]: i.get("fill") for i in c.canvas.items}
        self.assertEqual(colours["a"], ui.REPLY)
        self.assertEqual(colours["q"], ui.MUTED)

    def test_the_forming_words_sit_where_the_question_will(self):
        c = card()
        c.show_partial("how do I wid")
        self.assertIn("how do I wid", drawn(c))

    def test_and_are_replaced_by_the_question_when_it_goes(self):
        c = card()
        c.show_partial("how do I wid")
        c.ask("how do I widen a column")
        self.assertNotIn("how do I wid", drawn(c))
        self.assertIn("how do I widen a column", drawn(c))


class TestOlderTurnsScrollAbove(unittest.TestCase):
    def test_a_second_question_pushes_the_first_exchange_up(self):
        c = card()
        c.ask("first question")
        c.answer("first answer")
        c.ask("second question")
        self.assertEqual(c._history, [("q", "first question"), ("a", "first answer")])
        self.assertEqual(c._question, "second question")
        self.assertEqual(c._answer, "")

    def test_an_unanswered_question_still_becomes_history(self):
        # A question that failed is still a question that was asked, and losing it
        # would be the vanishing this card exists to end.
        c = card()
        c.ask("first")
        c.ask("second")
        self.assertEqual(c._history, [("q", "first")])

    def test_one_ask_puts_the_question_on_screen_once(self):
        """From a real session: one ask in the log, three copies on the card.

        The draft emptying is how the UI learns a question has gone, and more than one
        empty-draft event can land while a single ask is outstanding — a slow one leaves
        a long window. `ask` files the current question into history every time it is
        called, which is exactly what `test_a_second_question_pushes_the_first_exchange_up`
        depends on, so the fix belongs at the caller: `Pill._ask_is_new` turns the level
        ("is the session asking") into an edge ("has this ask been shown").

        Measured case: an 82-character question, one `ask` event, a 20 s timeout, and the
        question drawn three times with "ask failed" under it.
        """
        from flow.session import State

        pill = ui.Pill.__new__(ui.Pill)
        pill.session = mock.Mock(state=State.ASKING)
        pill._asked = False

        c = card()
        for _ in range(5):  # five empty-draft events during one slow ask
            if pill._ask_is_new():
                c.ask("Can you tell me about this project?")
        rows = [t for _, t in c._history] + [c._question]
        self.assertEqual(rows.count("Can you tell me about this project?"), 1)
        self.assertEqual(c._history, [])

    def test_asking_the_same_question_again_still_shows_it_again(self):
        # The flag must not swallow a real second ask — it is cleared on the first frame
        # the session is no longer ASKING, which is what `_pump` does.
        from flow.session import State

        pill = ui.Pill.__new__(ui.Pill)
        pill.session = mock.Mock(state=State.ASKING)
        pill._asked = False

        c = card()
        for _ in range(3):
            if pill._ask_is_new():
                c.ask("same question")
        pill._asked = False  # the ask ended
        for _ in range(3):
            if pill._ask_is_new():
                c.ask("same question")
        self.assertEqual(c._history, [("q", "same question")])
        self.assertEqual(c._question, "same question")

    def test_the_history_is_bounded_like_the_thread_is(self):
        c = card()
        for i in range(60):
            c.ask(f"question {i}")
            c.answer(f"answer {i}")
        self.assertLessEqual(len(c._history), 2 * ui.THREAD_MAX_TURNS)
        self.assertEqual(len(c._heights), len(c._history))

    def test_a_turn_is_measured_once_when_it_is_pushed_and_never_on_a_render(self):
        # This card draws on every partial. A per-render walk of twenty wrapped turns
        # is item 37's 476.7 ms rebuilt on a different surface.
        c = card()
        for i in range(8):
            c.ask(f"question {i}")
            c.answer(prose(2_000))
        with mock.patch.object(ui.ConversationCard, "_row_h",
                               side_effect=AssertionError("measured on a render")):
            c.show_partial("still typing")
            c.show_partial("still typing a bit more")

    def test_one_enormous_turn_is_laid_out_from_its_head_under_a_cap(self):
        c = card()
        c.ask(prose(50_000))
        c.answer("ok")
        c.ask("next")
        row = c._row_text(c._history[0])
        # `head_window` runs forward to the next space rather than cutting mid-word, so
        # the bound is the cap plus that scan — the point is that it is a bound at all.
        self.assertLessEqual(len(row), ui.CARD_TURN_CHARS + ui.BODY_BOUNDARY_SCAN)
        self.assertTrue(prose(50_000).startswith(row[:40]))


class TestTheWindowStaysInsideTheDesktop(unittest.TestCase):
    """Item 42's fit and item 44's anchor, on this window's width."""

    def positions(self):
        left, top, right, bottom = WORK
        return [(left, top), (right - ui.PILL_W, top),
                (left, bottom - ui.PILL_H), (right - ui.PILL_W, bottom - ui.PILL_H),
                ((left + right) // 2, (top + bottom) // 2)]

    def test_a_twelve_thousand_character_answer_does_not_grow_past_the_work_area(self):
        left, top, right, bottom = WORK
        for x, y in self.positions():
            with self.subTest(pos=(x, y)):
                c = card()
                c.pill.x, c.pill.y = x, y
                c.ask("write me a complete prompt")
                c.answer(prose(12_000))
                self.assertLessEqual(c._h, bottom - top - 2 * ui.EDGE_AIR)
                geom = c.placed[-1]
                size, gx, gy = geom.split("+")[0], *map(int, geom.split("+")[1:])
                self.assertEqual(size, f"{ui.CARD_W}x{c._h}")
                self.assertGreaterEqual(gx, left)
                self.assertGreaterEqual(gy, top)
                self.assertLessEqual(gx + ui.CARD_W, right)
                self.assertLessEqual(gy + c._h, bottom)

    def test_what_is_left_out_of_a_long_answer_is_said(self):
        c = card()
        c.ask("write me a complete prompt")
        c.answer(prose(12_000))
        self.assertTrue(any(t.startswith("… ") and t.endswith("more lines")
                            for t in drawn(c)),
                        "a clipped answer said nothing about the rest")

    def test_the_chips_are_inside_the_window_however_tall_the_answer(self):
        c = card()
        c.ask("q")
        c.answer(prose(12_000))
        chips = [i for i in c.canvas.items
                 if i["text"] in ("Ask", "Use this", "Copy", "New conversation")]
        self.assertEqual(len(chips), 4)
        for chip in chips:
            self.assertLess(chip["y"], c._h, chip["text"])
            self.assertGreater(chip["y"], 0, chip["text"])


class TestTheChips(unittest.TestCase):
    def labels(self, c) -> list[str]:
        keys = ("Ask", "Use this", "Copy", "New conversation")
        return [i["text"] for i in c.canvas.items
                if any(i["text"].startswith(k) for k in keys)]

    def test_ask_is_there_before_anything_has_been_asked(self):
        c = card()
        c.show()
        self.assertIn("Ask", self.labels(c))

    def test_the_countdown_rides_on_the_ask_chip(self):
        c = card()
        c.pill.session.auto_ask_in = 2.4
        c.ask("q")
        self.assertIn("Ask 3s", self.labels(c))

    def test_use_this_and_copy_appear_only_with_an_answer(self):
        c = card()
        c.ask("q")
        self.assertNotIn("Use this", self.labels(c))
        self.assertNotIn("Copy", self.labels(c))
        c.answer("an answer")
        self.assertIn("Use this", self.labels(c))
        self.assertIn("Copy", self.labels(c))

    def test_copy_carries_the_whole_answer_and_not_the_head_that_is_drawn(self):
        # Item 45's promise, restated on this surface: the window is a view, not a
        # truncation.
        c = card()
        c.pill._copy = mock.Mock(return_value="")
        c.ask("q")
        c.answer(prose(12_000))
        c._copy_answer()
        c.pill._copy.assert_called_once_with(prose(12_000))

    def test_use_this_hands_the_answer_over_and_stops_showing_it_as_one(self):
        c = card()
        c.pill.session.take_reply = mock.Mock(return_value=True)
        c.ask("q")
        c.answer("an answer")
        c._take_reply()
        self.assertEqual(c._answer, "")
        self.assertNotIn("an answer", drawn(c))

    def test_a_refused_take_leaves_the_answer_where_it_is(self):
        c = card()
        c.pill.session.take_reply = mock.Mock(return_value=False)
        c.ask("q")
        c.answer("an answer")
        c._take_reply()
        self.assertEqual(c._answer, "an answer")


class TestNewConversationEmptiesTheCard(unittest.TestCase):
    def test_the_chip_asks_the_session_rather_than_clearing_the_window(self):
        # Item 64. Clearing the card alone is the half-clear root 4 is about: the thread
        # and the reply would survive, so the next question would inherit a conversation
        # that is no longer on screen. The card is cleared by the event coming back.
        c = card()
        c.ask("first")
        c._new_conversation()
        c.pill.session.new_conversation.assert_called_once()

    def test_everything_goes_in_one_act(self):
        c = card()
        c.ask("first")
        c.answer("first answer")
        c.ask("second")
        c.note("a note")
        c.clear()
        self.assertEqual((c._history, c._question, c._answer, c._note), ([], "", "", ""))
        self.assertEqual(c._top, 0)


class TestScrolling(unittest.TestCase):
    """Item 32's viewport, and the reason it has two ways in."""

    def loaded(self):
        # 12 turns overflowed the viewport at Segoe UI's metrics; `FONT_NOTE` fits more
        # characters a line at the real canvas's measured width, so the row count is
        # raised rather than the assertions loosened — the same history still has to
        # scroll, just needs more of it to prove the viewport, not the font, is what's
        # being tested (decisions.md 2026-08-09, the IBM Plex Sans migration).
        c = card()
        for i in range(30):
            c.ask(f"question number {i}")
            c.answer(f"answer number {i}")
        c.ask("the current one")
        c.answer("the current answer")
        return c

    def test_the_wheel_moves_the_view(self):
        c = self.loaded()
        c._top = 0
        c._wheel(mock.Mock(delta=-120))
        self.assertGreater(c._top, 0)

    def test_the_drag_moves_it_too_and_is_the_one_that_cannot_be_switched_off(self):
        # On Windows `WM_MOUSEWHEEL` goes to the *focused* window and this one is never
        # focused; the wheel arrives only through a setting a user can turn off.
        c = self.loaded()
        c._top = 0
        c._grab(mock.Mock(y=200))
        c._drag(mock.Mock(y=100))
        self.assertGreater(c._top, 0)

    def test_it_never_scrolls_past_the_last_turn(self):
        c = self.loaded()
        c._scroll(10_000)
        self.assertLessEqual(c._top, max(0, len(c._history) - 1))

    def test_and_never_before_the_first(self):
        c = self.loaded()
        c._scroll(-10_000)
        self.assertEqual(c._top, 0)

    def test_a_new_question_scrolls_the_history_to_the_end(self):
        # The turn that just happened is the one worth looking at; a card that stayed
        # where the reader left it would answer into a view of last week.
        c = self.loaded()
        c._top = 0
        c.ask("and one more")
        self.assertEqual(c._top, c._max_top())


def drawn_answer(c) -> str:
    """What reached the canvas as the answer, ignoring probes and furniture."""
    hits = [i["text"] for i in c.canvas.items if i["text"] and i["text"] in c._answer]
    return hits[-1] if hits else ""


def more_line(c) -> str:
    return next((i["text"] for i in c.canvas.items
                 if i["text"].startswith("…") and "more lines" in i["text"]), "")


class TestTheAnswerShowsItsHead(unittest.TestCase):
    """P10, shape (b) — moved here from the bubble with the code it is about (item 63).

    An artifact is read from the top, so the window holds the top. The class is
    otherwise item 45's, restated on this window's width: the guarantees did not change,
    the surface did.
    """

    def answered(self, text):
        c = card()
        c.ask("write me a complete prompt")
        c.answer(text)
        return c

    def test_a_long_answer_shows_its_first_lines(self):
        c = self.answered(prose(12_000))
        shown = drawn_answer(c)
        self.assertTrue(c._answer.startswith(shown), "windowed from the wrong end")
        self.assertLess(len(shown), len(c._answer))

    def test_it_is_not_the_tail(self):
        # Both directions, so a window cannot pass this by being a window.
        c = self.answered(prose(12_000)[:-20] + "the very last words")
        self.assertNotIn("the very last words", drawn_answer(c))

    def test_no_word_is_cut_in_half(self):
        c = self.answered(prose(12_000))
        self.assertTrue(c._answer[len(drawn_answer(c))].isspace(),
                        "the window closed mid-word")

    def test_an_answer_that_fits_is_drawn_whole_and_says_nothing(self):
        c = self.answered(prose(200))
        self.assertEqual(drawn_answer(c), prose(200))
        self.assertEqual(more_line(c), "")

    def test_the_count_is_measured_and_exact(self):
        # The draft's `… N earlier lines` is an estimate from a characters-per-line
        # average, because laying the head out to count it exactly is the cost item 37
        # exists to avoid — on every partial. An answer is laid out once and already
        # carries a full-text probe, so here N is the truth: total lines minus shown
        # lines, both off the canvas.
        c = self.answered(prose(12_000))
        line = more_line(c)
        self.assertRegex(line, r"^… \d+ more lines$")
        shown_text = drawn_answer(c)
        probe = lambda t: c.canvas.create_text(  # noqa: E731
            ui.PAD, ui.PAD, anchor="nw", text=t, font=("Segoe UI", 10),
            width=ui.CARD_W - 2 * ui.PAD)
        h = lambda i: c.canvas.bbox(i)[3] - c.canvas.bbox(i)[1]  # noqa: E731
        full, one, shown = probe(c._answer), probe("M"), probe(shown_text)
        self.assertEqual(int(line.split()[1]),
                         round(h(full) / h(one)) - round(h(shown) / h(one)))

    def test_the_count_grows_with_the_answer(self):
        counts = [int(more_line(self.answered(prose(n))).split()[1])
                  for n in (6_000, 12_000)]
        self.assertLess(counts[0], counts[1])

    def test_the_answer_sizes_the_card_again(self):
        """It did; then it did not for two commits; now it does, and that is right.

        Fixing the height stopped the card moving and left a hole in it instead. A
        FluidVoice demo read frame by frame settled the argument: that overlay's bottom
        edge is at y=554 in every frame while the box is snug around two lines, then
        three. Snug is what a reader wants; what must not move is the *foot*, and
        `Pill._sync_shell` grows the shell upward so the pill row never does.

        Stepping by a whole body line (`_settled_h`) is what keeps it from thrashing.
        """
        self.assertGreater(self.answered(prose(4_000))._h,
                           self.answered(prose(200))._h)


class TestTheExitsCarryTheWholeAnswer(unittest.TestCase):
    """A head window that also truncated the exits would cause the loss it signals.

    `Use this` goes through `session.take_reply()`, which reads `session.reply`; `Copy`
    goes through `pill._copy(self._answer)`. Neither has ever read the drawn string and
    neither may start.
    """

    def test_take_reply_reads_the_session_not_the_drawn_window(self):
        from flow.session import Session

        class FakeAsr:
            def load(self, final=None) -> None: ...

            def text(self, a, *, final=False, hotwords="") -> str:
                return ""

        class FakeMic:
            level_db = -60.0

            def start(self) -> None: ...

            def stop(self) -> None: ...

            @property
            def active(self) -> bool:
                return True

            def restart(self) -> None: ...

            def drain(self) -> list:
                return []

        whole = prose(12_000)
        s = Session(asr=FakeAsr(), mic=FakeMic())
        s.reply = whole
        self.assertTrue(s.take_reply())
        self.assertEqual(s.draft.text, whole, "the exit carried a window, not the answer")

    def test_the_card_draws_less_than_it_holds(self):
        c = card()
        c.ask("q")
        c.answer(prose(12_000))
        self.assertLess(len(drawn_answer(c)), len(c._answer))
        self.assertEqual(len(c._answer), 12_000)


class TestEachWindowHasOneColour(unittest.TestCase):
    """Item 63: amber and violet stop being one card's moods.

    They used to be `pill.accent`, so the outline changed under the same words as the
    session moved through its states — the colour doing a second window's job.
    """

    def test_the_card_is_violet_and_the_bubble_claims_nothing(self):
        c = card()
        c.pill.accent = ui.ACCENT[ui.State.LISTENING]
        self.assertEqual(c.accent, ui.CARD_ACCENT)
        # The bubble's amber is gone. It was `RECOVER_ACCENT` under a second name, and
        # nothing reads this as a colour any more — the chrome is neutral, the primary
        # chip is `PRIMARY_FILL`, the loading dot is `WAITING`. Amber is spent once now,
        # on "Bring it back" (decisions.md 2026-08-09, "amber means five things").
        b = ui.Bubble.__new__(ui.Bubble)
        b.pill = mock.Mock(accent=ui.ACCENT[ui.State.LISTENING], flashing=False)
        self.assertEqual(b.accent, ui.MUTED)
        self.assertNotEqual(b.accent, ui.RECOVER_ACCENT)

    def test_neither_changes_with_the_session_state(self):
        c = card()
        for state in ui.State:
            c.pill.accent = ui.ACCENT[state]
            self.assertEqual(c.accent, ui.CARD_ACCENT, state)

    def test_but_the_error_flash_still_reaches_both(self):
        # The note the flash belongs to is drawn on one of these windows, so a red pill
        # beside a violet card would be two answers to one question.
        #
        # `flashing`, not `accent == ERROR`: §07 gives the pill's own hairline an 80 /
        # 1200 / 600 envelope, so `pill.accent` is a blend for most of a flash. A panel
        # ring is "set red once and cleared once" — it wants the fact, not the frame.
        c = card()
        c.pill.flashing = True
        self.assertEqual(c.accent, ui.ERROR)
        b = ui.Bubble.__new__(ui.Bubble)
        b.pill = mock.Mock(flashing=True)
        self.assertEqual(b.accent, ui.ERROR)

    def test_the_pill_keeps_three_colours_and_neither_of_theirs(self):
        values = set(ui.ACCENT.values())
        self.assertEqual(len(values), 3)
        self.assertNotIn(ui.RECOVER_ACCENT, values)
        self.assertNotIn(ui.CARD_ACCENT, values)

    def test_amber_is_spent_exactly_once(self):
        # The finding this whole palette pass came from: panel outline, primary chip,
        # loading dot and "Bring it back" were one amber, so none of them was emphasis.
        # `RECOVER_ACCENT` is now the only name it has, and undo-after-send is the only
        # thing that reads it.
        self.assertFalse(hasattr(ui, "DRAFT_ACCENT"))
        self.assertNotIn(ui.RECOVER_ACCENT, set(ui.ACCENT.values()))
        self.assertNotEqual(ui.PRIMARY_FILL, ui.RECOVER_ACCENT)
        self.assertNotEqual(ui.RING, ui.RECOVER_ACCENT)
        self.assertNotEqual(ui.WAITING, ui.RECOVER_ACCENT)

    def test_a_held_draft_and_a_question_out_are_no_longer_pill_moods(self):
        self.assertEqual(ui.ACCENT[ui.State.DRAFT], ui.ACCENT[ui.State.IDLE])
        self.assertEqual(ui.ACCENT[ui.State.ASKING], ui.ACCENT[ui.State.REFINING])


class TestTogglingSwapsSurfaces(unittest.TestCase):
    """One window opens, the other closes, and exactly one is up afterwards."""

    def pill(self, mode):
        p = ui.Pill.__new__(ui.Pill)
        p.session = mock.Mock(mode=mode)
        p.bubble = mock.Mock()
        p.card = mock.Mock()
        return p

    def test_switching_into_converse_opens_the_card_and_shuts_the_bubble(self):
        p = self.pill(ui.CONVERSE)
        p._swap_surfaces()
        p.card.show.assert_called_once()
        p.bubble.hide.assert_called_once()

    def test_switching_out_closes_the_card_and_brings_the_bubble_up(self):
        # The bubble is *opened* rather than left to the next event, because the note
        # that follows the mode event names the workshop and `note()` only paints on a
        # window that is already showing. That line has been invisible whenever there
        # was no draft on screen, which is most of the times somebody switches mode.
        p = self.pill(ui.DICTATE)
        p._swap_surfaces()
        p.card.close.assert_called_once()
        p.bubble.surface.assert_called_once_with("")


class TestTheBubbleStaysShutInConverse(unittest.TestCase):
    """`Pill.front`, which is what keeps two surfaces from being one again."""

    def pill(self, mode):
        p = ui.Pill.__new__(ui.Pill)
        p.session = mock.Mock(mode=mode)
        p.bubble = mock.Mock()
        p.card = mock.Mock()
        return p

    def test_converse_notes_and_partials_go_to_the_card(self):
        p = self.pill(ui.CONVERSE)
        self.assertTrue(p.converse)
        self.assertIs(p.front, p.card)

    def test_dictate_notes_and_partials_go_to_the_bubble(self):
        p = self.pill(ui.DICTATE)
        self.assertFalse(p.converse)
        self.assertIs(p.front, p.bubble)

    def test_both_surfaces_answer_to_the_same_names(self):
        # The protocol `Pill.front` hands work to. A rename on one side is invisible to
        # every unit test here, because none of them drives a real frame — which is
        # exactly how a card with `partial()` came to sit under a `_frame` calling
        # `show_partial`, caught by the real-Tk probe and not by any of these.
        for name in ("show_partial", "note"):
            with self.subTest(name=name):
                self.assertTrue(callable(getattr(ui.ConversationCard, name, None)))
                self.assertTrue(callable(getattr(ui.Bubble, name, None)))

    def test_the_names_frame_calls_on_the_card_all_exist(self):
        for name in ("show_partial", "note", "ask", "answer", "show", "close",
                     "tick_countdown"):
            with self.subTest(name=name):
                self.assertTrue(callable(getattr(ui.ConversationCard, name, None)))

    def test_a_session_with_no_mode_at_all_is_dictate(self):
        # `--no-profile`, a fixture, an embedding. The bubble is the safe default: it is
        # the surface that existed before there were two.
        p = ui.Pill.__new__(ui.Pill)
        p.session = object()
        p.bubble, p.card = mock.Mock(), mock.Mock()
        self.assertIs(p.front, p.bubble)


class TestAnAnswerThatLandsAfterTheSwitch(unittest.TestCase):
    """Reported from a screenshot: a dictate draft with the conversation card behind it.

    The sequence was ask in converse, clear, switch to dictate, start a new draft from
    the clipboard — and the CLI, still working, answered into a mode that had moved on.
    `_swap_surfaces` says exactly one window is up afterwards and it was true when it
    ran; the reply branch then deiconified the card on top of the bubble, several
    seconds later, with nothing on screen explaining why.

    `Session.send()` cannot ask in dictate mode, and the reply branch was commented
    "converse only, by construction" on the strength of it. That argument covers the
    moment a question *leaves*. It says nothing about the moment an answer *arrives*,
    which is the one this class is about — and the gap between them is the whole 4-20 s
    the CLI takes.
    """

    def pill(self, mode):
        p = ui.Pill.__new__(ui.Pill)
        p.session = mock.Mock(mode=mode, state=ui.State.IDLE)
        p.bubble, p.card = mock.Mock(), mock.Mock()
        p._asked, p._last_draft, p._flash = False, "", 0
        return p

    def pump(self, p, *events):
        p.session.events.return_value = [Event(k, t) for k, t in events]
        p._pump_events()

    def test_in_converse_the_answer_still_comes_up_on_the_card(self):
        p = self.pill(ui.CONVERSE)
        self.pump(p, ("reply", "you add it with a migration"))
        p.card.answer.assert_called_once()
        self.assertTrue(self.raised(p.card.answer))

    def test_in_dictate_it_does_not_open_the_card_over_the_draft(self):
        p = self.pill(ui.DICTATE)
        self.pump(p, ("reply", "you add it with a migration"))
        self.assertFalse(self.raised(p.card.answer),
                         "the card came up on top of the bubble")

    def test_but_the_answer_is_not_thrown_away_either(self):
        # The other way to keep one window up, and it is worse: the CLI spent seconds
        # on this, the question is spent with it, and there is no second copy anywhere.
        p = self.pill(ui.DICTATE)
        self.pump(p, ("reply", "you add it with a migration"))
        p.card.answer.assert_called_once()
        self.assertEqual(p.card.answer.call_args.args[0], "you add it with a migration")

    def test_and_the_bubble_says_the_answer_arrived(self):
        # P2's rule about dropped speech, read across to a dropped *surface*: the answer
        # may be off screen, it may not be off screen unexplained. `surface` rather than
        # `note` because the bubble paints a note only when it is already showing, and
        # the case that needs the line most is the one with no draft up.
        p = self.pill(ui.DICTATE)
        self.pump(p, ("reply", "you add it with a migration"))
        p.bubble.surface.assert_called_once()
        self.assertIn("converse", p.bubble.surface.call_args.args[0])

    def test_and_the_card_stays_shut_in_dictate(self):
        p = self.pill(ui.DICTATE)
        self.pump(p, ("reply", "an answer"))
        for opened in (p.card.show, p.card.deiconify):
            opened.assert_not_called()

    def test_switching_back_finds_the_answer_waiting(self):
        # What the held answer is for. `_swap_surfaces` opens the card and the card
        # renders what it was given while it was down — so the trip is one mode switch,
        # not a re-ask.
        c = card()
        c._visible = False
        c.deiconify = mock.Mock()
        c.attributes = mock.Mock()
        c.answer("you add it with a migration", surface=False)
        self.assertEqual(c._answer, "you add it with a migration")
        c.deiconify.assert_not_called()
        c.show()
        # It used to `deiconify` a window of its own. There is one window now, and a
        # band that has been given a place in it is a band that is showing.
        self.assertTrue(c.placed)

    @staticmethod
    def raised(call) -> bool:
        """Did the reply branch ask the card to come up, or only to hold the text?"""
        return call.call_args is not None and call.call_args.kwargs.get("surface", True)


if __name__ == "__main__":
    unittest.main()
