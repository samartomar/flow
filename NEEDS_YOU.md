# NEEDS_YOU — things only you can do

Updated 2026-08-02, the morning Flow went public. Every decision that was open is closed
or parked on named evidence: the standing record with each decision's why and its reopen
bar is **[docs/decisions.md](docs/decisions.md)**; the 28 items they spec'd are done,
with rounds one to three archived in
[docs/history/loop-rounds-1-3.md](docs/history/loop-rounds-1-3.md). This file holds only
what is live: desk work, and the two decisions parked on evidence.

## Decisions still open

(none — the record is [docs/decisions.md](docs/decisions.md); two evidence-parked
entries are further down)

## The selfdrive tripwire has fired — `capitalize sameer`, second sighting

- [ ] **Quarantine or fix `spoken: 'capitalize sameer'` in `scripts/selfdrive.py`.** Rule 2's
  same-check tripwire, written into policy on 2026-08-01 (decisions.md, "Selfdrive flake"),
  says two sightings of the *same* check flaking in two different runs stops being noise —
  even when both rerun green, which both of these did. This is sighting two.
  - **Sighting one:** item 2's run, 2026-08-01 — 63/64, `spoken: 'capitalize sameer'`,
    64/64 on the rerun, four green runs after it (loop-rounds-1-3.md).
  - **Sighting two:** item 39's run, 2026-08-02 — 63/64, the same check, decoded
    `sameer is writing the…` with the capital never applied; 64/64 on the automatic rerun.
  - **The load question the decision told us to ask first, answered: yes.** This run
    followed two full unit suites back to back (1031 tests, ~15 s each) plus three real-Tk
    render-cost measurements, so the fan was ramped and the room was not the idle one
    `--calibrate` measured. That is consistent with the mechanism already on record —
    `capitalize sameer` is marginal by design, and `asr.py`'s temperature fallback samples
    once `avg_logprob` crosses −1.0 — and it is *not* evidence that anything regressed:
    nothing in items 37–39 touches the decoder, the gate or the router.
  - **What is left for you, because it is a taste call rather than a measurement:** either
    quarantine the check (mark it advisory so a flip cannot cost a rerun) or make it
    non-marginal (a longer utterance, or a word the decoder is not on the edge about).
    Fixing it by loosening the *decoder* is the one option to refuse — the marginality is
    real and the check is the only place the suite sees it.
  - Cheapest thing that would settle the load half properly: run selfdrive twice from a
    cold machine before any suite has run, and twice straight after a suite. Four runs, no
    new instrument.

## Found while building, out of the item's scope

- [ ] **A `.cmd` shim truncates every prompt Flow sends at the first newline — and both
  CLIs document the install that produces one.** Found while trying to verify `opencode`
  for item 35, and it is not about opencode. Measured directly, against a batch shim of
  the shape `npm -g` writes: `['line one']` arrived where `['line one\nline two\nline
  three']` was sent, and the identical argument through a real executable arrived whole.
  A `.cmd` forwards `%*` through cmd.exe, which stops at the newline. **Every prompt in
  `refine.py` is multi-line** — `_PROMPT`, `_POLISH_PROMPT`, `_ASK_PROMPT`,
  `_ASK_ARTIFACT_PROMPT` all are — so on a machine where `codex` or `claude` was installed
  with `npm -g`, the CLI receives the framing and none of the user's text, exits 0, and
  answers a question it never saw. There is no error anywhere: the reply is fluent and
  about nothing.
  Not fixed here because it is outside item 35 (Rule 4) and because the fix is a design
  choice rather than a patch — the shapes are, roughly: hand the prompt on **stdin**
  (`_invoke` sets `stdin=DEVNULL` deliberately, because codex hangs on an open one, so
  this is a per-CLI variation the seam does not have today); write the prompt to a temp
  file and pass the path; or refuse a `.cmd` target with a message telling the user to
  install the real binary. **The measurement that picks one** is which CLIs actually
  behave differently — on this machine codex and claude are WinGet `.EXE`s and are
  unaffected, so nothing here can distinguish "shim breaks everything" from "shim breaks
  opencode". Reproduce with
  `C:\Users\samar\AppData\Local\Temp\claude\…\scratchpad\shim_probe.py`, or in four lines:
  a `.cmd` that echoes `%*`, invoked through `refine._invoke` with a two-line prompt.

