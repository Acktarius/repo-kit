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
for this run. That path must be the actual non-bare Git worktree root
(`git rev-parse --is-inside-work-tree` → `true`, and
`git rev-parse --show-toplevel` equals `source.path` after resolution).
Linked worktrees (`.git` file) are allowed; bare repositories and nested
paths that are not the worktree root are not.

Confirm **immediately before writing** the report:

- `source.commit` still matches `git rev-parse HEAD`;
- the worktree is clean;
- `reports/` and the selected output path still remain inside the approved
  run-root reports directory (not source/policy);
- the selected output still does not exist (including dangling symlinks).

Preflight checks can race with later filesystem changes.

Do not inspect paths outside the approved source tree.
Do not follow symlinks that escape the approved source root.
Do not checkout, reset, clean, or otherwise modify the source.

## 3. Prior reports

None required for phase 010. `prerequisites.artifacts` must be empty.
Do not load or invent prior phase reports.

## 4. Perform

Perform only Rule 010. Read-only inspection only.
Do not execute project code, install anything, use the network, run scanners,
builds, or tests.
Do not modify `run.json` or hand-edit `manifest.json`.
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

## 6. Register the artifact

After the report file is written, call the artifact helper to register it:

```text
<policy_prefix>/bin/hermes-vps-artifacts register \
  --run-json <run_json_path> \
  --phase 010 \
  --source-report <absolute-path-to-your-report-file>
```

The helper will:
- auto-select the next unused version (e.g. `phase-010-hermes-v1`);
- copy the report to its final versioned path under `reports/`;
- compute SHA-256 and update the artifact index (`manifest.json`);
- print the consultation prompt.

If registration fails after the report is saved (saved-but-unregistered),
follow the exact retry command printed by the helper. Do not re-run the
inventory phase or overwrite the report.

Structural and hash checks do not prove factual correctness of the report.

## 7. Stop

After the consultation prompt is printed, stop.
Do not start Task 020 or any other phase without a separate explicit human
request. Normal progression does not require a separate acceptance file.
