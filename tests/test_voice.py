"""Choosing which voice reads the replies (P9).

Flow spoke in whichever voice the engine defaulted to for its whole life, and on the
development machine that was `Microsoft David Desktop` — the oldest one installed, never
chosen by anybody. Two things came out of fixing that and both are pinned here.

The first is that "what is installed" depends on which PowerShell asks. `System.Speech`
is a .NET API with two implementations: Windows PowerShell 5.1 enumerated three voices on
that machine, PowerShell 7 enumerated nine, and the six it adds are the OneCore ones. So
the enumeration and the speech host must run under the same executable, or the menu offers
names the host will refuse.

What that difference is *not* is a route to a better voice. Nine is 3 classic
`TTS_MS_*_11.0` tokens plus 6 `MSTTS_V110_*`, all of them the 2013 generation, and
Windows 11's natural voices are unreachable from `System.Speech` under either host — the
package ships a valid token aimed at a registry hive that does not exist, behind an engine
CLSID registered in no COM store. `speak.installed_voices` carries the full measurement.
`test_a_voice_that_is_not_installed_resolves_to_nothing` reaches for `Microsoft Aria
(Natural)` to mean "a name nobody has" — which turns out to be true of every natural voice
on every machine, not the arbitrary miss it looked like when it was written.

That is what the Piper engine is for, and `TestTwoEngines` pins the part of it that this
module owns: a second engine changes which voice an *unnamed* request resolves to, and
must change nothing else.

The second is that a request should not have to be exact. `--voice female` and
`--voice mark` are how people actually ask.
"""

import contextlib
import sys
import time
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flow.speak import HOSTS, VOICE_PREFIX, Voice, host, pick  # noqa: E402

#: Whether the optional `[voice]` extra is installed here. Decided once, at import,
#: rather than inside a test: `TestPiperSynthesis` fakes the `piper` module in
#: `sys.modules`, so asking later could get the fake and skip nothing.
try:
    import piper as _piper  # noqa: F401

    _HAS_PIPER = True
except Exception:  # pragma: no cover - depends on what is installed
    _HAS_PIPER = False

#: What `pwsh` reported on the development machine, in the order it reported it — the
#: legacy pair first, which is why order alone is not a safe way to choose.
INSTALLED = [
    Voice("Microsoft David Desktop", "Male", "en-US"),
    Voice("Microsoft Zira Desktop", "Female", "en-US"),
    Voice("Microsoft David", "Male", "en-US"),
    Voice("Microsoft Mark", "Male", "en-US"),
    Voice("Microsoft Zira", "Female", "en-US"),
]


class TestPick(unittest.TestCase):
    def test_no_request_means_no_opinion(self):
        # None is "let the engine decide", which is the behaviour Flow had before any
        # of this — not a failure, and not a silent substitution.
        self.assertIsNone(pick(None, INSTALLED))
        self.assertIsNone(pick("", INSTALLED))

    def test_an_exact_name_is_honoured_even_when_it_is_the_old_one(self):
        # The preference below must never override someone who named a voice: they have
        # heard it and decided, which beats any rule this module has.
        self.assertEqual(
            pick("Microsoft Zira Desktop", INSTALLED), "Microsoft Zira Desktop"
        )

    def test_a_gender_picks_the_newer_engine(self):
        # Both Ziras are female and the legacy one is listed first, so enumeration order
        # would hand back exactly the voice this feature exists to get away from.
        self.assertEqual(pick("female", INSTALLED), "Microsoft Zira")
        self.assertEqual(pick("male", INSTALLED), "Microsoft David")

    def test_part_of_a_name_is_enough(self):
        self.assertEqual(pick("mark", INSTALLED), "Microsoft Mark")
        self.assertEqual(pick("MARK", INSTALLED), "Microsoft Mark")

    def test_a_partial_match_also_prefers_the_newer_engine(self):
        self.assertEqual(pick("zira", INSTALLED), "Microsoft Zira")

    def test_a_voice_that_is_not_installed_resolves_to_nothing(self):
        # Never a substitution. A profile naming a voice that has since been removed
        # falls back to the default, and the caller is the one that says so out loud.
        self.assertIsNone(pick("Microsoft Aria (Natural)", INSTALLED))

    def test_no_voices_at_all(self):
        self.assertIsNone(pick("female", []))

    def test_english_is_preferred_when_a_gender_matches_several(self):
        voices = [
            Voice("Microsoft Hanako", "Female", "ja-JP"),
            Voice("Microsoft Zira", "Female", "en-US"),
        ]
        self.assertEqual(pick("female", voices), "Microsoft Zira")

    def test_a_non_english_voice_is_still_reachable_by_name(self):
        voices = [Voice("Microsoft Hanako", "Female", "ja-JP")]
        self.assertEqual(pick("hanako", voices), "Microsoft Hanako")
        # ...and is still the answer when it is the only one of its gender.
        self.assertEqual(pick("female", voices), "Microsoft Hanako")


