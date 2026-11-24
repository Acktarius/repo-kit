#!/usr/bin/env bash
# Contract checks for Stage 04A scanner planning. Text checks show that the
# written contract and its consumers agree. They do not show that a reviewer
# follows them, and they do not show scanner isolation.
# Synthetic repos only. No network, installs, or target execution.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXT="${ROOT}/extensions/hermesVPS"
RUNNER="${EXT}/bin/hermes-vps-review"

fail=0
ok() { echo "PASS: $*"; }
bad() { echo "FAIL: $*" >&2; fail=1; }

need() {
  command -v "$1" >/dev/null 2>&1 || { echo "FAIL: missing host command $1" >&2; exit 1; }
}
need git
need python3
need cmp
need grep

PLAN="${ROOT}/modules/security/files/security/scanner-planning.md"
COPY="${EXT}/security-assets/scanner-planning.md"
HERMES_RULE="${ROOT}/extensions/hermes/rules/rules_030-scan-plan.md"
HERMES_TASK="${ROOT}/extensions/hermes/tasks/030-scan-plan.md"
VPS_RULE="${EXT}/rules/rules_030-scan-plan.md"
VPS_TASK="${EXT}/tasks/030-scan-plan.md"
VPS_TEMPLATE="${EXT}/templates/phase-030-report.md"
PLANNER="${ROOT}/modules/security/files/.cursor/rules/20-security-planner.mdc"
COMMAND="${ROOT}/modules/security/files/.cursor/commands/00-security-plan-hardening.md"

have() {
  local file="$1" needle="$2" label="$3"
  local flat
  flat="$(tr '\n' ' ' <"${file}")"
  if grep -Fq -- "${needle}" <<<"${flat}"; then
    ok "${label}"
  else
    bad "${label} (missing: ${needle})"
  fi
}

if cmp -s "${PLAN}" "${COPY}"; then
  ok "hermesVPS scanner-planning.md matches the canonical file"
else
  bad "hermesVPS scanner-planning.md drifted"
fi

have "${PLAN}" '`pending_verification` is not ready for execution.' "pending verification is not execution-ready"
have "${PLAN}" "A scanner hit is an unreviewed lead, not a supported finding." "a hit stays an unreviewed lead"
have "${PLAN}" "Scanner results do not mark source-review coverage as \`covered\`." "scanner results are not source-review coverage"
have "${PLAN}" "security/findings-reviewed.json" "handoff does not write the reviewed findings store"
have "${PLAN}" "Do not invent \`entrySink\`" "handoff does not invent entrySink"
have "${PLAN}" "Do not allocate an \`SG-*\` id" "handoff does not allocate SG ids"
have "${PLAN}" "NOT executable" "examples are labeled not executable"
have "${PLAN}" "Do not require a phase-050 surface inventory." "phase 030 does not require phase 050"
have "${HERMES_RULE}" "This phase produces a plan, not a scan." "local Rule 030 stays plan-only"
have "${HERMES_RULE}" '`pending_verification` is not ready for execution.' "local Rule 030 does not treat pending verification as ready"
have "${HERMES_RULE}" "does not depend on a phase-050 inventory" "local Rule 030 does not depend on phase 050"
have "${HERMES_TASK}" "This task produces a plan, not a scan." "local task stays plan-only"
have "${HERMES_TASK}" "scanner-planning.md" "local task reads the planning contract"
have "${VPS_RULE}" "Do **not** install, download, or run" "hermesVPS Rule 030 stays plan-only"
have "${VPS_RULE}" '`pending_verification` is not ready for execution.' "hermesVPS Rule 030 does not treat pending verification as ready"
have "${VPS_RULE}" "does not depend on a phase-050 inventory" "hermesVPS Rule 030 does not depend on phase 050"
have "${VPS_TASK}" "This task produces a plan, not a scan." "hermesVPS task stays plan-only"
have "${VPS_TASK}" "security-assets/scanner-planning.md" "hermesVPS task reads the bundled contract"
have "${VPS_TEMPLATE}" "hermes-vps-report:" "phase 030 template keeps the report identity marker"
have "${VPS_TEMPLATE}" 'State: `complete` | `incomplete` | `blocked`' "phase 030 template keeps the completion line"
have "${PLANNER}" "A manual plan does not" "planner does not force a scanner table onto a manual plan"
have "${COMMAND}" "A manual plan does not need that table." "plan command does not force a scanner table"

