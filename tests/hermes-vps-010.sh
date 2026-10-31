#!/usr/bin/env bash
# Stage 3 fixture tests for hermesVPS phase-010 runner and payload.
# Synthetic repos and temporary destinations only. No VPS / network.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXT="${ROOT}/extensions/hermesVPS"
RUNNER="${EXT}/bin/hermes-vps-review"
SCHEMA_SRC="${ROOT}/modules/security/files/security/findings.schema.json"
SCHEMA_DST="${EXT}/security-assets/findings.schema.json"

TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

fail=0
pass=0

ok() {
  pass=$((pass + 1))
  echo "PASS: $*"
}

bad() {
  fail=$((fail + 1))
  echo "FAIL: $*" >&2
}

need() {
  local c="$1"
  command -v "${c}" >/dev/null 2>&1 || {
    echo "FAIL: test host missing required command: ${c}" >&2
    exit 1
  }
}

need git
need python3
need cmp
need sha256sum

[[ -x "${RUNNER}" ]] || {
  echo "FAIL: runner not executable: ${RUNNER}" >&2
  exit 1
}

# --- payload static checks ---
if cmp -s "${SCHEMA_SRC}" "${SCHEMA_DST}"; then
  ok "findings.schema.json is an exact copy of the canonical schema"
else
  bad "findings.schema.json differs from canonical source"
fi

if grep -RIn '/home/acktarius' "${EXT}" >/dev/null 2>&1; then
  bad "developer-machine path /home/acktarius found under hermesVPS"
else
  ok "no /home/acktarius developer paths in hermesVPS tree"
fi

# Stale local-sandbox assumptions as runtime instructions (allow provenance notes)
if grep -RIn '/workspace/target' "${EXT}/rules" "${EXT}/tasks" "${EXT}/bin" \
  "${EXT}/BOOTSTRAP.md" "${EXT}/templates/phase-010-report.md" >/dev/null 2>&1; then
  bad "stale /workspace/target assumption in runtime instructions"
else
  ok "no /workspace/target in runtime rules/tasks/bin/bootstrap/010 template"
fi

if grep -RIn '\.repo-kit/hermes/reports' "${EXT}/rules" "${EXT}/tasks" "${EXT}/bin" >/dev/null 2>&1; then
  bad "stale .repo-kit/hermes/reports path in runtime rules/tasks/bin"
else
  ok "no .repo-kit/hermes/reports in runtime rules/tasks/bin"
fi

for rel in \
  rules/rules_000-safety-and-scope.md \
  rules/rules_005-report-output.md \
  rules/rules_010-inventory.md \
  tasks/010-inventory.md \
  templates/phase-010-report.md \
  security-assets/findings.schema.json \
  security-assets/README.md \
  PROVENANCE.md \
  BOOTSTRAP.md \
  bin/hermes-vps-review \
  bin/hermes-vps-artifacts \
  bin/init-hermes-review \
  lib/hermes_vps_common.py \
  lib/hermes_vps_artifacts.py; do
  if [[ -e "${EXT}/${rel}" ]]; then
    ok "payload has ${rel}"
  else
    bad "missing payload file ${rel}"
  fi
done

# --- fixture layout helpers ---
POLICY="${TMP}/policy with spaces/hermes-review"
SRC="${TMP}/repositories/example-repo"
RUN="${TMP}/review-runs/example-repo/run-010"
mkdir -p "${POLICY}" "${SRC}" "${RUN}/reports"

# Copy policy payload into temp policy prefix (simulate upload)
cp -a "${EXT}/." "${POLICY}/"
# Uploaded/copied trees must not carry developer __pycache__ into fixtures
find "${POLICY}" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "${POLICY}" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

# Init synthetic clean repo
git -C "${SRC}" init -q
git -C "${SRC}" config user.email "test@example.com"
git -C "${SRC}" config user.name "Test"
echo "hello" >"${SRC}/README.md"
git -C "${SRC}" add README.md
git -C "${SRC}" commit -q -m "init"
SHA="$(git -C "${SRC}" rev-parse HEAD)"