- [x] **The Voice submenu can never tick "Engine default" — the defect item 36 just
  fixed in the Workspace menu, measured on real Tk.** (Done, commit `cdb64b3`,
  fast-forwarded onto main and re-gated there — 979 OK: `VOICE_ENGINE_DEFAULT`
  sentinel exactly as prescribed below, pinned failing-first in
  `TestTheVoiceMenuCanTickEngineDefault`, suite 976 → 979.) A menu radiobutton built with
  `value=""` reads back with its *label* as the value — Tk treats an empty `-value` as
  unset and falls back — so `_voice_var`, which holds `""` for the engine default,
  matches no row and the Voice submenu opens with no tick anywhere when no voice is
  chosen. Measured while probing item 36's submenu:
  `add_radiobutton(label="Engine default", value="", variable=var)` read back
  `value='Engine default'` with the var holding `''`. Cosmetic only — taps still work,
  named voices still tick — and out of item 36's scope (Rule 4). The fix is the one the
  Workspace menu now carries: a non-empty sentinel as both label and value, the var
  defaulting to it (`ui.py`, `_voice_menu`'s "Engine default" row and the `_voice_var`
  init above it), plus one var-equals-row-value test the way
  `test_no_workspace_means_the_not_set_row_is_the_one_ticked` now pins Workspace.

- [x] (resolved — the `Session._provider()` pin mismatch became LOOP_PLAN item 24 and is
  done, commit `a18b619`: the notes now name the CLI the call will actually make)

## Going public — done 2026-08-02, except two steps that are not on this machine

