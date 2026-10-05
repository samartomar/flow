# Flow on macOS — the full set

**Status:** plan, 2026-10-05. Nothing here has run on a Mac yet. Every line that says
"measure" is a number this repository does not have, and the plan is ordered so that
those numbers arrive before the code that would depend on them.

**What changed.** The 2026-08-02 decision (decisions.md, *Flow Lite*) left a native macOS
body unfunded until sustained Lite use produced one number: how often the clipboard hop
made the user wish Flow had hands. The owner is buying a Mac and has decided the full set
gets built. That decision is taken, not re-argued here. The clipboard-hop number is still
worth recording in week one: it no longer gates anything, but it is the baseline the
native body has to beat.

## Where the Mac stands today

| Layer | Today | Verified on a Mac? |
|---|---|---|
| Brain (`session`, `clean`, `refine`, `lexicon`, `hold`) | Portable Python, no platform branch | CI only (`macos-latest` leg is green) |
| Ear (`audio`, `sounddevice`) | Portable; PortAudio wheel ships for macOS | No |
| Engines | Whisper (CPU only: CTranslate2 has no Metal), Apple native (`native.py` + `native/flow_stt.swift`) | Helper compiles and links in CI; **never recognised real speech** |
| Hands: paste | `inject_mac.py`: clipboard + System Events Cmd-V through `osascript`, terminal guard, Accessibility-denied detection | No |
| Hands: global hotkey | **None.** `hotkey.py` is `RegisterHotKey`; off Windows Flow runs Lite (click the pill) | — |
| Body: pill and bubble | Tk with `overrideredirect`, `-alpha`, `_aqua_work_area` Dock fix | **No: "does the pill draw at all?" is open** (NEEDS_YOU) |
| Body: tray | Win32 `Shell_NotifyIconW` only | — |
| Body: drawing quality | `paint.py` is GDI+ layered windows on Windows; Tk canvas elsewhere | No |
| Voice out | `speak.py` (SAPI through PowerShell), `edge.py` (network), `piper.py` (local) | Only edge and piper can work |
| Home | Opens in the default browser off Windows | No |
| Packaging | PyInstaller `flow.spec`, scoop, winget, all Windows | — |

The core of Flow (state machine, filters, refine loop, chord logic) is already portable.
The missing pieces are the platform-specific edges, and every one of them involves a macOS
permission (TCC).

## Phase 0: the first day with the Mac (no code)

Run each check and write down what happened, rather than fixing it on the spot. Each one
answers a question this repository has carried open.

1. **Install and test.** `uv sync`, then the full suite. Every failure gets triaged before
   anything else.
2. **Does the pill draw?** Borderless window, always on top, alpha honoured, above the
   Dock, Retina-sharp. Screenshot each of these.
3. **Does the pill steal focus?** Click it, then check which app is frontmost. This decides
   whether `inject_mac` pastes into the right window. Tk windows on Aqua usually activate
   the Python process, and a non-activating `NSPanel` was proposed on 2026-08-31 for
   exactly this. Treat it as the most likely blocker on the body side.
4. **Paste.** Grant Accessibility to the terminal, dictate into TextEdit, a browser,
   Terminal and VS Code. Record the result and the latency of each `osascript` round trip.
5. **Apple native engine end to end.** Enable Dictation, grant Speech Recognition, run
   `flow --engine native --file` on `.bench` clips. It has only ever been compiled, never
   used, so this is its first real test.
6. **Engine bench on Apple silicon.** Run the accent bench and silence probe for every
   candidate below. These numbers choose the Mac default.

## Phase 1: engines (chosen by measurement)

Without CUDA, the Windows answer ("large-v3 on the GPU") does not exist on the Mac. That
makes the engine choice the most consequential decision on this platform.

| Candidate | Runtime | What we know | Measure on the Mac |
|---|---|---|---|
| `small.en` / `large-v3-turbo` | faster-whisper, CPU (Accelerate) | 19.4 / 17.8 errors per 100 words on EdAcc (GTX 1070) | RTF on M-series; whether large is usable on CPU at all |
| **Parakeet TDT 0.6B v3 int8** | sherpa-onnx, the `[parakeet]` extra (built 2026-10-05) | 17.3 errors per 100 words, RTF 0.070 on a Zen 2 CPU, a token log-prob gate; **Japanese worse (26.3)** | RTF on the CPU and with `provider="coreml"`; gate threshold on Mac room noise |
| parakeet-redux (1.58-bit) | Photon, Metal/NEON | Vendor: 38× CPU / 43× GPU on an M2. Our run (dense path, Windows): 17.1 errors per 100 words, silent on 8/8 silence clips | Whether 1.1 GB of torch for a faster Parakeet earns an extra; confidence output |
| Apple native | `flow_stt` helper | No `no_speech_prob`, no hotwords, one tier | Accuracy on EdAcc (first ever) |

**Decision rule:** the Mac's `auto` picks the most accurate engine that holds the latency
budget on the measured machine. That is likely Parakeet, which is a change from Windows,
where `auto` never picks Parakeet. That asymmetry has to be written down in `_engine`'s
docstring and in decisions.md when it happens, not left implicit.

**Open questions:**
- Partials: sherpa's offline recogniser re-decodes the whole buffer each time. At an RTF of
  0.07 that may be fine. Measure the partial cadence before reaching for the streaming
  model.
