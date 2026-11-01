# Task 080 — Remediation plan for one finding (gate 1 only)

- Phase: 080 — remediate-and-retest
- Phase rule: `rules/rules_080-remediate-and-retest.md`
- Report: `<run_root>/reports/phase-080-hermes-vN.md`
- Payload: `<run_root>/reports/payload-080-<candidate_id>-vN.json` (provenance record)

The phase-060 candidate ID is provided in the trigger message (`--trigger-input`).
Phases 070 and 080 share this identity: `--trigger-input`, `--subject-id`, and the
payload `candidate_id` must all be equal.
This task implements **gate 1 only** of the five-gate remediation model.

## 1. Read first

1. `BOOTSTRAP.md`
2. `rules/rules_000-safety-and-scope.md`
3. `rules/rules_005-report-output.md`
4. `rules/rules_080-remediate-and-retest.md`

## 2. Target

Approved source path and commit from `run.json`.

## 3. Prior artifacts and inputs

Required:
- Selected phase-060 triage artifact; verify SHA-256.
- Selected phase-040 vuln-intel artifact (`selected_by_phase["040"]`); record its ID and `payload_sha256`.
- Selected phase-070 finding-record payload for the named candidate
  (`selected_by_subject["070"][candidate_id]`); record its ID and `payload_sha256`.

The phase-070 `assessment_disposition` must be `confirmed`, `suspected`, or
`needs-investigation`; the helper rejects any other disposition.

If any input is missing or stale, write the report with `blocked` and stop.
Commit change → report and stop.

## 4. Assess intelligence freshness

Load the phase-040 payload and evaluate freshness:

```python
# Pseudocode — Hermes reads the payload directly
intel_payload = load_json("<run_root>/reports/payload-040-all-vN.json")
freshness = assess_freshness(intel_payload, threshold_hours=24.0)
```

Record the freshness assessment in the `intel_freshness_at_plan_time` payload field.
If intel is stale, note it prominently in the report. **Do not silently omit it.**

## 5. Build provenance payload

Create `<run_root>/reports/plan-080-<candidate_id>.json`:

```json
{
  "schema_version": 1,
  "phase": "080",
  "candidate_id": "<candidate_id>",
  "finding_id": "<phase-070 proposed_finding.id, or null>",
  "source_commit": "<commit>",
  "intel_artifact_id": "<exact phase-040 artifact ID>",
  "intel_artifact_sha256": "<payload_sha256 of the phase-040 entry>",
  "assessed_finding_artifact_id": "<exact phase-070 artifact ID>",
  "assessed_finding_sha256": "<payload_sha256 of the phase-070 entry>",
  "intel_freshness_at_plan_time": {
    "freshness_ok": <true|false>,
    "evaluated_at_utc": "<now>",
    "effective_threshold_hours": 24.0,
    "threshold_source": "default",
    "stale_providers": [],
    "unknown_providers": [],
    "limitations": []
  },
  "gates_not_executed": ["gate-2-implement", "gate-3-retest", "gate-4-validate", "gate-5-close"]
}
```

These IDs and hashes are resolved NOW and stored immutably.
A later 040 re-collection does not update this record.

## 6. Perform gate 1 only

Perform only Rule 080 gate 1: propose the remediation and verification plan.

Do NOT:
- edit source files or apply patches
- run test commands or remediation commands
- update the finding record
- commit, push, or run CI

Mark gates 2–5 explicitly as NOT EXECUTED in the report.

## 7. Write

Write exactly one Markdown report to `<run_root>/reports/`.
Include the intel provenance section (artifact ID, freshness, limitations).

## 8. Register

```
hermes-vps-artifacts register \
  --run-json <run_json_path> \
  --phase 080 \
  --subject-id <candidate_id> \
  --source-report <absolute-path-to-report.md> \
  --payload-json <absolute-path-to-plan-080-<candidate_id>.json>
```

`--payload-json` is **required** for phase 080.
The artifact helper validates the payload against `templates/phase-080-plan.schema.json`
and requires the referenced IDs/hashes to be the current, complete 040 and 070 selections.

## 9. Stop

Stop and wait for human approval.
The presence of a remediation plan does not change the finding status to `fixed`.
A separate explicit request is required for each of gates 2–5.
