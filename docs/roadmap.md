# Roadmap: from working prototype to the product in [product.md](product.md)

Written 2026-07-31, after a full audit of the codebase against the actual target user —
a developer speaking accented English (Spanish, Indian, Russian, Japanese L1). This file
records what the audit found, the measurable targets, and the order of work. It follows
the project's standing rule: no claim without a number, and check the denominator.

## Where the build stands

The v0.1 loop is real and sound: mic → RMS speech gate → faster-whisper `base.en` int8 →
live partials → held draft → three-way routing (local regex edits / append / agent-CLI
rewrite) → clipboard+SendInput paste. ~1,660 lines, 10 modules, 3 dependencies, 79
tests, soak-tested for drift. The engineering discipline is the project's biggest asset.

Its accuracy, however, has never been measured on anything but SAPI-synthesised US
English (WER 0.000 — [README.md](../README.md) itself calls the number meaningless).
The open "risk 2" in [analysis.md](analysis.md) — real-voice accuracy — is where the
entire target population lives, and the audit found the current build is biased against
them at five specific points.

## The five defects that matter (all verified, file:line)

1. **Weakest possible model for accents.** `base.en` ([flow/asr.py:32](../flow/asr.py))
   is the smallest English-only tier. Published Svarah (Indian-English) numbers:
   multilingual base 13.6% WER, medium 8.3%, vs ~3–4% on LibriSpeech. English-only and
   distil variants rank *worse* on accented sets than their leaderboard positions.
   Expected real WER for strong accents on base.en: 15–25%+.

2. **A hidden second filter silently deletes accented speech.** Flow does not override
   faster-whisper's `no_speech_threshold=0.6` / `log_prob_threshold=-1.0`
   ([flow/asr.py:63-71](../flow/asr.py)), so segments failing both are dropped *inside
   the library* — before [clean.py](../flow/clean.py) runs, unlogged. Accented speech
   systematically scores worse on exactly these two signals.

3. **Flow's own filter breaks its two-signal doctrine.** The "thin" rule
   ([clean.py:110-112](../flow/clean.py)) drops any ≤3-word utterance on
   `no_speech_prob > 0.6` alone. Short utterances are what spoken corrections look like.
   All thresholds were calibrated on one voice, one machine.