class TestTwoEngines(unittest.TestCase):
    """Piper voices sit in the same list and are chosen by the same rules.

    The design this pins is that `Voice.name` stayed the only handle: the menu, the
    profile and `--voice` all carry a name and nothing else, so adding an engine did not
    have to touch any of them. These cases are what would fail if that stopped being true.
    """

    #: The same machine as INSTALLED, with one Piper model installed alongside.
    MIXED = INSTALLED + [
        Voice("Piper en_GB-alba-medium", "NotSet", "en-GB", engine="piper",
              path="/v/en_GB-alba-medium.onnx", sample_rate=22050),
        Voice("Piper en_US-hfc_female-medium", "Female", "en-US", engine="piper",
              path="/v/en_US-hfc_female-medium.onnx", sample_rate=22050),
    ]

    def test_the_old_shape_still_constructs(self):
        # Three positional fields is how every existing caller builds one, including
        # `_sapi_voices` and half of `scripts/`. The engine fields are additive or they
        # are a breaking change wearing a default.
        v = Voice("Microsoft Mark", "Male", "en-US")
        self.assertEqual(v.engine, "sapi")
        self.assertEqual((v.path, v.sample_rate), ("", 0))

    def test_a_gender_request_prefers_piper_over_both_windows_stores(self):
        # The whole point of adding the engine: `--voice female` should land on the good
        # voice, not on the newest of nine voices that are all from 2013.
        self.assertEqual(pick("female", self.MIXED), "Piper en_US-hfc_female-medium")

    def test_an_exact_windows_name_still_wins_against_a_piper_voice(self):
        # Preference never overrides someone who named a voice — the rule that already
        # protected `Microsoft Zira Desktop` has to hold across engines too.
        self.assertEqual(pick("Microsoft Zira", self.MIXED), "Microsoft Zira")
        self.assertEqual(
            pick("Microsoft Zira Desktop", self.MIXED), "Microsoft Zira Desktop"
        )

    def test_a_gendered_request_cannot_reach_an_unstated_piper_voice(self):
        # `piper._gender` refuses to read a gender off a dataset name, so `alba` is
        # NotSet and `female` must not select it. Documented in the README as the price
        # of not guessing; asserted here so it stays a decision rather than a surprise.
        only_alba = [v for v in self.MIXED if v.name != "Piper en_US-hfc_female-medium"]
        self.assertEqual(pick("female", only_alba), "Microsoft Zira")

    def test_an_unstated_piper_voice_is_still_reachable_by_name(self):
        self.assertEqual(pick("alba", self.MIXED), "Piper en_GB-alba-medium")

    def test_describe_drops_the_gender_it_does_not_have(self):
        # "notset" is a field name, and the menu renders this string.
        self.assertEqual(
            Voice("Piper en_GB-alba-medium", "NotSet", "en-GB", engine="piper").describe(),
            "Piper en_GB-alba-medium (en-GB)",
        )
        self.assertEqual(
            Voice("Microsoft Mark", "Male", "en-US").describe(),
            "Microsoft Mark (male, en-US)",
        )


