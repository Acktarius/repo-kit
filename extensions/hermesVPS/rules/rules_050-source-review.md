# Rule 050 — Source and configuration review (hermesVPS)

## Activation

Applies when phase 050 is requested.  Run only phase 050 for **one review
priority** per invocation, then stop.

## Prerequisites

Registered, complete, current artifacts for phases 010 and 020 must be
selected; the runner refuses to start otherwise and lists them as the
execution-input snapshot (Rule 005).  If scanner-assisted, also consult the
selected phase-030 scan plan (procedural; it is not a resolved input).

The review priority (`<priority_area>`) is required in the trigger message
(`--trigger-input`) and must be one of the prioritized review areas from the
phase-020 report.  Register with `--subject-id <priority_area>`.  Each priority
is selected separately in `selected_by_subject["050"][priority_area]`; phase
060 uses every selected priority.

## Scope

Manual source and configuration review for one priority area.

- Code paths and configuration relevant to the priority
- Input handling, trust boundaries, authentication/authorization logic
- Use of secrets, credentials, cryptography
- Third-party integrations and exposed interfaces

Read-only inspection.  Run a scanner **only** if explicitly approved in the
trigger message.  Do not execute target code, apply fixes, or modify files.

One report per priority.  A separate invocation is required for each
additional priority.

## Weakness-class catalog and surface inventory

Read these files under the policy prefix.  Phase 050 requires both.  The
runner lists their absolute paths with the other policy inputs and refuses
to start when either is missing.  Do not substitute copies from the source
repository or from memory.

- `security-assets/weakness-classes.md`
- `security-assets/surface-inventory.md`

If either file is missing, unreadable, or lacks its required sections, name
the path, set completion state to `incomplete`, and stop.  Do not treat any
class as reviewed and do not fill either table from memory.

Inventory only this invocation's approved priority and the supporting
context phases 010 and 020 already selected.  Do not build a
whole-repository inventory.  Do not carry coverage from another priority,
invocation, or revision.  Prior artifacts are usable only when Rule 005
already selected them; name their IDs, hashes, and limits.

Build that bounded inventory before the vulnerability pass, then refine it
as reading reveals in-scope relationships.  Record unresolved gaps.  Do not
invent routes, registration, or flows.  An inventory does not mark any
weakness class `covered`.

Apply the catalog's coverage contract in **Coverage limitations**, including
"Coverage linkage and gaps".  Use only its statuses: `covered`,
`not_applicable`, `not_reviewed`.  Include every class.  Cite `S-*` and
`F-*` IDs where useful.  An uninspected applicable surface in this priority
keeps that class `not_reviewed`.  `covered` means the class was reviewed in
this source review, not that the code is secure.  The table is source-review
coverage.  Scanner output and phase 030 or 040 results do not mark a class
`covered`.

The catalog does not relax the evidence contract below or Rule 000.
Unresolved cases stay candidates only when that evidence contract is already
met; otherwise record an unresolved question.  Do not promote either to a
reviewed finding.

## Evidence contract

Support every candidate issue with a concrete file path, line number range,
and relevant code or configuration excerpt.  Never invent findings.
Distinguish confirmed evidence from uncertainty.  A supported candidate also
identifies a reachable entry point or trust boundary, the flow or security
decision, the sensitive operation, and the absent or ineffective control.

## Report sections (required)

Keep the identity header and the completion-state line unchanged.
`State:` in the body must still agree with that header.

1. **Run identity**
2. **Prior artifacts** — selected IDs and SHA-256 status
3. **Review priority** — this invocation's priority only
4. **Review scope and inspection limits** — diff-scoped, priority-scoped,
   or broader; inspected paths, exclusions, truncation, and inaccessible files
5. **Entry-point and sensitive-operation inventory**
6. **Persisted-input and second-order flows**
7. **Candidate issues** — file, line, excerpt, severity estimate, confidence,
   and attack path description; labeled as candidates
8. **Unexecuted checks** — scanner commands that were not run
9. **Coverage limitations** — weakness-class coverage table and coverage
   linkage and gaps.  An inventory does not mark any weakness class `covered`.
10. **Completion state** and next human gate

## Completion

Write exactly one report.  Call `hermes-vps-artifacts register`.
Stop and wait for human approval.  A separate invocation is required for
each additional review priority.
