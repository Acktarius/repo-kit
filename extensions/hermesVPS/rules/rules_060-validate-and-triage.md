# Rule 060 — Validate and triage (hermesVPS)

## Activation

Applies when phase 060 is requested.  Run only phase 060, then stop.

## Prerequisites

At least one registered, complete artifact for phase 040 **or** phase 050
must be selected.  When both are available, use both as inputs; do not
silently hide a stale or invalid branch because the other is valid.  Verify
SHA-256 for all selected inputs.  Missing or stale → `blocked`.

Also read existing reviewed findings and accepted risks in the run's
security-assets directory when present.

## Scope

Validate candidate issues from phases 040 and 050 and assign dispositions.
Produce a structured triage payload alongside the Markdown report.

Dispositions:
- `validated-new` — confirmed new issue not in findings store
- `existing-record` — matches a known finding; cite SG-NNN
- `duplicate` — duplicate of another candidate
- `covered-by-accepted-risk` — within an accepted-risk boundary
- `rejected` — insufficient evidence; not a real issue
- `pending-evidence` — requires further investigation
- `blocked` — cannot assess without missing information

Do **not** allocate stable SG-NNN IDs.  Do **not** execute exploits or
modify findings or accepted risks.  Candidates are not canonical findings.

## Structured triage payload (required)

Write a JSON payload file conforming to `templates/triage-payload.schema.json`.
This file defines the **in-scope candidate inventory** for `generate-findings`.
Each candidate must have a stable `candidate_id` (e.g. `C-001`).

Register both the Markdown report and the JSON payload:
```
hermes-vps-artifacts register \
  --run-json <path> --phase 060 \
  --source-report <report.md> \
  --payload-json <triage-payload.json>
```

## Evidence contract

Never invent findings, CVEs, severity scores, or advisory identifiers.
Preserve candidates assessed as pending-evidence or blocked rather than
inventing confirmation.

## Phase-050 unresolved questions

Record phase-050 unresolved-question entries in **Coverage limitations**. Do not add them to the candidate triage table or the triage payload `candidates` array.

A phase-050 unresolved question stays an unresolved question. It is not automatically a candidate issue.

A conditional control proposal is not evidence that a control is absent, ineffective, or exploitable. It does not authorize an edit.

Do not assign a candidate ID, a severity, a triage disposition, an SG-* id, or a finding lifecycle status to an unresolved-question entry merely to fit the triage format.

Cross-reference the originating report and its `S-*` or `F-*` row when one exists. Do not create another identifier.

A question may lead to a new supported candidate only when additional permitted static evidence independently meets the existing candidate evidence threshold. Name that evidence and the uncertainty it resolves. Establish the entry point or trust boundary, the flow or security decision, the sensitive operation, and the absent or ineffective control. Stay inside the approved scope and this phase's permissions. Do not execute target code or probe to obtain the evidence.

Evidence that a control exists, or that the concern does not apply, also resolves the question. Do not force every question toward a vulnerability.

If the needed evidence is outside the approved scope, record the limitation or the required scope decision in **Coverage limitations**. Do not expand scope automatically.

Do not mark an affected weakness class covered because the question was discussed. Keep the phase-050 coverage limitation unless a permitted, explicitly scoped reassessment supplies the missing review evidence.

A supported candidate may still name bounded uncertainty. That uncertainty does not turn the candidate into an unresolved question. An unresolved question has not met the evidence threshold. A supported candidate with bounded uncertainty may still use `pending-evidence`.

Synthetic examples, not findings and not evidence about any repository:

- Supported candidate. The phase-050 candidate already shows the handler, the caller-controlled id, the load, and the missing owner check in the inspected file. One deployment assumption remains. Keep it in the candidate list and state that limit.
- Standalone question. Phase 050 recorded that the authorization policy was outside the inspected paths, with a conditional control proposal. Leave it under **Coverage limitations** with its `S-*` reference. Do not assign a candidate ID unless later permitted static evidence independently meets the threshold.

## Report sections (required)

1. **Run identity**
2. **Prior artifacts** — selected input artifact IDs and SHA-256 status
3. **Candidate triage table** — candidate_id, title, disposition, severity estimate, rationale
4. **Detailed assessment** — per candidate with evidence
5. **Coverage limitations** — phase-050 coverage limits, and phase-050 unresolved-question entries kept out of the candidate list
6. **Completion state** and next human gate

## Completion

Write exactly one Markdown report and one JSON triage payload.
Register both artifacts (Markdown + payload) with a single `register` call.
Stop and wait for human approval.  Do not start phase 070 automatically.
