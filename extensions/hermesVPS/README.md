# hermesVPS — Hermes review workflow for VPS / portal upload

## Status

All eight phases (010–080) implemented with:

- rules/tasks/templates for each phase;
- validation runner (`bin/hermes-vps-review`);
- review initializer (`bin/init-hermes-review`);
- shared validation library (`lib/hermes_vps_common.py`);
- phase table and prerequisite descriptors (`lib/hermes_vps_phases.py`);
- artifact helper (`bin/hermes-vps-artifacts`) — sole writer of `manifest.json`;
- operator target registry (`targets.json`);
- thin skill adapters `skills/hermes-vps-010` through `skills/hermes-vps-remediate`;
- security schema copy and fixture tests.

This extension does **not** replace `extensions/hermes/`. Local Hermes remains
unchanged.

**Not implemented:** installer/packaging automation, verified portal skill
discovery, Roomote/GitHub/MCP automation.

---

## A. Initialize a review

```bash
init-hermes-review https://github.com/org/repo.git
# optional flags:
#   --target-id ID
#   --run-id ID
#   --activate-new-run          # required to replace an existing active run
#   --policy-prefix /opt/data/hermes-review
```

The initializer clones the repo, writes `run.json` + empty `reports/`, validates,
and atomically updates `targets.json`.  It does not start analysis.

---

## B. Phase-by-phase operator guide

### CLI compatibility note

**`--phase NNN` is now required** on `hermes-vps-review`.  Callers that previously
omitted `--phase` (implying phase 010) must now pass `--phase 010` explicitly.
`run.json phase_request.phase` is legacy/informational metadata; the CLI flag is
authoritative.

### Phase 010 — Inventory

```bash
/hermes-vps-010 repoX
```

Or via runner directly:
```bash
hermes-vps-review --phase 010 --registry /opt/data/hermes-review/targets.json --target-id repoX
```

Agent writes report → calls `hermes-vps-artifacts register --phase 010 --source-report <path>`.
Operator reviews consultation prompt → separate explicit request before phase 020.

### Phases 020–050 (linear sequence)

```bash
/hermes-vps-020 repoX   # threat model (prereqs: 010)
/hermes-vps-030 repoX   # scanner plan (prereqs: 010, 020)
/hermes-vps-040 repoX   # dependency advisories + vuln intel (prereqs: 010, 020, 030)
/hermes-vps-050 repoX   # source review — one priority per invocation (prereqs: 010, 020)
```

Phases 040 and 050 may run in either order, or both, depending on the
approved scan plan.

### Phase 040 — Vulnerability intelligence

Phase 040 requires a structured `vuln-intel-record.json` payload. Hermes
invokes `bin/hermes-vps-collect-intel` automatically — no manual JSON assembly.

Collection modes (pass in trigger message):
- **Live** (explicit network authorization required): `--mode live`
- **Not authorized** (honest record, no network): `--mode not-authorized`
- **Offline/import** (re-use prior evidence): `--mode imported --import-evidence PATH`

All endpoint URLs are defined in `lib/hermes_vps_intel.py INTEL_SOURCES`. Do not
duplicate them in rules, tasks, or skills.

**Privacy notice:** In live mode, package names and versions are sent to OSV and NVD.
Use `--mode imported` or `--mode not-authorized` when dependency disclosure is restricted.

```bash
# Live collection (when network is authorized in trigger):
hermes-vps-collect-intel \
  --run-json /abs/run.json \
  --output /abs/reports/vuln-intel.json \
  --mode live \
  --packages-json /abs/packages.json

# Then register with payload:
hermes-vps-artifacts register \
  --run-json /abs/run.json --phase 040 \
  --source-report /abs/report.md \
  --payload-json /abs/reports/vuln-intel.json
```

The payload records per-provider freshness. `generate-findings` reads it to
evaluate intelligence readiness. Default freshness threshold: **24 hours**.

To refresh stale intel before `generate-findings`:
```bash
# Re-collect
hermes-vps-collect-intel --run-json /abs/run.json --output /abs/reports/vuln-intel-v2.json --mode live --packages-json /abs/packages.json
# Revise the 040 artifact:
hermes-vps-artifacts revise \
  --run-json /abs/run.json \
  --source-report /abs/updated-040-report.md \
  --supersedes phase-040-hermes-v1 \
  --reviewer-identity "operator" \
  --payload-json /abs/reports/vuln-intel-v2.json
# Then re-generate:
hermes-vps-artifacts generate-findings --run-json /abs/run.json
```

Phase 050 for a second priority:
```bash
/hermes-vps-050 repoX authentication-flows
```

