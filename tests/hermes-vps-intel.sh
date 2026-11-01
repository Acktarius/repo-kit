#!/usr/bin/env bash
# Fixture-based tests for hermes-vps-collect-intel and the hermes_vps_intel library.
# No live network calls. All API responses come from fixture files.
# Controlled clock via provider retrieved_at_utc in fixture files.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXT="${ROOT}/extensions/hermesVPS"
COLLECT="${EXT}/bin/hermes-vps-collect-intel"
ARTIFACTS="${EXT}/bin/hermes-vps-artifacts"
LIB="${EXT}/lib"
# Library imports below come straight from the source tree; never leave bytecode there.
export PYTHONDONTWRITEBYTECODE=1

# Reports get the runner's identity header (execution-input snapshot) just before
# registration, as an agent does at phase start; see tests/hermes_vps_stamp.py.
REAL_ARTIFACTS="${ARTIFACTS}"
artifacts_stamped() {
  PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT}/tests/hermes_vps_stamp.py" "${EXT}/bin/hermes-vps-review" "$@"
  "${REAL_ARTIFACTS}" "$@"
}
ARTIFACTS=artifacts_stamped

TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

fail=0
pass=0

ok()  { pass=$((pass + 1)); echo "PASS: $*"; }
bad() { fail=$((fail + 1)); echo "FAIL: $*" >&2; }

