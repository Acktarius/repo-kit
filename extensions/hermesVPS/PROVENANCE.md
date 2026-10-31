# Provenance — hermesVPS Stage 3 assembly

Recorded from the developer checkout at packaging/copy time for Stage 3.
This file documents what is present under `extensions/hermesVPS/` in the
repo-kit tree (upload/install packaging comes later).

## Assembly metadata

- **Toolkit repository:** Acktarius/repo-kit
- **Toolkit revision (full SHA):** `7c7484a5ed6472ebaac7b36e273f0e9528489c61`
- **Working tree dirty at record time:** `true` (untracked `extensions/hermesVPS/` work in progress; tracked `modules/security/files/security/findings.schema.json` was clean)
- **Record UTC date:** 2026-10-31 (operator session local calendar date 2026-10-30)
- **Assembler:** manual Stage 3 copy / authoring (installer not yet implemented)

## Classification

| Kind | Meaning |
|------|---------|
| **unchanged** | Byte-identical copy of a canonical repo-kit path |
| **adapted** | New text derived from methodology; not a byte copy |
| **new** | hermesVPS-specific documentation or tooling |

## Unchanged canonical copies

| Source path | Destination | Notes |
|-------------|-------------|-------|
| `modules/security/files/security/findings.schema.json` | `security-assets/findings.schema.json` | SHA-256 `5d23cd56a4af18751cd1e8c7ed38a8ef8f54438790c87b97410b3bd33a6aac45` |

## Newly written integration documentation

| Destination | Purpose |
|-------------|---------|
| `security-assets/README.md` | Explains bundled assets without Cursor slash-command workflow |
| `PROVENANCE.md` | This provenance record |
| `README.md`, `BOOTSTRAP.md`, `templates/*` | hermesVPS contracts (Stage 2+) |
| `rules/*`, `tasks/*` | Agent-neutral VPS phase instructions |
| `bin/hermes-vps-review` | Local validation + prompt printer |
| `bin/init-hermes-review` | Phase-010 review initializer (clone/register/validate) |
| `lib/hermes_vps_common.py` | Shared validation helpers for runner + initializer |

## Adapted instructions (not exact copies)

| Inspiration sources | Destination | Adaptation purpose |
|---------------------|-------------|--------------------|
| `extensions/hermes/rules/rules_000-safety-and-scope.md` | `rules/rules_000-safety-and-scope.md` | Policy/run-root paths; procedural boundaries; no `/workspace/target` |
| `extensions/hermes/rules/rules_005-report-output.md` | `rules/rules_005-report-output.md` | Versioned reports under run-root; operator-owned manifest |
| `extensions/hermes/rules/rules_010-inventory.md` | `rules/rules_010-inventory.md` | Explicit run registration; no scanners/builds |
| `extensions/hermes/tasks/010-inventory.md` | `tasks/010-inventory.md` | Absolute/policy paths; exact artifacts; stop after one phase |
| `modules/security/files/security/README.md` | *not copied* | Cursor `/security-*` and `.cursor/plans/` would mislead on VPS; replaced by adapted `security-assets/README.md` |
| `modules/security/files/.cursor/commands/00-security-plan-hardening.md` | Distilled into 010 inventory scope notes only | No Plan Mode; no `.cursor/plans/` writes |

## Explicitly not included in Stage 3

- Empty `findings-reviewed.json` / findings store seed
- Finding template, accepted-risks, threat-model template copies (later)
- Installer, packaging archives, phases 020–080, skills
- Local Hermes launcher (`extensions/hermes/hermes-review.sh`)
