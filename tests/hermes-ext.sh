#!/usr/bin/env bash
# Focused check: --ext hermes installs Rule 005, tasks, and reports/.gitkeep.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

TARGET="${TMP}/target"
mkdir -p "${TARGET}"

"${ROOT}/scripts/init.sh" "${TARGET}" --ext hermes >/dev/null

HERMES="${TARGET}/.repo-kit/hermes"
expected=(
  "review-rules/README.md"
  "review-rules/rules_005-report-output.md"
  "reports/.gitkeep"
  "tasks/010-inventory.md"
  "tasks/020-threat-model.md"
  "tasks/030-scan-plan.md"
  "tasks/040-dependency-advisories.md"
  "tasks/050-source-review.md"
  "tasks/060-validate-and-triage.md"
  "tasks/070-reviewed-findings.md"
  "tasks/080-remediate-and-retest.md"
)

fail=0
for rel in "${expected[@]}"; do
  if [[ ! -f "${HERMES}/${rel}" ]]; then
    echo "FAIL: missing .repo-kit/hermes/${rel}" >&2
    fail=1
  fi
done

if [[ "${fail}" -ne 0 ]]; then
  echo "Installed tree:" >&2
  find "${TARGET}" -print | sed "s|^${TARGET}|<target>|" >&2
  exit 1
fi

echo "PASS: hermes installs rules, tasks, and reports/.gitkeep"
