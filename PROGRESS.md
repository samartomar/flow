# Flow — build progress & budget

Loop state file. Each `/loop` iteration reads this first, does one stage, then
appends its own log entry. Spec lives in [docs/analysis.md](docs/analysis.md).

## Budget (R17 — hard cap 5 hr)

| | |
|---|---|
| Started | 2026-07-30 00:05 local |
| **Hard stop** | **2026-07-30 05:05 local** |
| Cadence | every 30 min (cron `7,37 * * * *`, job `2b8f8e45`) |
| Working iterations | 10 |

At the 05:05 mark the loop stops regardless of state, `CronDelete 2b8f8e45` runs,
and a final honest report lands here — including whatever is unfinished.

## Decisions locked in iteration 1

- **Stack**: Python 3.12 via `uv` + `faster-whisper` (`base.en`, int8, CPU) + `tkinter`.
  GUI, hotkeys and text injection all come from **stdlib** — that is where min-deps is won.
- **Interpreter is pinned**: bare `python` on this machine is 3.5. Never invoke it.
- **Refine routing**: local heuristic (correction-verb prefix) decides edit-vs-append.
  No CLI call on the append path.
- **CLI**: `codex exec` preferred, `claude -p` fallback, behind one adapter. Stateless,
  capped input, hard timeout. Never sees audio.
- **ASR engine sits behind a ~30-line interface** so whisper.cpp (Option B) can be
  swapped in if faster-whisper proves heavy.

## Stages

| # | Stage | Status | Gate to pass |
|---|---|---|---|
| 1 | Analysis, architecture decision, scaffold | **done** | Requirements table + option trade-off written |
| 2a | Measure CLI refine latency | **done** | Numbers in hand: ~7 s both CLIs |
| 2b | Measure ASR latency + footprint | **done** | R4 gate passed: 0.75–0.91 s decode |
| 3 | Audio capture + gate + utterance cut + re-decode partials (headless) | **done** | R4 shown live; draft holds on stop |
| 4 | State machine + threaded decode + draft buffer + router | **done** | Held draft, append/correct/undo/send all tested (R5, R7) |
| 5a | **Local edit ops** — the fast path for literal corrections | **done** | Corrections apply in microseconds, no CLI (R6, R11) |
| 5b | CLI adapter for semantic rewrites only + guards | **done** | Verified live: 5.7 s via codex, no key, non-destructive |
| 6 | Pill window + waveform + state colours | **done** | Screenshotted and inspected (R12, R13) |
| 7 | Draft bubble + float-up + Refine/Continue/Send chips | **done** | Screenshotted and inspected (R14, R15) |
| 8 | Global hotkeys + clipboard/`SendInput` injection | **done** | Clipboard round-trips; 3 hotkeys registered |
| 9 | Long-run hardening: caps, device recovery, idle model unload | **done** | 11 min: RSS −14 MB, p50 decode flat (R8) |
| 10 | README, entry point, final report | **done** | Real entry point launched and captured |

Stages 6–10 are deliberately behind the stage-2..5 gates — the idea says "once
proven", and the six proof criteria are in §7 of the analysis.

## Log

### Iteration 1 — 2026-07-30 00:05
Probed the machine: `codex` and `claude` both installed and authenticated
(so R9 "no api key" is satisfiable with zero key handling on our side); `uv 0.12`
and Python 3.12.10 present; `cargo` present; **no** `ffmpeg`, `ollama`, or `dotnet`
— which kills ffmpeg-based capture and any local-LLM refine path. Found bare
`python` resolves to **3.5**, a live trap for every later stage.

Wrote the requirements decomposition (R1–R17 + non-goals), compared four
architectures, and chose Python+`uv`+faster-whisper+tkinter on the grounds that
stdlib covers GUI/hotkey/injection, so the dep tree stays at three declared packages.

Named the one design problem the idea doesn't resolve: in the draft state, speech is
ambiguous between "append more" (R7) and "correct this" (R6). Chose a local
correction-verb heuristic over an LLM classifier specifically to keep the CLI out of
the hot path per R11.

Flagged **Risk 1 as concept-invalidating**: if `codex exec` cold start is 1–3 s, the
talk-to-refine loop does not feel like a refine loop. Then measured it rather than
deferring, because it changes the architecture rather than just an implementation detail.

**Measured (stage 2a) — Risk 1 is CONFIRMED and worse than estimated:**

| CLI | Wall clock | Exit | Notes |
|---|---|---|---|
| `codex exec --skip-git-repo-check` | **7.26 s** | 0 | Correct edit. Prints a banner, echoes the prompt, then emits the answer **twice** before `tokens used`. **19,670 tokens** consumed for a 10-word typo fix |
| `claude -p` | **6.72 s** | 0 | Correct edit, cleaner stdout, but the model volunteered an extra sentence of commentary; also warns the workspace is untrusted |

Three consequences, all design-level:

1. **~7 s is the floor, not the cold-start penalty.** It is process boot + auth +
   a full agent system prompt. No prompt tuning on our side removes it. So the CLI
   cannot sit on the correction path at all — a spoken "fix that typo" that takes
   7 s is worse than fixing it by hand, which defeats the product.
2. **19.7 k tokens for a typo fix is precisely the "heavy lifting" R11 warns against**,
   and it is inherent to agent CLIs rather than something our prompt caused.
3. Both CLIs polluted their output — a banner and a duplicated answer from `codex`,
   unrequested commentary from `claude`. Output sanitising is mandatory, not defensive
   politeness.

**Plan revised in response.** Stage 5 splits: literal corrections
("change X to Y", "replace X with Y", "delete X", "capitalise X") become **local
string operations** — instant, zero deps, and they cover the large majority of real
dictation corrections. The CLI is reserved for genuinely semantic rewrites
("make it more formal", "shorten this", "turn it into bullets"), where a 7 s wait is
acceptable because the user asked for a rewrite rather than a fix, and where the
pill's blue "refining" state makes the wait legible instead of feeling like a hang.

This is a better fit for R11 than the original design, and it came from measuring
first. Next iteration: stage 2b, the ASR half of the spike — the remaining
unmeasured concept risk.

### Iteration 2 — 2026-07-30 00:11 — stage 2b, ASR spike

`uv sync` installed in **6.3 s**; 3 declared deps resolve to **28 packages**.
Benchmark script: [scripts/asr_bench.py](scripts/asr_bench.py), driven by SAPI-synthesised
WAVs so latency is repeatable without a person at a microphone.

**R4 gate — PASSED, with a finding that simplifies stage 3 substantially:**

| Audio prefix | Decode | RTF |
|---|---|---|
| 1 s | 0.75 s | 0.75 |
| 2 s | 0.79 s | 0.39 |
| 3 s | 0.81 s | 0.27 |
| 5 s | 0.86 s | 0.17 |
| 8 s | 0.91 s | 0.11 |

**Decode time is nearly flat in audio length** — 1 s of audio costs 0.75 s, 8 s costs
0.91 s. Whisper pads every input to a fixed 30 s mel window, so the cost is dominated
by fixed overhead, not by how much has been said. Three consequences:

1. **No incremental-decoder state machine is needed.** Re-decoding the entire growing
   utterance on every refresh costs about the same as decoding one second of it. Stage 3
   collapses to "keep appending to a buffer, re-decode it, replace the partial" — which
   is far less code than the streaming design originally sketched.
2. **There is a hard ~0.8 s floor per decode**, so partials refresh at roughly 1.2 Hz.
   Text will appear in ~1 s bursts, not word-by-word as Wispr Flow appears to do. This
   satisfies R4 as written but is an honest gap against the reference product.
3. **The flat behaviour ends at 30 s.** Past one mel window the cost climbs, so R8
   requires cutting utterances before ~25 s and committing them to the immutable prefix.
   That is now a measured constraint rather than a guess.

**Accuracy: WER 0.000 on all three clips — but this number is not trustworthy yet.**
SAPI speech is clean, evenly paced and close to Whisper's training distribution. It
proves the pipeline is wired correctly and that `base.en` handles this vocabulary; it
says little about real microphone conditions. Real-speech WER remains **unmeasured**
and needs the user at a mic. `base.en` stays the default; `small.en` is a one-line change.

**Footprint (R3, R16):**

| | |
|---|---|
| Cold start | **~1.4 s** (0.40 s import + 0.98 s model load, warm cache) |
| `.venv` | 243.4 MB |
| Model (`base.en` int8) | 141.0 MB |
| **Total** | **~384 MB** |

384 MB is defensible for local ASR but is not "super light" in the strictest reading of
R16. The single biggest waste is `av` (26 MB wheel), a hard dependency of
faster-whisper used only for decoding audio *files* — our path feeds numpy arrays
straight from sounddevice, so `av` is imported and then does nothing. It cannot be
dropped without leaving faster-whisper, which is exactly what Option B (whisper.cpp)
would buy: roughly 100 MB back, at the cost of sourcing and verifying a Windows binary.
**Not taking that trade** — 384 MB works today and the 5 hr cap is better spent proving
the refine loop. Recorded as the known lever if footprint later matters more.

### Iteration 2 (cont.) — 2026-07-30 00:16 — stage 3, capture + live partials

Continued instead of idling to the next fire, since the 5 hr cap is wall-clock and idle
time is spent budget.

Confirmed a usable mic (OBSBOT Tiny 3 Lite, default index 1, natively 44.1 kHz stereo —
`sounddevice` is asked for 16 kHz mono directly so the driver resamples and we ship no
resampler). Wrote [flow/audio.py](flow/audio.py) (`Mic`, `SpeechGate`),
[flow/asr.py](flow/asr.py) (`WhisperTranscriber` behind a two-method interface) and
[scripts/listen.py](scripts/listen.py), which runs the identical code path from either the
mic or a WAV.

**Chose an RMS gate over Silero VAD.** Silero means carrying `onnxruntime` to answer a
question this only needs answered coarsely — "has the talking stopped?" — where being
200 ms late is invisible because the draft is held rather than sent (R5). Twenty lines
of stdlib maths instead of a 13 MB dependency.

**R4 demonstrated live** (real-time-paced replay). Partials build as speech continues:

