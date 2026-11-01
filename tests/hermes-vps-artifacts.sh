#!/usr/bin/env bash
# Fixture tests for hermesVPS hermes-vps-artifacts helper.
# Tests: register/accept/revise/selected; locking; idempotency; SHA-256; retry.
# Synthetic repos and temporary destinations only. No VPS / network.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXT="${ROOT}/extensions/hermesVPS"
ARTIFACTS="${EXT}/bin/hermes-vps-artifacts"
RUNNER="${EXT}/bin/hermes-vps-review"

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

[[ -x "${ARTIFACTS}" ]] || {
  echo "FAIL: artifacts helper not executable: ${ARTIFACTS}" >&2
  exit 1
}

# --- fixture layout helpers ---
POLICY="${TMP}/policy with spaces/hermes-review"
SRC="${TMP}/repositories/example-repo"
RUN="${TMP}/review-runs/example-repo/run-art"
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
  "run_id": "run-art",
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
  "toolkit": {"toolkit_revision": "deadbeef01", "toolkit_dirty": False},
}
with open(out, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
PY
}

RUN_JSON="${RUN}/run.json"
write_run "${RUN_JSON}" "${POLICY}" "${SRC}" "${RUN}" "${SHA}"

# helper: compute sha256 of a file
sha256() { sha256sum "$1" | awk '{print $1}'; }

# helper: make a report file with given content
make_report() {
  local path="$1" content="${2:-# Phase 010 inventory report\n\nTest content.}"
  printf '%b' "${content}" >"${path}"
  grep -qiE '^[[:space:]-]*(\*\*)?(completion )?state' "${path}" || printf '\nState: `complete`\n' >>"${path}"
}

# ============================================================
# Payload check: new files exist
# ============================================================
for rel in bin/hermes-vps-artifacts lib/hermes_vps_artifacts.py; do
  if [[ -e "${EXT}/${rel}" ]]; then
    ok "payload has ${rel}"
  else
    bad "missing payload file ${rel}"
  fi
done

# ============================================================
# 1. Basic register — happy path
# ============================================================
REPORT1="${TMP}/draft-phase-010-v1.md"
make_report "${REPORT1}" "# Phase 010 inventory\n\nVersion 1 content.\n"
REP1_SHA="$(sha256 "${REPORT1}")"

if "${ARTIFACTS}" register \
    --run-json "${RUN_JSON}" \
    --phase 010 \
    --source-report "${REPORT1}" \
    >"${TMP}/reg1.out" 2>"${TMP}/reg1.err"; then
  ok "register: happy path exits 0"
else
  bad "register: happy path failed: $(cat "${TMP}/reg1.err")"
fi

FINAL1="${RUN}/reports/phase-010-hermes-v1.md"
if [[ -f "${FINAL1}" ]]; then
  ok "register: final report file created"
else
  bad "register: final report file missing: ${FINAL1}"
fi

if [[ "$(sha256 "${FINAL1}")" == "${REP1_SHA}" ]]; then
  ok "register: final report SHA matches source"
else
  bad "register: SHA mismatch after copy"
fi

MANIFEST="${RUN}/manifest.json"
if [[ -f "${MANIFEST}" ]]; then
  ok "register: manifest.json created"
else
  bad "register: manifest.json not created"
fi

python3 - "${MANIFEST}" "${REP1_SHA}" "${SHA}" <<'PY'
import json, sys
path, rep_sha, src_commit = sys.argv[1:4]
with open(path, encoding="utf-8") as fh:
    m = json.load(fh)
arts = m.get("artifacts", [])
assert len(arts) == 1, f"expected 1 artifact, got {len(arts)}"
a = arts[0]
assert a["id"] == "phase-010-hermes-v1", f"bad id: {a['id']}"
assert a["phase"] == "010", f"bad phase"
assert a["version"] == 1, f"bad version"
assert a["sha256"] == rep_sha, f"sha mismatch in manifest"
assert a["source_commit"] == src_commit, f"commit mismatch"
assert a["completion_status"] == "complete", f"bad status"
assert a["producer"] == "hermes-vps-artifacts/register", f"bad producer"
assert m["selected_by_phase"]["010"] == "phase-010-hermes-v1", f"selection wrong"
print("PASS: manifest fields correct")
PY
if [[ $? -eq 0 ]]; then
  ok "register: manifest fields correct"
else
  bad "register: manifest fields incorrect"
fi

