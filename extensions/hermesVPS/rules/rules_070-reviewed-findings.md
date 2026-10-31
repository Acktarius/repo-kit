# Rule 070 — Reviewed findings (hermesVPS)

## Activation

Applies when phase 070 is requested for **one candidate per invocation**.
The candidate ID is provided in the trigger message (`--trigger-input`).
Run only phase 070 for that one candidate, then stop.

## Prerequisites

A registered, complete phase-060 triage-payload artifact must be selected.
Verify SHA-256.  The named candidate must exist in the triage payload with
a `validated-new` or `pending-evidence` disposition.

If the prerequisite is missing, stale, or the candidate is not in the
triage payload with an actionable disposition, write the report with
completion state `blocked`, name the gap, and stop.

## Scope

Propose a human-reviewed finding record for the named candidate.

- Review the candidate evidence from phases 040/050/060
- Assess the finding (confirmed / suspected / dismissed / needs-investigation)
- Propose a canonical-schema-compatible finding record
- Preserve uncertainties; never invent confirmation

One candidate per invocation.  Phase 070 does **not** write to the target
repository's `security/findings-reviewed.json`.  It does **not** allocate
stable SG-NNN IDs.  Both the operator and the canonical findings store are
the authoritative recipients for committed records.

**assessment_disposition** is distinct from the canonical **status** field.
Do not use canonical status values (`open`, `fixed`, etc.) to encode the
assessment outcome.  Use `assessment_disposition` for that purpose.

## Structured finding payload (required)

Write a JSON payload file conforming to `templates/finding-record.schema.json`.
The `candidate_id` in the payload must match the trigger `--trigger-input`.
The `assessment_disposition` must be set.
For `dismissed` candidates, set `assessment_rationale`.
Never set `status = "fixed"` merely because remediation is planned.

Register both the Markdown report and the JSON payload:
```
hermes-vps-artifacts register \
  --run-json <path> --phase 070 \
  --subject-id <candidate_id> \
  --source-report <report.md> \
  --payload-json <finding-record.json>
```

## Subject-scoped selection

Because phase 070 runs once per candidate, the manifest uses subject-scoped
selection (`selected_by_subject["070"][candidate_id]`).  Revising one
candidate's assessment does not affect other candidates' selections.

Cross-subject supersession is rejected: `revise --supersedes X` requires
that artifact X was registered for the same `candidate_id`.

## Evidence contract

Support every proposed finding with concrete evidence (file, line, excerpt).
Never invent exploit paths, impact, or remediation.
Preserve unknowns and blockers explicitly.

## Report sections (required)

1. **Run identity**
2. **Candidate** — candidate_id, source artifact, disposition summary
3. **Assessment** — disposition and detailed rationale with evidence
4. **Proposed finding record** — all canonical schema fields that can be populated
5. **Affected components** — beyond the file list
6. **Impact and likelihood**
7. **Unknowns and blockers** — explicit list; preserved, not resolved by invention
8. **Completion state** and next human gate

## Completion

Write exactly one Markdown report and one JSON finding-record payload.
Register both (Markdown + payload) with `--subject-id <candidate_id>`.
Stop and wait for human approval.  The approved record must be saved to the
findings store by the operator as a separate explicit action.
