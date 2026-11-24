# Flow's models on 2026-11-23: what it runs, what changed upstream, what is better

The brief was to identify every model Flow uses, find what has changed in each since it
was chosen, and research whether anything released since gives a better result. The
owner's example was NVIDIA's
[parakeet-tdt-0.6b-v2](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2).

This is the record of what was read and what was measured. No code in Flow was changed
by it. Every outside figure was read on 2026-11-23 from the page linked beside it; where a
number is the maker's own claim it says "vendor", and where it comes from the Hugging
Face Open ASR Leaderboard (v1.16.2, 2026-11-20) it says "leaderboard". Word error rates
from different test sets do not compare, so no table mixes them.

## The finding in one paragraph

Flow's speech model stays, and none of its pins has been superseded by its own maker,
with one exception that is a bug. **Parakeet v2 is older than the v3 Flow ships, not
newer**: it is English-only, a little better on English in published figures, and
**worse on Flow's own clips (15.5 errors per 100 words against 14.5)**. The two newer
fine-tunes of v3, Moondream's parakeet-ultra and Fluid Speech Pro, which the leaderboard
puts at 6.06 against v3's 7.04, **measured 14.8 and 14.4 here: no difference the
benchmark can see**. Which model answers a rewrite makes no measurable difference to the
wait or to the facts kept. And **the Microsoft voices add-on is pinned to a version of
`edge-tts` that Microsoft's service has refused since about 10 October**.

## What Flow runs

| Job | Model | Where it comes from, and the pin | Flow's own measurement |
|:---|:---|:---|:---|
| Dictation on a GPU (the default with one) | NVIDIA Parakeet TDT 0.6B v3, q8_0 | `mudler/parakeet-cpp-gguf` at `741158ae…`, run by `mudler/parakeet.cpp` v0.6.1 | 14.5 errors per 100 words |
| Dictation on a CPU (add-on) | Parakeet TDT 0.6B v3, fp32 and int8 | `istupakov/parakeet-tdt-0.6b-v3-onnx` at `8f23f0c0…`, through `onnx-asr` 0.12.0 | 14.7 and 16.9 |
| Dictation, default install | Whisper `small.en`, with `base.en` for the live preview | `Systran/faster-whisper-*`, pinned commits, `faster-whisper` 1.2.1 on `ctranslate2` 4.8.1 | 19.5 |
| Whisper on a GPU, and Hindi | Whisper `large-v3`, with `small` for the preview | same | 16.8 |
| Spoken replies | The Windows built-in voices | `System.Speech`, nothing installed | not measured |
| Spoken replies, local add-on | Piper, eight English voices | `rhasspy/piper-voices` at tag `v1.0.0`, `piper-tts` 1.8.0 | 0.13 to 0.22 s to first sound |
| Spoken replies, online add-on | Microsoft natural voices | `edge-tts` 7.2.8 | not measured |
| Refine and Ask | Whatever the agent CLI defaults to | none; Flow sends effort `low` | below |

The error figures are Flow's own 300 clips of accented English (EdAcc), scored by
`scripts/accent_bench.py`. Speech detection is Flow's own level gate, not a model.

## Measured here on 2026-11-23

**The shipped speech model, again.** `scripts/parakeet_bench.py gpu` on a GTX 1070, the
same clips and scorer as 2026-10-05, now on parakeet.cpp v0.6.1:

| | 2026-10-05 | 2026-11-23 |
|:---|---:|---:|
| Errors per 100 words | 14.5 | 14.5 |
| Median time per clip | 107 ms | 90 ms |
| 95th percentile | 229 ms | 189 ms |
| Words invented on 8 silent or noisy clips | 0 | 0 |

Per group: Indian 15.5, Japanese 20.2, Russian 9.3, Spanish 13.1, US 16.5. This is the
baseline any candidate has to beat. Result file:
`.bench/accent/results-parakeet-gpu-cuda-2026-11-23-baseline.json`.

