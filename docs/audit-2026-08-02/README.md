# Flow whole-product audit — 2026-08-02

## Outcome

The repository has strong internal documentation and a large passing unit suite, but it is
**not ready to claim its documented security boundary, terminal-safety invariant, or full
P1–P9 product acceptance**. The audit found high-severity defects that passing tests do not
exercise: agent-capable CLIs run inside project workspaces without tool/config isolation,
Windows executable lookup can prefer a hostile current-directory binary, terminal paste can
execute content unexpectedly, failed Ctrl-V injection can still be followed by Enter, final
transcripts can be associated with the wrong audio, and exact edit matching can alter text
inside unrelated words.

This is a review report, not a patch set. No runtime source was changed.

## Validation, 2026-08-03

The reports were written on 2026-08-02 by specialist agents and are checked in here as the
record a remediation round executes against. Before that round opened, 30 findings were taken
back to source or re-run as instruments. **27 reproduced.** What did not survive is corrected
in place rather than quietly dropped, so a reader of a finding sees what happened to it:

| Correction | Finding | What changed |
|---|---|---|
| False positive | DESKTOP-06 | Withdrawn — `ui.py:1110` already reschedules in `finally`, with the docstring the fix asked for. The ID is retired, not reused. |
| Wrong mechanism | DESKTOP-04 | Both stated failures are blocked by the sequence check at `inject.py:239`/`:258`. The residual defect — a second send capturing Flow's own payload as `previous` — is what the section now describes. |
| Wrong citation | CAP-02 | `audio.py:102-106` is `Mic.stop()` and touches no gate state; the finding stands on `session.pause()` at `session.py:557-570`. |
| Swapped citations | SPEECH-01 | `330-352` is `_watch`, `399-417` is `say`. |
| Overstated | DRAFT-04 | "Quadratic-like" against its own linear table; characters here against words in the performance review. Both re-measured; severity Medium. |
| Understated | RELEASE-07 | ~90×, not 54×, and `.claude/` ships larger than `.bench/`. The cited `pyproject.toml` lines are the wheel target and are correct; the defect is the absent sdist config. |
| Overclaimed evidence | CLI-01 | The probe reproduces only with `NoDefaultCurrentDirectoryInExePath` cleared, which the audit shell was not. The finding stands for ordinary launches. |

Every correction is dated in the section it touches and carries the reproduction that
established it. Nothing else in these reports was edited.

## Reports by review focus

Each requested specialist pass has its own cross-product report. The product-surface reports
below contain the deduplicated evidence and remediation details.

| Review focus | Dedicated report | Result |
|---|---|---|
| Code quality and correctness | [review-code-quality.md](review-code-quality.md) | 12 retained themes; destructive edit and injection defects lead |
| Security, privacy, trust boundaries | [review-security.md](review-security.md) | 4 high-impact trust/OS-boundary defects plus hardening gaps |
| Potential failures and reliability | [review-failure-modes.md](review-failure-modes.md) | State, recovery, queue, persistence, and shutdown failures across all surfaces |
| Performance and resource behavior | [review-performance.md](review-performance.md) | 12 measured/static findings across every surface |

## Reports by product surface

| # | Focus area | Report | Highest severity |
|---|---|---|---|
| 1 | Capture, transcription, filtering, product accuracy | [01-capture-transcription.md](01-capture-transcription.md) | High |
| 2 | Draft routing, editing, rescue, history | [02-draft-routing-history.md](02-draft-routing-history.md) | High |
| 3 | Agent-backed Refine, Converse, workspace egress | [03-agent-refine-converse.md](03-agent-refine-converse.md) | High |
| 4 | Speech output and half-duplex control | [04-speech-output.md](04-speech-output.md) | High |
| 5 | Desktop UI, hotkeys, paste, clipboard | [05-desktop-ui-os-integration.md](05-desktop-ui-os-integration.md) | High |
| 6 | Calibration, profile, lexicon, diagnostics | [06-personalization-diagnostics.md](06-personalization-diagnostics.md) | High |
| 7 | CLI, Lite, startup, shutdown lifecycle | [07-cli-lite-lifecycle.md](07-cli-lite-lifecycle.md) | High |
| 8 | Packaging, release, scripts, test strategy | [08-packaging-release-tooling.md](08-packaging-release-tooling.md) | Medium |

## Immediate priorities

| Priority | Finding | Why it is first |
|---|---|---|
| P0 | AGENT-01 — isolate Codex/Claude/Kiro from workspace instructions, tools, hooks, MCP, user config, and unrelated environment secrets | The implemented egress/execution boundary is much wider than the documented prompt-only boundary. |
| P0 | CLI-01 — exclude the current directory from executable resolution and run validated absolute paths | A repository-local `pwsh.exe`, `codex.exe`, or `claude.exe` can execute during ordinary startup/use. |
| P0 | DESKTOP-01 — fail closed for unbracketed or ambiguous terminal targets | Current code can paste interior newlines that execute before its warning is shown; integrated terminals are classified as editors. |
| P0 | DESKTOP-02 — require complete Ctrl-V injection before Enter | A blocked/partial paste can still submit pre-existing shell text. |
| P1 | CAP-01 — bind each final decode result to its own audio/utterance identity | Rescue can re-decode a different utterance from the transcript being rescued. |
| P1 | DRAFT-01 — require token/phrase boundaries for exact edit targets | `delete art` currently turns `cart` into `c`. |
| P1 | DRAFT-02 / DRAFT-03 — revision-bind and invalidate post-hoc rescue state | Stale rescue can duplicate or rewrite newer draft content. |
| P1 | DESKTOP-03 / DESKTOP-04 — make clipboard handling one owned, full-format transaction | Images/files/rich clipboard data are discarded, and a second send inside the first send's restore delay replaces the user's clipboard with Flow's own text. |
| P1 | PERSONAL-01 — validate the entire profile schema before accepting it | Valid JSON with wrong types crashes startup despite the documented fallback contract. |
| P1 | CAP-05 / CAP-06 — close P2 recovery and measured P1/P3/P4 acceptance gaps | The product definition still has unmet or unproven acceptance tests. |

