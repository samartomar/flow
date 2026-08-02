# What Flow is for

The build log records how Flow works; nothing in the repo records what it must do to be
worth using, or for whom. This document is that definition. [docs/analysis.md](analysis.md)
holds the original R1–R17 build requirements; the P-numbers here sit above them as the
product layer. [docs/roadmap.md](roadmap.md) maps the gap between this definition and the
current build, and [docs/architecture.md](architecture.md) describes the build itself.

## The one-line definition

**Wispr Flow + ChatGPT Voice mode + prompt correction, in one pill — local, free,
private.** Flow is voice-first AI work for developers who don't sound like Whisper's
training data: the developer whose first language is Spanish, Hindi, Russian or Japanese
speaks English, and Flow turns that into precise prompts — typed into any app, or run as
a spoken conversation with the agent CLI they already have.

Three ingredients, one loop:

| Ingredient | What it contributes |
|---|---|
| **Wispr Flow** | Dictation into whatever window has focus — the pill, live partials, Send |
| **ChatGPT Voice mode** | A conversation: speak, the AI answers, speak again — against the local `claude`/`codex` CLI, no cloud account beyond what the CLI already has |
| **Prompt correction** | The held draft you can edit by voice before anything is sent — the safety layer that makes accented ASR survivable |

## The user

A developer who:

- works with AI agents daily — terminal CLIs (`claude`, `codex`), IDE chats, browser chats;
- writes prompts that are *prose*, and lots of it — long-form English is now a core
  developer activity, and typing it is the slow part;
- speaks English as a second language, with a strong accent. Their US-native colleagues
  can use anything; commercial ASR understands them fine. This user is mis-transcribed,
  which today means they type.

Native US/UK speakers are explicitly not the design center. They are served adequately by
every existing tool; nothing here should break for them, but no decision is made for them.

The accent groups that anchor design and testing: Spanish/Latin-American, Indian, Russian,
Japanese L1 speakers. These four cover the major phonological failure modes (v/w and b/v
mergers, th-stopping, retroflex stops, r/l merger, epenthetic vowels, syllable- and
mora-timed rhythm). A fix that generalises across these four generalises broadly.

## The job to be done

> "I have a thought about what the AI should do. Get it into the tool as a precise,
> well-worded English prompt — faster than I could type it, without my accent mangling
> it, and without my rough phrasing weakening it."

Three things make a prompt land: the *words are right* (names, identifiers, jargon
survive transcription), the *phrasing is strong* (specific, structured, unambiguous), and
it *goes where the work is* (terminal, IDE, browser — whatever has focus). Flow's job is
all three. The correction loop and the agent-CLI rewrite path aren't accessories to
dictation; for this user they are the product — speech recognition will get accented
speech wrong sometimes, and the loop is what makes wrong recoverable instead of fatal.

## What must be true to be useful

| # | Requirement | Acceptance test |
|---|---|---|
| P1 | **Understands accented English.** The default configuration works for the four anchor accent groups, not just for clean US speech. | Per-accent WER ≤ 12% on every anchor group of the accent benchmark (`scripts/accent_bench.py`) — the floor, not the average, is the metric. |
| P2 | **Never loses words silently.** A filter or gate may reject audio, but the user can always find out that it happened and recover the text. | False-reject rate < 1% on real accented speech; every dropped segment logged; recovery affordance visible in the UI. |
| P3 | **Voice corrections work in an accent.** The command grammar tolerates the mis-transcriptions the target accents actually produce, in both the trigger verb and the target words. | ≥ 95% command recognition on the accented command set; command-misheard-as-dictation (silent append) ≈ 0. |
| P4 | **Knows the developer's vocabulary.** Identifiers, repo names, library names, and the user's own names/terms transcribe correctly because Flow biases recognition toward them. | ≥ 90% accuracy on a personal-lexicon entity test; lexicon grows from the user's own corrections without manual curation. |
| P5 | **Polishes prompts on request.** "Make this a proper prompt" turns rambling dictation into a crisp, structured prompt via the already-authenticated agent CLI — the R9 path, doing the thing it is best at. One-shot and in place: the draft goes out and a better draft comes back, which is what separates it from P9's workshop, where the prompt is talked about across several turns before anything replaces it. | A polish request produces a prompt a reviewer judges stronger than the raw dictation; latency within the existing ~7 s CLI budget; draft never lost on failure. |
| P6 | **Conversation continuity.** Sent prompts form a thread, like a ChatGPT conversation — Send does not erase history. The next utterance can be a follow-up; the previous prompt can be recalled, and rewrites can use the thread as context. | After Send, "follow up:" dictation and "bring back my last prompt" both work; the CLI rewrite path can see the thread tail (bounded, local, R11-sized). |
| P7 | **Safe into a terminal.** Pasting into a terminal must never execute prematurely: multi-line drafts use bracketed paste or trailing-newline suppression per target. | A multi-line draft pasted into a shell arrives whole, unexecuted. |
| P8 | **Adapts to this user.** The thresholds that decide "was that speech?" are calibrated to this speaker and this microphone, not to the machine Flow was developed on. | A first-run calibration (< 60 s) sets gate and filter parameters per user; the false-reject metric (P2) is measured against the calibrated profile. |
| P9 | **The prompt workshop.** Converse mode is where a prompt is *discussed and refined before it is sent* — not a general assistant. Rewritten from use, 2026-08-01: general conversation was tried at the desk and failed on its own merits (the CLI answered that it has no internet access, and hallucinated), while the thing that worked was talking a prompt into shape. So the scope is the owner's own: "discuss and refine prompts only, nothing more". Questions are **grounded in a workspace** — an explicit project path, named at startup and on every mode switch — because a prompt is written to be run somewhere. | The loop is the acceptance test: speak a rough prompt → the CLI's suggestions render in Flow → speak a follow-up, which continues the same conversation → **take the answer as the draft** (one chip, or "use that answer") → **send it** (one word, or one press) into the terminal where the work is. Switching modes is one action; the correction loop (P3) works on the outgoing prompt in both. Spoken replies via the OS speech engine, shipped. Half-duplex is a standing caveat, not a defect: there is no echo cancellation (R16), so Flow hears the user or talks, never both, and interrupting is an explicit action. |