write_run() {
  local out="$1"
  local policy="$2"
  local src="$3"
  local run_root="$4"
  local commit="$5"
  local extra_phase="${6:-}"
  python3 - "$out" "$policy" "$src" "$run_root" "$commit" "${extra_phase}" <<'PY'
import json, sys
out, policy, src, run_root, commit, extra = sys.argv[1:7]
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
}
if extra == "phase020":
    data["phase_request"]["phase"] = "020"
    data["phase_request"]["phase_name"] = "threat-model"
path = out
with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
PY
}

RUN_JSON="${RUN}/run.json"
write_run "${RUN_JSON}" "${POLICY}" "${SRC}" "${RUN}" "${SHA}"

# Snapshot fixture mtimes/content fingerprint before runner
fingerprint() {
  find "${SRC}" "${RUN}" -type f -print0 | sort -z | xargs -0 sha256sum
}
before="$(fingerprint)"

PROMPT_OUT="${TMP}/prompt.txt"
# --phase 010 is now required (intentional CLI compatibility change in phases 020-080 scope)
if "${RUNNER}" --phase 010 --run-json "${RUN_JSON}" >"${PROMPT_OUT}" 2>"${TMP}/prompt.err"; then
  ok "successful validation exits 0"
else
  bad "successful validation failed: $(cat "${TMP}/prompt.err")"
fi

if grep -Fq "Execute ONLY phase 010" "${PROMPT_OUT}" \
  && grep -Fq "${POLICY}/tasks/010-inventory.md" "${PROMPT_OUT}" \
  && grep -Fq "ARTIFACT REGISTRATION" "${PROMPT_OUT}" \
  && grep -Fq "hermes-vps-artifacts" "${PROMPT_OUT}" \
  && grep -Fq "${SHA}" "${PROMPT_OUT}" \
  && grep -Fq "Then STOP" "${PROMPT_OUT}"; then
  ok "prompt identifies inputs, registration command, and stop instruction"
else
  bad "prompt missing required content"
  sed -n '1,80p' "${PROMPT_OUT}" >&2 || true
fi

# Representative prompt saved for the Stage 3 report
cp "${PROMPT_OUT}" "${TMP}/representative-prompt.txt"
# Copy to a stable path under TMP that the outer harness can still... actually
# tests delete TMP. Echo a short excerpt later via the script printing at end.
REPR_SNIPPET="$(grep -E '^(POLICY PREFIX|SOURCE COMMIT|ARTIFACT REGISTRATION|  5\.|INSTRUCTIONS|  - Execute ONLY|  - Then STOP)' "${PROMPT_OUT}" | head -n 20)"

after="$(fingerprint)"
if [[ "${before}" == "${after}" ]]; then
  ok "runner validation made no persistent fixture file changes"
else
  bad "fixture files changed after runner validation"
fi

# No bytecode writes under policy during normal runner invocation
# (entry point disables bytecode; do not rely on ambient PYTHONDONTWRITEBYTECODE)
policy_fp() {
  find "${POLICY}" -type f -print0 | sort -z | xargs -0 sha256sum
}
find "${POLICY}" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "${POLICY}" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
POL_BEFORE="$(policy_fp)"
if env -u PYTHONDONTWRITEBYTECODE "${RUNNER}" --phase 010 --run-json "${RUN_JSON}" >/dev/null 2>"${TMP}/e"; then
  if [[ -z "$(find "${POLICY}" -type d -name '__pycache__' -print)" ]] \
    && [[ -z "$(find "${POLICY}" -type f \( -name '*.pyc' -o -name '*.pyo' \) -print)" ]] \
    && [[ "${POL_BEFORE}" == "$(policy_fp)" ]]; then
    ok "runner writes no bytecode under policy without ambient PYTHONDONTWRITEBYTECODE"
  else
    bad "bytecode or policy file changes after runner: $(find "${POLICY}" -name '__pycache__' -o -name '*.pyc' | head)"
  fi
else
  bad "bytecode-check runner invocation failed: $(cat "${TMP}/e")"
fi

# malformed JSON
echo '{not json' >"${TMP}/bad.json"
if "${RUNNER}" --phase 010 --run-json "${TMP}/bad.json" >"${TMP}/o" 2>"${TMP}/e"; then
  bad "malformed JSON should fail"
