#!/usr/bin/env bash
# Focused tests for hermesVPS /hermes-vps-010 skill + registry lookup.
# Deterministic file/runner checks only — not model obedience or portal discovery.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXT="${ROOT}/extensions/hermesVPS"
RUNNER="${EXT}/bin/hermes-vps-review"
SKILL="${EXT}/skills/hermes-vps-010/SKILL.md"
LOCAL_HERMES_SKILL="${ROOT}/extensions/hermes/skills/hermes-010/SKILL.md"

TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

fail=0
pass=0
static_pass=0
static_fail=0

ok() { pass=$((pass + 1)); echo "PASS: $*"; }
bad() { fail=$((fail + 1)); echo "FAIL: $*" >&2; }
sok() { static_pass=$((static_pass + 1)); echo "STATIC-PASS: $*"; }
sbad() { static_fail=$((static_fail + 1)); echo "STATIC-FAIL: $*" >&2; }

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "FAIL: missing host command $1" >&2
    exit 1
  }
}
need git
need python3
need cmp

[[ -x "${RUNNER}" ]] || {
  echo "FAIL: runner not executable" >&2
  exit 1
}

# --- static skill-text checks (do not prove model obedience) ---
if [[ -f "${SKILL}" ]]; then
  sok "skill file exists"
else
  sbad "missing skill file"
fi

if grep -Fqx "name: hermes-vps-010" "${SKILL}"; then
  sok "skill frontmatter name is hermes-vps-010"
else
  sbad "skill name mismatch"
fi

for needle in \
  "bin/hermes-vps-review" \
  "targets.json" \
  "--registry" \
  "--target-id" \
  "tasks/010-inventory.md" \
  "non-zero" \
  "prove OS isolation" \
  "/opt/data/hermes-review"; do
  if grep -Fq -- "${needle}" "${SKILL}"; then
    sok "skill mentions ${needle}"
  else
    sbad "skill missing ${needle}"
  fi
done

if grep -RIn '/home/acktarius' "${EXT}/skills" >/dev/null 2>&1; then
  sbad "developer path in skills"
else
  sok "no /home/acktarius in skills"
fi

if grep -RIn '/workspace/target' "${EXT}/skills" >/dev/null 2>&1; then
  sbad "/workspace/target in skills"
else
  sok "no /workspace/target in skills"
fi

if grep -Fq "name: hermes-010" "${LOCAL_HERMES_SKILL}" \
  && grep -Fq '/workspace/target/.repo-kit/hermes/tasks/010-inventory.md' "${LOCAL_HERMES_SKILL}"; then
  sok "local Hermes hermes-010 skill unchanged (spot check)"
else
  sbad "local Hermes skill unexpectedly altered or missing expected content"
fi

# git: ensure extensions/hermes has no modifications
if git -C "${ROOT}" status --porcelain -- extensions/hermes | grep . >/dev/null; then
  sbad "extensions/hermes working tree dirty"
else
  sok "extensions/hermes has no local modifications"
fi

# --- fixture setup ---
POLICY="${TMP}/policy with spaces/hermes-review"
SRC="${TMP}/repositories/example-repo"
RUN="${TMP}/review-runs/example-repo/run-010"
mkdir -p "${POLICY}" "${SRC}" "${RUN}/reports"
cp -a "${EXT}/." "${POLICY}/"

git -C "${SRC}" init -q
git -C "${SRC}" config user.email "test@example.com"
git -C "${SRC}" config user.name "Test"
echo "hello" >"${SRC}/README.md"
git -C "${SRC}" add README.md
git -C "${SRC}" commit -q -m "init"
SHA="$(git -C "${SRC}" rev-parse HEAD)"

