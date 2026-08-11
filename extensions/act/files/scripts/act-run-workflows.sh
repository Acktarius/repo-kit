#!/usr/bin/env bash
# Discover secrets-free GitHub Actions workflows and run them locally via act.
set -euo pipefail

WORKFLOW_PATTERNS=("npm-audit" "ci-check")
SECRETS_RE='\$\{\{[[:space:]]*secrets\.'

ROOT="$(pwd)"
LIST=0
ALL=0
EVENT=""
explicit=()
workflow_names=()

show_help() {
  cat <<'USAGE'
Usage:
  act-run-workflows.sh [--list] [--all] [--event EVENT] [--root PATH] [--workflow NAME ...] [workflow-file ...]

Discover and run secrets-free workflows under .github/workflows/ using act.

Default discovery (no arguments): filenames matching *npm-audit* or *ci-check*.
Use --all to consider every workflow file; use --workflow or a path to force one.

Workflows referencing ${{ secrets.* }} are skipped.

Options:
  --list        Print eligible vs skipped workflows; do not run act
  --all         With --list or default run: include all secrets-free workflows
  --workflow NAME  Force .github/workflows/NAME (appends .yml/.yaml if needed)
  --event NAME  GitHub event to simulate (default: infer from workflow on:)
  --root PATH   Project root (default: current directory)
  --help        Show this help

Examples:
  act-run-workflows.sh --list --all
  act-run-workflows.sh --workflow ci.yml
  act-run-workflows.sh --event pull_request .github/workflows/ci.yml
  act-run-workflows.sh .github/workflows/ci-check.yml
USAGE
}

die() {
  echo "error: $*" >&2
  exit 1
}

matches_pattern() {
  local base="$1"
  local pat
  for pat in "${WORKFLOW_PATTERNS[@]}"; do
    [[ "${base}" == *"${pat}"* ]] && return 0
  done
  return 1
}

uses_secrets() {
  grep -qE "${SECRETS_RE}" "$1"
}

infer_event() {
  local file="$1"
  if grep -qE '(^|[[:space:]])pull_request:' "${file}"; then
    echo "pull_request"
  elif grep -qE '(^|[[:space:]])push:' "${file}"; then
    echo "push"
  elif grep -qE '(^|[[:space:]])workflow_dispatch:' "${file}"; then
    echo "workflow_dispatch"
  else
    echo "push"
  fi
}

docker_preflight_hint() {
  if [[ -S /var/run/docker.sock ]] && ! docker info >/dev/null 2>&1; then
    if ! groups | grep -qw docker; then
      die "docker permission denied (user not in 'docker' group). Fix: sudo usermod -aG docker \$USER && newgrp docker   (or log out and back in)"
    fi
  fi
  die "docker daemon not reachable; start Docker (sudo systemctl start docker) or install via: ./scripts/init.sh <target> --ext act"
}

preflight() {
  command -v docker >/dev/null 2>&1 || die "docker not found; install via: ./scripts/init.sh <target> --ext act"
  command -v act >/dev/null 2>&1 || die "act not found; install via: ./scripts/init.sh <target> --ext act"
  docker info >/dev/null 2>&1 || docker_preflight_hint
}

