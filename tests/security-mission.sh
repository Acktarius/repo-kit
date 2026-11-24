#!/usr/bin/env bash
# Mission-alignment checks. Text checks show that the written instructions
# agree. They do not show that a reviewer follows them, and they do not
# show technical isolation. This script does not run the directory launcher.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXT="${ROOT}/extensions/hermesVPS"
SEC="${ROOT}/modules/security/files"

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
    bad "${label} (missing: ${needle})"
  fi
}

README="${SEC}/security/README.md"
CATALOG="${SEC}/security/weakness-classes.md"
INVENTORY="${SEC}/security/surface-inventory.md"
PLAN="${SEC}/security/scanner-planning.md"
PLANNER="${SEC}/.cursor/rules/20-security-planner.mdc"
REVIEWER="${SEC}/.cursor/rules/30-security-reviewer.mdc"
TEMPLATE="${SEC}/security/templates/finding-template.md"
HERMES_000="${ROOT}/extensions/hermes/rules/rules_000-safety-and-scope.md"
VPS_000="${EXT}/rules/rules_000-safety-and-scope.md"
HERMES_050="${ROOT}/extensions/hermes/rules/rules_050-source-review.md"
VPS_050="${EXT}/rules/rules_050-source-review.md"
HERMES_030="${ROOT}/extensions/hermes/rules/rules_030-scan-plan.md"
VPS_030="${EXT}/rules/rules_030-scan-plan.md"

have "${README}" "before build or compilation" "security README states the pre-build mission"
have "${README}" "It does not build or compile the application, run it or its tests, inspect a compiled binary, or execute an attack." "security README excludes build, runtime, binary, and attack assessment"
have "${README}" "Source evidence can support a finding without exploit execution or a network probe." "security README does not require exploitation"
have "${README}" "Apply only concerns the repository shape makes relevant." "security README keeps repository shape in scope"
have "${README}" "Further Gitleaks launcher work is deferred." "security README defers further launcher work"
have "${README}" "gitleaks_handoff.py" "offline normalizer remains documented"
have "${README}" "gitleaks_dir_scan.py" "pre-existing launcher remains documented"

BOUNDARY="Target assessment reads repository content before build or compilation."
have "${HERMES_000}" "${BOUNDARY}" "local Rule 000 states the assessment boundary"
have "${VPS_000}" "${BOUNDARY}" "hermesVPS Rule 000 states the assessment boundary"
have "${HERMES_050}" "Source evidence can support a finding without exploit execution or a" "local Rule 050 does not require exploitation"
have "${VPS_050}" "Source evidence can support a finding without exploit execution or a network probe." "hermesVPS Rule 050 does not require exploitation"
have "${HERMES_030}" "Further Gitleaks launcher work is deferred." "local Rule 030 defers further launcher work"
have "${VPS_030}" "Further Gitleaks launcher work is deferred." "hermesVPS Rule 030 defers further launcher work"
have "${CATALOG}" "Apply a class only when the repository shape makes it relevant." "catalog stays shape-specific"
have "${INVENTORY}" "Identify entry points from source and configuration." "inventory entry points stay on source"
have "${PLAN}" "A scanner is an optional supporting check, not the source review." "scanner planning is not the source review"
have "${PLAN}" "Further Gitleaks launcher work is deferred." "scanner planning defers further launcher work"
have "${PLANNER}" "This plan is a pre-build source review of the repository." "planner stays a pre-build source review"
have "${REVIEWER}" "a valid finding does not require exploit execution or a network probe" "reviewer does not require exploitation"
have "${TEMPLATE}" "It is not an executed attack." "finding template keeps exploit path as evidence"

if cmp -s "${CATALOG}" "${EXT}/security-assets/weakness-classes.md"; then
  ok "bundled weakness catalog matches the canonical file"
else
  bad "bundled weakness catalog drifted"
fi
if cmp -s "${INVENTORY}" "${EXT}/security-assets/surface-inventory.md"; then
  ok "bundled surface inventory matches the canonical file"
else
  bad "bundled surface inventory drifted"
fi
if cmp -s "${PLAN}" "${EXT}/security-assets/scanner-planning.md"; then
  ok "bundled scanner planning matches the canonical file"
else
  bad "bundled scanner planning drifted"
fi

if [[ -f "${SEC}/security/gitleaks_dir_scan.py" && -f "${ROOT}/tests/security-stage04c.sh" ]]; then
  ok "pre-existing launcher files are still present"
else
  bad "pre-existing launcher files are missing"
fi

if [[ "${fail}" -ne 0 ]]; then
  exit 1
fi
echo OK
