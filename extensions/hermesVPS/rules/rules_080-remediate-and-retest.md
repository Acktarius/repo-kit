# Rule 080 — Remediate and retest: gate 1 (remediation plan) (hermesVPS)

## Activation

Applies when phase 080 is requested for **one finding per invocation**.
The finding ID is provided in the trigger message (`--trigger-input`).
Run only phase 080 gate 1 for that one finding, then stop.

## Scope: gate 1 only

Phase 080 defines five gates. hermesVPS implements **gate 1 only**:

| Gate | Description | hermesVPS status |
|------|-------------|-----------------|
| 1 | Propose remediation and verification plan | **Implemented** |
| 2 | Apply patch / fix | Requires separate authorization; NOT EXECUTED |
| 3 | Run tests and verification | Requires separate authorization; NOT EXECUTED |
| 4 | Evaluate results | Requires separate authorization; NOT EXECUTED |
| 5 | Propose finding record update | Requires separate authorization; NOT EXECUTED |

Do **not** apply patches, edit source files, run test commands, update the
findings store, commit, push, or run CI. All of those actions require
separate explicit authorization.

## Prerequisites

A registered, complete phase-060 triage artifact must be selected.
A registered, complete phase-070 finding-record payload for this specific
`finding_id` must be selected in `selected_by_subject["070"][finding_id]`.

If either prerequisite is missing or stale, write the report with completion
state `blocked` and stop. The finding must be `open` in the proposed record.

## Intelligence provenance (mandatory payload)

Phase 080 requires a structured `phase-080-plan.json` payload registered via
`--payload-json`. This payload records **immutable provenance** at plan creation time:

- `intel_artifact_id`: exact ID of the phase-040 vuln-intel artifact used
- `intel_artifact_sha256`: SHA-256 of that artifact at plan creation time
- `assessed_finding_artifact_id`: exact ID of the phase-070 artifact this plan addresses
- `assessed_finding_sha256`: SHA-256 of the phase-070 artifact
- `intel_freshness_at_plan_time`: freshness evaluation snapshot (evaluated_at_utc, effective_threshold_hours, freshness_ok, limitations)

**Resolve these at plan creation time; do not leave floating references.**
The selected `selected_by_phase["040"]` and `selected_by_subject["070"][finding_id]`
provide the IDs and hashes. Record them exactly.

If a new phase-040 collection has been performed since the phase-070 assessment,
`generate-findings` will detect the mismatch and report a provenance limitation.
A stale-intelligence warning must remain visible in the plan and handoff.

Validate the freshness of the current phase-040 intel artifact and record the
result in `intel_freshness_at_plan_time`.

## Gate 1 required output

The report must include:

1. **Finding identity** — exact finding_id and assessed source commit
2. **Intel provenance** — phase-040 artifact ID, collection mode, freshness status
3. **Root cause** — from phase-070 evidence; no new speculation
4. **Proposed changes** — specific code/config modifications with file paths
5. **Dependencies** — prerequisite changes, affected components, suggested order
6. **Verification commands** — exact proposed commands to confirm the fix
7. **Acceptance criteria** — measurable criteria for success
8. **Risks, rollback, unknowns** — implementation risks and rollback guidance
9. **Gates 2-5** — explicitly marked NOT EXECUTED; separate authorization required

## Subject-scoped selection

Phase 080 uses `selected_by_subject["080"][finding_id]`.
Cross-subject supersession is rejected: revising a plan requires the same
`finding_id` as the superseded artifact.

## Evidence contract

Base the remediation plan only on evidence from the phase-070 assessment.
Do not apply or simulate fixes. Do not claim the finding is resolved.
Preserve unknowns; do not invent solutions where evidence is absent.

## Completion

Write exactly one Markdown report.
Call `hermes-vps-artifacts register --subject-id <finding_id> --payload-json <path>`.
Stop and wait for human approval. The presence of a remediation plan does
not change the finding status from `open` to `fixed`.
