#!/usr/bin/env bash
# Fixture tests for hermesVPS init-hermes-review (no live GitHub / VPS).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXT="${ROOT}/extensions/hermesVPS"
INIT="${EXT}/bin/init-hermes-review"
RUNNER="${EXT}/bin/hermes-vps-review"

TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

fail=0
pass=0
ok() { pass=$((pass + 1)); echo "PASS: $*"; }
bad() { fail=$((fail + 1)); echo "FAIL: $*" >&2; }

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "FAIL: missing host command $1" >&2
    exit 1
  }
}
need git
need python3

[[ -x "${INIT}" ]] || {
  echo "FAIL: init not executable: ${INIT}" >&2
  exit 1
}
[[ -x "${RUNNER}" ]] || {
  echo "FAIL: runner not executable: ${RUNNER}" >&2
  exit 1
}
[[ -f "${EXT}/lib/hermes_vps_common.py" ]] || {
  echo "FAIL: missing shared module" >&2
  exit 1
}

# --- URL rejection (no filesystem layout required) ---
reject_url() {
  local label="$1"
  local url="$2"
  local needle="${3:-}"
  if "${INIT}" "${url}" --policy-prefix "${TMP}/no-such-policy" >/dev/null 2>"${TMP}/e"; then
    bad "${label} should fail"
  else
    if [[ -n "${needle}" ]] && ! grep -qi "${needle}" "${TMP}/e"; then
      bad "${label}: expected message containing ${needle}: $(cat "${TMP}/e")"
    else
      ok "${label} rejected"
    fi
  fi
}

reject_url "ssh url" "git@github.com:org/repo.git" "HTTPS"
reject_url "http url" "http://github.com/org/repo.git" "HTTPS"
reject_url "credentials" "https://user:pass@github.com/org/repo.git" "credential"
reject_url "query" "https://github.com/org/repo.git?foo=1" "query\|fragment"
reject_url "fragment" "https://github.com/org/repo.git#frag" "query\|fragment"
reject_url "non-github host" "https://gitlab.com/org/repo.git" "github.com"
reject_url "shell meta" 'https://github.com/org/repo.git;rm -rf /' "unsafe\|invalid"
reject_url "extra path" "https://github.com/org/repo/extra.git" "path\|invalid"

# --- layout helpers ---
DATA="${TMP}/opt/data"
POLICY="${DATA}/hermes-review"
mkdir -p "${POLICY}"
cp -a "${EXT}/." "${POLICY}/"
find "${POLICY}" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "${POLICY}" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

seed_source() {
  local dest="$1" owner="$2" repo="$3"
  mkdir -p "$(dirname "${dest}")"
  if [[ -e "${dest}" ]]; then
    rm -rf "${dest}"
  fi
  mkdir -p "${dest}"
  git -C "${dest}" init -q
  git -C "${dest}" config user.email "fixture@example.invalid"
  git -C "${dest}" config user.name "fixture"
  echo "fixture ${owner}/${repo}" >"${dest}/README.md"
  git -C "${dest}" add README.md
  git -C "${dest}" commit -q -m "fixture"
  git -C "${dest}" remote add origin "https://github.com/${owner}/${repo}.git"
}

OWNER="FixtureOrg"
REPO="sample-repo"
URL="https://github.com/${OWNER}/${REPO}.git"
SRC="${DATA}/repositories/${REPO}"
seed_source "${SRC}" "${OWNER}" "${REPO}"
SHA="$(git -C "${SRC}" rev-parse HEAD)"

# Happy path
OUT="${TMP}/ok.txt"
if "${INIT}" "${URL}" \
  --policy-prefix "${POLICY}" \
  --run-id "smoke-010" \
  >"${OUT}" 2>"${TMP}/e"; then
  ok "init succeeds for seeded clean source"
else
  bad "init failed: $(cat "${TMP}/e")"
fi

RUN_JSON="${DATA}/review-runs/${REPO}/smoke-010/run.json"
REPORTS="${DATA}/review-runs/${REPO}/smoke-010/reports"
if [[ -f "${RUN_JSON}" && -d "${REPORTS}" ]] \
  && [[ "$(find "${REPORTS}" -mindepth 1 | wc -l)" -eq 0 ]] \
  && grep -Fq "TARGET ID: ${REPO}" "${OUT}" \
  && grep -Fq "SOURCE COMMIT: ${SHA}" "${OUT}" \
  && grep -Fq "/hermes-vps-010 ${REPO}" "${OUT}" \
  && grep -Fq "does not register skills" "${OUT}" \
  && grep -Fq "BOOTSTRAP FALLBACK:" "${OUT}"; then
  ok "success output and artifacts present"
