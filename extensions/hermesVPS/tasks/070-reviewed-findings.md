# Task 070 — Propose a reviewed finding record (one candidate per invocation)

- Phase: 070 — reviewed-findings
- Phase rule: `rules/rules_070-reviewed-findings.md`
- Report: `<run_root>/reports/phase-070-hermes-vN.md`
- Payload: `<run_root>/reports/payload-070-<candidate_id>-vN.json`

The candidate ID is provided in the trigger message (`--trigger-input`).

## 1. Read first

1. `BOOTSTRAP.md`
2. `rules/rules_000-safety-and-scope.md`
3. `rules/rules_005-report-output.md`
4. `rules/rules_070-reviewed-findings.md`
5. `templates/finding-record.schema.json`
6. `security-assets/findings.schema.json`

## 2. Target

Approved source path and commit from `run.json`.

## 3. Prior artifacts and inputs

Required:
- Selected phase-060 triage artifact (from `selected_by_phase["060"]`); verify SHA-256.
- One candidate ID named in the trigger message.

The named candidate must be in the phase-060 triage payload with a
`validated-new` or `pending-evidence` disposition.

Also read existing findings store and accepted risks when present.

If any required input is missing or the candidate is not actionable,
write the report with `blocked`, name the gap, and stop.

## 4. Perform

Perform only Rule 070 for the one named candidate.
Put the proposed record in the report and payload only.
Do not write the findings store, allocate a stable SG-NNN ID, or accept risks.
Do not process other candidates.

Set `assessment_disposition` (confirmed/suspected/dismissed/needs-investigation).
Keep it distinct from canonical `status`.
Never set `status = "fixed"` because remediation is planned.

## 5. Write

Write:
1. Exactly one Markdown report to `<run_root>/reports/`.
2. One JSON finding-record payload conforming to `templates/finding-record.schema.json`.
   The `candidate_id` in the payload must match the trigger `--trigger-input`.

## 6. Register

```
hermes-vps-artifacts register \
  --run-json <run_json_path> \
  --phase 070 \
  --subject-id <candidate_id> \
  --source-report <absolute-path-to-report.md> \
  --payload-json <absolute-path-to-finding-record.json>
```

Each candidate requires its own registration with its own `--subject-id`.
Revising one candidate's assessment does not affect others.

## 7. Stop

Stop and wait for human approval.  A separate invocation is required for
each additional candidate.  Saving the proposed record to the findings store
is a separate authorized action.