# Consultation prompt includes required fields
if grep -q "phase-010-hermes-v1" "${TMP}/reg1.out" \
  && grep -q "${SHA}" "${TMP}/reg1.out" \
  && grep -q "${REP1_SHA}" "${TMP}/reg1.out" \
  && grep -q "STOP" "${TMP}/reg1.out" \
  && grep -qi "cannot access those local paths" "${TMP}/reg1.out"; then
  ok "register: consultation prompt contains required fields"
else
  bad "register: consultation prompt missing fields"
  head -40 "${TMP}/reg1.out" >&2 || true
fi

# ============================================================
# 2. Idempotency — re-register same source
# ============================================================
if "${ARTIFACTS}" register \
    --run-json "${RUN_JSON}" \
    --phase 010 \
    --source-report "${REPORT1}" \
    >"${TMP}/idem.out" 2>"${TMP}/idem.err"; then
  ok "idempotent: re-register same source exits 0"
else
  bad "idempotent: re-register failed: $(cat "${TMP}/idem.err")"
fi

# Manifest should still have exactly one artifact
python3 - "${MANIFEST}" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    m = json.load(fh)
assert len(m["artifacts"]) == 1, f"idempotent added extra artifact: {len(m['artifacts'])}"
print("PASS: idempotent did not duplicate artifact")
PY
if [[ $? -eq 0 ]]; then
  ok "idempotent: manifest unchanged after re-register"
else
  bad "idempotent: manifest changed after re-register"
fi

if grep -qi 'idempotent\|already registered' "${TMP}/idem.err"; then
  ok "idempotent: stderr notes already registered"
else
  bad "idempotent: no idempotent note in stderr"
fi

# ============================================================
# 3. Final-path collision with different content → fail
# ============================================================
# A file at the final destination (reports/phase-010-hermes-v1.md) already
# exists with different content than the source being registered.
RUN2="${TMP}/review-runs/example-repo/run-art2"
mkdir -p "${RUN2}/reports"
write_run "${TMP}/run2.json" "${POLICY}" "${SRC}" "${RUN2}" "${SHA}"
# Plant a different file at the v1 destination before any registration
make_report "${RUN2}/reports/phase-010-hermes-v1.md" "# Different pre-existing content\n"
make_report "${TMP}/draft-v1-b.md" "# Version 1 content B\n"
if ! "${ARTIFACTS}" register \
    --run-json "${TMP}/run2.json" \
    --phase 010 \
    --source-report "${TMP}/draft-v1-b.md" \
    >/dev/null 2>"${TMP}/collision.err"; then
  if grep -qi 'different content\|Collision\|already exists' "${TMP}/collision.err"; then
    ok "collision: final-path exists with different content rejected"
  else
    ok "collision: rejected (msg: $(head -1 "${TMP}/collision.err"))"
  fi
else
  bad "collision: final-path with different content should fail"
fi

# ============================================================
# 4. Version auto-selection: v1 exists → v2 selected
# ============================================================
RUN3="${TMP}/review-runs/example-repo/run-art3"
mkdir -p "${RUN3}/reports"
write_run "${TMP}/run3.json" "${POLICY}" "${SRC}" "${RUN3}" "${SHA}"

make_report "${TMP}/draft-r3-v1.md" "# V1 report content\n"
"${ARTIFACTS}" register \
  --run-json "${TMP}/run3.json" \
  --phase 010 \
  --source-report "${TMP}/draft-r3-v1.md" >/dev/null 2>"${TMP}/r3v1.err"

make_report "${TMP}/draft-r3-v2.md" "# V2 report content\n"
if "${ARTIFACTS}" register \
    --run-json "${TMP}/run3.json" \
    --phase 010 \
    --source-report "${TMP}/draft-r3-v2.md" \
    >"${TMP}/r3v2.out" 2>"${TMP}/r3v2.err"; then
  ok "auto-version: v2 registration exits 0"
else
  bad "auto-version: v2 failed: $(cat "${TMP}/r3v2.err")"
fi

python3 - "${RUN3}/manifest.json" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    m = json.load(fh)
ids = [a["id"] for a in m["artifacts"]]
assert "phase-010-hermes-v1" in ids, f"v1 missing: {ids}"
assert "phase-010-hermes-v2" in ids, f"v2 missing: {ids}"
assert m["selected_by_phase"]["010"] == "phase-010-hermes-v2", f"selection not updated: {m['selected_by_phase']}"
print("PASS: v2 selected, v1 preserved")
PY
if [[ $? -eq 0 ]]; then
  ok "auto-version: v2 selected, v1 preserved"