**Flow is public: https://github.com/samartomar/flow · release
[v0.1.0](https://github.com/samartomar/flow/releases/tag/v0.1.0) with
`flow-windows-x64.zip` (126 MB) attached.** MIT in the sidebar, README rendering with
the `uv tool install` two-liner as its first code block, and
`uv tool install git+https://github.com/samartomar/flow` verified from the public URL in
a throwaway tool directory (`flow --help` exit 0, `uv tool list` → `flow v0.1.0`, then
uninstalled).

- [x] **License word** — MIT, © Samar Tomar 2026 (`LICENSE`, and the metadata says the
  same thing so a wheel cannot disagree with the file beside it).
- [x] **Phase A** — LOOP_PLAN items 26, 27, 28, each instrumented, gated on the full
  suite and committed separately.
- [x] **The flip** — but **not** by `gh repo edit` alone, and this is the part worth
  reading. The sweep found the volunteer recordings still live on GitHub: a force-push
  moves a ref, it does not remove objects, and the pre-rewrite tip `50d16f5` was still
  served by the API with `.bench/recorded/inbox/` intact — five clips, two named after a
  volunteer, plus the manifest that names people. Private that cost nothing; public it
  would have handed a stranger a volunteer's voice by SHA. So the repo was **deleted and
  recreated** (your call, over a Support purge, for being certain rather than promised),
  the clean history pushed, and the old SHA now returns 422. Same name, same URL, one
  repo. `docs/decisions.md`'s "Distribution, final" entry carries the correction.
- [x] **Consent paragraph** — written in `docs/recording-kit.md`. **Your job is still to
  read it and agree it is true**, since it speaks for you to people who trusted you.
- [ ] **List Flow in ai-harness** with the uv one-liner and the Releases link — the
  other machine, so it is still yours:
  `uv tool install git+https://github.com/samartomar/flow`, then
  `https://github.com/samartomar/flow/releases`.
- [ ] **Run the zip on a machine with no Python** — the one thing no harness here can
  prove. CI ran `flow.exe --help` against the bundle it built before zipping it, and the
  same bundle launched here and printed all 17 startup lines, but both machines have
  Python installed. Download `flow-windows-x64.zip`, unzip, run `flow.exe`, and expect
  one-time SmartScreen: **More info → Run anyway**.

Two things the sweep turned up that you have not ruled on, kept here rather than lost:

- [ ] **`docs/record.html:277` still carries the old one-line consent claim** ("stays on
  one laptop, is never uploaded, and is deleted whenever you ask") while
  `recording-kit.md` now carries the full paragraph. Both are true; the guided page is
  the one volunteers are actually walked through, so it is the one that matters more.
  Say the word and it gets the same paragraph.
- [ ] **`.bench/accent/manifest-aesrc.jsonl` is 240 rows of reference transcripts and
  speaker IDs** from a re-upload that, in `fetch_accent_data.py`'s own words, declares no
  licence — and `.gitignore` excludes the audio on exactly that reasoning ("not a claim
  that survives being committed anywhere") while the manifest carrying the text is
  committed. The 580 EdAcc rows are from a published corpus with its own terms and are a
  different question. Nobody has been harmed by this; it is simply inconsistent with the
  argument already written down.

## At the desk

- [ ] **A workshop turn through kiro-cli, in a workspace with MCP servers — and then
  decide whether you want it.** Item 41 removed the wall: the exact call you watched fail
  ran again on purpose, kiro-cli pinned with `--cwd D:\dev\ai-continuum\ai-continuum-product`
  (whose `.kiro/settings/mcp.json` declares four uvx/npx servers), and it **answered in
  38.9 s** where the old global 20 s executed it at second twenty. So it works. What only
  you can judge is whether ~39 s a turn is a workshop or a wait:
  `uv run flow --converse --cli kiro-cli --cwd <a project with .kiro MCP servers>`, ask two
  or three real questions, and see how it feels against the same questions through codex
  (`--cli codex`, seconds rather than tens of them). The residue is not Flow's to fix —
  kiro-cli spawns the project's MCP servers cold on every `chat` and there is no flag to
  skip it, `--require-mcp-startup` exists and its inverse does not — so the honest choices
  are: live with ~39 s, or use **Settings ▸ CLI** to put codex on the workspaces that are
  MCP-heavy. If you find yourself always tapping codex, say so and the *default* preference
  order per workspace becomes a decision rather than a habit.
  Two things worth watching while you are there: the pill's marker should read `kiro` (the
  entry below), and a genuine timeout note should now say **60s**, not 20.

- [ ] **The pill dragged high with a long draft — the eye half.** The mechanical half is
  done and passes through the app's own construction path: pill dragged to the top of the
  work area, a 50 000-character dictation, both windows read back from `GetWindowRect` —
  pill `(1100,0)-(1252,40)`, bubble `(872,8)-(1252,422)`, chips at 382..408, nothing
  outside the 1280×672 desktop. Item 42 pins the same property at all four corners in five
  states. What is left is what a rect cannot say: **when the pill is at the very top, the
  bubble is drawn over it.** Nothing clips and nothing is unreachable — the bubble anchors
  above the pill and there is no "above" left, so it clamps to the top edge and the pill
  ends up underneath it. Look at that once and say whether it is fine (it is only reachable
  by dragging the pill to the very top, which is not where it lives) or whether the bubble
  should flip to hanging *below* the pill when there is no room above. The second is a real
  change with a real question inside it — which way it should flip on a side-anchored pill
  — so it is a decision, not a tweak.

- [ ] **The artifact reply, now that the window stops at the desktop edge.** Item 42 found
  that a 12 000-character answer sized the bubble **4 179 px** on a 672 px screen and was
  simply placed off the bottom, chips and all — the long-draft incident's unreachable Send,
  alive on the reply path. It is **656 px** now and the chips are at 624..650, which is the
  fix. The cost is visible and is yours to accept or reject: past what fits, the tail of a
  long artifact is **clipped by the window**, and the chip row sits over its last lines.
  Ask for something long in converse mode — "give me a complete reusable prompt for X" —
  and look. `Use this` and `Copy` both still work on the whole answer, so nothing is lost;
  what you cannot do is *read* the end of it in the bubble. If that matters, the cure is a
  reply that scrolls, which is the proposal at the bottom of this file rather than a fix
  somebody guesses at.

- [ ] **Run the long draft on purpose, and watch the chips stay put.** Items 37 and 38
  shipped from the incident at your desk (decisions.md, "The long-draft incident"). The
  numbers say it is fixed — a 50 000-character draft renders in **4.3 ms** instead of
  476.7, and the bubble is **414 px** instead of 15 153 — but the thing the incident was
  actually about is whether the window is usable, and that is eyes.
  1. Dictate, or paste through Edit, until the draft is *long* — a few minutes of speech,
     or open Edit and paste a few pages in and press Done.
  2. Look at the bubble. It should stop growing, show the **end** of the draft, carry a
     muted `… N earlier lines` above it, and keep Refine / Continue / Edit / Send on
     screen. Newly spoken words should appear at the bottom with nothing to scroll.
  3. **There is no scroll back through the draft, deliberately** — scrolling back would
     have to lay out what it scrolls to, which is the cost the cap exists to bound. The
     whole draft is in **Edit**, and now in **Copy draft** (right-click, above Clear
     draft). If reading the middle of a long draft in the bubble turns out to be something
     you actually want, say so and it becomes a decision rather than a guess.
  4. Worth a look while there: is `… N earlier lines` a number you would trust? It is
     wraps plus explicit breaks from a measured 56.4 characters a line, not a layout — an
     estimate by construction, because counting exactly means laying the text out.
  If you can get the mic to overflow again (the right-click menu held open is the one
  known way, ~16 s), the note beside "microphone overflowed" should now read
  **"voice is down — <your send combo> still sends; click the draft to edit, or
  right-click to copy it"**, once, with the combo that actually registered.

- [ ] **Read the shim refusal on a machine where a CLI *is* an npm shim** — a work laptop
  with `npm i -g @openai/codex` or the Claude equivalent, or install one deliberately
  somewhere disposable. Item 39 ships the refusal and everything about it is verified here
  *except how it reads to somebody who did nothing wrong*. Flow will say, before starting
  anything:
  `codex is a codex.cmd launcher - cmd.exe cuts its argument at the first newline, so it
  would answer a prompt it never saw. Install the native codex build rather than npm -g.`
  Two questions only you can answer: is that enough for you to know what to do next, and
  does it name the right thing to blame? The alternative shape — let the call through and
  get a fluent answer to a question the CLI never received — is the one this replaces, and
  it is worth seeing the refusal once to be sure the trade is right. If the wording is
  wrong, it is one string in `flow/refine.py`.
  The repair is already built and switched off: `Cli(..., stdin_ok=True)` sends the prompt
  on stdin, where `%*` is never involved, and a `.cmd` is then not refused. Nothing ships
  with it on, because turning it on for a CLI is a measurement — run that CLI reading a
  multi-line prompt from stdin, on the machine that has it, then set the flag.

- [ ] **Eyeball the pill's marker now that it reads `kiro`.** You answered the old version
  of this question — `ASK` while kiro-cli was the CLI about to answer read to you as "Kiro
  is not captured" — and item 41 shipped the alias from that. Run
  `uv run flow --converse --cli kiro-cli` and look at the slot under the mic glyph: it
  should say **`kiro`**, four characters where the name is eight. Two things are yours to
  say and neither has a measurement behind it. **One:** does `kiro` at 6 pt read cleanly
  beside the level bars, or does it want the same widening item 15's entry above asks about
  for `codex`? **Two:** is a *nickname* the right idea at all? The slot now shows a name
  that appears nowhere else — the menu, the notes and the Help sheet all say `kiro-cli` —
  and the alternative was widening the slot so the real name fits everywhere. Both are one
  small change; the alias is what shipped because it needed no new measurement.

- [ ] **On a macOS machine: install uv, run
  `uv tool install git+https://github.com/samartomar/flow`, grant microphone permission
  when asked, and use Lite for real work. After sustained use, record the one number the
  port decision waits on: how often the clipboard hop made you wish Flow had hands.**
  Lite starts itself off Windows — no flag needed — and says so on the first line. That is
  the whole instrument; there is no harness for this and there cannot be, because the
  question is how much a working day notices a keystroke (product.md, "Flow Lite").
  Nothing else about this is a decision waiting on you: the fence is written, the body is
  built, and a native macOS port stays unfunded until this number exists.

- [ ] **First, though: does the pill draw at all on macOS?** The one thing no Windows
  machine can answer, and the reason item 34 is `done (macOS check pending)`. Every Lite
  path is unit-tested here and `uv run flow --lite` runs the same code on Windows, but
  three Tk questions are genuinely open on the other platform: whether
  `overrideredirect(True)` gives a borderless always-on-top window that behaves (macOS
  treats it differently from Windows), whether `-alpha` is honoured, and whether the pill
  and bubble land inside the work area — `_work_area` falls back to the full screen
  off-Windows, so the pill will sit against the very bottom-right corner, under the Dock
  if the Dock is there. **If it is behind the Dock, that is the first fix and it is a
  small one** (an inset, or NSScreen's visible frame via whatever is already on the
  machine). Report what you see; do not work around it silently, because a Lite that is
  awkward for a reason nobody wrote down is the version this decision would be measured
  on.

- [ ] **Verify `copilot` — the four commands, then one line back here.** It is an inert
  entry in `refine.CANDIDATES` today: Flow will find it on PATH, say
  `found copilot, not yet verified`, and never call it. What settles it, on a machine that
  has it:
  1. `copilot --help` — does it have a headless, one-shot, prompt-in mode at all? (If it
     only opens a UI, say so and it comes *out* of the candidate list, the way `kiro`
     did.)
  2. the one-shot call with a **single-line** prompt, e.g.
     `copilot -p "Reply with exactly: PONG"` — record the exact flag, whether stdout
     carries the answer alone, whether the banner is on stderr, and the exit code;
  3. **the same call with a multi-line prompt** — this is the leg that matters and the one
     that failed for opencode. Use
     `"Repeat the SECRET below verbatim and nothing else.\n\nSECRET:\nmarmalade-42"` and
     require `marmalade-42` back. Every prompt Flow sends is multi-line;
  4. `echo $?` / `$LASTEXITCODE` after a deliberately bad call, so a failure is
     distinguishable from an empty answer.
  Write the answer into `flow/refine.py`'s `CANDIDATES` comment as the measurement, then
  flip the entry to `Cli("copilot", (<the argv you ran>,))` with no `verified=False`.

- [ ] **Verify `gemini`** — the same four commands, the same place to record it. Likely
  `gemini -p "<prompt>"`, but that is a guess and guessing is the thing this entry exists
  to refuse.

- [x] **`kiro-cli` — verified, all four legs, 2026-08-02, this machine.** The round's
  kiro rejection was measured against the wrong binary: `kiro` on PATH is the IDE
  launcher, but the owner's MSI install put a real headless agent **off-PATH** at
  `%LOCALAPPDATA%\Kiro-Cli\kiro-cli.exe`. Measured: `--version` →
  `kiro-cli-chat 2.16.0`; one-shot
  `chat --no-interactive --trust-tools= "<prompt>"` → answer, exit 0, ~1 s;
  **multi-line through Popen list-argv (the `_invoke` mechanism): a SECRET on the
  last line of a three-line prompt came back verbatim** — native exe, no shim, no
  truncation; bad args exit 2, loudly. Shape facts for the wiring: stdout carries
  furniture (ANSI colour, a `> ` answer prefix, a `▸ Credits: … • Time: …` status
  line — the CLI meters, ~0.10 credits/call) that the adapter must strip; detection
  by PATH works — the MSI adds `%LOCALAPPDATA%\Kiro-Cli\` to the user PATH (verified
  in the registry; the "off-PATH" first impression was this session's own stale
  environment, corrected by the owner's fresh shell finding it) — with the AppData
  probe kept only as cheap insurance for stale environments; `--trust-tools=`
  (empty) is the right courier default, no tool runs without asking. Wiring is in
  the next session's prompt (the shim item's session, second item).
- [ ] **Verify `opencode` on a machine where it is not an npm `.cmd` shim** (a Mac, or a
  Windows box with the real binary). Its single-line call already passes here — exit 0 in
  8.2 s, `PONG` alone on stdout, banner on stderr — and its multi-line call already fails
  here, for a reason that is the shim's rather than opencode's (see the `.cmd` entry
  above). So this is one command: leg 3 of the copilot list, with `opencode run`. If
  `marmalade-42` comes back, the entry becomes
  `Cli("opencode", ("opencode", "run"))` and the whole thing was an install artefact.

- [ ] **Run the misfire on purpose — switch workspaces mid-session and watch the notes
  name the ground.** Item 36 shipped from the day-one misfire (decisions.md "Workspace
  grounding"): Settings ▸ Workspace ▸ now lists the places `--cwd` has taken you,
  radio-ticked with "(not set)" included, and one tap switches. The desk check is the
  misfire inverted, run deliberately:
  1. `uv run flow --converse --cwd <project A>` — ask one question;
  2. right-click ▸ Settings ▸ Workspace ▸ tap project B (it is in the list if any
     launch ever used it; otherwise launch once with `--cwd <project B>` first);
  3. confirm the switch note said both things in one line — `workshop: B — new
     conversation` — then ask a second question and read nothing but the asking note:
     `asking codex · B…` is the fix working; `asking codex · A…` is a bug report.
  Worth an eye while there: re-open the menu and confirm the tick moved (the radio
  value handling is the one thing real Tk broke during the build, fixed by
  measurement), and the second answer should show no memory of question A — the
  thread was cleared, and a reply that references A is the contamination coming back.
  This is the purposeful re-run of the "Is a grounded answer actually less generic?"
  entry below: the misfire already substantially answered its A/B half — a grounded
  answer was concrete enough to be wrong about the *wrong* project — so what is left
  to look at is the fix, not the effect.

- [x] **The help window reads as part of Flow — checked and approved 2026-08-02.** All
  four questions came back good: the bubble's palette and spacing, the `Close` chip where
  a hand goes, **the window stays put while you keep typing in another one** (which was
  the one that mattered — `WS_EX_NOACTIVATE` read back `True` when it was built, and this
  is the confirmation that the style is doing what the read-back claimed), and **the wheel
  arrives**. Two things stay true anyway and are worth keeping in the record: the wheel
  works here because *Scroll inactive windows when I hover over them* is on, which is a
  Windows 11 default and a user preference — so the press-and-drag path stays, because a
  machine with that switched off would otherwise have a window it cannot scroll. And this
  approval is of a **1280×672 work area**, where the window comes up 600×624 with ~22 rows
  below the fold; a taller display shows the whole sheet with no thumb and no drag hint,
  which is a different thing to look at and has not been looked at.
- [x] **The six preset trigger words decode — checked at the mic 2026-08-02, all good.**
  `boom, tango, mango, falcon, rocket, banana`. So nothing comes out of
  `edits.SEND_WORD_PRESETS`, and no `wrong -> right` line is needed in `lexicon.txt` for
  any of them. This is the half the corpus gate structurally cannot measure — it prices
  false fires, and this priced recognition — so the list is now good on both counts for
  this voice. Fourteen gate-passing words remain unshipped and swappable on a word from
  you, `goose` among them: `pelican`, `zulu`, `kilo`, `jupiter`, `otter`, `thunder`,
  `comet`, `pixel`, `walrus`, `badger`, `cobra`, `domino`, `harbour`.
- [ ] **Run `uv run python scripts/send_check.py --live` once, now that the menu is two
  levels deep.** Not run in the loop session, deliberately: it drives the real mouse and
  steals the foreground, and you were not at the desk. The reason it is worth a run is
  narrow and specific — the menu now has a cascade *inside* a cascade (Settings ▸ Trigger
  word ▸), and the foreground borrow-and-return around `tk_popup` was measured for a
  single-level popup under `WS_EX_NOACTIVATE`. Single cascades already worked (Voice,
  Agent CLI, Never offer), so this is the depth being new rather than the mechanism. The
  harness's own check is "the right-click menu opens and dismisses"; open the nested one
  by hand while it runs and confirm the submenu takes a click rather than hanging the
  pump.
- [ ] **Record more L1 anchor groups** per `docs/recording-kit.md` — two groups exist,
  the smoke benchmark wants 3–5 speakers per anchor group. New clips go to
  `D:\dev\flow-recordings\recorded\inbox\`, then copy into `.bench/recorded/` and run
  `scripts/ingest_recordings.py` (git ignores them now).
- [x] **The `--takes 3` measurement — done 2026-08-01, the best sheet ever recorded:
  29/33 (was 21/33 across the three single takes), takes of 11/11, 9/11, 9/11, seven
  items stable, nothing at zero.** Committed with its identity block (item 18 working
  live). Scored against the four predictions:
  - **Item 4 — confirmed, causally.** 3/3, including take 3 decoding "release nodes"
    and still routing `local/lower`. The spelling-variant fix is real.
  - **Item 9 — confirmed for "brown", and the family is open.** Take 1's "Make it a
    proper brown." — the exact decode that missed in run 1 — now reaches
    `semantic/polish`. But take 3 produced a *new* noun: "Make it a proper **font**."
    → `semantic/` unpolished. The lookup table admits only what is in it; "font" is
    plan item 26, same bounds as "brown".
  - **Item 10 — 3/3, but not attributable to item 20.** All three takes decoded
    "follow **up** and…" with the particle intact, so the admitted `follow and` path
    was never exercised live. The fix stays proven by its fixtures and its 0/580 gate,
    not by this run.
  - **Item 2 — still untestable, and still the weakest item.** 2/3, both hits the
    homophone no-op ("Change Samir to Samir"), the miss a full-sentence mis-decode
    ("It's time to send me" → silent append). **`lexicon.txt` now exists but the
    `semir -> Samir` line has still not been typed** — 30 seconds, right-click →
    Open settings folder, and the next run makes this prediction testable.
  - **Unpredicted:** item 7 went 3/3 *without* its Phase 3 fix — "draft" survived
    decoding all three takes (and "nodes"→"notes" snapped at 0.900, in range all
    along). Item 5 reproduced its pinned miss exactly once ("standard" vs "standup",
    0.667 — the Phase 3 fixture behaving as documented). And item 3 *fell out* of the
    stable set ("Samir" → "some you"): membership of the stable set changed for the
    fourth time in four measurements, which is the whole argument for `--takes`.
  P3's bar is ≥95%; this run is 88%. The gap is now concentrated in decode variance on
  content words — Phase 3 territory — not in the grammar.
- [ ] **Is a grounded answer actually less generic?** The felt half of item 23, and the
  one thing no unit test can settle. Ask the *same* question about your real repo twice,
  once with the workspace set and once without, and keep both transcripts:

  ```bash
  uv run python -m flow --converse --cwd D:\dev\products\acme
  ```

  Then the same again with no `--cwd`. Startup names which it got either way ("workshop:
  …" / "workshop: not set"), so there is no ambiguity about what you measured. What to
  look for: whether the grounded answer names real files, real conventions and real
  constraints from that project, or whether it is the same generic advice with a path
  mentioned in it. If it is the latter, the preamble is the thing to change, not the
  setting — the workspace reaches the CLI as text, and `codex`/`claude` decide for
  themselves whether to go and look. Worth recording either way, because the stale-path
  risk you accepted is only worth accepting if the grounding buys something.
  To make it permanent afterwards, `workspace` is a field in `profile.json` — or say the
  word and it becomes a menu entry, since you will not hand-edit it.
- [ ] **Eyeball the converse marker** — item 15 landed (`d1d2b51`), so this is live now:
  arm converse mode and look at the pill. The unit test can only prove the string is right and ≤6 characters;
  whether `codex` at 6 pt collides with the bottom of a tall level bar (bars run y 8–32,
  the marker's baseline is y 33) is a thing eyes decide.
- [ ] **Consent scope:** `docs/recording-kit.md` — one paragraph telling volunteers
  where recordings are stored (a private folder; a private repo's *history* no
  longer; keep it true).
- [ ] **The wake experiment** — run it the next time a spoken reply plays, with the
  predictions written down first so it is a measurement, not an impression. Prediction:
  while the reply plays *and for roughly its own duration again after the audio ends*,
  nothing spoken wakes Flow — shouting included, by design (the audio is discarded as
  presumed echo, and the discard is not level-based; `WORDS_PER_SEC` = 1.5 is
  deliberately half the measured rate, so estimated deafness runs ~2× the audio). The
  test is when the level bars respond to your voice again: almost immediately after the
  audio stops → the estimate is fine, nothing to fix; a dead stretch about as long as
  the reply itself → the 2× estimate is confirmed, and the fix to spec is ending
  deafness when the SAPI child actually exits. Separate case, by design not defect:
  every fresh launch starts disarmed (`arm=False`), so the first Ctrl+Alt+Space of a
  session is a choice — if *that* is the annoyance, an arm-on-launch preference is a
  cheap separate decision.
- [x] **README is behind the lexicon file** — done in the review session, commit
  `Catch the README up…`, plus a fifth stale spot the entry missed: the storage table
  still said the volunteer recordings were tracked.

## Parked — the evidence is now arriving, and is not yet enough (updated 2026-08-01 evening)

**`diag.jsonl` exists — 419 records from ~5 launches on 2026-08-01**: 229 decodes,
26 asks (the workshop got real use), 24 append routes, **2 refines**, and one stale
discard already recorded. The collection both entries wait on has started. Where it
stands against the bars: **2 of ≥30 refines** for the stale-rewrite entry; state
transitions are accumulating toward P2's ~200 pauses but are nowhere near it. Also
noted from the profile: a voice is chosen ("Microsoft George"), `auto_ask` is stored
ON, and `pairs` is still `{}` — no spoken "change X to Y" correction has occurred in
real use yet, so item 19's menu has had nothing to offer.

**What fills both:** keep using Flow plainly. The refine counter is the slow one —
rewrites happen a few per session, so ≥30 is likely two or three more real working
sessions away.

- [ ] **What a stale rewrite should cost.** Today it loses to newer words, visibly. The
  third option — re-run the instruction against the moved draft, once, for ~7 s more —
  needs the rate at which you speak inside a rewrite window. **Enough is ≥30 completed
  refine operations across ≥3 sessions.** A measured rewrite runs 5.7–7.3 s (§8
  `TIMEOUT_SEC`), so the window is real but narrow; under 30 rewrites a single incident
  reads as 3% or 10% depending on nothing, and either number would pick a different
  design. The trace already carries operation ids, durations and state transitions —
  no new instrument, just sessions.
- [ ] **P2 — adaptive auto-ask timeout.** Collect first: within-utterance pause
  distribution is already derivable from `~/.flow/diag.jsonl` state transitions; ~200
  pauses over ≥3 sessions before offering adaptive; then p95 + 0.5 s clamped [3.0, 8.0]
  as a profile field. The bar was always right; the file is empty of records because it
  is absent.

## Proposals still waiting (unchanged)

- [ ] **P3 — streaming replies.** Both CLIs stream JSONL today; ask-only, sentence
  buffer in `_pump_ask`, late chunks gated by the operation ids that now exist. The
  felt gain is on-screen only (SAPI cannot append to an utterance), which is why this
  waits.

- [ ] **P10 — a reply that actually scrolls.** Found while building item 42, and it is a
  claim the reference had been making without anybody checking it: §8's
  `ASK_ARTIFACT_MAX_CHARS` row said "the bubble scrolls", and it does not — no path does.
  That assumption is why the reply kept an unbounded full-text probe while the draft got a
  cap, and it is how a 12 000-character answer came to size the window **4 179 px** on a
  672 px desktop with its chip row at screen y 4 147. Item 42 fitted the window to the
  desktop, which makes the chips reachable and leaves the tail clipped; the row is
  corrected to say what is true.
  The real cure is a reply the eye can move through, and it is a *proposal* because the
  shape is a genuine choice and item 37 already rejected the obvious one for the draft: a
  scrollback has to lay out what it scrolls to, which is the cost the cap exists to bound.
  Three candidates, and the difference matters. **(a)** A tail window like the draft's —
  cheapest, reuses `body_window`, and exactly wrong here, because an artifact is read from
  the *top* and its first lines are the ones you want. **(b)** A head window with a
  `… N more lines` foot and Copy/Use this as the way to get the rest — nearly as cheap and
  probably right, since a bubble is not where a two-page prompt gets read. **(c)** A real
  scrolling viewport like the Help sheet's (item 32 already built one: drag or wheel, a
  thumb, bounded row layout) — the most work and the only one that makes the bubble a place
  you can read an artifact in. Which of those is right is a taste question about what the
  bubble is *for*, so it is yours; the measurement each would need is the same one item 37
  ran, and the instrument exists.

