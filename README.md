# Flow

Local English dictation with a talk-to-it refine loop. Speak, watch the text build,
then correct it by voice before it goes anywhere.

Windows. English only. Three declared dependencies. No API key.

```bash
uv run python -m flow
```

Click the pill to arm it, speak, and the draft floats up above it. Talk to the draft to
correct it, keep talking to add more, then Send.

---

## What it does

| | |
|---|---|
| **Live text while you speak** | Partials refresh roughly every second as you talk |
| **Nothing sends itself** | Stopping leaves a held draft, never an automatic send |
| **Correct it by voice** | "change Tuesday to Wednesday" edits the draft in place |
| **Keep talking** | Anything that isn't a correction is appended |
| **Rewrite on request** | "make it more formal" goes to your existing agent CLI |
| **Silence stays silent** | Whisper invents words on silence and noise; those are filtered out |
| **Send** | Pastes into whatever window has focus |

## Requirements

- Windows 10/11
- [`uv`](https://docs.astral.sh/uv/) (it fetches Python 3.12 and the deps itself)
- A microphone
- Optional: `codex` or `claude` on PATH, already signed in — only needed for semantic
  rewrites. Everything else works without them.

**No API key is read, stored or passed anywhere in this codebase.** Semantic rewrites
shell out to a CLI you have already authenticated.

## Install

```bash
uv sync
```

Downloads ~243 MB of packages; the `base.en` model (~141 MB) is fetched on first run.

### Slimming it down (optional, ~106 MB)

Two of those packages are unreachable from this app:

| Package | Size | Why it is never used |
|---|---|---|
| `onnxruntime` (+`protobuf`) | 34 MB | Only for faster-whisper's Silero VAD. Flow always passes `vad_filter=False` because it does its own speech gating |
| `av` | 66 MB | Only for decoding audio *files*. Flow feeds numpy arrays from the mic and never calls `decode_audio()` |

```bash
uv run python scripts/slim.py --apply
```

Measured: **243.5 MB → 137.3 MB**, with the full test suite and a real decode still
passing. `av` is replaced by a small stub because faster-whisper imports it at package
load time; the stub raises a clear error if anything ever does reach for it.

This deliberately breaks a dependency contract, which is why it is opt-in. A future
faster-whisper release could start touching `av` at import time or enable VAD by default.
Nothing is lost either way — `uv sync` rebuilds the full venv, and
`scripts/slim.py --undo` reinstalls both packages.

## Use

```bash
uv run python -m flow
```

| Hotkey | Action |
|---|---|
| `ctrl+alt+space` | arm / disarm the mic |
| `ctrl+alt+enter` | send the draft |
| `ctrl+alt+esc` | clear the draft |

Combos already owned by another app fall back automatically — the startup log prints
which ones actually registered, so a dead shortcut is never a silent mystery.

Right-click the pill for Send / Clear / Quit. Drag it anywhere. `Esc` quits.

### The pill's colours

| Colour | Meaning |
|---|---|
| slate | idle or disarmed |
| green | listening |
| amber | draft held, waiting on you |
| blue | agent CLI is rewriting |
| red | something failed (the draft is never lost) |

### Talking to the draft

Corrections are recognised by shape and applied locally — instantly, no subprocess:

```
change Tuesday to Wednesday      replace the last occurrence
replace all Bob with Alice       every occurrence
delete afternoon                 remove a phrase
delete the last two words        or "the last sentence" / "the last line"
delete from drop to between      remove a whole range
insert final before report       or "add today after report"
capitalize john                  -> John        (title case)
all caps nasa                    -> NASA        (also "uppercase nasa")
lowercase REPORT                 or "make REPORT lowercase"
new paragraph                    or "new line"
scratch that                     undo
```

Rewrite requests go to the CLI and take a few seconds (the pill turns blue):

```
make it more formal
shorten this
turn it into bullet points
fix the grammar
```

Anything else is treated as more dictation and appended.

The router decides using the draft as context, so *"Delete key handling is broken"* is
dictated as text while *"delete key handling"* is an instruction — the difference being
whether the target is actually in your draft. When it guesses wrong, **Refine** and
**Continue** force the next utterance either way, and every edit is undoable.

### Options

```
--model small.en     more accurate, ~3x the compute (default base.en)
--device 3           input device index; list them with scripts/devices.py
--arm                start listening immediately, no click needed
--no-paste           print the draft instead of pasting it
--no-hotkeys         skip global hotkey registration
```

If capture cannot start — no microphone, device held exclusively by another app, a bad
`--device` index — the pill stays slate and the reason appears in a red bubble. It will
not show a green pill that is quietly recording nothing.

## Layout

```
flow/
  session.py   state machine, threaded decoder, draft + undo
  edits.py     edit-vs-append routing and local string operations
  refine.py    agent-CLI adapter for semantic rewrites
  asr.py       faster-whisper behind a two-method interface
  audio.py     mic capture and the speech gate
  ui.py        the pill and the draft bubble (tkinter)
  inject.py    clipboard + SendInput (ctypes)
  hotkey.py    RegisterHotKey on its own message-loop thread (ctypes)
scripts/       benchmarks, probes and the soak test
tests/         router and state-machine tests
```

`tkinter` and `ctypes` are stdlib, which is how the GUI, global hotkeys and text
injection cost zero dependencies.

```bash
uv run python -m unittest discover -s tests
```

## Known limitations

- **Partials refresh about once a second, not per word.** Decode has a ~0.8 s floor on
  CPU, so text arrives in bursts. Wispr Flow feels smoother here.
- **Partials can contain nonsense** at mid-word boundaries. They are shown dimmed and
  are always replaced by the final text.
- **Elevated windows reject the paste** (Windows UIPI). The draft is put on the
  clipboard first, so `Ctrl+V` by hand still works.
- **Semantic rewrites take ~6 s** — the cost of starting an agent CLI. This is why only
  genuine rewrites use one.
- **Accuracy on your voice is unmeasured.** Every published number here comes from
  synthesised speech, which is optimistic. Try `scripts/listen.py` and switch to
  `--model small.en` if `base.en` disappoints.
- **~384 MB installed**, or ~278 MB after `scripts/slim.py --apply`. The floor is
  `ctranslate2` (60 MB), numpy (42 MB) and the model (141 MB).
- **Speaking for more than 24 s without a pause can split a word.** Whisper decodes
  inside a single 30 s window, so an utterance is cut and committed before that boundary
  to keep latency flat. The cut lands on an audio block, not on a word, so continuous
  speech past 24 s can produce `think` + `ing`. Any natural pause resets the timer, so
  this needs genuinely unbroken speech to hit.

## Measured on the development machine

Windows 11, CPU-only, `base.en` int8, 1280x720 RDP session.

| | |
|---|---|
| Cold start | ~1.4 s (0.40 s import + 0.98 s model load) |
| Decode, 1 s of audio | 0.75 s |
| Decode, 8 s of audio | 0.91 s — nearly flat, because Whisper pads to one 30 s window |
| Semantic rewrite via `codex` | ~5.7 s, ~19.7 k tokens |
| 11-minute session | RSS drift −3 to −6 MB; p50 decode unchanged |
| Installed size | 243 MB packages + 141 MB model (137 MB packages slimmed) |

Accuracy numbers are deliberately absent: the only ones measured come from synthesised
speech, where WER was 0.000, and that says more about the test audio than about a real
microphone.

## Design notes

[docs/analysis.md](docs/analysis.md) has the requirements breakdown, the four
architectures considered, and the ranked risks with measurements.
[PROGRESS.md](PROGRESS.md) is the build log, including the things that broke.
