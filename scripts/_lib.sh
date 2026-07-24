#!/usr/bin/env bash
# Shared helpers for repo-kit scripts.
# shellcheck disable=SC2034

set -euo pipefail

REPO_KIT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODULES_DIR="${REPO_KIT_ROOT}/modules"

# Globals set by loaders / resolvers
DECLARED_MODULES=()
SELECTED_MODULES=()
RESOLVED_MODULES=()
FORCE_COPY=0
CURSOR_ONLY=0
ADDED_COUNT=0
SKIPPED_COUNT=0
OVERWRITTEN_COUNT=0

die() {
  echo "error: $*" >&2
  exit 1
}

# Discover module names from modules/*/manifest.sh
discover_modules() {
  DECLARED_MODULES=()
  local manifest dir name
  shopt -s nullglob
  for manifest in "${MODULES_DIR}"/*/manifest.sh; do
    dir="$(dirname "${manifest}")"
    name="$(basename "${dir}")"
    DECLARED_MODULES+=("${name}")
  done
  shopt -u nullglob
  if [[ ${#DECLARED_MODULES[@]} -eq 0 ]]; then
    die "no modules found under ${MODULES_DIR}"
  fi
}

# Load one module's manifest into MODULE_* variables (caller scope).
load_manifest() {
  local name="$1"
  local path="${MODULES_DIR}/${name}/manifest.sh"
  [[ -f "${path}" ]] || die "module '${name}' has no manifest.sh"

  MODULE_NAME=""
  MODULE_DESC=""
  MODULE_DEPENDS=()
  MODULE_CONFLICTS=()

  # shellcheck source=/dev/null
  source "${path}"

  [[ -n "${MODULE_NAME}" ]] || die "module '${name}' did not set MODULE_NAME"
  [[ "${MODULE_NAME}" == "${name}" ]] || die "module '${name}' MODULE_NAME='${MODULE_NAME}' does not match directory"
}

module_exists() {
  local needle="$1" m
  for m in "${DECLARED_MODULES[@]}"; do
    [[ "${m}" == "${needle}" ]] && return 0
  done
  return 1
}

array_contains() {
  local needle="$1"
  shift
  local item
  for item in "$@"; do
    [[ "${item}" == "${needle}" ]] && return 0
  done
  return 1
}

# Resolve SELECTED_MODULES -> RESOLVED_MODULES (deps first, topo order).
resolve_dependencies() {
  RESOLVED_MODULES=()
  local visiting=()
  local visited=()

  _resolve_one() {
    local name="$1"
    local dep

    module_exists "${name}" || die "unknown module '${name}'"

    if array_contains "${name}" "${visited[@]+"${visited[@]}"}"; then
      return 0
    fi
    if array_contains "${name}" "${visiting[@]+"${visiting[@]}"}"; then
      die "circular dependency involving '${name}'"
    fi

    visiting+=("${name}")
    load_manifest "${name}"
    for dep in "${MODULE_DEPENDS[@]+"${MODULE_DEPENDS[@]}"}"; do
      _resolve_one "${dep}"
    done
    if [[ ${#visiting[@]} -gt 0 ]]; then
      visiting=("${visiting[@]:0:$((${#visiting[@]} - 1))}")
    fi
    visited+=("${name}")
    RESOLVED_MODULES+=("${name}")
  }

  local sel
  for sel in "${SELECTED_MODULES[@]}"; do
    _resolve_one "${sel}"
  done
}

# Fail if any resolved module conflicts with another resolved module.
detect_conflicts() {
  local name conflict
  for name in "${RESOLVED_MODULES[@]}"; do
    load_manifest "${name}"
    for conflict in "${MODULE_CONFLICTS[@]+"${MODULE_CONFLICTS[@]}"}"; do
      if array_contains "${conflict}" "${RESOLVED_MODULES[@]}"; then
        die "module '${name}' conflicts with '${conflict}' (both selected after dependency resolution)"
      fi
    done
  done
}

list_modules() {
  discover_modules
  local name depends conflicts
  printf "%-12s  %-60s  %-20s  %s\n" "NAME" "DESCRIPTION" "DEPENDS" "CONFLICTS"
  printf "%-12s  %-60s  %-20s  %s\n" "----" "-----------" "-------" "---------"
  for name in "${DECLARED_MODULES[@]}"; do
    load_manifest "${name}"
    depends="${MODULE_DEPENDS[*]:-}"
    conflicts="${MODULE_CONFLICTS[*]:-}"
    [[ -n "${depends}" ]] || depends="-"
    [[ -n "${conflicts}" ]] || conflicts="-"
    printf "%-12s  %-60s  %-20s  %s\n" "${MODULE_NAME}" "${MODULE_DESC}" "${depends}" "${conflicts}"
  done
}

# Copy one file into target, respecting FORCE_COPY.
_copy_file() {
  local src="$1"
  local dest="$2"

  if [[ -e "${dest}" || -L "${dest}" ]]; then
    if [[ "${FORCE_COPY}" -eq 1 ]]; then
      mkdir -p "$(dirname "${dest}")"
      cp -f "${src}" "${dest}"
      OVERWRITTEN_COUNT=$((OVERWRITTEN_COUNT + 1))
      echo "  overwrite  ${dest#"${TARGET_DIR}"/}"
    else
      SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
      echo "  skip       ${dest#"${TARGET_DIR}"/}"
    fi
    return 0
  fi

  mkdir -p "$(dirname "${dest}")"
  cp "${src}" "${dest}"
  ADDED_COUNT=$((ADDED_COUNT + 1))
  echo "  add        ${dest#"${TARGET_DIR}"/}"
}

# Copy files/ from a module into TARGET_DIR.
# If CURSOR_ONLY=1, only copy files under files/.cursor/
copy_module_files() {
  local name="$1"
  local src_root="${MODULES_DIR}/${name}/files"
  local rel dest

  [[ -d "${src_root}" ]] || die "module '${name}' has no files/ directory"

  echo "module: ${name}"

  while IFS= read -r -d '' src; do
    rel="${src#"${src_root}"/}"

    if [[ "${CURSOR_ONLY}" -eq 1 ]]; then
      [[ "${rel}" == .cursor/* ]] || continue
    fi

    dest="${TARGET_DIR}/${rel}"
    _copy_file "${src}" "${dest}"
  done < <(find "${src_root}" -type f -print0 | sort -z)
}

install_modules() {
  local name
  ADDED_COUNT=0
  SKIPPED_COUNT=0
  OVERWRITTEN_COUNT=0

  mkdir -p "${TARGET_DIR}"

  for name in "${RESOLVED_MODULES[@]}"; do
    copy_module_files "${name}"
  done

  echo
  echo "summary"
  echo "  modules:      ${RESOLVED_MODULES[*]}"
  echo "  added:        ${ADDED_COUNT}"
  echo "  skipped:      ${SKIPPED_COUNT}"
  echo "  overwritten:  ${OVERWRITTEN_COUNT}"
}

# Parse common CLI: [target] [--module ...] [--force] [--list] [--help]
# Sets: TARGET_DIR, SELECTED_MODULES, FORCE_COPY, DO_LIST
parse_common_args() {
  TARGET_DIR=""
  SELECTED_MODULES=()
  FORCE_COPY=0
  DO_LIST=0
  SHOW_HELP=0

  discover_modules

  local arg name matched
  while [[ $# -gt 0 ]]; do
    arg="$1"
    shift
    case "${arg}" in
      --list)
        DO_LIST=1
        ;;
      --force)
        FORCE_COPY=1
        ;;
      --help|-h)
        SHOW_HELP=1
        ;;
      --*)
        name="${arg#--}"
        matched=0
        if module_exists "${name}"; then
          if ! array_contains "${name}" "${SELECTED_MODULES[@]+"${SELECTED_MODULES[@]}"}"; then
            SELECTED_MODULES+=("${name}")
          fi
          matched=1
        fi
        [[ "${matched}" -eq 1 ]] || die "unknown flag '${arg}' (known modules: ${DECLARED_MODULES[*]})"
        ;;
      -*)
        die "unknown flag '${arg}'"
        ;;
      *)
        if [[ -n "${TARGET_DIR}" ]]; then
          die "unexpected argument '${arg}' (target already set to '${TARGET_DIR}')"
        fi
        TARGET_DIR="${arg}"
        ;;
    esac
  done
}