Everything above obeys the standing constraints inherited from the build: local-only and
key-free (R9), draft-held-never-autosent (R5), instant local corrections (R6/R11),
minimal dependencies (R16), long sessions without drift (R8).

## Non-goals

- **Multilingual output.** Flow produces English text, full stop. Accented *input* is the
  whole point; Hindi/Spanish/Japanese *output* is out of scope. The one obligation to
  code-switched speech: a stray L1 word must never trigger a destructive edit.
- **Cloud ASR or any API key.** Non-negotiable, inherited from R9. Accuracy improvements
  come from model choice, decoding, biasing and personalisation — never from egress.
- **Writing code by voice.** Flow is for prose — prompts, messages, docs, commit
  messages. Symbol-level code dictation ("open paren, self dot") is a different product.
- **General voice control.** No "open browser", no OS automation. Text in, text out —
  where "out" is a focused window (dictate mode) or the agent CLI (converse mode, P9).
- **Being an AI itself.** Flow never generates content on its own; every semantic
  operation — polish, rewrite, conversation reply — is the local agent CLI's work (R9,
  R11). Flow is the microphone, the editor, and the courier.

## What "useful" looks like, concretely

A Hyderabad-raised developer arms Flow, and says: *"claude, look at the session dot p-y
file and figure out why the decode worker, uh, sometimes drops the last utterance when I
stop it quickly."* The draft appears with `session.py` intact (P4: repo lexicon), their
retroflex t's and v/w merges notwithstanding (P1). One word came out wrong; they say
*"change dot p-y file to session file"* and it fixes instantly (P3). They say *"make it a
proper prompt"* — the CLI restructures it: context, symptom, request (P5). Send. It lands
in the Claude Code terminal, whole (P7). Claude asks a clarifying question; the developer
speaks the follow-up, which continues the same thread (P6). At no point did they touch
the keyboard, and at no point did a word vanish without a trace (P2).

Later, with a harder task ahead, the same developer flips the pill into converse mode
(P9). The note names where they are: *converse mode - Ask sends the draft to codex, and
the question leaves this machine, grounded in D:\dev\products\acme.* They talk a
rough prompt out loud — *"I need to add audit logging to every write path, but I don't
want it in the hot loop"* — and the CLI comes back with what the prompt leaves ambiguous:
which writes, what the log is read by, whether async is acceptable. They answer in
speech, twice, each turn continuing the same conversation (P6). When the version on
screen is the one they want, they say *"use that answer"* — it becomes the draft — and
then *"enter boom"*: it pastes into the Claude Code terminal and runs. No keyboard, no
new account, no API key, and their accent understood throughout.

That second scenario is the one that changed. It used to be a general question about
React, and general conversation is precisely what failed when it was finally tried: the
CLI has no internet access and said so, then hallucinated. What survived the desk was
narrower and more valuable — a prompt, talked into shape, grounded in a real project, and
handed to the terminal without touching the keys.

Those two scenarios, executed end-to-end on all four anchor accents, are the definition
of done.