[[ -x "${COLLECT}" ]] || { echo "FAIL: collect-intel not executable" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Fixture layout
# ---------------------------------------------------------------------------
FX="${TMP}/fixtures"
mkdir -p "${FX}"

# Setup: a minimal run.json for testing
SRC="${TMP}/src-repo"
RUN="${TMP}/review-runs/run-intel"
mkdir -p "${SRC}" "${RUN}/reports"

git -C "${SRC}" init -q
git -C "${SRC}" config user.email "t@test.com"
git -C "${SRC}" config user.name "Test"
echo "x" >"${SRC}/README.md"
git -C "${SRC}" add README.md
git -C "${SRC}" commit -q -m "init"
SHA="$(git -C "${SRC}" rev-parse HEAD)"

POLICY="${TMP}/policy"
mkdir -p "${POLICY}/rules" "${POLICY}/templates" "${POLICY}/tasks" "${POLICY}/bin"
cp -a "${EXT}/." "${POLICY}/"
find "${POLICY}" -type d -name '__pycache__' -prune -exec rm -rf {} +

RUN_JSON="${RUN}/run.json"
python3 - "${RUN_JSON}" "${POLICY}" "${SRC}" "${RUN}" "${SHA}" <<'PY'
import json, sys
out, policy, src, run_root, commit = sys.argv[1:6]
data = {
  "schema_version": 1, "run_id": "run-intel",
  "policy_prefix": policy,
  "source": {"path": src, "identity": "fixture/intel-repo", "commit": commit, "require_clean_worktree": True},
  "output": {"run_root": run_root},
  "phase_request": {"phase": "010", "phase_name": "inventory", "requested_by": "test", "requested_at_utc": "2026-10-30T00:00:00Z"},
  "prerequisites": {"artifacts": []},
  "boundaries": {"claims_os_readonly_source": False, "allowed_write_roots": [run_root]},
  "toolkit": {"toolkit_revision": "testrev", "toolkit_dirty": False},
}
with open(out, "w") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
PY

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

PACKAGES_JSON="${TMP}/packages.json"
python3 -c "
import json
pkgs = [
  {'ecosystem': 'PyPI', 'name': 'requests', 'version': '2.28.0'},
  {'ecosystem': 'npm', 'name': 'lodash', 'version': '4.17.20'},
  {'ecosystem': 'PyPI', 'name': 'no-match-pkg', 'version': '1.0.0'},
]
print(json.dumps(pkgs))
" >"${PACKAGES_JSON}"

NOW="2026-10-30T12:00:00Z"   # controlled clock for freshness tests
STALE_TS="2026-10-29T10:00:00Z"  # 26h ago → stale against 24h threshold
FRESH_TS="2026-10-30T11:00:00Z"  # 1h ago → fresh

# OSV querybatch fixture: requests and lodash match, no-match-pkg does not
cat >"${FX}/osv-querybatch.json" <<'EOF'
{
  "results": [
    { "vulns": [{ "id": "GHSA-j8r2-6x86-q33q" }] },
    { "vulns": [{ "id": "GHSA-jf85-cpcp-j695" }] },
    { "vulns": [] }
  ]
}
EOF

# Full OSV advisory for requests vuln
python3 -c "
import json
adv = {
  'id': 'GHSA-j8r2-6x86-q33q',
  'aliases': ['CVE-2023-32681'],
  'summary': 'Unintended leak of proxy credentials',
  'published': '2023-05-22T00:00:00Z',
  'modified': '2023-10-10T00:00:00Z',
  'affected': [{
    'package': {'ecosystem': 'PyPI', 'name': 'requests'},
    'ranges': [{'type': 'SEMVER', 'events': [{'introduced': '0'}, {'fixed': '2.31.0'}]}]
  }],
  'severity': [{'type': 'CVSS_V3', 'score': '6.1'}],
}
print(json.dumps(adv))
" >"${FX}/osv-vuln-GHSA-j8r2-6x86-q33q.json"

# Full OSV advisory for lodash vuln (KEV member)
python3 -c "
import json
adv = {
  'id': 'GHSA-jf85-cpcp-j695',
  'aliases': ['CVE-2021-23337'],
  'summary': 'Command injection in lodash',
  'published': '2021-02-15T00:00:00Z',
  'modified': '2021-09-07T00:00:00Z',
  'affected': [{
    'package': {'ecosystem': 'npm', 'name': 'lodash'},
    'ranges': [{'type': 'SEMVER', 'events': [{'introduced': '0'}, {'fixed': '4.17.21'}]}]
  }],
  'severity': [{'type': 'CVSS_V3', 'score': '7.2'}],
}
print(json.dumps(adv))
" >"${FX}/osv-vuln-GHSA-jf85-cpcp-j695.json"

# NVD fixture for CVE-2023-32681
python3 -c "
import json
d = {
  'vulnerabilities': [{
    'cve': {
      'id': 'CVE-2023-32681',
      'descriptions': [{'lang': 'en', 'value': 'Requests proxy credential leak'}],
      'metrics': {'cvssMetricV31': [{'cvssData': {'baseScore': 6.1, 'baseSeverity': 'MEDIUM'}}]},
      'published': '2023-05-22T00:00:00Z',
      'lastModified': '2023-10-10T00:00:00Z',
    }
  }]
}
print(json.dumps(d))
" >"${FX}/nvd-cve-CVE-2023-32681.json"

# NVD fixture for CVE-2021-23337
python3 -c "
import json
d = {
  'vulnerabilities': [{
    'cve': {
      'id': 'CVE-2021-23337',
      'descriptions': [{'lang': 'en', 'value': 'Lodash command injection'}],
      'metrics': {'cvssMetricV31': [{'cvssData': {'baseScore': 7.2, 'baseSeverity': 'HIGH'}}]},
      'published': '2021-02-15T00:00:00Z',
      'lastModified': '2021-09-07T00:00:00Z',
    }
  }]
}
print(json.dumps(d))
" >"${FX}/nvd-cve-CVE-2021-23337.json"

# CISA KEV fixture — CVE-2021-23337 is in KEV
python3 -c "
import json
d = {
  'title': 'CISA Known Exploited Vulnerabilities Catalog',
  'catalogVersion': '2024.01.01',
  'dateReleased': '2024-01-01T00:00:00Z',
  'count': 1,
  'vulnerabilities': [{
    'cveID': 'CVE-2021-23337',
    'vendorProject': 'lodash',
    'product': 'lodash',
    'vulnerabilityName': 'Lodash command injection',
    'dateAdded': '2021-09-07',
    'shortDescription': 'Command injection',
    'requiredAction': 'Apply patch',
    'dueDate': '2022-03-07',
    'knownRansomwareCampaignUse': 'Unknown',
  }]
}
print(json.dumps(d))
" >"${FX}/kev-feed.json"

# ---------------------------------------------------------------------------
# Section A: collect-intel basic invocation
# ---------------------------------------------------------------------------

echo "=== Section A: collect-intel basic invocation ==="

OUTPUT_LIVE="${TMP}/intel-live.json"
if "${COLLECT}" \
    --run-json "${RUN_JSON}" \
    --output "${OUTPUT_LIVE}" \
    --mode live \
    --packages-json "${PACKAGES_JSON}" \
    --fixture-dir "${FX}" \
    >"${TMP}/A-out.txt" 2>"${TMP}/A-err.txt"; then
  ok "collect-intel: live mode with fixtures exits 0"
else
  bad "collect-intel: live mode failed: $(cat "${TMP}/A-err.txt")"
fi

[[ -f "${OUTPUT_LIVE}" ]] && ok "collect-intel: output file created" \
                           || bad "collect-intel: output file missing"

# ---------------------------------------------------------------------------
# Section B: OSV match, NVD enrichment, alias deduplication
# ---------------------------------------------------------------------------

echo "=== Section B: OSV match, NVD enrichment, KEV membership ==="

python3 - "${OUTPUT_LIVE}" "${SHA}" <<'PY'
import json, sys
path, commit = sys.argv[1], sys.argv[2]
with open(path) as fh:
    rec = json.load(fh)

# Basic structure
assert rec["schema_version"] == 1
assert rec["phase"] == "040"
assert rec["source_commit"] == commit
assert rec["collection_mode"] == "live"
assert "collected_at_utc" in rec
assert "providers" in rec

# OSV matches found
assert rec["providers"]["osv"]["status"] in ("success",), f"OSV status: {rec['providers']['osv']['status']}"
assert len(rec["providers"]["osv"]["advisory_ids_returned"]) >= 2, \
    f"expected >=2 advisory IDs, got {rec['providers']['osv']['advisory_ids_returned']}"

# Matches present
assert len(rec["matches"]) >= 2, f"expected >=2 matches, got {len(rec['matches'])}"
match_ids = set()
for m in rec["matches"]:
    for aid in m["advisory_ids"] + m.get("aliases", []):
        match_ids.add(aid)
assert "CVE-2023-32681" in match_ids, f"CVE-2023-32681 not in match IDs: {match_ids}"
assert "CVE-2021-23337" in match_ids, f"CVE-2021-23337 not in match IDs: {match_ids}"

# Alias deduplication: GHSA and CVE should be in same match entry, not duplicated
osv_matches = [m for m in rec["matches"] if "CVE-2023-32681" in m["advisory_ids"] + m.get("aliases", [])]
assert len(osv_matches) == 1, f"expected 1 match for CVE-2023-32681, got {len(osv_matches)}"
all_ids = osv_matches[0]["advisory_ids"] + osv_matches[0].get("aliases", [])
assert "GHSA-j8r2-6x86-q33q" in all_ids, f"GHSA ID not in aliases: {all_ids}"
assert "CVE-2023-32681" in all_ids, f"CVE alias not in aliases: {all_ids}"
print("PASS: OSV match with CVE alias preserved in same match entry")

# NVD enrichment
nvd_stat = rec["providers"]["nvd"]["status"]
assert nvd_stat in ("success", "partial"), f"NVD status: {nvd_stat}"
enriched = rec["providers"]["nvd"]["cves_enriched"]
enriched_ids = [e["cve_id"] for e in enriched]
assert "CVE-2023-32681" in enriched_ids, f"CVE-2023-32681 not enriched: {enriched_ids}"
print(f"PASS: NVD enriched {len(enriched)} CVEs")

# Severity updated from NVD
requests_match = [m for m in rec["matches"] if "CVE-2023-32681" in m["advisory_ids"] + m.get("aliases", [])][0]
assert requests_match["severity"] == "medium", f"severity expected medium, got {requests_match['severity']}"

# CISA KEV membership
kev_stat = rec["providers"]["cisa_kev"]["status"]
assert kev_stat == "success", f"KEV status: {kev_stat}"
lodash_match = [m for m in rec["matches"] if "CVE-2021-23337" in m["advisory_ids"] + m.get("aliases", [])][0]
assert lodash_match["kev_membership"] is True, "lodash not marked KEV member"
print("PASS: KEV membership correctly set for CVE-2021-23337")

# No match packages
no_match_pkgs = [p["package"] for p in rec["no_match_packages"]]
assert "no-match-pkg" in no_match_pkgs, f"no-match-pkg should be in no_match: {no_match_pkgs}"
print(f"PASS: no-match-pkg in no_match_packages: {no_match_pkgs}")

# Candidate ID suggestions
for m in rec["matches"]:
    assert m.get("candidate_id_suggestion") is not None, "missing candidate_id_suggestion"
print("PASS: all matches have candidate_id_suggestion")

print("PASS: OSV match, NVD enrichment, KEV membership all correct")
PY
[[ $? -eq 0 ]] && ok "intel record: OSV/NVD/KEV integration correct" \
               || bad "intel record: content validation failed"

# ---------------------------------------------------------------------------
# Section C: not-authorized mode
# ---------------------------------------------------------------------------

echo "=== Section C: not-authorized mode ==="

OUTPUT_NA="${TMP}/intel-not-auth.json"
if "${COLLECT}" \
    --run-json "${RUN_JSON}" \
    --output "${OUTPUT_NA}" \
    --mode not-authorized \
    >"${TMP}/C-out.txt" 2>"${TMP}/C-err.txt"; then
  ok "collect-intel: not-authorized mode exits 0"
else
  bad "collect-intel: not-authorized mode failed: $(cat "${TMP}/C-err.txt")"
fi

python3 - "${OUTPUT_NA}" <<'PY'
import json, sys
with open(sys.argv[1]) as fh:
    rec = json.load(fh)
assert rec["collection_mode"] == "not_authorized"
for pname in ("osv", "nvd", "cisa_kev"):
    status = rec["providers"][pname]["status"]
    assert status == "not_authorized", f"{pname} status should be not_authorized, got {status!r}"
    ts = rec["providers"][pname].get("retrieved_at_utc")
    assert ts is None, f"{pname} retrieved_at_utc should be None (not_authorized)"
assert len(rec["matches"]) == 0, "not_authorized should have no matches"
print("PASS: not_authorized mode: all providers marked not_authorized, no timestamps, no matches")
PY
[[ $? -eq 0 ]] && ok "not-authorized: correct record structure" \
               || bad "not-authorized: incorrect record"

# ---------------------------------------------------------------------------
# Section D: offline import mode
# ---------------------------------------------------------------------------

echo "=== Section D: offline import mode ==="

OUTPUT_IMP="${TMP}/intel-imported.json"
if "${COLLECT}" \
    --run-json "${RUN_JSON}" \
    --output "${OUTPUT_IMP}" \
    --mode imported \
    --import-evidence "${OUTPUT_LIVE}" \
    >"${TMP}/D-out.txt" 2>"${TMP}/D-err.txt"; then
  ok "collect-intel: imported mode exits 0"
else
  bad "collect-intel: imported mode failed: $(cat "${TMP}/D-err.txt")"
fi

python3 - "${OUTPUT_IMP}" "${OUTPUT_LIVE}" <<'PY'
import json, sys
with open(sys.argv[1]) as fh:
    imp = json.load(fh)
with open(sys.argv[2]) as fh:
    orig = json.load(fh)

assert imp["collection_mode"] == "imported"
assert "imported_at_utc" in imp, "imported_at_utc should be set"

# Provider timestamps MUST NOT be updated — freshness still based on original collection
for pname in ("osv", "nvd", "cisa_kev"):
    orig_ts = orig["providers"][pname].get("retrieved_at_utc")
    imp_ts  = imp["providers"][pname].get("retrieved_at_utc")
    assert orig_ts == imp_ts, \
        f"{pname} retrieved_at_utc changed on import: {orig_ts!r} → {imp_ts!r}"

print("PASS: import mode preserves provider retrieved_at_utc (freshness not refreshed)")
PY
[[ $? -eq 0 ]] && ok "imported mode: provider timestamps preserved" \
               || bad "imported mode: timestamps incorrectly updated"

# Import requires --import-evidence
if "${COLLECT}" \
    --run-json "${RUN_JSON}" \
    --output "${TMP}/imp-fail.json" \
    --mode imported \
    >/dev/null 2>"${TMP}/imp-fail.err"; then
  bad "collect-intel: --mode imported without --import-evidence should fail"
else
  ok "collect-intel: --mode imported without --import-evidence rejected"
fi

# ---------------------------------------------------------------------------
# Section E: freshness assessment — fresh, stale, unknown
# ---------------------------------------------------------------------------

echo "=== Section E: freshness assessment with controlled timestamps ==="

python3 - "${LIB}" "${OUTPUT_LIVE}" "${FRESH_TS}" "${STALE_TS}" "${NOW}" <<'PY'
import sys, json
sys.path.insert(0, sys.argv[1])
from hermes_vps_intel import assess_freshness, FreshnessSource

path = sys.argv[2]
fresh_ts = sys.argv[3]
stale_ts = sys.argv[4]
now = sys.argv[5]

with open(path) as fh:
    rec = json.load(fh)

# Patch timestamps for controlled test
for pname in ("osv", "nvd", "cisa_kev"):
    rec["providers"][pname]["retrieved_at_utc"] = fresh_ts
    rec["providers"][pname]["status"] = "success"

result = assess_freshness(rec, threshold_hours=24.0, at_utc=now)
assert result["ok"] is True, f"expected fresh with {fresh_ts}, now={now}: {result}"
assert len(result["stale_providers"]) == 0
print(f"PASS: fresh evidence (age ~1h): freshness_ok=True")

# Stale: set all providers to old timestamp
for pname in ("osv", "nvd", "cisa_kev"):
    rec["providers"][pname]["retrieved_at_utc"] = stale_ts

result2 = assess_freshness(rec, threshold_hours=24.0, at_utc=now)
assert result2["ok"] is False, "expected stale with old timestamps"
assert len(result2["stale_providers"]) > 0, f"no stale providers reported: {result2}"
print(f"PASS: stale evidence (age ~26h): freshness_ok=False, stale_providers={result2['stale_providers']}")

# Missing timestamp → unknown, not fresh
for pname in ("osv", "nvd", "cisa_kev"):
    rec["providers"][pname]["retrieved_at_utc"] = None
    rec["providers"][pname]["status"] = "success"

result3 = assess_freshness(rec, threshold_hours=24.0, at_utc=now)
assert result3["ok"] is False, "missing timestamps should NOT be treated as fresh"
assert len(result3["unknown_providers"]) > 0, f"no unknown providers: {result3}"
print(f"PASS: missing timestamps: reported as unknown, not fresh: {result3['unknown_providers']}")

# not_authorized → unknown, not fresh
for pname in ("osv", "nvd", "cisa_kev"):
    rec["providers"][pname]["status"] = "not_authorized"
    rec["providers"][pname]["retrieved_at_utc"] = None

result4 = assess_freshness(rec, threshold_hours=24.0, at_utc=now)
assert result4["ok"] is False, "not_authorized should not be treated as fresh"
print(f"PASS: not_authorized providers: freshness_ok=False")
PY
[[ $? -eq 0 ]] && ok "freshness assessment: fresh/stale/unknown/not_authorized correct" \
               || bad "freshness assessment: incorrect behavior"

# ---------------------------------------------------------------------------
# Section F: old evidence reimported does not refresh age
# ---------------------------------------------------------------------------

echo "=== Section F: old evidence reimported does not become fresh ==="

# Create a record with stale timestamps
OLD_RECORD="${TMP}/old-record.json"
python3 - "${OLD_RECORD}" "${SHA}" "${STALE_TS}" "${LIB}" <<'PY'
import sys, json
sys.path.insert(0, sys.argv[4])
from hermes_vps_intel import run_collection, Status

# Build a synthetic stale record
rec = {
  "schema_version": 1,
  "phase": "040",
  "source_commit": sys.argv[2],
  "collection_mode": "live",
  "collected_at_utc": sys.argv[3],
  "freshness_policy_hours": 24.0,
  "providers": {
    "osv": {"status": "success", "endpoint_used": "https://api.osv.dev/v1/querybatch",
            "retrieved_at_utc": sys.argv[3], "response_sha256": "abc", "packages_queried": 1, "advisory_ids_returned": [], "note": None},
    "nvd": {"status": "not_checked", "endpoint_used": "https://services.nvd.nist.gov/rest/json/cves/2.0",
            "retrieved_at_utc": None, "response_sha256": None, "cves_enriched": [], "cves_failed": [], "api_key_used": False, "note": None},
    "cisa_kev": {"status": "success", "endpoint_used": "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
                 "retrieved_at_utc": sys.argv[3], "response_sha256": "def", "catalog_version": "2024.01.01", "kev_count": 1, "matched_cves": [], "note": None}
  },
  "vendor_advisories": [], "matches": [], "no_match_packages": [], "unsupported_ecosystems": [],
  "inventory_gaps": [], "coverage": {"total_packages_checked": 0, "total_matches": 0, "kev_matches": 0, "packages_with_gaps": 0, "baseline_or_refresh": "baseline", "notes": ""}
}
with open(sys.argv[1], "w") as fh:
    json.dump(rec, fh, indent=2)
    fh.write("\n")
PY

# Import the old record
IMPORTED_OLD="${TMP}/imported-old.json"
"${COLLECT}" \
    --run-json "${RUN_JSON}" \
    --output "${IMPORTED_OLD}" \
    --mode imported \
    --import-evidence "${OLD_RECORD}" \
    >/dev/null 2>&1 || true

python3 - "${IMPORTED_OLD}" "${STALE_TS}" "${NOW}" "${LIB}" <<'PY'
import sys, json
sys.path.insert(0, sys.argv[4])
from hermes_vps_intel import assess_freshness

with open(sys.argv[1]) as fh:
    rec = json.load(fh)
stale_ts = sys.argv[2]
now = sys.argv[3]

assert rec["collection_mode"] == "imported"
# imported_at_utc is recent but retrieved_at_utc is old
imp_ts = rec.get("imported_at_utc", "")
assert imp_ts, "imported_at_utc should be set"

# Freshness must use retrieved_at_utc, not imported_at_utc
result = assess_freshness(rec, threshold_hours=24.0, at_utc=now)
assert result["ok"] is False, \
    f"old imported evidence must NOT be fresh: got ok={result['ok']}, limitations={result['limitations']}"
print(f"PASS: old evidence reimported: still stale (age based on original retrieved_at_utc)")
print(f"  imported_at_utc={imp_ts} (recent) vs retrieved_at_utc={stale_ts} (old) → stale={result['stale_providers']}")
PY
[[ $? -eq 0 ]] && ok "import: old evidence age is preserved; import does not refresh" \
               || bad "import: old evidence incorrectly marked fresh after import"

# ---------------------------------------------------------------------------
# Section G: freshness vs. coverage are independent
# ---------------------------------------------------------------------------

echo "=== Section G: freshness and coverage are separate ==="

python3 - "${OUTPUT_LIVE}" "${FRESH_TS}" "${NOW}" "${LIB}" <<'PY'
import sys, json
sys.path.insert(0, sys.argv[4])
from hermes_vps_intel import assess_freshness

with open(sys.argv[1]) as fh:
    rec = json.load(fh)
fresh_ts = sys.argv[2]
now = sys.argv[3]

# OSV is fresh; NVD is partially failed; KEV is fresh
rec["providers"]["osv"]["retrieved_at_utc"] = fresh_ts
rec["providers"]["osv"]["status"] = "success"
rec["providers"]["nvd"]["retrieved_at_utc"] = None
rec["providers"]["nvd"]["status"] = "failed"
rec["providers"]["cisa_kev"]["retrieved_at_utc"] = fresh_ts
rec["providers"]["cisa_kev"]["status"] = "success"

result = assess_freshness(rec, threshold_hours=24.0, at_utc=now)
# OSV + KEV are fresh; NVD failed → unknown → freshness_ok should be False
assert result["ok"] is False, \
    f"freshness should be False when NVD failed (unknown): {result}"
assert "nvd" in result["unknown_providers"], f"nvd not in unknown: {result}"
# But this is NOT the same as saying no coverage exists
# The coverage failures must be reported separately
print(f"PASS: NVD failed → reported as unknown provider; freshness_ok=False independently of matches")
print(f"  stale={result['stale_providers']}, unknown={result['unknown_providers']}")
PY
[[ $? -eq 0 ]] && ok "freshness and coverage: independent assessment" \
               || bad "freshness/coverage: not independently assessed"

# ---------------------------------------------------------------------------
# Section H: failed provider — not silently "no vulnerabilities"
# ---------------------------------------------------------------------------

echo "=== Section H: failed provider status — no silent no-vuln ==="

# Create a fixture where OSV querybatch is missing (simulates failure)
FX_FAIL="${TMP}/fixtures-fail"
mkdir -p "${FX_FAIL}"
# No osv-querybatch.json → OSV collection fails

OUTPUT_FAIL="${TMP}/intel-fail.json"
if "${COLLECT}" \
    --run-json "${RUN_JSON}" \
    --output "${OUTPUT_FAIL}" \
    --mode live \
    --packages-json "${PACKAGES_JSON}" \
    --fixture-dir "${FX_FAIL}" \
    >/dev/null 2>"${TMP}/H-err.txt"; then
  # Should still exit 0 (collection helper writes a record even on provider failure)
  ok "collect-intel: provider failure still produces output (exit 0)"
else
  ok "collect-intel: provider failure exits non-zero (acceptable)"
fi

# Either way, check the output if it exists
if [[ -f "${OUTPUT_FAIL}" ]]; then
  python3 - "${OUTPUT_FAIL}" <<'PY'
import json, sys
with open(sys.argv[1]) as fh:
    rec = json.load(fh)
osv_status = rec["providers"]["osv"]["status"]
assert osv_status in ("failed", "not_checked"), \
    f"OSV status should be failed/not_checked, not 'success': {osv_status}"
# No matches when OSV failed
# (matches may be empty; this is correct)
print(f"PASS: OSV failure → status={osv_status!r}, not silently success with no matches")
PY
  [[ $? -eq 0 ]] && ok "failed provider: status recorded, not silently no-vuln" \
                 || bad "failed provider: incorrect status"
else
  ok "failed provider: no output file (collection exited non-zero with no output)"
fi

# ---------------------------------------------------------------------------
# Section I: no network request without authorization
# ---------------------------------------------------------------------------

echo "=== Section I: no network request in not-authorized mode ==="

# not-authorized mode with no fixture-dir — must not attempt network
OUTPUT_NET="${TMP}/intel-nonet.json"
# We can't reliably detect if network was attempted in sandbox,
# but we can verify the mode is correctly recorded
if "${COLLECT}" \
    --run-json "${RUN_JSON}" \
    --output "${OUTPUT_NET}" \
    --mode not-authorized \
    >/dev/null 2>&1; then
  python3 - "${OUTPUT_NET}" <<'PY'
import json, sys
with open(sys.argv[1]) as fh:
    rec = json.load(fh)
assert rec["collection_mode"] == "not_authorized"
for pname in ("osv", "nvd", "cisa_kev"):
    assert rec["providers"][pname]["status"] == "not_authorized", \
        f"{pname} should be not_authorized"
    assert rec["providers"][pname].get("retrieved_at_utc") is None, \
        f"{pname} should have no timestamp"
print("PASS: not_authorized mode: no provider timestamps, no matches")
PY
  [[ $? -eq 0 ]] && ok "not-authorized: no timestamps, no network activity recorded" \
                 || bad "not-authorized: incorrect record"
else
  bad "collect-intel: not-authorized mode failed"
fi

# ---------------------------------------------------------------------------
# Section J: vuln-intel-record registered as phase-040 payload
# ---------------------------------------------------------------------------

echo "=== Section J: registration as phase-040 payload ==="

# Register baseline phases 010, 020, 030 first (prerequisite chain)
RPT_010="${TMP}/phase-010.md"
printf '# Phase 010\nContent.\nState: `complete`\n' >"${RPT_010}"
"${ARTIFACTS}" register --run-json "${RUN_JSON}" --phase 010 --source-report "${RPT_010}" \
    >/dev/null 2>/dev/null || true

RPT_020J="${TMP}/phase-020j.md"
printf '# Phase 020\nContent.\nState: `complete`\n' >"${RPT_020J}"
"${ARTIFACTS}" register --run-json "${RUN_JSON}" --phase 020 --source-report "${RPT_020J}" \
    >/dev/null 2>/dev/null || true

RPT_030J="${TMP}/phase-030j.md"
printf '# Phase 030\nContent.\nState: `complete`\n' >"${RPT_030J}"
"${ARTIFACTS}" register --run-json "${RUN_JSON}" --phase 030 --source-report "${RPT_030J}" \
    >/dev/null 2>/dev/null || true

RPT_040="${TMP}/phase-040.md"
printf '# Phase 040 with vuln-intel\nContent.\nState: `complete`\n' >"${RPT_040}"

if "${ARTIFACTS}" register \
    --run-json "${RUN_JSON}" \
    --phase 040 \
    --source-report "${RPT_040}" \
    --payload-json "${OUTPUT_LIVE}" \
    >"${TMP}/reg040.out" 2>"${TMP}/reg040.err"; then
  ok "artifacts register: phase 040 with vuln-intel payload succeeds"
else
  bad "artifacts register: phase 040 with payload failed: $(cat "${TMP}/reg040.err")"
fi

MANIFEST="${RUN}/manifest.json"
python3 - "${MANIFEST}" <<'PY'
import json, sys
with open(sys.argv[1]) as fh:
    m = json.load(fh)
arts_040 = [a for a in m["artifacts"] if a.get("phase") == "040"]
assert len(arts_040) == 1, f"expected 1 040 artifact, got {len(arts_040)}"
a = arts_040[0]
assert "payload_path" in a, "missing payload_path"
assert "payload_sha256" in a, "missing payload_sha256"
assert m["selected_by_phase"]["040"] == a["id"]
print(f"PASS: manifest has phase-040 artifact with payload: {a['id']}")
PY
[[ $? -eq 0 ]] && ok "manifest: phase-040 has payload fields" \
               || bad "manifest: phase-040 missing payload fields"

# Phase 040 without --payload-json must fail
RPT_040B="${TMP}/phase-040b.md"
printf '# Phase 040 no payload\nContent.\nState: `complete`\n' >"${RPT_040B}"
if "${ARTIFACTS}" register \
    --run-json "${RUN_JSON}" \
    --phase 040 \
    --source-report "${RPT_040B}" \
    >/dev/null 2>"${TMP}/nopay040.err"; then
  bad "register: phase 040 without --payload-json should fail"
else
  ok "register: phase 040 without payload rejected"
fi

# Phase 040 with wrong collection_mode in payload must fail
# Use the actual commit SHA so cross-commit validation does not fire first.
python3 - "${TMP}/bad-mode-payload.json" "${SHA}" <<'PY'
import json, sys
path, commit = sys.argv[1], sys.argv[2]
bad = {'schema_version': 1, 'phase': '040', 'source_commit': commit,
       'collection_mode': 'BAD_MODE', 'collected_at_utc': '2026-10-30T00:00:00Z',
       'providers': {'osv': {}, 'nvd': {}, 'cisa_kev': {}},
       'vendor_advisories': [], 'matches': [], 'no_match_packages': [],
       'unsupported_ecosystems': [], 'inventory_gaps': [],
       'coverage': {'total_packages_checked': 0, 'total_matches': 0, 'kev_matches': 0},
       'freshness_policy_hours': 24.0}
with open(path, "w") as fh:
    json.dump(bad, fh); fh.write("\n")
PY

RPT_040C="${TMP}/phase-040c.md"
printf '# Phase 040\nContent.\nState: `complete`\n' >"${RPT_040C}"
if "${ARTIFACTS}" register \
    --run-json "${RUN_JSON}" \
    --phase 040 \
    --source-report "${RPT_040C}" \
    --payload-json "${TMP}/bad-mode-payload.json" \
    >/dev/null 2>"${TMP}/badmode.err"; then
  bad "register: phase 040 payload with invalid collection_mode should fail"
else
  grep -qi 'collection_mode\|BAD_MODE\|not in' "${TMP}/badmode.err" \
    && ok "register: invalid collection_mode rejected" \
    || bad "register: wrong error: $(cat "${TMP}/badmode.err")"
fi

# ---------------------------------------------------------------------------
# Section K: generate-findings freshness gate
# ---------------------------------------------------------------------------

echo "=== Section K: generate-findings freshness gate ==="

# Register phases 060, 070 needed for generate-findings
# Use a simple triage payload and finding record
TRIAGE="${TMP}/triage-060.json"
python3 - "${TRIAGE}" "${SHA}" <<'PY'
import json, sys
data = {"schema_version": 1, "phase": "060", "source_commit": sys.argv[2],
        "candidates": [{"candidate_id": "C-001", "title": "Test finding", "disposition": "validated-new"}]}
with open(sys.argv[1], "w") as fh:
    json.dump(data, fh)
    fh.write("\n")
PY
RPT_060="${TMP}/phase-060.md"
printf '# Phase 060\nContent.\nState: `complete`\n' >"${RPT_060}"
"${ARTIFACTS}" register --run-json "${RUN_JSON}" --phase 060 \
    --source-report "${RPT_060}" --payload-json "${TRIAGE}" \
    >/dev/null 2>/dev/null || true

FINDING="${TMP}/finding-070.json"
python3 - "${FINDING}" "${SHA}" <<'PY'
import json, sys
data = {"schema_version": 1, "phase": "070", "candidate_id": "C-001", "source_commit": sys.argv[2],
        "assessment_disposition": "confirmed", "assessment_rationale": "test",
        "affected_components": [], "impact": "test", "likelihood": "medium",
        "evidence": [], "unknowns": [], "blockers": [],
        "proposed_finding": {"title": "Test finding", "status": "open", "severity": "medium", "files": ["x.py"]}}
with open(sys.argv[1], "w") as fh:
    json.dump(data, fh)
    fh.write("\n")
PY
RPT_070="${TMP}/phase-070.md"
printf '# Phase 070\nContent.\nState: `complete`\n' >"${RPT_070}"
"${ARTIFACTS}" register --run-json "${RUN_JSON}" --phase 070 \
    --subject-id C-001 \
    --source-report "${RPT_070}" --payload-json "${FINDING}" \
    >/dev/null 2>/dev/null || true

# Generate findings — should include readiness with intel info
if "${ARTIFACTS}" generate-findings --run-json "${RUN_JSON}" \
    >"${TMP}/gf-out.txt" 2>"${TMP}/gf-err.txt"; then
  ok "generate-findings: exits 0 (with vuln-intel registered)"
else
  bad "generate-findings: failed: $(cat "${TMP}/gf-err.txt")"
fi

# Check findings export has readiness object
FINDINGS_FILE="${RUN}/reports/findings-v1.json"
if [[ -f "${FINDINGS_FILE}" ]]; then
  python3 - "${FINDINGS_FILE}" <<'PY'
import json, sys
with open(sys.argv[1]) as fh:
    exp = json.load(fh)
# Should have readiness object
assert "readiness" in exp, "findings export missing 'readiness' object"
r = exp["readiness"]
assert "intel" in r, "readiness missing 'intel'"
assert "assessment" in r, "readiness missing 'assessment'"
assert "readiness_ok" in r, "readiness missing 'readiness_ok'"
assert "policy_check_failed" in r, "readiness missing 'policy_check_failed'"
assert "limitations" in r, "readiness missing 'limitations'"
intel = r["intel"]
assert "artifact_id" in intel, "readiness.intel missing artifact_id"
assert "freshness" in intel, "readiness.intel missing freshness"
assert "coverage" in intel, "readiness.intel missing coverage"
# intel_freshness_ok in coverage
assert "intel_freshness_ok" in exp["coverage"], "coverage missing intel_freshness_ok"
assert "intel_collected_at_utc" in exp["coverage"], "coverage missing intel_collected_at_utc"
print(f"PASS: readiness object present; intel.artifact_id={intel['artifact_id']!r}")
PY
  [[ $? -eq 0 ]] && ok "generate-findings: readiness object correct" \
                 || bad "generate-findings: readiness object incorrect"
else
  bad "generate-findings: findings file not found"
fi

# Test --require-fresh-intel with stale intel: exit code 2
# Create a stale intel record (collected 26h ago)
STALE_RECORD="${TMP}/stale-intel.json"
python3 - "${STALE_RECORD}" "${SHA}" "${STALE_TS}" <<'PY'
import json, sys
rec = {
  "schema_version": 1, "phase": "040", "source_commit": sys.argv[2],
  "collection_mode": "live",
  "collected_at_utc": sys.argv[3],
  "freshness_policy_hours": 24.0,
  "providers": {
    "osv": {"status": "success", "endpoint_used": "https://api.osv.dev/v1/querybatch",
            "retrieved_at_utc": sys.argv[3], "response_sha256": "abc", "packages_queried": 1, "advisory_ids_returned": [], "note": None},
    "nvd": {"status": "not_checked", "endpoint_used": "https://services.nvd.nist.gov/rest/json/cves/2.0",
            "retrieved_at_utc": None, "response_sha256": None, "cves_enriched": [], "cves_failed": [], "api_key_used": False, "note": None},
    "cisa_kev": {"status": "success", "endpoint_used": "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
                 "retrieved_at_utc": sys.argv[3], "response_sha256": "def", "catalog_version": "2024.01.01", "kev_count": 0, "matched_cves": [], "note": None}
  },
  "vendor_advisories": [], "matches": [], "no_match_packages": [],
  "unsupported_ecosystems": [], "inventory_gaps": [],
  "coverage": {"total_packages_checked": 0, "total_matches": 0, "kev_matches": 0, "packages_with_gaps": 0, "baseline_or_refresh": "baseline", "notes": ""}
}
with open(sys.argv[1], "w") as fh:
    json.dump(rec, fh, indent=2)
    fh.write("\n")
PY

# Revise the 040 artifact with the stale record
RPT_040D="${TMP}/phase-040-stale.md"
printf '# Phase 040 stale\nContent.\nState: `complete`\n' >"${RPT_040D}"
ART040_ID="$(python3 -c "
import json
with open('${MANIFEST}') as fh:
    m = json.load(fh)
print(m['selected_by_phase']['040'])
")"
"${ARTIFACTS}" revise --run-json "${RUN_JSON}" \
    --source-report "${RPT_040D}" \
    --supersedes "${ART040_ID}" \
    --reviewer-identity "tester" \
    --payload-json "${STALE_RECORD}" \
    >/dev/null 2>/dev/null || true

# generate-findings without --require-fresh-intel → exit 0 even with stale intel
GF2_EXIT=0
"${ARTIFACTS}" generate-findings --run-json "${RUN_JSON}" \
    >"${TMP}/gf2-out.txt" 2>"${TMP}/gf2-err.txt" || GF2_EXIT=$?
if [[ "${GF2_EXIT}" -eq 0 ]]; then
  ok "generate-findings: stale intel → exit 0 (no --require-fresh-intel; findings preserved)"
else
  bad "generate-findings: stale intel without --require-fresh-intel should exit 0, got ${GF2_EXIT}"
fi

grep -qi 'stale\|WARNING\|freshness' "${TMP}/gf2-err.txt" \
  && ok "generate-findings: stale intel produces visible warning" \
  || bad "generate-findings: stale intel warning missing"

# generate-findings WITH --require-fresh-intel → exit 2
GF3_EXIT=0
"${ARTIFACTS}" generate-findings --run-json "${RUN_JSON}" \
    --require-fresh-intel \
    >"${TMP}/gf3-out.txt" 2>"${TMP}/gf3-err.txt" || GF3_EXIT=$?
if [[ "${GF3_EXIT}" -eq 2 ]]; then
  ok "generate-findings: --require-fresh-intel with stale intel → exit 2 (policy check)"
else
  bad "generate-findings: expected exit 2, got ${GF3_EXIT}"
fi

grep -qi 'POLICY CHECK FAILED\|policy.*gate\|freshness.*requirement' "${TMP}/gf3-err.txt" \
  && ok "generate-findings: policy failure message printed" \
  || bad "generate-findings: policy failure message missing"

# Export must still be written even when policy check failed
FINDINGS_COUNT="$(ls "${RUN}/reports/findings-v"*.json 2>/dev/null | wc -l)"
[[ "${FINDINGS_COUNT}" -ge 2 ]] \
  && ok "generate-findings: export written even when --require-fresh-intel fails" \
  || bad "generate-findings: export not written on policy failure"

# Check that policy_check_failed is recorded in the latest export
LATEST_FINDINGS="$(ls -t "${RUN}/reports/findings-v"*.json | head -1)"
python3 - "${LATEST_FINDINGS}" <<'PY'
import json, sys
with open(sys.argv[1]) as fh:
    exp = json.load(fh)
r = exp.get("readiness", {})
assert r.get("policy_check_failed") is True, \
    f"policy_check_failed should be True in export: {r.get('policy_check_failed')}"
print("PASS: policy_check_failed=True in findings export readiness")
PY
[[ $? -eq 0 ]] && ok "generate-findings: policy_check_failed recorded in export" \
               || bad "generate-findings: policy_check_failed not in export"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo
echo "Summary: ${pass} passed, ${fail} failed"
if [[ "${fail}" -ne 0 ]]; then
  exit 1
fi
echo "PASS: hermes-vps-intel fixture suite"
