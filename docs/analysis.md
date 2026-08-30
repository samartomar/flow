# Flow — analysis of the idea

Local, English-only, voice-first dictation with a talk-to-it refine loop.
Reference product: Wispr Flow. This document is the analysis of the raw idea,
not the build plan (see [PROGRESS.md](history/PROGRESS.md) for that).

Status of every claim below: `CONFIRMED` = verified on this machine ·
`PLAUSIBLE` = mechanism known, not yet run · `SPECULATIVE` = pattern-match only.

---

## 1. The idea, decomposed

The raw idea was a single dictated paragraph. Split into testable requirements:

| ID | Requirement | Reading of the intent |
|---|---|---|
| R1 | "product like wisprflow.ai" | Speak, get text into whatever app has focus |
| R2 | "only english as language" | One English-only model; no multilingual weights |
| R3 | "light weight but functional" | Fast start, low idle RAM, small install |
| R4 | "while speaker it is getting text" | Live partial transcript **during** speech |
| R5 | "when you stop it has you can refine" | On stop, text lands in a held draft — not sent yet |
| R6 | "you can talk it to refine / takes corrections" | Voice instructions **edit** the draft |
| R7 | "continue talking to it" | Voice **appends** to the same draft |
| R8 | "handle long running" | Multi-minute sessions; no unbounded memory or latency growth |
| R9 | "use any existing cli available, no api key nothing" | Refinement shells out to an already-authenticated agent CLI |
| R10 | "short codex have better integration support" | Prefer `codex`; keep the CLI swappable |
| R11 | "cli can be limited... no heavy lifting for it" | CLI does short text edits only — never ASR, never long context |
| R12 | "small interface... floating mic" | Always-on-top pill, not a window |
| R13 | "small wave display will color" | Live level/wave; colour encodes state |
| R14 | "when text ready float up" | Draft bubble rises above the pill |
| R15 | "refine and continue or send" | Three actions from the bubble |
| R16 | "super light, dependencies at min" | Hard constraint, not a preference |
| R17 | "hard cap of 5hr" | Build budget, not a runtime property |

**Non-goals** (explicitly out, to protect R16/R17): multilingual, cloud ASR,
custom vocabulary training, per-app formatting profiles, mobile, installer/MSI,
speaker diarisation, macOS/Linux.

---

## 2. The one real tension

R4 (live partials) × R16 (min deps) pull against each other. Streaming ASR needs
either a streaming-native model (extra runtime) or chunked re-decode of a
batch model (simple, but partials lag ~0.5–1.5 s and can flicker as they firm up).

Resolution: accept chunked re-decode. Flicker is acceptable because the draft is
*explicitly* non-final until Send — the product already has a "text isn't
committed yet" stage (R5), so a wobbling partial is on-brand rather than a bug.

---

## 3. Architecture options considered

### Option A — Python 3.12 (via `uv`) + faster-whisper + tkinter ← **chosen**
- **ASR**: `faster-whisper` (CTranslate2), `base.en` int8 on CPU.
- **Deps**: `faster-whisper`, `sounddevice`, `numpy` declared. The "~6 transitive"
  estimate here was **wrong: it is 28 packages, 243 MB** `CONFIRMED`. Two of the
  largest are unreachable from this app (`onnxruntime` 38.6 MB, needed only for the
  Silero VAD this code never enables; `av` 65.9 MB, needed only to decode audio files),
  and `scripts/slim.py` removes them for a measured 106 MB saving.
- **VAD**: *not* faster-whisper's Silero, as first assumed. A ~20-line RMS gate with an
  adaptive noise floor answers "has the talking stopped?" well enough, and avoids
  carrying `onnxruntime` for it.
- **GUI**: `tkinter` — **stdlib, zero extra dep**. Borderless, `-topmost`, `-alpha`,
  canvas for the waveform.
