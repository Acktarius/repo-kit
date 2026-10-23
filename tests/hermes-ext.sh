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

# Stub `hermes` on PATH; it logs each call and keeps a tiny config store so
# get/set/unset and restore can be exercised.
log="${TMP}/hermes-calls.log"
cfg="${TMP}/hermes-config"
mkdir -p "${TMP}/bin" "${cfg}"
# Pre-existing operator values the launcher must restore.
printf '%s' '/prior/cwd' >"${cfg}/terminal.cwd"
printf '%s' '["/prior:/data:ro"]' >"${cfg}/terminal.docker_volumes"
printf '%s' 'true' >"${cfg}/terminal.docker_mount_cwd_to_workspace"
printf '%s' 'docker' >"${cfg}/terminal.backend"
printf '%s' 'false' >"${cfg}/terminal.docker_network"

cat >"${TMP}/bin/hermes" <<EOF
#!/usr/bin/env bash
set -euo pipefail
cfg="${cfg}"
log="${log}"
if [[ "\${1:-}" == "config" ]]; then
  cmd="\${2:-}"
  key="\${3:-}"
  case "\${cmd}" in
    get)
      [[ -f "\${cfg}/\${key}" ]] || exit 1
      val="\$(cat "\${cfg}/\${key}")"
      if [[ "\${4:-}" == "--json" ]]; then
        # Scalars already stored as JSON literals where needed (volumes).
        printf '%s\n' "\${val}"
      else
        printf '%s\n' "\${val}"
      fi
      echo "config get \${key}\${4:+ \$4}" >>"\${log}"
      ;;
    set)
      val="\${4:-}"
      printf '%s' "\${val}" >"\${cfg}/\${key}"
      echo "config set \${key} \${val}" >>"\${log}"
      ;;
    unset)
      rm -f "\${cfg}/\${key}"
      echo "config unset \${key}" >>"\${log}"
      ;;
    *)
      echo "stub: unknown config subcommand: \${cmd}" >&2
      exit 1
      ;;
  esac
  exit 0
fi
echo "run in \${PWD}: \$*" >>"\${log}"
EOF
chmod +x "${TMP}/bin/hermes"

volumes="[\"${TARGET}:/workspace/target:ro\",\"${HERMES}/reports:/workspace/target/.repo-kit/hermes/reports\"]"
want_prefix="config get terminal.backend
config get terminal.docker_network
config get terminal.cwd
config get terminal.docker_volumes --json
config get terminal.docker_mount_cwd_to_workspace
config set terminal.cwd .
config set terminal.docker_volumes ${volumes}
config set terminal.docker_mount_cwd_to_workspace true
config get terminal.docker_volumes --json
config get terminal.docker_mount_cwd_to_workspace
run in ${TARGET}: --cli
config set terminal.cwd /prior/cwd
config set terminal.docker_volumes [\"/prior:/data:ro\"]
config set terminal.docker_mount_cwd_to_workspace true"

# Collaborator path: run the installed launcher directly from a subdirectory.
: >"${log}"
(
  mkdir -p "${TARGET}/sub"
  cd "${TARGET}/sub"
  PATH="${TMP}/bin:${PATH}" ../.repo-kit/hermes/hermes-review.sh --cli
) 2>"${TMP}/launcher.err"
got="$(cat "${log}")"
if [[ "${got}" != "${want_prefix}" ]]; then
  echo "FAIL: hermes-review.sh call sequence" >&2
  echo "--- want" >&2
  echo "${want_prefix}" >&2
  echo "--- got" >&2
  echo "${got}" >&2
  fail=1
fi

# Prior operator config must be restored on disk.
if [[ "$(cat "${cfg}/terminal.cwd")" != "/prior/cwd" ]]; then
  echo "FAIL: terminal.cwd not restored" >&2
  fail=1
fi
if [[ "$(cat "${cfg}/terminal.docker_volumes")" != '["/prior:/data:ro"]' ]]; then
  echo "FAIL: terminal.docker_volumes not restored" >&2
  fail=1
fi
if [[ "$(cat "${cfg}/terminal.docker_mount_cwd_to_workspace")" != "true" ]]; then
  echo "FAIL: terminal.docker_mount_cwd_to_workspace not restored" >&2
  fail=1
fi
if ! grep -Fq "reports remain on the host" "${TMP}/launcher.err"; then
  echo "FAIL: launcher did not mention host-accessible reports" >&2
  fail=1
fi

for task_file in "${tasks[@]}"; do
  skill="hermes-${task_file%%-*}"
  if [[ ! -f "${HOME}/.hermes/skills/repo-kit-hermes/${skill}/SKILL.md" ]]; then
    echo "FAIL: launcher did not install ${skill} into ~/.hermes/skills/repo-kit-hermes/" >&2
    fail=1
  fi
done

# Lock: a second concurrent launch must fail while the first holds the lock.
: >"${log}"
(
  PATH="${TMP}/bin:${PATH}"
  # Hold the same lock the launcher uses.
  exec 8>"${HOME}/.hermes/hermes-review.lock"
  flock -n 8
  if "${HERMES}/hermes-review.sh" --cli 2>"${TMP}/lock.err"; then
    echo "FAIL: second launch succeeded while lock held" >&2
    exit 1
  fi
  if ! grep -Fq "another review already holds" "${TMP}/lock.err"; then
    echo "FAIL: lock failure message missing" >&2
    cat "${TMP}/lock.err" >&2
    exit 1
  fi
) || fail=1

# Prerequisite refusal: non-docker backend.
printf '%s' 'local' >"${cfg}/terminal.backend"
: >"${log}"
if PATH="${TMP}/bin:${PATH}" "${HERMES}/hermes-review.sh" --cli 2>"${TMP}/backend.err"; then
  echo "FAIL: launcher allowed non-docker backend" >&2
  fail=1
fi
if ! grep -Fq "terminal.backend must be docker" "${TMP}/backend.err"; then
  echo "FAIL: missing backend refusal message" >&2
  fail=1
fi
printf '%s' 'docker' >"${cfg}/terminal.backend"

# Prerequisite refusal: networking enabled.
printf '%s' 'true' >"${cfg}/terminal.docker_network"
if PATH="${TMP}/bin:${PATH}" "${HERMES}/hermes-review.sh" --cli 2>"${TMP}/net.err"; then
  echo "FAIL: launcher allowed docker_network true" >&2
  fail=1
fi
if ! grep -Fq "terminal.docker_network must be false" "${TMP}/net.err"; then
  echo "FAIL: missing docker_network refusal message" >&2
  fail=1
fi
printf '%s' 'false' >"${cfg}/terminal.docker_network"

# Shortcut path: the ~/.bashrc function delegates to the installed launcher.
: >"${log}"
(
  cd "${TARGET}/sub"
  # shellcheck source=/dev/null
  source "${ROOT}/extensions/hermes/.bashrc_hermes"
  PATH="${TMP}/bin:${PATH}" hermes-review --cli
) >/dev/null 2>&1
if [[ "$(cat "${log}")" != "${want_prefix}" ]]; then
  echo "FAIL: hermes-review shortcut call sequence" >&2
  echo "--- got" >&2
  cat "${log}" >&2
  fail=1
fi

if [[ "${fail}" -ne 0 ]]; then
  echo "Installed tree:" >&2
  find "${TARGET}" -path "${TARGET}/.git" -prune -o -print | sed "s|^${TARGET}|<target>|" >&2
  exit 1
fi

echo "PASS: hermes installs rules, tasks, skills, launcher, reports/.gitkeep, and hook; launcher restores config, locks, and checks sandbox prerequisites"
