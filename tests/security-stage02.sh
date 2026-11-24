#!/usr/bin/env bash
# Contract checks for the Stage 02 surface inventory and the findings-summary
# wording. Text and installer checks do not show that a reviewer follows them.
# Synthetic repos only. No network, installs, or target execution.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXT="${ROOT}/extensions/hermesVPS"
RUNNER="${EXT}/bin/hermes-vps-review"
ART="${EXT}/bin/hermes-vps-artifacts"
STAMP="${ROOT}/tests/hermes_vps_stamp.py"

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

REVIEWER="${ROOT}/modules/security/files/.cursor/rules/30-security-reviewer.mdc"
CATALOG="${ROOT}/modules/security/files/security/weakness-classes.md"
INVENTORY="${ROOT}/modules/security/files/security/surface-inventory.md"
HERMES_RULE="${ROOT}/extensions/hermes/rules/rules_050-source-review.md"
HERMES_TASK="${ROOT}/extensions/hermes/tasks/050-source-review.md"
VPS_RULE="${ROOT}/extensions/hermesVPS/rules/rules_050-source-review.md"
VPS_TASK="${ROOT}/extensions/hermesVPS/tasks/050-source-review.md"
VPS_TEMPLATE="${ROOT}/extensions/hermesVPS/templates/phase-050-report.md"
COMMAND="${ROOT}/modules/security/files/.cursor/commands/01-security-review-priority-1.md"

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

# --- Part A: findings summary is a line, not a blocked-review outcome ---
have "${REVIEWER}" 'Say exactly: `no valid findings`.' "reviewer keeps the literal findings line"
have "${REVIEWER}" "standalone line" "findings line is standalone"
have "${REVIEWER}" "not the entire response" "findings line is not the entire response"
have "${REVIEWER}" "does not mean the application is secure" "findings line is not a security claim"
have "${REVIEWER}" "blocked or incomplete" "unavailable inputs use blocked or incomplete"
have "${REVIEWER}" 'Do not use `no valid findings` as that outcome.' "blocked review does not use the findings line"
have "${REVIEWER}" "completion limits" "limited reviews keep completion limits with the line"
have "${COMMAND}" 'say exactly: `no valid findings for Priority 1`.' "priority command keeps its own findings line"
have "${COMMAND}" "blocked or incomplete" "priority command defers to the blocked outcome"

# --- Inventory contract sections, columns, examples ---
for section in \
  "## 1. Review scope and inspection limits" \
  "## 2. Entry-point and sensitive-operation inventory" \
  "## 3. Persisted-input and second-order flows" \
  "## 4. Coverage linkage and gaps"
do
  have "${INVENTORY}" "${section}" "contract has ${section}"
done
have "${INVENTORY}" "surface_id | kind/entry | evidence | trust boundary/inputs | controls observed | sensitive operation | class IDs | review state/limits" "surface table columns"
have "${INVENTORY}" "flow_id | untrusted source/writer | store or handoff | reader/consumer | sensitive use | controls/evidence | limits" "flow table columns"
have "${INVENTORY}" "An inventory does not mark any weakness class \`covered\`." "inventory does not upgrade coverage"
have "${INVENTORY}" "They are not review findings" "examples are labeled as examples"
have "${INVENTORY}" "### Example 1 — object-scoped handler" "example: object-scoped handler"
have "${INVENTORY}" "### Example 2 — stored input, consumer unresolved" "example: unresolved stored flow"
have "${INVENTORY}" "### Example 3 — CLI and queue inputs, not an HTTP service" "example: CLI and queue"
have "${INVENTORY}" "### Example 4 — diff-scoped review with gaps" "example: diff-scoped gaps"
have "${INVENTORY}" "queue-consumer" "example includes a queue consumer"
have "${CATALOG}" "An inventory does not mark any weakness class \`covered\`." "catalog does not treat inventory as coverage"

