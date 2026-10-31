# Task 010 — Read-only repository inventory (hermesVPS)

- Phase: 010 — inventory
- Phase rule: `rules/rules_010-inventory.md`
- Report: `<run_root>/reports/phase-010-hermes-vN.md`

## 1. Read first

Resolve these under the registered **policy prefix** (absolute paths preferred):

1. `BOOTSTRAP.md` (already read for entry; re-check only if needed)
2. `rules/rules_000-safety-and-scope.md`
3. `rules/rules_005-report-output.md`
4. `rules/rules_010-inventory.md`
5. `templates/phase-010-report.md` (structure aid)

If any required file is missing or unreadable, report the missing path and
**stop**. Do not guess.

## 2. Target

The approved target is **only** `source.path` from the operator `run.json`
for this run. Confirm `source.commit` still matches `git rev-parse HEAD` and
that the worktree is clean **immediately before writing** the report
(preflight checks can race with later filesystem changes).

Do not inspect paths outside the approved source tree.
Do not follow symlinks that escape the approved source root.

## 3. Prior reports

None required for phase 010. `prerequisites.artifacts` must be empty.
Do not load or invent prior phase reports.

## 4. Perform

Perform only Rule 010. Read-only inspection only.
Do not execute project code, install anything, use the network, run scanners,
builds, or tests.
Do not modify `run.json` or `manifest.json`.
Do not create findings or update security stores.

## 5. Write

Write exactly one new report to the **selected** path from the validated
prompt / `run.json` (for example `reports/phase-010-hermes-v1.md` under the
run root). Never overwrite.

Include Rule 005 required contents and Rule 010 response sections.
Prefer the section layout in `templates/phase-010-report.md`.

On success, completion state is `complete` or `incomplete` (if scoped gaps
remain but work stopped cleanly). On validation/prerequisite failure,
`blocked`.

## 6. After writing (describe only)

Tell the operator the exact artifact id and path to record in
`manifest.json`. Do **not** update the manifest yourself.
Do **not** create a separate manifest-update file.

Remind the operator of the gate:

- optional Roomote handoff;
- human acceptance of exact artifact versions;
- separate explicit request required before phase 020.

## 7. Stop

Stop and wait. Do not start Task 020 or any other phase.
