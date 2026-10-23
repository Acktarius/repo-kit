#!/usr/bin/env bash
# Start Hermes for this repository: mounted read-only at /workspace/target,
# with only .repo-kit/hermes/reports writable.
# Installed at <repo>/.repo-kit/hermes/hermes-review.sh; needs only `hermes`.
# The Hermes gateway reads mounts from its config.yaml, so they are written
# there for this session and restored when Hermes exits. A lock enforces one
# review at a time for the whole session.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
hermes_dir="${root}/.repo-kit/hermes"
reports="${hermes_dir}/reports"
skills_src="${hermes_dir}/skills"
hermes_home="${HERMES_HOME:-${HOME}/.hermes}"
skills_dest="${hermes_home}/skills/repo-kit-hermes"
lock_file="${hermes_home}/hermes-review.lock"

command -v hermes >/dev/null || {
  echo "hermes-review: hermes is not installed or not on PATH" >&2
  exit 1
}
command -v flock >/dev/null || {
  echo "hermes-review: flock is required (util-linux)" >&2
  exit 1
}
[[ -d "${reports}" ]] || {
  echo "hermes-review: missing ${reports}" >&2
  exit 1
}
case "${root}" in
  *'"'* | *'\'* | *:* | *,*)
    echo "hermes-review: unsupported characters in path: ${root}" >&2
    exit 1
    ;;
esac

mkdir -p "${hermes_home}"
exec 9>"${lock_file}"
if ! flock -n 9; then
  echo "hermes-review: another review already holds ${lock_file}" >&2
  echo "hermes-review: wait for it to finish, or remove a stale lock only if no review is running" >&2
  exit 1
fi

config_get() {
  # Prints the value; stderr (warnings) discarded. Exit non-zero if unset.
  hermes config get "$@" 2>/dev/null
}

backend="$(config_get terminal.backend || true)"
if [[ "${backend}" != "docker" ]]; then
  echo "hermes-review: terminal.backend must be docker (got: ${backend:-unset})" >&2
  echo "hermes-review: fix with: hermes config set terminal.backend docker" >&2
  exit 1
fi
docker_network="$(config_get terminal.docker_network || true)"
if [[ "${docker_network}" != "false" ]]; then
  echo "hermes-review: terminal.docker_network must be false (got: ${docker_network:-unset})" >&2
  echo "hermes-review: fix with: hermes config set terminal.docker_network false" >&2
  exit 1
fi

# Capture prior values before mutation so exit restores the operator's config.
had_cwd=0
had_volumes=0
had_mount_cwd=0
prev_cwd=""
prev_volumes=""
prev_mount_cwd=""
if prev_cwd="$(config_get terminal.cwd)"; then
  had_cwd=1
fi
if prev_volumes="$(config_get terminal.docker_volumes --json)"; then
  had_volumes=1
fi
if prev_mount_cwd="$(config_get terminal.docker_mount_cwd_to_workspace)"; then
  had_mount_cwd=1
fi

restore_failed=0
restore_one() {
  local key="$1" had="$2" value="$3"
  if [[ "${had}" -eq 1 ]]; then
    if ! hermes config set "${key}" "${value}" >/dev/null; then
      echo "hermes-review: failed to restore ${key} to: ${value}" >&2
      restore_failed=1
    fi
  else
    if ! hermes config unset "${key}" >/dev/null; then
      echo "hermes-review: failed to unset ${key} (was unset before this review)" >&2
      restore_failed=1
    fi
  fi
}

restore_config() {
  restore_one terminal.cwd "${had_cwd}" "${prev_cwd}"
  restore_one terminal.docker_volumes "${had_volumes}" "${prev_volumes}"
  restore_one terminal.docker_mount_cwd_to_workspace "${had_mount_cwd}" "${prev_mount_cwd}"
  if [[ "${restore_failed}" -ne 0 ]]; then
    echo "hermes-review: one or more settings were not restored; check ~/.hermes/config.yaml" >&2
  fi
}

cleanup() {
  local ec=$?
  restore_config
  if [[ "${restore_failed}" -ne 0 && "${ec}" -eq 0 ]]; then
    exit 1
  fi
  exit "${ec}"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# Phase commands (/hermes-010 ...) are identical for every repository.
# Promoting checkout skills into ~/.hermes is a trust decision; review them first.
if [[ -d "${skills_src}" ]]; then
  mkdir -p "${skills_dest}"
  cp -R "${skills_src}/." "${skills_dest}/"
fi

expected_volumes="[\"${root}:/workspace/target:ro\",\"${reports}:/workspace/target/.repo-kit/hermes/reports\"]"

# The session cwd must be a host path; with docker_mount_cwd_to_workspace,
# Hermes reuses the matching docker_volumes bind (including :ro) instead of
# adding a writable mount of the launch directory.
hermes config set terminal.cwd . >/dev/null
hermes config set terminal.docker_volumes "${expected_volumes}" >/dev/null
hermes config set terminal.docker_mount_cwd_to_workspace true >/dev/null

# Confirm the review mounts landed; do not start if the gateway would see something else.
active_volumes="$(config_get terminal.docker_volumes --json || true)"
if [[ "${active_volumes}" != "${expected_volumes}" ]]; then
  echo "hermes-review: docker_volumes mismatch after config set" >&2
  echo "hermes-review: expected: ${expected_volumes}" >&2
  echo "hermes-review: got: ${active_volumes:-unset}" >&2
  exit 1
fi
active_mount_cwd="$(config_get terminal.docker_mount_cwd_to_workspace || true)"
if [[ "${active_mount_cwd}" != "true" ]]; then
  echo "hermes-review: terminal.docker_mount_cwd_to_workspace must be true for RO cwd reuse (got: ${active_mount_cwd:-unset})" >&2
  exit 1
fi

echo "hermes-review: sandbox mounts (target RO, reports RW on host for downstream tools):" >&2
echo "  ${root} -> /workspace/target:ro" >&2
echo "  ${reports} -> /workspace/target/.repo-kit/hermes/reports" >&2
echo "hermes-review: reports remain on the host at ${reports}" >&2

cd "${root}"
hermes "$@"