```
…I need to send an email.                                          (0.74s)
…I need to send an email to the team about the quarterly review.   (0.84s)
…scheduled for next Tuesday afternoon, and please remind everyone  (0.97s)
[draft] I need to send an email to the team about the quarterly review meeting
        scheduled for next Tuesday afternoon, and please remind everyone to
        bring their updated figures.
```

Final draft was word-perfect and, per R5, was held rather than sent.

**Three defects, all found by running it rather than by reading it:**

1. **Noise floor ran away to −142 dB.** The padded silence is exact zeros, so
   `rms_db` returns ≈ −180 dB and the floor tracker chased it; the gate's threshold
   then sat below any conceivable signal and everything read as speech. Fixed by
   bounding the floor to [−70, −25] dB and refusing to train it on digital silence
   (that is a dead stream, not room noise). Floor now settles at a sane −54.7 dB.
2. **The first run did zero partial decodes and I nearly recorded a pass on it.**
   Replaying the WAV as fast as the disk allowed compressed 10 s of audio into under a
   second, so the 0.9 s partial timer never elapsed — the entire live-partial path was
   untested while the output looked correct. Replay is now paced to real time.
3. **Decode blocks the capture loop** — the actual architectural finding. 42 decodes
   ran for 11.4 s of audio, and the tail shows the same completed sentence re-decoded
   ~15 times. Because decode is synchronous, wall time becomes
   `audio + Σ decode`, so in a live session partial latency would drift further and
   further behind speech. **Stage 4 must move decode onto a worker thread that always
   decodes the newest snapshot and discards stale requests.** Not patched here — it is
   the state machine's job, and the harness proved the point.

Cosmetic, worth knowing: partials sometimes contain hallucinated fragments
(`bring // // //`) on mid-word boundaries. Harmless since partials get replaced, but the
UI should render them dimmed so "not final yet" is visible.

Still unmeasured: **real-microphone accuracy** (risk 2). Every WER number so far comes
from synthesised speech and is optimistic. To settle it, run:

    uv run python scripts/listen.py

### Iteration 3 — 2026-07-30 00:40 — stages 4, 5a, 5b

Wrote [flow/session.py](flow/session.py) (state machine, `DecodeWorker`, `Draft`),
[flow/edits.py](flow/edits.py) (router + local ops), [flow/refine.py](flow/refine.py)
(CLI adapter), and 23 tests across [tests/](tests). Whole suite runs in 0.7 s with no
microphone, no model and no subprocess.

**Defect 3 fixed.** `DecodeWorker` is one thread where partials are *latest-wins* — a
new snapshot replaces the pending one — while finals go through a FIFO that is never
dropped, because losing a final would lose the user's words. `Session` additionally
only requests a partial when the worker is idle, so speech outrunning the decoder skips
intermediate states instead of building a backlog.

**A correction to iteration 2's finding on CLI output.** I reported that both CLIs
pollute their output and would need a parser. That was wrong, and it was my measurement
that was at fault: I had merged the streams with `2>&1`. Captured properly, `codex`
writes **only the answer to stdout** and puts the banner, prompt echo and token count on
stderr. No parser is needed — `refine.py` just strips whitespace, with a light guard for
stray code fences. One real find survived from that measurement: `codex` blocks reading
stdin, so `stdin=DEVNULL` is required or the call can hang to the timeout.

**The router needed the draft, not just the utterance.** The first test run caught
`"Delete key handling is broken."` being routed as an edit — ordinary dictation about a
keyboard, silently eaten as an instruction. Nothing in the utterance distinguishes it
from `"delete key handling"`; what distinguishes them is whether the target text exists
in the draft. So weak verbs (`delete`, `capitalize`) now only fire when their target is
really present, while a strong shape (`change X to Y`, which is hard to say by accident)
escalates to the CLI when the target is missing rather than being appended as speech.

**Second time I nearly recorded a false pass.** The first defect-3 regression test drove
partials through `FakeMic`, whose `drain()` returns every block at once — so exactly one
partial was ever submitted and the test would have passed against the old synchronous
code too. Replaced with a direct `DecodeWorker` test: 40 partials submitted during a
slow decode result in fewer than 10 decodes, and the newest snapshot is provably not the
one dropped. That pattern — a green test that does not exercise the thing it names — has
now appeared twice, so it is worth distrusting any test here that passed on the first try.

**CLI refine verified live** via [scripts/refine_check.py](scripts/refine_check.py):

| Instruction | Time | Result |
|---|---|---|
| "make it more formal" | 5.69 s | "Hello, I wanted to confirm whether we are still scheduled for Tuesday and whether you received the figures I sent." |
| "turn it into bullet points" | 5.78 s | two clean bullets |

No API key anywhere in the path (R9), `codex` preferred with `claude` as fallback (R10),
input capped and tail-spliced, hard timeout, and every failure mode leaves the draft
untouched (R11).

**Proof criteria from analysis §7:** 1, 2, 3, 4 and 6 now hold. 5 (10-minute session,
flat RAM) is stage 9. The remaining gap is still real-mic accuracy — no synthetic test
can close it.

### Iteration 4 — 2026-07-30 01:10 — stages 6, 7, 8

**Risk 3 retired first**, since it gated the whole UI. [scripts/tk_probe.py](scripts/tk_probe.py)
confirmed all five attributes the pill needs work on this Win 11 / Tk 8.6 build:
`overrideredirect`, `-topmost`, `-alpha`, `-transparentcolor` (true rounded corners) and
`-toolwindow` (stays out of the taskbar and alt-tab). Values read back rather than being
silently ignored.

Wrote [flow/ui.py](flow/ui.py) (pill + bubble), [flow/inject.py](flow/inject.py)
(clipboard + `SendInput`), [flow/hotkey.py](flow/hotkey.py) (`RegisterHotKey` on its own
message-loop thread) and [flow/\_\_main\_\_.py](flow/__main__.py). Still three declared
dependencies — tkinter and ctypes are stdlib, so R16 held through the entire UI stage.

**The UI was verified by looking at it, not by assuming.** That took three attempts, and
the first two failures were both in the capture method rather than the app:

1. `Start-Process -WindowStyle Hidden` suppressed the Tk window, so the screenshot
   captured whatever was behind it.
2. With the window visible, the crop was still uniform dark. Enumerating top-level
   windows proved both windows existed exactly where intended — pill at `1100,590
   152x40`, bubble at `872,437 380x143`. The real cause: `CopyFromScreen` uses BitBlt,
   which does not capture **layered** windows, and `-alpha`/`-transparentcolor` make
   these layered. Under RDP it returns the desktop underneath instead.
3. `PrintWindow` with `PW_RENDERFULLCONTENT` against the window handles worked, and is
   the right tool for layered windows.

Both surfaces render correctly: the pill shows the drawn mic glyph and 18 mirrored level
bars in the state accent (amber for DRAFT), and the bubble shows wrapped draft text, the
muted note line, and the three chips with **Send** filled in the accent colour.

**A segfault, found by running the smoke check.** `scripts/inject_check.py` exited
`0xC0000005` with no output at all. Cause: ctypes defaults an undeclared `restype` to C
`int` — 32 bits — so `GlobalLock` returned a **truncated pointer** on x64 and
dereferencing it killed the interpreter. Every Win32 signature in `inject.py` and
`hotkey.py` is now declared explicitly, and `set_clipboard_text` frees the handle on the
failure path instead of leaking it. This class of bug is invisible to reading and fatal
at runtime, which is a good argument for smoke-checking every ctypes surface.

Post-fix the clipboard round-trips and — importantly — **the user's clipboard is
restored** afterwards rather than being clobbered.

**A hotkey was silently dead and the code caught it.** `ctrl+alt+space` is already owned
by another process on this machine. `RegisterHotKey` just returns false, so this would
have shipped as "the shortcut does nothing, no idea why". Each action now has an ordered
list of alternatives and reports which one won:

| Action | Registered |
|---|---|
| toggle | `ctrl+shift+space` (first choice was taken) |
| send | `ctrl+alt+enter` |
| cancel | `ctrl+alt+esc` |

`paste()` deliberately writes the clipboard **before** attempting the keystroke, so that
the documented UIPI limitation (elevated windows reject synthetic input) degrades to
"press Ctrl-V yourself" rather than losing the text.

23 tests still pass. Test count did not grow this iteration — the UI, clipboard and
hotkey layers were verified by inspection and smoke checks instead, which is the honest
description of their coverage.

### Iteration 5 — 2026-07-30 01:37 — stages 9 and 10

**R8 hardening.** Four things a long session needs that a short one hides:

- **Idle unload.** After 5 minutes with no speech and no held draft, the 141 MB model is
  dropped; the next utterance pays ~1 s to reload it. This deliberately **narrows**
  what analysis §4 proposed: that said "release the mic and unload the model", but
  releasing the mic would leave the app unable to hear its own wake-up. The mic is cheap
  and stays open; only the model goes.
- **Device recovery.** A PortAudio stream can die mid-session (unplugged, driver reset)
  without raising anywhere the session can see, so `Mic.active` is polled every 5 s and
  capture is reopened. `Session.pause()` exists so a *deliberate* pause is
  distinguishable from a dead device — otherwise the health check would helpfully
  reopen a mic the user just switched off.
- **Bounded undo.** `Draft` history was capped at 30 snapshots, which for a very long
  draft is megabytes of copies. Now bounded by total characters as well.
- **Utterance cut** at 24 s was already in place from stage 3 (risk 7).

**Test coverage went from 23 to 41**, and the additions target the code least likely to
be exercised by hand:

- [tests/test_longrun.py](tests/test_longrun.py) — history bounds, idle unload,
  model *kept* while a draft is held, dead-device recovery, and paused-mic-not-reopened.
- [tests/test_refine.py](tests/test_refine.py) — the R11 guards, which had none. Lossless
  tail splitting, commentary refusal, timeout, non-zero exit, empty output, fence
  stripping, missing CLI, and an explicit assertion that `stdin=DEVNULL` is passed
  (the thing that stops `codex` hanging).

**Stage 10.** [README.md](README.md) written for someone who has never seen the project,
including a **Known limitations** section that states the unflattering things plainly:
~1 s partial bursts rather than per-word, nonsense in partials at word boundaries, UIPI
blocking paste into elevated windows, ~6 s semantic rewrites, ~384 MB installed, and that
accuracy on the user's own voice is still unmeasured.

