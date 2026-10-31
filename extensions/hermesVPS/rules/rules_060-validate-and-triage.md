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

## Report sections (required)

1. **Run identity**
2. **Prior artifacts** — selected input artifact IDs and SHA-256 status
3. **Candidate triage table** — candidate_id, title, disposition, severity estimate, rationale
4. **Detailed assessment** — per candidate with evidence
5. **Coverage limitations**
6. **Completion state** and next human gate

## Completion

Write exactly one Markdown report and one JSON triage payload.
Register both artifacts (Markdown + payload) with a single `register` call.
Stop and wait for human approval.  Do not start phase 070 automatically.