### Phase 060 — Validate and triage

```bash
/hermes-vps-060 repoX
```

Requires at least one of 040 or 050.  When both are selected and valid, both
are read as input.  Phase 060 produces:
- A Markdown report
- A JSON triage payload (`triage-payload.schema.json`) with stable `candidate_id` values

Both are registered together:
```bash
hermes-vps-artifacts register \
  --run-json /abs/run.json --phase 060 \
  --source-report /abs/report.md \
  --payload-json /abs/triage-payload.json
```

### Phase 070 — Reviewed findings (one candidate per invocation)

```bash
/hermes-vps-070 repoX C-001   # first candidate
/hermes-vps-070 repoX C-002   # second candidate — separate invocation
```

Revising C-001 does not replace C-002's assessment:
```bash
hermes-vps-artifacts revise \
  --run-json /abs/run.json \
  --source-report /abs/revised-report.md \
  --supersedes phase-070-hermes-v1 \
  --reviewer-identity "reviewer-name"
# ^ updates C-001's selected artifact; C-002 selection unchanged
```

Each registration uses `--subject-id <candidate_id>`.  Cross-subject
supersession is rejected.

Phase 070 produces per-candidate:
- A Markdown report
- A JSON finding-record payload (`finding-record.schema.json`)

```bash
hermes-vps-artifacts register \
  --run-json /abs/run.json --phase 070 \
  --subject-id C-001 \
  --source-report /abs/report.md \
  --payload-json /abs/finding-record.json
```

### Generate findings export (after all 070 phases complete)

```bash
/hermes-vps-remediate repoX
# or directly:
hermes-vps-artifacts generate-findings --run-json /abs/run.json
```

The export includes a multi-field `readiness` object with separate fields for
intel freshness, assessment completeness, and 080 provenance. A stale-intel
warning does not discard valid findings.

```bash
# Strict freshness gate (exit 2 if stale; export still written and registered):
hermes-vps-artifacts generate-findings --run-json /abs/run.json --require-fresh-intel
# Override threshold:
hermes-vps-artifacts generate-findings --run-json /abs/run.json --freshness-hours 48
# Exit codes: 0=success, 1=error, 2=policy check failed (--require-fresh-intel)
```

If any candidates from the triage inventory have no current 070 assessment,
the export is labeled **PARTIAL**. A partial export is **not** a complete
remediation handoff.

Enriching with optional 080 plans: run phase 080 for each finding before
calling `generate-findings`; the helper automatically incorporates available
080 plans.

```bash
# With 080 plans for SG-001 registered:
hermes-vps-artifacts generate-findings --run-json /abs/run.json
# → findings-v1.json includes remediation_plan_artifact: "phase-080-hermes-v1"
# → finding status remains "open" (plan ≠ fix)
# → readiness.provenance_080 reports mismatched_intel if 040 changed since 080 plan
```

### Phase 080 — Remediation plan (one finding per invocation, gate 1 only)

```bash
/hermes-vps-080 repoX SG-001   # plan for first finding
/hermes-vps-080 repoX SG-002   # separate invocation for second finding
```

Gate 1 only. Produces a remediation plan **and a provenance payload**.
Phase 080 now requires `--payload-json` at registration.
The payload records the exact phase-040 and phase-070 artifact IDs/hashes
used — resolved at plan creation time, stored immutably.

```bash
hermes-vps-artifacts register \
  --run-json /abs/run.json --phase 080 \
  --subject-id SG-001 \
  --source-report /abs/report.md \
  --payload-json /abs/plan-080-SG-001.json
```

Gates 2–5 require separate authorization. Does not change finding status.

---

## C. Stale downstream selections

When a phase-050 or phase-040 report is revised and re-registered, the
phase-060 and all downstream artifacts may reference the old prerequisite.

`hermes-vps-artifacts selected` prints the current selections with SHA-256
verification.  `generate-findings` detects stale assessments and labels the
export partial.

```bash
hermes-vps-artifacts selected --run-json /abs/run.json
```

---

## D. `run.json` versus `manifest.json`

| File | Owner | Role |
|------|-------|------|
| `run.json` | Operator; stable during the run | Identity, commit, output root, phase (legacy metadata) |
| `manifest.json` | `hermes-vps-artifacts` only | Artifact index; never hand-edit |

`hermes-vps-review` is validate-only and never writes any file.

### `manifest.json` selection fields

| Field | Used for | Authoritative for |
|-------|----------|-------------------|
| `selected_by_phase` | Phases 010–060, findings | Single-instance phases |
| `selected_by_subject["070"][candidate_id]` | Phase 070 | Repeated 070 assessments |
| `selected_by_subject["080"][finding_id]` | Phase 080 | Repeated 080 plans |