else
  grep -qi 'malformed JSON' "${TMP}/e" && ok "malformed JSON rejected" || bad "malformed JSON message unclear: $(cat "${TMP}/e")"
fi

# invalid field type
python3 - "${RUN_JSON}" "${TMP}/badtype.json" <<'PY'
import json, sys
src, dst = sys.argv[1:3]
with open(src, encoding="utf-8") as fh:
    data = json.load(fh)
data["schema_version"] = "1"
with open(dst, "w", encoding="utf-8") as fh:
    json.dump(data, fh)
PY
if "${RUNNER}" --phase 010 --run-json "${TMP}/badtype.json" >/dev/null 2>"${TMP}/e"; then
  bad "invalid field type should fail"
else
  grep -q 'schema_version' "${TMP}/e" && ok "invalid field type rejected" || bad "type error unclear: $(cat "${TMP}/e")"
fi

# missing policy file
rm -f "${POLICY}/tasks/010-inventory.md"
if "${RUNNER}" --phase 010 --run-json "${RUN_JSON}" >/dev/null 2>"${TMP}/e"; then
  bad "missing task should fail"
else
  grep -q 'missing required policy' "${TMP}/e" && ok "missing policy/task rejected" || bad "missing policy message unclear"
fi
# restore task for later tests
cp -a "${EXT}/tasks/010-inventory.md" "${POLICY}/tasks/010-inventory.md"

# dirty worktree
echo dirty >>"${SRC}/README.md"
if "${RUNNER}" --phase 010 --run-json "${RUN_JSON}" >/dev/null 2>"${TMP}/e"; then
  bad "dirty worktree should fail"
else
  grep -qi 'dirty' "${TMP}/e" && ok "dirty worktree rejected" || bad "dirty message unclear"
fi
git -C "${SRC}" checkout -q -- README.md

# commit mismatch
python3 - "${RUN_JSON}" "${TMP}/mismatch.json" <<'PY'
import json, sys
src, dst = sys.argv[1:3]
with open(src, encoding="utf-8") as fh:
    data = json.load(fh)
data["source"]["commit"] = "0" * 40
with open(dst, "w", encoding="utf-8") as fh:
    json.dump(data, fh)
PY
if "${RUNNER}" --phase 010 --run-json "${TMP}/mismatch.json" >/dev/null 2>"${TMP}/e"; then
  bad "commit mismatch should fail"
else
  grep -qi 'mismatch' "${TMP}/e" && ok "commit mismatch rejected" || bad "mismatch message unclear"
fi

# paths containing spaces already used for POLICY — reconfirm success
write_run "${RUN_JSON}" "${POLICY}" "${SRC}" "${RUN}" "${SHA}"
if "${RUNNER}" --phase 010 --run-json "${RUN_JSON}" >/dev/null 2>"${TMP}/e"; then
  ok "paths containing spaces accepted when valid"
else
  bad "spaces path failed: $(cat "${TMP}/e")"
fi

# output inside source
write_run "${TMP}/inside-src.json" "${POLICY}" "${SRC}" "${SRC}/nested-run" "${SHA}"
mkdir -p "${SRC}/nested-run/reports"
if "${RUNNER}" --phase 010 --run-json "${TMP}/inside-src.json" >/dev/null 2>"${TMP}/e"; then
  bad "output inside source should fail"
else
  grep -qi 'inside the source' "${TMP}/e" && ok "output inside source rejected" || bad "inside-source message unclear: $(cat "${TMP}/e")"
fi

# output inside policy
write_run "${TMP}/inside-pol.json" "${POLICY}" "${SRC}" "${POLICY}/nested-run" "${SHA}"
mkdir -p "${POLICY}/nested-run/reports"
if "${RUNNER}" --phase 010 --run-json "${TMP}/inside-pol.json" >/dev/null 2>"${TMP}/e"; then
  bad "output inside policy should fail"
else
  grep -qi 'inside the policy' "${TMP}/e" && ok "output inside policy rejected" || bad "inside-policy message unclear: $(cat "${TMP}/e")"