else
  bad "auto-version: manifest state incorrect"
fi

if [[ -f "${RUN3}/reports/phase-010-hermes-v2.md" ]]; then
  ok "auto-version: v2 file created"
else
  bad "auto-version: v2 file missing"
fi

# ============================================================
# 5. accept subcommand
# ============================================================
if "${ARTIFACTS}" accept \
    --run-json "${RUN_JSON}" \
    --artifact-id phase-010-hermes-v1 \
    --reviewer-identity "test-reviewer-01" \
    >"${TMP}/acc.out" 2>"${TMP}/acc.err"; then
  ok "accept: exits 0"
else
  bad "accept: failed: $(cat "${TMP}/acc.err")"
fi

python3 - "${MANIFEST}" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    m = json.load(fh)
a = m["artifacts"][0]
assert len(a.get("reviews", [])) == 1, f"expected 1 review, got {len(a.get('reviews', []))}"
r = a["reviews"][0]
assert r["outcome"] == "ACCEPT", f"bad outcome: {r['outcome']}"
assert r["reviewer_identity_declared"] == "test-reviewer-01", f"bad reviewer"
assert r["authenticated"] == False, "should be unauthenticated"
# selection should be unchanged
assert m["selected_by_phase"]["010"] == "phase-010-hermes-v1", "selection changed by accept"
print("PASS: accept review recorded, selection unchanged")
PY
if [[ $? -eq 0 ]]; then
  ok "accept: review recorded; selection unchanged"
else
  bad "accept: manifest state incorrect after accept"
fi

if grep -qi 'does not require ACCEPT\|not required' "${TMP}/acc.out"; then
  ok "accept: output notes ACCEPT not required for normal progression"
else
  # Not required to mention this; accept the message as printed
  ok "accept: completed (optional reminder not checked)"
fi

# accept against unknown artifact → fail
if "${ARTIFACTS}" accept \
    --run-json "${RUN_JSON}" \
    --artifact-id phase-010-hermes-v999 \
    --reviewer-identity "tester" \
    >/dev/null 2>"${TMP}/acc-bad.err"; then
  bad "accept: unknown artifact should fail"
else
  grep -qi 'not found\|unknown' "${TMP}/acc-bad.err" \
    && ok "accept: unknown artifact rejected" \
    || bad "accept: unclear error: $(cat "${TMP}/acc-bad.err")"
fi

# ============================================================
# 6. revise subcommand — source file outside reports/
# ============================================================
REVISED_SRC="${TMP}/external-revised-report.md"
make_report "${REVISED_SRC}" "# Phase 010 inventory — corrected\n\nRevised content.\n"
REV_SHA="$(sha256 "${REVISED_SRC}")"

if "${ARTIFACTS}" revise \
    --run-json "${RUN_JSON}" \
    --source-report "${REVISED_SRC}" \
    --supersedes phase-010-hermes-v1 \
    --reviewer-identity "test-reviewer-revise" \
    >"${TMP}/rev.out" 2>"${TMP}/rev.err"; then
  ok "revise: exits 0"
else
  bad "revise: failed: $(cat "${TMP}/rev.err")"
fi

if [[ -f "${RUN}/reports/phase-010-hermes-v2.md" ]]; then
  ok "revise: v2 file created inside reports/"
else
  bad "revise: v2 file missing"
fi

if [[ "$(sha256 "${RUN}/reports/phase-010-hermes-v2.md")" == "${REV_SHA}" ]]; then
  ok "revise: v2 SHA matches source"
else
  bad "revise: v2 SHA mismatch"
fi

python3 - "${MANIFEST}" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    m = json.load(fh)
ids = {a["id"]: a for a in m["artifacts"]}
assert "phase-010-hermes-v1" in ids, "v1 missing after revise"
assert "phase-010-hermes-v2" in ids, "v2 missing after revise"
v2 = ids["phase-010-hermes-v2"]
assert v2["supersedes"] == "phase-010-hermes-v1", f"supersedes wrong: {v2.get('supersedes')}"
assert m["selected_by_phase"]["010"] == "phase-010-hermes-v2", "selection not updated"
assert len(v2.get("reviews", [])) == 1, "revise review not recorded"
assert v2["reviews"][0]["outcome"] == "REVISE", "review outcome wrong"
assert v2["reviews"][0]["reviewer_identity_declared"] == "test-reviewer-revise"
assert v2["reviews"][0]["authenticated"] == False
print("PASS: revise manifest state correct")
PY
if [[ $? -eq 0 ]]; then
  ok "revise: manifest state correct"