- Hotword rescue: the command re-decode passes `hotwords`, and neither Parakeet path takes
  them. sherpa-onnx has hotword biasing for some transducers; check whether it works with
  `nemo_transducer`.
- The `TOKEN_LOGPROB_MIN` gate was set from one invention. Re-measure it with the
  `fan*_quiet` recordings repeated in a Mac room.

## Phase 2: hands

**Global hotkey.** Nothing exists yet. `hold.py` already owns the chord state machine
without platform code (moved out of the hook on 2026-09-30), so the Mac only needs a
source of key-down and key-up events.

- *Recommended:* a second small Swift helper (`native/flow_keys.swift`) using a
  `CGEventTap`, writing modifier and key events to stdout. This follows `native.py`'s
  reasoning: R16 stays at three, Objective-C stays behind a pipe, a crash becomes an exit
  code, and it compiles on first use like `flow_stt`. It needs **Input Monitoring** (a
  listen-only tap) or Accessibility.
- *Rejected:* `pynput` (breaks R16), and ctypes into ApplicationServices (a CFRunLoop
  driven from Python through ctypes is fragile, and a crash there takes down the
  interpreter).
- Re-measure the gesture. The single-press threshold came from 74 Windows presses (median
  hold 626 ms). Mac keyboards and the Fn/Globe key may change that, and Globe is the
  native dictation key, so check for conflicts.

**Paste.** Keep `inject_mac`'s `osascript` path for the first build, since it works without
new code. Move to `CGEventPost` Cmd-V inside the same helper once the helper exists. It is
faster (no process per paste) and draws on the same Accessibility grant.

## Phase 3: body

- **Pill window.** Depends on the Phase 0 answers. If Tk cannot make a non-activating
  window, the options are (a) restore focus to the previous app before pasting (System
  Events can name the frontmost app, so record it on arm), or (b) let the helper own an
  `NSPanel` overlay. Prefer (a): it keeps one drawing path.
- **Retina.** Tk on macOS scales by points. Check that the pill's measured-pixel constants
  (one-surface.md) hold at 2×.
- **Menu bar.** `tray.py`'s equivalent is an `NSStatusItem`, which only a native process
  can own. Either the keys helper hosts it and sends menu picks back over the pipe, or the
  Mac has no tray and Home plus the pill menu cover it. Decide after Phase 0. A missing
  tray icon is acceptable at first; a crashing one is not (the 2026-09 CI lesson:
  `tray.py` must import cleanly on darwin).
- **Home.** Already opens in the browser. Check that the server binds to localhost only.

## Phase 4: voice out

`speak.py`'s SAPI path is PowerShell. macOS ships `say`, which has modern voices, needs no
network and no dependency, and fits `speak.py`'s backend shape: one process per utterance,
with the `speaking` mic gate unchanged. Add it as the macOS default and keep edge and piper
as the opt-in alternatives they already are. Measure the time to first audio, as was done
for PowerShell's ~700 ms.

## Phase 5: packaging and permissions

macOS attributes TCC permissions to the *responsible process*. Run from a terminal, every
prompt says "Terminal" (or iTerm, or VS Code), and the user grants rights to the wrong
thing. A real Mac product therefore needs:

- **A signed, notarised `.app`.** Requires an Apple Developer ID ($99/yr, the owner's
  decision and account), a PyInstaller (or py2app) build next to `flow.spec`, hardened
  runtime, notarisation in `release.yml`, and a `macos` release leg.
- **Usage strings** in Info.plist for Microphone, Speech Recognition, plus Accessibility
  and Input Monitoring guidance (these two cannot be requested by a prompt; the user must
  be sent to System Settings, and `inject_mac` already has the wording).
- **The Swift helpers built at release time** and signed inside the bundle, replacing the
  first-use compile that exists to avoid Gatekeeper warnings for unsigned binaries.
- A Homebrew cask beside scoop and winget.

Until the bundle exists, the terminal-attributed path is the development path, and the
docs say so.

## Phase 6: re-take the measurements

Every threshold in Flow was calibrated on one voice and one Windows machine (roadmap.md).
On the Mac, re-run the silence/hallucination probe, the accent bench, `gate_bench`,
`command_bench`, calibration (room tuning), cold-start and the release-to-paste latency.
Record each result in decisions.md against the machine it was measured on. A threshold
that differs per OS becomes a per-platform constant with both measurements in its comment.

## Order and exit criteria

| Step | Done when |
|---|---|
| Phase 0 | All six checks recorded in NEEDS_YOU / decisions.md with numbers and screenshots |
| Engine default | Mac `auto` chosen from the Phase 0 bench, decision entry written |
| Hotkey helper | Hold-to-talk works system-wide with Input Monitoring granted, and fails with a named reason when it is not |
| Paste | Dictation lands in the frontmost app across the four Phase 0 targets, terminal guard intact |
| Body | Pill visible, non-focus-stealing (or focus restored), sharp at 2× |
| Voice out | `say` backend live, mic gated while speaking |
| Bundle | Signed, notarised `.app`; permissions name Flow |
| Re-measure | Phase 6 numbers recorded; no Windows-tuned constant left unverified on the Mac |

What can start before the Mac arrives: the `[parakeet]` engine (done on Windows), a draft
of the `say` backend, and the keys helper's Swift source, which can be compiled in CI the
way `flow_stt` is. Its behaviour cannot be verified until the Mac is here, so it stays
unwired until then.
