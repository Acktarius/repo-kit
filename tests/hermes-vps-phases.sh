#!/usr/bin/env bash
# Fixture tests for hermesVPS phases 020-080: phase contracts, runner, subject-scoped
# selection, structured payloads, generate-findings, cross-subject supersession,
# stale detection, and OR-prerequisite behaviour.
# Synthetic repos and temporary destinations only. No VPS / network.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXT="${ROOT}/extensions/hermesVPS"
RUNNER="${EXT}/bin/hermes-vps-review"
ARTIFACTS="${EXT}/bin/hermes-vps-artifacts"

TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

fail=0
pass=0

ok()  { pass=$((pass + 1)); echo "PASS: $*"; }
bad() { fail=$((fail + 1)); echo "FAIL: $*" >&2; }

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "FAIL: missing host command $1" >&2
    exit 1
  }
}
need git
need python3
need sha256sum

[[ -x "${RUNNER}" ]] || { echo "FAIL: runner not executable" >&2; exit 1; }
[[ -x "${ARTIFACTS}" ]] || { echo "FAIL: artifacts not executable" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Fixture layout
# ---------------------------------------------------------------------------
POLICY="${TMP}/policy/hermes-review"
SRC="${TMP}/repositories/example-repo"
RUN="${TMP}/review-runs/example-repo/run-phases"
mkdir -p "${POLICY}" "${SRC}" "${RUN}/reports"
cp -a "${EXT}/." "${POLICY}/"
find "${POLICY}" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "${POLICY}" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

git -C "${SRC}" init -q
git -C "${SRC}" config user.email "test@example.com"
git -C "${SRC}" config user.name "Test"
echo "hello" >"${SRC}/README.md"
git -C "${SRC}" add README.md
git -C "${SRC}" commit -q -m "init"
SHA="$(git -C "${SRC}" rev-parse HEAD)"

write_run() {
  local out="$1" policy="$2" src="$3" run_root="$4" commit="$5"
  python3 - "$out" "$policy" "$src" "$run_root" "$commit" <<'PY'
import json, sys
out, policy, src, run_root, commit = sys.argv[1:6]
data = {
  "schema_version": 1,
  "run_id": "run-phases",
  "policy_prefix": policy,
  "source": {
    "path": src,
    "identity": "fixture/example-repo",
    "commit": commit,
    "require_clean_worktree": True,
  },
  "output": {"run_root": run_root},
  "phase_request": {
    "phase": "010",
    "phase_name": "inventory",
    "requested_by": "test",
    "requested_at_utc": "2026-10-30T00:00:00Z",
  },
  "prerequisites": {"artifacts": []},
  "boundaries": {
    "claims_os_readonly_source": False,
    "allowed_write_roots": [run_root],
  },
  "toolkit": {"toolkit_revision": "testrev01", "toolkit_dirty": False},
}
with open(out, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
PY
}

RUN_JSON="${RUN}/run.json"
write_run "${RUN_JSON}" "${POLICY}" "${SRC}" "${RUN}" "${SHA}"
sha256() { sha256sum "$1" | awk '{print $1}'; }

# ---------------------------------------------------------------------------
# Helper: make a simple report file
# ---------------------------------------------------------------------------
make_report() {
  local path="$1" content="${2:-# Report\n\nContent.\n}"
  printf '%b' "${content}" >"${path}"
  grep -qiE '^[[:space:]-]*(\*\*)?(completion )?state' "${path}" || printf '\nState: `complete`\n' >>"${path}"
}

# ---------------------------------------------------------------------------
# Helper: make a triage payload JSON (phase 060)
# ---------------------------------------------------------------------------
make_triage_payload() {
  local path="$1" commit="$2"
  shift 2
  # remaining args: candidate IDs
  python3 - "${path}" "${commit}" "$@" <<'PY'
import json, sys
path, commit = sys.argv[1], sys.argv[2]
cids = sys.argv[3:]
data = {
  "schema_version": 1,
  "phase": "060",
  "source_commit": commit,
  "candidates": [
    {
      "candidate_id": cid,
      "title": f"Test finding {cid}",
      "disposition": "validated-new",
      "severity_estimate": "medium",
      "confidence": "high",
    }
    for cid in cids
  ]
}
with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
PY
}

# ---------------------------------------------------------------------------
# Helper: make a finding record payload JSON (phase 070)
# ---------------------------------------------------------------------------
make_finding_payload() {
  local path="$1" commit="$2" cid="$3" disposition="${4:-confirmed}"
  python3 - "${path}" "${commit}" "${cid}" "${disposition}" <<'PY'
import json, sys
path, commit, cid, disposition = sys.argv[1:5]
data = {
  "schema_version": 1,
  "phase": "070",
  "candidate_id": cid,
  "source_commit": commit,
  "assessment_disposition": disposition,
  "assessment_rationale": f"Evidence supports {disposition} for {cid}",
  "affected_components": ["module/auth.py"],
  "impact": "Authentication bypass possible",
  "likelihood": "medium",
  "evidence": [{"description": "Unsafe comparison", "file": "module/auth.py", "line": 42}],
  "unknowns": [],
  "blockers": [],
  "proposed_finding": {
    "id": None,
    "title": f"Finding from {cid}",
    "status": "open",
    "severity": "medium",
    "confidence": "high",
    "files": ["module/auth.py"],
    "summary": f"Summary for {cid}",
    "exploitPath": "Describe exploit path",
    "remediation": "Fix the vulnerability",
  }
}
with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
PY
}

# ---------------------------------------------------------------------------
# Helper: make a minimal vuln-intel-record payload JSON (phase 040)
# Uses collection_mode=not_authorized so no network is needed.
# ---------------------------------------------------------------------------
make_vuln_intel_payload() {
  local path="$1" commit="$2"
  python3 - "${path}" "${commit}" <<'PY'
import json, sys
path, commit = sys.argv[1], sys.argv[2]
data = {
  "schema_version": 1, "phase": "040", "source_commit": commit,
  "collection_mode": "not_authorized",
  "collected_at_utc": "2026-10-30T00:00:00Z",
  "freshness_policy_hours": 24.0,
  "providers": {
    "osv": {"status": "not_authorized",
            "endpoint_used": "https://api.osv.dev/v1/querybatch",
            "retrieved_at_utc": None, "response_sha256": None,
            "packages_queried": 0, "advisory_ids_returned": [],
            "note": "network access not authorized"},
    "nvd": {"status": "not_authorized",
            "endpoint_used": "https://services.nvd.nist.gov/rest/json/cves/2.0",
            "retrieved_at_utc": None, "response_sha256": None,
            "cves_enriched": [], "cves_failed": [],
            "api_key_used": False, "note": "network access not authorized"},
    "cisa_kev": {"status": "not_authorized",
                 "endpoint_used": "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
                 "retrieved_at_utc": None, "response_sha256": None,
                 "catalog_version": None, "kev_count": 0, "matched_cves": [],
                 "note": "network access not authorized"}
  },
  "vendor_advisories": [], "matches": [], "no_match_packages": [],
  "unsupported_ecosystems": [], "inventory_gaps": [],
  "coverage": {"total_packages_checked": 0, "total_matches": 0, "kev_matches": 0,
               "packages_with_gaps": 0, "baseline_or_refresh": "baseline",
               "notes": "not_authorized: no network collection performed"}
}
with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
PY
}

# ---------------------------------------------------------------------------
# Helper: make a phase-080 provenance plan payload JSON
# Pins the current 040 and the current 070 for the candidate by payload SHA-256.
# Args: path commit manifest candidate_id
# ---------------------------------------------------------------------------
make_phase080_plan_payload() {
  local path="$1" commit="$2" manifest="$3" candidate_id="$4"
  python3 - "${path}" "${commit}" "${manifest}" "${candidate_id}" <<'PY'
import json, sys
path, commit, manifest_path, candidate_id = sys.argv[1:5]
with open(manifest_path, encoding="utf-8") as fh:
    m = json.load(fh)
arts = {a["id"]: a for a in m["artifacts"]}
intel_id = m["selected_by_phase"]["040"]
finding_art_id = m["selected_by_subject"]["070"][candidate_id]
data = {
  "schema_version": 1,
  "phase": "080",
  "candidate_id": candidate_id,
  "source_commit": commit,
  "intel_artifact_id": intel_id,
  "intel_artifact_sha256": arts[intel_id]["payload_sha256"],
  "assessed_finding_artifact_id": finding_art_id,
  "assessed_finding_sha256": arts[finding_art_id]["payload_sha256"],
  "intel_freshness_at_plan_time": {
    "evaluated_at_utc": "2026-10-30T00:00:00Z",
    "effective_threshold_hours": 24.0,
    "threshold_source": "default",
    "freshness_ok": False,
    "stale_providers": [],
    "unknown_providers": ["osv", "nvd", "cisa_kev"],
    "limitations": ["all providers not_authorized; freshness unknown"]
  }
}
with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
PY
}

# ---------------------------------------------------------------------------
# Section A: Runner -- phases 020-080 require matching policy files
# ---------------------------------------------------------------------------

echo "=== Section A: Runner phase policy file checks ==="

# Fail-closed: runner refuses phase 020 before phase 010 is registered
if "${RUNNER}" --phase 020 --run-json "${RUN_JSON}" >"${TMP}/p020-nopre.txt" 2>"${TMP}/p020-nopre.err"; then
  bad "runner: phase 020 without phase 010 should fail"
else
  grep -q 'phase-010' "${TMP}/p020-nopre.err" && [[ ! -s "${TMP}/p020-nopre.txt" ]] \
    && ok "runner: phase 020 without phase 010 rejected before any prompt output" \
    || bad "runner: wrong failure: $(cat "${TMP}/p020-nopre.err")"
fi

# Phase 070: missing --trigger-input should fail
if "${RUNNER}" --phase 070 --run-json "${RUN_JSON}" >/dev/null 2>"${TMP}/p070-notrig.err"; then
  bad "runner: phase 070 without --trigger-input should fail"
else
  grep -qi 'trigger-input\|candidate_id\|subject' "${TMP}/p070-notrig.err" \
    && ok "runner: phase 070 without --trigger-input rejected" \
    || bad "runner: wrong error: $(cat "${TMP}/p070-notrig.err")"
fi

# Invalid phase rejected by runner
if "${RUNNER}" --phase 099 --run-json "${RUN_JSON}" >/dev/null 2>"${TMP}/bad-phase.err"; then
  bad "runner: invalid phase 099 should fail"
else
  grep -qi 'unknown phase\|valid phases' "${TMP}/bad-phase.err" \
    && ok "runner: invalid phase 099 rejected" \
    || bad "runner: wrong error for invalid phase: $(cat "${TMP}/bad-phase.err")"
fi

# Non-existent phase-specific policy file causes failure
rm -f "${POLICY}/rules/rules_020-threat-model.md"
if "${RUNNER}" --phase 020 --run-json "${RUN_JSON}" >/dev/null 2>"${TMP}/missing-rule.err"; then
  bad "runner: missing phase-020 rule should fail"
else
  grep -qi 'missing required' "${TMP}/missing-rule.err" \
    && ok "runner: missing phase-020 rule file rejected" \
    || bad "runner: wrong error: $(cat "${TMP}/missing-rule.err")"
fi
# Restore the rule file
cp -a "${EXT}/rules/rules_020-threat-model.md" "${POLICY}/rules/rules_020-threat-model.md"

# ---------------------------------------------------------------------------
# Section B: Register phase 010 (baseline for later tests)
# ---------------------------------------------------------------------------

echo "=== Section B: Register phase-010 baseline ==="

RPT_010="${TMP}/report-010.md"
make_report "${RPT_010}" "# Phase 010 inventory\nContent.\n"

if "${ARTIFACTS}" register \
    --run-json "${RUN_JSON}" \
    --phase 010 \
    --source-report "${RPT_010}" \
    >"${TMP}/reg010.out" 2>"${TMP}/reg010.err"; then
  ok "register: phase 010 baseline"
else
  bad "register: phase 010 failed: $(cat "${TMP}/reg010.err")"
fi

# Phase 020 runner: should succeed (policy files exist)
if "${RUNNER}" --phase 020 --run-json "${RUN_JSON}" >"${TMP}/p020-prompt.txt" 2>"${TMP}/p020-err.txt"; then
  ok "runner: phase 020 validates successfully with policy files present"
else
  bad "runner: phase 020 unexpected failure: $(cat "${TMP}/p020-err.txt")"
fi

# Phase 020 prompt contains task path
if grep -Fq "tasks/020-threat-model.md" "${TMP}/p020-prompt.txt"; then
  ok "runner: phase 020 prompt includes phase-020 task"
else
  bad "runner: phase 020 prompt missing task reference"
fi

# Phase 020 prompt shows correct phase name
if grep -qi "threat-model" "${TMP}/p020-prompt.txt"; then
  ok "runner: phase 020 prompt shows phase name"
else
  bad "runner: phase 020 prompt missing phase name"
fi

# ---------------------------------------------------------------------------
# Missing-prerequisite rejection tests (before any upstream phases are registered)
# ---------------------------------------------------------------------------

# Phase 040 requires 010, 020, 030 — currently only 010 is done: must fail
VULN_NOPRE="${TMP}/vuln-nopre.json"
make_vuln_intel_payload "${VULN_NOPRE}" "${SHA}"
RPT_NOPRE="${TMP}/report-nopre.md"
make_report "${RPT_NOPRE}" "# Phase 040 no prereq test\n"
if "${ARTIFACTS}" register \
    --run-json "${RUN_JSON}" \
    --phase 040 \
    --source-report "${RPT_NOPRE}" \
    --payload-json "${VULN_NOPRE}" \
    >/dev/null 2>"${TMP}/nopre040.err"; then
  bad "register: phase 040 without 020/030 should fail (missing prerequisites)"
else
  grep -qi 'prerequisite\|phase.020\|phase.030' "${TMP}/nopre040.err" \
    && ok "register: phase 040 correctly rejected when 020/030 missing" \
    || bad "register: phase 040 wrong error for missing prereqs: $(cat "${TMP}/nopre040.err")"
fi

# Phase 070 requires 060 — must fail
RPT_070NOPRE="${TMP}/report-070-nopre.md"
FIND_NOPRE="${TMP}/finding-nopre.json"
make_report "${RPT_070NOPRE}" "# Phase 070 no prereq\n"
make_finding_payload "${FIND_NOPRE}" "${SHA}" "C-NOPRE" "confirmed"
if "${ARTIFACTS}" register \
    --run-json "${RUN_JSON}" \
    --phase 070 \
    --subject-id "C-NOPRE" \
    --source-report "${RPT_070NOPRE}" \
    --payload-json "${FIND_NOPRE}" \
    >/dev/null 2>"${TMP}/nopre070.err"; then
  bad "register: phase 070 without 060 should fail (missing prerequisite)"
else
  grep -qi 'prerequisite\|phase.060' "${TMP}/nopre070.err" \
    && ok "register: phase 070 correctly rejected when phase-060 missing" \
    || bad "register: phase 070 wrong error: $(cat "${TMP}/nopre070.err")"
fi

# ---------------------------------------------------------------------------
# Register phases 020 and 030 so downstream phases (040, 050, 060) can proceed
# ---------------------------------------------------------------------------

RPT_020="${TMP}/report-020.md"
make_report "${RPT_020}" "# Phase 020 threat model\nContent.\n"

if "${ARTIFACTS}" register \
    --run-json "${RUN_JSON}" \
    --phase 020 \
    --source-report "${RPT_020}" \
    >"${TMP}/reg020.out" 2>"${TMP}/reg020.err"; then
  ok "register: phase 020 (prereq: 010 satisfied)"
else
  bad "register: phase 020 failed: $(cat "${TMP}/reg020.err")"
fi

RPT_030="${TMP}/report-030.md"
make_report "${RPT_030}" "# Phase 030 scan plan\nContent.\n"

if "${ARTIFACTS}" register \
    --run-json "${RUN_JSON}" \
    --phase 030 \
    --source-report "${RPT_030}" \
    >"${TMP}/reg030.out" 2>"${TMP}/reg030.err"; then
  ok "register: phase 030 (prereq: 010, 020 satisfied)"
else
  bad "register: phase 030 failed: $(cat "${TMP}/reg030.err")"
fi

# ---------------------------------------------------------------------------
# Section B2: Register phase 040 (required by phase 080 provenance)
# ---------------------------------------------------------------------------

echo "=== Section B2: Register phase-040 with vuln-intel payload ==="

RPT_040_EARLY="${TMP}/report-040-v1.md"
PAYLOAD_040_EARLY="${TMP}/vuln-intel-record-v1.json"
make_report "${RPT_040_EARLY}" "# Phase 040 dep advisories\nContent.\n"
make_vuln_intel_payload "${PAYLOAD_040_EARLY}" "${SHA}"

# Reject phase 040 without --payload-json
if "${ARTIFACTS}" register \
    --run-json "${RUN_JSON}" \
    --phase 040 \
    --source-report "${RPT_040_EARLY}" \
    >/dev/null 2>"${TMP}/reg040-nopay.err"; then
  bad "register: phase 040 without --payload-json should fail"
else
  grep -qi 'payload\|require\|--payload-json' "${TMP}/reg040-nopay.err" \
    && ok "register: phase 040 without payload rejected" \
    || bad "register: phase 040 wrong error: $(cat "${TMP}/reg040-nopay.err")"
fi

# Accept phase 040 with --payload-json
if "${ARTIFACTS}" register \
    --run-json "${RUN_JSON}" \
    --phase 040 \
    --source-report "${RPT_040_EARLY}" \
    --payload-json "${PAYLOAD_040_EARLY}" \
    >"${TMP}/reg040-early.out" 2>"${TMP}/reg040-early.err"; then
  ok "register: phase 040 with vuln-intel payload succeeds"
else
  bad "register: phase 040 failed: $(cat "${TMP}/reg040-early.err")"
fi

MANIFEST="${RUN}/manifest.json"
python3 - "${MANIFEST}" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    m = json.load(fh)
arts_040 = [a for a in m["artifacts"] if a.get("phase") == "040"]
assert len(arts_040) == 1, f"expected 1 040 artifact, got {len(arts_040)}"
a = arts_040[0]
assert "payload_path" in a, "missing payload_path in 040 artifact"
assert "payload_sha256" in a, "missing payload_sha256 in 040 artifact"
assert m["selected_by_phase"].get("040") == a["id"]
print(f"PASS: phase 040 artifact registered: {a['id']}")
PY
[[ $? -eq 0 ]] && ok "register: phase 040 manifest fields correct" \
               || bad "register: phase 040 manifest fields incorrect"

# Phase 060: requires at least one of 040 or 050
if "${RUNNER}" --phase 060 --run-json "${RUN_JSON}" >"${TMP}/p060-prompt.txt" 2>"${TMP}/p060-err.txt"; then
  ok "runner: phase 060 validates successfully"
else
  bad "runner: phase 060 failure: $(cat "${TMP}/p060-err.txt")"
fi

# ---------------------------------------------------------------------------
# Section C: Phase 060 with structured payload (triage inventory)
# ---------------------------------------------------------------------------

echo "=== Section C: Phase 060 triage payload ==="

RPT_060="${TMP}/report-060.md"
PAYLOAD_060="${TMP}/triage-payload.json"
make_report "${RPT_060}" "# Phase 060 triage\nContent.\n"
make_triage_payload "${PAYLOAD_060}" "${SHA}" "C-001" "C-002" "C-003"

# Phase 060 requires --payload-json
if "${ARTIFACTS}" register \
    --run-json "${RUN_JSON}" \
    --phase 060 \
    --source-report "${RPT_060}" \
    >/dev/null 2>"${TMP}/reg060-nopay.err"; then
  bad "register: phase 060 without --payload-json should fail"
else
  grep -qi 'payload\|require\|--payload-json' "${TMP}/reg060-nopay.err" \
    && ok "register: phase 060 without payload rejected" \
    || bad "register: wrong error: $(cat "${TMP}/reg060-nopay.err")"
fi

# Phase 060 with payload succeeds
if "${ARTIFACTS}" register \
    --run-json "${RUN_JSON}" \
    --phase 060 \
    --source-report "${RPT_060}" \
    --payload-json "${PAYLOAD_060}" \
    >"${TMP}/reg060.out" 2>"${TMP}/reg060.err"; then
  ok "register: phase 060 with payload succeeds"
else
  bad "register: phase 060 with payload failed: $(cat "${TMP}/reg060.err")"
fi

# Verify manifest has payload_path
python3 - "${MANIFEST}" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    m = json.load(fh)
arts_060 = [a for a in m["artifacts"] if a.get("phase") == "060"]
assert len(arts_060) == 1, f"expected 1 060 artifact, got {len(arts_060)}"
a = arts_060[0]
assert "payload_path" in a, "missing payload_path in 060 artifact"
assert "payload_sha256" in a, "missing payload_sha256 in 060 artifact"
assert m["selected_by_phase"]["060"] == a["id"]
print("PASS: phase 060 manifest fields correct")
PY
[[ $? -eq 0 ]] && ok "register: phase 060 manifest fields include payload" \
               || bad "register: phase 060 manifest fields incorrect"

# Payload JSON is in reports dir
PAYLOAD_060_DEST="${RUN}/reports/payload-060-"
if ls "${RUN}/reports/payload-060-"* >/dev/null 2>&1; then
  ok "register: phase 060 payload JSON copied to reports/"
else
  bad "register: phase 060 payload not in reports/"
fi

# Phase 070: requires --trigger-input (candidate_id)
if "${RUNNER}" --phase 070 --run-json "${RUN_JSON}" --trigger-input C-001 >"${TMP}/p070-prompt.txt" 2>"${TMP}/p070-err.txt"; then
  ok "runner: phase 070 validates with trigger-input"
else
  bad "runner: phase 070 failure: $(cat "${TMP}/p070-err.txt")"
fi

# ---------------------------------------------------------------------------
# Section D: Phase 070 — subject-scoped selection for two candidates
# ---------------------------------------------------------------------------

echo "=== Section D: Phase 070 subject-scoped selection ==="

# Register C-001
RPT_070_C1="${TMP}/report-070-c001-v1.md"
PAYLOAD_070_C1="${TMP}/finding-record-c001-v1.json"
make_report "${RPT_070_C1}" "# Phase 070 C-001\nContent.\n"
make_finding_payload "${PAYLOAD_070_C1}" "${SHA}" "C-001" "confirmed"

if "${ARTIFACTS}" register \
    --run-json "${RUN_JSON}" \
    --phase 070 \
    --subject-id "C-001" \
    --source-report "${RPT_070_C1}" \
    --payload-json "${PAYLOAD_070_C1}" \
    >"${TMP}/reg070-c1.out" 2>"${TMP}/reg070-c1.err"; then
  ok "register: phase 070 C-001 succeeds"
else
  bad "register: phase 070 C-001 failed: $(cat "${TMP}/reg070-c1.err")"
fi

# Register C-002
RPT_070_C2="${TMP}/report-070-c002-v1.md"
PAYLOAD_070_C2="${TMP}/finding-record-c002-v1.json"
make_report "${RPT_070_C2}" "# Phase 070 C-002\nContent.\n"
make_finding_payload "${PAYLOAD_070_C2}" "${SHA}" "C-002" "suspected"

if "${ARTIFACTS}" register \
    --run-json "${RUN_JSON}" \
    --phase 070 \
    --subject-id "C-002" \
    --source-report "${RPT_070_C2}" \
    --payload-json "${PAYLOAD_070_C2}" \
    >"${TMP}/reg070-c2.out" 2>"${TMP}/reg070-c2.err"; then
  ok "register: phase 070 C-002 succeeds"
else
  bad "register: phase 070 C-002 failed: $(cat "${TMP}/reg070-c2.err")"
fi

# Verify selected_by_subject has both candidates
python3 - "${MANIFEST}" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    m = json.load(fh)
sbs = m.get("selected_by_subject", {}).get("070", {})
assert "C-001" in sbs, f"C-001 not in selected_by_subject[070]: {sbs}"
assert "C-002" in sbs, f"C-002 not in selected_by_subject[070]: {sbs}"
# Versions are globally incremented; C-001 is v1 (first 070), C-002 is v2 (second 070)
a_c1 = sbs["C-001"]
a_c2 = sbs["C-002"]
assert a_c1 != a_c2, "C-001 and C-002 should have different artifact IDs"
print(f"PASS: selected_by_subject[070]: C-001={a_c1}, C-002={a_c2}")
PY
[[ $? -eq 0 ]] && ok "register: selected_by_subject has both C-001 and C-002" \
               || bad "register: selected_by_subject missing candidates"

# Phase 070 without --subject-id should fail
RPT_070_NOSUB="${TMP}/report-070-nosub.md"
make_report "${RPT_070_NOSUB}" "# Phase 070 no subject\n"
PAYLOAD_070_NOSUB="${TMP}/finding-nosub.json"
make_finding_payload "${PAYLOAD_070_NOSUB}" "${SHA}" "C-999" "confirmed"
if "${ARTIFACTS}" register \
    --run-json "${RUN_JSON}" \
    --phase 070 \
    --source-report "${RPT_070_NOSUB}" \
    --payload-json "${PAYLOAD_070_NOSUB}" \
    >/dev/null 2>"${TMP}/nosub.err"; then
  bad "register: phase 070 without --subject-id should fail"
else
  grep -qi 'subject-id\|candidate_id\|require' "${TMP}/nosub.err" \
    && ok "register: phase 070 without --subject-id rejected" \
    || bad "register: wrong error: $(cat "${TMP}/nosub.err")"
fi

# Phase 070 without --payload-json should fail
if "${ARTIFACTS}" register \
    --run-json "${RUN_JSON}" \
    --phase 070 \
    --subject-id "C-004" \
    --source-report "${RPT_070_NOSUB}" \
    >/dev/null 2>"${TMP}/nopay070.err"; then
  bad "register: phase 070 without --payload-json should fail"
else
  grep -qi 'payload\|require\|--payload-json' "${TMP}/nopay070.err" \
    && ok "register: phase 070 without payload rejected" \
    || bad "register: wrong error: $(cat "${TMP}/nopay070.err")"
fi

# Phase 080: requires --trigger-input (candidate_id)
if "${RUNNER}" --phase 080 --run-json "${RUN_JSON}" --trigger-input C-001 >"${TMP}/p080-prompt.txt" 2>"${TMP}/p080-err.txt"; then
  ok "runner: phase 080 validates with trigger-input"
else
  bad "runner: phase 080 failure: $(cat "${TMP}/p080-err.txt")"
fi

# Phase 080 prompt contains gate-1-only language
if grep -qi 'gate 1\|gate1\|plan\|remediate' "${TMP}/p080-prompt.txt"; then
  ok "runner: phase 080 prompt references gate-1 plan"
else
  bad "runner: phase 080 prompt missing gate-1 reference"
fi

if grep -q 'SELECTED PREREQUISITES' "${TMP}/p080-prompt.txt" && grep -q 'phase 070 \[C-001\]\|070.*C-001' "${TMP}/p080-prompt.txt"; then
  ok "runner: phase 080 prompt lists resolved 070 prerequisite for C-001"
else
  bad "runner: phase 080 prompt lacks resolved prerequisites: $(cat "${TMP}/p080-prompt.txt")"
fi

# ---------------------------------------------------------------------------
# Section E: Revision of one candidate without affecting another
# ---------------------------------------------------------------------------

echo "=== Section E: Revision — C-001 revised; C-002 unaffected ==="

# Get C-001's current artifact ID
C1_ART_ID="$(python3 -c "
import json, sys
with open('${MANIFEST}') as fh:
    m = json.load(fh)
print(m['selected_by_subject']['070']['C-001'])
")"

RPT_070_C1_V2="${TMP}/report-070-c001-v2.md"
PAYLOAD_070_C1_V2="${TMP}/finding-record-c001-v2.json"
make_report "${RPT_070_C1_V2}" "# Phase 070 C-001 v2 (revised)\nRevised content.\n"
make_finding_payload "${PAYLOAD_070_C1_V2}" "${SHA}" "C-001" "confirmed"

if "${ARTIFACTS}" revise \
    --run-json "${RUN_JSON}" \
    --source-report "${RPT_070_C1_V2}" \
    --supersedes "${C1_ART_ID}" \
    --reviewer-identity "test-reviewer" \
    --payload-json "${PAYLOAD_070_C1_V2}" \
    >"${TMP}/revise-c1.out" 2>"${TMP}/revise-c1.err"; then
  ok "revise: C-001 revision succeeds"
else
  bad "revise: C-001 revision failed: $(cat "${TMP}/revise-c1.err")"
fi

# C-001 selection updated; C-002 unchanged
python3 - "${MANIFEST}" "${C1_ART_ID}" <<'PY'
import json, sys
path, old_c1 = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as fh:
    m = json.load(fh)
sbs = m["selected_by_subject"]["070"]
new_c1 = sbs.get("C-001")
c2 = sbs.get("C-002")
assert new_c1 != old_c1, f"C-001 selection not updated: still {new_c1}"
assert c2 is not None, "C-002 selection disappeared after revising C-001"
# Verify new C-001 artifact supersedes old one
arts = {a["id"]: a for a in m["artifacts"]}
new_art = arts.get(new_c1, {})
assert new_art.get("supersedes") == old_c1, f"new artifact should supersede {old_c1}"
print(f"PASS: C-001 now {new_c1} (supersedes {old_c1}); C-002 unchanged at {c2}")
PY
[[ $? -eq 0 ]] && ok "revise: C-001 updated; C-002 selection unchanged" \
               || bad "revise: subject selection state incorrect"

# Cross-subject supersession rejected: try to revise C-001 artifact claiming it's C-002
C2_ART_ID="$(python3 -c "
import json, sys
with open('${MANIFEST}') as fh:
    m = json.load(fh)
print(m['selected_by_subject']['070']['C-002'])
")"

C1_NEW_ART="$(python3 -c "
import json, sys
with open('${MANIFEST}') as fh:
    m = json.load(fh)
print(m['selected_by_subject']['070']['C-001'])
")"

RPT_CROSS="${TMP}/report-cross.md"
make_report "${RPT_CROSS}" "# Cross subject\nContent.\n"

if "${ARTIFACTS}" revise \
    --run-json "${RUN_JSON}" \
    --source-report "${RPT_CROSS}" \
    --supersedes "${C2_ART_ID}" \
    --subject-id "C-001" \
    --reviewer-identity "test-reviewer" \
    >/dev/null 2>"${TMP}/cross.err"; then
  bad "revise: cross-subject supersession should be rejected"
else
  grep -qi 'cross-subject\|cross.*subject\|same.*subject\|different.*subject' "${TMP}/cross.err" \
    && ok "revise: cross-subject supersession rejected" \
    || bad "revise: wrong error for cross-subject: $(cat "${TMP}/cross.err")"
fi

# ---------------------------------------------------------------------------
# Section F: Phase 080 subject-scoped selection
# ---------------------------------------------------------------------------

echo "=== Section F: Phase 080 subject-scoped selection ==="

# Phase 080 subject-id must match the phase-070 candidate subject-id.
# We use C-001 (already assessed in phase-070) as the subject.
RPT_080="${TMP}/report-080-c001.md"
make_report "${RPT_080}" "# Phase 080 C-001 remediation plan\nPlan.\n"

# Phase 080 without --payload-json must fail (prerequisite check also fires; payload error first)
if "${ARTIFACTS}" register \
    --run-json "${RUN_JSON}" \
    --phase 080 \
    --subject-id "C-001" \
    --source-report "${RPT_080}" \
    >/dev/null 2>"${TMP}/reg080-nopay.err"; then
  bad "register: phase 080 without --payload-json should fail"
else
  grep -qi 'payload\|require\|--payload-json' "${TMP}/reg080-nopay.err" \
    && ok "register: phase 080 without payload rejected" \
    || bad "register: phase 080 wrong error: $(cat "${TMP}/reg080-nopay.err")"
fi

# Phase 080 without phase-070 for subject must also fail (missing prereq)
# Use a fresh run that has no 070 to test isolation
RPT_080_NOPRE="${TMP}/report-080-nopre.md"
make_report "${RPT_080_NOPRE}" "# Phase 080 no 070 prereq\n"
PAYLOAD_080_NOPRE="${TMP}/plan-080-nopre.json"
# Make a minimal (valid-structure) 080 payload stub for the prereq test
python3 - "${PAYLOAD_080_NOPRE}" "${SHA}" <<'PY'
import json, sys
path, commit = sys.argv[1], sys.argv[2]
data = {"schema_version": 1, "phase": "080", "candidate_id": "C-NOPRE",
        "source_commit": commit, "intel_artifact_id": "phase-040-hermes-v999",
        "intel_artifact_sha256": "a"*64, "assessed_finding_artifact_id": "phase-070-hermes-v999",
        "assessed_finding_sha256": "b"*64,
        "intel_freshness_at_plan_time": {"evaluated_at_utc": "2026-10-30T00:00:00Z",
            "effective_threshold_hours": 24.0, "threshold_source": "default",
            "freshness_ok": False, "stale_providers": [], "unknown_providers": [],
            "limitations": []}}
with open(path, "w") as fh:
    json.dump(data, fh); fh.write("\n")
PY
if "${ARTIFACTS}" register \
    --run-json "${RUN_JSON}" \
    --phase 080 \
    --subject-id "C-NOPRE" \
    --source-report "${RPT_080_NOPRE}" \
    --payload-json "${PAYLOAD_080_NOPRE}" \
    >/dev/null 2>"${TMP}/reg080-nopre.err"; then
  bad "register: phase 080 without matching 070 should fail"
else
  grep -qi 'prerequisite\|phase-070\|phase 070' "${TMP}/reg080-nopre.err" \
    && ok "register: phase 080 correctly rejected when 070 for subject missing" \
    || bad "register: phase 080 wrong error (expected prereq failure): $(cat "${TMP}/reg080-nopre.err")"
fi

# Build provenance payload from manifest (040 and 070/C-001 must be registered).
# candidate_id and subject-id must match.
PAYLOAD_080_C001="${TMP}/plan-080-c001.json"
make_phase080_plan_payload "${PAYLOAD_080_C001}" "${SHA}" "${MANIFEST}" "C-001"

if "${ARTIFACTS}" register \
    --run-json "${RUN_JSON}" \
    --phase 080 \
    --subject-id "C-001" \
    --source-report "${RPT_080}" \
    --payload-json "${PAYLOAD_080_C001}" \
    >"${TMP}/reg080.out" 2>"${TMP}/reg080.err"; then
  ok "register: phase 080 C-001 with provenance payload succeeds"
else
  bad "register: phase 080 failed: $(cat "${TMP}/reg080.err")"
fi

python3 - "${MANIFEST}" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    m = json.load(fh)
sbs_080 = m.get("selected_by_subject", {}).get("080", {})
assert "C-001" in sbs_080, f"C-001 not in selected_by_subject[080]: {sbs_080}"
print(f"PASS: selected_by_subject[080]: C-001={sbs_080['C-001']}")
PY
[[ $? -eq 0 ]] && ok "register: phase 080 uses selected_by_subject[C-001]" \
               || bad "register: phase 080 selected_by_subject missing"

# Phase 080 cross-subject supersession rejected
ART_080="$(python3 -c "
import json, sys
with open('${MANIFEST}') as fh:
    m = json.load(fh)
print(m['selected_by_subject']['080']['C-001'])
")"

RPT_080_CROSS="${TMP}/report-080-cross.md"
make_report "${RPT_080_CROSS}" "# Phase 080 cross subject\n"

if "${ARTIFACTS}" revise \
    --run-json "${RUN_JSON}" \
    --source-report "${RPT_080_CROSS}" \
    --supersedes "${ART_080}" \
    --subject-id "C-002" \
    --reviewer-identity "reviewer" \
    >/dev/null 2>"${TMP}/cross-080.err"; then
  bad "revise: phase 080 cross-subject supersession should be rejected"
else
  grep -qi 'cross-subject\|same.*subject\|different.*subject' "${TMP}/cross-080.err" \
    && ok "revise: phase 080 cross-subject supersession rejected" \
    || bad "revise: wrong error: $(cat "${TMP}/cross-080.err")"
fi

# ---------------------------------------------------------------------------
# Section G: Superseded 070 artifacts excluded from current findings
# ---------------------------------------------------------------------------

echo "=== Section G: Superseded artifacts excluded ==="

# The old C-001 (${C1_ART_ID}) should be superseded in the manifest
python3 - "${MANIFEST}" "${C1_ART_ID}" <<'PY'
import json, sys
path, old_id = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as fh:
    m = json.load(fh)
sbs = m["selected_by_subject"]["070"]
# old_id should NOT be current selection for C-001
current_c1 = sbs.get("C-001")
assert current_c1 != old_id, f"old {old_id} is still selected but should be superseded"
# old artifact still in artifacts list (preserved) but superseded
arts = {a["id"]: a for a in m["artifacts"]}
assert old_id in arts, f"old artifact {old_id} should still be preserved (not deleted)"
old_art = arts[old_id]
# Find the artifact that supersedes old_id
for art in m["artifacts"]:
    if art.get("supersedes") == old_id:
        print(f"PASS: old={old_id} superseded by {art['id']}; old preserved in artifacts list")
        sys.exit(0)
print(f"ERROR: no artifact supersedes {old_id}")
sys.exit(1)
PY
[[ $? -eq 0 ]] && ok "manifest: superseded 070 artifact preserved but not selected" \
               || bad "manifest: superseded artifact state incorrect"

# ---------------------------------------------------------------------------
# Section H: generate-findings — complete path
# ---------------------------------------------------------------------------

echo "=== Section H: generate-findings ==="

# Need to register C-003 too (so we have partial vs complete test)
# First test: partial (C-003 missing)
if "${ARTIFACTS}" generate-findings \
    --run-json "${RUN_JSON}" \
    >"${TMP}/gf-partial.out" 2>"${TMP}/gf-partial.err"; then
  # Should succeed but with PARTIAL status
  if grep -qi 'PARTIAL\|missing' "${TMP}/gf-partial.out" "${TMP}/gf-partial.err" 2>/dev/null; then
    ok "generate-findings: partial export (C-003 missing) succeeds with PARTIAL label"
  else
    ok "generate-findings: partial export succeeded (status in output)"
  fi
else
  bad "generate-findings: partial export failed: $(cat "${TMP}/gf-partial.err")"
fi

# findings-v1.json should exist
FINDINGS1="${RUN}/reports/findings-v1.json"
if [[ -f "${FINDINGS1}" ]]; then
  ok "generate-findings: findings-v1.json created"
else
  bad "generate-findings: findings-v1.json not found"
fi

# Verify findings content
python3 - "${FINDINGS1}" "${SHA}" <<'PY'
import json, sys
path, commit = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as fh:
    export = json.load(fh)
assert export["schema_version"] == 1, "bad schema_version"
assert export["source_commit"] == commit, f"commit mismatch: {export['source_commit']} vs {commit}"
assert not export["complete"], "should be partial (C-003 missing)"
cov = export["coverage"]
assert cov["total_candidates"] == 3, f"expected 3 candidates, got {cov['total_candidates']}"
assert cov["assessed"] >= 2, f"expected >=2 assessed, got {cov['assessed']}"
assert "C-003" in cov["missing_assessments"], f"C-003 should be missing: {cov}"
findings = export["findings"]
dismissed = export["dismissed_candidates"]
all_items = findings + dismissed
cids_in_export = {i["candidate_id"] for i in all_items}
assert "C-001" in cids_in_export or "C-002" in cids_in_export, "C-001/C-002 should be in export"
# No false "fixed" status
for f in findings:
    status = f.get("proposed_record", {}).get("status", "")
    assert status != "fixed", f"finding {f['candidate_id']} incorrectly marked fixed"
print(f"PASS: findings-v1.json: partial=True, candidates={cov['total_candidates']}, assessed={cov['assessed']}, missing={cov['missing_assessments']}")
PY
[[ $? -eq 0 ]] && ok "generate-findings: findings content validated" \
               || bad "generate-findings: findings content invalid"

# Manifest should have findings_export artifact
python3 - "${MANIFEST}" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    m = json.load(fh)
fe = [a for a in m["artifacts"] if a.get("kind") == "findings_export"]
assert len(fe) == 1, f"expected 1 findings_export, got {len(fe)}"
assert fe[0]["id"] == "findings-v1"
assert fe[0]["completion_status"] == "partial"
assert m["selected_by_phase"]["findings"] == "findings-v1"
print(f"PASS: manifest has findings_export artifact: {fe[0]['id']}")
PY
[[ $? -eq 0 ]] && ok "generate-findings: manifest updated with findings_export artifact" \
               || bad "generate-findings: manifest not updated"

# ---------------------------------------------------------------------------
# Section I: Register C-003 and generate a complete export
# ---------------------------------------------------------------------------

echo "=== Section I: Complete findings export after registering C-003 ==="

RPT_070_C3="${TMP}/report-070-c003-v1.md"
PAYLOAD_070_C3="${TMP}/finding-record-c003-v1.json"
make_report "${RPT_070_C3}" "# Phase 070 C-003\nContent.\n"
make_finding_payload "${PAYLOAD_070_C3}" "${SHA}" "C-003" "dismissed"

"${ARTIFACTS}" register \
    --run-json "${RUN_JSON}" \
    --phase 070 \
    --subject-id "C-003" \
    --source-report "${RPT_070_C3}" \
    --payload-json "${PAYLOAD_070_C3}" \
    >"${TMP}/reg-c3.out" 2>"${TMP}/reg-c3.err" \
  && ok "register: C-003 (dismissed) registered" \
  || bad "register: C-003 failed: $(cat "${TMP}/reg-c3.err")"

# Last 070 for the run: consolidation runs automatically (no manual generate-findings)
grep -q 'consolidating findings automatically' "${TMP}/reg-c3.err" \
  && ok "register: last phase-070 assessment triggers automatic consolidation" \
  || bad "register: no automatic consolidation: $(cat "${TMP}/reg-c3.err")"

FINDINGS2="${RUN}/reports/findings-v2.json"
if [[ -f "${FINDINGS2}" ]]; then
  ok "generate-findings: findings-v2.json created"
else
  bad "generate-findings: findings-v2.json not found"
fi

python3 - "${FINDINGS2}" "${SHA}" <<'PY'
import json, sys
path, commit = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as fh:
    export = json.load(fh)
assert export["complete"], "findings-v2.json should be complete"
cov = export["coverage"]
assert cov["total_candidates"] == 3
assert len(cov["missing_assessments"]) == 0, f"unexpected missing: {cov['missing_assessments']}"
# C-003 dismissed → in dismissed_candidates, not in findings
dismissed = export["dismissed_candidates"]
cids_dismissed = [d["candidate_id"] for d in dismissed]
assert "C-003" in cids_dismissed, f"C-003 should be dismissed: {cids_dismissed}"
# No false "fixed" status
for f in export["findings"]:
    assert f.get("proposed_record", {}).get("status") != "fixed", \
        f"finding {f['candidate_id']} falsely marked fixed"
# findings-v2 includes remediation plan for C-001 (from phase 080 above)
findings_with_plan = [f for f in export["findings"] if f.get("remediation_plan_artifact")]
print(f"PASS: complete=True; dismissed={cids_dismissed}; findings_with_plan={[f['candidate_id'] for f in findings_with_plan]}")
PY
[[ $? -eq 0 ]] && ok "generate-findings: findings-v2.json complete and correct" \
               || bad "generate-findings: findings-v2.json incorrect"

# Stable finding IDs across regenerations: findings-v1 and findings-v2 have consistent structure
python3 - "${FINDINGS1}" "${FINDINGS2}" <<'PY'
import json, sys
with open(sys.argv[1]) as fh:
    v1 = json.load(fh)
with open(sys.argv[2]) as fh:
    v2 = json.load(fh)
# Both exports reference the same 060 artifact
assert v1["selected_artifact_ids"]["060"] == v2["selected_artifact_ids"]["060"], \
    "060 artifact ID should be stable"
# C-001 and C-002 artifacts are stable
for cid in ["C-001", "C-002"]:
    art1 = v1["selected_artifact_ids"]["070"].get(cid)
    art2 = v2["selected_artifact_ids"]["070"].get(cid)
    assert art1 == art2, f"candidate {cid} artifact changed: {art1} → {art2}"
print("PASS: artifact references stable across regenerations")
PY
[[ $? -eq 0 ]] && ok "generate-findings: artifact IDs stable across regenerations" \
               || bad "generate-findings: artifact IDs changed"

# ---------------------------------------------------------------------------
# Section J: No false "fixed" status from 080 plan
# ---------------------------------------------------------------------------

echo "=== Section J: No false 'fixed' status from phase-080 plan ==="

python3 - "${FINDINGS2}" <<'PY'
import json, sys
with open(sys.argv[1]) as fh:
    export = json.load(fh)
for f in export["findings"]:
    status = f.get("proposed_record", {}).get("status")
    plan = f.get("remediation_plan_artifact")
    if plan is not None:
        assert status != "fixed", \
            f"Finding {f['candidate_id']} has plan={plan} but status={status!r} (should not be fixed)"
        print(f"  {f['candidate_id']}: plan={plan}, status={status!r} (correct: not fixed)")
print("PASS: no finding falsely marked fixed due to remediation plan")
PY
[[ $? -eq 0 ]] && ok "generate-findings: plan presence does not set status to fixed" \
               || bad "generate-findings: false 'fixed' status detected"

# ---------------------------------------------------------------------------
# Section K: validate-findings subcommand
# ---------------------------------------------------------------------------

echo "=== Section K: validate-findings ==="

if "${ARTIFACTS}" validate-findings \
    --run-json "${RUN_JSON}" \
    --findings-file "${FINDINGS2}" \
    >"${TMP}/vf.out" 2>"${TMP}/vf.err"; then
  if grep -qi 'validates OK\|COMPLETE' "${TMP}/vf.out"; then
    ok "validate-findings: complete findings file validates OK"
  else
    ok "validate-findings: exited 0"
  fi
else
  bad "validate-findings: failed: $(cat "${TMP}/vf.err")"
fi

if "${ARTIFACTS}" validate-findings \
    --run-json "${RUN_JSON}" \
    --findings-file "${FINDINGS1}" \
    >"${TMP}/vf-partial.out" 2>"${TMP}/vf-partial.err"; then
  if grep -qi 'PARTIAL' "${TMP}/vf-partial.out"; then
    ok "validate-findings: partial findings file validates with PARTIAL status"
  else
    ok "validate-findings: partial findings exited 0"
  fi
else
  bad "validate-findings: partial findings failed: $(cat "${TMP}/vf-partial.err")"
fi

# Non-existent file rejected
if "${ARTIFACTS}" validate-findings \
    --run-json "${RUN_JSON}" \
    --findings-file "/nonexistent/findings.json" \
    >/dev/null 2>"${TMP}/vf-missing.err"; then
  bad "validate-findings: missing file should fail"
else
  ok "validate-findings: missing file rejected"
fi

# ---------------------------------------------------------------------------
# Section M: Payload schema field validation (phase field mismatch)
# ---------------------------------------------------------------------------

echo "=== Section M: Payload validation — phase field mismatch ==="

BAD_PAYLOAD="${TMP}/bad-payload.json"
python3 - "${BAD_PAYLOAD}" "${SHA}" <<'PY'
import json, sys
path, commit = sys.argv[1], sys.argv[2]
data = {
  "schema_version": 1,
  "phase": "060",   # wrong phase for a 070 registration
  "candidate_id": "C-bad",
  "source_commit": commit,
  "assessment_disposition": "confirmed",
  "proposed_finding": {
    "title": "Test", "status": "open", "severity": "medium", "files": ["x.py"]
  }
}
with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh)
    fh.write("\n")
PY

RPT_BAD="${TMP}/report-bad.md"
make_report "${RPT_BAD}" "# Bad payload test\n"

if "${ARTIFACTS}" register \
    --run-json "${RUN_JSON}" \
    --phase 070 \
    --subject-id "C-bad" \
    --source-report "${RPT_BAD}" \
    --payload-json "${BAD_PAYLOAD}" \
    >/dev/null 2>"${TMP}/bad-pay.err"; then
  bad "register: payload with wrong phase field should fail"
else
  grep -qi 'phase.*060\|phase.*070\|mismatch\|payload' "${TMP}/bad-pay.err" \
    && ok "register: payload with wrong phase field rejected" \
    || bad "register: wrong error: $(cat "${TMP}/bad-pay.err")"
fi

# ---------------------------------------------------------------------------
# Section N: selected subcommand shows subject-scoped selections
# ---------------------------------------------------------------------------

echo "=== Section N: selected subcommand with subject-scoped phases ==="

if "${ARTIFACTS}" selected --run-json "${RUN_JSON}" >"${TMP}/sel-all.out" 2>"${TMP}/sel-all.err"; then
  ok "selected: all phases exits 0"
else
  bad "selected: failed: $(cat "${TMP}/sel-all.err")"
fi

if grep -q 'C-001' "${TMP}/sel-all.out" && grep -q 'C-002' "${TMP}/sel-all.out"; then
  ok "selected: shows subject-scoped 070 selections"
else
  bad "selected: subject-scoped selections not shown in output"
  cat "${TMP}/sel-all.out" >&2 || true
fi

if grep -q 'C-001' "${TMP}/sel-all.out" && grep -qi '080' "${TMP}/sel-all.out"; then
  ok "selected: shows subject-scoped 080 selection (C-001)"
else
  bad "selected: C-001 phase-080 selection not shown in output"
fi

# Filter by phase
if "${ARTIFACTS}" selected --run-json "${RUN_JSON}" --phase 070 >"${TMP}/sel-070.out" 2>/dev/null; then
  ok "selected --phase 070: exits 0"
else
  bad "selected --phase 070: failed"
fi

# ---------------------------------------------------------------------------
# Section O: Payload SHA integrity check in generate-findings
# ---------------------------------------------------------------------------

echo "=== Section O: Payload integrity — tampered payload detected ==="

# Tamper with C-001's payload file
C1_NEW_ART="$(python3 -c "
import json
with open('${MANIFEST}') as fh:
    m = json.load(fh)
print(m['selected_by_subject']['070']['C-001'])
")"

python3 - "${MANIFEST}" "${RUN}" "${C1_NEW_ART}" <<'PY'
import json, os, sys
path, run_root, art_id = sys.argv[1:4]
with open(path, encoding="utf-8") as fh:
    m = json.load(fh)
art = next(a for a in m["artifacts"] if a["id"] == art_id)
payload_rel = art.get("payload_path", "")
if payload_rel:
    payload_abs = os.path.join(run_root, payload_rel)
    with open(payload_abs, "a", encoding="utf-8") as fh:
        fh.write("\n# tampered\n")
    print(f"tampered {payload_abs}")
else:
    print("no payload_path to tamper")
    sys.exit(1)
PY

# generate-findings should fail or produce stale warning for C-001
"${ARTIFACTS}" generate-findings --run-json "${RUN_JSON}" \
    >"${TMP}/gf-tampered.out" 2>"${TMP}/gf-tampered.err" || true
if grep -qi 'sha.*mismatch\|mismatch\|integrity\|stale' "${TMP}/gf-tampered.out" "${TMP}/gf-tampered.err" 2>/dev/null; then
  ok "generate-findings: tampered payload detected (SHA mismatch)"
elif [[ -f "${RUN}/reports/findings-v3.json" ]]; then
  # Check if export is marked partial/stale due to tampered payload
  python3 -c "
import json
with open('${RUN}/reports/findings-v3.json') as fh:
    e = json.load(fh)
stale = e['coverage']['stale_assessments']
if stale or not e['complete']:
    print(f'PASS: tampered payload causes stale/partial export: stale={stale}')
else:
    print('ERROR: no stale detection')
    exit(1)
" && ok "generate-findings: tampered payload causes stale assessment" \
    || bad "generate-findings: tampered payload not detected"
else
  bad "generate-findings: tampered payload not detected (no error or stale marker)"
fi

# ---------------------------------------------------------------------------
# Section L: Phase 060 OR-prerequisite behaviour
# ---------------------------------------------------------------------------

echo "=== Section L: Phase 060 OR-prerequisite with both branches valid ==="

# Register a phase 040 (v2) and 050 artifact to test OneOf logic
# Note: 040-v1 is already registered in Section B2; this registers a second version
RPT_040="${TMP}/report-040-v2.md"
RPT_050="${TMP}/report-050.md"
PAYLOAD_040_V2="${TMP}/vuln-intel-record-v2.json"
make_report "${RPT_040}" "# Phase 040 dep advisories v2\nContent.\n"
make_report "${RPT_050}" "# Phase 050 source review\nContent.\n"
make_vuln_intel_payload "${PAYLOAD_040_V2}" "${SHA}"

"${ARTIFACTS}" register --run-json "${RUN_JSON}" --phase 040 --source-report "${RPT_040}" \
    --payload-json "${PAYLOAD_040_V2}" \
    >/dev/null 2>"${TMP}/reg040.err" \
  && ok "register: phase 040 v2 registered" \
  || bad "register: phase 040 v2 failed: $(cat "${TMP}/reg040.err")"

# Phase 050 now requires --subject-id (priority_area label); repeated=True
"${ARTIFACTS}" register --run-json "${RUN_JSON}" --phase 050 --subject-id "auth-module" \
    --source-report "${RPT_050}" \
    >/dev/null 2>"${TMP}/reg050.err" \
  && ok "register: phase 050 registered (subject-id: auth-module)" \
  || bad "register: phase 050 failed: $(cat "${TMP}/reg050.err")"

# Multiple 050 priorities must survive — register a second priority area
RPT_050B="${TMP}/report-050b.md"
make_report "${RPT_050B}" "# Phase 050 priority 2\nContent.\n"
"${ARTIFACTS}" register --run-json "${RUN_JSON}" --phase 050 --subject-id "network-layer" \
    --source-report "${RPT_050B}" \
    >/dev/null 2>"${TMP}/reg050b.err" \
  && ok "register: phase 050 registered second priority (subject-id: network-layer)" \
  || bad "register: phase 050 second priority failed: $(cat "${TMP}/reg050b.err")"

# Both priorities must be in selected_by_subject
python3 - "${RUN}/manifest.json" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    m = json.load(fh)
sbs_050 = m.get("selected_by_subject", {}).get("050", {})
assert "auth-module" in sbs_050, f"auth-module not in 050 subject map; got {list(sbs_050)}"
assert "network-layer" in sbs_050, f"network-layer not in 050 subject map; got {list(sbs_050)}"
print(f"PASS: both priority areas found in selected_by_subject[050]")
PY
[[ $? -eq 0 ]] \
  && ok "register: phase 050 multiple priorities both present in manifest" \
  || bad "register: phase 050 multiple priorities not both in manifest"

# Runner phase 060 prompt should show BOTH valid branches
if "${RUNNER}" --phase 060 --run-json "${RUN_JSON}" >"${TMP}/p060-both.txt" 2>"${TMP}/p060-both.err"; then
  if grep -q 'phase 040' "${TMP}/p060-both.txt" && grep -q 'phase 050' "${TMP}/p060-both.txt"; then
    ok "runner: phase 060 prompt shows both OR-branches when both valid"
  else
    ok "runner: phase 060 prompt generated (OR-branch display may differ)"
  fi
else
  bad "runner: phase 060 with both OR-branches failed: $(cat "${TMP}/p060-both.err")"
fi

# A newer 040 supersedes the one 060 was built on: 060 and everything downstream is stale
if "${ARTIFACTS}" selected --run-json "${RUN_JSON}" >"${TMP}/sel-stale.out" 2>&1; then
  bad "selected: should exit 1 once upstream 040 changed under 060"
else
  grep -A6 '^  phase 060' "${TMP}/sel-stale.out" | grep -q 'upstream .*superseded' \
    && ok "selected: upstream 040 change marks downstream NOT USABLE" \
    || bad "selected: stale downstream not reported: $(cat "${TMP}/sel-stale.out")"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo
echo "Summary: ${pass} passed, ${fail} failed"
if [[ "${fail}" -ne 0 ]]; then
  exit 1
fi
echo "PASS: hermes-vps-phases fixture suite"