- **Injection**: `ctypes` (stdlib) — clipboard + `SendInput` Ctrl+V.
- **Why**: `uv` is already installed `CONFIRMED`, so the whole dep tree is one
  isolated command the user never manages. GUI + hotkeys + injection all come from
  stdlib, which is where "min deps" is actually won.
- **Risk**: LOW. Every piece is well-trodden.

### Option B — Python + `whisper.cpp` prebuilt binary / `whisper-server`
- Lightest *pip* tree (`sounddevice` + `numpy` only), one long-lived localhost
  server process — a genuinely good fit for R8.
- **Rejected as primary** because it adds a fetch-and-verify-a-Windows-binary step
  whose cost is unbounded inside a 5 hr cap. Kept as the documented escape hatch
  if Option A's install turns out heavy.

### Option C — Rust (egui/Tauri) + whisper-rs
- Smallest possible distributable, no Python at all. `cargo` is present `CONFIRMED`.
- **Rejected**: GUI + audio + FFI + a state machine from scratch does not fit 5 hr.
  This is the right v2 rewrite target once the design is proven.

### Option D — Windows built-in speech (`System.Speech` / WinRT `SpeechRecognizer`)
- Zero model, zero download.
- **Rejected**: `System.Speech` accuracy on free-form dictation is poor, and the
  good WinRT dictation path wants network. Also `dotnet` is absent `CONFIRMED`.

---

## 4. Design of the refine loop (R5–R7, R9–R11)

State machine:

```
IDLE ──hotkey──▶ LISTENING ──silence/hotkey──▶ DRAFT
                     ▲                          │
                     └──────── continue ────────┤
                                                ├── refine ──▶ (CLI) ──▶ DRAFT
                                                └── send ────▶ inject ──▶ IDLE
```

### The ambiguity that has to be solved
In `DRAFT`, when the user speaks, is it **more dictation** (R7 append) or a
**correction** (R6 edit)? Three ways to decide:

1. **Explicit modes** — separate hotkey/chip per intent. Zero ambiguity, zero cost,
   but costs the user a deliberate action every time.
2. **LLM classifier** — ask the CLI "append or edit?" every utterance. Violates R11
   directly and adds a round-trip to every single utterance.
3. **Local heuristic** — utterances opening with a correction verb
   (`change`, `replace`, `delete`, `make it`, `no,`, `actually`, `scratch that`,
   `instead`, `fix`) route to edit; everything else appends. Instant, no CLI, no deps.

**Chosen: 3 as the default, 1 as the override.** The heuristic will be wrong
sometimes, which is tolerable *only because* the draft is non-destructive and
undoable — a mis-route costs one undo, not lost text. This keeps the CLI out of
the hot path entirely, which is what R11 asks for.

**As built, option 3 turned out to need two refinements** (see [history/PROGRESS.md](history/PROGRESS.md) stages 4
and 5):

- **The utterance alone is not enough — the draft is part of the decision.**
  "Delete key handling is broken" is dictation about a keyboard; "delete key handling"
  is an instruction. Nothing in the words separates them. What separates them is
  whether the target text exists in the draft, so weak verbs (`delete`, `capitalize`,
  `lowercase`) only fire when it does. Strong shapes (`change X to Y`, which is hard to
  say by accident) instead escalate to the CLI when the target is missing.
- **The routing is three-way, not two-way.** Because a CLI call costs ~7 s measured,
  "edit" splits into **local** (literal string operations, applied in microseconds —
  replace, replace-all, delete, delete-range, insert, case changes, undo) and
  **semantic** (genuine rewrites like "make it more formal"). Only the semantic branch
  ever starts a subprocess.

### CLI adapter contract (R9, R10)
Both candidates are installed and already authenticated, so no key ever touches
this codebase `CONFIRMED`:

```
codex exec --skip-git-repo-check "<prompt>"    # preferred per R10
claude -p "<prompt>"                           # fallback
```

Guards that enforce R11 ("no heavy lifting"), **as built**:
- Invoked **only** on a *semantic* rewrite — never for transcription, never on append,
  and never on a literal correction.
