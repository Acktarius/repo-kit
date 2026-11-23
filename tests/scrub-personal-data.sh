#!/usr/bin/env bash
# scrub-personal-data: unittest suite against throwaway git repos, then
# init --base delivery: script, skill, command, and a gitignored tokens file.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT
export PYTHONDONTWRITEBYTECODE=1

(cd "${ROOT}/tests/scrub_personal_data" && python3 -m unittest discover -q)

TARGET="${TMP}/target"
mkdir -p "${TARGET}"
git -C "${TARGET}" init -q
"${ROOT}/scripts/init.sh" "${TARGET}" --base >/dev/null

fail=0
for rel in \
  .repo-kit/.gitignore \
  .repo-kit/personal-tokens.txt.example \
  .repo-kit/scripts/scrub-personal-data.py \
  .repo-kit/scripts/scrub-personal-data.sh \
  .cursor/skills/scrub-personal-data/SKILL.md \
  .cursor/commands/scrub-personal-data.md; do
  if [[ ! -f "${TARGET}/${rel}" ]]; then
    echo "FAIL: missing ${rel}" >&2
    fail=1
  fi
done

if [[ ! -x "${TARGET}/.repo-kit/scripts/scrub-personal-data.sh" ]]; then
  echo "FAIL: launcher is not executable after init" >&2
  fail=1
fi

cp "${TARGET}/.repo-kit/personal-tokens.txt.example" "${TARGET}/.repo-kit/personal-tokens.txt"
if ! git -C "${TARGET}" check-ignore -q .repo-kit/personal-tokens.txt; then
  echo "FAIL: .repo-kit/personal-tokens.txt is not gitignored" >&2
  fail=1
fi

if ! (cd "${TARGET}" && .repo-kit/scripts/scrub-personal-data.sh >/dev/null); then
  echo "FAIL: fresh install does not scan clean" >&2
  fail=1
fi

if [[ "${fail}" -ne 0 ]]; then
  exit 1
fi
echo "OK: scrub-personal-data suite and init --base delivery"
