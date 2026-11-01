# Task 060 — Validate and triage security candidates

- Phase: 060 — validate-and-triage
- Phase rule: `rules/rules_060-validate-and-triage.md`
- Report: `<run_root>/reports/phase-060-hermes-vN.md`
- Payload: `<run_root>/reports/payload-060-<subject>-vN.json` (triage inventory)

## 1. Read first

1. `BOOTSTRAP.md`
2. `rules/rules_000-safety-and-scope.md`
3. `rules/rules_005-report-output.md`
4. `rules/rules_060-validate-and-triage.md`
5. `templates/triage-payload.schema.json`

## 2. Target

Approved source path and commit from `run.json`.

## 3. Prior artifacts

Resolve at least one of: selected phase-040 or phase-050 artifacts.
Use **every** selected input the runner lists under SELECTED PREREQUISITES,
including every selected phase-050 review priority.
When both are selected, read both as inputs.
Verify SHA-256 for each present selected artifact.
Do not silently use one branch if the other is stale; report stale branches.

Also read existing reviewed findings and accepted risks from
`security-assets/` when present.

If no candidate report exists, write the report with `blocked` and stop.
Commit mismatch → report and stop.

## 4. Perform

Perform only Rule 060.  Read-only validation.
Do not execute exploits, tests, or target code.
Do not allocate SG-NNN IDs or modify findings or accepted risks.

Assign a stable candidate_id (e.g. `C-001`) to each validated candidate.
These IDs are stable across revisions; do not renumber.

## 5. Write

Write:
1. Exactly one Markdown report to `<run_root>/reports/`.
2. One JSON triage payload conforming to `templates/triage-payload.schema.json`.
   The payload defines the **in-scope candidate inventory** for `generate-findings`.
   Its `candidates[].candidate_id` values are the identities used by phases 070 and 080.

## 6. Register

Register both artifacts with a single `register` call:
```
hermes-vps-artifacts register \
  --run-json <run_json_path> \
  --phase 060 \
  --source-report <absolute-path-to-report.md> \
  --payload-json <absolute-path-to-triage-payload.json>
```

## 7. Stop

Stop and wait for human approval.  Do not start Task 070.