class TestPiperDiscovery(unittest.TestCase):
    """A machine with no Piper is the normal case and must be a quiet one."""

    def test_no_binary_means_no_voices_and_no_directory_read(self):
        from flow import piper

        with mock.patch("flow.piper._CACHE", None), \
             mock.patch("flow.piper.available", return_value=False):
            self.assertEqual(piper.voices(refresh=True), [])

    def test_a_model_without_its_sidecar_is_not_a_voice(self):
        # Half a model is worse than none: the sidecar carries the sample rate, and a
        # guessed rate plays every syllable at the wrong pitch instead of failing.
        import tempfile

        from flow import piper

        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "en_GB-alba-medium.onnx").write_bytes(b"")
            with mock.patch("flow.piper._CACHE", None), \
                 mock.patch("flow.piper.VOICES_DIR", Path(d)), \
                 mock.patch("flow.piper.available", return_value=True):
                self.assertEqual(piper.voices(refresh=True), [])

    def test_a_complete_pair_becomes_a_voice(self):
        import json as _json
        import tempfile

        from flow import piper

        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "en_GB-alba-medium.onnx").write_bytes(b"")
            (Path(d) / "en_GB-alba-medium.onnx.json").write_text(_json.dumps({
                "audio": {"sample_rate": 22050},
                "language": {"code": "en_GB"},
                "dataset": "alba",
            }))
            with mock.patch("flow.piper._CACHE", None), \
                 mock.patch("flow.piper.VOICES_DIR", Path(d)), \
                 mock.patch("flow.piper.available", return_value=True):
                found = piper.voices(refresh=True)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].name, "Piper en_GB-alba-medium")
        self.assertEqual(found[0].engine, "piper")
        self.assertEqual(found[0].culture, "en-GB")  # underscore normalised
        self.assertEqual(found[0].sample_rate, 22050)

    def test_a_missing_sample_rate_is_refused_rather_than_defaulted(self):
        import json as _json
        import tempfile

        from flow import piper

        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "x.onnx").write_bytes(b"")
            (Path(d) / "x.onnx.json").write_text(_json.dumps({"dataset": "x"}))
            with mock.patch("flow.piper._CACHE", None), \
                 mock.patch("flow.piper.VOICES_DIR", Path(d)), \
                 mock.patch("flow.piper.available", return_value=True):
                self.assertEqual(piper.voices(refresh=True), [])

    def test_gender_is_read_only_when_the_name_states_it(self):
        from flow.piper import _gender

        self.assertEqual(_gender("hfc_female", {}), "Female")
        self.assertEqual(_gender("northern_english_male", {}), "Male")
        # Not inferred from a first name, which is the whole rule.
        self.assertEqual(_gender("alba", {}), "NotSet")
        self.assertEqual(_gender("ryan", {}), "NotSet")
        # A sidecar that does state it is believed.
        self.assertEqual(_gender("alba", {"gender": "female"}), "Female")

    def test_rate_maps_onto_pipers_inverted_scale(self):
        from flow.piper import length_scale

        # SAPI's rate is higher-is-faster; Piper's length scale is lower-is-faster.
        self.assertLess(length_scale(5), length_scale(0))
        self.assertGreater(length_scale(-5), length_scale(0))
        self.assertAlmostEqual(length_scale(0), 1.0)
        # Clamped, so the extremes stay intelligible.
        self.assertGreaterEqual(length_scale(-100), 0.4)
        self.assertLessEqual(length_scale(100), 2.0)