**Soak result — memory half of proof criterion 5 passes.** 11 minutes, 58 utterances
decoded, [scripts/soak.py](scripts/soak.py) driving a real model with looped speech in real time:

| | |
|---|---|
| Baseline RSS | 175.5 MB |
| Range over the run | 194 – 277 MB |
| First samples → last samples | 214.7 → 211.7 MB |
| **Drift** | **−3.0 MB over 10.5 min (−0.28 MB/min)** |

Memory oscillates and ends slightly *below* where it started, so nothing accumulates.
A second signal worth noting: the draft-length progression was byte-identical on every
cycle (335 → 839 → 1343 → 1679 → 2183 → 2687 → 3023 → 3527 → send → 0) at minute 9.5 as
at minute 0.5, which means the pipeline behaved the same at the end as at the beginning.

**But I had only measured half of criterion 5.** It reads "flat RAM *and unchanged
latency*", and the soak recorded no latency at all — the byte-identical draft progression
is suggestive but it is not a latency measurement. Rather than claim the criterion,
added `DecodeWorker.timings` (a bounded deque, safe to leave on) and per-window p50
decode sampling to the soak, then re-ran it. Sampling has to be windowed, not
cumulative: a whole-run average would hide exactly the drift being looked for.

**And the instrumented re-run was itself broken — third time in this build.** It printed
a clean-looking verdict:

```
p50 decode first quartile: 0.860s
p50 decode last  quartile: 0.858s
latency change           : -2 ms (-0.2%)
```

That number is not wrong so much as *not about the last quartile*. The `n` column gives
it away: every window from minute 5.0 onward reported `n=0`. `timings` is a
`deque(maxlen=300)`, so once it saturated its length stopped growing and the
"everything since last time" slice `all_t[seen_timings:]` was empty forever. The
reported "last quartile" came from around minute 4–5 of an 11-minute run.

Fixed by draining instead of indexing — `DecodeWorker.take_timings()` returns and clears
under the lock — with a regression test that overfills the deque and asserts new work is
still reported afterwards.

**The pattern is now worth stating as a rule for this project.** Three times a green
result did not measure what it claimed:

1. Stage 3 — WAV replayed faster than real time, so the partial path never ran while the
   output looked correct.
2. Stage 4 — the defect-3 regression test drove partials through a `FakeMic` that
   returned every block at once, so it would have passed against the buggy code.
3. Stage 9 — latency windows silently went empty once a bounded deque saturated.

All three were *measurement* bugs, not product bugs, and all three produced plausible
output. The rule: **check the denominator before believing the ratio** — how many samples
did this number actually come from, and does that count make sense for the interval it
claims to describe. The `n` column existed only because of lesson 2; it is what caught
lesson 3.

**Real capture path verified** via [scripts/mic_check.py](scripts/mic_check.py). Until now
every audio test came from a WAV or a fake, so PortAudio had never actually run:

| | |
|---|---|
| Blocks in 3 s | 46 (expected ~46) |
| Dropped | 0 |
| Level range | −97.1 to −63.4 dB (quiet room) |
| Noise floor settled | −59.9 dB |
| **False speech onsets** | **0** |

Zero false onsets matters: the gate does not trip on room noise. The −97 dB blocks were
correctly refused as floor-training input by the digital-silence clamp added in stage 3,
which is that fix doing its job on real hardware rather than on padded zeros.

**Proof criterion 5 now passes on a valid measurement.** Third soak run, windowing fixed,
`n` between 31 and 33 in every single window through minute 10.5:

| | |
|---|---|
| Utterances decoded | 58 |
| RSS first → last samples | 223.2 → 208.9 MB |
| **Memory drift** | **−14.3 MB over 10.5 min** |
| p50 decode, first quartile | 0.848 s |
| p50 decode, last quartile | 0.868 s |
| **Latency change** | **+21 ms (+2.4%)** |

Per-window p50 oscillated between 0.83 s and 0.88 s across the whole run with **no
monotonic trend**, so +21 ms sits inside a ~50 ms jitter band rather than indicating
drift. Stated precisely: latency is unchanged within measurement noise, and memory ends
lower than it started. Both halves of the criterion hold.

**Real entry point launched.** Every component had been verified individually but
`python -m flow` itself had never been run. It starts clean: exactly one visible window
(the bubble is correctly withdrawn until a draft exists), pill at `1100,590 152x40`,
slate accent and flat bars for the disarmed state, nothing on stderr, and the process
tree exits cleanly.

Two real fixes came out of that launch:

1. **Startup diagnostics were invisible when redirected.** Python block-buffers stdout
   when it is not a tty, so the lines reporting which CLI was found and which hotkeys
   registered — precisely the output someone needs when it is not working — were lost.
   Now flushed.
2. **Non-ASCII in console output was a latent crash.** The messages used `·` and `—`.
   Redirected stdout uses the locale encoding, and a legacy console code page
   (cp437/cp850) cannot encode either, which turns a startup message into a
   `UnicodeEncodeError` before the UI ever appears. Console strings are now ASCII.

Verified output:

```
refine CLI: codex
  (fallbacks: claude)
hotkey  toggle   ctrl+shift+space
hotkey  send     ctrl+alt+enter
hotkey  cancel   ctrl+alt+esc
click the pill to arm | right-click for the menu | esc quits
```

**All ten stages are complete at 02:25, 2 h 40 m inside the 5 h cap.** 42 tests.
Requirements R1–R17 are all addressed; the one thing no amount of further building can
settle is **real-microphone accuracy (risk 2)**, which needs the user's own voice.

### Iteration 6 — 2026-07-30 02:27 — quality work that does not depend on the open question

With all ten stages done and the only blocker being something a user has to answer, the
remaining budget went to two improvements that are correct either way.

**1. Whisper invents text on silence, and it was reaching the draft.**
[scripts/hallucination_probe.py](scripts/hallucination_probe.py) measured what the model
emits when there is nothing to hear:

| Input | `no_speech_prob` | Emitted |
|---|---|---|
| digital silence 3 s | 0.691 | `'You'` |
| quiet noise 3 s | — | nothing |
| room-ish noise 3 s | — | nothing |
| louder hiss 2 s | 0.899 | `'You'` |
| genuine 0.4 s fragment | 0.099 | `'I need...'` |
| real speech | 0.00017 | correct |

For a tool that pastes into someone's document, an invented word is a defect. The gap
between a real fragment (0.099) and a hallucination (0.691) is wide, so
[flow/clean.py](flow/clean.py) filters on `no_speech_prob` rather than on a blocklist of
phrases.

The design bias is stated in the module and enforced in the tests: **dropping a real word
is worse than admitting a rare invented one**, because a user can delete text they can
see but cannot recover text never shown. So nothing is discarded on one signal —
`no_speech_prob > 0.6` must be confirmed by either thin content (≤3 words) or poor
`avg_logprob`. A long, confident utterance survives even at `no_speech_prob` 0.95.

Verified end to end through `WhisperTranscriber`: all four silence/noise cases now return
nothing, while the genuine 0.4 s fragment and full speech pass through untouched. Also
collapses the degenerate `bring // // // //` repetition seen in stage 3 partials, while
leaving real repetition ("very very good") alone.

**2. More corrections handled locally**, which is the direct way to serve R11 — every
correction handled locally is one that does not pay the ~6 s CLI. Added `replace all X
with Y`, `delete from X to Y`, `insert X before/after Y`, `lowercase X` / `make X
lowercase`, and split case handling: `capitalize john` → `John` (title case) while
`all caps nasa` / `uppercase nasa` → `NASA`. Previously `capitalize` mapped onto
upper-case, which turned `capitalize john` into `JOHN` — the more jarring of the two
possible mistakes.

**Two bugs the new tests caught immediately:**

- `replace all Bob with Alice` never reached the new op. The generic `change|replace|swap
  X to|with Y` pattern matched first with target `"all Bob"`, which is never in the
  draft, so it silently escalated to the CLI — the exact opposite of the intent. Pattern
  order fixed.
- Deleting a range framed by commas left `,,` behind. Worse, my first test expectation
  was written as `"Keep this,, keep the end.".replace(",,", ",")` — papering over the bug
  inside the assertion instead of failing on it. `_tidy` now collapses adjacent
  punctuation, and the test asserts the actual desired string.

Also guarded pronoun targets: "make it lowercase" is a request about the whole draft, not
about the word "it", so it routes to the CLI rather than mangling a random occurrence.

**63 tests.** Deliberately did *not* download `small.en` to benchmark it: it would put
~466 MB on the user's disk unasked, and without real speech its accuracy cannot be
compared anyway — only its (predictable) compute cost. It stays a documented one-flag
option.

### Iteration 7 — 2026-07-30 02:37 — failure paths

Went after one class of bug specifically: **failures that leave the pill on screen but
dead**. For an always-on widget that is worse than a crash, because nothing tells the user
anything is wrong.

**1. A raise inside the frame pump killed the app silently.** `Pill._tick` ended with
`self.after(30, self._tick)`, so any exception — a device error, a decode failure — broke
the chain and left a pill that still painted but no longer did anything, with the
traceback in a stderr nobody watches. The re-schedule now lives in `finally`, and errors
become a red flash plus a visible note.

**2. `Session.start()` awaited the model load, freezing the UI on first click.** On a
first run that includes a ~141 MB download, so the very first click would hang the whole
interface for as long as the network took, with no indication of why. The load is now a
background pre-warm; the decode worker loads lazily on its own thread regardless, so only
`mic.start()` has to succeed synchronously. A load failure arrives as an `error` event
instead of vanishing into a thread.

**3. Two threads could race to load the model.** The new pre-warm and the decode worker
can both call `load()`, and the unguarded `if self._model is None` check meant both could
build a 141 MB model with one silently discarded. Now lock-guarded, with a test that runs
eight concurrent loads and asserts exactly one construction.

**4. A failing mic used to flip the pill green anyway.** `_toggle` set `armed` before
calling `start()`, so an unopenable device produced a green "listening" pill that captured
nothing — the app lying about its own state. It now stays disarmed and reports why.

Added `--arm` (start listening without a click), which is useful in its own right and made
the failure path testable end to end.

**Verified in the real app, not just in unit tests.** Launched with `--device 999 --arm`:

