# Rule 030 — Scanner selection and execution plan (hermesVPS)

## Activation

Applies when phase 030 is requested.  Run only phase 030, then stop.

## Prerequisites

Registered, complete phase-010 inventory and phase-020 threat-model artifacts
must be selected in `manifest.json`.  Verify SHA-256 for both.  If either is
missing or stale, write the report with completion state `blocked` and stop.

Commit mismatch between prior artifacts and the current run → report and stop.

## Scope

Select appropriate security scanners based on inventory and threat model.
Produce a detailed execution plan.  Do **not** install, download, or run
scanners in this phase.  Every proposed command must be labeled as a
**proposal**.

- Scanner selection rationale (languages, frameworks, asset types)
- Exact proposed commands with flags
- Expected output types and paths
- Approval gates before execution
- Fallback approach if a scanner is unavailable

## Evidence contract

Base scanner selection on concrete evidence from phases 010 and 020.
Never invent scanner names, CVE databases, or expected findings.

## Report sections (required)

1. **Run identity**
2. **Prior artifacts** — selected IDs and SHA-256 status for phases 010 and 020
3. **Proposed scanners** — name, version/source, rationale per scanner
4. **Proposed commands** — labeled as proposals; exact argv
5. **Expected outputs and collection paths**
6. **Authorization gates** — what must be explicitly approved before execution
7. **Fallback notes** — coverage gaps if a scanner is unavailable
8. **Coverage limitations**
9. **Completion state** and next human gate

## Completion

Write exactly one report.  Call `hermes-vps-artifacts register`.
Stop and wait for human approval.  Do not start phase 040 or 050 automatically.