---

## E. Artifact helper (`hermes-vps-artifacts`)

Sole writer of `manifest.json`.

```bash
# Register a report (single-instance phases)
hermes-vps-artifacts register \
  --run-json PATH --phase 010 \
  --source-report PATH

# Register with structured payload (phases 060, 070)
hermes-vps-artifacts register \
  --run-json PATH --phase 060 \
  --source-report PATH --payload-json PATH

# Register repeated phase with subject identity (phases 070, 080)
hermes-vps-artifacts register \
  --run-json PATH --phase 070 \
  --subject-id C-001 \
  --source-report PATH --payload-json PATH

# Accept second opinion (does not change selection)
hermes-vps-artifacts accept \
  --run-json PATH --artifact-id phase-010-hermes-v1 \
  --reviewer-identity "name"

# Import revised report (updates subject-scoped selection; rejects cross-subject supersession)
hermes-vps-artifacts revise \
  --run-json PATH --source-report PATH \
  --supersedes phase-070-hermes-v1 \
  --reviewer-identity "name"

# Print/verify current selections
hermes-vps-artifacts selected --run-json PATH [--phase 070]

# Generate consolidated findings export
hermes-vps-artifacts generate-findings --run-json PATH

# Validate a findings export file (read-only)
hermes-vps-artifacts validate-findings \
  --run-json PATH --findings-file PATH
```

---

## F. Runner

```bash
# Mode A: direct run.json
hermes-vps-review --phase NNN --run-json PATH

# Mode B: registry lookup
hermes-vps-review --phase NNN \
  --registry PATH --target-id ID

# Repeated phases (070, 080): provide trigger input
hermes-vps-review --phase 070 --run-json PATH --trigger-input C-001
hermes-vps-review --phase 080 --run-json PATH --trigger-input SG-001
```

**`--phase` is required.** The runner prints the operator prompt and exits;
it never writes any file.

---

## G. Findings schemas

| Schema | Location | Purpose |
|--------|----------|---------|
| Canonical findings | `security-assets/findings.schema.json` | Validates target repo's `security/findings-reviewed.json` |
| Vuln-intel record | `templates/vuln-intel-record.schema.json` | Phase-040 evidence payload |
| Triage payload | `templates/triage-payload.schema.json` | Phase-060 candidate inventory |
| Finding record | `templates/finding-record.schema.json` | Phase-070 per-candidate payload |
| Phase-080 plan | `templates/phase-080-plan.schema.json` | Phase-080 provenance payload |
| Findings export | `templates/findings-export.schema.json` | Consolidated remediation handoff |

Intelligence endpoints: all URLs in `lib/hermes_vps_intel.py INTEL_SOURCES`.
Freshness default: 24 hours (`DEFAULT_FRESHNESS_HOURS`).

`assessment_disposition` (confirmed/suspected/dismissed/needs-investigation) is
distinct from canonical `status` (open/fixed/accepted-risk/duplicate/rejected).
Migration to the target repository's findings store requires separate
validation and authorization.

---

## H. Intelligence collection and refresh

`bin/hermes-vps-collect-intel` produces `vuln-intel-record.json`.
It is invoked by Hermes as part of phase 040 — not manually by the operator.

**When collection occurs:** Phase 040 task invokes the helper with mode
determined by the trigger message.

**External services receiving metadata (live mode):**
- OSV (`api.osv.dev`): package names, ecosystems, versions
- NVD (`services.nvd.nist.gov`): CVE IDs for enrichment
- CISA KEV (`www.cisa.gov`): full feed fetch; local matching only

**How to refresh stale evidence:** Revise the phase-040 artifact with a new
`vuln-intel-record.json`. `generate-findings` detects 080 plans that used the
old 040 snapshot and reports them in `readiness.provenance_080.mismatched_intel`.

**How to import offline evidence:**
```bash
hermes-vps-collect-intel --run-json PATH --output PATH \
  --mode imported --import-evidence /path/to/prior-record.json
```
Importing does not refresh evidence age; original `retrieved_at_utc` is preserved.

**Coverage limitations** appear in `readiness.intel.coverage.limitations` in the
export and in the phase-040 report's Coverage Limitations section.

---

## I. What upload mode does not require

`hermes` CLI, `gh`, Docker, sudo, systemd, GitHub/MCP bridges, shared
Roomote filesystem, or automatic skill discovery.

---

## Provenance

See `PROVENANCE.md`.