| | |
|---|---|
| Process still alive after the failure | yes |
| Visible windows | 2 — pill + error bubble |
| Bubble text | `could not start capture: Error querying device 999` |
| Bubble accent | red |
| Pill | slate, disarmed — did **not** claim to be listening |
| stderr | empty |

**69 tests.** The three UI-resilience tests skip automatically where there is no display.

### Iteration 8 — 2026-07-30 03:10 — R16, the requirement most compromised on

"Super light, dependencies at min" was stated as a hard constraint and 384 MB was the
weakest answer in this build. Earlier iterations asserted `av` was dead weight but never
tested whether it could actually go. Measured it properly.

Per-package sizes in the venv, and where each is imported:

| Package | Installed | Import site |
|---|---|---|
| `av` + `av.libs` | 65.9 MB | `audio.py:15` — **module level** |
| `ctranslate2` | 59.8 MB | genuinely needed |
| `onnxruntime` | 38.6 MB | `vad.py:298` — **inside a function** |
| numpy + numpy.libs | 41.6 MB | genuinely needed |

Both large ones are unreachable from this app, for different reasons: `onnxruntime` exists
only for Silero VAD and `asr.py` always passes `vad_filter=False`; `av` exists only to
decode audio *files* and every use of it sits inside `decode_audio()`, which never runs
because audio arrives as numpy arrays.

Tested in a throwaway venv rather than by reasoning:

| Step | Size | Decode |
|---|---|---|
| baseline | 236.8 MB | ok |
| −`onnxruntime` −`protobuf` | 203.1 MB | ok |
| −`av` | 137.1 MB | **`ModuleNotFoundError`** — confirming the module-level import |
| `av` replaced by a stub | 137.1 MB | ok |

Then ran the **full 69-test suite using the slimmed interpreter** — all passing. Wrapped it
in [scripts/slim.py](scripts/slim.py), which dry-runs by default and has `--undo`;
exercising the script end to end gave **243.5 MB → 137.3 MB, saving 106.2 MB**. With the
model that is 384 MB → ~278 MB, a 28% reduction.

**Left opt-in rather than default.** It knowingly breaks a dependency contract: a future
faster-whisper could touch `av` at import time or enable VAD by default. Since it is
one command each way and `uv sync` restores everything, the user gets to make that call.
Also added two guard tests asserting the couplings the trim depends on — `vad_filter` is
never True, and audio is always passed as an ndarray rather than a path — so a later
change cannot silently break slimmed installs with a baffling ImportError.

**A test-suite bug I introduced and nearly reported a pass on.** After adding those two
tests the suite aborted with `Tcl_AsyncDelete: async handler deleted by the wrong thread`
and printed **no summary line at all** — 62 dots and then nothing. Cause: these tests
create `Tk` roots while others start background threads, and if a Tk object is finalised
on a thread other than the one that created it, Tcl kills the process. Fixed by tearing
down child-first, dropping the reference and calling `gc.collect()` on the main thread, so
finalisation is deterministic. Confirmed with **four consecutive clean runs** rather than
one, because an intermittent abort that passes once is not fixed.

That makes four times in this build that a green-looking result was not what it claimed.
The absent summary line here is the same lesson as the absent `n` column in stage 9:
**check that the run actually completed, not just that nothing said FAILED.**

**71 tests.**

### Iteration 9 — 2026-07-30 03:40 — the seams between iterations

Every module had unit tests, but the pieces were added across eight iterations and the
*seams* between them had none. Wrote [tests/test_integration.py](tests/test_integration.py)
to cover where the hallucination filter meets the state machine, and where the new local
edit ops meet undo and send. Two real bugs came out of tracing the filtered-utterance path:

1. **A fully filtered utterance left the pill stuck green.** When `clean.py` rejects
   everything — silence, noise, a hallucination — the transcriber returns `""`.
   `_pump_decodes` skipped empty finals entirely, so `_after_draft_change()` never ran and
   the state machine stayed on `LISTENING`. The pill would sit there green with nothing in
   flight, which is the app misreporting its own state. Now an empty final still resolves
   the state to DRAFT or IDLE.
2. **An empty partial popped a blank bubble open.** Partials were emitted unconditionally,
   so a partial the filter reduced to nothing still made the bubble deiconify with no
   content in it. Only non-empty partials are emitted now.

**A third test-scripting flaw, same shape as the other four.** The forced-append test
queued both utterances before starting, and `ScriptedMic.drain()` hands over every block in
one call — so both were routed before `force_next` could be set, and the test "found a bug"
that was purely its own scripting. Audio is now fed one utterance at a time, and a
counterpart test asserts the *unforced* path produces the different result, so the override
test can no longer pass for the wrong reason.

Also fixed stale Tk `after` callbacks leaking between tests (`invalid command name
..._tick`). `_tick` reschedules itself, so a queued callback outlived its widget and Tcl
complained later while another root pumped events. Teardown now cancels pending `after`
ids before destroying, and `pill.update()` was dropped from teardown since flushing was
what fired them.

**79 tests, four consecutive clean runs, zero Tcl noise**, and the real entry point still
launches.

### Iteration 10 — 2026-07-30 04:07 — doc/code alignment, and stopping

Nine iterations of measurement changed several decisions recorded in
[docs/analysis.md](docs/analysis.md), and a design doc that contradicts the code is worse
than none. Audited it against the implementation and corrected every divergence found:

| Claimed in §3–§5 | Actually built |
|---|---|
| "~6 transitive deps" | **28 packages, 243 MB** — the estimate was simply wrong |
| faster-whisper's built-in Silero VAD | own ~20-line RMS gate, so `onnxruntime` is unreachable |
| CLI hard timeout ~6 s | **20 s** — a normal call measures 5.7–7.3 s, so 6 s would have killed healthy calls |
| CLI invoked "on an edit" | only on a **semantic** rewrite; literal corrections never reach it |
| output "stripped of preamble" | **no parser needed** — stdout is clean, stderr carries the banner |
| committed-prefix / editable-tail split | **not built** — the 2000-char tail cut in `refine.py` bounds cost with less machinery |
| "ASR worker health-checked and restartable" | the **input device** is; the worker swallows per-decode errors and cannot die |
| idle → release mic and unload model | **model only** — releasing the mic would leave the app deaf to its own wake-up |
| pill ~140×36, ~24 bars, amber = transcribing | **152×40, 18 bars, amber = draft held** (the state that needs attention) |
| bubble "keyboard-editable" | **not built** — never requested, and the product is voice-driven |
| solid-background fallback for transparency | unnecessary; all five window attributes probed working |

Also recorded the outcome of the six proof criteria from §7 — all six pass, with the
numbers — and restated plainly that **accuracy on a real microphone remains unproven**,
because every WER figure in the document comes from synthesised speech.

**Stopping here at 04:13, ~50 minutes inside the cap.** The cap was a limit, not a quota:
all ten stages are done, all 17 requirements are addressed, 79 tests pass, and the one
question that would direct further work — whether `base.en` is good enough on the user's
own voice — cannot be answered without them. Continuing would mean inventing scope that
was never asked for. Cron job `2b8f8e45` deleted.

## Final state

| | |
|---|---|
| Time used | 4 h 08 m of a 5 h cap |
| Tests | 79, running in ~1.4 s with no mic, model or subprocess |
| Declared dependencies | 3 (`faster-whisper`, `sounddevice`, `numpy`) |
| Product code | ~1660 lines across 10 modules |
| Footprint | ~384 MB, or ~278 MB after `scripts/slim.py --apply` |
| Cold start | ~1.4 s |
| Open question | real-microphone accuracy (risk 2) |

**The lesson worth carrying out of this build**, recorded because it recurred five times:
a green result is not evidence until you check it could have been red. Twice a passing
test hid a real bug (a WAV replayed faster than real time; a fake mic that returned every
block at once), once a metric silently stopped sampling after a bounded deque saturated,
once a suite aborted without printing a summary line, and once a test invented a bug that
was purely its own scripting. Every one of them produced plausible output. **Check the
denominator, and check the run finished.**

---

## Log — accuracy & product track (from 2026-07-31)

The v0.1 build above answered "does the loop work". This track answers the question it
left open: does it work for the user in [docs/product.md](docs/product.md) — a developer
speaking accented English. Plan and phases in [docs/roadmap.md](docs/roadmap.md).

### 2026-07-31 — Phase 0: the R4 partial-latency gate, measured on accented speech

The Phase 0 accent run picked `small.en` as the default on WER grounds and left one
gate unrun: does `small.en` still show a partial within 1.5 s? Ran it. It does not —
and neither, in two regimes, does the `base.en` we ship today.

**What changed.** `scripts/asr_bench.py` grew a real gate in place of its six-line
prefix loop. It now cuts growing prefixes from the *longest real accented clip in each
L1 group* (16–20 s of EdAcc: Indian, Japanese, Russian, Spanish, us-control) plus the
SAPI `long.wav` as a control, decodes each with the exact production partial parameters
(`beam_size=1`, `vad_filter=False`, `condition_on_previous_text=False`), takes the
median of N repeats per (length, source) cell, and gates on the **worst source** — a
user does not experience a median. `--prefix-only`, `--repeats=N` and `--finals` flags;
results merge into `.bench/accent/prefix-gate.json` rather than overwriting, so
re-running one model to settle a noisy cell no longer deletes the other's numbers.
`summarise_gate()` is pure and unit-tested: worst-case-not-median, and no operating
point above a breach (a 16 s cell that passes over a failing 12 s cell is not reachable).

**Measured** — 195 timed decodes for `base.en` (39 cells × 5 repeats), 117 for
`small.en` (× 3), plus 144 finals decodes:

| prefix | base.en med / worst | small.en med / worst |
|---|---|---|
| 1 s | 0.78 / **1.67** | 2.60 / 2.62 |
| 2–8 s | 0.80–0.93 / 0.84–0.98 | 2.66–3.11 / 2.75–3.42 |
| 12 s | 1.02 / **1.76** | 3.37 / 6.34 |
| 16 s | 1.21 / **1.87** | 3.75 / 3.97 |

- **`small.en` breaches at every length, 1.7–2.5× over budget.** Whisper pads to one
  30 s mel window, so cost is nearly flat in prefix length: there is no short-utterance
  regime where this tier is fast. It cannot drive partials on this CPU, full stop.
