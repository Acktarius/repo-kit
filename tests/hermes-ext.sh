#!/usr/bin/env bash
# Focused check: --ext hermes installs rules, tasks, phase-command skills, the
# hermes-review.sh launcher, reports/.gitkeep, and a single ~/.bashrc hook.
# The launcher must work from the target alone (no repo-kit checkout needed).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

export HOME="${TMP}/home"
mkdir -p "${HOME}"
unset HERMES_HOME

TARGET="${TMP}/target"
mkdir -p "${TARGET}"
git -C "${TARGET}" init -q

"${ROOT}/scripts/init.sh" "${TARGET}" --ext hermes >/dev/null
# Re-install must not duplicate the hook.
"${ROOT}/scripts/init.sh" "${TARGET}" --ext hermes >/dev/null

HERMES="${TARGET}/.repo-kit/hermes"
tasks=(
  010-inventory.md
  020-threat-model.md
  030-scan-plan.md
  040-dependency-advisories.md
  050-source-review.md
  060-validate-and-triage.md
  070-reviewed-findings.md
  080-remediate-and-retest.md
)
expected=(
  "review-rules/README.md"
  "review-rules/rules_005-report-output.md"
  "reports/.gitkeep"
  "hermes-review.sh"
)
for task_file in "${tasks[@]}"; do
  expected+=("tasks/${task_file}" "skills/hermes-${task_file%%-*}/SKILL.md")
done

fail=0
for rel in "${expected[@]}"; do
  if [[ ! -f "${HERMES}/${rel}" ]]; then
    echo "FAIL: missing .repo-kit/hermes/${rel}" >&2
    fail=1
  fi
done
if [[ ! -x "${HERMES}/hermes-review.sh" ]]; then
  echo "FAIL: .repo-kit/hermes/hermes-review.sh is not executable" >&2
  fail=1
fi

for task_file in "${tasks[@]}"; do
  skill="hermes-${task_file%%-*}"
  skill_md="${HERMES}/skills/${skill}/SKILL.md"
  [[ -f "${skill_md}" ]] || continue
  if ! grep -Fqx "name: ${skill}" "${skill_md}"; then
    echo "FAIL: ${skill} SKILL.md name does not match its directory" >&2
    fail=1
  fi
  if ! grep -Fq "\`/workspace/target/.repo-kit/hermes/tasks/${task_file}\`" "${skill_md}"; then
    echo "FAIL: ${skill} does not reference /workspace/target/.repo-kit/hermes/tasks/${task_file}" >&2
    fail=1
  fi
done

hooks="$(grep -c '^# repo-kit hermes$' "${HOME}/.bashrc" || true)"
if [[ "${hooks}" -ne 1 ]]; then
  echo "FAIL: expected 1 '# repo-kit hermes' hook in ~/.bashrc, found ${hooks}" >&2
  fail=1
fi
if ! grep -Fqx "source \"${ROOT}/extensions/hermes/.bashrc_hermes\"" "${HOME}/.bashrc"; then
  echo "FAIL: ~/.bashrc does not source the kit's .bashrc_hermes" >&2
  fail=1
fi

# Stub `hermes` on PATH; it logs each call.
log="${TMP}/hermes-calls.log"
mkdir -p "${TMP}/bin"
cat >"${TMP}/bin/hermes" <<EOF
#!/usr/bin/env bash
if [[ "\$1" == "config" ]]; then echo "\$*"; else echo "run in \${PWD}: \$*"; fi >>"${log}"
EOF
chmod +x "${TMP}/bin/hermes"

volumes="[\"${TARGET}:/workspace/target:ro\",\"${HERMES}/reports:/workspace/target/.repo-kit/hermes/reports\"]"
want="config set terminal.cwd .
config set terminal.docker_volumes ${volumes}
config set terminal.docker_mount_cwd_to_workspace true
run in ${TARGET}: --cli
config set terminal.docker_volumes []
config set terminal.docker_mount_cwd_to_workspace false"

# Collaborator path: run the installed launcher directly from a subdirectory.
(
  mkdir -p "${TARGET}/sub"
  cd "${TARGET}/sub"
  PATH="${TMP}/bin:${PATH}" ../.repo-kit/hermes/hermes-review.sh --cli
)
got="$(cat "${log}")"
if [[ "${got}" != "${want}" ]]; then
  echo "FAIL: hermes-review.sh call sequence" >&2
  echo "--- want" >&2
  echo "${want}" >&2
  echo "--- got" >&2
  echo "${got}" >&2
  fail=1
fi

for task_file in "${tasks[@]}"; do
  skill="hermes-${task_file%%-*}"
  if [[ ! -f "${HOME}/.hermes/skills/repo-kit-hermes/${skill}/SKILL.md" ]]; then
    echo "FAIL: launcher did not install ${skill} into ~/.hermes/skills/repo-kit-hermes/" >&2
    fail=1
  fi
done

# Shortcut path: the ~/.bashrc function delegates to the installed launcher.
: >"${log}"
(
  cd "${TARGET}/sub"
  # shellcheck source=/dev/null
  source "${ROOT}/extensions/hermes/.bashrc_hermes"
  PATH="${TMP}/bin:${PATH}" hermes-review --cli
)
if [[ "$(cat "${log}")" != "${want}" ]]; then
  echo "FAIL: hermes-review shortcut call sequence" >&2
  fail=1
fi

if [[ "${fail}" -ne 0 ]]; then
  echo "Installed tree:" >&2
  find "${TARGET}" -path "${TARGET}/.git" -prune -o -print | sed "s|^${TARGET}|<target>|" >&2
  exit 1
fi

echo "PASS: hermes installs rules, tasks, skills, launcher, reports/.gitkeep, and hook; launcher works without repo-kit"
