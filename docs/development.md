# Developing Flow

How the source is laid out, how it is tested, and how a distributable is built.
[docs/architecture.md](architecture.md) is the runtime reference underneath this —
data flow, threads, the event stream and the tuning constants with their measurements.

## Layout

```
flow/
  __main__.py  entry point: parses flags, prints diagnostics, wires the pieces together
  session.py   state machine, threaded decoder, draft + undo, mode, rescue, learning
  edits.py     edit-vs-append routing, verb snapping, and the local string operations
  phonetic.py  vendored Double Metaphone + the span search the router and edits share
  refine.py    agent-CLI adapter: semantic rewrite, prompt polish (P5), converse ask (P9)
  asr.py       faster-whisper in two tiers, behind a two-method interface
  clean.py     rejecting text the model invented rather than heard, with the evidence
  audio.py     mic capture and the speech gate (RMS, adaptive floor, pre-roll)
  calibrate.py first-run measurement of this room and this voice (P8)
  profile.py   what Flow learned about one person, stored locally (P8/P4)
  lexicon.py   the user's own terms and declared corrections, re-read on change
  thread.py    what has already been sent, bounded (P6)
  speak.py     spoken replies through one long-lived System.Speech host (P9)
  ui.py        the pill, the draft bubble and the hand editor (tkinter), DPI-aware
  inject.py    clipboard + SendInput, and terminal-safe paste (ctypes, P7)
  hotkey.py    RegisterHotKey on its own message-loop thread (ctypes)
  diag.py      the wordless trace, and the identity block every benchmark records
scripts/       benchmarks, probes, the soak test and the self-drive harness
tests/         1,591 tests: routing, state machine, filters, phonetics, resilience
docs/          what Flow is for, the roadmap, the analysis, the recording kit
```

`tkinter` and `ctypes` are stdlib, which is how the GUI, global hotkeys, text injection,
DPI awareness and speech synthesis all cost zero dependencies.

See [docs/architecture.md](architecture.md) for the runtime data flow, the threads,
the event stream and the tuning constants with the measurements behind them.

## Development

```bash
uv run python -m unittest discover -s tests
```

1,591 tests, ~45 s, no microphone or model required — the fakes are injectable precisely so
the routing logic, where the subtle bugs live, can be tested without either.

The end-to-end harness is the one that catches what unit tests cannot:

```bash
uv run python scripts/selfdrive.py
```

A Windows SAPI voice speaks each utterance to a WAV; the WAV is fed to a real `Session` as
microphone blocks, through the real gate, the real two-tier decoder, the real router and
the real apply. 64 checks covering dictation, five correction shapes, undo, rescue, send,
converse against the live CLI, a spoken follow-up, the asking-state UI, calibration, the
learning loop, window placement and the chips. It found two real defects on its first
outings, both of which every layer-specific harness had missed.

There is one thing it cannot see, and it is the one that mattered most. It clicks chips
with `event_generate`, which hands Tk an event without Windows ever being involved — so
its clicks cannot move the focus, and for the whole life of the project it stayed green
while a *real* click on Send pasted into nothing at all. That needs a real mouse:

```bash
uv run python scripts/send_check.py --live
```

It opens an ordinary window and a console, clicks Send where the chip is actually drawn,
and reads back what arrived in each. Before the fix: 6 of 12 checks, nothing delivered
anywhere, and Send reporting success. After: 18 of 18.

### The scripts