else
  bad "success artifacts/output incomplete: $(cat "${OUT}"; echo '---'; cat "${TMP}/e")"
fi

# Copied policy without Git metadata → unknown revision, dirty true
python3 - "${RUN_JSON}" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
tk = data["toolkit"]
assert tk["toolkit_revision"] == "unknown", tk
assert tk["toolkit_dirty"] is True, tk
PY
ok "copied policy without Git metadata records unknown/dirty toolkit"

# Unrelated target preserved + registry schema
python3 - "${POLICY}/targets.json" "${REPO}" <<'PY'
import json, sys
path, tid = sys.argv[1:3]
reg = json.load(open(path, encoding="utf-8"))
assert type(reg["schema_version"]) is int and reg["schema_version"] == 1
assert tid in reg["targets"]
# inject unrelated target for later preservation check
reg["targets"]["other-target"] = {
  "active_run_json": "/tmp/does-not-need-to-exist-for-this-assert.json"
}
json.dump(reg, open(path, "w", encoding="utf-8"), indent=2)
open(path, "a", encoding="utf-8").write("\n")
PY

# Second run without --activate-new-run must fail; preserve other-target
if "${INIT}" "${URL}" \
  --policy-prefix "${POLICY}" \
  --run-id "smoke-011" \
  >/dev/null 2>"${TMP}/e"; then
  bad "second init without --activate-new-run should fail"
else
  grep -qi 'activate-new-run' "${TMP}/e" && ok "activate-new-run required" || bad "activate msg: $(cat "${TMP}/e")"
fi
python3 - "${POLICY}/targets.json" <<'PY'
import json, sys
reg = json.load(open(sys.argv[1], encoding="utf-8"))
assert "other-target" in reg["targets"], reg
print("other-target preserved")
PY
ok "unrelated target preserved after refused activation"

# With --activate-new-run
if "${INIT}" "${URL}" \
  --policy-prefix "${POLICY}" \
  --run-id "smoke-011" \
  --activate-new-run \
  >"${TMP}/act.txt" 2>"${TMP}/e"; then
  ok "activate-new-run allows new active run"
else
  bad "activate-new-run failed: $(cat "${TMP}/e")"
fi
python3 - "${POLICY}/targets.json" "${DATA}/review-runs/${REPO}/smoke-011/run.json" <<'PY'
import json, sys, os
reg = json.load(open(sys.argv[1], encoding="utf-8"))
want = os.path.realpath(sys.argv[2])
got = os.path.realpath(reg["targets"]["sample-repo"]["active_run_json"])
assert got == want, (got, want)
assert "other-target" in reg["targets"]
PY
ok "registry active_run_json updated; unrelated target kept"

# Existing run directory collision
mkdir -p "${DATA}/review-runs/${REPO}/dup-run"
if "${INIT}" "${URL}" \
  --policy-prefix "${POLICY}" \
  --run-id "dup-run" \
  --activate-new-run \
  >/dev/null 2>"${TMP}/e"; then
  bad "existing run dir should fail"
else
  grep -qi 'already exists' "${TMP}/e" && ok "existing run directory rejected" || bad "run exists msg: $(cat "${TMP}/e")"
fi

# Owner collision on same target id
OTHER_URL="https://github.com/OtherOrg/${REPO}.git"
# source still FixtureOrg — identity from URL OtherOrg will not match existing target's run identity
if "${INIT}" "${OTHER_URL}" \
  --policy-prefix "${POLICY}" \
  --run-id "other-owner-010" \
  --activate-new-run \
  >/dev/null 2>"${TMP}/e"; then
  bad "owner collision should fail"
else
  grep -Eqi 'collision|different repository identity' "${TMP}/e" \
    && ok "owner/target-id collision rejected" \
    || bad "collision msg: $(cat "${TMP}/e")"
fi

# Override target id avoids collision (but source path uses new id — seed it)
ALT_ID="sample-repo-otherorg"
ALT_SRC="${DATA}/repositories/${ALT_ID}"
seed_source "${ALT_SRC}" "OtherOrg" "${REPO}"
if "${INIT}" "${OTHER_URL}" \
  --policy-prefix "${POLICY}" \
  --target-id "${ALT_ID}" \
  --run-id "alt-010" \
  >"${TMP}/alt.txt" 2>"${TMP}/e"; then
  ok "--target-id override succeeds"