- **`base.en` is clean only in the 2–8 s band.** At ≥ 12 s the Spanish clip costs
  1.73–1.91 s across five repeats — dense speech, more tokens, real work, reproducible.
- **The 1 s breach has a different cause, and it is now diagnosed.** The Japanese 1 s
  prefix scores `avg_logprob` −1.15, under faster-whisper's `log_prob_threshold` of
  −1.0, so the library silently re-decodes up the entire temperature ladder:
  **1.69–3.24 s uncapped vs 0.69–0.76 s at `temperature=[0.0]` — 2.4–4.7×, and
  nondeterministic run to run.** The Spanish cell is unaffected (`avg_logprob` −0.21),
  which is what proves the two breaches are not the same bug. The Phase 1 temperature
  cap is now a measured latency fix pointed straight at accented audio.
- **Finals** (full 10–20 s utterance, median/worst of 6 sources): base.en beam 2
  1.12 / 1.53 s, beam 5 1.37 / 2.52 s; small.en beam 2 4.07 / 4.90 s, beam 5
  4.87 / 6.12 s. Beam 5 costs ~20%. Finals are not latency-bound — the draft is held
  (R5) — so that is affordable where a partial is not.

**What this breaks.** The Phase 2 "default moves to `small.en`" decision, as written.
It splits instead: `base.en` on partials, `small.en` on the final that is actually
pasted. Phase 2 is rewritten as decided, and Phase 3 inherits a new open question —
past ~12 s of continuous speech even `base.en` misses R4, so partials must eventually
decode a trailing window rather than the whole utterance, or the utterance must be cut
before 24 s.

**What this says about the old number.** The SAPI control passes every cell at
0.73–0.79 s, reproducing stage 2b's "R4 gate passed: 0.75–0.91 s" almost exactly. That
gate was not run wrong. It was run on synthesised US English, and every breach found
today lives in the audio it never contained. Same lesson as the five in the section
above, sixth instance: **check the denominator.**

**91 tests green** (79 + 12 new in `tests/test_bench.py` covering `summarise_gate`,
`median` and `wer`). No product code changed this iteration — this was measurement.

### 2026-07-31 — Phase 0: the short-clip false-reject probe

The ≥ 1.5 s accent run reported zero filter drops in 900 decodes. That number proved
nothing about the case the audit actually predicts — short, quiet, borderline speech —
so it needed its own slice and its own metric. Both now exist.

**What changed.** `fetch_accent_data.py` grew `--tag`, `--min-words` and honest
duration bounds, so a differently-filtered slice lands in its own directory and its own
manifest instead of contaminating the WER benchmark's denominator; 280 clips of
0.31–1.48 s (median 0.70 s) came down that way. `accent_bench.py` grew `--manifest`
selection, per-slice results files, and per-clip false-reject accounting: `model_empty`
(the model produced nothing — an ASR failure) is separated from `false_reject` (the
model produced text and the filters deleted all of it), and every drop is attributed to
the exact rule that fired. The filter simulation is now the pure `apply_filters()`, and
`flow/clean.py` gained `invented_reason()` — same decision as `is_invented`, but naming
the rule, which is what the Phase 1 log line will need anyway. No behaviour changed:
a test asserts the two never disagree.

**Measured**, 280 clips, both models:

| | base.en | small.en |
|---|---|---|
| user sees nothing (model had text, filters ate it) | 3/280 = **1.1%** | 6/280 = **2.1%** |
| …where the deleted text was actually correct | **0** | **1** (0.36%) |
| under the proposed two-signal thin rule | 3 (1.1%) | 5 (1.8%) |
| drop paths | lib-skip 2, thin+unconfident 2 | lib-skip 3, thin+unconfident 2, thin 1 |
| model WER on this slice | 0.54–1.59 | 0.39–0.62 |

**What the drops actually were.** Eight of nine discarded a *mis-hearing* of a
backchannel: "UH" heard as "Mm.", "OKAY" as "Gay.", "NICE MM HMM" as "You". One lost
real content — `small.en` transcribed a 0.31 s Russian "YEAH" correctly and the
library skipped it (`no_speech` 0.674, `avg_logprob` −1.05). So the filter stack is not
eating accented speech at the rate the audit feared; it is mostly refusing to paste
garbage. Content loss sits inside P2's 1% bound. User-visible silence does not.

**Three findings that change the plan:**

1. **The library's skip is the dominant path** — 5 of 9 drops, unlogged, unattributable,
   inside faster-whisper. Defect 2 moves to the front of Phase 1.
2. **The thin-rule fix is nearly a no-op, and it has a cost.** It recovers one clip in
   280. Worse, the digital-silence hallucination in clean.py's own measurement table
   ('You', `no_speech` 0.691, `avg_logprob` −0.711) is thin but *not* unconfident, so
   deleting the thin test re-admits exactly the thing the filter was built to catch.
   The unit test found that, not the run. Phase 1 needs a third signal — the
   whole-utterance filler list — instead of just requiring two.
3. **`small.en` is much stronger on short clips** (Japanese 1.59 → 0.62, Indian
   0.97 → 0.57). Short utterances are where `base.en` collapses hardest, which is more
   support for the split-tier decision. RTF 4–5 on sub-1.5 s clips: a 0.7 s utterance
   still costs `small.en` ~3.5 s, the flat 30 s window again.

**The denominator, stated because it limits the claim: 31% of this slice (87/280) is
pure backchannel.** That is what sub-1.5 s conversational speech mostly is. EdAcc has
no short spoken *commands*, so this probe bounds the filter on short speech in general,
not on "delete that line" — which still needs recorded speakers, as the roadmap already
says.

**109 tests green** (91 + 18: `invented_reason` attribution and the reason/boolean
agreement property in `test_clean.py`, `apply_filters` accounting in `test_bench.py`).

### 2026-07-31 — Phase 1: decode parameters, and the loops the cap lets through

Two Phase 0 items were left. The Svarah dictation-register slice is **blocked on a
human**: `ai4bharat/Svarah` returns 401 (gated — someone must accept the terms and
supply an `HF_TOKEN`), VoxPopuli `en_accented`'s paged endpoint returns 500 on every
attempt leaving only 100 reachable rows (5 Spanish, no other anchor group), Common
Voice is 401/501, and L2-ARCTIC is a request form. Every WER number in this project
therefore remains a *conversational* stress test until a human unblocks that. The order
advanced to Phase 1.

**What changed.** `flow/asr.py` grew `decode_options(final)` — one place that owns the
decode parameters, imported by both benches so they cannot drift from the app. Partials
now decode at `temperature=(0.0,)` and finals at `(0.0, 0.2, 0.4)` with `beam_size=5`
(was 2). `flow/clean.py` grew `collapse_phrase_repeats()`, and `accent_bench.py` grew
`--beam` / `--temperature` / `--tag` so a proposed config can be A/B'd against the
shipped one over the same 300 clips.

**Why partials get no retries at all**, which is stronger than the roadmap's blanket
cap: faster-whisper re-decodes whenever `avg_logprob` falls under −1.0, and accented
speech fails that constantly. The Japanese 1 s prefix scores −1.15 and cost 2.40 s
median (1.48–3.69 s, nondeterministic) against a 1.5 s budget. A partial is replaced
within seconds, so buying quality with latency is simply the wrong trade there.

**Measured — latency:**

| | before | after |
|---|---|---|
| R4 longest clean prefix (base.en) | none | **8 s of speech** |
| 1 s accented prefix, worst of 6 sources | 1.67 s | **0.79 s** |
| 5 s noise clip, partial path, worst of 4 | 8.52 s | **1.37 s** |
| finals on 6 real 10–20 s utterances | 1.12 s median | 1.17 s median, 2.01 s worst |

**Measured — accuracy**, 300-clip accent slice, base.en, shipped (beam 2 + full ladder)
vs proposed (beam 5 + capped): indian 0.235 → 0.231, japanese 0.412 → **0.281**,
russian 0.192 → 0.178, spanish 0.187 → 0.187, us-control 0.280 → 0.276. Per clip:
53 better, 41 worse, 206 unchanged. The uncapped ladder is also *unstable* — Japanese
scored 0.299, 0.312 and 0.412 on three runs of the same 60 clips, because temperatures
above zero sample; the capped config scored 0.281, 0.286, 0.289.

**What broke, twice, and how it was caught.** Capping the ladder removes Whisper's own
escape from repetition loops — the hot samples are what break them. The first A/B
showed Spanish *worse* (0.214 → 0.263) on model WER, traced to one clip that came back
"I'm so sorry." thirty times: 87 edits against a four-word reference. Adding
`collapse_phrase_repeats()` fixed that, and the next run showed Indian at 0.450 — a
second loop, "I read on the bit of course" twenty-two times, seven words long, which
the six-word scan window had missed. Widening to twelve words settled it. A third bug
lived in the collapse itself: scanning longest-phrase-first matches a *multiple* of the
true period, so thirty copies of a three-word phrase read as fifteen copies of a
six-word one and collapsing to two left four behind. Shortest-first finds the
fundamental period. All three are pinned as tests with the measured text.

Note the interaction this de-risks: those 29 Spanish repeat segments are currently also
being dropped by the per-segment thin rule — the rule the *next* Phase 1 item relaxes.
With the phrase collapse in place, relaxing it no longer re-admits the loop, because
`asr.py` normalises the joined text after filtering.

**123 tests green** (116 + 7). `tests/test_asr.py` is new: the decode parameters are
one-line settings with 2.4× and 7.6× consequences, so they get tests that fail when
someone tidies them.

### 2026-07-31 — Phase 1: one filter, and every rejection on the record

Defect 2 was "a hidden second filter silently deletes accented speech". `flow/asr.py`
now passes `no_speech_threshold=None`, so faster-whisper's internal skip is off and
every rejection is Flow's own: a `Drop` record (text, the rule that fired, both
signals, partial-or-final) in a bounded log, drained by `Session` into its own `drop`
event kind and shown by the pill. The text is kept, which is what makes Phase 3's
rescue chip possible — a user cannot recover words they were never shown.

