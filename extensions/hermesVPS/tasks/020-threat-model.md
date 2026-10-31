# Task 020 — Evidence-based threat model

- Phase: 020 — threat-model
- Phase rule: `rules/rules_020-threat-model.md`
- Report: `<run_root>/reports/phase-020-hermes-vN.md`

## 1. Read first

Read these files from the policy prefix (absolute paths printed by the runner):
1. `BOOTSTRAP.md`
2. `rules/rules_000-safety-and-scope.md`
3. `rules/rules_005-report-output.md`
4. `rules/rules_020-threat-model.md`

If any file is missing, report the missing path and stop.

## 2. Target

The approved target is the source path and commit recorded in `run.json`.
Do not infer the target from cwd.  Do not inspect paths outside the
approved source path.

## 3. Prior artifacts

Resolve the selected phase-010 artifact from `manifest.json` as shown
in the runner prompt.  Verify SHA-256 is OK.

If the phase-010 artifact is missing, stale, or its completion state is not
`complete`, write the report with completion state `blocked`, name the gap,
and stop.

If the source commit in the phase-010 artifact differs from the current run
commit, report the difference and stop.

## 4. Perform

Perform only Rule 020.  Read-only inspection only.
Do not execute project code, install anything, or use the network.
Do not update `security/threat-model.md` in the source repository.

## 5. Write

Write exactly one Markdown report to `<run_root>/reports/` following Rule 005.
Do not overwrite an existing versioned report.

## 6. Register

After writing the report, call:
```
hermes-vps-artifacts register \
  --run-json <run_json_path from runner prompt> \
  --phase 020 \
  --source-report <absolute-path-to-your-report>
```

If registration fails after the report is saved, follow the retry command
printed by the helper.

## 7. Stop

Stop and wait for human approval.  Do not start Task 030.
