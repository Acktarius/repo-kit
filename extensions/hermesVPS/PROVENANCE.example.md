# Provenance example — packaged hermesVPS security assets

This file is a **template** for the provenance record that install/packaging
(Stage 5) will write into the runtime prefix (suggested name: `PROVENANCE.md`).

It is not itself a packaged payload. Do not treat example SHA values as real.

The existing security module under `modules/security/` is never modified by
hermesVPS. Canonical files are copied or methodology is adapted into hermesVPS
instructions.

## Assembly metadata

- **Toolkit repository:** `Acktarius/repo-kit` (confirm at package time)
- **Toolkit revision (full SHA):** `REPLACE_AT_PACKAGE_TIME`
- **Working tree dirty at package/install:** `true` | `false`
- **Assembly UTC time:**
- **Assembler:** `scripts/install-hermes-vps.sh` | packaging helper (later)
- **Policy prefix:** `/opt/data/hermes-review` (example)

## Distinction

| Kind | Meaning |
|------|---------|
| **unchanged** | Byte-for-byte copy of a canonical repo-kit path into the runtime prefix |
| **adapted** | Methodology rewritten as agent-neutral VPS rules/tasks; Cursor slash commands are not runnable Hermes commands |

## Planned unchanged copies (Stage 5+)

| Source path in repo-kit | Runtime destination (under prefix) | Purpose |
|-------------------------|------------------------------------|---------|
| `modules/security/files/security/findings.schema.json` | `security-assets/findings.schema.json` | Findings store schema; preserve fields/enums |
| `modules/security/files/security/templates/finding-template.md` | `security-assets/templates/finding-template.md` | Human-readable finding form |
| `modules/security/files/security/findings-reviewed.json` | `security-assets/findings-reviewed.empty.json` | Empty store **shape** only (not a live target store) |
| `modules/security/files/security/accepted-risks.md` | `security-assets/accepted-risks.md` | `AR-XXX` template and conventions |
| `modules/security/files/security/threat-model.md` | `security-assets/threat-model.md` | Durable threat-model template |
| `modules/security/files/security/README.md` | `security-assets/README.md` | Status enums and workflow overview |

Required dependency for interpreting findings: `findings.schema.json` (draft
2020-12). No schema validator is assumed installed on the VPS.

## Planned adaptations (Stage 3–4; not copies of Cursor commands)

| Source path in repo-kit | Runtime destination | Adaptation purpose |
|-------------------------|---------------------|--------------------|
| `modules/security/files/.cursor/commands/00-security-plan-hardening.md` | Distilled into phase 010/020 rules/tasks | Remove Plan Mode / `.cursor/plans/` write; planning stays in phase reports |
| `modules/security/files/.cursor/rules/20-security-planner.mdc` | Same | Agent-neutral planning checks |
| `modules/security/files/.cursor/commands/01-security-review-priority-1.md` | Distilled into 030/040/050 guidance | Evidence-only priority review |
| `modules/security/files/.cursor/rules/30-security-reviewer.mdc` | Same | Evidence and “no valid findings” discipline |
| `modules/security/files/.cursor/commands/05-security-triage-findings.md` | Distilled into phase 060 | Exact artifact inputs; schema statuses |
| `modules/security/files/.cursor/rules/40-security-triage.mdc` | Same | Stable IDs; human approval for store updates |
| `modules/security/files/.cursor/commands/02-security-generate-finding.md` | Distilled into phase 070 | Propose only; no store write |
| `modules/security/files/.cursor/commands/03-generate-accepted-risk.md` | Later gated task/template | Propose `AR-XXX`; human decides |
| `modules/security/files/.cursor/commands/04-security-fix-finding.md` | Phase 080 **plan** boundary only | Strip apply-patch authority from Hermes default |
| `modules/security/files/.cursor/commands/security-record-finding.md` | Operator note / Roomote guidance | Host-side record path; not Hermes sandbox write |
| `extensions/hermes/rules/*`, `tasks/*` | `rules/`, `tasks/` | Replace `/workspace/target` and `.repo-kit/hermes/reports/` with policy/run-root paths; exact prerequisite artifact ids |

## Explicitly not packaged as Hermes authority

| Source | Reason |
|--------|--------|
| `modules/security/files/.github/workflows/security-check.yml` | CI; not VPS review runtime |
| `modules/security/files/.cursor/skills/security-hardening/SKILL.md` as a Hermes skill | Avoid duplicating tasks; Cursor-specific aggregation |
| `extensions/hermes/hermes-review.sh`, `.bashrc_hermes` | Local Docker launcher only |

## Verification checklist (for packaging tests later)

- [ ] Every unchanged row is a bit-identical copy of the named source at the recorded toolkit revision
- [ ] No `/home/…` or other developer-machine paths appear in runtime instructions
- [ ] No requirement that `gh`, Hermes CLI, or MCP exist in upload mode
- [ ] Schema enums and `SG-` / `AR-` patterns match the copied schema and accepted-risk template
- [ ] Live target findings stores are not overwritten by empty template copies