else
  bad "target-id override failed: $(cat "${TMP}/e")"
fi

# Dirty existing source rejected
echo dirty >>"${SRC}/README.md"
if "${INIT}" "${URL}" \
  --policy-prefix "${POLICY}" \
  --run-id "dirty-010" \
  --activate-new-run \
  >/dev/null 2>"${TMP}/e"; then
  bad "dirty source should fail"
else
  grep -qi 'dirty' "${TMP}/e" && ok "dirty existing source rejected" || bad "dirty msg: $(cat "${TMP}/e")"
fi
git -C "${SRC}" checkout -q -- README.md

# Identity mismatch on existing source (wrong origin)
git -C "${SRC}" remote set-url origin "https://github.com/WrongOrg/${REPO}.git"
if "${INIT}" "${URL}" \
  --policy-prefix "${POLICY}" \
  --run-id "mismatch-010" \
  --activate-new-run \
  >/dev/null 2>"${TMP}/e"; then
  bad "origin mismatch should fail"
else
  grep -qi 'identity mismatch' "${TMP}/e" && ok "origin identity mismatch rejected" || bad "mismatch msg: $(cat "${TMP}/e")"
fi
git -C "${SRC}" remote set-url origin "${URL}"

# Validator agrees with produced run (no report created)
BEFORE="$(find "${DATA}/review-runs/${REPO}/smoke-010/reports" -mindepth 1 | wc -l)"
if "${RUNNER}" --run-json "${RUN_JSON}" >/dev/null 2>"${TMP}/e"; then
  ok "produced run.json validates with hermes-vps-review"
else
  bad "runner validation failed: $(cat "${TMP}/e")"
fi
AFTER="$(find "${DATA}/review-runs/${REPO}/smoke-010/reports" -mindepth 1 | wc -l)"
[[ "${BEFORE}" -eq 0 && "${AFTER}" -eq 0 ]] && ok "init/validate created no report" || bad "report appeared"

# --- validation-before-activate regressions ---
fingerprint_tree() {
  find "$1" -type f -print0 2>/dev/null | sort -z | xargs -0 sha256sum
}

# Existing registry must remain byte-identical when validation fails after run create
REG_SNAP="$(sha256sum "${POLICY}/targets.json" | awk '{print $1}')"
PRIOR_RUN="${DATA}/review-runs/${REPO}/smoke-010"
PRIOR_SNAP="$(fingerprint_tree "${PRIOR_RUN}")"
ACTIVE_BEFORE="$(python3 -c "import json; print(json.load(open('${POLICY}/targets.json'))['targets']['${REPO}']['active_run_json'])")"
rm -f "${POLICY}/tasks/010-inventory.md"
FAIL_EXIST_ID="fail-val-existing"
FAIL_EXIST_ROOT="${DATA}/review-runs/${REPO}/${FAIL_EXIST_ID}"
if "${INIT}" "${URL}" \
  --policy-prefix "${POLICY}" \
  --run-id "${FAIL_EXIST_ID}" \
  --activate-new-run \
  >/dev/null 2>"${TMP}/e"; then
  bad "init should fail when shared validation cannot succeed"
else
  ok "init fails when shared validation fails (existing registry)"
fi
REG_AFTER="$(sha256sum "${POLICY}/targets.json" | awk '{print $1}')"
PRIOR_AFTER="$(fingerprint_tree "${PRIOR_RUN}")"
ACTIVE_AFTER="$(python3 -c "import json; print(json.load(open('${POLICY}/targets.json'))['targets']['${REPO}']['active_run_json'])")"
if [[ "${REG_SNAP}" == "${REG_AFTER}" && "${ACTIVE_BEFORE}" == "${ACTIVE_AFTER}" ]]; then
  ok "existing targets.json unchanged after validation failure"
else
  bad "registry mutated on validation failure"
fi
if [[ "${PRIOR_SNAP}" == "${PRIOR_AFTER}" ]]; then
  ok "prior run artifacts unchanged after validation failure"
else
  bad "prior run artifacts changed on validation failure"
