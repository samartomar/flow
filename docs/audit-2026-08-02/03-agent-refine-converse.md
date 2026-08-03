# Focus area 3 — Agent-backed Refine, Converse, and workspace egress

## Scope and trust boundary

Reviewed `refine.py`, the Refine/Ask paths in `session.py`, `thread.py`, workspace selection,
provider discovery/cancellation, local provider CLI help, and relevant product/security docs.
The architecture describes a prompt-oriented subprocess boundary. The implementation actually
starts agent-capable CLIs with wider ambient authority.

## Findings

| ID | Severity | Finding |
|---|---|---|
| AGENT-01 | High | Provider agents run inside the selected project with tools/config active. |
| AGENT-02 | Medium | Full prompts are exposed in argv and children inherit the full environment. |
| AGENT-03 | Medium | Provider stdout/stderr is fully buffered before limits apply. |
| AGENT-04 | Medium | Workspace/provider can change while an operation is in flight. |
| AGENT-05 | Medium | NaN/infinite timeout values evade normal validation. |
| AGENT-06 | Medium | Ask failure can hide the user's question and weaken recovery. |
| AGENT-07 | Medium | Output cleanup destroys nested Markdown fences. |
| AGENT-08 | Low | Automatic fallback can disclose one prompt to multiple vendors. |
| AGENT-09 | Medium | Sequential fallback can multiply the configured wait budget. |

## Detailed evidence and remediation

### AGENT-01 — The documented AI boundary is not the executed boundary

`refine.py:183-188` defines the Codex, Claude, and Kiro commands. `refine.py:482-496`
launches them with the selected project as `cwd`; the Refine and Ask paths pass that workspace
at `session.py:1646-1652` and `session.py:1823-1862`. There is no consistent disabling of
project instructions, user config, hooks, plugins, MCP, tools, repository discovery, network,
or writes. Local help confirmed available isolation controls are omitted and Claude's
noninteractive mode skips workspace trust.

**Impact:** a hostile or merely customized repository can influence the agent and access files,
commands, services, or secrets beyond the visible prompt.

**Fix:** run from a neutral directory with a provider-specific, verified non-agentic/no-tool
profile; disable project/user rules, hooks, plugins and MCP; impose filesystem/network
sandboxing and an environment allowlist. Make repository access a separately disclosed opt-in.
Write adversarial workspace tests for every supported provider/version.

### AGENT-02 — Prompt and secrets cross ambient OS boundaries

All shipped candidates are configured without stdin at `refine.py:183-188`; the completed
prompt is appended to argv at `refine.py:483-496`. No restricted `env` is supplied.

**Impact:** draft/thread content may enter process inspection, EDR and crash telemetry, while
unrelated AWS/GitHub/database credentials are available to the child and any enabled tools.

**Fix:** send content over stdin or a tightly ACL'd transient channel, and construct a minimal
environment containing only required locale/path/provider credentials. Document unavoidable
local observability.

### AGENT-03 — Output bounds are applied after allocation

`refine.py:507-523` uses `communicate()` to buffer all stdout/stderr; caps at
`refine.py:638-646` and `refine.py:704-709` run only afterward.

**Fix:** stream both pipes with hard byte budgets, terminate the process tree on overflow,
and return a bounded diagnostic. Test infinite and high-rate producers without deadlock.

### AGENT-04 — Operation execution context is mutable

Workspace and provider are selected in session paths around `session.py:1232-1235` and
`session.py:1646-1653`, while operations complete asynchronously. A user can change context
mid-operation, making result attribution and subsequent context surprising.

**Fix:** snapshot provider identity, executable path, cwd, prompt, thread revision, and operation
ID into an immutable request; display that identity with failures/results; reject stale commits.

### AGENT-05 — Non-finite timeout values

CLI parsing at `__main__.py:125-127` accepts floats; the process wait loop at
`refine.py:500-518` assumes a finite value. `NaN`/`Infinity` can defeat ordinary comparisons
or create effectively unbounded behavior.

**Fix:** require `math.isfinite(timeout)` and a documented positive range at every public
entry point. Add NaN, positive/negative infinity, zero, and extreme tests.

### AGENT-06 — Ask failure loses the visible recovery anchor

Question/draft clearing around `session.py:1786-1801` precedes provider completion, while
failure handling at `session.py:1878-1882` does not reliably restore an actionable question.

**Fix:** retain the question until success, or restore it atomically with a retry affordance
and the same workspace/provider identity after failure/cancel/timeout.

### AGENT-07 — Cleanup strips meaningful inner fences

If output begins fenced, `_clean()` at `refine.py:573-588` removes every line beginning with
backticks, including nested blocks. A generated Markdown artifact can silently lose structure.

**Fix:** strip only one matching outer first/last fence and preserve all internal fence lines.
Test multiple, nested, unmatched, and language-tagged fences.

### AGENT-08 — Multi-vendor fallback expands egress

Fallback at `refine.py:284-326` can send the same content to another vendor after failure or
timeout. This behavior is documented, so it is an accepted risk rather than a hidden defect,
but a late provider response or ambiguous timeout makes the actual recipient set non-obvious.

**Fix:** default to one pinned provider; require explicit consent for cross-vendor fallback and
record a local bounded disclosure receipt.

### AGENT-09 — Fallback has no overall deadline

Providers run sequentially at `refine.py:284-319` and each receives the full timeout in the
wait loop at `refine.py:500-518`; Kiro also has a documented 60-second floor around
`refine.py:170-179`. Several installed but unhealthy CLIs can make one action wait far longer
than the user's configured expectation.

**Fix:** establish one operation deadline, subtract elapsed time from later attempts, surface
each fallback transition, and test cumulative duration with several hanging providers.

## Strengths and validation

The code avoids `shell=True`, directly interpolated shell prompts, and unescaped regex input.
Some result paths already reject stale operation/revision IDs. Local CLI help was used only to
confirm the currently available controls and warnings; this audit did not run an adversarial
provider prompt. The unit suite passed.
