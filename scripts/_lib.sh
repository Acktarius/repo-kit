#!/usr/bin/env bash
# Shared helpers for repo-kit scripts.
# shellcheck disable=SC2034

set -euo pipefail

REPO_KIT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODULES_DIR="${REPO_KIT_ROOT}/modules"
EXTENSIONS_DIR="${REPO_KIT_ROOT}/extensions"

# Globals set by loaders / resolvers
DECLARED_MODULES=()
SELECTED_MODULES=()
RESOLVED_MODULES=()
SELECTED_EXTENSIONS=()
FORCE_COPY=0
CURSOR_ONLY=0
ADDED_COUNT=0
SKIPPED_COUNT=0
OVERWRITTEN_COUNT=0

# Known extensions (non-module tooling). Expand as new --ext values land.
KNOWN_EXTENSIONS=("continue" "openspec" "forge")

die() {
  echo "error: $*" >&2
  exit 1
}

warn() {
  echo "warning: $*" >&2
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
  for sel in "${SELECTED_MODULES[@]+"${SELECTED_MODULES[@]}"}"; do
    _resolve_one "${sel}"
  done
}

# Fail if any resolved module conflicts with another resolved module.
detect_conflicts() {
  local name conflict
  for name in "${RESOLVED_MODULES[@]+"${RESOLVED_MODULES[@]}"}"; do
    load_manifest "${name}"
    for conflict in "${MODULE_CONFLICTS[@]+"${MODULE_CONFLICTS[@]}"}"; do
      if array_contains "${conflict}" "${RESOLVED_MODULES[@]+"${RESOLVED_MODULES[@]}"}"; then
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

  echo
  printf "%-12s  %-50s  %s\n" "EXTENSION" "DESCRIPTION" "DEPENDS"
  printf "%-12s  %-50s  %s\n" "---------" "-----------" "-------"
  local ext_dir ext_name ext_desc ext_depends
  for name in "${KNOWN_EXTENSIONS[@]}"; do
    load_ext_manifest "${name}"
    ext_name="${EXT_NAME:-${name}}"
    ext_desc="${EXT_DESC:-}"
    ext_depends="${EXT_DEPENDS[*]:-}"
    [[ -n "${ext_depends}" ]] || ext_depends="-"
    printf "%-12s  %-50s  %s\n" "${ext_name}" "${ext_desc}" "${ext_depends}"
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

# Ensure project-local .chat/ dirs exist (idempotent).
# Seed files (.chat/current.json, current.md, *.gitkeep) come from base/files
# via _copy_file (skipped unless --force). mkdir covers empty dirs on re-run.
ensure_chat_scaffold() {
  local chat_root="${TARGET_DIR}/.chat"
  mkdir -p \
    "${chat_root}" \
    "${chat_root}/sessions" \
    "${chat_root}/decisions" \
    "${chat_root}/archive"
  echo "chat scaffold: ${chat_root#"${TARGET_DIR}"/}/{sessions,decisions,archive}"
}

install_modules() {
  local name
  ADDED_COUNT=0
  SKIPPED_COUNT=0
  OVERWRITTEN_COUNT=0

  mkdir -p "${TARGET_DIR}"

  for name in "${RESOLVED_MODULES[@]+"${RESOLVED_MODULES[@]}"}"; do
    copy_module_files "${name}"
  done

  # .chat/ is project data, not a Cursor asset — skip during sync-cursor.
  if [[ "${CURSOR_ONLY}" -eq 0 ]] && array_contains "base" "${RESOLVED_MODULES[@]+"${RESOLVED_MODULES[@]}"}"; then
    ensure_chat_scaffold
  fi

  echo
  echo "summary"
  if [[ ${#RESOLVED_MODULES[@]} -gt 0 ]]; then
    echo "  modules:      ${RESOLVED_MODULES[*]}"
  else
    echo "  modules:      (none)"
  fi
  echo "  added:        ${ADDED_COUNT}"
  echo "  skipped:      ${SKIPPED_COUNT}"
  echo "  overwritten:  ${OVERWRITTEN_COUNT}"
}

prompt_yn() {
  local prompt="$1"
  local reply
  # Default Y
  read -r -p "${prompt} [Y/n] " reply || true
  case "${reply}" in
    ""|Y|y|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

cmd_exists() {
  command -v "$1" >/dev/null 2>&1
}

# Ensure a host command exists; prompt to install if missing. Exits on decline.
# Args: binary_name [apt_package_or_special]
# Special: cn → npm i -g @continuedev/cli
ensure_cmd() {
  local bin="$1"
  local pkg="${2:-$1}"

  if cmd_exists "${bin}"; then
    return 0
  fi

  echo "missing required command: ${bin}"
  if ! prompt_yn "Install ${bin}?"; then
    die "refused to install '${bin}'; aborting extension install"
  fi

  case "${bin}" in
    cn)
      cmd_exists npm || die "npm is required to install cn (@continuedev/cli)"
      npm i -g @continuedev/cli
      ;;
    *)
      if cmd_exists apt-get; then
        sudo apt-get install -y "${pkg}"
      else
        die "cannot auto-install '${bin}' (no apt-get). Install manually, e.g. package '${pkg}', then re-run."
      fi
      ;;
  esac

  cmd_exists "${bin}" || die "installed '${bin}' but it is still not on PATH"
  echo "  installed ${bin}"
}

extension_exists() {
  local needle="$1" e
  for e in "${KNOWN_EXTENSIONS[@]}"; do
    [[ "${e}" == "${needle}" ]] && return 0
  done
  return 1
}

# Load one extension's manifest into EXT_* variables (caller scope).
load_ext_manifest() {
  local name="$1"
  local manifest="${EXTENSIONS_DIR}/${name}/manifest.sh"
  EXT_NAME="${name}"
  EXT_DESC=""
  EXT_DEPENDS=()
  [[ -f "${manifest}" ]] || return 0
  # shellcheck source=/dev/null
  source "${manifest}"
}

# Resolve SELECTED_EXTENSIONS in-place: deps first (e.g. forge → openspec then forge).
resolve_extension_dependencies() {
  [[ ${#SELECTED_EXTENSIONS[@]} -gt 0 ]] || return 0

  local selected=("${SELECTED_EXTENSIONS[@]}")
  local resolved=()
  local visiting=()
  local visited=()

  _resolve_ext_one() {
    local name="$1"
    local dep

    extension_exists "${name}" || die "unknown extension '${name}'"

    if array_contains "${name}" "${visited[@]+"${visited[@]}"}"; then
      return 0
    fi
    if array_contains "${name}" "${visiting[@]+"${visiting[@]}"}"; then
      die "circular extension dependency involving '${name}'"
    fi

    visiting+=("${name}")
    load_ext_manifest "${name}"
    for dep in "${EXT_DEPENDS[@]+"${EXT_DEPENDS[@]}"}"; do
      _resolve_ext_one "${dep}"
    done
    if [[ ${#visiting[@]} -gt 0 ]]; then
      visiting=("${visiting[@]:0:$((${#visiting[@]} - 1))}")
    fi
    visited+=("${name}")
    resolved+=("${name}")
  }

  local sel
  for sel in "${selected[@]+"${selected[@]}"}"; do
    _resolve_ext_one "${sel}"
  done

  SELECTED_EXTENSIONS=("${resolved[@]}")
}

# Idempotently append/update a source line in ~/.bashrc for this target.
hook_bashrc_repokit() {
  local bashrc_file="$1"
  local marker="# repo-kit continue: ${TARGET_DIR}"
  local source_line="source \"${bashrc_file}\""
  local home_bashrc="${HOME}/.bashrc"
  local tmp

  touch "${home_bashrc}"

  if grep -Fqx "${marker}" "${home_bashrc}" 2>/dev/null; then
    # Refresh the source line immediately after the marker.
    tmp="$(mktemp)"
    awk -v marker="${marker}" -v src="${source_line}" '
      $0 == marker { print; print src; skip=1; next }
      skip { skip=0; if ($0 ~ /^source /) next }
      { print }
    ' "${home_bashrc}" >"${tmp}"
    mv "${tmp}" "${home_bashrc}"
    echo "  updated ~/.bashrc hook for ${TARGET_DIR}"
  else
    {
      echo ""
      echo "${marker}"
      echo "${source_line}"
    } >>"${home_bashrc}"
    echo "  added ~/.bashrc hook for ${TARGET_DIR}"
  fi
}

install_continue_ext() {
  local ext_root="${EXTENSIONS_DIR}/continue"
  local scripts_src="${ext_root}/files/scripts"
  local rules_src="${ext_root}/.continue/rules"
  local prompts_src="${ext_root}/.continue/prompts"
  local template="${ext_root}/bashrc_repokit"
  local scripts_dest="${TARGET_DIR}/.repo-kit/scripts"
  local bashrc_dest="${TARGET_DIR}/.repo-kit/bashrc_repokit"
  local src dest

  [[ -d "${ext_root}" ]] || die "extension 'continue' missing under ${EXTENSIONS_DIR}"

  echo "extension: continue"
  echo "  checking host dependencies..."

  ensure_cmd cn
  ensure_cmd python3 python3
  ensure_cmd grep grep
  ensure_cmd gh gh
  ensure_cmd curl curl
  ensure_cmd rg ripgrep

  if [[ ! -f "${HOME}/.continue/config.yaml" ]]; then
    warn "~/.continue/config.yaml not found — Continue CLI may need local config before cn works"
  fi

  echo "  copying .continue/rules and prompts..."
  shopt -s nullglob
  for src in "${rules_src}"/*; do
    [[ -f "${src}" ]] || continue
    dest="${TARGET_DIR}/.continue/rules/$(basename "${src}")"
    _copy_file "${src}" "${dest}"
  done
  for src in "${prompts_src}"/*; do
    [[ -f "${src}" ]] || continue
    dest="${TARGET_DIR}/.continue/prompts/$(basename "${src}")"
    _copy_file "${src}" "${dest}"
  done

  echo "  copying ai-*.sh to .repo-kit/scripts/..."
  mkdir -p "${scripts_dest}"
  for src in "${scripts_src}"/ai-*.sh; do
    [[ -f "${src}" ]] || continue
    dest="${scripts_dest}/$(basename "${src}")"
    _copy_file "${src}" "${dest}"
    chmod +x "${dest}"
  done
  shopt -u nullglob

  echo "  writing .repo-kit/bashrc_repokit..."
  mkdir -p "$(dirname "${bashrc_dest}")"
  sed \
    -e "s|@TARGET_DIR@|${TARGET_DIR}|g" \
    -e "s|@SCRIPTS_DIR@|${scripts_dest}|g" \
    "${template}" >"${bashrc_dest}"
  echo "  wrote     .repo-kit/bashrc_repokit"

  hook_bashrc_repokit "${bashrc_dest}"

  echo
  echo "  activate now:  source ~/.bashrc"
  echo "  or:            source ${bashrc_dest}"
}

# Host: npm i -g @fission-ai/openspec@latest; project: openspec init --tools cursor if needed.
install_openspec_ext() {
  echo "extension: openspec"

  cmd_exists npm || die "npm is required to install openspec (@fission-ai/openspec)"

  echo "  npm i -g @fission-ai/openspec@latest..."
  npm i -g @fission-ai/openspec@latest
  cmd_exists openspec || die "installed openspec but it is still not on PATH"

  if [[ -f "${TARGET_DIR}/openspec/config.yaml" && "${FORCE_COPY}" -eq 0 ]]; then
    echo "  openspec already initialized in ${TARGET_DIR}; skipping init (pass --force to re-run)"
    return 0
  fi

  echo "  openspec init --tools cursor..."
  (
    cd "${TARGET_DIR}"
    if [[ "${FORCE_COPY}" -eq 1 ]]; then
      openspec init --tools cursor --force
    else
      openspec init --tools cursor
    fi
  )
  echo "  openspec ready in ${TARGET_DIR}"
}

# Host: npm i -g @izkac/forgekit@latest + forgekit install; project: forge init if needed.
# Ordering: resolve_extension_dependencies always runs openspec before forge.
install_forge_ext() {
  echo "extension: forge"

  cmd_exists npm || die "npm is required to install forgekit (@izkac/forgekit)"

  echo "  npm i -g @izkac/forgekit@latest..."
  npm i -g @izkac/forgekit@latest
  cmd_exists forgekit || die "installed forgekit but it is still not on PATH"
  cmd_exists forge || die "installed forgekit but 'forge' is still not on PATH"

  echo "  forgekit install (cursor + openspec)..."
  forgekit install --skills forge --agents cursor --openspec --force

  if [[ -f "${TARGET_DIR}/.forge/config.json" && "${FORCE_COPY}" -eq 0 ]]; then
    echo "  forge already initialized in ${TARGET_DIR}; skipping init (pass --force to re-run)"
    return 0
  fi

  echo "  forge init --cursor --openspec..."
  (
    cd "${TARGET_DIR}"
    forge init --cursor --openspec
  )
  echo "  forge ready in ${TARGET_DIR}"
}

install_extensions() {
  local name
  [[ ${#SELECTED_EXTENSIONS[@]} -gt 0 ]] || return 0

  resolve_extension_dependencies
  echo "extensions: ${SELECTED_EXTENSIONS[*]}"

  for name in "${SELECTED_EXTENSIONS[@]}"; do
    case "${name}" in
      continue) install_continue_ext ;;
      openspec) install_openspec_ext ;;
      forge) install_forge_ext ;;
      *) die "unsupported extension '${name}'" ;;
    esac
  done
}

# Parse common CLI: [target] [--module ...] [--ext <name>] [--force] [--list] [--help]
# Sets: TARGET_DIR, SELECTED_MODULES, SELECTED_EXTENSIONS, FORCE_COPY, DO_LIST
parse_common_args() {
  TARGET_DIR=""
  SELECTED_MODULES=()
  SELECTED_EXTENSIONS=()
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
      --ext)
        [[ $# -gt 0 ]] || die "--ext requires a name (e.g. --ext continue)"
        name="$1"
        shift
        extension_exists "${name}" || die "unknown extension '${name}' (known: ${KNOWN_EXTENSIONS[*]})"
        if ! array_contains "${name}" "${SELECTED_EXTENSIONS[@]+"${SELECTED_EXTENSIONS[@]}"}"; then
          SELECTED_EXTENSIONS+=("${name}")
        fi
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
        [[ "${matched}" -eq 1 ]] || die "unknown flag '${arg}' (known modules: ${DECLARED_MODULES[*]}; extensions via --ext: ${KNOWN_EXTENSIONS[*]})"
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