class TestPiperSynthesis(unittest.TestCase):
    """The synthesise-to-speakers path, against a fake model and a fake device.

    Both halves are faked, for different reasons. The device because a test that plays
    audio needs one and CI has none. The model because `piper` is an *optional* extra, so
    these cases have to run on a machine that never installed it — which is most of them.
    `TestPiperReal` covers the real package when it happens to be present.

    What the fake pins is the contract this module actually depends on: `PiperVoice.load`
    returns something whose `synthesize` yields chunks carrying `audio_int16_bytes`. If a
    future Piper changes that, `TestPiperReal` fails while these still pass, and that
    split is what tells you it was the dependency rather than this file.
    """

    SAMPLES = 16000  # bytes, so 8000 frames — several passes of CHUNK_FRAMES

    class FakeChunk:
        def __init__(self, data):
            self.audio_int16_bytes = data
            self.sample_rate = 22050

    class FakeStream:
        def __init__(self, **kw):
            self.kw, self.written = kw, bytearray()
            self.aborted = self.closed = self.stopped = self.started = False

        def start(self):
            self.started = True

        def write(self, data):
            self.written.extend(data)

        def stop(self):
            self.stopped = True

        def abort(self):
            self.aborted = True

        def close(self):
            self.closed = True

    def _fake_piper(self, chunks=None, load_error=None, slow=0.0):
        """A stand-in `piper` module, injected into `sys.modules` for the duration."""
        test = self

        class FakeVoice:
            @staticmethod
            def load(path, *a, **kw):
                if slow:
                    time.sleep(slow)
                if load_error:
                    raise load_error
                return FakeVoice()

            def synthesize(self, text, cfg=None, **kw):
                for data in (chunks if chunks is not None else [b"\0" * test.SAMPLES]):
                    yield test.FakeChunk(data)

        mod = types.ModuleType("piper")
        mod.PiperVoice = FakeVoice
        mod.SynthesisConfig = lambda **kw: kw
        return mock.patch.dict(sys.modules, {"piper": mod})

    def _synth(self, rate=0):
        from flow.piper import Synth
        from flow.speak import Voice

        v = Voice("Piper test-medium", "NotSet", "en-GB", engine="piper",
                  path="/v/test.onnx", sample_rate=22050)
        return Synth(v, rate=rate)

    def _device(self, made):
        def factory(**kw):
            st = self.FakeStream(**kw)
            made.append(st)
            return st

        return mock.patch("sounddevice.RawOutputStream", side_effect=factory)

    def _drain(self, s, limit=20):
        deadline = time.monotonic() + limit
        while s.speaking and time.monotonic() < deadline:
            time.sleep(0.01)

    def test_it_plays_the_whole_utterance_and_then_stops_speaking(self):
        made = []
        # A load slow enough to observe, which is also the real first-utterance case:
        # 3.16 s was measured for the largest English model. Without the delay the fake
        # finishes inside `say()` and there is no window in which to check the gate.
        with self._fake_piper(slow=0.3):
            s = self._synth()
            try:
                with self._device(made):
                    self.assertTrue(s.say("hello there"))
                    # Gated *before* a sample is written — and before the model has even
                    # finished loading — or the reply's first syllable is transcribed as
                    # the user's. The invariant `Speaker.say` shares.
                    self.assertTrue(s.speaking)
                    self._drain(s)
                self.assertFalse(s.speaking, "speaking must clear when the audio ends")
                self.assertEqual(len(made), 1)
                self.assertEqual(len(made[0].written), self.SAMPLES)
                self.assertEqual(made[0].kw["samplerate"], 22050, "rate from the sidecar")
                self.assertEqual(made[0].kw["dtype"], "int16")
                # Drained, not aborted: this is the end of an answer, and clipping the
                # last word would sound like a fault.
                self.assertTrue(made[0].stopped)
                self.assertFalse(made[0].aborted)
            finally:
                s.close()

    def test_a_long_chunk_is_written_in_slices_so_stop_can_interrupt_it(self):
        # Piper emits a chunk per sentence, which for a long answer is seconds of audio.
        # One `write` per chunk would block until the device had taken all of it, so an
        # interruption would not be heard until that sentence finished.
        from flow.piper import CHUNK_FRAMES

        made = []
        with self._fake_piper(chunks=[b"\0" * (CHUNK_FRAMES * 2 * 5)]):
            s = self._synth()
            try:
                with self._device(made):
                    s.say("one long sentence")
                    self._drain(s)
                self.assertEqual(len(made[0].written), CHUNK_FRAMES * 2 * 5)
            finally:
                s.close()

    def test_stop_aborts_the_device_and_abandons_the_generator(self):
        made = []
        with self._fake_piper():
            s = self._synth()
            try:
                with self._device(made):
                    s.say("hello there")
                    self.assertTrue(s.stop())
                    self.assertFalse(s.speaking)
                    self._drain(s, limit=5)
                # `abort`, not `stop`: silence now rather than silence after the rest of
                # the sentence has played.
                if made:
                    self.assertTrue(made[0].aborted or made[0].closed)
            finally:
                s.close()

    def test_empty_text_is_silent_without_starting_anything(self):
        made = []
        with self._fake_piper():
            s = self._synth()
            try:
                with self._device(made):
                    self.assertFalse(s.say("   "))
                self.assertEqual(made, [])
                self.assertFalse(s.speaking)
            finally:
                s.close()

    def test_a_model_that_will_not_load_falls_silent_rather_than_raising(self):
        made = []
        with self._fake_piper(load_error=RuntimeError("corrupt model")):
            s = self._synth()
            try:
                s._loaded.wait(5)  # noqa: SLF001
                self.assertFalse(s.ready)
                with self._device(made):
                    # False, and no exception: a bad model must not take the session down
                    # or leave the microphone gated.
                    self.assertFalse(s.say("hello"))
                self.assertEqual(made, [])
                self.assertFalse(s.speaking)
            finally:
                s.close()

    def test_the_ceiling_releases_the_microphone_even_if_synthesis_never_ends(self):
        # The safety property `speak.Speaker.speaking` exists for, carried into the second
        # engine: a stalled synthesis must not latch `speaking` True, because the
        # microphone is gated on it and Flow would go permanently deaf.
        made = []
        with self._fake_piper(slow=30):
            s = self._synth()
            try:
                with self._device(made):
                    s.say("hello there")
                    self.assertTrue(s.speaking)
                    with s._lock:  # noqa: SLF001
                        s._deadline = time.monotonic() - 1  # noqa: SLF001
                    self.assertFalse(s.speaking)
            finally:
                s.close()