**A correction to the audit, and to the previous entry.** That entry said "the
library's skip is the dominant drop path — 5 of 9". That was an artefact of running the
library's rule first in the simulation. The library skips on `no_speech_prob > 0.6 AND
avg_logprob < −1.0`, and `< −1.0` implies `< −0.8`, so **every segment it ate was
already failing Flow's own rule**. Checked across all 681 segments of the short slice:
5 library-skips, 5 of them also dropped by clean.py. The measured false-reject rate is
therefore unchanged by this fix — 1.1% (base.en) and 2.1% (small.en), pre-fix column
identical to shipped column in the new bench output. Defect 2 is an **observability**
defect, not extra deletion. It still had to be fixed: once P8 calibrates thresholds per
user, Flow's rule can become looser than the library's fixed 0.6/−1.0, and the hidden
filter would start eating speech Flow meant to keep.

**`log_prob_threshold` is now `None`, decided by measurement.** Turning off the skip
also turns off the library's suppression of temperature fallback on probable silence,
which cost one 5 s noise clip 0.84 s → 3.66 s. The question was whether the
low-confidence retry earns that. It does not: on the 300-clip slice base.en scores
0.233 / 0.283 / 0.173 / 0.189 / 0.276 without it against 0.231 / 0.281 / 0.178 /
0.187 / 0.276 with it — inside the sampling's own run-to-run noise. So Flow retries a
final only when the output is *degenerate* (`compression_ratio_threshold`, the library
default), never merely when it was unsure. Noise finals land at 0.83–0.93 s again.

**What the short-clip re-run then exposed.** With beam 5, sub-1.5 s clips produce
repetition loops *spread across segments* — a 0.55 s clip whose reference is "UM" came
back as **29 segments of "Okay."**, and a 1.15 s clip as 29 of "It's like...".
`collapse_phrase_repeats` never saw them, because it requires two words; the old
`collapse_repeats` never saw them either, because it only touched tokens of at most two
characters. A single long token looping fell exactly between the two rules. Removing
the length condition (the limit of 3 stays, so "very very very good" is untouched)
closes it. Re-scoring the same decodes: short-slice base.en indian 0.748 → 0.741,
japanese 0.786 → 0.745, russian 0.536 → 0.503, us-control 0.882 → 0.850; small.en and
the 300-clip slice byte-identical, so the fix is targeted rather than broad.

**The trade this leaves, stated plainly.** On sub-1.5 s clips base.en is now much
better for the target population and worse for the control: japanese 1.592 → 0.745,
indian 0.966 → 0.741, russian 0.771 → 0.503, spanish 0.544 → 0.550, **us-control
0.733 → 0.850**. Beam 5 gives accented speech more room and gives a clean US voice more
room to ramble. On a slice that is 31% backchannel with 147–187 reference words per
group, that is a real but noisy signal — and the direction favours the people Flow is
for.

**139 tests green** (135 + 4). No measurement in this entry required re-decoding: the
collapse fix was scored by re-running the saved per-segment output through the new
normaliser, which is the same decode with different post-processing.

### 2026-07-31 — Phase 1: shortness stops being evidence

Defect 3 was that `clean.py` dropped any utterance of three words or fewer whenever
`no_speech_prob` crossed 0.6 — one signal, and a signal about *length*, not about
whether the model invented anything. Spoken corrections are short. The rule was
structurally biased against exactly the utterances Flow exists to handle.

**What changed.** A segment is now dropped only when the model doubts it was speech
**and** a second, independent signal agrees: the whole utterance is in the
known-hallucination list (`_FILLER_ONLY`), or the token confidence is poor
(`avg_logprob < −0.8`). Shortness is gone as a criterion. The filler list carries the
weight that "thin" used to, which is what keeps the trap from closing: the
digital-silence 'You' measured in clean.py's own table is short but **confident**
(0.691 / −0.711), so a naive "require two signals" would have re-admitted the exact
artefact the filter was built for. `scripts/accent_bench.py` grew `legacy_reason()` —
the old rule, kept in the bench rather than the app — so the change keeps a
before-and-after from the same decodes.

**Measured** by re-scoring saved per-segment output (no re-decoding: same audio, same
decodes, different filter), across the 280-clip short slice for both models and the
300-clip main slice:

| | legacy rule | shipped rule |
|---|---|---|
| segments where the rules disagree | — | **29 of 1416** |
| false-reject, short slice, base.en / small.en | 3 / 6 | 3 / 6 |
| app WER, spanish (main slice) | 0.183 | 0.187 |
| app WER, every other group | unchanged | unchanged |

**All 29 disagreements are the same clip** — the Spanish loop where `"I'm sorry."`
repeats, `avg_logprob` −0.11, text the model was *sure* about, deleted by the old rule
purely for being two words long. Those segments now survive the filter and are folded
back to two copies by `collapse_phrase_repeats` instead, which is the better mechanism:
content-based and deterministic rather than a length heuristic. The +0.004 on Spanish
is those four surviving words.

**What this does not show, stated because it is the point.** The case the rule exists
for — a short spoken command surviving a high `no_speech_prob` — **cannot be measured
on EdAcc, because EdAcc contains no spoken commands**. The corpus can price the change's
cost and it cannot price its benefit. So the benefit is pinned as a test instead
("delete that line" at 0.9 / −0.3, kept; "scratch that" at 0.95 / −0.5, kept), and the
real number waits on the recorded command set the roadmap has always deferred to human
speakers. A change justified by a failure mode rather than a corpus win is worth saying
out loud rather than dressing up.

**139 tests green.** Nine existing tests changed their expectations in this commit —
each one asserted the old rule, and each now asserts the new one with the measured
signals attached.

### 2026-07-31 — Phase 2: the split ships

The R4 gate decided this two iterations ago; this is the wiring. `WhisperTranscriber`
now holds two tiers — `base.en` for partials, `small.en` for the final that actually
gets pasted — each loading lazily and independently, each with its own lock.

**Why not one model, restated with the numbers that forced it.** `small.en` is 5–20%
relative better on every accent group, but the R4 gate measured it at 2.66–3.78 s per
partial *at every prefix length from 1 s up*, against a 1.5 s budget. Whisper pads
every input to one 30 s mel window, so there is no short-utterance regime where the
tier is fast. Finals are not bound that way — the draft is held on screen while they
run (R5) — so the accuracy goes where the pasted text is decided.

**Measured under the shipped decode config** (beam 5, capped ladder, one filter),
300 clips, model WER:

| group | base.en | small.en | relative |
|---|---|---|---|
| indian | 0.231 | 0.219 | −5% |
| japanese | 0.281 | **0.234** | −17% |
| russian | 0.178 | 0.151 | −15% |
| spanish | 0.187 | 0.166 | −11% |
| us-control | 0.276 | 0.221 | −20% |

`small.en` finals run at RTF 0.36–0.51, so a full 10–20 s utterance commits in 3.65 s
median (4.87 s worst) behind a held draft.

**What it costs, measured rather than estimated.** Resident memory: 38 MB baseline,
**181 MB with the partial tier alone, 450 MB with both**, 100 MB after the idle unload
releases them. On disk the second model is 464 MB against `base.en`'s 141 MB (`du`, not
the model card). So the split roughly doubles peak RSS. `--model base.en` pins both
tiers to one model for a machine where that matters, and a session that never finalises
an utterance never loads `small.en` at all.

**What broke.** Making `load()` load both tiers turned the existing
"concurrent loads build exactly one model" test red — correctly, because it now builds
two. But fixing that surfaced a real regression I had written myself: to avoid holding
a lock across a multi-second model download I had moved the build *outside* the lock,
which reinstated exactly the duplicate-build bug the lock existed to prevent — eight
racing threads could build eight models and discard seven. The fix is one lock per
tier, held across the build: per tier so preloading `small.en` never blocks a partial,
held across the build so a tier is only ever constructed once. Now asserted directly —
eight racing threads produce exactly two builds, one named `base.en` and one `small.en`.

The README's footprint section was wrong the moment this landed (it still described a
single 141 MB model and a 384 MB install), so it now carries the measured two-model
numbers, and `scripts/soak.py` was switched to the shipped two-tier default — a second
resident model is precisely the kind of thing that soak test exists to catch drifting.

**142 tests green** (139 + 3: partials never load the finals model, finals do, and
unload releases both).

### 2026-07-31 — Phase 1: the personal lexicon, and what biasing actually costs

`flow/lexicon.py` reads `~/.flow/lexicon.txt` — one term per line, `#` comments,
re-read whenever mtime or size changes so a name added mid-session lands on the next
utterance. Terms are deduplicated case-insensitively and capped at 64 *whole* terms,
because faster-whisper truncates the prompt at 223 tokens silently and mid-term, and
half of "Kubernetes" biases the decoder toward nothing. `decode_options()` grew a
`hotwords` parameter; both tiers use it; `--lexicon PATH` and `--no-lexicon` override.

**Then the harness said the feature was the wrong shape.** `scripts/lexicon_bench.py`
asks three questions on the EdAcc slice with `small.en`:

| condition | WER | recovery |
|---|---|---|
| baseline, 100 clips | 0.223 | — |
| oracle lexicon (the rare words that decode missed) | 0.216 | **29/85 = 34%** |
| 61 irrelevant terms | **0.265** | — |
| baseline, 60 clips | 0.221 | — |
| oracle | 0.215 | 15/55 = 27% |
| 61 irrelevant terms | **0.252** | — |
| baseline, 40 clips | 0.201 | — |
| **8** irrelevant terms | **0.278** | — |
| 32 irrelevant terms | 0.274 | — |

So biasing recovers about a third of the rare words it is aimed at, worth ~3% relative
WER — and costs **14–38% relative WER on speech containing none of the terms**, which
is the common case, because a lexicon is the user's vocabulary rather than this
utterance's. Three independent runs on different clip subsets agree on the direction.
The harm did **not** scale with lexicon size: eight irrelevant terms hurt as much as
sixty-one, which kills the obvious "just keep it short" advice.

The oracle column is an oracle and is labelled as one everywhere it appears — the
lexicon is built from the answer key, so 34% is the ceiling of the mechanism, not a
product claim.

**What that changed.** The file does not exist by default and creating it is the
opt-in, which is now a stated design decision with numbers behind it rather than an
accident of implementation. The startup line prints the term count, because a lexicon
someone forgot creating is a very plausible cause of "it suddenly got worse". And the
real fix is named where it belongs: Phase 3's constrained re-decode, which biases only
when the first pass produced something phonetically near a term — spending the cost
where it pays instead of on every utterance.

