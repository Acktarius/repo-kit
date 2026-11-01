# Rule 080 — Remediate and retest: gate 1 (remediation plan) (hermesVPS)

## Activation

Applies when phase 080 is requested for **one candidate per invocation**.
The phase-060 `candidate_id` is provided in the trigger message (`--trigger-input`).
Run only phase 080 gate 1 for that one candidate, then stop.

Identity: phases 070 and 080 are keyed by `candidate_id`.  `--trigger-input`,
`--subject-id`, and the plan payload's `candidate_id` must all be equal.
`finding_id` (e.g. `SG-001`) is optional canonical metadata; when present in the
plan it must equal the phase-070 `proposed_finding.id`.

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

The runner resolves and lists them; all must be complete, intact, and current:

- the selected phase-060 triage artifact, whose inventory contains the candidate;
- the selected phase-070 assessment `selected_by_subject["070"][candidate_id]`,
  with disposition `confirmed`, `suspected`, or `needs-investigation`;
- the selected phase-040 vuln-intel artifact `selected_by_phase["040"]`.

If any prerequisite is missing or stale the runner refuses to start; if one
becomes stale during the phase, registration is rejected (see Rule 005,
execution-input snapshot).  Write the report with completion state `blocked`
only for blockers the runner cannot detect.

## Intelligence provenance (mandatory payload)

Phase 080 requires a structured plan payload (`templates/phase-080-plan.schema.json`)
registered via `--payload-json`. It records **immutable provenance** at plan creation time:

- `candidate_id`: the phase-060 candidate this plan addresses
- `finding_id` (optional): the phase-070 `proposed_finding.id`
- `intel_artifact_id` / `intel_artifact_sha256`: the selected phase-040 artifact ID
  and its manifest `payload_sha256` (not the report `sha256`)
- `assessed_finding_artifact_id` / `assessed_finding_sha256`: the selected phase-070
  artifact ID and its manifest `payload_sha256`
- `intel_freshness_at_plan_time`: freshness evaluation snapshot
  (`evaluated_at_utc`, `effective_threshold_hours`, `threshold_source`, `freshness_ok`, limitations)

**Resolve these at plan creation time; do not leave floating references.**
The helper rejects a plan whose IDs or `payload_sha256` values are not the
current selections.

If phase 040 or the candidate's phase 070 is revised after the plan is
registered, the plan becomes stale: `generate-findings` excludes it and lists it
in `readiness.provenance_080.stale_plans`.  A stale-intelligence warning must
remain visible in the plan and handoff.

## Gate 1 required output

The report must include:

1. **Candidate identity** — exact `candidate_id`, optional `finding_id`, assessed source commit
2. **Intel provenance** — phase-040 artifact ID, collection mode, freshness status
3. **Root cause** — from phase-070 evidence; no new speculation
4. **Proposed changes** — specific code/config modifications with file paths
5. **Dependencies** — prerequisite changes, affected components, suggested order
6. **Verification commands** — exact proposed commands to confirm the fix
7. **Acceptance criteria** — measurable criteria for success
8. **Risks, rollback, unknowns** — implementation risks and rollback guidance
9. **Gates 2-5** — explicitly marked NOT EXECUTED; separate authorization required

These sections are procedural requirements; only the identity header (Rule 005)
and the plan payload are machine-validated.

## Subject-scoped selection

Phase 080 uses `selected_by_subject["080"][candidate_id]`.
Cross-subject supersession is rejected: revising a plan requires the same
`candidate_id` as the superseded artifact.

## Evidence contract

Base the remediation plan only on evidence from the phase-070 assessment.
Do not apply or simulate fixes. Do not claim the finding is resolved.
Preserve unknowns; do not invent solutions where evidence is absent.

## Completion

Write exactly one Markdown report starting with the runner's identity header.
Call `hermes-vps-artifacts register --phase 080 --subject-id <candidate_id> --payload-json <path>`.
Stop and wait for human approval. The presence of a remediation plan does
not change the finding status from `open` to `fixed`.