4. **The command grammar shatters under accent.** Exact regex verbs + exact substring
   target match ([flow/edits.py](../flow/edits.py)): a mis-heard trigger ("delete"→"the
   lead", "swap"→"stop", "replace"→"leplace") silently APPENDS the command as text; a
   draft-mis-transcription makes the spoken (correct) target unfindable, so the free
   local fix escalates to a 7 s CLI call over text that doesn't contain the word. Undo
   phrases share the same fragility. No fuzzy or phonetic matching exists.

5. **The speech gate clips accented speech.** No pre-roll (soft onsets permanently
   lost), noise floor can ratchet to −25 dB (soft speakers gated out in noisy rooms),
   800 ms hangover fragments syllable-/mora-timed delivery into exactly the short
   segments defect 3 preferentially drops ([flow/audio.py](../flow/audio.py)).

Unused free levers: `hotwords` and `initial_prompt` (both supported by the installed
faster-whisper 1.2.1), final beam 2 vs library default 5, uncapped temperature fallback.

## Targets

| Metric | Today | Target |
|---|---|---|
| Per-accent WER, every anchor group (P1) | 18.7–30.6% on EdAcc (conversational; see Phase 0 results) | **≤ 12% floor** (not average) |
| Filter false-reject on real speech (P2) | 0 drops on 300 clips ≥ 1.5 s; short-utterance regime untested | **< 1%**, every drop logged |
| Command recognition, accented (P3) | unmeasured | **≥ 95%**; silent misroutes ≈ 0 |
| Personal-lexicon entity accuracy (P4) | no biasing exists | **≥ 90%** |
| Partial latency (R4) | ~1 s | **< 1.5 s, preserved** |

Benchmark composition (all local, redistribution-safe for internal eval):
**EdAcc** (CC BY-SA — the only open corpus with Spanish/Russian/Japanese/Indian slices
under one L1 metadata schema; conversational, treat as stress test) + **Svarah** (CC BY
4.0, Indian at scale, published baselines to sanity-check against) + **L2-ARCTIC**
(CC BY-NC, read speech ≈ dictation register, Spanish + Hindi) + **VoxPopuli
`en_accented`** (CC0, Spanish supplement). No published per-model numbers exist for
Russian- or Japanese-accented English — this harness produces new data.

## Phases

Two tracks. The accuracy track makes speech survive; the product track makes the result
worth speaking into. They interleave — each phase is independently shippable.

### Phase 0 — Measure (accuracy track, the foundation)

`scripts/fetch_accent_data.py` pulls per-L1 slices into `.bench/accent/` with a
`manifest.jsonl`; `scripts/accent_bench.py` decodes each clip per model and reports,
per accent group: **model WER** (all segments kept) vs **app WER** (simulating the
library's internal skip + `clean.is_invented`, i.e. what Flow would actually show), the
false-reject counts for both filters, and decode latency. The command-phrase benchmark
(P3) needs recorded accented speakers and is deferred until there are users to record —
the script inventory in [edits.py](../flow/edits.py) is the source of its prompt set.

**First run (2026-07-31, dev CPU, int8, 60 EdAcc clips/group, 31 min audio):**

| group | base.en | small.en | small | medium | small.en vs base.en |
|---|---|---|---|---|---|
| indian | 0.236 | 0.227 | 0.230 | 0.197 | −4% rel |
| japanese | 0.306 | **0.234** | 0.240 | 0.224 | **−23% rel** |
| russian | 0.187 | **0.149** | 0.150 | 0.150 | −20% rel |
| spanish | 0.189 | 0.163 | **0.159** | 0.148 | −16% rel |
| us-control | 0.282 | 0.224 | 0.227 | 0.199 | −20% rel |
| mean RTF | 0.19 | 0.51 | 0.43 | **1.44** | |

Read with the denominator in mind: EdAcc is *conversational* dialogue with cross-talk,
so absolute WER runs far above dictation register and even us-control scores 22–28%.
Valid signals are within-group model deltas, not group-vs-group absolutes. What the run
established:

- **`small.en` beats `base.en` by 16–23% relative on four of five groups** — largest on
  Japanese, the worst-served accent (30.6% → 23.4%). The Indian slice barely moved on
  this conversational data; the Svarah read-speech benchmark (base 13.6 → medium 8.3 in
  the literature) says the dictation-register gain is bigger — measure it next.
- **`small` (multilingual) ≈ `small.en` on every group.** The theorised multilingual
  accent advantage did not materialise at this tier on this data — the .en model is
  fine, and it removes the Hindi-transliteration failure mode debate.
- **RTF ~0.5 at small tier** — finals stay comfortably real-time; the R4 partial-prefix
  gate must be re-run before switching the default (asr_bench.py's prefix section).
- **Zero filter drops in 900 clip-decodes** (both the library skip and clean.is_invented,
  clips ≥ 1.5 s). The silent-deletion risk (defects 2–3) is *not* visible in energetic
  conversational speech; it remains untested exactly where the audit predicted it lives —
  short, quiet, borderline utterances. The probe for that is a short-clip (< 1.5 s)
  extension of this harness, not a reason to relax the Phase 1 observability fixes.

- **`medium` is where the Indian gain finally appears** (22.7 → 19.7 vs small.en, −13%
  rel) and it leads every group — but at **RTF 1.44 it is slower than real time on this
  CPU**, which rules it out even as a finals-only tier here: a 10 s utterance would take
  ~14 s to commit. It becomes viable only with faster hardware or a quantised/distilled
  variant worth a separate measurement.

**Decision from this data: `small.en` as the default.** Remaining Phase 0 measurements:
the R4 prefix-latency gate for `small.en` (asr_bench.py's prefix section), a Svarah
slice for dictation-register Indian numbers, and the short-clip (< 1.5 s) false-reject
probe.

### Phase 1 — Stop the bleeding (accuracy track, small diffs)

- Pass explicit `no_speech_threshold` / `log_prob_threshold`; log every dropped segment
  (defect 2 → P2).
- Thin rule requires two signals again; drops become visible events (defect 3 → P2).
- Final beam 5, temperature fallback capped at (0.0, 0.2, 0.4).
- `hotwords` from a user-editable lexicon file — names, repo terms, jargon (P4 seed).
- Grammar hardening: politeness/hedge prefixes on all patterns, fuzzy verb-snapping
  (edit distance ≤ 1 + suffix stripping), alias table, `re.escape` fix, stale
  force-next fix (defect 4, first half → P3).
- Code-switch guardrail: low-confidence utterances cannot trigger destructive edits.

### Phase 2 — Model decision (accuracy track, from Phase 0 data)

Default likely moves to multilingual `small`; decide with the Phase 0 table plus the R4
latency gate re-run. If `small` partials breach 1.5 s on the dev CPU, split tiers: fast
model for partials, stronger model for the final that is actually pasted (finals are not
latency-bound the same way — the draft is held anyway, R5).

### Phase 3 — Correction loop that survives accents (both tracks)

- Phonetic target matching: one `find_span()` (double-metaphone, vendored ~100 lines,
  + `difflib` ratio) replacing both exact-match sites — *"change Sameer to Samir"*
  finds "summer" in the draft (defect 4, second half → P3).
- Constrained re-decode of suspected commands, biased with the trigger lexicon + draft
  tokens via `hotwords` (~1 s, replaces the 7 s CLI escalation).
- Post-hoc "that was a command" rescue chip; pre-roll ring buffer + gate retune
  (defect 5 → P2).
- **Prompt polish (P5):** "make it a proper prompt" as a first-class semantic verb with
  a purpose-built CLI instruction (structure: context → constraint → ask).
- **Terminal-safe send (P7):** bracketed paste / newline suppression per target class.

### Phase 4 — The product grows a memory and a voice (product track)

- **Thread continuity (P6):** Send appends to a session thread instead of erasing;
  "follow up" / "bring back my last prompt"; CLI rewrites see the bounded thread tail.
- **Converse mode (P9):** route Send to the agent CLI instead of the focused window,
  render the reply above the pill, keep the CLI session alive across turns — ChatGPT
  Voice mode against `claude`/`codex`. Optional spoken replies via Windows SAPI
  (ctypes-reachable, R16 intact).
- **Personalisation (P8/P4):** first-run calibration (gate floor + per-user threshold
  profile from a 60 s read); lexicon growth from corrections (every "change X to Y" is
  a labelled confusion pair); local misroute telemetry (undo-after-append signature)
  growing the alias table. No egress, ever (R9).

## What this explicitly defers

- Accent-specific fine-tunes: helps one L1 group, does not generalise across four;
  personalisation is the scalable substitute. Revisit only if Phase 2 + biasing leave a
  measured gap.
- Streaming/word-level partials (the Wispr smoothness gap): architecture-level, and
  worthless until the words being streamed are the right ones.
- The command-phrase recorded benchmark: needs real accented speakers; prompt inventory
  is ready when they are.