@unittest.skipUnless(_HAS_PIPER, "the piper extra is not installed")
class TestPiperReal(unittest.TestCase):
    """The real package, when this machine has it. Skipped everywhere else.

    Two things the fakes cannot check, and both are contracts with someone else's code:
    that `PiperVoice.synthesize` still yields chunks exposing `audio_int16_bytes`, and
    that `SynthesisConfig` still accepts `length_scale`. A break in either shows up here
    and nowhere else.

    No model is loaded, so this stays fast and works on a machine that installed the
    extra but never downloaded a voice.
    """

    def test_the_api_this_module_is_built_on_still_exists(self):
        import inspect

        from piper import PiperVoice, SynthesisConfig

        self.assertTrue(hasattr(PiperVoice, "load"))
        self.assertIn("length_scale", inspect.signature(SynthesisConfig).parameters)
        self.assertIn("text", inspect.signature(PiperVoice.synthesize).parameters)

    def test_available_agrees_with_the_import(self):
        from flow import piper

        self.assertTrue(piper.available())


class TestEdgeVoices(unittest.TestCase):
    """What the service returns, turned into rows a menu can show and `pick` can choose.

    No network: every case feeds `voices()` a canned service payload, because the ordering
    rules below are the whole point and they must not depend on what Microsoft published
    this morning.
    """

    #: Trimmed from the real payload, keeping only the fields this module reads.
    PAYLOAD = [
        {"ShortName": "en-US-AnaNeural", "Locale": "en-US", "Gender": "Female",
         "VoiceTag": {"ContentCategories": ["Cartoon", "Conversation"]}},
        {"ShortName": "en-US-AvaNeural", "Locale": "en-US", "Gender": "Female",
         "VoiceTag": {"ContentCategories": ["Conversation", "Copilot"]}},
        {"ShortName": "en-US-AvaMultilingualNeural", "Locale": "en-US", "Gender": "Female",
         "VoiceTag": {"ContentCategories": ["Conversation", "Copilot"]}},
        {"ShortName": "en-US-AriaNeural", "Locale": "en-US", "Gender": "Female",
         "VoiceTag": {"ContentCategories": ["News", "Novel"]}},
        {"ShortName": "en-GB-SoniaNeural", "Locale": "en-GB", "Gender": "Female",
         "VoiceTag": {"ContentCategories": ["General"]}},
        {"ShortName": "en-AU-NatashaNeural", "Locale": "en-AU", "Gender": "Female",
         "VoiceTag": {"ContentCategories": ["General"]}},
        {"ShortName": "fr-FR-DeniseNeural", "Locale": "fr-FR", "Gender": "Female",
         "VoiceTag": {"ContentCategories": ["General"]}},
    ]

    def _voices(self, locale="en-US"):
        from flow import edge

        with mock.patch("flow.edge._CACHE", None), \
             mock.patch("flow.edge.available", return_value=True), \
             mock.patch("flow.edge._cached", return_value=self.PAYLOAD), \
             mock.patch("flow.edge._system_locale", return_value=locale):
            return edge.voices(refresh=False)

    def test_only_english_is_offered(self):
        # 322 voices across every locale would make the menu useless, and Flow produces
        # English to read.
        self.assertNotIn("fr-FR", [v.culture for v in self._voices()])

    def test_a_cartoon_voice_is_never_what_an_unnamed_request_gets(self):
        # en-US-Ana is tagged Cartoon/Cute. Alphabetically it is first among the en-US
        # females, so plain name order handed it to anyone who typed `--voice female`.
        self.assertEqual(pick("female", self._voices()), "Natural en-US-AvaNeural")

    def test_conversational_voices_outrank_news_ones(self):
        names = [v.name for v in self._voices()]
        self.assertLess(names.index("Natural en-US-AvaNeural"),
                        names.index("Natural en-US-AriaNeural"))

    def test_plain_outranks_multilingual(self):
        # Both match `--voice ava`; en-US-AvaNeural is the one somebody means, and name
        # order alone returns the Multilingual variant, which is a different voice.
        self.assertEqual(pick("ava", self._voices()), "Natural en-US-AvaNeural")

    def test_the_machines_own_locale_comes_first(self):
        # Left in service order this was en-AU-Natasha: alphabetically first, Australian,
        # and handed to a user who asked only for "female".
        gb = [v.culture for v in self._voices(locale="en-GB")]
        self.assertEqual(gb[0], "en-GB")
        us = [v.culture for v in self._voices(locale="en-US")]
        self.assertEqual(us[0], "en-US")

    def test_a_locale_nobody_asked_for_is_ordered_last_not_dropped(self):
        cultures = [v.culture for v in self._voices()]
        self.assertIn("en-AU", cultures)
        self.assertEqual(cultures[-1], "en-AU")

    def test_gender_survives_the_trip(self):
        # Unlike Piper, the service states it — so `--voice female` works here.
        self.assertTrue(all(v.gender == "Female" for v in self._voices()))

    def test_no_extra_means_no_voices_and_no_network(self):
        from flow import edge

        with mock.patch("flow.edge._CACHE", None), \
             mock.patch("flow.edge.available", return_value=False), \
             mock.patch("flow.edge._fetch", side_effect=AssertionError("no network")):
            self.assertEqual(edge.voices(refresh=True), [])

    def test_rate_maps_onto_the_percentage_the_service_takes(self):
        from flow.edge import rate_percent

        self.assertEqual(rate_percent(0), "+0%")
        self.assertEqual(rate_percent(1), "+10%")
        self.assertEqual(rate_percent(-3), "-30%")
        # Clamped to what the service accepts.
        self.assertEqual(rate_percent(50), "+100%")
        self.assertEqual(rate_percent(-50), "-50%")