**Three candidates against it.** The owner approved the downloads. Each file was fetched
at a named commit into a folder outside Flow's own, and its size and SHA-256 matched
what Hugging Face lists. Each was then run exactly as the shipped model is: the same
parakeet.cpp v0.6.1 CUDA helper, greedy decoding, the same 300 clips and scorer. Only the
weights differed. The shipped model was run through the same route first, as a control,
and scored the baseline's figures group for group.

| Model | Errors per 100 words | Against the control | 95% interval | Clips better / worse | Median, 95th percentile |
|:---|---:|---:|:---:|:---:|:---|
| Parakeet v3 q8_0 (shipped), control | 14.55 | | | | 86 ms, 177 ms |
| The same again, four minutes later | 14.59 | +0.04 | | 0 / 1 | 82 ms, 164 ms |
| Parakeet v2 q8_0 | **15.54** | +0.99 | +0.10 to +1.86 | 61 / 86 | 86 ms, 172 ms |
| parakeet-ultra q8_0 | 14.76 | +0.21 | −0.40 to +0.84 | 40 / 52 | 83 ms, 168 ms |
| Fluid Speech Pro q8_0 | 14.35 | −0.19 | −0.91 to +0.50 | 45 / 48 | 90 ms, 182 ms |

| Errors per 100 words, by group | Indian | Japanese | Russian | Spanish | US |
|:---|---:|---:|---:|---:|---:|
| Parakeet v3 (shipped) | 15.5 | 20.2 | 9.3 | 13.1 | 16.5 |
| Parakeet v2 | 16.4 | 19.9 | 11.6 | 14.0 | 17.2 |
| parakeet-ultra | 15.8 | 20.1 | 9.7 | 12.8 | 17.2 |
| Fluid Speech Pro | 16.3 | 19.2 | 9.7 | 12.1 | 16.3 |

The interval is a paired bootstrap: the same 300 clips resampled 20,000 times, each
candidate against the control clip for clip. An interval that includes zero means the
benchmark cannot tell the two apart.

- **Parakeet v2 is worse here**, by a point, and the interval excludes zero. It lost on
  four of the five groups, the US speakers included, and returned nothing at all for one
  clip. The published English figures pointed the other way.
- **parakeet-ultra and Fluid Speech Pro are level with v3.** Fluid Speech Pro made 740
  errors in 5,155 words against 750, and was better on 45 clips and worse on 48. Its
  lead of a point on the leaderboard does not appear on these clips with this decoder.
- **None invented a word** on the eight silent or noisy clips.
- **Speed is the same.** All five runs had medians between 82 and 90 ms and loaded in
  about a second. The first control, v2 and Fluid Speech Pro were run while a download
  was in progress; the second control and parakeet-ultra were not.
- **The shipped model is not perfectly repeatable**: its second run differed from the
  first by two errors on one clip. That is the floor under every difference above.
- **The fine-tunes report higher word confidence.** Flow drops a dictation as invented
  when its mean word confidence is under 0.45 (`clean.WORD_CONF_MIN`). Two of v3's 300
  clips fall under that bar, one of v2's and none of either fine-tune's; the first
  percentile is 0.52 for v3, 0.59 for parakeet-ultra and 0.64 for Fluid Speech Pro. A
  swap would move what that bar catches, and the bar would have to be measured again.

The benchmark also holds four recorded sentences of technical dictation, three of one
sentence in different noise and one of another. They are too few to score and are
reported as heard. "PKCE" came out right in one of three for v3, two of three for
parakeet-ultra and three of three for Fluid Speech Pro. "Priya" came out right for v3
and v2, and as "Pria" and "Bria" for the two fine-tunes.

**So nothing changes.** The bar was a clear win over 14.5 with no inventions and no cost
in speed, and no candidate cleared it. The decision and what would reopen it are in
`docs/decisions.md` under 2026-11-23. Result files:
`.bench/accent/results-parakeet-gpu-cuda-2026-11-23-{v3-control,v3-control-2,v2,ultra,fluid-speech-pro}.json`.