# --- Three consumers agree, without copying the contract ---
for pair in \
  "${REVIEWER}|security/surface-inventory.md" \
  "${HERMES_RULE}|.repo-kit/hermes/review-rules/surface-inventory.md" \
  "${VPS_RULE}|security-assets/surface-inventory.md"
do
  file="${pair%%|*}"
  needle="${pair#*|}"
  have "${file}" "${needle}" "$(basename "${file}") names its inventory path"
  have "${file}" "An inventory does not mark any weakness class \`covered\`." "$(basename "${file}") does not upgrade inventory to coverage"
done

have "${HERMES_RULE}" "Review scope and inspection limits" "local Hermes rule names scope section"
have "${HERMES_RULE}" "Entry-point and sensitive-operation inventory" "local Hermes rule names surface table"
have "${HERMES_RULE}" "Persisted-input and second-order flows" "local Hermes rule names flow table"
have "${HERMES_RULE}" 'Section 7 stays "Coverage and completion state".' "local Hermes keeps section 7"
have "${HERMES_RULE}" '"No supported findings within the completed scope."' "local Hermes keeps its findings sentence"
have "${HERMES_TASK}" "surface-inventory.md" "local Hermes task reads the inventory"
have "${HERMES_TASK}" "one review priority" "local Hermes task stays one priority"

have "${VPS_RULE}" "Review scope and inspection limits" "hermesVPS rule names scope section"
have "${VPS_RULE}" "Entry-point and sensitive-operation inventory" "hermesVPS rule names surface table"
have "${VPS_RULE}" "Persisted-input and second-order flows" "hermesVPS rule names flow table"
have "${VPS_RULE}" "**Coverage limitations**" "hermesVPS keeps Coverage limitations"
have "${VPS_RULE}" "whole-repository inventory" "hermesVPS does not require a whole-repository inventory"
have "${VPS_RULE}" "labeled as candidates" "hermesVPS keeps candidate labeling"
have "${VPS_TASK}" "security-assets/surface-inventory.md" "hermesVPS task reads the bundled inventory"
have "${VPS_TASK}" "one review priority" "hermesVPS task stays one priority"

# Identity header and completion enums stay on the phase-050 template.
first="$(head -n 1 "${VPS_TEMPLATE}")"
if [[ "${first}" == "<!-- hermes-vps-report:"* ]]; then
  ok "phase-050 template keeps the identity-header placeholder"
else
  bad "phase-050 template lost the identity-header placeholder"
fi
have "${VPS_TEMPLATE}" 'State: `complete` | `incomplete` | `blocked`' "phase-050 template keeps the completion-state line"
have "${VPS_TEMPLATE}" "## Review scope and inspection limits" "template has scope section"
have "${VPS_TEMPLATE}" "## Entry-point and sensitive-operation inventory" "template has surface table"
have "${VPS_TEMPLATE}" "## Persisted-input and second-order flows" "template has flow table"
have "${VPS_TEMPLATE}" "## Candidate issues" "template keeps candidate issues"
have "${VPS_TEMPLATE}" "## Coverage limitations" "template keeps Coverage limitations"
if [[ "$(grep -c 'hermes-vps-report:' "${VPS_TEMPLATE}")" -eq 1 ]]; then
  ok "phase-050 template has one identity header"
else
  bad "phase-050 template identity header count changed"
fi

# Byte copies. Install equality is also checked by tests/hermes-ext.sh.
if cmp -s "${INVENTORY}" "${EXT}/security-assets/surface-inventory.md"; then
  ok "hermesVPS surface-inventory.md matches the canonical file"
else
  bad "hermesVPS surface-inventory.md drifted"
fi
if cmp -s "${CATALOG}" "${EXT}/security-assets/weakness-classes.md"; then
  ok "hermesVPS weakness-classes.md matches the canonical file"
else
  bad "hermesVPS weakness-classes.md drifted"
fi