fi
if [[ -d "${FAIL_EXIST_ROOT}/reports" && -f "${FAIL_EXIST_ROOT}/run.json" ]] \
  && grep -Fq "created: ${FAIL_EXIST_ROOT}" "${TMP}/e" \
  && grep -Fq "created: ${FAIL_EXIST_ROOT}/run.json" "${TMP}/e" \
  && grep -qi 'not a full rollback' "${TMP}/e" \
  && ! grep -Fq "changed: ${POLICY}/targets.json" "${TMP}/e" \
  && ! grep -Fq "created: ${POLICY}/targets.json" "${TMP}/e"; then
  ok "failure report lists new run paths; registry not listed as written"
else
  bad "failure report incomplete: $(cat "${TMP}/e")"
fi
# restore policy task for later checks
cp -a "${EXT}/tasks/010-inventory.md" "${POLICY}/tasks/010-inventory.md"

# Absent registry must remain absent when validation fails
DATA2="${TMP}/opt2/data"
POLICY2="${DATA2}/hermes-review"
mkdir -p "${POLICY2}"
cp -a "${EXT}/." "${POLICY2}/"
rm -f "${POLICY2}/targets.json"
REPO2="absent-reg-repo"
URL2="https://github.com/FixtureOrg/${REPO2}.git"
SRC2="${DATA2}/repositories/${REPO2}"
seed_source "${SRC2}" "FixtureOrg" "${REPO2}"
rm -f "${POLICY2}/tasks/010-inventory.md"
FAIL_ABSENT_ID="fail-val-absent"
FAIL_ABSENT_ROOT="${DATA2}/review-runs/${REPO2}/${FAIL_ABSENT_ID}"
if "${INIT}" "${URL2}" \
  --policy-prefix "${POLICY2}" \
  --run-id "${FAIL_ABSENT_ID}" \
  >/dev/null 2>"${TMP}/e2"; then
  bad "init should fail validation with absent registry + missing policy file"
else
  ok "init fails validation when registry was absent"
fi
if [[ ! -e "${POLICY2}/targets.json" ]]; then
  ok "absent targets.json remains absent after validation failure"
else
  bad "targets.json was created despite validation failure"
fi
if [[ -d "${FAIL_ABSENT_ROOT}" && -f "${FAIL_ABSENT_ROOT}/run.json" ]] \
  && grep -Fq "created: ${FAIL_ABSENT_ROOT}" "${TMP}/e2" \
  && ! grep -Fq "created: ${POLICY2}/targets.json" "${TMP}/e2"; then
  ok "absent-registry failure report lists new paths only"
else
  bad "absent-registry failure report wrong: $(cat "${TMP}/e2")"
fi

# Duplicate registry keys rejected by initializer load path
cp -a "${EXT}/tasks/010-inventory.md" "${POLICY}/tasks/010-inventory.md"
python3 - "${POLICY}" "${DATA}/review-runs/${REPO}/smoke-011/run.json" <<'PY'
import json, sys
policy, run_json = sys.argv[1:3]
raw = (
  '{\n'
  '  "schema_version": 1,\n'
  f'  "policy_prefix": {json.dumps(policy)},\n'
  '  "targets": {\n'
  f'    "sample-repo": {{"active_run_json": {json.dumps(run_json)}}},\n'
  f'    "sample-repo": {{"active_run_json": {json.dumps(run_json)}}}\n'
  '  }\n'
  '}\n'
)
open(f"{policy}/targets.json", "w", encoding="utf-8").write(raw)
PY
if "${INIT}" "${URL}" \
  --policy-prefix "${POLICY}" \
  --run-id "dup-reg-010" \
  --activate-new-run \
  >/dev/null 2>"${TMP}/e"; then
  bad "duplicate registry keys should fail"
else
  grep -qi 'duplicate' "${TMP}/e" && ok "duplicate registry keys rejected" || bad "dup reg msg: $(cat "${TMP}/e")"
fi

# Policy under an unrelated ancestor Git repo must not inherit that SHA
ANC="${TMP}/ancestor-git"
mkdir -p "${ANC}/opt/data"
git -C "${ANC}" init -q
git -C "${ANC}" config user.email "anc@example.invalid"
git -C "${ANC}" config user.name "anc"
echo marker >"${ANC}/marker.txt"
git -C "${ANC}" add marker.txt
git -C "${ANC}" commit -q -m "ancestor"
ANC_SHA="$(git -C "${ANC}" rev-parse HEAD)"
POLICY_A="${ANC}/opt/data/hermes-review"
mkdir -p "${POLICY_A}"
cp -a "${EXT}/." "${POLICY_A}/"
find "${POLICY_A}" -type d -name '__pycache__' -prune -exec rm -rf {} +
REPO_A="anc-repo"
URL_A="https://github.com/FixtureOrg/${REPO_A}.git"
SRC_A="${ANC}/opt/data/repositories/${REPO_A}"
seed_source "${SRC_A}" "FixtureOrg" "${REPO_A}"
if "${INIT}" "${URL_A}" \
  --policy-prefix "${POLICY_A}" \
  --run-id "anc-010" \
  >"${TMP}/anc.out" 2>"${TMP}/anc.err"; then
  python3 - "${ANC}/opt/data/review-runs/${REPO_A}/anc-010/run.json" "${ANC_SHA}" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