| File measured | Repository and commit | Bytes | SHA-256 |
|:---|:---|---:|:---|
| `tdt-0.6b-v2-q8_0.gguf` | `mudler/parakeet-cpp-gguf` at `07a08a3a…` | 903,835,936 | `2027e2e1…8119c6` |
| `ultra-q8_0.gguf` | the same | 941,517,728 | `c2fb452a…50986a` |
| `fluid-speech-pro-q8_0.gguf` | `FluidVoice-Labs/fluid-speech-pro-gguf` at `fee970d9…` | 940,663,968 | `1b9c613f…dc5ffd` |

**Which model answers a rewrite.** The five dictations of `scripts/polish_check.py`,
through `flow.refine.refine` as Flow calls it, effort `low`, one run each:

| CLI and model | Median | Range | Details kept | Length against the dictation |
|:---|---:|:---|:---:|---:|
| codex, `gpt-6.2-astra` (the configured default) | 6.3 s | 5.6 to 13.8 s | 15/15 | 1.0× |
| codex, `gpt-6.2-sol` | 5.5 s | 5.0 to 6.8 s | 15/15 | 1.1× |
| codex, `gpt-6.1-terra` | 5.5 s | 4.5 to 7.3 s | 15/15 | 1.0× |
| claude, default (`claude-opus-5-5`) | 6.0 s | 5.8 to 6.6 s | 15/15 | 1.1× |
| claude, `sonnet` | 4.8 s | 4.5 to 6.4 s | 15/15 | 1.7× |
| claude, `haiku` | 5.3 s | 4.2 to 6.3 s | 15/15 | 1.6× |

Every model kept every version number, path and name, put the request on the first line
and added no preamble. The spread between models is about a second, and the two quicker
ones write about 60% more. A one-word `claude` call took 3.6 s end to end with 1.8 s of
it on the model's side, so about half of every wait is the CLI starting, not the model
thinking. The check does not judge which rewrite reads better, and the 13.8 s call was
not explained.

## Parakeet v2 against v3

From NVIDIA's own cards
([v2](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2),
[v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3)):

| | v2 | v3 (what Flow ships) |
|:---|:---|:---|
| Released | 1 May 2025 | 14 August 2025 |
| Languages | English | 25 European languages, English included |
| Training audio | about 120,000 hours of English | about 670,000 hours |
| Size and design | 600 million parameters, FastConformer-TDT | the same |
| Licence | CC-BY-4.0 | CC-BY-4.0 |

v2's own card now points readers to v3. On English, v2 is slightly ahead:

| English word error rate, lower is better | v2 | v3 |
|:---|---:|---:|
| Vendor, average of the cards' eight test sets | 6.05 | 6.34 |
| Leaderboard, average of its nine current sets | 6.93 | 7.04 |
| Leaderboard, Indian English (Voice Arena Monsoon) | 3.89 | 4.14 |
| Leaderboard, private non-US accents | 9.33 | 9.75 |
| Leaderboard, private US accents | 9.48 | 9.22 |

v3 wins on some sets (GigaSpeech, TED-LIUM, VoxPopuli) and loses badly on one (SPGISpeech,
3.97 against 2.17 on the cards). Both sources that isolate accented English lean to v2,
by a quarter to half a point. Flow's own clips went the other way: v2 measured a point
worse than v3 (above). Switching would also give up 24 languages.