fi

# symlink escape: run_root symlink into source
ESCAPE_LINK="${TMP}/escape-run"
ln -s "${SRC}" "${ESCAPE_LINK}"
write_run "${TMP}/symlink.json" "${POLICY}" "${SRC}" "${ESCAPE_LINK}" "${SHA}"
if "${RUNNER}" --phase 010 --run-json "${TMP}/symlink.json" >/dev/null 2>"${TMP}/e"; then
  bad "symlink escape run_root should fail"
else
  grep -qi 'inside the source' "${TMP}/e" && ok "symlink escape run_root rejected" || bad "symlink escape message unclear: $(cat "${TMP}/e")"
fi

# path traversal in configured path
python3 - "${RUN_JSON}" "${TMP}/trav.json" "${POLICY}" <<'PY'
import json, sys, os
src, dst, policy = sys.argv[1:4]
with open(src, encoding="utf-8") as fh:
    data = json.load(fh)
data["policy_prefix"] = policy + "/../" + os.path.basename(policy)
with open(dst, "w", encoding="utf-8") as fh:
    json.dump(data, fh)
PY
if "${RUNNER}" --phase 010 --run-json "${TMP}/trav.json" >/dev/null 2>"${TMP}/e"; then
  bad "path with '..' segments should fail"
else
  grep -q "\\.\\." "${TMP}/e" && ok "path traversal '..' rejected" || bad "traversal message unclear: $(cat "${TMP}/e")"
fi

# invalid run_id
python3 - "${RUN_JSON}" "${TMP}/badid.json" <<'PY'
import json, sys
src, dst = sys.argv[1:3]
with open(src, encoding="utf-8") as fh:
    data = json.load(fh)
data["run_id"] = "../evil"
with open(dst, "w", encoding="utf-8") as fh:
    json.dump(data, fh)
PY
if "${RUNNER}" --phase 010 --run-json "${TMP}/badid.json" >/dev/null 2>"${TMP}/e"; then
  bad "invalid run_id should fail"
else
  grep -q 'run_id' "${TMP}/e" && ok "invalid run_id rejected" || bad "run_id message unclear"
fi

# manifest/run identity mismatch
python3 - "${RUN}" "${SHA}" "${POLICY}" "${SRC}" <<'PY'
import json, sys, os
run, sha, policy, src = sys.argv[1:5]
manifest = {
  "schema_version": 1,
  "run_id": "OTHER-RUN",
  "source": {"identity": "fixture/example-repo", "path": src, "commit": sha},
  "policy": {"prefix": policy},
  "artifacts": [],
}
with open(os.path.join(run, "manifest.json"), "w", encoding="utf-8") as fh:
    json.dump(manifest, fh)
PY
write_run "${RUN_JSON}" "${POLICY}" "${SRC}" "${RUN}" "${SHA}"
if "${RUNNER}" --phase 010 --run-json "${RUN_JSON}" >/dev/null 2>"${TMP}/e"; then
  bad "manifest run_id mismatch should fail"
else
  grep -qi 'identity mismatch' "${TMP}/e" && ok "manifest/run identity mismatch rejected" || bad "manifest mismatch message unclear: $(cat "${TMP}/e")"
fi
rm -f "${RUN}/manifest.json"

# agreeing empty manifest should pass
python3 - "${RUN}" "${SHA}" "${POLICY}" "${SRC}" <<'PY'
import json, sys, os
run, sha, policy, src = sys.argv[1:5]
manifest = {
  "schema_version": 1,
  "run_id": "run-010",
  "source": {"identity": "fixture/example-repo", "path": src, "commit": sha},
  "policy": {"prefix": policy},
  "artifacts": [],
}
with open(os.path.join(run, "manifest.json"), "w", encoding="utf-8") as fh:
    json.dump(manifest, fh)
PY
if "${RUNNER}" --phase 010 --run-json "${RUN_JSON}" >/dev/null 2>"${TMP}/e"; then
  ok "agreeing empty manifest accepted"
else
  bad "agreeing empty manifest failed: $(cat "${TMP}/e")"
fi

