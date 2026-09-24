<p align="center">
  <img src="flow/assets/flow.svg" width="88" alt="">
</p>

<h1 align="center">Flow</h1>

<p align="center">
  Local voice dictation for Windows, made for developers who speak English with an accent.
</p>

<p align="center">
  <a href="https://github.com/samartomar/flow/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/samartomar/flow"></a>
  <img alt="Windows 10 and 11" src="https://img.shields.io/badge/Windows-10%20%7C%2011-0078d4">
  <a href="https://github.com/samartomar/flow/actions/workflows/ci.yml"><img alt="Tests" src="https://github.com/samartomar/flow/actions/workflows/ci.yml/badge.svg?branch=main"></a>
  <a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/github/license/samartomar/flow"></a>
</p>

<p align="center">
  <a href="#install">Install</a> ·
  <a href="docs/guide.md">Guide</a> ·
  <a href="https://github.com/samartomar/flow/issues/new">Report a mishearing</a>
</p>

![Flow Home page by page: Home, History, Voice, then a question dictated with the pill into Conversations and answered by the agent, then Models and Settings](docs/flow.gif)

Hold <kbd>Ctrl</kbd>+<kbd>Win</kbd>, say what you want to write, and let go. Flow pastes the
words wherever you were typing: your editor, a terminal, Slack, a browser tab. If it heard
something wrong, hold the keys again and say *"change Tuesday to Thursday"* or *"scratch
that"*, and it fixes the text it just pasted.

Flow sits in a small pill at the bottom of the screen, and the pill has two more modes. In
Refine, what you say is rewritten into a proper prompt for your project. In Ask, your question goes to the agent
CLI you already use (`codex` or `claude`) and the answer is read back to you.

I made Flow for people whose English has an accent that speech recognition keeps tripping
over, often enough that they give up and type. Spanish, Indian, Russian and Japanese
speakers are who it's designed and benchmarked for. Recognition runs on your own machine,
there's no account or API key, and your audio never leaves your PC.

## Install

### Windows

