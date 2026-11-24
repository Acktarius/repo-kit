#!/usr/bin/env bash
# Phase 060 must keep unresolved questions out of the candidate list.
# Text checks show the instructions agree. They do not show that a reviewer follows them.
# No network, installs, scanners, or target execution.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

fail=0
ok() { echo "PASS: $*"; }
bad() { echo "FAIL: $*" >&2; fail=1; }

have() {
  local file="$1" needle="$2" label="$3"
  local flat
  flat="$(tr '\n' ' ' <"${file}")"
  if grep -Fq -- "${needle}" <<<"${flat}"; then
    ok "${label}"
  else
    bad "${label}"
  fi
}

LOCAL_RULE="${ROOT}/extensions/hermes/rules/rules_060-validate-and-triage.md"
LOCAL_TASK="${ROOT}/extensions/hermes/tasks/060-validate-and-triage.md"
VPS_RULE="${ROOT}/extensions/hermesVPS/rules/rules_060-validate-and-triage.md"
VPS_TASK="${ROOT}/extensions/hermesVPS/tasks/060-validate-and-triage.md"
VPS_TEMPLATE="${ROOT}/extensions/hermesVPS/templates/phase-060-report.md"
SCHEMA="${ROOT}/extensions/hermesVPS/templates/triage-payload.schema.json"

for pair in \
  "${LOCAL_RULE}|local Hermes rule" \
  "${VPS_RULE}|hermesVPS rule"
do
  file="${pair%%|*}"
  name="${pair#*|}"
  have "${file}" "A phase-050 unresolved question stays an unresolved question." "${name} keeps the question unresolved"
  have "${file}" "It is not automatically a candidate issue." "${name} does not auto-promote the question"
  have "${file}" "A conditional control proposal is not evidence that a control is absent, ineffective, or exploitable." "${name} does not treat a proposal as vulnerability evidence"
  have "${file}" "It does not authorize an edit." "${name} does not authorize an edit from a proposal"
  have "${file}" "merely to fit the triage format." "${name} does not assign triage identity to fit the format"
  have "${file}" "additional permitted static evidence" "${name} requires new static evidence before a new candidate"
  have "${file}" "Do not force every question toward a vulnerability." "${name} allows a non-vulnerability resolution"
  have "${file}" "Do not expand scope automatically." "${name} does not expand scope"
  have "${file}" "Do not mark an affected weakness class covered because the question was discussed." "${name} does not upgrade coverage from discussion"
  have "${file}" "A supported candidate may still name bounded uncertainty." "${name} keeps bounded uncertainty on a supported candidate"
  have "${file}" "Synthetic examples, not findings" "${name} labels the distinction examples as synthetic"
done

have "${LOCAL_RULE}" "Record phase-050 unresolved-question entries in section 5." "local Hermes records questions in section 5"
have "${LOCAL_RULE}" "Phase-050 unresolved-question entries are listed here separately and have no candidate ID." "local Hermes section 5 is not the candidate table"
have "${LOCAL_RULE}" "pending-evidence" "local Hermes still has the pending-evidence disposition"
have "${LOCAL_RULE}" "validated-new" "local Hermes still has the validated-new disposition"
have "${LOCAL_RULE}" "covered-by-accepted-risk" "local Hermes still handles accepted risk"
have "${LOCAL_RULE}" "Do not write to canonical stores or accept risks." "local Hermes still blocks findings-store writes"

have "${VPS_RULE}" "Record phase-050 unresolved-question entries in **Coverage limitations**." "hermesVPS records questions under Coverage limitations"
have "${VPS_RULE}" 'Do not add them to the candidate triage table or the triage payload `candidates` array.' "hermesVPS keeps questions out of the payload"
have "${VPS_RULE}" 'A supported candidate with bounded uncertainty may still use `pending-evidence`.' "hermesVPS still allows pending-evidence on a supported candidate"
have "${VPS_RULE}" 'Do **not** allocate stable SG-NNN IDs.' "hermesVPS still withholds SG ids"

have "${LOCAL_TASK}" "Phase-050 unresolved-question entries stay out of the candidate list." "local Hermes task keeps questions out of the candidate list"
have "${LOCAL_TASK}" "A conditional control proposal is not vulnerability evidence." "local Hermes task separates a proposal from evidence"
have "${VPS_TASK}" 'out of the triage payload `candidates` array.' "hermesVPS task keeps questions out of the payload"
have "${VPS_TASK}" "A conditional control proposal is not vulnerability evidence." "hermesVPS task separates a proposal from evidence"
have "${VPS_TASK}" "A supported candidate may still name bounded uncertainty." "hermesVPS task keeps bounded uncertainty"

have "${VPS_TEMPLATE}" "### Unresolved questions" "template records questions under coverage limitations"
have "${VPS_TEMPLATE}" 'not objects in the triage payload `candidates` array.' "template keeps questions out of the payload"
have "${VPS_TEMPLATE}" "not evidence that a control is absent, ineffective, or exploitable" "template does not treat a proposal as vulnerability evidence"
have "${VPS_TEMPLATE}" "additional permitted static evidence" "template requires new static evidence"
have "${VPS_TEMPLATE}" "A supported candidate may still name bounded uncertainty." "template keeps bounded uncertainty"
have "${VPS_TEMPLATE}" "Do not copy the synthetic examples" "template does not copy the synthetic examples"
have "${VPS_TEMPLATE}" 'State: `complete` | `incomplete` | `blocked`' "template keeps the completion-state line"

header_count="$(grep -c '<!-- hermes-vps-report:' "${VPS_TEMPLATE}" || true)"
if [[ "${header_count}" -eq 1 ]]; then
  ok "phase-060 template has one identity header"
else
  bad "phase-060 template identity header count is ${header_count}"
fi

have "${SCHEMA}" '"required": ["schema_version", "phase", "source_commit", "candidates"]' "triage schema required fields are unchanged"
if grep -Fq 'unresolved_question' "${SCHEMA}"; then
  bad "triage schema gained an unresolved-question field"
else
  ok "triage schema has no unresolved-question field"
fi

if [[ "${fail}" -ne 0 ]]; then
  echo "FAIL: phase 060 unresolved-question checks" >&2
  exit 1
fi
echo "PASS: phase 060 unresolved-question checks (not proof a reviewer follows them)"
