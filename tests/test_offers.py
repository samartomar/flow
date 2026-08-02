"""What Flow inferred, offered for the user to declare — and never self-promoted.

An inferred pair is a guess from a word-level diff, and `profile.json` on this machine
has yet to learn a single real one, so nothing here promotes itself. The other half of
the problem is the owner's, in their own words: "unless it is exposed to UI right click
… i will not be able to use it". A correction that only exists if somebody opens a text
file and types an arrow is a correction that will not exist.

So consent costs one tap. A pair seen `PROMOTE_AFTER` times appears in the right-click
menu, the tap appends the arrow line, and the declared/inferred boundary survives intact
— what changes is the typing, not the standard of evidence.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.lexicon import MAX_TERMS, append_pair, pairs  # noqa: E402
from flow.profile import PROMOTE_AFTER, Profile  # noqa: E402


def tmp_profile() -> Profile:
    return Profile(Path(tempfile.mkdtemp()) / "profile.json")


class Temp(unittest.TestCase):
    def setUp(self) -> None:
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = Path(d.name)
        self.path = self.dir / "lexicon.txt"


class TestWhatIsWorthOffering(unittest.TestCase):
    def test_a_pair_seen_twice_is_offered_and_once_is_not(self):
        p = tmp_profile()
        p.learn_pair("semir", "Samir")
        self.assertEqual(p.offered_pairs(), [], "one sighting is not a pattern")
        p.learn_pair("semir", "Samir")
        self.assertEqual(p.offered_pairs(), [("semir", "Samir")])

    def test_a_pair_already_declared_is_not_offered_again(self):
        # The tap's own consequence removes the offer: the substitution exists now, and
        # a menu that keeps asking about a decision already made is a menu nobody reads.
        p = tmp_profile()
        for _ in range(PROMOTE_AFTER):
            p.learn_pair("semir", "Samir")
        self.assertEqual(p.offered_pairs(declared=[("semir", "Samir")]), [])

    def test_the_left_side_is_matched_case_insensitively_like_the_file_is(self):
        p = tmp_profile()
        for _ in range(PROMOTE_AFTER):
            p.learn_pair("Semir", "Samir")
        self.assertEqual(p.offered_pairs(declared=[("SEMIR", "Samir")]), [])

    def test_at_most_three_are_shown_most_seen_first(self):
        # The menu is a native modal loop that already costs a measured ~16 s stall at
        # worst, and this is not a settings page. The full list has no other UI on
        # purpose.
        p = tmp_profile()
        for n, (wrong, right) in enumerate(
            [("a", "A"), ("b", "B"), ("c", "C"), ("d", "D"), ("e", "E")]
        ):
            for _ in range(PROMOTE_AFTER + n):
                p.learn_pair(wrong, right)
        offers = p.offered_pairs()
        self.assertEqual(len(offers), 3)
        self.assertEqual([r for _w, r in offers], ["E", "D", "C"])


class TestNeverMeansNever(unittest.TestCase):
    def test_a_dismissed_pair_is_not_offered_again(self):
        p = tmp_profile()
        for _ in range(PROMOTE_AFTER):
            p.learn_pair("semir", "Samir")
        p.dismiss_pair("semir", "Samir")
        self.assertEqual(p.offered_pairs(), [])

    def test_and_survives_a_reload(self):
        p = tmp_profile()
        for _ in range(PROMOTE_AFTER):
            p.learn_pair("semir", "Samir")
        p.dismiss_pair("semir", "Samir")
        self.assertTrue(p.save())
        again = Profile(p.path)
        self.assertEqual(again.offered_pairs(), [])

    def test_dismissing_does_not_stop_the_term_being_learned_as_a_hotword(self):
        # "do not ask me about this again" is not "do not use what you learned": the
        # inferred hotword was never the thing needing consent, because it biases
        # toward the *right* spelling and changes no text.
        p = tmp_profile()
        for _ in range(PROMOTE_AFTER):
            p.learn_pair("semir", "Samir")
        p.dismiss_pair("semir", "Samir")
        self.assertIn("Samir", p.learned_terms())

    def test_an_older_profile_with_no_dismissals_loads_and_offers(self):
        # Additive, schema stays 1, exactly as `voice` established.
        p = tmp_profile()
        p.path.parent.mkdir(parents=True, exist_ok=True)
        p.path.write_text('{"schema": 1, "pairs": {"semir -> Samir": 2}}',
                          encoding="utf-8")
        self.assertTrue(p.load())
        self.assertEqual(p.offered_pairs(), [("semir", "Samir")])


class TestTheTapWritesOneLine(Temp):
    ORIGINAL = (
        "# my own words\n"
        "Samir\n"
        "kubectl\n"
        "\n"
        "cube cuttle -> kubectl\n"
    )

    def test_exactly_one_line_is_added_and_nothing_else_moves(self):
        # Flow appends. It does not rewrite, reformat, sort or de-duplicate a file the
        # user owns — so what was there before must come back byte for byte.
        self.path.write_text(self.ORIGINAL, encoding="utf-8")
        self.assertEqual(append_pair(self.path, "semir", "Samir"), "")
        after = self.path.read_text(encoding="utf-8")
        self.assertTrue(after.startswith(self.ORIGINAL))
        self.assertEqual(after[len(self.ORIGINAL):], "semir -> Samir\n")

    def test_a_file_with_no_trailing_newline_does_not_get_a_joined_line(self):
        self.path.write_text("Samir", encoding="utf-8")
        self.assertEqual(append_pair(self.path, "semir", "Samir"), "")
        self.assertEqual(self.path.read_text(encoding="utf-8"),
                         "Samir\nsemir -> Samir\n")

    def test_a_missing_file_is_created_from_the_template_first(self):
        # Otherwise the first tap produces a file with one arrow in it and none of the
        # explanation, which is the file the user then has to make sense of.
        self.assertEqual(append_pair(self.path, "semir", "Samir"), "")
        body = self.path.read_text(encoding="utf-8")
        self.assertIn("# Flow settings", body)
        self.assertEqual(pairs(body), [("semir", "Samir")])

    def test_the_pair_parses_back_out_as_a_correction(self):
        self.path.write_text(self.ORIGINAL, encoding="utf-8")
        append_pair(self.path, "semir", "Samir")
        self.assertIn(("semir", "Samir"),
                      pairs(self.path.read_text(encoding="utf-8")))

    def test_the_shared_cap_refuses_the_sixty_fifth_entry_and_says_why(self):
        # `MAX_TERMS` is one budget over terms and corrections together (section 8), and
        # a silent drop past it is the library-truncation failure the cap exists to
        # prevent — the same failure this project already found once.
        self.path.write_text("".join(f"term{i}\n" for i in range(MAX_TERMS)),
                             encoding="utf-8")
        before = self.path.read_text(encoding="utf-8")
        reason = append_pair(self.path, "semir", "Samir")
        self.assertIn(str(MAX_TERMS), reason)
        self.assertEqual(self.path.read_text(encoding="utf-8"), before,
                         "a refused write still changed the file")

    def test_a_missing_directory_is_created_rather_than_refused(self):
        # `ensure` makes the parent, which is what puts `~/.flow/lexicon.txt` there on a
        # first run — so a deep path is a success, not the failure it looks like.
        deep = self.dir / "not" / "yet" / "lexicon.txt"
        self.assertEqual(append_pair(deep, "semir", "Samir"), "")
        self.assertTrue(deep.exists())

    def test_a_path_that_cannot_be_written_reports_instead_of_raising(self):
        # A file where a directory has to be. The menu is a modal loop on the UI thread
        # and an exception out of a tap takes the frame chain with it.
        blocker = self.dir / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        reason = append_pair(blocker / "lexicon.txt", "semir", "Samir")
        self.assertTrue(reason)


class TestTheNextDecodePicksItUp(Temp):
    def test_the_mtime_re_read_sees_the_appended_line(self):
        from flow.lexicon import Lexicon

        self.path.write_text("Samir\n", encoding="utf-8")
        lex = Lexicon(self.path)
        self.assertEqual(lex.pairs(), [])
        self.assertEqual(lex.apply("Change Semir to Samir"), "Change Semir to Samir")
        append_pair(self.path, "semir", "Samir")
        self.assertEqual(lex.pairs(), [("semir", "Samir")])
        self.assertEqual(lex.apply("Change Semir to Samir"), "Change Samir to Samir")


class FakeMenu:
    """Records what was built, so the menu can be pinned without a desktop."""

    def __init__(self, *a, **kw) -> None:
        self.commands: dict = {}
        self.cascades: dict = {}

    def add_command(self, label="", command=None, **kw) -> None:
        self.commands[label] = command

    def add_radiobutton(self, label="", command=None, **kw) -> None:
        # The trigger-word list is built on every open, so a menu fake that could not
        # record a radio entry would stop the offers being testable at all.
        self.commands[label] = command

    def add_separator(self) -> None: ...

    def add_cascade(self, label="", menu=None, **kw) -> None:
        self.cascades[label] = menu

    def tk_popup(self, *a) -> None: ...

    def grab_release(self) -> None: ...


class TestTheMenuCarriesTheOffers(Temp):
    def _menu(self, profile):
        import tkinter as tk

        import flow.ui as ui

        built: list[FakeMenu] = []

        def make(*a, **kw):
            m = FakeMenu()
            built.append(m)
            return m

        pill = ui.Pill.__new__(ui.Pill)
        # `workspace` set for the reason item 34 recorded about Mock parents: an
        # auto-created attribute is truthy, and the Workspace submenu (item 36) would
        # read it as a current path and try to measure it.
        pill.session = mock.Mock(mode=ui.DICTATE, speaker=None, profile=profile,
                                 workspace=None)
        pill.settings_path = self.path
        self._notes: list[str] = []
        pill.bubble = mock.Mock()
        pill.bubble.note = self._notes.append
        pill._clis = []
        with mock.patch.object(tk, "Menu", make), \
                mock.patch.object(tk, "StringVar", mock.Mock()), \
                mock.patch.object(ui, "available", return_value=[]), \
                mock.patch.object(ui, "foreground_hwnd", return_value=0), \
                mock.patch.object(ui, "toplevel_hwnd", return_value=0), \
                mock.patch.object(ui, "_user32"):
            pill._menu(mock.Mock(x_root=0, y_root=0))
        return built

    @staticmethod
    def _offer_labels(built) -> list[str]:
        return [lbl for m in built for lbl in m.commands if "->" in lbl or "→" in lbl]

    def test_a_learned_pair_becomes_a_menu_entry(self):
        p = tmp_profile()
        for _ in range(PROMOTE_AFTER):
            p.learn_pair("semir", "Samir")
        labels = self._offer_labels(self._menu(p))
        self.assertTrue(any("semir" in lbl and "Samir" in lbl for lbl in labels), labels)

    def test_nothing_learned_means_nothing_added(self):
        self.assertEqual(self._offer_labels(self._menu(tmp_profile())), [])

    def test_no_profile_at_all_is_not_a_crash(self):
        # `--no-profile` is a supported way to run.
        self.assertEqual(self._offer_labels(self._menu(None)), [])

    @staticmethod
    def _command(menu, needle: str):
        found = [c for lbl, c in menu.commands.items() if needle in lbl]
        assert len(found) == 1, f"{needle!r} matched {len(found)} entries"
        return found[0]

    def test_tapping_the_entry_writes_the_line(self):
        p = tmp_profile()
        for _ in range(PROMOTE_AFTER):
            p.learn_pair("semir", "Samir")
        top = self._menu(p)[0]
        self._command(top, "semir")()
        self.assertEqual(pairs(self.path.read_text(encoding="utf-8")),
                         [("semir", "Samir")])

    def test_and_the_offer_is_gone_the_next_time_the_menu_opens(self):
        p = tmp_profile()
        for _ in range(PROMOTE_AFTER):
            p.learn_pair("semir", "Samir")
        top = self._menu(p)[0]
        self._command(top, "semir")()
        self.assertEqual(self._offer_labels(self._menu(p)), [],
                         "still asking about a decision already made")

    def test_never_is_reachable_and_persists(self):
        p = tmp_profile()
        for _ in range(PROMOTE_AFTER):
            p.learn_pair("semir", "Samir")
        # "Never offer" moved under Settings when the menu was split: the tap that
        # matters is the one that says yes, and that one is still top-level.
        settings = self._menu(p)[0].cascades["Settings"]
        never = settings.cascades["Never offer"]
        self._command(never, "semir")()
        self.assertEqual(p.offered_pairs(), [])
        self.assertEqual(Profile(p.path).offered_pairs(), [], "not written to disk")

    def test_a_full_lexicon_refuses_the_tap_and_says_so(self):
        # The cap is shared, and a tap that silently did nothing would be the worst of
        # both: the user consented and nothing happened.
        self.path.write_text("".join(f"term{i}\n" for i in range(MAX_TERMS)),
                             encoding="utf-8")
        p = tmp_profile()
        for _ in range(PROMOTE_AFTER):
            p.learn_pair("semir", "Samir")
        top = self._menu(p)[0]
        pill_note = None
        self._command(top, "semir")()
        for call in self._notes:
            pill_note = call
        self.assertIn(str(MAX_TERMS), pill_note or "")


if __name__ == "__main__":
    unittest.main()
