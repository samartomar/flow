# Focus area 2 — Draft routing, editing, rescue, and history

## Scope and invariants

Reviewed `edits.py`, `phonetic.py`, `thread.py`, Draft/session routing, UI rescue actions,
and their tests. The main invariants are nondestructive ambiguity, exact targets that really
exist as words/phrases, revision-bound asynchronous actions, bounded history/context, and no
long computation on the UI pump.

## Findings

| ID | Severity | Finding |
|---|---|---|
| DRAFT-01 | High | Exact matching edits inside unrelated words. |
| DRAFT-02 | High | Stale “Was a command” state can duplicate newer content. |
| DRAFT-03 | High | Post-hoc rescue is not bound to the draft revision it diagnoses. |
| DRAFT-04 | Medium | Absent-target edit planning scales linearly and blocks the UI pump. |
| DRAFT-05 | Medium | One oversized thread turn bypasses the context character bound. |
| DRAFT-06 | High | Generic change diffs become quadratic on repetitive drafts. |

## Detailed evidence and remediation

### DRAFT-01 — “Exact” edit targets are substrings

`phonetic.py:299-302` and `phonetic.py:331-337` use unrestricted case-insensitive substring
search; `edits.py:793-804` and `edits.py:844-854` consume the resulting spans as confident
edits. Reproductions:

- `delete art` on `the cart is red` → `the c is red`
- `replace all art with x` on `cart art cart` → `cx x cx`
- `capitalize cat` can modify `concatenate`

**Fix:** exact matching must use complete token/phrase boundaries while allowing intended
whitespace/punctuation flexibility. Fuzzy matching should compare complete word windows only.
Add negative target-inside-word tests at span, planner, and application levels.

### DRAFT-02 — Rescue state survives newer draft activity

The last-append/rescue state around `session.py:1090-1124` and
`session.py:1314-1373` can remain eligible after the draft has evolved. The UI exposes that
state as “Was a command.”

**Impact:** a delayed rescue may append or reinterpret old speech against a newer draft,
duplicating text or applying the wrong command.

**Fix:** clear rescue eligibility on every unrelated capture, edit, send, clear, mode change,
or revision change. Store the originating utterance and pre/post draft revisions and require
all to match when clicked.

### DRAFT-03 — Post-hoc rescue lacks an atomic revision guard

`session.py:270-274`, `session.py:1356-1362`, and `session.py:1398-1429` do not give rescue
the same operation/revision protection used for some other asynchronous results.

**Fix:** compute a rescue proposal from immutable input, then compare operation ID, utterance
ID, and current draft revision immediately before commit. On mismatch, discard visibly and
non-destructively. Test edits and new captures while rescue is decoding.

### DRAFT-04 — Missing target search freezes interaction

The fallback scan at `phonetic.py:304-317` scores every candidate window when a target is
absent. It is reached synchronously through `session.py:975-997` on the UI pump.

*Corrected 2026-08-03, two ways.* The finding's summary said "quadratic-like" while its own
table is linear — 10× the text costs 10× the time at every step, which is what one pass over
the word windows costs. And this report measured **characters** where
[review-performance.md](review-performance.md) measured **words** for the same finding; a 2,000-
character draft of ordinary English is about 400 words, which is the whole distance between the
two tables. Re-measured here against `find_span`, absent `plan` target, characters:

| Draft size | Words | Time |
|---:|---:|---:|
| 1,000 chars | 205 | 10.5 ms |
| 2,000 chars | 409 | 20.6 ms |
| 5,000 chars | 1,023 | 51.0 ms |
| 10,000 chars | 2,046 | 98.6 ms |
| 20,000 chars | 4,091 | 198.2 ms |
| 200,000 chars | 40,909 | 2.0 s |

**Severity lowered to Medium**, because the multi-second rows need a draft four times larger
than the largest one this repo has ever measured. A dictated draft in the low thousands of
characters costs 10–100 ms — noticeable against a 30 ms pump, not a freeze. The largest draft
on record is the 50,000-character dictation behind the long-draft incident (LOOP_PLAN item 37),
which scans in roughly half a second; 200,000 characters is 4× beyond it. The two paths that
insert text the user did not dictate are both capped well below that — `MAX_CHARS` at 2,000 for
refine and `ASK_ARTIFACT_MAX_CHARS` at 12,000 for an artifact answer. It returns to High the day
a path exists that can put pasted or imported text of that size into a draft.

**Fix:** tokenize once, index normalized tokens/phrases, cap candidate work, and move any
remaining expensive plan computation off the UI thread with a revision guard. Add complexity
and UI-latency tests, not only correctness examples.

### DRAFT-05 — Thread tail can exceed its own cap

`thread.py:64-85` retains a single oversized recent turn whole because the `max_chars` check
is only enforced after another turn has been added. `session.py:1646-1652` then passes it to
Refine and `refine.py:625-630` adds framing without a final prompt cap.

**Impact:** excess prior-content disclosure, command-line length failure, latency, and memory
growth.

**Fix:** cap the first turn too, preserving an explicit truncation marker, and enforce a final
serialized prompt byte limit. Test a one-turn oversize thread and multi-byte text.

### DRAFT-06 — Repetitive-text diffs are quadratic

`edits.py:633-671` uses `SequenceMatcher(..., autojunk=False)` and the learning/description
path at `session.py:1114-1124` can compute related diffs repeatedly. Changing the last token
of a repeated-word draft measured 65 ms/500 words, 268 ms/1,000, 1.10 s/2,000, and 6.91 s/
5,000.

**Fix:** derive one bounded change record from the already known operation/span and reuse it
for learning and description. If a generic diff remains, trim common prefix/suffix and impose
a work budget. Add adversarial repeated-token latency tests.

## Strengths and validation

Draft and Thread history bounds are otherwise explicit; regex replacement inputs are escaped;
and several asynchronous Refine paths already use useful stale-operation/revision guards.
Targeted fault injection reproduced DRAFT-01, and the long-draft measurements established
DRAFT-04. The unit suite passed, showing these are coverage gaps rather than baseline failures.
