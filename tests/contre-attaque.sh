#!/usr/bin/env bash
# contre-attaque: Python unit/integration suite (fixtures only, no live network),
# then init/sync delivery checks: --contre-attaque pulls in security, installs the
# command/skill/rule/docs, MODULE_PRESERVE keeps findings and state across
# init/sync --force, missing preserved files are recreated, and the helper runs
# from the target alone.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT
export PYTHONDONTWRITEBYTECODE=1

(cd "${ROOT}/tests/contre_attaque" && python3 -m unittest discover -q)

TARGET="${TMP}/target"
mkdir -p "${TARGET}"
git -C "${TARGET}" init -q

"${ROOT}/scripts/init.sh" "${TARGET}" --contre-attaque >/dev/null

fail=0
expect_file() {
  if [[ ! -f "${TARGET}/$1" ]]; then
    echo "FAIL: missing $1" >&2
    fail=1
  fi
}
for rel in \
  .cursor/commands/contre-attaque.md \
  .cursor/rules/50-contre-attaque.mdc \
  .cursor/skills/contre-attaque/SKILL.md \
  .cursor/skills/contre-attaque/references/sources.md \
  .cursor/skills/contre-attaque/references/state.schema.json \
  .cursor/skills/contre-attaque/scripts/contre_attaque.py \
  .cursor/skills/contre-attaque/scripts/ca_intel.py \
  .cursor/skills/contre-attaque/scripts/ca_inventory.py \
  .cursor/skills/contre-attaque/scripts/ca_state.py \
  .cursor/skills/contre-attaque/scripts/ca_report.py \
  .repo-kit/contre-attaque/.gitignore \
  docs/contre-attaque.md \
  security/findings-reviewed.json \
  security/findings.schema.json; do
  expect_file "${rel}"
done

if [[ -n "$(git -C "${TARGET}" status --porcelain --untracked-files=all -- .repo-kit/contre-attaque | grep -v '\.gitignore$' || true)" ]]; then
  echo "FAIL: .repo-kit/contre-attaque content is not ignored" >&2
  fail=1
fi

HELPER=(python3 "${TARGET}/.cursor/skills/contre-attaque/scripts/contre_attaque.py" --root "${TARGET}")
"${HELPER[@]}" status >/dev/null || { echo "FAIL: helper status from target" >&2; fail=1; }
set +e
"${HELPER[@]}" start 3days >/dev/null
code=$?
set -e
if [[ "${code}" -ne 3 ]]; then
  echo "FAIL: start without consent exited ${code}, expected 3 (consent_required)" >&2
  fail=1
fi
if [[ -e "${TARGET}/.repo-kit/contre-attaque/state.json" ]]; then
  echo "FAIL: start without consent wrote state" >&2
  fail=1
fi

# Simulate prior work: human-owned findings, edited gitignore, state.
FINDINGS="${TARGET}/security/findings-reviewed.json"
printf '{"repo":"t","lastReviewed":"2026-11-01","findings":[]}\n' >"${FINDINGS}"
printf '*\n!.gitignore\n# local edit\n' >"${TARGET}/.repo-kit/contre-attaque/.gitignore"
printf '{"kept":true}\n' >"${TARGET}/.repo-kit/contre-attaque/state.json"
sums_before="$(cd "${TARGET}" && sha256sum security/findings-reviewed.json security/accepted-risks.md \
  security/threat-model.md .repo-kit/contre-attaque/.gitignore .repo-kit/contre-attaque/state.json)"

init_out="$("${ROOT}/scripts/init.sh" "${TARGET}" --contre-attaque --force)"
sync_out="$("${ROOT}/scripts/sync-cursor.sh" "${TARGET}" --contre-attaque --force)"
sums_after="$(cd "${TARGET}" && sha256sum security/findings-reviewed.json security/accepted-risks.md \
  security/threat-model.md .repo-kit/contre-attaque/.gitignore .repo-kit/contre-attaque/state.json)"
if [[ "${sums_before}" != "${sums_after}" ]]; then
  echo "FAIL: init/sync --force changed preserved content" >&2
  fail=1
fi
for rel in security/findings-reviewed.json security/accepted-risks.md security/threat-model.md \
  .repo-kit/contre-attaque/.gitignore; do
  if ! grep -Fq "preserve   ${rel}" <<<"${init_out}"; then
    echo "FAIL: init --force did not report preserve for ${rel}" >&2
    fail=1
  fi
done
if ! grep -Eq 'preserved: +[1-9]' <<<"${init_out}"; then
  echo "FAIL: init summary has no preserved count" >&2
  fail=1
fi
if ! grep -Fq "overwrite  .cursor/skills/contre-attaque/SKILL.md" <<<"${sync_out}"; then
  echo "FAIL: sync --force did not refresh non-preserved skill files" >&2
  fail=1
fi

rm -f "${FINDINGS}" "${TARGET}/.repo-kit/contre-attaque/.gitignore"
init_out="$("${ROOT}/scripts/init.sh" "${TARGET}" --contre-attaque)"
for rel in security/findings-reviewed.json .repo-kit/contre-attaque/.gitignore; do
  if ! grep -Fq "add        ${rel}" <<<"${init_out}"; then
    echo "FAIL: missing preserved file ${rel} was not recreated" >&2
    fail=1
  fi
done

if [[ "${fail}" -ne 0 ]]; then
  exit 1
fi
echo "OK: contre-attaque suite, install, preserve, and target-only helper"