## Coverage matrix

Every runtime module and each operational surface was reviewed under four dedicated passes:
code quality/correctness, security/privacy, potential failure/reliability, and performance/
resource behavior. The performance pass was a separate agent turn because the root agent hit
its three-child creation limit after starting the other reviewers.

| Surface | Code | Security | Failure | Performance | Reported |
|---|---:|---:|---:|---:|---:|
| Audio capture / ASR / filtering | yes | yes | yes | yes | yes |
| Draft / routing / edits / phonetics / thread | yes | yes | yes | yes | yes |
| Refine / Converse / workspace / provider CLI | yes | yes | yes | yes | yes |
| Speech output | yes | yes | yes | yes | yes |
| UI / hotkeys / injection / help | yes | yes | yes | yes | yes |
| Calibration / profile / lexicon / diagnostics | yes | yes | yes | yes | yes |
| CLI / Lite / startup / shutdown | yes | yes | yes | yes | yes |
| Packaging / release / scripts / tests / docs | yes | yes | yes | yes | yes |

Reviewed production files: all 19 modules under `flow/`, `pyproject.toml`, `uv.lock`,
`packaging/entrypoint.py`, `packaging/flow.spec`, `.github/workflows/release.yml`, all test
modules, all scripts, and the current README/product/architecture/decision/roadmap documents.

Runtime inventory: `__init__.py`, `__main__.py`, `audio.py`, `asr.py`, `clean.py`,
`edits.py`, `phonetic.py`, `session.py`, `thread.py`, `refine.py`, `speak.py`, `ui.py`,
`hotkey.py`, `inject.py`, `help.py`, `calibrate.py`, `profile.py`, `lexicon.py`, and `diag.py`.

## Verification performed

| Check | Result |
|---|---|
| `uv run python -m unittest discover -s tests` | **1,089 passed** in 23.933 s on the root run; reviewers independently reproduced a passing suite. |
| `uv run python -m compileall -q flow scripts tests` | passed |
| `uv run python -m flow --help` | passed; current CLI surface rendered |
| `uv run python scripts/command_bench.py` | reproduced 100% snapped synthetic recall, 5/20 adversarial misroutes, 0/580 real-utterance misroutes, and the recorded threshold sweep |
| `uvx bandit -q -r flow packaging scripts` | 0 high, 1 medium (developer data-fetch URL handling), 32 low scanner findings |
| `uvx pip-audit --path .venv\\Lib\\site-packages` | no known vulnerabilities in installed third-party packages; local `flow` package skipped as non-PyPI |
| Local `codex exec --help`, `claude -p --help`, `kiro-cli chat --help` | confirmed omitted sandbox/tool/config isolation controls and Claude's noninteractive workspace-trust warning |
| Profile type fault injection | reproduced `AttributeError`/`TypeError` for schema-1 JSON with numeric send word, scalar workspaces/dismissed values, and string calibration values |
| Edit-target fault injection | reproduced `delete art` → `cart` becomes `c`; `replace all art with x` corrupts `cart` occurrences |
| Long-draft routing microbenchmark | absent-target plan measured ~38 ms/2k, 371 ms/20k, 3.7 s/200k, 37 s/2M **characters** on the UI pump; re-measured 2026-08-03 and re-stated with the word-count column in [DRAFT-04](02-draft-routing-history.md#draft-04--missing-target-search-freezes-interaction) |
| Windows executable lookup probe | `shutil.which("pwsh")` resolves `.\pwsh.EXE` from the current directory **when `NoDefaultCurrentDirectoryInExePath` is cleared**; the audit shell exported it as `1`, under which the same probe returns the WindowsApps path. Ordinary launches are the first case — see [CLI-01](07-cli-lite-lifecycle.md#cli-01--current-directory-executable-hijacking) |

The command benchmark changed only its recorded date; that diagnostic change was restored.
The pre-existing edits to `LOOP_PLAN.md` and `NEEDS_YOU.md` were not touched.

## Severity model

- **High:** credible code execution, unintended command execution/egress, permanent user-data
  loss, destructive silent text corruption, or loss of a core product invariant.
- **Medium:** user-visible incorrect behavior, bounded privacy leak, recoverability/lifecycle
  failure, substantial stall/resource growth, or a release-control gap needing correction.
- **Low:** hardening, documentation drift, maintainability, or a narrow edge with limited impact.

## Important limitations of this audit

- No microphone/person-dependent `live_check.py`, real-mouse `send_check.py --live`, model-heavy
  accent benchmark, or external-provider self-drive was re-run. The reports distinguish the
  repository's recorded measurements from checks performed during this audit.
- Security analysis establishes what the current local CLI flags permit; it did not execute an
  adversarial provider prompt or a malicious binary.
- Static scanners are supporting evidence only. Findings were retained only when source or a
  targeted reproduction established the scenario.

## Exit criteria for a follow-up remediation run

1. All P0 findings fixed with negative regression tests.
2. Clipboard and rescue/data-association P1 findings fixed before relying on “non-destructive.”
3. Provider isolation documented from actual invocation tests for every verified CLI.
4. P1–P4 product acceptance table refreshed with current, non-contradictory measurements.
5. PR/push CI covers Windows plus real Lite imports/startup on macOS and Linux.
6. Full unit suite, command benchmark, self-drive, real-mouse Send check, and applicable human
   gates rerun; results record versions/model revisions and link back to this audit.