else
  bad "revise: manifest state incorrect"
fi

if grep -q "phase-010-hermes-v2" "${TMP}/rev.out" \
  && grep -q "${REV_SHA}" "${TMP}/rev.out"; then
  ok "revise: consultation prompt references new artifact + SHA"
else
  bad "revise: consultation prompt missing fields"
fi

# revise: supersedes nonexistent → fail
if "${ARTIFACTS}" revise \
    --run-json "${RUN_JSON}" \
    --source-report "${REVISED_SRC}" \
    --supersedes phase-010-hermes-v999 \
    --reviewer-identity "tester" \
    >/dev/null 2>"${TMP}/rev-bad.err"; then
  bad "revise: nonexistent supersedes should fail"
else
  grep -qi 'not found\|unknown' "${TMP}/rev-bad.err" \
    && ok "revise: nonexistent supersedes rejected" \
    || bad "revise: unclear error: $(cat "${TMP}/rev-bad.err")"
fi

# ============================================================
# 7. revise idempotency — same SHA already in index
# ============================================================
if "${ARTIFACTS}" revise \
    --run-json "${RUN_JSON}" \
    --source-report "${REVISED_SRC}" \
    --supersedes phase-010-hermes-v1 \
    --reviewer-identity "test-reviewer-revise" \
    >"${TMP}/rev-idem.out" 2>"${TMP}/rev-idem.err"; then
  ok "revise idempotent: exits 0"
else
  bad "revise idempotent: failed: $(cat "${TMP}/rev-idem.err")"
fi

python3 - "${MANIFEST}" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    m = json.load(fh)
# Should still be 2 artifacts (accept + v2 original + no new one)
# The v1 has a review from accept; v2 is the revise
count = len([a for a in m["artifacts"] if a.get("kind") == "hermes_phase_report"])
assert count == 2, f"expected 2 phase reports, got {count}"
print("PASS: revise idempotent did not add duplicate")
PY
if [[ $? -eq 0 ]]; then
  ok "revise idempotent: no duplicate added"
else
  bad "revise idempotent: state incorrect"
fi

# ============================================================
# 8. selected subcommand — read-only; verifies SHA
# ============================================================
if "${ARTIFACTS}" selected \
    --run-json "${RUN_JSON}" \
    >"${TMP}/sel.out" 2>"${TMP}/sel.err"; then
  ok "selected: exits 0"
else
  bad "selected: failed: $(cat "${TMP}/sel.err")"
fi

if grep -q "phase-010-hermes-v2" "${TMP}/sel.out" \
  && grep -qi 'SHA-256 OK' "${TMP}/sel.out"; then
  ok "selected: shows v2 with SHA-256 OK"
else
  bad "selected: output incorrect"
  cat "${TMP}/sel.out" >&2 || true
fi

# selected modifies nothing
MTIME_BEFORE="$(stat -c '%Y' "${MANIFEST}")"
"${ARTIFACTS}" selected --run-json "${RUN_JSON}" >/dev/null 2>&1 || true
MTIME_AFTER="$(stat -c '%Y' "${MANIFEST}")"
if [[ "${MTIME_BEFORE}" == "${MTIME_AFTER}" ]]; then
  ok "selected: manifest not modified (read-only)"
else
  bad "selected: manifest was modified"
fi

# selected with corrupted file detects SHA mismatch
cp "${RUN}/reports/phase-010-hermes-v2.md" "${TMP}/v2-backup.md"
echo "TAMPERED" >>"${RUN}/reports/phase-010-hermes-v2.md"
if ! "${ARTIFACTS}" selected \
    --run-json "${RUN_JSON}" \
    >"${TMP}/sel-bad.out" 2>"${TMP}/sel-bad.err"; then
  if grep -qi 'MISMATCH\|mismatch\|verification' "${TMP}/sel-bad.out" \
    || grep -qi 'MISMATCH\|mismatch\|verification' "${TMP}/sel-bad.err"; then
    ok "selected: SHA mismatch detected"
  else
    ok "selected: exited non-zero for tampered file"
  fi