resolve_workflow_path() {
  local arg="$1"
  if [[ "${arg}" == /* ]]; then
    printf '%s\n' "${arg}"
  elif [[ -f "${ROOT}/${arg}" ]]; then
    printf '%s\n' "${ROOT}/${arg}"
  elif [[ -f "${arg}" ]]; then
    local dir
    dir="$(cd "$(dirname "${arg}")" && pwd)"
    printf '%s\n' "${dir}/$(basename "${arg}")"
  else
    die "workflow not found: ${arg}"
  fi
}

resolve_workflow_name() {
  local name="$1"
  local dir="${ROOT}/.github/workflows"
  local candidate

  [[ -d "${dir}" ]] || die "no .github/workflows directory at ${dir}"

  if [[ -f "${dir}/${name}" ]]; then
    printf '%s\n' "${dir}/${name}"
    return 0
  fi
  if [[ "${name}" != *.yml && "${name}" != *.yaml ]]; then
    for candidate in "${name}.yml" "${name}.yaml"; do
      if [[ -f "${dir}/${candidate}" ]]; then
        printf '%s\n' "${dir}/${candidate}"
        return 0
      fi
    done
  fi
  die "workflow not found under .github/workflows/: ${name}"
}

discover_all_candidates() {
  local dir="${ROOT}/.github/workflows"
  local f

  [[ -d "${dir}" ]] || die "no .github/workflows directory at ${dir}"

  shopt -s nullglob
  for f in "${dir}"/*.{yml,yaml}; do
    [[ -f "${f}" ]] || continue
    printf '%s\n' "${f}"
  done
  shopt -u nullglob
}

discover_candidates() {
  local dir="${ROOT}/.github/workflows"
  local f base

  [[ -d "${dir}" ]] || die "no .github/workflows directory at ${dir}"

  if [[ "${ALL}" -eq 1 ]]; then
    discover_all_candidates
    return 0
  fi

  shopt -s nullglob
  for f in "${dir}"/*; do
    [[ -f "${f}" ]] || continue
    base="$(basename "${f}")"
    matches_pattern "${base}" || continue
    printf '%s\n' "${f}"
  done
  shopt -u nullglob
}

classify_workflow() {
  local file="$1"
  local rel reason="" status="eligible"

  rel="${file#"${ROOT}"/}"
  if uses_secrets "${file}"; then
    status="skipped"
    reason="uses \${{ secrets.* }}"
  fi

  printf '%s\t%s\t%s\n' "${status}" "${rel}" "${reason}"
}

list_workflows() {
  local file status rel reason ev
  local found=0

  while IFS= read -r file; do
    [[ -n "${file}" ]] || continue
    found=1
    IFS=$'\t' read -r status rel reason <<<"$(classify_workflow "${file}")"
    if [[ "${status}" == "eligible" ]]; then
      ev="$(infer_event "${file}")"
      echo "eligible  ${rel}  (event: ${ev})"
    else
      echo "skipped   ${rel}  (${reason})"
    fi
  done < <(collect_workflows)

  if [[ "${found}" -eq 0 ]]; then
    if [[ "${ALL}" -eq 1 ]]; then
      echo "(no workflow files under .github/workflows/)"
    else
      echo "(no matching workflows — try --list --all or --workflow ci.yml)"
    fi
  fi
}

collect_workflows() {
  local arg file name

  for name in "${workflow_names[@]}"; do
    explicit+=("$(resolve_workflow_name "${name}")")
  done

  if [[ ${#explicit[@]} -gt 0 ]]; then
    for arg in "${explicit[@]}"; do
      resolve_workflow_path "${arg}"
    done
    return 0
  fi

  discover_candidates
}

run_workflows() {
  local file status rel reason ev run_event failed=0 ran=0

  while IFS= read -r file; do
    [[ -n "${file}" ]] || continue
    IFS=$'\t' read -r status rel reason <<<"$(classify_workflow "${file}")"
    if [[ "${status}" != "eligible" ]]; then
      echo "skip  ${rel}  (${reason})"
      continue
    fi

    run_event="${EVENT:-$(infer_event "${file}")}"
    echo "run   ${rel}  (event: ${run_event})"
    (
      cd "${ROOT}"
      act -W "${file}" "${run_event}" --secret-file /dev/null
    ) || failed=1
    ran=$((ran + 1))
  done < <(collect_workflows)

  if [[ "${ran}" -eq 0 ]]; then
    die "no eligible workflows to run (try --list --all or --workflow ci.yml)"
  fi

  [[ "${failed}" -eq 0 ]] || exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --list)
      LIST=1
      shift
      ;;
    --all)
      ALL=1
      shift
      ;;
    --event)
      [[ $# -gt 1 ]] || die "--event requires a value"
      EVENT="$2"
      shift 2
      ;;
    --root)
      [[ $# -gt 1 ]] || die "--root requires a path"
      ROOT="$(cd "$2" && pwd)"
      shift 2
      ;;
    --workflow)
      [[ $# -gt 1 ]] || die "--workflow requires a name"
      workflow_names+=("$2")
      shift 2
      ;;
    --help|-h)
      show_help
      exit 0
      ;;
    -*)
      die "unknown option: $1"
      ;;
    *)
      explicit+=("$1")
      shift
      ;;
  esac
done

if [[ "${LIST}" -ne 1 ]]; then
  preflight
fi

if [[ "${LIST}" -eq 1 ]]; then
  list_workflows
  exit 0
fi

run_workflows