You need Windows 10 or 11 and a microphone. Download
[`flow-windows-x64.zip`](https://github.com/samartomar/flow/releases/latest/download/flow-windows-x64.zip),
unzip it anywhere and run `flow.exe`. No Python required.

> [!NOTE]
> The zip isn't code-signed, so the first launch shows a SmartScreen warning. Click
> **More info**, then **Run anyway**.

Or get the same build through [Scoop](https://scoop.sh), which makes updating one command:

```powershell
scoop bucket add flow https://github.com/samartomar/scoop-flow
scoop install flow/flow    # flow/ matters: Scoop's main bucket has a different "flow"
```

If you already use [uv](https://docs.astral.sh/uv/), you can install from source instead.
It fetches Python and Flow's three dependencies (faster-whisper, sounddevice and numpy):

```bash
uv tool install git+https://github.com/samartomar/flow
flow
```

The speech models aren't part of any of these. Flow downloads them on first run and shows
you the progress.

### macOS and Linux

Install with uv, as above. Off Windows, Flow runs as **Flow Lite**: the same recognition,
corrections and agent features, but it can't paste into other apps or listen for global
hotkeys. You hold the pill to talk, and Send copies the text for you to paste. The
microphone is the only permission it needs. There's no Mac or Linux download yet.
[More about Lite](docs/product.md#flow-lite--the-portable-body).

### The agent CLI (optional)

Refine and Ask need `codex` or `claude` on your PATH, already signed in. Dictation and
spoken corrections work without either. [The guide](docs/guide.md#install) has the details.

## Using it

1. Hold <kbd>Ctrl</kbd>+<kbd>Win</kbd> (or hold the pill) and talk.
2. Let go, and the text is pasted where your cursor was.
3. Heard you wrong? Hold again and say *"change Tuesday to Thursday"* or *"scratch that"*.
   Flow can fix its last paste until you type or click there.
4. Pasted into the wrong window? Click the right one and press
   <kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>Z</kbd>.
5. Want an answer rather than text? Hold <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>Win</kbd> and
   ask.

Those last two are Wispr Flow's keys on Windows as well, so if you've used it, your hands
already know them.

The first run walks you through the microphone, the model download, a 45-second tuning to
your voice, and whether to keep a history. You can skip any step.

## Type, Refine, Ask

Tap the pill to cycle through its three modes. Its colour tells you which one it's in.

| Mode | Pill | When you let go |
|:---|:---|:---|
| Type | white | The words are pasted. |
| Refine | gold | `codex` or `claude` turns them into a prompt for your project. Nothing is pasted until you press Send. |
| Ask | violet | The question goes to your agent CLI. The answer appears above the pill and is read aloud, and **Continue in Flow** opens the conversation in a window. |

Point Refine and Ask at a project folder (Flow Home ▸ Settings ▸ Workspaces, or `--cwd`)
and the answers are about your code. If you'd rather correct a draft by voice before
anything is sent, switch to the Classic pill in Settings.

## Flow Home

Everything that isn't talking happens in one window, the one in the GIF above. Right-click
the pill and choose **Open Flow**, or run `flow --home`. Speech models download there with
a progress bar and swap in without a restart, and it's where you set the microphone,
shortcuts, workspaces, agent CLI and the voice that reads answers. Voice tunes Flow to how
you speak, History shows what you've dictated if you chose to keep it, and Conversations
is Ask in a full window.

## Privacy

By default nothing leaves your PC. Audio, recognition, corrections, your word list and your
voice profile all stay local, and no API key is read, stored or passed anywhere in the code.

A few things do go out, and only when you use them:

- A draft you refine or a question you ask goes to that agent CLI's cloud, along with your
  workspace path if you set one.
- Pasting puts the text on the Windows clipboard for a moment, where clipboard managers
  and cloud sync can see it.
- If you choose one of Microsoft's natural voices to read answers, the text of each answer
  is sent to Microsoft. Every other voice runs locally.

History is kept only if you say so, in `~/.flow/history.jsonl`. Flow Home is served on
`127.0.0.1` to the window Flow opens and nothing else, with a new token every launch.
[The exact boundary](docs/architecture.md#what-leaves-the-machine) is in the architecture
doc.

## Known limits

- Flow does English only.
- Corrections have to be phrased as commands. *"delete the bit about the standup"* works;
  *"I feel it should not contain the summary"* gets typed as words.
- Your personal word list cuts both ways. It recovers 27–34% of the rare words the model
  missed, but raises the error rate by 14–38% on speech that doesn't contain them
  (measured on EdAcc with `small.en`). Add the words you say often, not every word you know.
- The live preview refreshes about once a second and is shown dimmed. The final text
  always replaces it.
- How accurate it is depends on your voice. Flow Home ▸ Voice ▸ **How well Flow hears you**
  measures yours with five sentences.

The rest are in [the guide](docs/guide.md#known-limitations).

## Docs

[The guide](docs/guide.md) is the manual: every flag, spoken command, mode and setting.
[product.md](docs/product.md) says who Flow is for and what it deliberately won't do,
[architecture.md](docs/architecture.md) how it fits together and the measurements behind
its tuned numbers, [roadmap.md](docs/roadmap.md) what's left and the accent benchmark that
tracks it, [development.md](docs/development.md) how to work on it and cut a release, and
[decisions.md](docs/decisions.md) why things are the way they are.

## Contributing

The most useful thing you can send me is a mishearing. If you speak English with an
accent, [open an issue](https://github.com/samartomar/flow/issues/new) with what you said
and what Flow typed. That's the one thing I can't measure on my own.

Pull requests are welcome for anything else. To run it from a clone:

```bash
git clone https://github.com/samartomar/flow && cd flow
uv sync && uv run flow                          # run it
uv run python -m unittest discover -s tests     # ~3,200 tests, about 90 s, no mic needed
```

The GIF at the top is recorded by [`scripts/home_reel.py`](scripts/home_reel.py) from a
scripted session, so it can be re-shot whenever the app changes.

## License

MIT. Flow is built on [faster-whisper](https://github.com/SYSTRAN/faster-whisper) and
OpenAI's [Whisper](https://github.com/openai/whisper) models, and reads answers aloud with
[Piper](https://github.com/OHF-Voice/piper1-gpl) if you add it.
