# Task 050 — Evidence-based source and configuration review

- Phase: 050 — source-review
- Phase rule: `rules/rules_050-source-review.md`
- Report: `<run_root>/reports/phase-050-hermes-vN.md`

## 1. Read first

1. `BOOTSTRAP.md`
2. `rules/rules_000-safety-and-scope.md`
3. `rules/rules_005-report-output.md`
4. `rules/rules_050-source-review.md`

## 2. Target

Approved source path and commit from `run.json`.

## 3. Prior artifacts

Resolve selected phase-010 and phase-020 artifacts.  If scanner-assisted,
also resolve phase-030.  Verify SHA-256.  Missing, stale, or blocked →
write report with `blocked`, stop.

## 4. Perform

Perform only Rule 050, for **one review priority**: the `<priority_area>`
named in the trigger message (`--trigger-input`).  It must be one of the
prioritized review areas from the phase-020 report.

Read-only inspection by default.  Run a scanner only if the human approved
that exact action in the trigger message.
Do not execute target code or apply fixes.

## 5. Write

Write exactly one Markdown report to `<run_root>/reports/`.

## 6. Register

```
hermes-vps-artifacts register \
  --run-json <run_json_path> \
  --phase 050 \
  --subject-id <priority_area> \
  --source-report <absolute-path>
```

## 7. Stop

Stop and wait for human approval.  A separate invocation is required for
each additional review priority.  Phase 060 uses every selected priority.