- **Stateless**: input is `(current draft, one instruction)`. No history, no audio.
- **Input cap** 2000 chars; past that only the tail is sent, cut on a sentence
  boundary, and the untouched head is re-joined to the result.
- **Hard timeout 20 s**, not the ~6 s first sketched here. Measurement put a normal
  call at 5.7–7.3 s, so a 6 s limit would have killed healthy calls. On timeout the
  pre-edit draft is kept and the pill flashes red.
- `stdin` is closed explicitly: `codex` blocks reading it and would otherwise hang to
  the timeout.
- Output needs **no parser**. Both CLIs write only the answer to stdout and put their
  banner and token accounting on stderr — the earlier belief that output was polluted
  came from merging the streams with `2>&1`. What remains is a light guard: strip stray
  code fences and surrounding quotes, and **reject a reply that balloons**, since that
  is the model explaining itself rather than revising.

### Long-running behaviour (R8), as built
- Mic blocks land in a **bounded queue that drops the oldest** when full, so a stalled
  consumer loses audio instead of growing memory. Full-session audio is never retained.
- An utterance is **cut and committed before 24 s**, because decode cost is flat only
  inside Whisper's single 30 s window (measured) — this is what keeps latency constant
  in a long session.
- Only the trailing 2000 chars of a draft ever reach the CLI, so refine cost stays flat
  as the draft grows. *(The committed-prefix/editable-tail split originally sketched
  here was not built: the 2000-char tail cut in `refine.py` achieves the same bound with
  far less machinery, and `Draft` stayed a single string plus an undo stack.)*
- The **input device** is health-checked every 5 s and reopened if it dies. The decode
  worker instead swallows and reports per-decode exceptions, so it cannot die and needs
  no restart.
- Idle > 30 min → **unload the models only**. The mic stays open, a deliberate narrowing
  of the "release the mic" idea above: releasing it would leave the app unable to hear
  its own wake-up, and the mic is cheap while the models are ~605 MB (`base.en` 141 MB
  for partials plus `small.en` 464 MB for finals — this line said "the model is 141 MB"
  while there were two tiers resident, understating its own case fourfold). Was 5 min,
  which sat *inside* the gaps of an ordinary session: the common case was not reclaiming
  memory from somebody who had left, it was paying a reload in the middle of their first
  sentence back. The chord now also warms on press-down, so the load happens during the
  hold rather than inside the first utterance.
- Undo history is bounded by **both** snapshot count and total characters, since 30
  copies of a long draft is where undo quietly becomes megabytes.

---

## 5. Interface spec (R12–R15)

Two borderless, always-on-top tkinter windows.

As built (numbers here are the shipped ones, not the sketch):