class TestEdgePadding(unittest.TestCase):
    """The crackle. A regression test for a bug that was found by ear, not by a test."""

    class FakeFrame:
        def __init__(self, samples, padding):
            self.samples = samples
            # Real samples are 0x11; the padding after them is 0xFF, standing in for
            # whatever the allocator last left in the buffer.
            self.planes = [b"\x11" * (samples * 2) + b"\xff" * padding]

    def test_the_padding_after_the_samples_is_not_played(self):
        from flow.edge import pcm

        # The measured shape: 576 samples in a 1216-byte plane, so 64 bytes of noise
        # spliced into the speech every 1152 bytes, on every frame of the reply.
        out = pcm(self.FakeFrame(576, 64))
        self.assertEqual(len(out), 1152)
        self.assertNotIn(b"\xff", out)

    def test_an_unpadded_frame_is_unchanged(self):
        from flow.edge import pcm

        self.assertEqual(len(pcm(self.FakeFrame(576, 0))), 1152)


class TestLegacyVoicesAreHidden(unittest.TestCase):
    """The 2013 voices stay reachable by name after they stop being offered."""

    SAPI = [Voice("Microsoft George", "Male", "en-GB"),
            Voice("Microsoft Zira", "Female", "en-US")]
    PIPER = [Voice("Piper en_GB-cori-high", "NotSet", "en-GB", engine="piper",
                   path="/v/c.onnx", sample_rate=22050)]

    @contextlib.contextmanager
    def _machine(self, piper_voices=(), edge_voices=()):
        """A machine with these engines installed, and both caches cleared."""
        with contextlib.ExitStack() as stack:
            for patch in (
                mock.patch("flow.speak._CACHE", None),
                mock.patch("flow.speak._ALL", None),
                mock.patch("flow.piper.voices", return_value=list(piper_voices)),
                mock.patch("flow.edge.voices", return_value=list(edge_voices)),
                mock.patch("flow.speak._sapi_voices", return_value=self.SAPI),
            ):
                stack.enter_context(patch)
            yield

    def test_windows_voices_are_offered_when_nothing_better_exists(self):
        # The default install: three declared dependencies, neither extra. Removing SAPI
        # unconditionally would leave it with no spoken replies at all.
        from flow.speak import installed_voices

        with self._machine():
            self.assertEqual(installed_voices(refresh=True), self.SAPI)

    def test_they_disappear_once_a_better_engine_has_one(self):
        from flow.speak import installed_voices

        with self._machine(piper_voices=self.PIPER):
            offered = installed_voices(refresh=True)
        self.assertEqual([v.name for v in offered], ["Piper en_GB-cori-high"])

    def test_a_hidden_voice_is_still_reachable_by_name(self):
        # Hidden from the menu is not withdrawn: a profile written last month, or a
        # `--voice george` typed from habit, must still resolve to the voice it names.
        from flow.speak import all_voices, pick

        with self._machine(piper_voices=self.PIPER):
            self.assertEqual(pick("george"), "Microsoft George")
            self.assertIn("Microsoft George", [v.name for v in all_voices()])