Builds for both of Flow's runtimes exist: `tdt-0.6b-v2-q8_0.gguf` (903,835,936 bytes) in
the same [`mudler/parakeet-cpp-gguf`](https://huggingface.co/mudler/parakeet-cpp-gguf)
repository Flow already downloads from, present at the pinned commit, and
[`istupakov/parakeet-tdt-0.6b-v2-onnx`](https://huggingface.co/istupakov/parakeet-tdt-0.6b-v2-onnx)
for the CPU.

## What else exists

Candidates that could run under Flow's constraints (local, no PyTorch, a permissive
licence, an 8 GB GTX 1070 or a CPU):

| Model | Maker, date | Languages | Licence | Leaderboard average | Vendor claim | Build Flow could run |
|:---|:---|:---|:---|---:|:---|:---|
| parakeet-tdt-0.6b-v3 (in use) | NVIDIA, 2025-08 | 25 | CC-BY-4.0 | 7.04 | 6.34, eight sets | in use |
| parakeet-tdt-0.6b-v2 | NVIDIA, 2025-05 | English | CC-BY-4.0 | 6.93 | 6.05, eight sets | GGUF in the pinned repository; ONNX |
| [fluid-speech-pro](https://huggingface.co/FluidVoice-Labs/fluid-speech-pro) | FluidVoice Labs, 2026-10-30 | 25 | CC-BY-4.0 | **6.06** | the same figure, decoded with four beams | [own GGUF repository](https://huggingface.co/FluidVoice-Labs/fluid-speech-pro-gguf), [own ONNX repository](https://huggingface.co/FluidVoice-Labs/fluid-speech-pro-onnx) |
| [parakeet-ultra](https://huggingface.co/moondream/parakeet-ultra) | Moondream, 2026-09 | 25 | CC-BY-4.0 | not listed | 5.80 against 6.26 for v3, seven sets | `ultra-q8_0.gguf` in the pinned repository, supported since parakeet.cpp v0.6.0 |
| [nemotron-labs-unified-asr-0.6b](https://huggingface.co/nvidia/nemotron-labs-unified-asr-0.6b) | NVIDIA, 2026-10 | 25 | OpenMDW-1.1 | not listed | 4.68 against 4.93 for v3, seven cleaned sets | GGUF, but only on parakeet.cpp's unreleased master |
| [parakeet-unified-en-0.6b](https://huggingface.co/nvidia/parakeet-unified-en-0.6b) | NVIDIA, 2026-04 | English | NVIDIA Open Model License | not listed | 5.91 against 6.04 for v2, eight sets | sherpa-onnx only |

Fluid Speech Pro is a fine-tune of v3 by way of Moondream's parakeet-ultra. On the
leaderboard's accent sets it is ahead of both NVIDIA models: Indian English 3.71, private
non-US accents 8.90, private US 8.86. Three cautions: its leaderboard run used four-beam
decoding where Flow decodes greedily (its card puts the beam's benefit at about 0.6%
fewer errors); its GGUF leaves out one small block the card says matters most for noisy speech;
and its publisher is one Flow has not downloaded from before. Measured on Flow's clips
with Flow's helper, it is level with v3 (above).

Of the 20 open-weight models the leaderboard ranks above v3, only Fluid Speech Pro and
Parakeet v2 can run under Flow's constraints as things stand. The rest are out for a
stated reason: two billion parameters or more with a language-model decoder (Qwen3-ASR
1.7B, Granite Speech 2B, Canary-Qwen 2.5B, Cohere Transcribe and others), a
non-commercial or unread licence (Granite `-nc`, Kroko), or no runtime without PyTorch
(Rumble-2-Flash, ARK-ASR). Five cloud services rank above every open model. OpenAI has
published no new open speech weights; Whisper `large-v3` and `large-v3-turbo` sit at 8.24
and 8.75.

NVIDIA has released no Parakeet v4. Its newer models are "unified" ones that do offline
and streaming transcription from one checkpoint, which speaks to Flow using one model for
both partials and finals; their gains are vendor-reported only and neither is on the
leaderboard. Its Nemotron 3.5 streaming model is the only small NVIDIA model that covers
Hindi, and it is far behind v3 on English (11.09).

## What changed upstream since each pin

| Pin | State on 2026-11-23 |
|:---|:---|
| `mudler/parakeet.cpp` v0.6.1 | Still the [latest release](https://github.com/mudler/parakeet.cpp/releases) (2026-10-07). Seven unreleased commits add two new model families. No vocabulary biasing. |
| `mudler/parakeet-cpp-gguf` at `741158ae…` | Nine commits later; Flow's file is unchanged at 940,663,680 bytes. New files are for other models. |
| `istupakov/parakeet-tdt-0.6b-v3-onnx` at `8f23f0c0…` | No change; the pinned commit is still the head. |
| `onnx-asr` 0.12.0 | Still the [latest](https://pypi.org/project/onnx-asr/). Greedy decoding only. |
| `faster-whisper` 1.2.1 | Still the [latest](https://pypi.org/project/faster-whisper/) (2025-10-31). No new Whisper conversions from Systran. |
| `ctranslate2` 4.8.1 | Six [releases](https://github.com/OpenNMT/CTranslate2/releases) later, at 4.9.1 (2026-11-22). They fix memory-safety and CUDA precision bugs and make flash attention effective for the Whisper encoder. None says whether the CUDA 12 wheels still cover a Pascal card. |
| `onnxruntime` 1.28.0 | 1.32.0 is out; the notes between were not read. |
| `piper-tts` 1.8.0 | Still the [latest](https://pypi.org/project/piper-tts/). GPL-3.0-or-later, as every version from 1.3.0. |
| `rhasspy/piper-voices` at `v1.0.0` | The tag still serves the files Flow's checksums expect. On `main`, voices are being retrained in place since 2026-11-09 and three of Flow's eight now differ. |
| `edge-tts` 7.2.8 | **Refused by the service.** See below. |

One statement to keep an eye on: parakeet.cpp's README says its CUDA release binaries
target Turing cards and newer. The v0.6.1 CUDA build runs on this GTX 1070, which is
older, and produced the baseline above.

**Custom vocabulary on Parakeet** is still missing from both runtimes Flow uses. The only
route found without PyTorch is a fourth runtime,
[sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx/pull/3077), which added hotwords for
NeMo transducers including TDT in February 2026. It needs beam search, and a later
contributor reported the offline decoder double-counting the boost, so it would have to
be measured against greedy decoding before it could be trusted.

## Voices

**`edge-tts` 7.2.8 no longer works.** Flow pins it in `flow/home/voicepacks.py`.
Microsoft made a new token mandatory around 10 October 2026 and version 7.2.8 fails the
handshake with HTTP 403 ([issue 490](https://github.com/rany2/edge-tts/issues/490), 48
comments). The fix is in [7.3.0](https://github.com/rany2/edge-tts/releases) of
2026-10-13; 7.3.1 is the latest. Users report slower and sometimes empty responses after
the fix. Not reproduced here, because a test sends text to Microsoft.

**Piper.** The original `rhasspy/piper` repository is archived; the engine continues at
[`OHF-Voice/piper1-gpl`](https://github.com/OHF-Voice/piper1-gpl) under GPL-3.0-or-later.
Flow is MIT, imports Piper in its own process, and does not ship it: the user installs it
as an add-on. Piper's own
[licensing note](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/LICENSING.md)
(new since 2026-11-09) says the engine's licence does not cover the voices, and that a
voice's rights come from its training data. By that reading, at the tag Flow pins:

| Voice | Training data, per its model card | Clean for any use? |
|:---|:---|:---|
| en_GB-cori-high | LibriVox, public domain, trained from scratch | Yes |
| en_US-lessac-high | Blizzard 2013 Lessac, described by Piper as research-only | No |
| en_US-ryan-high | RyanSpeech, CC BY-NC-SA | No |
| en_GB-alan-medium | Mycroft, all rights reserved; fine-tuned from lessac | No |
| en_GB-jenny_dioco-medium | Jenny (Dioco), commercial use allowed with credit; fine-tuned from lessac | Only the copy retrained on `main` |
| en_GB-northern_english_male-medium | OpenSLR 83, CC BY-SA; fine-tuned from lessac | Only the copy retrained on `main` |
| en_US-amy-medium | Mycroft, no documented licence | No |
| en_US-hfc_male-medium | Hi-Fi-CAPTAIN, CC BY-NC-SA; fine-tuned from lessac | No |

Flow offers these for download and does not ship them, and it downloads the voice and its
config but not the model card that states the terms. What this means for Flow is the
owner's call, and a lawyer's if it matters; this note only reports what the documents say.

**The Windows natural voices** still have no public interface for other programs in any
Microsoft document found; the [Windows AI APIs](https://learn.microsoft.com/en-us/windows/ai/apis/)
list (2026-11-18) has no speech synthesis.

**Newer local voices.** Two are worth hearing:

| | Phonon 31m English | Kokoro-82M v1.0 (ONNX) |
|:---|:---|:---|
| Maker, date | Gradium, 2026-10-20 | hexgrad, 2025-01 |
| Download | about 71 MB with its runtime | 114 to 326 MB plus 28 MB of voices |
| Licence | weights Apache-2.0; runtime `ptts` MIT or Apache-2.0 | weights Apache-2.0; its phonemizer is GPL-3.0 |
| Needs | numpy only | ONNX Runtime |
| Time to first sound, 8 virtual CPUs ([Open TTS Leaderboard](https://huggingface.co/spaces/hf-audio/open_tts_leaderboard)) | 19.5 ms median, streams | 852 ms median, does not stream |
| Listener preference ([Artificial Analysis](https://artificialanalysis.ai/text-to-speech/leaderboard)) | Elo 1108 | Elo 1060 |
| Objective rank, same leaderboard, 49 models | 12th | 1st |

[Phonon 31m](https://huggingface.co/gradium/phonon-31m-en) is the only candidate that
meets every constraint on paper, including a licence chain with no GPL in it. It is one
month old, its runtime has had seven releases in that month, its x86 build needs AVX2,
and its card does not say what it was trained on. It is not related to the Phonon speech
recognition models from a different maker. Kokoro has the stronger quality record and is
too slow to start as measured.

## What follows from this

1. **Keep Parakeet v3.** Parakeet v2, parakeet-ultra and Fluid Speech Pro were measured
   on Flow's own clips the same day and none clearly beat 14.5. Look again when the
   helper can decode with a beam or take a vocabulary, or when a model is published that
   is not a fine-tune of v3.
2. **Move the `edge-tts` pin to 7.3.1**, after one test call confirms 7.2.8 is refused.
3. **Decide what the Piper catalogue should offer** in light of the voice terms above.
4. **Leave the rewrite model alone.** There is no faster or more faithful choice to make.
5. **Hear Phonon 31m against Piper** if a better local voice is wanted; it would be a new
   add-on, installed from a publisher Flow has not used before.

## Could not verify

- Speed of any candidate on a desktop CPU, and of the candidates that were not measured
  on the GTX 1070. The three that were measured are as fast as v3 there.
- Whether Fluid Speech Pro does better with the four-beam decoding its published figure
  used. Flow's helper, `parakeet-server`, decodes greedily and has no beam option. Its
  GGUF does load and run in parakeet.cpp v0.6.1, which its card left open.
- Whether any of these models is better at technical dictation: names of tools, flags,
  version numbers. Flow's 300 clips are conversation, and its four technical sentences
  are too few to score.
- Whether the candidates are better or worse than v3 in the other 24 languages. Only
  English was measured.
- Whether `edge-tts` 7.2.8 fails on this network today. Taken from upstream reports.
- The leaderboard's results dataset is private; its numbers were read from the page's own
  data, and the three rows quoted most here were checked against that capture.
- That the Windows natural voices are unreachable: no Microsoft page says so outright.
- The wording of several licences named here and not read: OpenMDW-1.1, the NVIDIA Open
  Model License, Blizzard 2013, the Kroko community licence.
- Phonon 31m's training data, and its speed on a Windows x86 PC.
- Whether sherpa-onnx's offline hotword decoder has had its reported faults fixed.
