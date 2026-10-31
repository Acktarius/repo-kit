# Rule 020 — Evidence-based threat model (hermesVPS)

## Activation

Applies when phase 020 is requested.  Run only phase 020, then stop.

## Prerequisites

A registered, complete phase-010 inventory artifact must be selected in
`manifest.json`.  The runner prints the selected artifact ID and path;
verify the SHA-256 is OK before proceeding.  If no phase-010 artifact is
selected, write the report with completion state `blocked`, name the gap,
and stop.

If the source commit differs from the inventory's recorded `source_commit`,
report the mismatch and stop.

## Scope

Model threats against the system and data assets identified in phase 010.

- System overview and asset classification
- Entry points, trust boundaries, data flows
- Threat actors, abuse scenarios, attack chains
- Prioritized review areas for phases 040 and 050

Read-only analysis only.  Do not execute code, scanners, or network access.
Do not update `security/threat-model.md` in the source repository.
Do not expand scope without approval.

## Evidence contract

All claims must be supported by inventory evidence from the phase-010 report.
Never invent assets, data flows, threat actors, or impact descriptions.
Preserve uncertainties; use "unknown" where evidence is absent.

## Report sections (required)

1. **Run identity** — run ID, source identity, source commit, working-tree state
2. **Phase 010 input** — selected artifact ID and SHA-256
3. **System overview** — key assets and sensitivity classification
4. **Entry points and trust boundaries** — documented from inventory evidence
5. **Threat actors and abuse scenarios** — evidence-based; mark speculative items
6. **Data flows** — with trust boundary crossings
7. **Prioritized review areas** — ranked for phases 040 and 050
8. **Coverage limitations and open questions**
9. **Completion state** — `complete` | `incomplete` | `blocked`; next human gate

## Completion

Write exactly one report to the run-root reports directory following Rule 005.
Call `hermes-vps-artifacts register` after writing.  Then stop and wait for
human approval.  Do not start phase 030 automatically.