class TestHost(unittest.TestCase):
    """*Which* host is chosen. That it arrives as a path is `test_speak.py`'s question.

    These three asserted the bare name until 2026-08-03, when SPEECH-04 made `host()`
    keep what the lookup returned. The preference order they pin has not moved at all —
    only what a chosen host is spelled as, which is why the edit is to the expectation
    and not to the case.
    """

    def test_the_modern_shell_is_preferred(self):
        with mock.patch("flow.speak.shutil.which", side_effect=lambda n: f"/x/{n}"), \
             mock.patch("flow.speak._HOST", None):
            self.assertEqual(host(), "/x/pwsh")

    def test_it_falls_back_to_the_one_every_windows_has(self):
        with mock.patch("flow.speak.shutil.which",
                        side_effect=lambda n: None if n == "pwsh" else "/x/powershell"), \
             mock.patch("flow.speak._HOST", None):
            self.assertEqual(host(), "/x/powershell")

    @unittest.skipUnless(sys.platform == "win32", "Windows-only: the PowerShell speech host")
    def test_with_neither_found_it_still_returns_something_runnable(self):
        # Guessing beats raising: `Speaker` already degrades to silent when the host
        # will not start, and `which` failing is not proof the shell is absent. What the
        # guess *is* changed with SPEECH-04 — `HOSTS[-1]` was a name, and a name reaching
        # `Popen` is resolved by a search that reads the current directory first, so the
        # branch that existed to be safe was the last one that was not.
        with mock.patch("flow.speak.shutil.which", return_value=None), \
             mock.patch("flow.speak._HOST", None):
            found = host()
        self.assertTrue(found.lower().endswith(f"{HOSTS[-1]}.exe"), found)
        self.assertNotEqual(found, HOSTS[-1], "a bare name is what CreateProcess searches")


