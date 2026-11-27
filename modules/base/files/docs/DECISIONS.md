# Decisions Log

Status: Active  
Scope: File locations, CLI options, defaults, and operational choices for this project.

## How to use this file

Create a new entry whenever the project changes or confirms:

- where a file is written or read
- a CLI option or its default
- a compatibility or rollout choice
- an output format that callers depend on

Guidelines:

- Append new entries; do not rewrite history
- If a decision changes, set the old entry to `Superseded` and link the new one
- Keep entries short, with the rationale and the consequences
- Say "the operator", not a personal name or handle

## Entry template

---

### DEC-XXXX: Short decision title

- Date: YYYY-MM-DD
- Status: Proposed | Accepted | Deferred | Superseded | Rejected
- Related work: doc, source, or PR links
- Supersedes: DEC-XXXX or none
- Superseded by: DEC-XXXX or none

#### Context

#### Decision

#### Consequences

---

### DEC-0001: Example — replace or delete

- Date: 2026-01-01
- Status: Accepted
- Related work: [roadmap.md](roadmap.md), [progress.md](progress.md)
- Supersedes: none
- Superseded by: none

#### Context

New projects need a place for durable choices that are not slice narrative.

#### Decision

Record those choices here as numbered `DEC-XXXX` entries. Link them from roadmap slices and progress notes when relevant.

#### Consequences

Roadmap and progress stay focused on work status. Callers can find why a default or path exists without reading the full progress log.
