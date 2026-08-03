# Focus area 6 — Calibration, profile, lexicon, and diagnostics

## Scope and data contract

Reviewed `calibrate.py`, `profile.py`, `lexicon.py`, `diag.py`, persistence call sites and
tests. Local personalization data must be safely parsed, bounded, atomic, private by default,
and able to degrade to defaults after corruption.

## Findings

| ID | Severity | Finding |
|---|---|---|
| PERSONAL-01 | High | Valid JSON with wrong types can crash startup or corrupt behavior. |
| PERSONAL-02 | High | Profile persistence failures are routinely ignored. |
| PERSONAL-03 | Low | Local profile/lexicon permissions are not explicitly hardened. |
| PERSONAL-04 | Low | Calibration preview text is printed into terminal history. |
| PERSONAL-05 | Medium | Whole-file configuration and diagnostic I/O blocks UI/startup paths. |

## Detailed evidence and remediation

### PERSONAL-01 — Schema number is checked, field schema is not

`profile.py:165-195` parses JSON and assigns fields without validating their types/ranges.
Consumers at `profile.py:84-99` assume strings, mappings, lists, booleans, and finite numbers.
Targeted schema-1 inputs reproduced:

- numeric `send_word` → `AttributeError` on `.strip()`;
- scalar `workspaces` or `dismissed` data → `TypeError`;
- string calibration values → arithmetic `TypeError`;
- string `"false"` may be coerced truthy, silently reversing preference.

**Fix:** validate every field into temporary typed values with size/range/enum/finite checks;
retain defaults for invalid independent fields; only then construct/replace the Profile. Bound
collection sizes and string lengths. Add table-driven wrong-type tests for every persisted field.

### PERSONAL-02 — Failed saves look successful

The atomic writer at `profile.py:198-228` returns failure, but calibration at
`calibrate.py:211-216` and several session/UI/main callers do not consistently surface or
recover from it.

**Impact:** a user completes calibration, changes a workspace, or teaches a preference, sees
the new behavior in memory, and loses it at restart without warning.

**Fix:** centralize mutations in a transactional ProfileStore. Report failure visibly, keep a
dirty/retry state, preserve the last known-good file, and test permission denial, disk full,
replace failure, concurrent write, and shutdown with dirty state.

### PERSONAL-03 — Explicit least-privilege file creation

Atomic writes are a strong baseline, but cross-platform Lite paths should deliberately create
profile and lexicon files/directories with user-only permissions rather than relying entirely
on process defaults.

**Fix:** apply platform-appropriate user-private ACL/mode on creation and document backup/export
behavior. Do not silently tighten an existing shared file without migration notice.

### PERSONAL-04 — Calibration transcript in terminal logs

`calibrate.py:202-203` prints a transcription preview. On recorded/shared terminals this can
persist spoken content beyond the GUI interaction.

**Fix:** default to a bounded/redacted success indication or request explicit preview consent;
document that terminal output may be retained.

### PERSONAL-05 — User-controlled files have no byte or latency budget

Lexicon reads at `lexicon.py:129-170` and `lexicon.py:354-370`, menu rereads at
`ui.py:934-967`, profile I/O at `profile.py:165-228`, and diagnostic writes at
`diag.py:138-176` materialize or write synchronously. Logical entry caps do not cap the file
bytes first. Large hand-edited files, roaming folders, antivirus, or a slow disk can block
startup, menu opening, routing, or Send.

**Fix:** check byte bounds before parsing, stream only the allowed lexicon entries, cache by
file stamp, and use one bounded persistence/diagnostic writer. Test oversized files and delayed
filesystem calls.

## Strengths and validation

Lexicon parsing, escaping, bounds, and atomic replacement were sound in the reviewed paths.
Diagnostics use bounded allowlisted fields and do not log raw dictated words, a valuable privacy
property. No unsafe deserialization was found. Profile fault injection established
PERSONAL-01; the general unit suite passed.
