# `.bench/` — what the harnesses made, and what is worth keeping

This directory used to be git-ignored wholesale, on the reasoning that everything in it
is reproducible by `scripts/`. That is true of the audio and false of everything else,
and the distinction is the whole point of tracking it now:

- **A result is a measurement taken at a moment.** `results-base.en-shipped.json` cannot
  be reproduced by re-running anything — it records what *that* build scored on *that*
  slice. Re-running produces a new number, not the old one, which is exactly why the
  before/after comparisons this project runs on need the old one kept.
- **A recording is a person.** The clips under `recorded/` came from volunteers reading
  the sheet in [docs/recording-kit.md](../docs/recording-kit.md). They are the only
  material here that answers P1 and P3 at all — and that is exactly why they are **no
  longer in git** (2026-08-01, history rewritten): a tracked clip rides every clone and
  push forever, and durability for a voice should not mean distribution. The originals
  live in `D:\dev\flow-recordings\` with a pre-rewrite bundle beside them. On any
  machine that needs them, copy that `recorded/` folder back into `.bench/` —
  `.gitignore` keeps it out of the index either way.
- **Generated audio is cheap to keep and slow to remake.** The SAPI WAVs under
  `selfdrive/` and `commands/` are regenerated on demand, but only if missing, and a
  cold self-drive run spends minutes in PowerShell synthesising them one at a time.

So: results, manifests, recordings and the small generated fixtures are tracked. Two
categories are not, and both are in `.gitignore` with the reason next to them.

## What is here

| Path | Size | What it is |
|---|---|---|
| `accent/results-*.json` | 2.7 MB | per-accent WER runs, one file per model/config. The `-shipped` / `-proposed` pairs are the A/B comparisons behind the tuning decisions |
| `accent/manifest-*.jsonl` | 166 KB | which corpus clip is which — clip id, group, speaker, reference text. **Keep these even though the audio is not kept**: they are what makes a re-fetched corpus line up with a result measured months earlier |
| `accent/{command,gate,guardrail,lexicon,prefix}-*.json` | 30 KB | the smaller single-question benchmarks |
| `recorded/inbox/` | 19 MB | **untracked** — volunteer recordings exactly as their phones produced them, never converted. The originals; they live in `D:\dev\flow-recordings\` |
| `recorded/indian/`, `recorded/us-control/` | 12 MB | **untracked** — those recordings cut into scored per-item clips by `scripts/ingest_recordings.py` |
| `recorded/manifest-recorded.jsonl` | 7 KB | **untracked** — one row per clip: file, group, speaker, sheet item, operation, intent, and what was actually said. Untracked with the clips because it names the people |
| `live/live-check.json` | 1 KB | what `scripts/live_check.py` measured with a person at a real microphone — first run 2026-08-01 |
| `commands/` | 2.4 MB | synthesised command audio for `command_bench.py`, plus its results |
| `selfdrive/` | 2.2 MB | the SAPI WAVs `selfdrive.py` speaks, cached by utterance name, plus the throwaway profiles two scenarios write |
| `*.wav`, `*.txt` at the top | 6 MB | room/fan/speech fixtures for the gate and calibration benchmarks, and the short/medium/long latency fixtures. **Four of them are the owner's own voice** — see below |
| `polish.json`, `soak.log` | 4 KB | the polish check's output, and the long-session memory/latency log |

## What is deliberately not here

**The accent corpora** — `accent/edacc/`, `accent/edacc-short/`, `accent/aesrc/`, about
98 MB. Re-fetch them:

```bash
uv run python scripts/fetch_accent_data.py --corpus edacc
uv run python scripts/fetch_accent_data.py --corpus edacc --tag short --max-sec 6
uv run python scripts/fetch_accent_data.py --corpus aesrc
```

Two reasons, and the second is the one that decides it. They are downloadable, so
storing them buys nothing but repository size. And the AESRC slice comes from a
community re-upload that **declares no licence** — `fetch_accent_data.py` says so at the
point of use and calls it local internal eval only, which is not a claim that survives
being committed somewhere. EdAcc is a published research corpus with its own terms;
fetching it per machine keeps those terms where they belong.

The manifests are kept, so a fresh fetch can be checked against the rows an old result
was computed from rather than assumed to match.

**Scratch** — `*.npy`, `*.bak`, and `send-check-console.txt`. The `.npy` files are 19 MB
of raw audio arrays that nothing under `scripts/` reads; `send-check-console.txt` is an
eight-byte marker that `send_check.py --live` deletes and rewrites on every run, so
tracking it would leave a dirty worktree after every measurement.

## Rebuilding the rest

Everything tracked here regenerates too, it is just slower and — for the recordings —
impossible. If a generated fixture is deleted, the harness that owns it makes it again:

| Deleted | Remade by |
|---|---|
| `selfdrive/*.wav` | `uv run python scripts/selfdrive.py` (SAPI, minutes on a cold cache) |
| `commands/*.wav` | `uv run python scripts/command_bench.py` |
| top-level 22 kHz `*.wav` (`short`, `medium`, `long`) | `uv run python scripts/asr_bench.py` — SAPI, so genuinely remade |
| top-level 48 kHz `*.wav` | **nothing remakes four of them** — see below |
| `recorded/<group>/*.wav` | `uv run python scripts/ingest_recordings.py`, from `recorded/inbox/` |
| `recorded/inbox/*` | **nothing** remakes a person. Copy from `D:\dev\flow-recordings\recorded\inbox\` — and if that is lost too, ask someone to record the sheet again |

**The four that are a voice.** `acoustic.wav`, `fan45_speech.wav`, `fan55_speech.wav` and
`setup_speech.wav` — 48 kHz, about 44 seconds in total — are the owner speaking into the
machine's own microphone while the room and the fan were what they were. That is the
whole point of them: the gate is measured against real speech in real noise, and SAPI
played through a speaker measures a speaker, not a room. Two sentences, said each time:
*"Refactor the OAuth middleware to use PKCE instead of the implicit grant, then redeploy
to staging"* and *"The Kubernetes operator for Postgres needs an updated Helm chart"*.

This row used to say `gate_bench.py` and `asr_bench.py` remade all the top-level WAVs.
For four of them that was never true — a script does not remake a person, which is the
argument this file already makes about the volunteer clips — and it went unnoticed until
the repo was swept before going public. They are tracked deliberately: `gate_bench.py`'s
numbers in `docs/architecture.md` are re-runnable by a stranger only if the audio they
were measured on ships with them, and the owner chose to publish their own voice on that
trade (2026-08-02). The volunteer clips got the opposite answer, and the difference is
consent: one person can decide this about themselves and about nobody else.
