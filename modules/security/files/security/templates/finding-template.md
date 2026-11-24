# SG-XXX — Short finding title

## Metadata

- **Status:** `open`
- **Severity:** `low` | `medium` | `high` | `critical`
- **Confidence:** `low` | `medium` | `high`
- **Source:** manual review, tool, or review command
- **First seen:** `YYYY-MM-DDTHH:MM:SSZ`

## Technical description

- **Affected files:** paths and relevant functions
- **Root cause:** concrete cause supported by evidence
- **Preconditions:** conditions required for exploitation
- **Exploit path:** high-level path from attacker-controlled input to impact
- **Impact:** practical effect if exploited

## Remediation

- **Recommended fix:** smallest change addressing the root cause
- **Verification:** focused tests or review evidence
- **Possible side effects:** behavior or compatibility risks

## Relationships

- **Duplicate of:** `SG-XXX` or none
- **Accepted risk:** `AR-XXX` or none

## Review notes

Record relevant status changes and supporting evidence.

## Optional classification

Omit this section when the mapping is uncertain or the evidence is incomplete.
Do not invent a class. Do not use an empty list or a placeholder to fill it.
`S-*` and `F-*` ids stay in the review narrative; they are not store fields.

- **Weakness classes:** one or more catalog `WC-*` ids, only when the evidence supports each one
- **Entry point:** evidence-backed trust boundary
- **Flow:** data flow, control flow, or security decision
- **Sensitive operation:** the sensitive use
- **Control gap:** the absent or ineffective control
- **Evidence:** portable repository-relative path (`/`, no `.` or `..` components), optional symbol, optional line range, and what that reference establishes. The path is not opened during validation.

A line range needs both ends, with the end on or after the start.