anc = sys.argv[2].lower()
tk = data["toolkit"]
assert tk["toolkit_revision"] == "unknown", tk
assert tk["toolkit_dirty"] is True, tk
assert tk["toolkit_revision"] != anc
PY
  ok "policy inside unrelated Git repo does not inherit ancestor revision"
else
  bad "ancestor-git init failed: $(cat "${TMP}/anc.err")"
fi

# Dirty toolkit when policy prefix is itself a Git worktree root
POL_GIT="${TMP}/policy-as-worktree"
mkdir -p "${POL_GIT}"
cp -a "${EXT}/." "${POL_GIT}/"
find "${POL_GIT}" -type d -name '__pycache__' -prune -exec rm -rf {} +
git -C "${POL_GIT}" init -q
git -C "${POL_GIT}" config user.email "pol@example.invalid"
git -C "${POL_GIT}" config user.name "pol"
git -C "${POL_GIT}" add -A
git -C "${POL_GIT}" commit -q -m "policy toolkit"
POL_SHA="$(git -C "${POL_GIT}" rev-parse HEAD)"
# nested data root: parent of policy-as-worktree
DATA_PG="$(dirname "${POL_GIT}")"
# seed source under sibling repositories/
REPO_PG="polgit-repo"
URL_PG="https://github.com/FixtureOrg/${REPO_PG}.git"
SRC_PG="${DATA_PG}/repositories/${REPO_PG}"
seed_source "${SRC_PG}" "FixtureOrg" "${REPO_PG}"
# dirty the policy worktree
echo dirty-toolkit >>"${POL_GIT}/README.md"
if "${INIT}" "${URL_PG}" \
  --policy-prefix "${POL_GIT}" \
  --run-id "polgit-dirty-010" \
  >"${TMP}/pg.out" 2>"${TMP}/pg.err"; then
  python3 - "${DATA_PG}/review-runs/${REPO_PG}/polgit-dirty-010/run.json" "${POL_SHA}" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
want = sys.argv[2].lower()
tk = data["toolkit"]
assert tk["toolkit_revision"] == want, tk
assert tk["toolkit_dirty"] is True, tk
PY
  ok "dirty policy worktree root records HEAD with toolkit_dirty true"
else
  bad "dirty policy-worktree init failed: $(cat "${TMP}/pg.err")"
fi
git -C "${POL_GIT}" checkout -q -- README.md
# Drop initializer-created untracked registry/lock so porcelain is clean again
rm -f "${POL_GIT}/targets.json" "${POL_GIT}/.init-hermes-review.lock"
if [[ -n "$(git -C "${POL_GIT}" status --porcelain)" ]]; then
  bad "policy worktree still dirty before clean provenance check: $(git -C "${POL_GIT}" status --porcelain)"
else
  if "${INIT}" "${URL_PG}" \
    --policy-prefix "${POL_GIT}" \
    --run-id "polgit-clean-010" \
    >"${TMP}/pg2.out" 2>"${TMP}/pg2.err"; then
    python3 - "${DATA_PG}/review-runs/${REPO_PG}/polgit-clean-010/run.json" "${POL_SHA}" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
want = sys.argv[2].lower()
tk = data["toolkit"]
assert tk["toolkit_revision"] == want, tk
assert tk["toolkit_dirty"] is False, tk
PY
    ok "clean policy worktree root records HEAD with toolkit_dirty false"
  else
    bad "clean policy-worktree init failed: $(cat "${TMP}/pg2.err")"
  fi
fi

# extensions/hermes untouched
if git -C "${ROOT}" status --porcelain -- extensions/hermes | grep . >/dev/null; then
  bad "extensions/hermes modified"
else
  ok "extensions/hermes unmodified"
fi

echo
echo "Summary: ${pass} passed, ${fail} failed"
if [[ "${fail}" -ne 0 ]]; then
  exit 1
fi
echo "PASS: hermes-vps-init fixture suite"