else
  bad "selected: tampered file should cause non-zero exit"
fi
# Restore
cp "${TMP}/v2-backup.md" "${RUN}/reports/phase-010-hermes-v2.md"

# ============================================================
# 9. saved-but-unregistered retry path
# ============================================================
# Simulate: report copied but manifest not yet written (index absent)
RUN4="${TMP}/review-runs/example-repo/run-art4"
mkdir -p "${RUN4}/reports"
write_run "${TMP}/run4.json" "${POLICY}" "${SRC}" "${RUN4}" "${SHA}"

make_report "${TMP}/draft-r4.md" "# Run4 report\n"
R4_SHA="$(sha256 "${TMP}/draft-r4.md")"

# Manually copy to final path to simulate interrupted register
cp "${TMP}/draft-r4.md" "${RUN4}/reports/phase-010-hermes-v1.md"

# Now call register with the already-copied final path as --source-report
if "${ARTIFACTS}" register \
    --run-json "${TMP}/run4.json" \
    --phase 010 \
    --source-report "${RUN4}/reports/phase-010-hermes-v1.md" \
    >"${TMP}/retry.out" 2>"${TMP}/retry.err"; then
  ok "retry: registering already-copied file exits 0"
else
  bad "retry: registering already-copied file failed: $(cat "${TMP}/retry.err")"
fi

if [[ -f "${RUN4}/manifest.json" ]]; then
  python3 - "${RUN4}/manifest.json" "${R4_SHA}" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    m = json.load(fh)
assert len(m["artifacts"]) == 1, f"expected 1 artifact"
assert m["artifacts"][0]["sha256"] == sys.argv[2], "SHA mismatch in retry manifest"
print("PASS: retry manifest correct")
PY
  if [[ $? -eq 0 ]]; then
    ok "retry: manifest correct after retry register"
  else
    bad "retry: manifest incorrect after retry register"
  fi
else
  bad "retry: manifest.json not created"
fi

# ============================================================
# 10. CLI error cases
# ============================================================
# Missing --run-json
if "${ARTIFACTS}" register \
    --phase 010 \
    --source-report "${REPORT1}" \
    >/dev/null 2>"${TMP}/no-rj.err"; then
  bad "register: missing --run-json should fail"
else
  ok "register: missing --run-json rejected"
fi

# Relative --run-json
if "${ARTIFACTS}" register \
    --run-json "relative/path/run.json" \
    --phase 010 \
    --source-report "${REPORT1}" \
    >/dev/null 2>"${TMP}/rel-rj.err"; then
  bad "register: relative --run-json should fail"
else
  grep -qi 'absolute' "${TMP}/rel-rj.err" \
    && ok "register: relative --run-json rejected" \
    || ok "register: relative --run-json rejected (alt msg)"
fi

# Non-absolute --source-report
if "${ARTIFACTS}" register \
    --run-json "${RUN_JSON}" \
    --phase 010 \
    --source-report "relative/report.md" \
    >/dev/null 2>"${TMP}/rel-sr.err"; then
  bad "register: relative --source-report should fail"
else
  grep -qi 'absolute' "${TMP}/rel-sr.err" \
    && ok "register: relative --source-report rejected" \
    || ok "register: relative --source-report rejected (alt msg)"
fi

# Non-existent --source-report
if "${ARTIFACTS}" register \
    --run-json "${RUN_JSON}" \
    --phase 010 \
    --source-report "/tmp/does-not-exist-$(date +%s).md" \
    >/dev/null 2>"${TMP}/nofile.err"; then
  bad "register: non-existent --source-report should fail"
else
  grep -qi 'not found\|does not exist' "${TMP}/nofile.err" \
    && ok "register: non-existent --source-report rejected" \
    || ok "register: non-existent --source-report rejected (alt msg)"
fi

# Phase gate intentionally removed: run.json has phase 010 but --phase 020 is now accepted by the
# artifact helper. The helper is the sole writer of manifest.json and accepts any phase in VALID_PHASES.
# Policy file checks for the requested phase belong to the runner (hermes-vps-review), not the helper.
REPORT_020="${TMP}/draft-phase-020.md"
printf '# Phase 020 report\n\nContent.\nState: `complete`\n' >"${REPORT_020}"
if "${ARTIFACTS}" register \
    --run-json "${RUN_JSON}" \
    --phase 020 \
    --source-report "${REPORT_020}" \
    >"${TMP}/phase-020.out" 2>"${TMP}/phase-mm.err"; then
  ok "register: phase 020 accepted by helper (phase gate removed; runner gates policy files)"
  # Cleanup: remove registered v3 artifact from manifest so later tests aren't confused
  python3 - "${MANIFEST}" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    m = json.load(fh)
