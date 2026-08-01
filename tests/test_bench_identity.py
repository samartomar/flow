"""A number in `.bench/` belongs to a build, and until now none of them said which.

Section 9 tracks `.bench/` results in git because "a measurement taken at a moment cannot
be re-taken" — and every one of those numbers is a word error rate or a latency produced
by a particular ctranslate2 release against a particular set of model weights, neither of
which announces itself. Item 10 put that identity in the app's diag trace, which on this
machine does not exist; so the pinning decision's own reopen condition — a revision hash
that changed between two runs — could not be checked from the results themselves.

The awkward part is that provenance contains a date, and item 14 verified a grammar
change by showing two consecutive `command_bench.py` outputs were **byte-identical**.
That idiom has to survive, so everything provenance goes under one key and a comparison
diffs around it.
"""

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.diag import BENCH_KEY, bench_identity  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

#: Every script under `scripts/` that writes a *measurement*. Confirmed by grepping for
#: json writers rather than by trusting a list: `gate_bench`, `rescue_bench`, `asr_bench`
#: and `polish_check` are all here and were all missing from the first list drawn up.
WRITERS = (
    "accent_bench.py", "asr_bench.py", "command_bench.py", "gate_bench.py",
    "guardrail_bench.py", "lexicon_bench.py", "live_check.py", "polish_check.py",
    "rescue_bench.py",
)

#: Deliberately not on that list. These write a manifest of the *data* a benchmark reads
#: — which clips were downloaded, which recordings were ingested — and a manifest is an
#: input, not a result. Nothing in either is a number a model produced, so there is
#: nothing for a model revision to explain.
MANIFESTS = ("fetch_accent_data.py", "ingest_recordings.py")


class TestEveryBenchResultNamesWhatProducedIt(unittest.TestCase):
    def test_each_writer_puts_an_identity_block_in_its_payload(self):
        # Two shapes, because `asr_bench` merges into a file that already exists and
        # assigns the key rather than writing a fresh dict literal.
        written = re.compile(rf'"{BENCH_KEY}"\s*(?:\]\s*=|:)\s*bench_identity\(')
        for name in WRITERS:
            body = (SCRIPTS / name).read_text(encoding="utf-8")
            with self.subTest(script=name):
                # `assertTrue`, not `assertRegex`: a failed `assertRegex` prints the
                # whole haystack, and the haystack here is a 400-line script.
                self.assertTrue(written.search(body) is not None,
                                f"{name} writes a result with no provenance in it")

    def test_and_imports_it_rather_than_reimplementing_the_resolver(self):
        # The hash comes from the local HF cache's own `refs/main`, and two copies of
        # that walk would be two things to keep true.
        for name in WRITERS:
            body = (SCRIPTS / name).read_text(encoding="utf-8")
            with self.subTest(script=name):
                self.assertRegex(body, r"from flow\.diag import [^\n]*bench_identity")

    def test_a_new_json_writer_cannot_slip_in_without_one(self):
        # The check that catches the *next* person: any script writing a json result
        # is either on the list above or is a data manifest, and nothing else.
        writes = {
            p.name for p in SCRIPTS.glob("*.py")
            if re.search(r"write_text\(\s*\n?\s*(json\.dumps|$)|json\.dumps\(",
                         p.read_text(encoding="utf-8"))
        }
        unexplained = writes - set(WRITERS) - set(MANIFESTS)
        self.assertEqual(unexplained, set(),
                         "a script writes json and is neither a bench nor a manifest")


class TestTheBlockItself(unittest.TestCase):
    def test_it_resolves_real_values_on_this_machine(self):
        block = bench_identity(models=("base.en",))
        self.assertRegex(block["faster-whisper"], r"^\d+\.\d+")
        self.assertRegex(block["ctranslate2"], r"^\d+\.\d+")
        self.assertRegex(block["date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertRegex(block["models"]["base.en"], r"^[0-9a-f]{8,}$")

    def test_a_model_that_is_not_cached_says_so_instead_of_lying(self):
        block = bench_identity(models=("no-such-model-anywhere",))
        self.assertEqual(block["models"]["no-such-model-anywhere"], "uncached")

    def test_a_cli_is_named_only_when_it_is_asked_for(self):
        # Each costs a process start, and most benches never touch a CLI.
        self.assertNotIn("clis", bench_identity())
        block = bench_identity(clis=("codex",))
        self.assertIn("codex", block["clis"])

    def test_every_value_survives_a_round_trip_through_json(self):
        # It is written into a result file, so anything unserialisable is a bench that
        # crashes at the last line after doing all the work.
        block = bench_identity(models=("base.en", "small.en"))
        self.assertEqual(json.loads(json.dumps(block)), block)

    def test_the_whole_of_it_is_under_one_key(self):
        # Item 14's idiom: two runs of the same bench are compared byte for byte, and
        # this block has a date in it. Under one key, a comparison can drop that key and
        # keep meaning what it meant — spread across the payload it could not.
        self.assertEqual(BENCH_KEY, "identity")
        payload = {"recall": {"n": 14}, BENCH_KEY: bench_identity()}
        without = {k: v for k, v in payload.items() if k != BENCH_KEY}
        self.assertEqual(without, {"recall": {"n": 14}})


class TestTheShippedResultsCarryIt(unittest.TestCase):
    """The one result this round could actually re-run.

    The rest need audio, models, or a person, so their files stay provenance-less until
    somebody re-runs them — which is a fact about the files, not about the writers, and
    the writers are what the checks above pin.
    """

    def test_command_bench_json_has_been_re_run_with_provenance(self):
        path = Path(__file__).resolve().parent.parent / ".bench" / "accent" / "command-bench.json"
        if not path.exists():
            self.skipTest("no command-bench.json in this tree")
        result = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn(BENCH_KEY, result)
        self.assertIn("date", result[BENCH_KEY])

    def test_and_names_no_model_because_it_loads_none(self):
        # The one bench with no audio in it: it measures the grammar, and a revision
        # hash for weights it never touched would be a provenance claim that is false.
        # An empty block says "nothing here depends on a model", which is the truth.
        path = Path(__file__).resolve().parent.parent / ".bench" / "accent" / "command-bench.json"
        if not path.exists():
            self.skipTest("no command-bench.json in this tree")
        result = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(result[BENCH_KEY]["models"], {})
        self.assertRegex(result[BENCH_KEY]["ctranslate2"], r"^\d+\.\d+")


if __name__ == "__main__":
    unittest.main()