write_run() {
  local out="$1" policy="$2" src="$3" run_root="$4" commit="$5" phase="${6:-010}"
  python3 - "$out" "$policy" "$src" "$run_root" "$commit" "$phase" <<'PY'
import json, sys
out, policy, src, run_root, commit, phase = sys.argv[1:7]
name = "inventory" if phase == "010" else "threat-model"
data = {
  "schema_version": 1,
  "run_id": "run-010",
  "policy_prefix": policy,
  "source": {
    "path": src,
    "identity": "fixture/example-repo",
    "commit": commit,
    "require_clean_worktree": True,
  },
  "output": {"run_root": run_root},
  "phase_request": {
    "phase": phase,
    "phase_name": name,
    "report_version": 1,
    "requested_by": "test",
    "requested_at_utc": "2026-10-30T00:00:00Z",
  },
  "prerequisites": {"artifacts": []},
  "boundaries": {
    "claims_os_readonly_source": False,
    "allowed_write_roots": [run_root],
  },
}
with open(out, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
PY
}

write_registry() {
  local out="$1" policy="$2" run_json="$3" tid="${4:-repoX}"
  python3 - "$out" "$policy" "$run_json" "$tid" <<'PY'
import json, sys
out, policy, run_json, tid = sys.argv[1:5]
data = {
  "schema_version": 1,
  "policy_prefix": policy,
  "targets": {tid: {"active_run_json": run_json}},
}
with open(out, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
PY
}

RUN_JSON="${RUN}/run.json"
REG="${POLICY}/targets.json"
write_run "${RUN_JSON}" "${POLICY}" "${SRC}" "${RUN}" "${SHA}"
write_registry "${REG}" "${POLICY}" "${RUN_JSON}" "repoX"

fingerprint() {
  find "${SRC}" "${RUN}" "${POLICY}/targets.json" -type f -print0 2>/dev/null | sort -z | xargs -0 sha256sum
}

before="$(fingerprint)"

# Successful short-command resolution (registry mode)
OUT="${TMP}/ok-prompt.txt"
if "${RUNNER}" --registry "${REG}" --target-id repoX >"${OUT}" 2>"${TMP}/e"; then
  ok "registry+target-id validation succeeds"
else
  bad "registry mode failed: $(cat "${TMP}/e")"
fi

if grep -Fq "PHASE: 010" "${OUT}" \
  && grep -Fq "${RUN}/reports/phase-010-hermes-v1.md" "${OUT}" \
  && grep -Fq "Execute ONLY phase 010" "${OUT}"; then
  ok "successful short-command resolution prints phase-010 prompt"
else
  bad "prompt incomplete after registry resolution"
fi

# Same family as --run-json
OUT2="${TMP}/runjson-prompt.txt"
"${RUNNER}" --run-json "${RUN_JSON}" >"${OUT2}" 2>"${TMP}/e" || bad "run-json mode failed"
# Compare key lines (paths may differ only by resolution; both should name same report)
r1="$(grep '^SELECTED REPORT OUTPUT:' "${OUT}")"
r2="$(grep '^SELECTED REPORT OUTPUT:' "${OUT2}")"
if [[ "${r1}" == "${r2}" ]]; then
  ok "registry mode and --run-json select the same report output"
else
  bad "mode prompt divergence: [${r1}] vs [${r2}]"
fi

after="$(fingerprint)"
if [[ "${before}" == "${after}" ]]; then
  ok "runner produces no filesystem changes in fixtures"
else
  bad "fixture files changed after runner"
fi

# Unknown target
if "${RUNNER}" --registry "${REG}" --target-id unknownRepo >/dev/null 2>"${TMP}/e"; then
  bad "unknown target should fail"
else
  grep -qi 'unknown target' "${TMP}/e" && ok "unknown target rejected" || bad "unknown msg: $(cat "${TMP}/e")"
fi

# Invalid identifier with embedded ..
if "${RUNNER}" --registry "${REG}" --target-id 'a..b' >/dev/null 2>"${TMP}/e"; then
  bad "a..b should fail"
else
  grep -q "\\.\\." "${TMP}/e" && ok "embedded .. in identifier rejected" || bad "a..b msg: $(cat "${TMP}/e")"
fi

# Duplicate target IDs (duplicate JSON keys)
python3 - "${REG}" "${TMP}/dup-targets.json" <<'PY'
import sys
src, dst = sys.argv[1:3]
text = open(src, encoding="utf-8").read()
# Inject a duplicate "repoX" key after the first targets object entry by rewriting naively
# Build invalid JSON with duplicate keys explicitly:
import json
data = json.load(open(src, encoding="utf-8"))
# Write raw duplicate-key JSON
run_json = data["targets"]["repoX"]["active_run_json"]
policy = data["policy_prefix"]
raw = (
  '{\n'
  '  "schema_version": 1,\n'
  f'  "policy_prefix": {json.dumps(policy)},\n'
  '  "targets": {\n'
  f'    "repoX": {{"active_run_json": {json.dumps(run_json)}}},\n'
  f'    "repoX": {{"active_run_json": {json.dumps(run_json)}}}\n'
  '  }\n'
  '}\n'
)
open(dst, "w", encoding="utf-8").write(raw)
PY
if "${RUNNER}" --registry "${TMP}/dup-targets.json" --target-id repoX >/dev/null 2>"${TMP}/e"; then
  bad "duplicate target keys should fail"
else
  grep -qi 'duplicate' "${TMP}/e" && ok "duplicate target IDs rejected" || bad "dup targets msg: $(cat "${TMP}/e")"
fi

# Duplicate active_run_json field
python3 - "${POLICY}" "${RUN_JSON}" "${TMP}/dup-field.json" <<'PY'
import json, sys
policy, run_json, dst = sys.argv[1:4]
raw = (
  '{\n'
  '  "schema_version": 1,\n'
  f'  "policy_prefix": {json.dumps(policy)},\n'
  '  "targets": {\n'
  '    "repoX": {\n'
  f'      "active_run_json": {json.dumps(run_json)},\n'
  f'      "active_run_json": {json.dumps(run_json)}\n'
  '    }\n'
  '  }\n'
  '}\n'
)
open(dst, "w", encoding="utf-8").write(raw)
PY
if "${RUNNER}" --registry "${TMP}/dup-field.json" --target-id repoX >/dev/null 2>"${TMP}/e"; then
  bad "duplicate active_run_json should fail"
else
  grep -qi 'duplicate' "${TMP}/e" && ok "duplicate active_run_json key rejected" || bad "dup field msg: $(cat "${TMP}/e")"
fi

# Duplicate key in run.json
python3 - "${RUN_JSON}" "${TMP}/dup-run.json" <<'PY'
import json, sys
src, dst = sys.argv[1:3]
data = json.load(open(src, encoding="utf-8"))
# recreate with duplicate schema_version keys
body = json.dumps(data)
# cheaper: write raw
raw = open(src, encoding="utf-8").read().replace(
  '"schema_version": 1',
  '"schema_version": 1,\n  "schema_version": 1',
  1,
)
open(dst, "w", encoding="utf-8").write(raw)
PY
if "${RUNNER}" --run-json "${TMP}/dup-run.json" >/dev/null 2>"${TMP}/e"; then
  bad "duplicate run.json keys should fail"
else
  grep -qi 'duplicate' "${TMP}/e" && ok "duplicate run.json keys rejected" || bad "dup run msg: $(cat "${TMP}/e")"
fi

# CLI: missing partner flags
if "${RUNNER}" --registry "${REG}" >/dev/null 2>"${TMP}/e"; then
  bad "registry without target-id should fail"
else
  grep -Fq -- '--target-id' "${TMP}/e" && ok "registry without target-id rejected" || bad "msg: $(cat "${TMP}/e")"
fi
if "${RUNNER}" --target-id repoX >/dev/null 2>"${TMP}/e"; then
  bad "target-id without registry should fail"
else
  grep -Fq -- '--registry' "${TMP}/e" && ok "target-id without registry rejected" || bad "msg: $(cat "${TMP}/e")"
fi

# Conflicting modes
if "${RUNNER}" --run-json "${RUN_JSON}" --registry "${REG}" --target-id repoX >/dev/null 2>"${TMP}/e"; then
  bad "conflicting modes should fail"
else
  grep -qi 'conflict\|either' "${TMP}/e" && ok "conflicting input modes rejected" || bad "conflict msg: $(cat "${TMP}/e")"
fi

# Repeated flags
if "${RUNNER}" --run-json "${RUN_JSON}" --run-json "${RUN_JSON}" >/dev/null 2>"${TMP}/e"; then
  bad "repeated --run-json should fail"
else
  grep -qi 'only be specified once\|once' "${TMP}/e" && ok "repeated --run-json rejected" || bad "repeat msg: $(cat "${TMP}/e")"
fi

# Unexpected positional
if "${RUNNER}" --run-json "${RUN_JSON}" extra-arg >/dev/null 2>"${TMP}/e"; then
  bad "unexpected positional should fail"
else
  ok "unexpected positional rejected"
fi

# Registry/run policy-prefix mismatch
OTHER_POL="${TMP}/other-policy"
mkdir -p "${OTHER_POL}"
# minimal copy so registry path exists as dir; run still points at POLICY
write_registry "${TMP}/mismatch-reg.json" "${OTHER_POL}" "${RUN_JSON}" "repoX"
if "${RUNNER}" --registry "${TMP}/mismatch-reg.json" --target-id repoX >/dev/null 2>"${TMP}/e"; then
  bad "policy_prefix mismatch should fail"
else
  # may fail earlier if other-policy missing required files when validating run —
  # but mismatch check happens after load; if other-policy isn't the run's prefix,
  # expected_policy differs from run → mismatch error. OTHER_POL must be a dir.
  if grep -qi 'policy_prefix mismatch' "${TMP}/e"; then
    ok "registry/run policy_prefix mismatch rejected"
  else
    # If it failed because OTHER_POL isn't usable as expected_policy compare — show err
    # Actually validate_run compares expected_policy (OTHER_POL realpath) to run's POLICY — should mismatch.
    bad "expected policy_prefix mismatch, got: $(cat "${TMP}/e")"
  fi
fi

# Wrong phase selection
write_run "${TMP}/phase020.json" "${POLICY}" "${SRC}" "${RUN}" "${SHA}" "020"
write_registry "${TMP}/reg020.json" "${POLICY}" "${TMP}/phase020.json" "repoX"
# Remove collision file if any from previous — phase020 uses same report name pattern phase-020...
if "${RUNNER}" --registry "${TMP}/reg020.json" --target-id repoX >/dev/null 2>"${TMP}/e"; then
  bad "wrong phase should fail"
else
  grep -qi 'not phase 010\|phase 010' "${TMP}/e" && ok "wrong phase selection rejected" || bad "phase msg: $(cat "${TMP}/e")"
fi

# Spaces in paths already covered by POLICY path — confirm registry mode
if "${RUNNER}" --registry "${REG}" --target-id repoX >/dev/null 2>"${TMP}/e"; then
  ok "spaces in policy/registry paths handled"
else
  bad "spaces path failed: $(cat "${TMP}/e")"
fi

echo
echo "==== successful short-command resolution example (excerpt) ===="
grep -E '^(POLICY PREFIX|SOURCE COMMIT|RUN ID|PHASE|SELECTED REPORT|INSTRUCTIONS|  - Execute ONLY|  - Then STOP)' "${OUT}" | head -n 20
echo "==== end excerpt ===="
echo
echo "Executable checks: ${pass} passed, ${fail} failed"
echo "Static skill-text checks: ${static_pass} passed, ${static_fail} failed (not model obedience)"
if [[ "${fail}" -ne 0 || "${static_fail}" -ne 0 ]]; then
  exit 1
fi
echo "PASS: hermes-vps-010-skill suite"