m["artifacts"] = [a for a in m.get("artifacts", []) if a.get("phase") != "020"]
m["selected_by_phase"].pop("020", None)
with open(sys.argv[1], "w", encoding="utf-8") as fh:
    json.dump(m, fh, indent=2)
    fh.write("\n")
PY
else
  bad "register: phase 020 unexpectedly rejected: $(cat "${TMP}/phase-mm.err")"
fi

# Runner validates correctly with --phase 010 (--phase now required)
if "${RUNNER}" --phase 010 --run-json "${RUN_JSON}" >/dev/null 2>"${TMP}/runner.err"; then
  ok "runner: validates with --phase 010"
else
  bad "runner: failed with --phase 010: $(cat "${TMP}/runner.err")"
fi

# Runner rejects --report-version (removed flag) — must also pass --phase
if "${RUNNER}" --phase 010 --run-json "${RUN_JSON}" --report-version 1 >/dev/null 2>"${TMP}/rv.err"; then
  bad "runner: --report-version should be rejected (flag removed)"
else
  ok "runner: --report-version rejected (flag removed)"
fi

# Runner warns on run.json with deprecated report_version field (--phase required)
python3 - "${RUN_JSON}" "${TMP}/legacy-run.json" <<'PY'
import json, sys
src, dst = sys.argv[1:3]
with open(src, encoding="utf-8") as fh:
    data = json.load(fh)
data["phase_request"]["report_version"] = 1
with open(dst, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
PY
if "${RUNNER}" --phase 010 --run-json "${TMP}/legacy-run.json" >/dev/null 2>"${TMP}/legacy.err"; then
  if grep -qi 'deprecat' "${TMP}/legacy.err"; then
    ok "runner: deprecated report_version warns but succeeds"
  else
    ok "runner: deprecated report_version accepted (no warning required)"
  fi
else
  bad "runner: deprecated report_version should not hard-fail: $(cat "${TMP}/legacy.err")"
fi

# ============================================================
# 11. Runner makes no writes (validate-only)
# ============================================================
RUN5="${TMP}/review-runs/example-repo/run-art5"
mkdir -p "${RUN5}/reports"
write_run "${TMP}/run5.json" "${POLICY}" "${SRC}" "${RUN5}" "${SHA}"

fingerprint5() {
  find "${SRC}" "${RUN5}" -type f -print0 | sort -z | xargs -0 sha256sum
}
before5="$(fingerprint5)"
"${RUNNER}" --phase 010 --run-json "${TMP}/run5.json" >/dev/null 2>/dev/null || true
after5="$(fingerprint5)"
if [[ "${before5}" == "${after5}" ]]; then
  ok "runner: makes no writes to source or run root"
else
  bad "runner: modified files"
fi

# ============================================================
# 12. register rejects destination that is a dangling symlink
# ============================================================
RUN6="${TMP}/review-runs/example-repo/run-art6"
mkdir -p "${RUN6}/reports"
write_run "${TMP}/run6.json" "${POLICY}" "${SRC}" "${RUN6}" "${SHA}"
# Pre-create a dangling symlink at the v1 destination
ln -s "${RUN6}/reports/does-not-exist.md" "${RUN6}/reports/phase-010-hermes-v1.md"
make_report "${TMP}/draft-r6.md" "# Run6 report\n"
if ! "${ARTIFACTS}" register \
    --run-json "${TMP}/run6.json" \
    --phase 010 \
    --source-report "${TMP}/draft-r6.md" \
    >/dev/null 2>"${TMP}/dangle.err"; then
  grep -qi 'not a regular file\|different content\|Collision\|exists' "${TMP}/dangle.err" \
    && ok "register: dangling symlink at destination rejected" \
    || ok "register: dangling symlink at destination rejected (alt msg: $(head -1 "${TMP}/dangle.err"))"
else
  bad "register: dangling symlink at destination should fail"
fi

# ============================================================
echo
echo "Summary: ${pass} passed, ${fail} failed"
if [[ "${fail}" -ne 0 ]]; then
  exit 1
fi
echo "PASS: hermes-vps-artifacts fixture suite"
