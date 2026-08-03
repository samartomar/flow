# Focus area 5 — Desktop UI, hotkeys, paste, and clipboard

## Scope and safety contract

Reviewed `ui.py`, `hotkey.py`, `inject.py`, `help.py`, native Windows calls, target tracking,
clipboard transactions, Send/submit behavior, layout, and tests. The product's strongest
desktop invariant is “paste, never unexpectedly execute”; failures must be nondestructive and
recoverable.

## Findings

| ID | Severity | Finding |
|---|---|---|
| DESKTOP-01 | High | Terminal identification fails open; multiline paste can execute commands. |
| DESKTOP-02 | High | Enter can be injected after Ctrl-V failed or was partial. |
| DESKTOP-03 | High | Sending destroys non-text/rich clipboard formats. |
| DESKTOP-04 | High | A second send captures Flow's own text as the clipboard to restore. |
| DESKTOP-05 | Medium | Clear bypasses Session state and leaves stale follow-up/rescue state. |
| DESKTOP-07 | Medium | Reachable chip combinations overflow the fixed bubble. |
| DESKTOP-08 | Medium | Modal/menu and synchronous planning paths can stall the UI pump. |
| DESKTOP-09 | Medium | Every restored paste creates a new sleeping thread. |

## Detailed evidence and remediation

### DESKTOP-01 — Terminal safety is incomplete and too late

`inject.py:295-317` recognizes a fixed list of top-level terminal classes/processes;
`inject.py:397-405` classifies the top-level HWND; `inject.py:448-471` strips trailing line
breaks only for a recognized terminal. VS Code, JetBrains, and other integrated terminals
share an editor top-level process and are misclassified. For legacy terminals, existing tests
at `tests/test_inject_target.py:235-239` explicitly expect warning-and-proceed behavior.

Interior newlines can execute earlier shell lines immediately on paste, before a warning helps.

**Fix:** always remove trailing CR/LF, identify the focused child/control with UI Automation,
fail closed when terminal/editor identity is ambiguous, and require explicit confirmation or
bracketed-paste capability for multiline terminal payloads. Add real integration tests for
Windows Terminal, console host, VS Code terminal, PowerShell ISE/editor, and focus changes.

### DESKTOP-02 — Submission ignores the actual SendInput result

`inject.py:88-90` returns inserted event count, but callers at `inject.py:241` and
`inject.py:253` ignore it; `inject.py:271` reports success. A zero/partial Ctrl-V may still be
followed by Enter, potentially executing pre-existing shell text.

**Fix:** require all four paste events, never submit on partial insertion, revalidate the
foreground target immediately before submission, and validate Enter too. Preserve the payload
for manual recovery on failure. Test zero, every partial count, target change, and UIPI denial.

### DESKTOP-03 — Clipboard transaction loses user data

`inject.py:93-108` saves only Unicode text. `inject.py:111-135` empties the complete clipboard;
image/file/HTML/RTF formats are discarded, a limitation acknowledged at `inject.py:227-233`.
The restore result at `inject.py:255-270` is ignored. Allocation/write failure after
`EmptyClipboard()` can also erase the original before paste begins.

**Fix:** preserve the full OLE clipboard data object, or refuse with a clear warning whenever
formats cannot be preserved. Allocate/populate before emptying; verify install and restore;
surface a durable recovery action when restoration fails.

### DESKTOP-04 — The second send borrows from the first

*Rewritten 2026-08-03: the two failures originally stated here are already blocked, and the
reproduction that was supposed to show them showed a different defect instead.*

`clipboard_sequence()` is stamped at `inject.py:239` the moment Flow's payload lands and
re-read at `inject.py:258` before the delayed restore commits. A later send moves that counter,
so the older timer refuses rather than overwriting it, and a user copy made during the 600 ms
window is kept for the same reason. Both stated failures are covered.

