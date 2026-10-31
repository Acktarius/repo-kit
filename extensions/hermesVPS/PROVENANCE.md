# Provenance — hermesVPS assembly

Recorded from the developer checkout at packaging/copy time.
This file documents what is present under `extensions/hermesVPS/` in the
repo-kit tree (upload/install packaging comes later).

## Assembly metadata

- **Toolkit repository:** Acktarius/repo-kit
- **Toolkit revision (full SHA):** `7c7484a5ed6472ebaac7b36e273f0e9528489c61`
- **Working tree dirty at record time:** `true` (untracked/modified hermesVPS work)
- **Record UTC date:** 2026-10-31
- **Assembler:** manual authoring (installer not yet implemented)

## Classification

| Kind | Meaning |
|------|---------|
| **unchanged** | Byte-identical copy of a canonical repo-kit path |
| **adapted** | New text derived from methodology; not a byte copy |
| **new** | hermesVPS-specific documentation or tooling |

## Unchanged canonical copies

| Source path | Destination | Notes |
|-------------|-------------|-------|
| `modules/security/files/security/findings.schema.json` | `security-assets/findings.schema.json` | Canonical findings schema; not modified by hermesVPS |

## Newly written tooling and documentation

| Destination | Purpose |
|-------------|---------|
| `security-assets/README.md` | Explains bundled assets |
| `PROVENANCE.md` | This provenance record |
| `README.md`, `BOOTSTRAP.md` | hermesVPS operator guide |
| `templates/*` | hermesVPS report/schema templates |
| `rules/*` | Agent-neutral VPS phase instructions (phases 000–080) |
| `tasks/*` | Phase task contracts (phases 010–080) |
| `bin/hermes-vps-review` | Validate-only runner + prompt printer (never writes files) |
| `bin/init-hermes-review` | Review initializer; 0faf7fe scope |
| `bin/hermes-vps-artifacts` | Artifact helper entry point (sole writer of manifest.json) |
| `lib/hermes_vps_common.py` | Shared validation helpers |
| `lib/hermes_vps_artifacts.py` | Artifact registration logic (all subcommands; per-run lock; SHA-256) |
| `lib/hermes_vps_phases.py` | Phase table, prerequisite descriptors, policy-file lists |
| `skills/hermes-vps-010/` through `skills/hermes-vps-remediate/` | Thin skill adapters |

## Adapted instructions (not exact copies)

| Inspiration source | Destination | Adaptation |
|-------------------|-------------|-----------|
| `extensions/hermes/rules/rules_000*` | `rules/rules_000*` | No `/workspace/target`; run.json paths |
| `extensions/hermes/rules/rules_005*` | `rules/rules_005*` | write-then-register flow |
| `extensions/hermes/rules/rules_010*` | `rules/rules_010*` | VPS paths; helper-owned manifest |
| `extensions/hermes/tasks/010*` | `tasks/010*` | Absolute paths; register step |
| `extensions/hermes/rules/rules_020–080*` | `rules/rules_020–080*` | VPS adaptation; subject-scoped selection for 070/080 |
| `extensions/hermes/tasks/020–080*` | `tasks/020–080*` | Register step; payload requirement for 060/070 |

## Design changelog

### Stage 3 — Artifact-index automation (separate from 0faf7fe)

Replaced operator-maintained `manifest.json` with automatic maintenance:

- `hermes-vps-review` is validate-only (never writes files)
- `hermes-vps-artifacts` is the sole writer of `manifest.json`
- Auto-version selection under per-run `fcntl` lock; SHA-256 integrity
- `phase_request.report_version` deprecated (warning, not error)
- Normal progression does not require a separate acceptance file

### Stage 3 — Phases 020–080 and findings export

Extended workflow through all eight phases:

- **`--phase NNN` required** on runner (breaking CLI change; documented)
- `run.json.phase_request.phase` is legacy/informational; CLI phase is authoritative
- Subject-scoped selection (`selected_by_subject`) for repeated phases 070 and 080
- Structured JSON payloads (phase 060: triage inventory; phase 070: finding record)
- `generate-findings` subcommand: consolidates selected 070 payloads into immutable export
- Three new schemas: `triage-payload.schema.json`, `finding-record.schema.json`, `findings-export.schema.json`
- `assessment_disposition` distinct from canonical `status`; no false "fixed" status
- Phase 080: gate 1 (plan) only; gates 2–5 require separate authorization
- Prerequisite OR-descriptor (`OneOf`) for phase 060; stale-branch reporting
- Cross-subject supersession rejection in `revise`

## Vulnerability intelligence (2026-10-30)

- `lib/hermes_vps_intel.py`: centralized endpoint config (`INTEL_SOURCES`), OSV querybatch,
  NVD CVE 2.0 enrichment, CISA KEV feed, per-provider freshness evaluation, fixture injection
- `bin/hermes-vps-collect-intel`: CLI shim; modes: live / imported / not-authorized
- `templates/vuln-intel-record.schema.json`: phase-040 evidence payload schema
- `templates/phase-080-plan.schema.json`: phase-080 immutable provenance schema
- Phase 040 `payload_required=True`: `vuln-intel-record.json` mandatory at registration
- Phase 080 `payload_required=True`: plan provenance payload mandatory at registration
- `generate-findings` expanded: multi-field `readiness` object; `--require-fresh-intel` (exit 2);
  `--freshness-hours`; 080 provenance mismatch detection; per-provider freshness not aggregate bool
- Default freshness threshold: 24 hours (`DEFAULT_FRESHNESS_HOURS`)
- Freshness evaluated per-provider using `retrieved_at_utc`; import/registration time never used
- `revise` now accepts `--payload-json` for payload-required phases (040, 070, 080)

## Explicitly not included

- Installer, packaging archives
- Local Hermes launcher (`extensions/hermes/hermes-review.sh`)
- Verified portal skill discovery or automatic skill registration