# relative run-json path rejected
if (cd "${RUN}" && "${RUNNER}" --phase 010 --run-json "./run.json") >/dev/null 2>"${TMP}/e"; then
  bad "relative --run-json should fail"
else
  grep -qi 'absolute' "${TMP}/e" && ok "relative --run-json rejected" || bad "relative path message unclear"
fi

# --- external-review validation gaps ---

# schema_version boolean true (JSON true → Python True == 1 without exact-type check)
python3 - "${RUN_JSON}" "${TMP}/schema-true.json" <<'PY'
import json, sys
src, dst = sys.argv[1:3]
with open(src, encoding="utf-8") as fh:
    data = json.load(fh)
data["schema_version"] = True
with open(dst, "w", encoding="utf-8") as fh:
    json.dump(data, fh)
PY
if "${RUNNER}" --phase 010 --run-json "${TMP}/schema-true.json" >/dev/null 2>"${TMP}/e"; then
  bad "schema_version true should fail"
else
  grep -q 'schema_version' "${TMP}/e" && ok "schema_version true rejected" || bad "schema true msg: $(cat "${TMP}/e")"
fi

# schema_version numeric 1.0
python3 - "${RUN_JSON}" "${TMP}/schema-float.json" <<'PY'
import json, sys
src, dst = sys.argv[1:3]
with open(src, encoding="utf-8") as fh:
    data = json.load(fh)
data["schema_version"] = 1.0
with open(dst, "w", encoding="utf-8") as fh:
    json.dump(data, fh)
PY
if "${RUNNER}" --phase 010 --run-json "${TMP}/schema-float.json" >/dev/null 2>"${TMP}/e"; then
  bad "schema_version 1.0 should fail"
else
  grep -q 'schema_version' "${TMP}/e" && ok "schema_version 1.0 rejected" || bad "schema float msg: $(cat "${TMP}/e")"
fi

# missing reports/
RUN_MISS="${TMP}/review-runs/example-repo/run-missing-reports"
mkdir -p "${RUN_MISS}"
write_run "${TMP}/missing-reports.json" "${POLICY}" "${SRC}" "${RUN_MISS}" "${SHA}"
if "${RUNNER}" --phase 010 --run-json "${TMP}/missing-reports.json" >/dev/null 2>"${TMP}/e"; then
  bad "missing reports/ should fail (must not print success prompt)"
else
  if grep -qi 'reports directory missing' "${TMP}/e" \
    && ! grep -Fq 'Execute ONLY phase 010' "${TMP}/e"; then
    ok "missing reports/ rejected with actionable error"
  else
    bad "missing reports/ message unclear: $(cat "${TMP}/e")"
  fi
fi

# valid prepared reports/ (explicit; success path already uses RUN/reports)
RUN_OK="${TMP}/review-runs/example-repo/run-prepared-reports"
mkdir -p "${RUN_OK}/reports"
write_run "${TMP}/prepared-reports.json" "${POLICY}" "${SRC}" "${RUN_OK}" "${SHA}"
if "${RUNNER}" --phase 010 --run-json "${TMP}/prepared-reports.json" >/dev/null 2>"${TMP}/e"; then
  ok "valid prepared reports/ accepted"
else
  bad "prepared reports/ failed: $(cat "${TMP}/e")"
fi

# reports/ symlink to the source
RUN_RS="${TMP}/review-runs/example-repo/run-reports-src"
mkdir -p "${RUN_RS}"
ln -s "${SRC}" "${RUN_RS}/reports"
write_run "${TMP}/reports-src.json" "${POLICY}" "${SRC}" "${RUN_RS}" "${SHA}"
if "${RUNNER}" --phase 010 --run-json "${TMP}/reports-src.json" >/dev/null 2>"${TMP}/e"; then
  bad "reports/ symlink to source should fail"
else
  grep -Eqi 'strictly inside the run root|into the source' "${TMP}/e" \
    && ok "reports/ symlink to source rejected" \
    || bad "reports→source msg: $(cat "${TMP}/e")"
fi