**Latency, separately measured:** a full 64-term lexicon costs +6% on a `base.en`
partial (0.69 → 0.73 s, against a 1.5 s budget), +13% on a `base.en` final, and +27%
on a `small.en` final (2.33 → 2.97 s). Affordable; it is the accuracy that is not.

**What broke.** Two harness bugs, both caught before they produced a number: the first
draft decoded the distractor condition twice (once discarded for timing), and the
`--harm` sweep silently did not run because a scripted edit did not match — the sweep
printed the *standard* table instead, which looked like a perfectly plausible result.
It reproduced the harm finding on a fresh 60 clips, which is the only reason it was
obvious something was off. A harness that fails by printing the wrong valid answer is
the failure mode this project keeps rediscovering.

**161 tests green** (142 + 19: parsing, the cap, hot reload, a deleted file, undecodable
bytes, the disable path, and that both tiers actually receive the string).

### 2026-07-31 — Phase 1: the command grammar stops shattering (defect 4, first half)

Five fixes in one item, because they are one failure: a command that is heard slightly
wrong is silently appended into the user's text as dictation.

**Politeness on every pattern.** The lead-in was hesitation only ("no", "actually") and
only on two patterns. It is now a repeatable prefix on all of them and includes the
half that was missing — "can you", "could you please", "would you", "just". A speaker
who asks a tool politely was having their request typed into the draft verbatim, and
politeness is exactly what a non-native speaker reaches for.

**Verb snapping**, three mechanisms because one is not enough: edit distance ≤ 1,
adjacent transposition ("deleet" → "delete", two substitutions by the strict definition
but a single slip of the ear), suffix stripping *then* fuzzy matching ("deleting" →
"delet" → "delete"), and an explicit alias table for the mis-hearings too far away for
any distance metric — "the lead" is three edits from "delete".

**The safety property that makes aliases acceptable**: a snapped reading is accepted
**only when it produces a local edit whose target is really in the draft**. So snapping
can promote a mis-heard command to what the user meant, and can never demote dictation
into an edit. "stop" only becomes "swap" when the words after it are in the draft.

**`re.escape` on the replacement.** `replace_all` passed the payload to `re.sub` as a
template, so a dictated `\1` or a Windows path was read as a group reference — either
an exception or a silent splice of captured text. It substitutes through a function now.

**Stale force-next.** The Refine/Continue chip was consumed only when a draft was held.
Press Refine, say something that starts a fresh draft, and the override sat there until
it silently routed an unrelated later sentence to the CLI. It is now consumed on every
routed utterance and expires after 30 s, announced when it does. `force_next` became a
property so that *assigning* it stamps the time — the UI, the tests and the probes all
set it directly, and a TTL depending on each caller to remember a timestamp is a TTL
that does not apply.

**Measured** with the new `scripts/command_bench.py`:

| corruption (synthetic) | n | patterns only | + snapping |
|---|---|---|---|
| clean | 14 | 100% | 100% |
| politeness lead-in | 112 | 100% | 100% |
| verb suffix | 14 | 0% | **100%** |
| one substituted letter | 14 | 14% | **100%** |
| adjacent transposition | 14 | 14% | **100%** |
| known mis-hearing | 12 | 0% | **100%** |

The corruptions are synthetic and labelled as such throughout — they are the failure
classes the audit named, not recordings of accented speakers, which is still deferred.
The politeness row reads 100% in both columns because the lead-in now lives in the
patterns themselves; its gain is against the *previous* grammar, not against the column
beside it.

**And what it costs, which is the number that matters:** nothing. On 20 adversarial
sentences that start like commands, with drafts deliberately full of their own words,
snapping adds **no** misroutes — 4 of 20 either way, all four being the exact grammar's
own shape heuristic, which is undoable by design. On 580 real EdAcc utterances: 0
misroutes both ways.

**Check the denominator on that last one.** `snap()` alters exactly **one** of those 580
real utterances, so the corpus mostly cannot fail this test. That is why the adversarial
set exists, and it is the set that found the actual defect below.

**What broke.** The first version of snapping cost precision: suffix stripping turned
two sentence-opening gerunds into commands — "Deleting a branch does not delete the
history" became a delete, "Changing Tuesday to Wednesday broke the booking" became a
replace. Both are dictation; both are long. Every command in the inventory is five words
or fewer, so snapping now applies only to utterances of six words or fewer, counted
*after* the lead-in. That guard then exposed a second bug: `snap()` was reading the
first token of the whole utterance, so "could you please deleting Tuesday" only ever saw
"could". The lead-in is split off and re-attached now. Both are pinned as tests, and the
harness reports 4/20 either way again.

**180 tests green** (178 + 2). Two of the three bugs in this entry were found by the
harness rather than by the tests, which is the argument for building the harness first.

### 2026-07-31 — Phase 3: matching the target by sound (defect 4, second half)

The remaining half of the command defect is not the verb but the *target*. The user
says "change Sameer to Samir"; the draft, transcribed from the same accented voice
seconds earlier, says "summer". An exact substring search finds nothing, so a free
local edit escalates to a ~7 s CLI call over text that does not contain the word.

**What changed.** `flow/phonetic.py` vendors Double Metaphone — about 200 lines of
table lookup, stdlib only, so R16's three dependencies hold. It returns two codes
because English pronunciation is genuinely ambiguous ("ch" is K in "school", X in
"chair"), and two words match if any codes agree. `similarity()` blends the phonetic
key with `difflib`'s spelling ratio, because neither is sufficient alone: keys are
coarse enough that "Tuesday" and "Thursday" are neighbours, and spelling alone misses
exactly the substitutions accent produces. `find_span()` / `find_spans()` then search
word windows sized around the target's word count ±1, since a mis-transcription moves
word boundaries as readily as letters — "Sameer" comes back as "some ear" as often as
"summer". Both exact-match sites now route through it.

**Measured** with `scripts/command_bench.py`, extended for this:

| threshold | pairs found | correct span | false spans (354 real utterances) |
|---|---|---|---|
| 0.75 | 10/10 | 10/10 | 19 |
| 0.80 | 10/10 | 10/10 | 10 |
| **0.82** | **10/10** | **10/10** | **4** |
| 0.85 | 7/10 | 7/10 | 4 |
| 0.90 | 5/10 | 5/10 | 3 |

0.82 is where recall is still complete and the false-span curve has flattened. And the
number the whole item exists for: **10 of 10 corrections whose target the draft spells
differently now stay local and edit the right span**, where every one of them
previously paid a ~7 s CLI call to rewrite text that did not contain the word.

**Denominators, because they are small.** Ten mis-transcription pairs, hand-written
from the substitution classes accent produces (vowel colouring, lost syllable
boundaries, th/t, v/w, f/ph). They are not recordings. The 354 false-span trials *are*
real EdAcc utterances, each paired with a content word from a distant utterance and
checked absent — that side has a denominator worth quoting; the recall side does not
yet, and will not until there are recorded speakers.

**What broke.** Three things, two of them mine and both silent. A scripted edit to
`apply_local`'s `replace_all` did not apply — the pattern contained a backslash — so
the phonetic path was wired into every operation *except* that one, and the tests
passed until the one test that covered it failed. Then the appended `spans()` function
landed after the `if __name__` block, so `main()` ran before it existed. And a heredoc
turned `\n` inside an f-string into a real newline, producing an unterminated literal.
None of these are interesting bugs; all three are the same lesson, which is that a
scripted edit that silently matches nothing looks exactly like a scripted edit that
worked.

**200 tests green** (180 + 20): the metaphone keys, the pairs that must match and the
pairs that must not, empty and vowel-only input, span selection including the
last-occurrence rule, non-overlap in `find_spans`, and six end-to-end corrections that
now land locally.

### 2026-07-31 — Phase 3: keeping the head of the word that opened the gate

Defect 5, first half. A gate can only open once it has heard something loud enough,
which means the quiet head of the word that opened it is already behind you. That head
is not silence — it is the unaspirated stop, the soft fricative, the approximant
carrying the consonant — and it is exactly the part an accented utterance can least
afford to lose.

**What changed.** `SpeechGate` keeps a bounded ring of the last four blocks (256 ms)
heard while quiet, and hands them over when it opens. `Session._pump_audio` prepends
them to the utterance. The ring is drained on take and cleared on reset, so a second
utterance cannot begin with the head of the first. Four blocks of float32 at 16 kHz is
16 kB, which is the entire cost.

**Measured** with the new `scripts/gate_bench.py`. It does not test the gate in
isolation: it runs the production `SpeechGate` over 80 real clips, reassembles exactly
what the session would have captured, and decodes *that*.

| condition | WER | audio kept |
|---|---|---|
| ungated (whole clip) | 0.284 | 100% |
| gated, no pre-roll | 0.291 | 97.4% |
| gated, 128 ms | 0.278 | 98.0% |
| gated, 256 ms | 0.282 | 98.2% |
| gated, 512 ms | 0.281 | 98.4% |

Gating without pre-roll deletes **2.6% of the audio** and costs about 2.5% relative
WER. Any pre-roll from 128 ms up puts WER back at the ungated level — and the three
settings cannot be told apart at this denominator: the spread is 0.004, roughly six
edits in 1,400 reference words. So 256 ms is the middle of a range the data says is
flat, not a tuned optimum, and it is written down that way.

**A methodology note worth keeping.** The first run used the app's real finals config,
whose temperature ladder samples — and the run-to-run noise from that is the same size
as the effect being measured. Re-running with the decode pinned to a single temperature
changed the ungated number by 0.002 and left the conclusion intact, but the first table
was not evidence of anything. When the variable under test is the audio, everything
else has to be deterministic.

**The denominator, as usual.** EdAcc clips are pre-trimmed to utterance boundaries, so
most of what this measures is the gate re-opening after a mid-utterance pause rather
than a cold start on a soft onset. And these are energetic conversational speakers; the
quiet speaker in a noisy room, which is where the audit expects pre-roll to matter
most, is not in this corpus at all.