What is not covered is where `previous` comes from. `inject.py:233` reads the clipboard as it
stands *now*; when send B runs inside send A's restore delay, what stands there is **send A's
own payload**. B therefore schedules a restore of Flow's text, and the user's original is
overwritten by Flow rather than by another application — permanently, with no warning, because
from B's point of view nothing anomalous happened.

**Reproduced 2026-08-03** with the native calls faked and the delay shortened, two `paste()`
calls back to back:

| Moment | Clipboard |
|---|---|
| before any send | `the user's own clipboard` |
| after A's paste | `send A text` |
| after B's paste | `send B text` |
| after both restores fired | `send A text` |

A's restore correctly declined and said so — *"kept what you copied since - the clipboard Flow
borrowed was not put back"* — which is the counter check working. B's restore then completed
against a `previous` it should never have captured.

**Fix:** carry the value to restore with the transaction rather than re-reading it per send.
One owner holds the original from the first send until the last restore in a burst commits, and
a send that finds Flow's own payload on the clipboard restores nothing. Test two-send,
manual-change, cancel, and application-exit interleavings.

### DESKTOP-05 — UI Clear violates state ownership

`ui.py:1072-1078` directly clears the Draft and hides the bubble rather than using a
Session-owned transition. It leaves state such as `_settled_at`, `_last_append`, follow-up mode,
countdown, and possibly DRAFT capture state inconsistent.

**Fix:** provide one Session cancel/clear operation that emits the empty revision, invalidates
rescue/async work, clears follow-up/countdown, and settles capture. UI must call only that API.

### DESKTOP-06 — withdrawn, and the number is left empty on purpose

The finding claimed the recurring tick could raise before re-registering `after()` and leave a
pill on screen with a dead pump. `ui.py:1093-1110` — the lines the finding itself cited — is
`_tick`, and it does the opposite: `_frame()` runs inside `try`, any exception becomes a red
flash plus a visible note, and `self.after(30, self._tick)` sits in `finally` at `ui.py:1110`.
The docstring above it states the reasoning the fix asked for, in the same terms.

Withdrawn 2026-08-03 against those lines. The identifier is retired rather than reused and the
later numbers do not shift: DESKTOP-07 through -09 keep the IDs the other reports link to, and
a gap in the sequence is cheaper than a renumbering that silently re-points a citation.

### DESKTOP-07 — Primary actions can be clipped

The 380 px bubble and single-row layout at `ui.py:2013-2061` can simultaneously render Refine,
Continue, Edit, Was a command, Use this, and Ask. The computed row extends to roughly 468 px;
Ask is entirely outside the canvas.

**Fix:** wrap bounded rows or move secondary actions to overflow, always prioritize the primary
action, and derive height from layout. Exhaustively test all state/chip combinations and DPI.

### DESKTOP-08 — UI-thread latency has more than one source

The menu/modal loop at `ui.py:597-623` and synchronous draft planning can delay the pump; the
repository already documents a roughly 16-second menu/pump edge. DRAFT-04 demonstrates the
planning path reaching seconds on large text.

**Fix:** remove nested/modal polling where possible, bound each pump task, and use cancellable
workers plus revision guards for expensive computation. Add watchdog metrics and responsiveness
tests under open menus, long drafts, decode bursts, and reply playback.

### DESKTOP-09 — Clipboard restore creates unbounded short-lived threads

The delayed restore at `inject.py:255-270` starts a new sleeping thread for every send. With
native calls mocked, 300 rapid pastes created 300 restore threads in 52 ms until their 600 ms
delay expired.

**Fix:** use the single owned restore timer/worker DESKTOP-04 requires. A stress test should
keep thread count constant across thousands of rapid sends.

## Strengths and validation

Hotkey registration and the native message loop are separated cleanly; help content generation
does not introduce an execution sink. The clipboard/paste findings are logical native-boundary
failures and were not exercised against real mouse/focus/UIPI targets in this run. Existing
tests and the full unit suite passed, but some mocks currently encode success without realistic
SendInput counts and must be corrected.