class TestEnumeration(unittest.TestCase):
    """`installed_voices` parses the host's output, and must not trust it."""

    def _voices(self, stdout):
        # Every other engine is stubbed out, not left to answer for itself. These cases
        # are about parsing what PowerShell printed, and `installed_voices` concatenates
        # all three — so without this they assert "the SAPI parse plus whatever this
        # developer happens to have installed", and pass or fail by machine. They did
        # exactly that twice: once when the dev box grew two Piper voices, and again when
        # it grew forty-seven natural ones.
        #
        # `_ALL` as well as `_CACHE`, because the offered list is now derived from the
        # full one and a stale full list would survive the refresh.
        with mock.patch("flow.speak._CACHE", None), \
             mock.patch("flow.speak._ALL", None), \
             mock.patch("flow.piper.voices", return_value=[]), \
             mock.patch("flow.edge.voices", return_value=[]), \
             mock.patch("flow.speak.subprocess.run") as run:
            run.return_value = mock.Mock(stdout=stdout)
            from flow.speak import installed_voices

            return installed_voices(refresh=True)

    def test_it_reads_the_marked_lines(self):
        out = (f"{VOICE_PREFIX}Microsoft Mark|Male|en-US\n"
               f"{VOICE_PREFIX}Microsoft Zira|Female|en-US\n")
        self.assertEqual(
            self._voices(out),
            [Voice("Microsoft Mark", "Male", "en-US"),
             Voice("Microsoft Zira", "Female", "en-US")],
        )

    def test_unmarked_output_is_ignored(self):
        # PowerShell prints things nobody asked for — a profile banner, a warning about
        # an execution policy. None of them are voices.
        out = ("WARNING: something\n"
               f"{VOICE_PREFIX}Microsoft Mark|Male|en-US\n"
               "PS D:\\> \n")
        self.assertEqual(self._voices(out), [Voice("Microsoft Mark", "Male", "en-US")])

    def test_a_malformed_line_is_dropped_rather_than_half_read(self):
        out = (f"{VOICE_PREFIX}broken\n"
               f"{VOICE_PREFIX}|Male|en-US\n"
               f"{VOICE_PREFIX}Microsoft Mark|Male|en-US\n")
        self.assertEqual(self._voices(out), [Voice("Microsoft Mark", "Male", "en-US")])

    def test_no_engine_is_an_empty_list_and_not_a_crash(self):
        # "No engine" means none of the three: no PowerShell to enumerate SAPI, no Piper
        # and no network voices. With any one still answering this asserts the wrong thing.
        with mock.patch("flow.speak._CACHE", None), \
             mock.patch("flow.speak._ALL", None), \
             mock.patch("flow.piper.voices", return_value=[]), \
             mock.patch("flow.edge.voices", return_value=[]), \
             mock.patch("flow.speak.subprocess.run", side_effect=OSError("no shell")):
            from flow.speak import installed_voices

            self.assertEqual(installed_voices(refresh=True), [])


class TestProfileRemembersTheVoice(unittest.TestCase):
    def test_it_survives_a_round_trip(self):
        import tempfile

        from flow.profile import Profile

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "profile.json"
            p = Profile(path)
            p.voice = "Microsoft Mark"
            self.assertTrue(p.save())
            self.assertEqual(Profile(path).voice, "Microsoft Mark")

    def test_a_profile_written_before_voices_existed_still_loads(self):
        # Additive, so no schema bump: an older file has no `voice` key and has to load
        # as "no opinion" rather than refusing and resetting someone's calibration.
        import json
        import tempfile

        from flow.profile import SCHEMA, Profile

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "profile.json"
            path.write_text(json.dumps({"schema": SCHEMA, "floor_db": -96.5}))
            p = Profile(path)
            self.assertIsNone(p.voice)
            self.assertEqual(p.floor_db, -96.5)


if __name__ == "__main__":
    unittest.main()