# reports/ symlink to the policy
RUN_RP="${TMP}/review-runs/example-repo/run-reports-pol"
mkdir -p "${RUN_RP}"
ln -s "${POLICY}" "${RUN_RP}/reports"
write_run "${TMP}/reports-pol.json" "${POLICY}" "${SRC}" "${RUN_RP}" "${SHA}"
if "${RUNNER}" --phase 010 --run-json "${TMP}/reports-pol.json" >/dev/null 2>"${TMP}/e"; then
  bad "reports/ symlink to policy should fail"
else
  grep -Eqi 'strictly inside the run root|into the policy' "${TMP}/e" \
    && ok "reports/ symlink to policy rejected" \
    || bad "reports→policy msg: $(cat "${TMP}/e")"
fi

# reports/ symlink to unrelated directory outside the run root
OUTSIDE="${TMP}/unrelated-outside"
mkdir -p "${OUTSIDE}"
RUN_RO="${TMP}/review-runs/example-repo/run-reports-out"
mkdir -p "${RUN_RO}"
ln -s "${OUTSIDE}" "${RUN_RO}/reports"
write_run "${TMP}/reports-out.json" "${POLICY}" "${SRC}" "${RUN_RO}" "${SHA}"
if "${RUNNER}" --phase 010 --run-json "${TMP}/reports-out.json" >/dev/null 2>"${TMP}/e"; then
  bad "reports/ symlink outside run root should fail"
else
  grep -qi 'strictly inside the run root' "${TMP}/e" \
    && ok "reports/ symlink outside run root rejected" \
    || bad "reports→outside msg: $(cat "${TMP}/e")"
fi

# nested source path rather than worktree root
mkdir -p "${SRC}/nested-dir"
echo nested >"${SRC}/nested-dir/file.txt"
# keep parent worktree clean: the nested file is untracked → would dirty parent;
# for nested-path test we point source.path at nested-dir (which is not a root).
write_run "${TMP}/nested-src.json" "${POLICY}" "${SRC}/nested-dir" "${RUN_OK}" "${SHA}"
if "${RUNNER}" --phase 010 --run-json "${TMP}/nested-src.json" >/dev/null 2>"${TMP}/e"; then
  bad "nested source path should fail"
else
  grep -Eqi 'worktree root|not a usable Git worktree|non-bare' "${TMP}/e" \
    && ok "nested source path rejected" \
    || bad "nested source msg: $(cat "${TMP}/e")"
fi
rm -rf "${SRC}/nested-dir"

# bare repository
BARE="${TMP}/repositories/example-bare.git"
git clone --bare -q "${SRC}" "${BARE}"
write_run "${TMP}/bare-src.json" "${POLICY}" "${BARE}" "${RUN_OK}" "${SHA}"
if "${RUNNER}" --phase 010 --run-json "${TMP}/bare-src.json" >/dev/null 2>"${TMP}/e"; then
  bad "bare repository should fail"
else
  grep -Eqi 'non-bare|worktree' "${TMP}/e" \
    && ok "bare repository rejected" \
    || bad "bare repo msg: $(cat "${TMP}/e")"
fi

# legitimate linked worktree (.git file)
LINKED="${TMP}/repositories/example-linked"
git -C "${SRC}" worktree add -q "${LINKED}" HEAD
LINKED_SHA="$(git -C "${LINKED}" rev-parse HEAD)"
RUN_LW="${TMP}/review-runs/example-repo/run-linked"
mkdir -p "${RUN_LW}/reports"
write_run "${TMP}/linked-wt.json" "${POLICY}" "${LINKED}" "${RUN_LW}" "${LINKED_SHA}"
if "${RUNNER}" --phase 010 --run-json "${TMP}/linked-wt.json" >/dev/null 2>"${TMP}/e"; then
  ok "legitimate linked worktree accepted"
else
  bad "linked worktree failed: $(cat "${TMP}/e")"
fi

echo
echo "==== representative prompt excerpt ===="
echo "${REPR_SNIPPET:-<no matching lines>}"
echo "==== end excerpt ===="
echo
echo "Summary: ${pass} passed, ${fail} failed"
if [[ "${fail}" -ne 0 ]]; then
  exit 1
fi
echo "PASS: hermes-vps-010 fixture suite"