- **Pill** 152×40: drawn mic glyph + **18** mirrored level bars (R13). Drawn rather than
  fonted so no emoji font has to be present.
  Colour = state: `slate` idle/disarmed · `green` listening · `amber` **draft held,
  awaiting a decision** · `blue` refining (CLI running) · `red` error.
  *(Amber means "your text is waiting", not "transcribing" — the state that actually
  needs the user's attention.)*
- **Bubble** 380 wide, height fitted to the wrapped text: rises above the pill when a
  draft exists (R14), with three chips: **Refine · Continue · Send** (R15). Partials are
  rendered dimmed and italic, because they can contain hallucinated fragments at word
  boundaries and "not final yet" has to be visible.
  **Not keyboard-editable** — that was in this spec but never requested, and the product
  as described is voice-driven, so it was not built.
- Rounded/translucent look via `-alpha` plus a canvas rounded-rect. All five window
  attributes were probed on this machine before the UI was written and all work, so the
  solid-background fallback mentioned here proved unnecessary and was not built
  `CONFIRMED`.
- Global hotkey: tkinter cannot register one, so `ctypes.RegisterHotKey` on a dedicated
  message-loop thread (stdlib — no `keyboard`/`pynput` dep) `CONFIRMED`. Each action
  carries an ordered list of alternatives: `ctrl+alt+space` was already owned by another
  process on this machine, and `RegisterHotKey` merely returns false, so without
  fallbacks it would have shipped as a silently dead shortcut.

---

## 6. Risks, ranked

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| 1 | Agent-CLI latency makes "refine" feel slow | **HIGH — CONFIRMED, worse than estimated** | Measured **7.26 s** (`codex`) / **6.72 s** (`claude`) — a floor, not a cold-start penalty. Resolved by moving literal corrections off the CLI entirely (§4) |
| 2 | `base.en` accuracy too low to feel like Wispr Flow | HIGH — **still open** | WER 0.000 on synthesised speech `CONFIRMED`, which only proves the pipeline is wired right. Real-mic WER needs the user at a microphone. `small.en` is a one-line upgrade at ~3× compute |
| 3 | tkinter transparency / always-on-top quirks on Win 11 | MEDIUM — **retired** | All five attributes probed working on this Tk 8.6 build, values read back rather than silently ignored `CONFIRMED`. The planned fallback proved unnecessary |
| 4 | Paste injection blocked into elevated windows (UIPI) | MEDIUM — accepted | Documented. The clipboard is written *before* the keystroke is attempted, so it degrades to "press Ctrl-V yourself" rather than losing text |
| 5 | Install size fights "super light" | MEDIUM — **quantified and partly fixed** | **~384 MB** total `CONFIRMED`. `scripts/slim.py` removes 106 MB of unreachable packages (→ ~278 MB) without needing Option B; verified by running the whole suite plus a real decode on the slimmed venv |
| 6 | Python 3.5 shadows 3.12 on PATH | LOW — mitigated | Pinned via `uv --python 3.12`; bare `python` never invoked `CONFIRMED` |
| 7 | Utterances past ~25 s leave Whisper's single 30 s mel window and decode cost climbs | MEDIUM — **newly discovered** | Cut and commit utterances before the boundary — this is what makes R8 tractable |

**Risk 1 was the one that could invalidate the product concept**, so it was measured
before any UI work — and it did change the design rather than just an implementation
detail. Risk 2 is now the highest remaining unknown, and it is the one item here that
cannot be settled without the user's own voice.

---

## 7. What "proven" means before UI work starts

The idea says "once proven, floating mic...". Concretely, the concept is proven when,
headless and keyboard-driven:

1. Speech → partial text visible in < 1.5 s while still speaking. (R4)
2. Stopping speech yields a stable draft rather than an auto-send. (R5)
3. "change X to Y" spoken at the draft actually edits it, round-trip < 2 s. (R6, R11)
4. Continuing to speak appends cleanly without re-transcribing prior audio. (R7)
5. A 10-minute session ends with flat RAM and unchanged latency. (R8)
6. Nothing in the codebase reads an API key. (R9)

Only after all six does the pill/bubble get built.

### Outcome

| # | Result |
|---|---|
| 1 | **pass** — 0.75–0.91 s per decode; partials stream while speech continues |
| 2 | **pass** — the draft is held; sending is always an explicit action |
| 3 | **pass**, and far better than the bar: literal corrections are local string ops, microseconds rather than 2 s |
| 4 | **pass** — appends without re-transcribing; utterances are cut before 24 s |
| 5 | **pass** — 11 min, 58 utterances: RSS drift −14.3 MB, p50 decode 0.848 s → 0.868 s (inside a ~50 ms jitter band, no trend) |
| 6 | **pass** — no key is read, stored or passed anywhere; the CLI is already authenticated |

All six held before the pill was built, as intended. **What is still not proven is
accuracy on a real microphone** (risk 2). Every WER figure in this document comes from
SAPI-synthesised speech, which is clean, evenly paced and close to Whisper's training
distribution; it demonstrates the pipeline is wired correctly and nothing more. That one
needs a person and a microphone:

    uv run python -m flow
