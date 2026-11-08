"""The Whisper rows of Flow Home's model list download the commit the decode path loads.

`tests/test_home.py` covers the page; this is only the pin, which has to agree across two
modules that never call each other: `home.models` downloads, `asr` loads. A download at one
commit and a load at another would fetch three gigabytes and then fetch them again.
"""

import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow import asr  # noqa: E402
from flow.home import models  # noqa: E402

WHISPER = [s for s in (*models.CATALOG, *models.RETIRED) if s.engine == "whisper"]


class TestEveryWhisperRowIsPinned(unittest.TestCase):
    def test_every_whisper_spec_has_a_full_commit_hash(self):
        self.assertTrue(WHISPER)
        for spec in WHISPER:
            with self.subTest(name=spec.name):
                self.assertRegex(spec.revision, r"^[0-9a-f]{40}$")

    def test_and_it_is_the_commit_the_load_path_asks_for(self):
        for spec in WHISPER:
            with self.subTest(name=spec.name):
                self.assertEqual(asr.whisper_revision(spec.name), spec.revision)
                self.assertEqual(asr.WHISPER_PINS[spec.name][0], spec.repo)

    def test_the_parakeet_rows_carry_no_hub_revision(self):
        # Parakeet's commit lives in `parakeet.VARIANTS`; its `repo` here is a folder name.
        for spec in models.PARAKEET_SPECS:
            self.assertEqual(spec.revision, "")


class TestTheDownloadIsPinned(unittest.TestCase):
    def test_snapshot_download_receives_the_specs_revision(self):
        spec = models.BY_NAME["base.en"]
        finished = threading.Event()
        d = models.Downloader(on_done=lambda _job: finished.set())
        with mock.patch("huggingface_hub.snapshot_download") as snap:
            d.start(spec)
            self.assertTrue(finished.wait(2))
        self.assertEqual(snap.call_args.args[0], spec.repo)
        self.assertEqual(snap.call_args.kwargs["revision"], spec.revision)

    def test_a_finished_copy_is_looked_for_at_the_pinned_commit(self):
        # A download by commit hash writes no `refs/main`, so the default lookup would
        # report the model the page just fetched as missing.
        spec = models.BY_NAME["small.en"]
        with mock.patch("huggingface_hub.try_to_load_from_cache",
                        return_value="x/model.bin") as look:
            self.assertTrue(models.complete(spec.repo))
        self.assertEqual(look.call_args.kwargs["revision"], spec.revision)


if __name__ == "__main__":
    unittest.main()
