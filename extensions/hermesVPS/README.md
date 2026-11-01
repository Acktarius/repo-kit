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
/hermes-vps-050 repoX <priority_area>   # source review — one priority per invocation (prereqs: 010, 020)
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

Requires at least one of 040 or 050.  Every selected input is read: phase 040
if selected, and every selected phase-050 review priority.  A selected input
that is incomplete, tampered, or stale blocks phase 060.  Phase 060 produces:
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

### Findings export (automatic after the last 070 assessment)

When a phase-070 registration leaves every triaged candidate with a complete,
current assessment, `hermes-vps-artifacts` consolidates the findings export
automatically and prints the handoff prompt.  To regenerate later (for
example after registering 080 plans):

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

Enriching with optional 080 plans: run phase 080 for each candidate, then
regenerate the export; current 080 plans are incorporated automatically.

```bash
# With an 080 plan for C-001 registered:
hermes-vps-artifacts generate-findings --run-json /abs/run.json
# → findings-v1.json includes remediation_plan_artifact: "phase-080-hermes-v1"
# → finding status remains "open" (plan ≠ fix)
# → readiness.provenance_080.stale_plans lists plans whose 040/070 inputs changed
```

### Phase 080 — Remediation plan (one candidate per invocation, gate 1 only)

```bash
/hermes-vps-080 repoX C-001   # plan for first actionable candidate
/hermes-vps-080 repoX C-002   # separate invocation for second candidate
```

Phases 070 and 080 are keyed by the phase-060 `candidate_id`.  Phase 080 requires
the candidate's current 070 assessment to be confirmed, suspected, or
needs-investigation.  The optional payload `finding_id` must equal the 070
`proposed_finding.id`.

Gate 1 only. Produces a remediation plan **and a provenance payload**.
Phase 080 now requires `--payload-json` at registration.
The payload records the exact phase-040 and phase-070 artifact IDs and their
`payload_sha256` values — resolved at plan creation time, stored immutably.

```bash
hermes-vps-artifacts register \
  --run-json /abs/run.json --phase 080 \
  --subject-id C-001 \
  --source-report /abs/report.md \
  --payload-json /abs/plan-080-C-001.json
```

Gates 2–5 require separate authorization. Does not change finding status.

---

## C. Stale downstream selections

Each registration records its prerequisite IDs with their report and payload
SHA-256 values.  An artifact is stale when any upstream input is no longer the
current selection, is not complete, or no longer matches the recorded hashes
(checked recursively).  The runner and the helper refuse stale inputs, and a
report whose recorded execution inputs are no longer the current selection is
not registered (no silent substitution of newer inputs).

`hermes-vps-artifacts selected` prints every current selection with its
problems and exits 1 if any selection is not usable.  `generate-findings`
excludes stale assessments and plans and labels the export partial.

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
| `selected_by_subject["050"][priority_area]` | Phase 050 | Repeated 050 review priorities |
| `selected_by_subject["080"][candidate_id]` | Phase 080 | Repeated 080 plans |

---

## E. Artifact helper (`hermes-vps-artifacts`)

Sole writer of `manifest.json`.  Every report must start with the REPORT
IDENTITY HEADER printed by the runner (`<!-- hermes-vps-report: {...} -->`):
run ID, phase, subject, source identity and commit, completion state, and the
execution-input snapshot (prerequisite IDs with report `sha256` and
`payload_sha256`).  Registration rejects the report, and records nothing, if any
header field disagrees with the run or command, or if the snapshot differs from
the inputs selected at registration time (an input was revised or added during
the phase): re-run `hermes-vps-review` and redo the phase.  Only the header and
payload schemas are machine-validated; report sections are procedural (Rule 005).

Only `complete` artifacts are usable as prerequisites.  Files are created
exclusively; if a write fails, the printed recovery command repeats the original
operation.

`register` exit codes: 0 registered; 1 not registered; 3 the phase-070 artifact
**is** registered but automatic findings consolidation failed — do not re-register;
run the printed export-only retry (`generate-findings`).  Consolidation runs inside
the registering lock and never re-acquires it.

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

# Repeated phases: provide trigger input (050: priority_area; 070/080: candidate_id)
hermes-vps-review --phase 050 --run-json PATH --trigger-input auth-module
hermes-vps-review --phase 070 --run-json PATH --trigger-input C-001
hermes-vps-review --phase 080 --run-json PATH --trigger-input C-001
```

**`--phase` is required.** The runner resolves every prerequisite (complete,
intact, current) before printing the operator prompt, and exits non-zero
without a prompt otherwise; it never writes any file.

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

**Destination policy (live mode):** HTTPS on port 443 only; no embedded
credentials; every resolved address must be globally routable unicast IPv4/IPv6
(checked again at connect time and for every redirect target); environment
proxies are not used.  Unresolvable hosts are refused.

**How to refresh stale evidence:** Revise the phase-040 artifact with a new
`vuln-intel-record.json`. `generate-findings` excludes 080 plans built on the
old 040 snapshot and lists them in `readiness.provenance_080.stale_plans`.

**How to import offline evidence:**
```bash
hermes-vps-collect-intel --run-json PATH --output PATH \
  --mode imported --import-evidence /path/to/prior-record.json
```
Importing does not refresh evidence age; original `retrieved_at_utc` is preserved.

**Coverage limitations** appear in `readiness.intel.coverage.limitations` in the
export and in the phase-040 report's Coverage Limitations section.

**Intelligence scope and evidence retention (current limitations):**
- OSV pagination is **not implemented**.  When a querybatch result carries a
  `next_page_token`, the package is listed in `providers.osv.incomplete_packages`,
  the OSV status is `partial`, and the package is never reported as no-match.
  Coverage for such packages remains incomplete (unresolved limitation).
- NVD is queried one CVE at a time (`cveId=`), so no NVD pagination is involved;
  CISA KEV is fetched as a single full feed.
- Raw response bodies, request bodies, HTTP status/headers, and per-request
  timestamps are **not retained**.  The record keeps, per provider, the endpoint,
  one `retrieved_at_utc`, counts, normalized results, and `response_sha256`.
- `response_sha256` covers only the raw bodies the collector read: OSV querybatch
  responses (not the per-advisory `/v1/vulns/{id}` fetches) and NVD CVE responses;
  in fixture mode it hashes re-serialized fixture JSON.  Because the raw bodies are
  not kept, the hash cannot be re-verified later; it is an identity marker only.


---

## I. What upload mode does not require

`hermes` CLI, `gh`, Docker, sudo, systemd, GitHub/MCP bridges, shared
Roomote filesystem, or automatic skill discovery.

---

## Provenance

See `PROVENANCE.md`.