**What broke.** Two tests asserted absolute captured-audio lengths, which failed
because the capture also contains the hangover blocks — a real fact about the gate that
the assertions were not about. They asserts the *difference* between pre-roll settings
now, which is the thing under test and is immune to hangover changes. Also added a
regression test for the digital-silence floor clamp, since implementing the pre-roll
meant reordering the branch that clamp lives in.

**210 tests green** (200 + 10).

### 2026-07-31 — Phase 3: one cheap re-listen before paying for the CLI

When a correction's target is nowhere in the draft, the router escalates to the agent
CLI — ~7 s, to edit text that does not contain the word it was asked about. That is
almost always the wrong diagnosis: the shape was a correction, so the user *was*
correcting something; the model just mis-heard which word.

**What changed.** `Plan` now records why it is semantic. `escalated=True` marks the
four sites where a correction shape failed only on target lookup; a genuine rewrite
verb never sets it. On an escalated plan the session re-decodes the same audio —
already kept for exactly this — biased by `edits.command_bias()`: every trigger verb
plus the draft's own words longer than three letters, longest first, capped at 48
terms. The cap and the ordering come from the lexicon measurement, which was emphatic
that a long prompt full of words that are not being said costs accuracy.

The decode worker grew a third queue for these. Rescues are queued like finals rather
than latest-wins, because dropping one means paying the CLI call this exists to avoid,
and `hotwords` is passed to the transcriber only when non-empty, so every existing
fake Transcriber in the tests still satisfies the protocol.

**Measured** with the new `scripts/rescue_bench.py` — the command inventory
synthesised through two SAPI voices, buried in white noise at falling SNR, decoded
with the production finals config (`small.en`):

| SNR | first read | after the biased re-read | re-read cost |
|---|---|---|---|
| clean | 23/24 | **24/24** | 2.06 s |
| 15 dB | 23/24 | **24/24** | 2.01 s |
| 10 dB | 21/24 | **24/24** | 2.01 s |
| 5 dB | 20/24 | **24/24** | 2.04 s |
| 0 dB | 15/24 | **21/24** | 2.05 s |

Every first-read failure recovers down to 5 dB SNR, and six of nine at 0 dB, for about
**2.0 s against the ~7 s** the CLI costs — and what comes back is a correct local edit
instead of a rewrite of the wrong text.

**What this is not.** SAPI is a US-English synthesiser and white noise is a stand-in
for "the decoder is unsure". This measures the mechanism — can biasing recover a
command the model got wrong — and says nothing about how often accented speech needs
it. That benchmark still needs recorded speakers.

**What broke, and what it revealed.** The first version of the rescue test used
"change Toosday to Friday" as the mis-hearing, and the rescue never fired: the phonetic
matcher from the previous iteration already resolves "Toosday" to "Tuesday", so the
plan was local before any re-decode. Good news dressed as a failing test — the two
layers cover different distances, and the test now uses a target no phonetic search can
reach. Chasing it also surfaced a real defect in the phonetic path: word windows are
whitespace-delimited, so matching the last word of a sentence included its full stop,
and replacing that span deleted the punctuation — "Meeting on Tuesday." became "Meeting
on Friday". Spans are now trimmed to alphanumeric boundaries.

**222 tests green** (210 + 12).

### 2026-07-31 — Phase 3: "that was a command", and what it revealed

The last Phase 3 item. When Flow mishears the *kind* of an utterance and types a
command into the draft, recovering costs two utterances — undo, then say it again —
and the second attempt is no likelier to be heard correctly than the first.

**What changed.** A spoken trigger ("that was a command / an instruction / an edit",
plus "i meant that as…" and the usual lead-ins) and a chip that appears only when
there is something to re-read. `Session.rescue_last_append()` withdraws the append
*first*, so the re-plan sees the draft as it was when the command was spoken — the
target of a correction lives in that text, not in the text with the correction stuck
on the end. If the words still are not a command, the stored audio is re-decoded with
the command bias. If that fails too, `_give_back()` restores the words exactly where
they were. Dictation is never the price of a failed guess.

**Measured — and it changes how to read the previous entry.** Splitting misroutes by
how they present:

| SNR | first read | silent appends | escalations | after the re-read |
|---|---|---|---|---|
| clean | 23/24 | 1 | 0 | 24/24 |
| 15 dB | 23/24 | 1 | 0 | 24/24 |
| 10 dB | 21/24 | 3 | 0 | 24/24 |
| 5 dB | 20/24 | 3 | 1 | 24/24 |
| 0 dB | 15/24 | 8 | 1 | 21/24 |

Of 17 misroutes across all noise levels, **16 arrived as silent appends and exactly one
as an escalation**. The automatic constrained re-decode built last iteration only fires
on escalations, so it covers about 6% of the failures; this chip covers the other 94%.
Both end in the same biased re-read at ~2.0 s. That is worth saying plainly: the
automatic path is the smaller half by an order of magnitude, and the entry before this
one would read as if it were the main event.

**What broke.** Three things, and one of them is a lesson about tooling rather than
code. A scripted edit wrote a literal **backspace character** (0x08) into the regex
where `\b` was intended — invisible in the file, invisible in a diff, and it made the
pattern match nothing. It also made the Read view and the file disagree, so two
follow-up edits failed to apply against text that looked correct on screen. Fixed by
matching `chr(8)` explicitly.

The other two were mine in the tests: three cases set `force_next = "append"` *after*
the utterance had already been routed, so the misroute they meant to stage never
happened — the helper now presses Continue before the utterance, which is the only
order that means anything. And "please, that was a command" did not trigger, because
the politeness branch of the lead-in did not allow a trailing comma. It does now.

**231 tests green** (222 + 9). Phase 3 is complete.

### 2026-07-31 — Phase 4: "make it a proper prompt" (P5)

The first product item. Dictating a prompt and writing one are different acts: spoken
thought arrives as context, correction and afterthought in whatever order it occurred
to the speaker. Asking a CLI to "make it a proper prompt" as free text makes it guess
what that means; naming the transformation does not.

**What changed.** A dedicated verb in `edits.py` — checked *before* the generic
`make it …` rewrite pattern, which would otherwise swallow it — producing a semantic
plan with `op="polish"`. `refine.py` gained its own instruction for that op: order as
context, then constraints, then the ask; keep every concrete detail verbatim; invent
nothing; no preamble. The spoken phrase is deliberately not included in what the CLI
sees, because the user named a transformation rather than writing an instruction.

The commentary guard had to be split. A revision that quadruples its input is the model
explaining itself, but a *polish* legitimately grows — structure costs words that
rambling does not spend — so polish allows 8× + 600 where a revision allows 4× + 200.
A runaway 20 kB response is still refused.

**Measured** with the new `scripts/polish_check.py` — five rambling technical
dictations through `codex`, each carrying tokens a reader actually needs:

| | |
|---|---|
| detail retention (versions, paths, names, error codes) | **15/15** |
| latency | median **5.3 s**, max 8.3 s |
| growth | median **×1.1** |
| preamble despite being forbidden | **0/5** |

Latency sits inside the existing ~7 s CLI budget at the median and above it at the
tail, which is the same shape stage 2a measured for a plain rewrite (5.7–7.3 s).

**What broke, and what it says about the measurement.** The first run scored 14/15,
having "lost" the token `fifteen`. It had not: *"postgres fifteen"* came back as
*"PostgreSQL 15"*, which is the correct rendering of a spoken number in written text.
The checker was wrong, not the feature. Counting a numeral as satisfying its spoken
form takes retention to 15/15 — and the lesson is the familiar one, that a metric which
looks like a defect is worth reading before it is worth believing.

Also: two scripted edits again wrote a literal backspace (0x08) where `\b` was intended
— the same failure as the last iteration, this time caught in one step because the
symptom was recognised. In this environment, regex escapes do not survive a heredoc; the
editor tools or `chr(92)` do.

**Whether the output is better is still a human's call.** P5's acceptance test says "a
reviewer judges it stronger", and nothing here measures that. The before/after pairs
are written to `.bench/polish.json` for exactly that reading.

**242 tests green** (231 + 11).

### 2026-07-31 — Phase 4: Send stops erasing (P6)

Send used to clear the draft and forget it. That is right for a typewriter and wrong
for what people actually do with one: a prompt is rarely finished on the first send,
and the next utterance is usually a follow-up rather than a fresh thought.

**What changed.** `flow/thread.py` holds the sent prompts, bounded twice over — by turn
count and by total characters — because R8 says a long session must cost what a short
one costs. `Session.send()` appends there instead of dropping the text. Two verbs join
the grammar, and they are deliberately the *only* commands that mean anything when the
draft is empty, which is precisely the state Send leaves behind: "bring back my last
prompt" restores it, and "follow up" (optionally carrying its own words — "follow up:
and add a rollback") opens the new draft as a continuation.

`refine()` takes a `context` list, rendered as labelled background with an explicit
instruction not to repeat or rewrite it. It is attached **only** when the draft was
opened as a follow-up: a follow-up like "and do the same for the other endpoint" is
meaningless without the thread, and an ordinary "make it more formal" should not pay
1.6 kB of prompt for context it does not need.

**Measured:**

| | |
|---|---|
| 5,000 sends of a realistic prompt | **20 turns, 1,640 chars** (caps 20 / 20,000) |
| tail handed to the CLI | 18 turns, **1,476 chars** (cap 1,500) |
| CLI prompt with context attached | 220 → 1,823 chars (**+1.6 kB**) |
| one 200,000-char send | kept whole, as a single turn |

That last row is a deliberate exception to the character cap: an oversized prompt is
never dropped, because "bring back my last prompt" has to work for a long one too. It
is bounded by the utterance limit above it rather than by this store.

The +729% relative growth of the CLI prompt reads worse than it is — the absolute
number is 1.6 kB against a call already measured at ~19.7 k tokens, and it is only
attached on follow-ups. Quoting the percentage without the absolute would be the
misleading half.

**What broke.** One test asserted that a follow-up carrying an instruction ("follow up:
make it more formal") would reach the CLI with thread context. It does not, and should
not: the words after "follow up:" are *dictation*, the thing being followed up with,
not an instruction about a draft that is empty at that moment. The test now runs the
realistic sequence — send, open a follow-up, dictate into it, then ask for the rewrite —
which is what actually exercises the context path. The feature was right; the test had
collapsed two steps into one.

**263 tests green** (242 + 21).
