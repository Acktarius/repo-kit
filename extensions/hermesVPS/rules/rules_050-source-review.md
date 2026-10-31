# Rule 050 — Source and configuration review (hermesVPS)

## Activation

Applies when phase 050 is requested.  Run only phase 050 for **one review
priority** per invocation, then stop.

## Prerequisites

Registered, complete artifacts for phases 010 and 020 must be selected.
If scanner-assisted, a complete phase-030 artifact must also be selected.
Verify SHA-256 for all required inputs.  Missing or stale input → `blocked`.

The review priority is named in the trigger message.  If none is named, use
the first prioritized review area from the phase-020 threat-model report.

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

## Evidence contract

Support every candidate issue with a concrete file path, line number range,
and relevant code or configuration excerpt.  Never invent findings.
Distinguish confirmed evidence from uncertainty.

## Report sections (required)

1. **Run identity**
2. **Prior artifacts** — selected IDs and SHA-256 status
3. **Review priority** — scope and boundaries for this invocation
4. **Findings** — candidate issues with file, line, excerpt, severity estimate,
   confidence, and attack path description; labeled as candidates
5. **Unexecuted checks** — scanner commands that were not run
6. **Coverage limitations** — what was not inspected
7. **Completion state** and next human gate

## Completion

Write exactly one report.  Call `hermes-vps-artifacts register`.
Stop and wait for human approval.  A separate invocation is required for
each additional review priority.
