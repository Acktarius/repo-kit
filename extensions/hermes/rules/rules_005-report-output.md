# Rule 005 — Review report output and artefact boundary

## Purpose
Define the only permitted write location for Hermes review reports and
evidence artefacts.

## Prerequisites
- Apply rules_000-safety-and-scope.md throughout.

## Policy and output paths
- Read policy only from:
  `.repo-kit/hermes/review-rules/`
- Write generated review artefacts only to:
  `.repo-kit/hermes/reports/`
- Treat the review-rules directory as read-only policy input.
- Never write outside `.repo-kit/hermes/reports/` during read-only
  review phases.
- Do not modify application source, configuration, dependencies,
  lockfiles, tests, documentation, git metadata, CI configuration, or
  existing finding records unless the human explicitly approves a
  separate remediation action.

## Reports directory
Before beginning a phase, ensure `.repo-kit/hermes/reports/` exists.
If it does not exist and the environment permits creation there, create
it; otherwise report the missing output path and stop.

## Phase report naming
Produce exactly one primary Markdown report per completed phase:

```text
.repo-kit/hermes/reports/phase-NNN-<phase-name>.md
```

Examples:
- `phase-010-inventory.md`
- `phase-020-threat-model.md`
- `phase-030-scan-plan.md`

Never overwrite an existing phase report. If the intended filename
already exists, create a new filename with a UTC timestamp:

```text
phase-NNN-<phase-name>-YYYYMMDD-HHMMSSZ.md
```

## Required report contents
Each report must state:
1. phase number and name
2. UTC creation time
3. approved target and scope
4. rules consulted
5. actions actually performed
6. evidence and file paths examined
7. limitations, failures, and coverage gaps
8. completion state
9. next human approval required

## Boundary
Reports are review artefacts, not approval to change source code.
Stop after writing the requested phase report. Do not advance
automatically.
