# Focus area 7 — CLI, Lite, startup, and shutdown lifecycle

## Scope and operating contract

Reviewed `__main__.py`, Lite selection/startup, provider and speech discovery invoked during
startup, cleanup ownership, CLI validation, and cross-platform documentation/tests.

## Findings

| ID | Severity | Finding |
|---|---|---|
| CLI-01 | High | Current-directory executable lookup permits repository-local code execution. |
| CLI-02 | Medium | Shutdown does not join/close all resources and exceptional paths lack one owner. |
| CLI-03 | Medium | Startup diagnostics execute provider binaries unnecessarily. |
| CLI-04 | Low | Lite/platform/distribution documentation contradicts implemented behavior. |
| CLI-05 | Medium | Repeated arming spawns duplicate preload waiters. |

## Detailed evidence and remediation

### CLI-01 — Current-directory executable hijacking

Provider lookup at `refine.py:237-245` and execution at `refine.py:470-486` use
`shutil.which`; on the audited Windows runtime it resolves an executable from the current
directory before PATH. Speech lookup at `speak.py:141-146` validates with `which` but returns a
bare name used at `speak.py:178-184` and `speak.py:361-372`. Voice enumeration is reached at
ordinary startup (`__main__.py:233-257`). Diagnostics run bare provider names at
`diag.py:241-280`, reached from `__main__.py:382-393`; cancellation also invokes bare
`taskkill` at `refine.py:392-413`.

**Attack scenario:** launch Flow inside a cloned repository containing `pwsh.exe`,
`powershell.exe`, `codex.exe`, or `claude.exe`; malicious code can run with the user's ambient
credentials before dictation or on first use.

**Environment caveat, added 2026-08-03 — the original evidence sentence overclaimed.** Windows
suppresses the current-directory search when `NoDefaultCurrentDirectoryInExePath` is set, and
the shell the audit ran in exports it as `1`. Re-running the probe both ways from a temporary
directory holding an empty `pwsh.EXE`, which was never executed:

| `NoDefaultCurrentDirectoryInExePath` | `shutil.which("pwsh")` |
|---|---|
| cleared | `.\pwsh.EXE` — the planted file |
| `1` | `C:\Users\…\WindowsApps\pwsh.EXE` |

So the reproduction needs the variable cleared, and the audited shell was not the vulnerable
configuration. **The finding stands unchanged for ordinary launches**: the variable is present
only in that shell's own process environment — both the User and Machine scopes on this machine
read empty — so Explorer, a shortcut, and a fresh `cmd`/PowerShell session all reach the first
row, and nothing in Flow sets it. What changes is that this is a property of the launching
environment rather than of the runtime, which is also what makes the one-line fix possible:
Flow can set for itself the condition its own audit shell happened to have.

**Fix:** resolve only from explicit trusted directories excluding cwd, retain and execute the
validated absolute path, use fixed System32 locations for system tools, allow explicitly
configured provider paths, and optionally verify publisher/signature. Test with hostile cwd and
PATH entries. Replace `taskkill` process-tree management with a Windows Job Object.

### CLI-02 — Cleanup ownership is incomplete

`Session.close()` at `session.py:580-588` signals but does not bounded-join the decode worker,
does not close the speaker (`speak.py:426-436`), and does not own the preload daemon. Main paths
around `__main__.py:273-299` and `__main__.py:403-408` do not consistently put all acquired
resources under one `try/finally`; calibration constructs a Session but stops only the mic.

**Impact:** repeated/embedded runs, mainloop exceptions, calibration, or active decode can leave
threads or a PowerShell host alive and race process teardown.

**Fix:** make Session an idempotent context manager owning capture, decode, preload, provider
operations, speaker, and callbacks. Stop admission, cancel, bounded-join, then close dependencies
in a documented order. Test exception at every startup stage and repeated `main()`/close.

### CLI-03 — Version diagnostics execute ambient binaries

`diag.py:241-280` starts `codex --version` and `claude --version` during a profiled startup
thread. Beyond CLI-01, this runs third-party initialization/config merely to label diagnostics.

**Fix:** avoid executing providers until requested. Prefer metadata from a trusted configured
path, or collect version only after explicit provider use and with the same sandbox/env controls.

### CLI-04 — Lite documentation drift

`README.md:58-62` says non-Windows exits while `__main__.py:136-146` starts Lite. The README
also says no frozen executable despite `.github/workflows/release.yml:49-76`, describes the
whole product as Windows-only instead of separating full Flow from Lite, and contains stale test
counts. ASR documentation also claims partial-only never loads final while Session preloads both.

**Fix:** create one generated capability matrix for Full vs Lite by OS, align install/release
instructions with artifacts, and avoid hard-coded test counts unless CI updates them.

### CLI-05 — Preload work is not single-flight

The arming paths at `session.py:507-519` and `session.py:549-555` can start another preload
thread while an earlier model load is blocked. A controlled 100 arm/pause loop produced 100
live preload threads. This compounds CLI-02's missing joins and late-work rejection.

**Fix:** maintain one owned preload future/generation, make arm/start idempotent, and cancel or
join it during close. Repeated rearming must keep the preload thread count constant.

## Strengths and validation

`python -m flow --help` passed and the CLI surface is coherent for normal finite inputs. The
Windows lookup precedence was reproduced safely with an empty temporary executable and the
directory was removed afterward. No malicious binary was executed. Cross-platform Lite was not
actually started on macOS/Linux in this Windows audit; focus area 8 requires CI coverage.
