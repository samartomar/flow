# flow agent instructions

## Branch rules

Before pushing or choosing a merge method, check the target branch's current GitHub rulesets and branch protection settings. If you cannot verify them, pause and tell Samar before proceeding.

Use a pull request for every change to `main` and choose a merge method that satisfies its history rules. Before any action that would bypass a rule, name the rule and the proposed action, explain why the bypass is needed, and wait for Samar's explicit approval for that specific bypass. This applies even when Samar has already asked you to commit, push, or merge.

## Agent skills

Use the installed Matt Pocock engineering skills and aih-extensions within this repository's existing rules. Keep the skills in their managed user installation.

### Issue tracker

GitHub Issues on `samartomar/flow`. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the five default triage roles. See `docs/agents/triage-labels.md`.

### Domain docs

One product vocabulary with the existing decision authority. See `docs/agents/domain.md`.
