#!/usr/bin/env bash
# Start Hermes for this repository: mounted read-only at /workspace/target,
# with only .repo-kit/hermes/reports writable.
# Installed at <repo>/.repo-kit/hermes/hermes-review.sh; needs only `hermes`.
# The Hermes gateway reads mounts from its config.yaml, so they are written
# there for this session and cleared when Hermes exits. Run one review at a time.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
hermes_dir="${root}/.repo-kit/hermes"
reports="${hermes_dir}/reports"
skills_src="${hermes_dir}/skills"
skills_dest="${HERMES_HOME:-${HOME}/.hermes}/skills/repo-kit-hermes"

command -v hermes >/dev/null || {
  echo "hermes-review: hermes is not installed or not on PATH" >&2
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

# Phase commands (/hermes-010 ...) are identical for every repository.
if [[ -d "${skills_src}" ]]; then
  mkdir -p "${skills_dest}"
  cp -R "${skills_src}/." "${skills_dest}/"
fi

reset_mounts() {
  hermes config set terminal.docker_volumes '[]' >/dev/null || true
  hermes config set terminal.docker_mount_cwd_to_workspace false >/dev/null || true
}
trap reset_mounts EXIT
trap 'exit 130' INT TERM

# The session cwd must be a host path; Hermes maps it to the read-only
# /workspace/target mount because that volume binds the same directory.
hermes config set terminal.cwd . >/dev/null
hermes config set terminal.docker_volumes \
  "[\"${root}:/workspace/target:ro\",\"${reports}:/workspace/target/.repo-kit/hermes/reports\"]" >/dev/null
hermes config set terminal.docker_mount_cwd_to_workspace true >/dev/null

cd "${root}"
hermes "$@"