python3 - "${EXT}" <<'PY'
import os, sys
sys.path.insert(0, sys.argv[1])
from lib.hermes_vps_phases import PHASE_TABLE
rel = "security-assets/surface-inventory.md"
files = PHASE_TABLE["050"].policy_files
if rel not in files:
    raise SystemExit("phase 050 policy files omit surface-inventory.md")
for phase, info in PHASE_TABLE.items():
    if phase != "050" and rel in info.policy_files:
        raise SystemExit(f"surface inventory unexpectedly required for phase {phase}")
if "security-assets/weakness-classes.md" not in files:
    raise SystemExit("phase 050 dropped the weakness-class catalog")
print("PASS: phase 050 requires the inventory; other phases do not")
PY

# Runner: missing inventory fails closed before a prompt. Present inventory
# is not reported missing; the next failure is the missing phase-010 artifact.
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
  "run_id": "run-050",
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

rm -f "${POLICY}/security-assets/surface-inventory.md"
if "${RUNNER}" --phase 050 --run-json "${RUN_JSON}" --trigger-input auth-module \
  >"${TMP}/missing-out.txt" 2>"${TMP}/missing-err.txt"; then
  bad "runner printed a phase 050 prompt without the inventory"
else
  if grep -Fq "missing required policy" "${TMP}/missing-err.txt" \
    && grep -Fq "surface-inventory.md" "${TMP}/missing-err.txt" \
    && [[ ! -s "${TMP}/missing-out.txt" ]]; then
    ok "missing inventory is rejected before a phase 050 prompt"
  else
    bad "missing inventory was not rejected cleanly: $(cat "${TMP}/missing-err.txt")"
  fi
fi

cp -f "${INVENTORY}" "${POLICY}/security-assets/surface-inventory.md"
if "${RUNNER}" --phase 050 --run-json "${RUN_JSON}" --trigger-input auth-module \
  >"${TMP}/present-out.txt" 2>"${TMP}/present-err.txt"; then
  bad "phase 050 prompt ran without phase 010"
else
  if grep -Fq "phase-010" "${TMP}/present-err.txt" \
    && ! grep -Fq "missing required policy" "${TMP}/present-err.txt" \
    && [[ ! -s "${TMP}/present-out.txt" ]]; then
    ok "present inventory passes the policy gate and still requires phase 010"
  else
    bad "present inventory did not reach the phase-010 gate: $(cat "${TMP}/present-err.txt")"
  fi
fi

# With the selected prior artifacts, the prompt lists the absolute inventory path.
reg() {
  PYTHONDONTWRITEBYTECODE=1 python3 "${STAMP}" "${RUNNER}" "$@"
  "${ART}" "$@"
}
printf '# Phase 010\n\nState: `complete`\n' >"${TMP}/r010.md"
printf '# Phase 020\n\nState: `complete`\n' >"${TMP}/r020.md"
reg register --run-json "${RUN_JSON}" --phase 010 --source-report "${TMP}/r010.md" >/dev/null
reg register --run-json "${RUN_JSON}" --phase 020 --source-report "${TMP}/r020.md" >/dev/null
if "${RUNNER}" --phase 050 --run-json "${RUN_JSON}" --trigger-input auth-module \
  >"${TMP}/prompt.txt" 2>"${TMP}/prompt.err"; then
  if grep -Fq "${POLICY}/security-assets/surface-inventory.md" "${TMP}/prompt.txt" \
    && grep -Fq "READ THESE POLICY INPUTS" "${TMP}/prompt.txt"; then
    ok "phase 050 prompt lists the inventory before the agent starts"
  else
    bad "phase 050 prompt did not list the inventory path"
  fi
else
  bad "phase 050 runner failed with inventory and priors present: $(cat "${TMP}/prompt.err")"
fi

if [[ "${fail}" -ne 0 ]]; then
  echo "FAIL: security stage 02 contract checks" >&2
  exit 1
fi
echo "PASS: security stage 02 contract checks (not proof a reviewer follows them)"