python3 - "${EXT}" "${VPS_TEMPLATE}" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from lib.hermes_vps_phases import PHASE_TABLE
template = sys.argv[2]
info = PHASE_TABLE["030"]
if info.prereqs.phases != ["010", "020"]:
    raise SystemExit(f"phase 030 prerequisites changed: {info.prereqs.phases}")
rel = "security-assets/scanner-planning.md"
if rel not in info.policy_files:
    raise SystemExit("phase 030 policy files omit scanner-planning.md")
if "security-assets/surface-inventory.md" in info.policy_files:
    raise SystemExit("phase 030 requires the phase-050 inventory")
for phase, other in PHASE_TABLE.items():
    if phase != "030" and rel in other.policy_files:
        raise SystemExit(f"phase {phase} requires scanner-planning.md")
text = open(template, encoding="utf-8").read().splitlines()
if not text[0].startswith("<!-- hermes-vps-report:"):
    raise SystemExit("phase 030 template lost its identity header")
states = [line for line in text if line.startswith("State:")]
if states != ["State: `complete` | `incomplete` | `blocked`"]:
    raise SystemExit(f"phase 030 completion line changed: {states}")
print("PASS: phase 030 policy gate, prerequisites, and completion line")
PY

# No scanner runner, installer, or importer in the planning contract or Rule 030.
for file in "${PLAN}" "${COPY}" "${HERMES_RULE}" "${HERMES_TASK}" "${VPS_RULE}" "${VPS_TASK}" "${VPS_TEMPLATE}"; do
  if grep -nE 'subprocess|os\.system|Popen|curl |wget |pip install|npm install' "${file}" >/dev/null; then
    bad "scanner execution wording in ${file}"
  fi
done
ok "planning files do not name a scanner invocation mechanism"

# Runner: missing contract fails closed before a prompt.
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT
POLICY="${TMP}/policy"
SRC="${TMP}/src"
RUN="${TMP}/run"
mkdir -p "${POLICY}" "${SRC}" "${RUN}/reports"
cp -a "${EXT}/." "${POLICY}/"
find "${POLICY}" -type d -name '__pycache__' -prune -exec rm -rf {} +
git -C "${SRC}" init -q
git -C "${SRC}" config user.email "test@example.com"
git -C "${SRC}" config user.name "Test"
echo hello >"${SRC}/README.md"
git -C "${SRC}" add README.md
git -C "${SRC}" commit -q -m init
SHA="$(git -C "${SRC}" rev-parse HEAD)"
RUN_JSON="${RUN}/run.json"
python3 - "${RUN_JSON}" "${POLICY}" "${SRC}" "${RUN}" "${SHA}" <<'PY'
import json, sys
out, policy, src, run_root, commit = sys.argv[1:6]
data = {
  "schema_version": 1,
  "run_id": "run-030",
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

rm -f "${POLICY}/security-assets/scanner-planning.md"
if "${RUNNER}" --phase 030 --run-json "${RUN_JSON}" \
  >"${TMP}/missing-out.txt" 2>"${TMP}/missing-err.txt"; then
  bad "runner printed a phase 030 prompt without the planning contract"
else
  if grep -Fq "missing required policy" "${TMP}/missing-err.txt" \
    && grep -Fq "scanner-planning.md" "${TMP}/missing-err.txt" \
    && [[ ! -s "${TMP}/missing-out.txt" ]]; then
    ok "missing planning contract is rejected before a phase 030 prompt"
  else
    bad "missing planning contract was not rejected cleanly: $(cat "${TMP}/missing-err.txt")"
  fi
fi

cp -f "${PLAN}" "${POLICY}/security-assets/scanner-planning.md"
if "${RUNNER}" --phase 030 --run-json "${RUN_JSON}" \
  >"${TMP}/present-out.txt" 2>"${TMP}/present-err.txt"; then
  bad "phase 030 prompt ran without phase 010"
else
  if grep -Fq "phase-010" "${TMP}/present-err.txt" \
    && ! grep -Fq "missing required policy" "${TMP}/present-err.txt" \
    && [[ ! -s "${TMP}/present-out.txt" ]]; then
    ok "present planning contract passes the policy gate and still requires phase 010"
  else
    bad "present planning contract did not reach the phase-010 gate: $(cat "${TMP}/present-err.txt")"
  fi
fi

if [[ "${fail}" -ne 0 ]]; then
  echo "FAILED" >&2
  exit 1
fi
echo "OK"
