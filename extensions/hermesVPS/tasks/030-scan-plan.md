# Task 030 — Scanner selection and execution plan

- Phase: 030 — scan-plan
- Phase rule: `rules/rules_030-scan-plan.md`
- Report: `<run_root>/reports/phase-030-hermes-vN.md`

## 1. Read first

1. `BOOTSTRAP.md`
2. `rules/rules_000-safety-and-scope.md`
3. `rules/rules_005-report-output.md`
4. `rules/rules_030-scan-plan.md`

## 2. Target

Approved source path and commit from `run.json`.

## 3. Prior artifacts

Resolve selected phase-010 and phase-020 artifacts from `manifest.json`.
Verify SHA-256 for both.  Missing, stale, or `blocked` completion state →
write report with `blocked`, name the gap, and stop.

Commit mismatch → report and stop.

## 4. Perform

Perform only Rule 030.  This task produces a plan, not a scan.
Do not install, download, authenticate, or run scanners.
Label every command as a proposal.

## 5. Write

Write exactly one Markdown report to `<run_root>/reports/`.

## 6. Register

```
hermes-vps-artifacts register \
  --run-json <run_json_path> \
  --phase 030 \
  --source-report <absolute-path>
```

## 7. Stop

Stop and wait for human approval.  Do not start Task 040 or 050.