| Script | What it answers |
|---|---|
| `devices.py` | which input devices exist, by index |
| `mic_check.py` | does the real capture path deliver blocks |
| `listen.py` | headless partials-while-speaking, held draft on stop |
| `live_check.py` | a person, a real microphone, this loop — the guided session |
| `selfdrive.py` | does the whole app work, driven by synthesised speech |
| `soak.py` | does a long session drift in memory or latency (R8) |
| `accent_bench.py` | per-accent WER and false-reject rate (P1/P2) |
| `asr_bench.py` | decode latency, and the R4 partial-latency gate |
| `command_bench.py` | does the hardened grammar catch more commands without eating dictation (P3) |
| `rescue_bench.py` | does a biased second decode recover a mis-heard command |
| `lexicon_bench.py` | does biasing actually recover words, and what does it cost (P4) |
| `gate_bench.py` | how much speech does the gate eat, and does pre-roll get it back |
| `guardrail_bench.py` | where a confidence bar on destructive edits would land |
| `hallucination_probe.py` | what the model emits when there is nothing to transcribe |
| `polish_check.py` | does the polish verb keep the facts, and does it fit the budget (P5) |
| `refine_check.py` | end-to-end check of the CLI refine path |
| `inject_check.py` | clipboard and paste-target classification, without side effects |
| `send_check.py` | do the words a pressed Send hands over actually arrive — `--live` opens a window and a console and clicks the chip with the real mouse |
| `fetch_accent_data.py` | pull per-accent evaluation slices into `.bench/` |
| `ingest_recordings.py` | turn a volunteer's phone recording into scored clips (P3) |
| `voices.py` | which voices this machine has, and what each one sounds like — `--speak` says a line in each, `--wav` writes them |
| `tk_probe.py` | the window attributes the pill depends on |
| `ui_probe.py` | render the pill and bubble against a fake session that walks every state — `--hold STATE` pins one, `--bare` drops the draft, `--sent` presses Send so the card it leaves behind can be looked at |
| `slim.py` | trim the unreachable dependencies |

Every benchmark writes an `identity` block into its result file — the date, the
`faster-whisper` and `ctranslate2` versions, and the cache revision of each model tier
that run loaded. A number is a measurement *of a build*, and comparing an old result to a
fresh one used to mean hoping nothing underneath had moved. Comparisons that were
byte-for-byte before still are: they drop `identity` and diff the rest.

Benchmark scripts download additional models (`small`, `medium`, `distil-large-v3`) into
the HuggingFace cache — several GB. Only `base.en` and `small.en` are needed to run Flow.

### Building a distributable

```bash
uv build
```

Produces `dist/flow-0.5.0-py3-none-any.whl` and `dist/flow-0.5.0.tar.gz` via `hatchling`.
The wheel carries the 17 `flow/*.py` modules and declares the `flow` console script, so it
installs and runs anywhere with Python 3.12 and a microphone:

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv dist/flow-0.5.0-py3-none-any.whl
./.venv/Scripts/flow --help
```

**`hatchling` is a build dependency, not a runtime one** — it is fetched into an isolated
build environment and never enters the venv Flow runs in, so R16's three declared
dependencies are intact. Verified: the runtime venv holds the same 28 distributions it
held before packaging existed, plus `flow` itself.

`scripts/` and `tests/` are deliberately outside the wheel. They are development tools that
want the repo — the benchmarks read `.bench/`, and the self-drive harness shells out.

**There is still no installer.** No MSI, no frozen `.exe`, no code signing, no auto-update.
A user needs `uv` and Python. That is a real gap for non-developer users and it is not
started; the wheel is the unit of distribution today.

## Why `.bench/` is in the repository

It was git-ignored for most of this project's life, on the reasoning that `scripts/`
reproduces it. That is true of the audio and false of everything else:

- **A result is a measurement taken at a moment.** Re-running `accent_bench.py` produces
  a new number, not the old one. The `-shipped` / `-proposed` pairs under
  `.bench/accent/` are the A/B comparisons the tuning decisions were made on, and this
  project decides almost nothing without a before and an after.
- **A recording is a person.** The clips under `.bench/recorded/` came from volunteers
  reading the sheet in [docs/recording-kit.md](recording-kit.md). They are the only
  material that answers P1 and P3 at all, they are not on the internet, and losing that
  directory loses them.
- **The generated fixtures are cheap to store and slow to remake** — a cold self-drive
  run spends minutes synthesising WAVs one at a time through PowerShell.

**The accent corpora are excluded** (`.bench/accent/edacc/`, `edacc-short/`, `aesrc/` —
about 98 MB). They are re-downloadable with `scripts/fetch_accent_data.py`, so storing
them buys only repository size; and the AESRC slice comes from a community re-upload
that declares no licence, which `fetch_accent_data.py` flags as local internal eval only
— not a claim that survives being committed anywhere. Their **manifests are kept**, so a
fresh fetch can be checked against the rows an old result was computed from.

[`.bench/README.md`](../.bench/README.md) is the full inventory: what is tracked, what is
not, and which harness remakes each thing that is missing.
