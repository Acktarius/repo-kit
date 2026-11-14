#!/usr/bin/env bash
# Shared helpers for repo-kit scripts.
# shellcheck disable=SC2034

set -euo pipefail

REPO_KIT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODULES_DIR="${REPO_KIT_ROOT}/modules"
EXTENSIONS_DIR="${REPO_KIT_ROOT}/extensions"
TOOLS_DIR="${REPO_KIT_ROOT}/tools"

# Globals set by loaders / resolvers
DECLARED_MODULES=()
SELECTED_MODULES=()
RESOLVED_MODULES=()
SELECTED_EXTENSIONS=()
DECLARED_TOOLS=()
SELECTED_TOOLS=()
RESOLVED_TOOLS=()
FORCE_COPY=0
CURSOR_ONLY=0
ADDED_COUNT=0
SKIPPED_COUNT=0
DIFFERENT_COUNT=0
OVERWRITTEN_COUNT=0
PRESERVED_COUNT=0

# Known extensions (non-module tooling). Expand as new --ext values land.
KNOWN_EXTENSIONS=("continue" "openspec" "forge" "act" "hermes")

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
  # Project-owned paths (relative to files/): created when missing, never overwritten.
  MODULE_PRESERVE=()

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

# Discover tool names from tools/*/manifest.sh
discover_tools() {
  DECLARED_TOOLS=()
  local manifest dir name
  shopt -s nullglob
  for manifest in "${TOOLS_DIR}"/*/manifest.sh; do
    dir="$(dirname "${manifest}")"
    name="$(basename "${dir}")"
    DECLARED_TOOLS+=("${name}")
  done
  shopt -u nullglob
}

# Load one tool's manifest into TOOL_* variables (caller scope).
load_tool_manifest() {
  local name="$1"
  local path="${TOOLS_DIR}/${name}/manifest.sh"
  [[ -f "${path}" ]] || die "tool '${name}' has no manifest.sh"

  TOOL_NAME=""
  TOOL_DESC=""
  TOOL_DEPENDS=()
  # Project-owned paths (relative to files/): created when missing, never overwritten.
  TOOL_PRESERVE=()

  # shellcheck source=/dev/null
  source "${path}"

  [[ -n "${TOOL_NAME}" ]] || die "tool '${name}' did not set TOOL_NAME"
  [[ "${TOOL_NAME}" == "${name}" ]] || die "tool '${name}' TOOL_NAME='${TOOL_NAME}' does not match directory"
}

tool_exists() {
  local needle="$1" t
  for t in "${DECLARED_TOOLS[@]+"${DECLARED_TOOLS[@]}"}"; do
    [[ "${t}" == "${needle}" ]] && return 0
  done
  return 1
}

# Resolve SELECTED_TOOLS -> RESOLVED_TOOLS (deps first, topo order).
resolve_tool_dependencies() {
  RESOLVED_TOOLS=()
  [[ ${#SELECTED_TOOLS[@]} -gt 0 ]] || return 0

  local visiting=()
  local visited=()

  _resolve_tool_one() {
    local name="$1"
    local dep

    tool_exists "${name}" || die "unknown tool '${name}'"

    if array_contains "${name}" "${visited[@]+"${visited[@]}"}"; then
      return 0
    fi
    if array_contains "${name}" "${visiting[@]+"${visiting[@]}"}"; then
      die "circular tool dependency involving '${name}'"
    fi

    visiting+=("${name}")
    load_tool_manifest "${name}"
    for dep in "${TOOL_DEPENDS[@]+"${TOOL_DEPENDS[@]}"}"; do
      _resolve_tool_one "${dep}"
    done
    if [[ ${#visiting[@]} -gt 0 ]]; then
      visiting=("${visiting[@]:0:$((${#visiting[@]} - 1))}")
    fi
    visited+=("${name}")
    RESOLVED_TOOLS+=("${name}")
  }

  local sel
  for sel in "${SELECTED_TOOLS[@]+"${SELECTED_TOOLS[@]}"}"; do
    _resolve_tool_one "${sel}"
  done
}

list_modules() {
  discover_modules
  discover_tools
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
  local ext_name ext_desc ext_depends
  for name in "${KNOWN_EXTENSIONS[@]}"; do
    load_ext_manifest "${name}"
    ext_name="${EXT_NAME:-${name}}"
    ext_desc="${EXT_DESC:-}"
    ext_depends="${EXT_DEPENDS[*]:-}"
    [[ -n "${ext_depends}" ]] || ext_depends="-"
    printf "%-12s  %-50s  %s\n" "${ext_name}" "${ext_desc}" "${ext_depends}"
  done

  echo
  printf "%-12s  %-50s  %s\n" "TOOL" "DESCRIPTION" "DEPENDS"
  printf "%-12s  %-50s  %s\n" "----" "-----------" "-------"
  local tool_name tool_desc tool_depends
  if [[ ${#DECLARED_TOOLS[@]} -eq 0 ]]; then
    printf "%-12s  %-50s  %s\n" "(none)" "-" "-"
  else
    for name in "${DECLARED_TOOLS[@]}"; do
      load_tool_manifest "${name}"
      tool_name="${TOOL_NAME:-${name}}"
      tool_desc="${TOOL_DESC:-}"
      tool_depends="${TOOL_DEPENDS[*]:-}"
      [[ -n "${tool_depends}" ]] || tool_depends="-"
      printf "%-12s  %-50s  %s\n" "${tool_name}" "${tool_desc}" "${tool_depends}"
    done
  fi
}

# Copy one file into target, respecting FORCE_COPY.
# A third argument of 1 marks a preserved path: existing content is never overwritten.
_copy_file() {
  local src="$1"
  local dest="$2"
  local preserve="${3:-0}"

  if [[ -e "${dest}" || -L "${dest}" ]]; then
    if [[ "${preserve}" -eq 1 ]]; then
      PRESERVED_COUNT=$((PRESERVED_COUNT + 1))
      echo "  preserve   ${dest#"${TARGET_DIR}"/}"
    elif [[ "${FORCE_COPY}" -eq 1 ]]; then
      mkdir -p "$(dirname "${dest}")"
      cp -f "${src}" "${dest}"
      OVERWRITTEN_COUNT=$((OVERWRITTEN_COUNT + 1))
      echo "  overwrite  ${dest#"${TARGET_DIR}"/}"
    else
      SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
      if [[ -L "${dest}" || ! -f "${dest}" ]]; then
        echo "  skip       ${dest#"${TARGET_DIR}"/} (not a regular file)"
      elif cmp -s "${src}" "${dest}"; then
        echo "  unchanged  ${dest#"${TARGET_DIR}"/}"
      else
        DIFFERENT_COUNT=$((DIFFERENT_COUNT + 1))
        echo "  different  ${dest#"${TARGET_DIR}"/} (differs from template; kept, use --force to overwrite)"
      fi
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
  local rel dest preserve

  [[ -d "${src_root}" ]] || die "module '${name}' has no files/ directory"

  load_manifest "${name}"
  echo "module: ${name}"

  while IFS= read -r -d '' src; do
    rel="${src#"${src_root}"/}"

    if [[ "${CURSOR_ONLY}" -eq 1 ]]; then
      [[ "${rel}" == .cursor/* ]] || continue
    fi

    preserve=0
    if array_contains "${rel}" "${MODULE_PRESERVE[@]+"${MODULE_PRESERVE[@]}"}"; then
      preserve=1
    fi
    dest="${TARGET_DIR}/${rel}"
    _copy_file "${src}" "${dest}" "${preserve}"
  done < <(find "${src_root}" -type f -print0 | sort -z)
}

# Ensure project-local .repo-kit/chat/ dirs exist (idempotent).
# Seed files (.repo-kit/chat/current.json, current.md) come from base/files
# via _copy_file (skipped unless --force). mkdir covers empty dirs on re-run.
ensure_repo_kit_scaffold() {
  local chat_root="${TARGET_DIR}/.repo-kit/chat"
  mkdir -p \
    "${chat_root}" \
    "${chat_root}/sessions" \
    "${chat_root}/decisions" \
    "${chat_root}/archive"
  echo "repo-kit scaffold: ${chat_root#"${TARGET_DIR}"/}/{sessions,decisions,archive}"
}

# Read repo-kit release version from VERSION at kit root.
read_kit_version() {
  local version_file="${REPO_KIT_ROOT}/VERSION"
  [[ -f "${version_file}" ]] || die "missing VERSION at ${version_file}"
  tr -d '[:space:]' < "${version_file}"
}

# Read installed version from target.
# Missing .repo-kit/version is treated as <= 1.0.1: 1.0.0 when legacy .chat/ exists, else 1.0.1.
read_installed_version() {
  local target="$1"
  local version_file="${target}/.repo-kit/version"
  if [[ -f "${version_file}" ]]; then
    tr -d '[:space:]' < "${version_file}"
    return 0
  fi
  if [[ -d "${target}/.chat" ]]; then
    echo "1.0.0"
  else
    echo "1.0.1"
  fi
}

# Return 0 when $1 < $2 (semver via sort -V).
version_lt() {
  [[ "$(printf '%s\n' "$1" "$2" | sort -V | head -n1)" == "$1" && "$1" != "$2" ]]
}

# Return 0 when $1 >= $2.
version_ge() {
  ! version_lt "$1" "$2"
}

write_installed_version() {
  local target="$1"
  local version="$2"
  mkdir -p "${target}/.repo-kit"
  printf '%s\n' "${version}" > "${target}/.repo-kit/version"
  echo "version: ${version} -> ${target}/.repo-kit/version"
}

# Move legacy .chat/ contents into .repo-kit/chat/ (1.0.0 -> 1.0.1).
_migrate_chat_entry() {
  local src="$1"
  local dest="$2"
  local child

  if [[ -d "${src}" && -d "${dest}" ]]; then
    shopt -s dotglob nullglob
    for child in "${src}"/*; do
      [[ -e "${child}" ]] || continue
      _migrate_chat_entry "${child}" "${dest}/$(basename "${child}")"
    done
    shopt -u dotglob nullglob
    rmdir "${src}" 2>/dev/null || die "legacy directory not empty after merge: ${src}"
    return 0
  fi

  if [[ -e "${dest}" ]]; then
    die "migration conflict: ${dest} already exists (legacy ${src})"
  fi

  mv "${src}" "${dest}"
  echo "  moved     ${src#"${TARGET_DIR}"/} -> ${dest#"${TARGET_DIR}"/}"
}

migrate_chat_to_repo_kit() {
  local target="$1"
  local legacy="${target}/.chat"
  local chat_root="${target}/.repo-kit/chat"
  local entry

  TARGET_DIR="${target}"
  mkdir -p "${chat_root}" "${chat_root}/sessions" "${chat_root}/decisions" "${chat_root}/archive"

  if [[ ! -d "${legacy}" ]]; then
    echo "migrate chat: no legacy .chat/ at ${legacy}"
    return 0
  fi

  shopt -s dotglob nullglob
  for entry in "${legacy}"/*; do
    [[ -e "${entry}" ]] || continue
    _migrate_chat_entry "${entry}" "${chat_root}/$(basename "${entry}")"
  done
  shopt -u dotglob nullglob

  rmdir "${legacy}" 2>/dev/null || die "legacy .chat/ not empty after move: ${legacy}"
  echo "  removed   .chat/"
}

# Upgrade root .gitignore from legacy .findings/ to .repo-kit/findings/.
_migrate_gitignore_findings() {
  local target="$1"
  local gitignore="${target}/.gitignore"
  local tmp
  local had_new=0 had_old=0

  if [[ ! -f "${gitignore}" ]]; then
    printf '%s\n' '.repo-kit/findings/' > "${gitignore}"
    echo "  added     .gitignore: .repo-kit/findings/"
    return 0
  fi

  grep -qF '.repo-kit/findings/' "${gitignore}" && had_new=1
  grep -qF '.findings/' "${gitignore}" && had_old=1

  if [[ "${had_new}" -eq 0 ]]; then
    printf '\n%s\n' '.repo-kit/findings/' >> "${gitignore}"
    echo "  added     .gitignore: .repo-kit/findings/"
  fi

  if [[ "${had_old}" -eq 1 ]]; then
    tmp="$(mktemp)"
    grep -Fv '.findings/' "${gitignore}" > "${tmp}"
    mv "${tmp}" "${gitignore}"
    echo "  removed   .gitignore: .findings/"
  fi
}

# Move legacy .findings/ contents into .repo-kit/findings/ (1.0.1 -> 1.0.2).
migrate_findings_to_repo_kit() {
  local target="$1"
  local legacy="${target}/.findings"
  local findings_root="${target}/.repo-kit/findings"
  local entry

  TARGET_DIR="${target}"
  mkdir -p "${findings_root}"

  _migrate_gitignore_findings "${target}"

  if [[ ! -d "${legacy}" ]]; then
    echo "migrate findings: no legacy .findings/ at ${legacy}"
    return 0
  fi

  shopt -s dotglob nullglob
  for entry in "${legacy}"/*; do
    [[ -e "${entry}" ]] || continue
    _migrate_chat_entry "${entry}" "${findings_root}/$(basename "${entry}")"
  done
  shopt -u dotglob nullglob

  rmdir "${legacy}" 2>/dev/null || die "legacy .findings/ not empty after move: ${legacy}"
  echo "  removed   .findings/"
}

install_modules() {
  local name
  ADDED_COUNT=0
  SKIPPED_COUNT=0
  DIFFERENT_COUNT=0
  OVERWRITTEN_COUNT=0
  PRESERVED_COUNT=0

  mkdir -p "${TARGET_DIR}"

  for name in "${RESOLVED_MODULES[@]+"${RESOLVED_MODULES[@]}"}"; do
    copy_module_files "${name}"
  done

  # .repo-kit/chat/ is project data, not a Cursor asset — skip during sync-cursor.
  if [[ "${CURSOR_ONLY}" -eq 0 ]] && array_contains "base" "${RESOLVED_MODULES[@]+"${RESOLVED_MODULES[@]}"}"; then
    ensure_repo_kit_scaffold
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
  echo "    different:  ${DIFFERENT_COUNT}"
  echo "  overwritten:  ${OVERWRITTEN_COUNT}"
  echo "  preserved:    ${PRESERVED_COUNT}"
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

# Idempotently append/update a source line in ~/.bashrc after a marker
# (default: one marker per continue target).
hook_bashrc() {
  local bashrc_file="$1"
  local marker="${2:-# repo-kit continue: ${TARGET_DIR}}"
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
    echo "  updated ~/.bashrc hook: ${marker#\# }"
  else
    {
      echo ""
      echo "${marker}"
      echo "${source_line}"
    } >>"${home_bashrc}"
    echo "  added ~/.bashrc hook: ${marker#\# }"
  fi
}

install_continue_ext() {
  local ext_root="${EXTENSIONS_DIR}/continue"
  local scripts_src="${ext_root}/files/scripts"
  local cursor_rules_src="${ext_root}/files/.cursor/rules"
  local agents_src="${ext_root}/files/AGENTS.md"
  local rules_src="${ext_root}/.continue/rules"
  local prompts_src="${ext_root}/.continue/prompts"
  local template="${ext_root}/.bashrc_continue"
  local scripts_dest="${TARGET_DIR}/.repo-kit/scripts"
  local bashrc_dest="${TARGET_DIR}/.repo-kit/.bashrc_continue"
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

  echo "  copying .cursor/rules (dispatch + continue-sidekick)..."
  shopt -s nullglob
  for src in "${cursor_rules_src}"/*; do
    [[ -f "${src}" ]] || continue
    dest="${TARGET_DIR}/.cursor/rules/$(basename "${src}")"
    _copy_file "${src}" "${dest}"
  done

  echo "  copying AGENTS.md..."
  [[ -f "${agents_src}" ]] || die "continue extension missing files/AGENTS.md"
  _copy_file "${agents_src}" "${TARGET_DIR}/AGENTS.md"

  echo "  copying .continue/rules and prompts..."
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

  echo "  writing .repo-kit/.bashrc_continue..."
  mkdir -p "$(dirname "${bashrc_dest}")"
  sed \
    -e "s|@TARGET_DIR@|${TARGET_DIR}|g" \
    -e "s|@SCRIPTS_DIR@|${scripts_dest}|g" \
    "${template}" >"${bashrc_dest}"
  echo "  wrote     .repo-kit/.bashrc_continue"

  hook_bashrc "${bashrc_dest}"

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

# Install nektos/act from GitHub releases (Linux x86_64 / arm64).
_install_act_binary() {
  local url arch
  cmd_exists curl || die "curl is required to install act"

  case "$(uname -m)" in
    x86_64|amd64) url="https://github.com/nektos/act/releases/latest/download/act_Linux_x86_64.tar.gz" ;;
    aarch64|arm64) url="https://github.com/nektos/act/releases/latest/download/act_Linux_arm64.tar.gz" ;;
    *) die "unsupported architecture for act auto-install: $(uname -m)" ;;
  esac

  curl -sSfL "${url}" | sudo tar xz -C /usr/local/bin act
}

ensure_act() {
  if cmd_exists act; then
    return 0
  fi

  echo "missing required command: act"
  if ! prompt_yn "Install act?"; then
    die "refused to install 'act'; aborting extension install"
  fi

  if [[ "$(uname -s)" != "Linux" ]]; then
    die "cannot auto-install act on this OS; install from https://github.com/nektos/act/releases then re-run"
  fi

  _install_act_binary
  cmd_exists act || die "installed act but it is still not on PATH"
  echo "  installed act"
}

ensure_docker_daemon() {
  ensure_cmd docker docker.io

  if docker info >/dev/null 2>&1; then
    return 0
  fi

  if ! id -nG "${USER}" 2>/dev/null | tr ' ' '\n' | grep -qx docker; then
    echo "docker is installed but ${USER} is not in the 'docker' group"
    if ! prompt_yn "Add ${USER} to the 'docker' group?"; then
      die "refused to add user to 'docker' group; aborting extension install"
    fi
    sudo usermod -aG docker "${USER}"
    echo "  added ${USER} to 'docker' group"
  fi

  if docker info >/dev/null 2>&1; then
    return 0
  fi

  # Group membership applies to new sessions; sg verifies access without re-login.
  if getent group docker >/dev/null 2>&1 && sg docker -c "docker info >/dev/null 2>&1" 2>/dev/null; then
    echo "  docker reachable via 'docker' group (log out/in or: newgrp docker)"
    return 0
  fi

  die "docker is installed but the daemon is not reachable; start Docker, then re-run"
}

install_act_ext() {
  local ext_root="${EXTENSIONS_DIR}/act"
  local scripts_src="${ext_root}/files/scripts"
  local commands_src="${ext_root}/files/.cursor/commands"
  local skills_src="${ext_root}/files/.cursor/skills"
  local actrc_src="${ext_root}/files/.actrc"
  local scripts_dest="${TARGET_DIR}/.repo-kit/scripts"
  local src dest skill_dir skill_name

  [[ -d "${ext_root}" ]] || die "extension 'act' missing under ${EXTENSIONS_DIR}"

  echo "extension: act"
  echo "  checking host dependencies..."

  ensure_docker_daemon
  ensure_act

  echo "  copying .cursor/commands..."
  shopt -s nullglob
  for src in "${commands_src}"/*; do
    [[ -f "${src}" ]] || continue
    dest="${TARGET_DIR}/.cursor/commands/$(basename "${src}")"
    _copy_file "${src}" "${dest}"
  done

  echo "  copying .cursor/skills..."
  for skill_dir in "${skills_src}"/*; do
    [[ -d "${skill_dir}" ]] || continue
    skill_name="$(basename "${skill_dir}")"
    mkdir -p "${TARGET_DIR}/.cursor/skills/${skill_name}"
    for src in "${skill_dir}"/*; do
      [[ -f "${src}" ]] || continue
      dest="${TARGET_DIR}/.cursor/skills/${skill_name}/$(basename "${src}")"
      _copy_file "${src}" "${dest}"
    done
  done

  echo "  copying act-run-workflows.sh to .repo-kit/scripts/..."
  mkdir -p "${scripts_dest}"
  [[ -f "${scripts_src}/act-run-workflows.sh" ]] || die "act extension missing files/scripts/act-run-workflows.sh"
  dest="${scripts_dest}/act-run-workflows.sh"
  _copy_file "${scripts_src}/act-run-workflows.sh" "${dest}"
  chmod +x "${dest}"

  echo "  copying .actrc..."
  [[ -f "${actrc_src}" ]] || die "act extension missing files/.actrc"
  _copy_file "${actrc_src}" "${TARGET_DIR}/.actrc"
  shopt -u nullglob

  echo "  act ready in ${TARGET_DIR}"
}

# Copy Hermes phased review rules into target .repo-kit/hermes/review-rules/,
# task triggers into .repo-kit/hermes/tasks/, phase-command skills into
# .repo-kit/hermes/skills/, the hermes-review.sh launcher, seed an empty
# .repo-kit/hermes/reports/ directory, and hook ~/.bashrc to the kit's
# .bashrc_hermes (one hook for all targets).
install_hermes_ext() {
  local ext_root="${EXTENSIONS_DIR}/hermes"
  local rules_src="${ext_root}/rules"
  local tasks_src="${ext_root}/tasks"
  local skills_src="${ext_root}/skills"
  local launcher_src="${ext_root}/hermes-review.sh"
  local readme_src="${ext_root}/README.md"
  local reports_gitkeep_src="${ext_root}/reports/.gitkeep"
  local bashrc_src="${ext_root}/.bashrc_hermes"
  local hermes_root="${TARGET_DIR}/.repo-kit/hermes"
  local dest_dir="${hermes_root}/review-rules"
  local tasks_dir="${hermes_root}/tasks"
  local skills_dir="${hermes_root}/skills"
  local reports_dir="${hermes_root}/reports"
  local src dest

  [[ -d "${ext_root}" ]] || die "extension 'hermes' missing under ${EXTENSIONS_DIR}"
  [[ -d "${rules_src}" ]] || die "hermes extension missing rules/"
  [[ -d "${tasks_src}" ]] || die "hermes extension missing tasks/"
  [[ -d "${skills_src}" ]] || die "hermes extension missing skills/"
  [[ -f "${launcher_src}" ]] || die "hermes extension missing hermes-review.sh"
  [[ -f "${reports_gitkeep_src}" ]] || die "hermes extension missing reports/.gitkeep"
  [[ -f "${bashrc_src}" ]] || die "hermes extension missing .bashrc_hermes"

  echo "extension: hermes"
  echo "  copying review rules to .repo-kit/hermes/review-rules/..."

  shopt -s nullglob
  local found=0
  for src in "${rules_src}"/*.md; do
    [[ -f "${src}" ]] || continue
    found=1
    dest="${dest_dir}/$(basename "${src}")"
    _copy_file "${src}" "${dest}"
  done
  shopt -u nullglob
  [[ "${found}" -eq 1 ]] || die "hermes extension has no rules/*.md"

  if [[ -f "${readme_src}" ]]; then
    _copy_file "${readme_src}" "${dest_dir}/README.md"
  fi

  echo "  copying tasks to .repo-kit/hermes/tasks/..."
  shopt -s nullglob
  found=0
  for src in "${tasks_src}"/*.md; do
    [[ -f "${src}" ]] || continue
    found=1
    _copy_file "${src}" "${tasks_dir}/$(basename "${src}")"
  done
  shopt -u nullglob
  [[ "${found}" -eq 1 ]] || die "hermes extension has no tasks/*.md"

  echo "  copying phase commands to .repo-kit/hermes/skills/..."
  shopt -s nullglob
  found=0
  for src in "${skills_src}"/*/SKILL.md; do
    found=1
    _copy_file "${src}" "${skills_dir}/$(basename "$(dirname "${src}")")/SKILL.md"
  done
  shopt -u nullglob
  [[ "${found}" -eq 1 ]] || die "hermes extension has no skills/*/SKILL.md"

  echo "  copying launcher to .repo-kit/hermes/hermes-review.sh..."
  _copy_file "${launcher_src}" "${hermes_root}/hermes-review.sh"
  chmod +x "${hermes_root}/hermes-review.sh"

  echo "  seeding .repo-kit/hermes/reports/..."
  _copy_file "${reports_gitkeep_src}" "${reports_dir}/.gitkeep"

  hook_bashrc "${bashrc_src}" "# repo-kit hermes"

  echo "  hermes ready in ${hermes_root}/{review-rules,tasks,skills,reports}"
  echo "  activate now:  source ~/.bashrc"
  echo "  then, from the target repository:  hermes-review"
  echo "  (without repo-kit:  .repo-kit/hermes/hermes-review.sh)"
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
      act) install_act_ext ;;
      hermes) install_hermes_ext ;;
      *) die "unsupported extension '${name}'" ;;
    esac
  done
}

# Copy files/ from a tool into TARGET_DIR (full install; sync-cursor does not strip tools).
copy_tool_files() {
  local name="$1"
  local src_root="${TOOLS_DIR}/${name}/files"
  local rel dest preserve

  [[ -d "${src_root}" ]] || die "tool '${name}' has no files/ directory"

  load_tool_manifest "${name}"
  echo "tool: ${name}"

  while IFS= read -r -d '' src; do
    rel="${src#"${src_root}"/}"
    # Never distribute bytecode / caches from the kit checkout.
    case "${rel}" in
      *__pycache__*|*.pyc|*.pyo) continue ;;
    esac
    preserve=0
    if array_contains "${rel}" "${TOOL_PRESERVE[@]+"${TOOL_PRESERVE[@]}"}"; then
      preserve=1
    fi
    dest="${TARGET_DIR}/${rel}"
    _copy_file "${src}" "${dest}" "${preserve}"
  done < <(find "${src_root}" -type f -print0 | sort -z)
}

# Prompt that refuses on EOF / non-interactive (unlike prompt_yn, which treats EOF as Yes).
prompt_yn_interactive() {
  local prompt="$1"
  local reply

  if [[ ! -t 0 ]]; then
    if [[ "${REPO_KIT_TOOL_ASSUME_YES:-0}" == "1" ]]; then
      echo "${prompt} [Y/n] Y (REPO_KIT_TOOL_ASSUME_YES=1)"
      return 0
    fi
    echo "${prompt} [Y/n]" >&2
    echo "error: non-interactive stdin; refuse network install without consent (set REPO_KIT_TOOL_ASSUME_YES=1 to allow in CI/tests)" >&2
    return 1
  fi

  if ! read -r -p "${prompt} [Y/n] " reply; then
    echo "error: no response; refuse network install without consent" >&2
    return 1
  fi
  case "${reply}" in
    ""|Y|y|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

# --- py-indexer (user-wide application + per-project config) -----------------

# Kit-required compat_version and capability (must match tools/py-indexer).
_PY_INDEXER_REQUIRED_COMPAT="0.3.3"
_PY_INDEXER_REQUIRED_CAPABILITY="staging-publish"

_py_indexer_data_home() {
  if [[ -n "${XDG_DATA_HOME:-}" ]]; then
    printf '%s\n' "${XDG_DATA_HOME}/py-indexer"
  else
    printf '%s\n' "${HOME}/.local/share/py-indexer"
  fi
}

_py_indexer_bin_dir() {
  if [[ -n "${XDG_BIN_HOME:-}" ]]; then
    printf '%s\n' "${XDG_BIN_HOME}"
  else
    printf '%s\n' "${HOME}/.local/bin"
  fi
}

_py_indexer_venv_dir() {
  printf '%s\n' "$(_py_indexer_data_home)/venv"
}

_py_indexer_exe_path() {
  printf '%s\n' "$(_py_indexer_bin_dir)/py-indexer"
}

# Print identity JSON from an executable; nonempty stdout on success.
_py_indexer_probe() {
  local exe="$1"
  [[ -x "${exe}" ]] || return 1
  "${exe}" --app-id 2>/dev/null
}

_py_indexer_compat_ok() {
  local json="$1"
  local required="${2:-${_PY_INDEXER_REQUIRED_COMPAT}}"
  local capability="${3:-${_PY_INDEXER_REQUIRED_CAPABILITY}}"
  python3 - "${json}" "${required}" "${capability}" <<'PY'
import json, sys
raw, required, capability = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    doc = json.loads(raw)
except Exception:
    sys.exit(1)
if doc.get("name") != "py-indexer":
    sys.exit(1)
if not doc.get("fts5"):
    sys.exit(1)
# 0.2.1 probes omit cli_ready and capability. Both are required now.
if doc.get("cli_ready") is not True:
    sys.exit(1)
if doc.get("capability") != capability:
    sys.exit(1)
ver = str(doc.get("compat_version") or doc.get("version") or "")

def parts(v):
    out = []
    for p in v.split("."):
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    return out

a, b = parts(required), parts(ver)
n = max(len(a), len(b))
a += [0] * (n - len(a))
b += [0] * (n - len(b))
sys.exit(0 if b >= a else 1)
PY
}

# Resolve a verified py-indexer executable (empty if none).
_py_indexer_find_verified() {
  local candidates=()
  local exe bin_dir json
  bin_dir="$(_py_indexer_bin_dir)"
  candidates+=("${bin_dir}/py-indexer")
  if cmd_exists py-indexer; then
    candidates+=("$(command -v py-indexer)")
  fi
  candidates+=("$(_py_indexer_venv_dir)/bin/py-indexer")

  for exe in "${candidates[@]}"; do
    [[ -n "${exe}" && -x "${exe}" ]] || continue
    json="$(_py_indexer_probe "${exe}" || true)"
    [[ -n "${json}" ]] || continue
    if _py_indexer_compat_ok "${json}" "${_PY_INDEXER_REQUIRED_COMPAT}"; then
      printf '%s\n' "${exe}"
      return 0
    fi
  done
  return 1
}

_py_indexer_find_any_ours() {
  local candidates=() exe json
  candidates+=("$(_py_indexer_bin_dir)/py-indexer")
  if cmd_exists py-indexer; then
    candidates+=("$(command -v py-indexer)")
  fi
  candidates+=("$(_py_indexer_venv_dir)/bin/py-indexer")
  for exe in "${candidates[@]}"; do
    [[ -n "${exe}" && -x "${exe}" ]] || continue
    json="$(_py_indexer_probe "${exe}" || true)"
    [[ -n "${json}" ]] || continue
    if python3 -c 'import json,sys; d=json.loads(sys.argv[1]); raise SystemExit(0 if d.get("name")=="py-indexer" else 1)' "${json}"; then
      printf '%s\n' "${exe}"
      return 0
    fi
  done
  return 1
}

# Shell wrapper so the launcher survives spaces in HOME / XDG paths.
# A raw "#!<interpreter>" shebang is split on whitespace by the kernel.
_py_indexer_write_launcher() {
  local py="$1"
  local dest="$2"
  python3 - "${py}" "${dest}" <<'PY'
import os, sys
py, dest = sys.argv[1], sys.argv[2]
quoted = "'" + py.replace("'", "'\\''") + "'"
text = "#!/bin/sh\nexec " + quoted + " -m py_indexer \"$@\"\n"
with open(dest, "w", encoding="utf-8") as fh:
    fh.write(text)
os.chmod(dest, 0o755)
PY
}

_py_indexer_venv_python() {
  local exe="$1"
  local resolved bin
  resolved="$(readlink -f "${exe}" 2>/dev/null || printf '%s\n' "${exe}")"
  bin="$(dirname "${resolved}")"
  if [[ -x "${bin}/python" ]]; then
    printf '%s\n' "${bin}/python"
    return 0
  fi
  return 1
}

# Report MCP by importing the API serve uses, not by package metadata alone.
_py_indexer_mcp_import_ok() {
  local py="$1"
  "${py}" -c 'from mcp.server.fastmcp import FastMCP' >/dev/null 2>&1
}

_offer_py_indexer_mcp_repair() {
  local exe="$1"
  local py json
  json="$(_py_indexer_probe "${exe}" || true)"
  if [[ -n "${json}" ]] && python3 -c 'import json,sys; d=json.loads(sys.argv[1]); raise SystemExit(0 if d.get("mcp_ready") is True else 1)' "${json}"; then
    echo "  mcp       ready (mcp.server.fastmcp.FastMCP)"
    return 0
  fi
  if ! py="$(_py_indexer_venv_python "${exe}")"; then
    warn "shared py-indexer at ${exe} is CLI-only; its virtualenv python was not found, so mcp was not installed"
    return 0
  fi
  if _py_indexer_mcp_import_ok "${py}"; then
    echo "  mcp       ready (mcp.server.fastmcp.FastMCP)"
    return 0
  fi
  if [[ "${REPO_KIT_TOOL_SKIP_DEPS:-0}" == "1" ]]; then
    warn "shared py-indexer is CLI-only (installed offline without mcp; REPO_KIT_TOOL_SKIP_DEPS=1). Not an MCP installation. serve needs: ${py} -m pip install 'mcp==1.30.0'"
    return 0
  fi
  echo "  mcp       missing mcp.server.fastmcp.FastMCP in ${py}"
  if [[ ! -t 0 ]] && [[ "${REPO_KIT_TOOL_ASSUME_YES:-0}" != "1" ]]; then
    warn "non-interactive: left the shared app CLI-only; re-run to install mcp==1.30.0"
    return 0
  fi
  if ! prompt_yn_interactive "Install mcp==1.30.0 into the existing virtualenv so py-indexer serve works (may use network)?"; then
    warn "MCP dependencies left missing; CLI indexing still works, serve does not"
    return 0
  fi
  "${py}" -m pip install 'mcp==1.30.0'
  if _py_indexer_mcp_import_ok "${py}"; then
    echo "  mcp       ready (mcp.server.fastmcp.FastMCP)"
  else
    warn "mcp install finished but mcp.server.fastmcp.FastMCP still does not import; serve is not operational"
  fi
}

_ensure_py_indexer_link() {
  local venv_exe link
  venv_exe="$(_py_indexer_venv_dir)/bin/py-indexer"
  link="$(_py_indexer_exe_path)"
  [[ -x "${venv_exe}" ]] || return 0
  mkdir -p "$(dirname "${link}")"
  if [[ -e "${link}" && ! -L "${link}" ]]; then
    warn "not replacing ${link} (existing file is not the managed symlink)"
    return 0
  fi
  ln -sfn "${venv_exe}" "${link}"
}

# Probe or rewrite the managed PATH block. Does not source the profile.
# Prints one of: absent, match, differ, ambiguous, added, updated, refused.
_py_indexer_path_edit() {
  local mode="$1"
  local profile="$2"
  local bin_dir="$3"
  python3 - "${mode}" "${profile}" "${bin_dir}" <<'PY'
import os, subprocess, sys

mode, profile, bin_dir = sys.argv[1], sys.argv[2], sys.argv[3]
start = "# repo-kit py-indexer PATH"
end = "# repo-kit py-indexer PATH end"
window = 30

def block_for(bin_dir: str) -> list[str]:
    quoted = "'" + bin_dir.replace("'", "'\\''") + "'"
    return [
        start,
        "# bin: " + bin_dir,
        f"_repo_kit_py_indexer_bin={quoted}",
        'case ":${PATH}:" in',
        '*":${_repo_kit_py_indexer_bin}:"*) ;;',
        '*) export PATH="${_repo_kit_py_indexer_bin}:${PATH}" ;;',
        "esac",
        end,
    ]

def classify(lines: list[str]) -> tuple[str, int | None, int | None]:
    """Return (kind, start_at, end_at). kind is absent, block, oneline, or ambiguous."""
    starts = [n for n, line in enumerate(lines) if line.strip() == start]
    if not starts:
        return ("absent", None, None)
    if len(starts) != 1:
        return ("ambiguous", None, None)
    i = starts[0]
    end_at = [
        i + 1 + k
        for k, line in enumerate(lines[i + 1 : i + 1 + window])
        if line.strip() == end
    ]
    if len(end_at) > 1:
        return ("ambiguous", None, None)
    if len(end_at) == 1:
        return ("block", i, end_at[0])
    j = i + 1
    while j < len(lines) and j <= i + 8:
        stripped = lines[j].strip()
        if stripped == "" or stripped.startswith("#"):
            j += 1
            continue
        if stripped.startswith("case ") and "esac" in stripped and stripped.endswith("esac"):
            return ("oneline", i, j)
        return ("ambiguous", None, None)
    return ("ambiguous", None, None)

def recorded_bin(lines: list[str], start_at: int, end_at: int) -> str | None:
    for line in lines[start_at : end_at + 1]:
        if line.startswith("# bin:"):
            return line[len("# bin:") :].lstrip()
    return None

def state_of(kind: str, lines: list[str], start_at: int | None, end_at: int | None) -> str:
    if kind == "absent":
        return "absent"
    if kind == "ambiguous" or start_at is None or end_at is None:
        return "ambiguous"
    if kind == "block":
        recorded = recorded_bin(lines, start_at, end_at)
        return "match" if recorded == bin_dir else "differ"
    region = "\n".join(lines[start_at : end_at + 1])
    return "match" if bin_dir in region else "differ"

def explain_ambiguous() -> None:
    print(
        "PATH block in "
        + profile
        + " is missing an end marker or is not the one-line case form; left untouched."
    )
    print("  repair: edit " + profile + " yourself. Remove the old block from")
    print("          '" + start + "' through its case/esac, then re-run.")
    print("          Or append this block once those lines are gone:")
    print("  activate:  export PATH=\"" + bin_dir + ":$PATH\"")

if "\n" in bin_dir or "\r" in bin_dir:
    print("refused")
    raise SystemExit("bin directory contains a newline")

text = ""
if os.path.isfile(profile):
    text = open(profile, encoding="utf-8", errors="replace").read()
lines = text.splitlines()
kind, start_at, end_at = classify(lines)
state = state_of(kind, lines, start_at, end_at)

if mode == "probe":
    print(state)
    raise SystemExit(0)

if state == "ambiguous":
    explain_ambiguous()
    print("ambiguous")
    raise SystemExit(0)
if state == "match":
    print("match")
    raise SystemExit(0)

block = block_for(bin_dir)
if state == "absent":
    prefix = text
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    if prefix and not prefix.endswith("\n\n"):
        prefix += "\n"
    out = prefix + "\n".join(block) + "\n"
    label = "added"
else:
    assert start_at is not None and end_at is not None
    updated = lines[:start_at] + block + lines[end_at + 1 :]
    out = "\n".join(updated)
    if text.endswith("\n") or out:
        out += "\n"
    label = "updated"

parent = os.path.dirname(profile) or "."
os.makedirs(parent, exist_ok=True)
tmp = profile + ".repo-kit-tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    fh.write(out)
check = subprocess.run(["bash", "-n", tmp], capture_output=True, text=True)
if check.returncode != 0:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    sys.stderr.write(check.stderr)
    print(
        "bash -n failed for the rewritten "
        + profile
        + "; left the existing file untouched."
    )
    print("refused")
    raise SystemExit(2)
os.replace(tmp, profile)
print(label)
PY
}

_ensure_py_indexer_path() {
  local bin_dir="$1"
  local profile="${HOME}/.bashrc"
  local state prompt result rc

  if python3 -c 'import os,sys; b=sys.argv[1]; raise SystemExit(0 if b in os.environ.get("PATH","").split(":") else 1)' "${bin_dir}"; then
    echo "  PATH ok   ${bin_dir} already on PATH"
  else
    echo "  note      ${bin_dir} is not on PATH in this process"
    echo "            GUI/Cursor MCP uses the absolute executable and does not need PATH."
  fi

  state="$(_py_indexer_path_edit probe "${profile}" "${bin_dir}")"
  case "${state}" in
    match)
      echo "  reuse     PATH marker already matches ${bin_dir} in ${profile}"
      return 0
      ;;
    ambiguous)
      warn "PATH block in ${profile} was left untouched"
      _py_indexer_path_edit apply "${profile}" "${bin_dir}" | sed '/^ambiguous$/d'
      return 0
      ;;
  esac

  if [[ "${state}" == "differ" ]]; then
    prompt="Update the repo-kit py-indexer PATH block in ${profile} to ${bin_dir}?"
  else
    prompt="Add ${bin_dir} to PATH in ${profile} (idempotent marker)?"
  fi
  if [[ ! -t 0 ]] && [[ "${REPO_KIT_TOOL_ASSUME_YES:-0}" != "1" ]]; then
    warn "non-interactive: not modifying shell profile; add ${bin_dir} to PATH yourself"
    echo "  activate:  export PATH=\"${bin_dir}:\$PATH\""
    return 0
  fi
  if ! prompt_yn_interactive "${prompt}"; then
    warn "skipped PATH profile update"
    echo "  activate:  export PATH=\"${bin_dir}:\$PATH\""
    return 0
  fi

  set +e
  result="$(_py_indexer_path_edit apply "${profile}" "${bin_dir}" 2>&1)"
  rc=$?
  set -e
  if [[ "${rc}" -ne 0 || "${result}" == *refused* ]]; then
    warn "did not modify ${profile}"
    printf '%s\n' "${result}"
    return 0
  fi
  if [[ "${state}" == "differ" ]]; then
    echo "  updated   PATH block in ${profile}"
  else
    echo "  added     PATH block to ${profile}"
  fi
  echo "  activate now in this terminal:"
  echo "    export PATH=\"${bin_dir}:\$PATH\""
  echo "  or: source ${profile}"
  echo "  (this script does not source the profile)"
}

_install_py_indexer_shared_app() {
  local src="${TOOLS_DIR}/py-indexer"
  local data venv bin_dir exe py
  local skip_deps="${REPO_KIT_TOOL_SKIP_DEPS:-0}"

  data="$(_py_indexer_data_home)"
  venv="$(_py_indexer_venv_dir)"
  bin_dir="$(_py_indexer_bin_dir)"
  exe="$(_py_indexer_exe_path)"

  [[ -f "${src}/pyproject.toml" ]] || die "py-indexer package missing at ${src}/pyproject.toml"
  cmd_exists python3 || die "python3 is required for py-indexer"

  if ! python3 -c 'import venv, ensurepip' >/dev/null 2>&1; then
    die "python3 venv support missing (install python3-venv / ensurepip), then re-run"
  fi

  if ! python3 - <<'PY' >/dev/null
import sqlite3
c = sqlite3.connect(":memory:")
c.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
PY
  then
    die "SQLite FTS5 is unavailable in this python3 build"
  fi

  mkdir -p "${data}" "${bin_dir}"

  if [[ ! -x "${venv}/bin/python" ]]; then
    echo "  creating user venv at ${venv} ..."
    python3 -m venv "${venv}"
  else
    echo "  reuse     user venv ${venv}"
  fi
  py="${venv}/bin/python"
  [[ -x "${py}" ]] || die "venv python missing at ${py}"

  echo "  install   shared py-indexer from ${src} ..."
  if [[ "${skip_deps}" == "1" ]]; then
    # Fully offline: copy package into site-packages + write console script (no PyPI).
    "${py}" - "${src}" "${venv}" <<'PY'
import pathlib, shutil, sys, subprocess
src, venv = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
pkg_src = src / "src" / "py_indexer"
assert pkg_src.is_dir(), pkg_src
site = subprocess.check_output(
    [str(venv / "bin" / "python"), "-c", "import site; print(site.getsitepackages()[0])"],
    text=True,
).strip()
dest = pathlib.Path(site) / "py_indexer"
if dest.exists():
    shutil.rmtree(dest)
shutil.copytree(pkg_src, dest)
PY
    _py_indexer_write_launcher "${py}" "${venv}/bin/py-indexer"
  else
    if ! prompt_yn_interactive "Install/upgrade shared py-indexer into ${venv} (may use network for mcp==1.30.0)?"; then
      die "refused shared py-indexer install; aborting (MCP would be unusable)"
    fi
    "${py}" -m pip install --upgrade "${src}"
    _py_indexer_write_launcher "${py}" "${venv}/bin/py-indexer"
  fi

  [[ -x "${venv}/bin/py-indexer" ]] || die "console script missing after install: ${venv}/bin/py-indexer"

  ln -sfn "${venv}/bin/py-indexer" "${exe}"
  [[ -x "${exe}" ]] || die "failed to link ${exe}"

  local json
  json="$(_py_indexer_probe "${exe}" || true)"
  [[ -n "${json}" ]] || die "installed py-indexer failed --app-id probe"
  _py_indexer_compat_ok "${json}" "${_PY_INDEXER_REQUIRED_COMPAT}" \
    || die "installed py-indexer failed compatibility check: ${json}"

  echo "  installed ${exe}"
  # Caller captures via global. PATH and MCP repair run in _ensure_py_indexer_shared.
  PY_INDEXER_EXE="${exe}"
}

_ensure_py_indexer_shared() {
  local verified existing json
  load_tool_manifest "py-indexer"
  if [[ -n "${TOOL_PY_INDEXER_COMPAT:-}" ]]; then
    _PY_INDEXER_REQUIRED_COMPAT="${TOOL_PY_INDEXER_COMPAT}"
  fi

  PY_INDEXER_EXE=""
  if verified="$(_py_indexer_find_verified)"; then
    echo "  reuse     shared py-indexer: ${verified}"
    PY_INDEXER_EXE="${verified}"
    _ensure_py_indexer_link
    _ensure_py_indexer_path "$(_py_indexer_bin_dir)"
    _offer_py_indexer_mcp_repair "${PY_INDEXER_EXE}"
    _offer_py_indexer_structural "${PY_INDEXER_EXE}"
    return 0
  fi

  if existing="$(_py_indexer_find_any_ours)"; then
    json="$(_py_indexer_probe "${existing}" || true)"
    echo "  found     incompatible py-indexer at ${existing}"
    echo "            ${json}"
    if [[ ! -t 0 ]] && [[ "${REPO_KIT_TOOL_ASSUME_YES:-0}" != "1" ]]; then
      die "incompatible py-indexer; re-run interactively or set REPO_KIT_TOOL_ASSUME_YES=1 to upgrade"
    fi
    if ! prompt_yn_interactive "Upgrade shared py-indexer to compat ${_PY_INDEXER_REQUIRED_COMPAT}?"; then
      die "refused to upgrade incompatible py-indexer"
    fi
  else
    echo "  missing   shared py-indexer application"
    if [[ "${REPO_KIT_TOOL_SKIP_DEPS:-0}" == "1" ]]; then
      if [[ ! -t 0 ]] && [[ "${REPO_KIT_TOOL_ASSUME_YES:-0}" != "1" ]]; then
        die "shared py-indexer not installed; non-interactive run refused install without REPO_KIT_TOOL_ASSUME_YES=1"
      fi
      if [[ "${REPO_KIT_TOOL_ASSUME_YES:-0}" != "1" ]]; then
        if ! prompt_yn_interactive "Install shared py-indexer from kit (offline --no-deps; MCP optional)?"; then
          die "refused shared py-indexer install"
        fi
      fi
    elif [[ ! -t 0 ]] && [[ "${REPO_KIT_TOOL_ASSUME_YES:-0}" != "1" ]]; then
      die "shared py-indexer not installed; non-interactive refuse without REPO_KIT_TOOL_ASSUME_YES=1"
    fi
  fi

  _install_py_indexer_shared_app
  [[ -n "${PY_INDEXER_EXE}" && -x "${PY_INDEXER_EXE}" ]] \
    || die "shared py-indexer install did not set PY_INDEXER_EXE"
  _ensure_py_indexer_link
  _ensure_py_indexer_path "$(_py_indexer_bin_dir)"
  _offer_py_indexer_mcp_repair "${PY_INDEXER_EXE}"
  _offer_py_indexer_structural "${PY_INDEXER_EXE}"
}

# Seed repos.json from kit example when missing; never overwrite an existing file.
_seed_py_indexer_repos_json() {
  local tool_root="$1"
  local example="${TOOLS_DIR}/py-indexer/project/repos.example.json"
  local dest="${tool_root}/repos.json"
  local target_name

  [[ -f "${example}" ]] || die "py-indexer missing project/repos.example.json"
  mkdir -p "${tool_root}"
  if [[ -e "${dest}" || -L "${dest}" ]]; then
    echo "  preserve   ${dest#"${TARGET_DIR}"/}"
    PRESERVED_COUNT=$((PRESERVED_COUNT + 1))
    return 0
  fi

  target_name="$(basename "${TARGET_DIR}" | tr -c 'A-Za-z0-9._-' '_' | sed 's/^_//;s/_$//')"
  [[ -n "${target_name}" ]] || target_name="active"
  case "${target_name}" in
    [A-Za-z0-9]*) ;;
    *) target_name="r_${target_name}" ;;
  esac
  # shellcheck disable=SC2016
  sed \
    -e "s|@TARGET_REPO_ID@|${target_name}|g" \
    "${example}" >"${dest}"
  ADDED_COUNT=$((ADDED_COUNT + 1))
  echo "  add        ${dest#"${TARGET_DIR}"/}"
}

# Idempotently ensure repos.json is gitignored.
_ensure_py_indexer_gitignore() {
  local gitignore="${TARGET_DIR}/.gitignore"
  local marker="# repo-kit py-indexer"
  local entries=(
    ".repo-kit/tools/py-indexer/repos.json"
  )
  local entry

  if [[ ! -f "${gitignore}" ]]; then
    {
      echo "${marker}"
      for entry in "${entries[@]}"; do
        echo "${entry}"
      done
    } >"${gitignore}"
    echo "  added     .gitignore py-indexer block"
    return 0
  fi

  if grep -Fqx "${marker}" "${gitignore}" 2>/dev/null; then
    for entry in "${entries[@]}"; do
      if ! grep -Fqx "${entry}" "${gitignore}" 2>/dev/null; then
        printf '%s\n' "${entry}" >>"${gitignore}"
        echo "  added     .gitignore: ${entry}"
      fi
    done
    return 0
  fi

  {
    echo ""
    echo "${marker}"
    for entry in "${entries[@]}"; do
      echo "${entry}"
    done
  } >>"${gitignore}"
  echo "  added     .gitignore py-indexer block"
}

_offer_py_indexer_structural() {
  local exe="$1"
  local py
  if ! py="$(_py_indexer_venv_python "${exe}")"; then
    warn "structural parsers were not checked; virtualenv python was not found"
    return 0
  fi
  if "${py}" - <<'PY' >/dev/null 2>&1
import importlib.metadata as metadata
from tree_sitter import LANGUAGE_VERSION, MIN_COMPATIBLE_LANGUAGE_VERSION, Language
import tree_sitter_cpp, tree_sitter_javascript, tree_sitter_typescript, tree_sitter_rust
assert metadata.version("tree-sitter") == "0.26.1"
assert int(LANGUAGE_VERSION) == 15 and int(MIN_COMPATIBLE_LANGUAGE_VERSION) == 13
pairs = [
    (tree_sitter_cpp.language, "tree-sitter-cpp", "0.23.4", 14),
    (tree_sitter_javascript.language, "tree-sitter-javascript", "0.25.0", 15),
    (tree_sitter_typescript.language_typescript, "tree-sitter-typescript", "0.23.2", 14),
    (tree_sitter_typescript.language_tsx, "tree-sitter-typescript", "0.23.2", 14),
    (tree_sitter_rust.language, "tree-sitter-rust", "0.24.2", 15),
]
for fn, dist, ver, abi in pairs:
    assert metadata.version(dist) == ver
    got = int(Language(fn()).abi_version)
    assert got == abi
    assert MIN_COMPATIBLE_LANGUAGE_VERSION <= got <= LANGUAGE_VERSION
PY
  then
    echo "  structural parsers ready (tree-sitter==0.26.1, ABI 13-15)"
    return 0
  fi
  if [[ "${REPO_KIT_TOOL_SKIP_DEPS:-0}" == "1" ]]; then
    warn "structural parsers not installed (REPO_KIT_TOOL_SKIP_DEPS=1). Lexical indexing still works."
    warn "offline: ${py} -m pip install --no-index --find-links=/path/to/wheels 'tree-sitter==0.26.1' 'tree-sitter-cpp==0.23.4' 'tree-sitter-javascript==0.25.0' 'tree-sitter-typescript==0.23.2' 'tree-sitter-rust==0.24.2'"
    return 0
  fi
  echo "  structural parsers missing from ${py}"
  if [[ ! -t 0 ]] && [[ "${REPO_KIT_TOOL_ASSUME_YES:-0}" != "1" ]]; then
    warn "non-interactive: left structural parsers uninstalled; lexical indexing still works"
    return 0
  fi
  if ! prompt_yn_interactive "Install pinned tree-sitter parsers into the existing virtualenv (may use network)?"; then
    warn "structural parsers left missing; lexical indexing still works"
    return 0
  fi
  "${py}" -m pip install \
    'tree-sitter==0.26.1' \
    'tree-sitter-cpp==0.23.4' \
    'tree-sitter-javascript==0.25.0' \
    'tree-sitter-typescript==0.23.2' \
    'tree-sitter-rust==0.24.2'
}

_copy_py_indexer_cursor_rule() {
  local src="${TOOLS_DIR}/py-indexer/files/.cursor/rules/py-indexer.mdc"
  local dest="${TARGET_DIR}/.cursor/rules/py-indexer.mdc"
  local existed=0
  [[ -f "${src}" ]] || die "py-indexer missing cursor rule at ${src}"
  if [[ -e "${dest}" || -L "${dest}" ]]; then
    existed=1
  fi
  mkdir -p "$(dirname "${dest}")"
  _copy_file "${src}" "${dest}"
  if [[ "${existed}" -eq 1 && "${FORCE_COPY}" -ne 1 ]]; then
    if cmp -s "${src}" "${dest}"; then
      echo "  notice    .cursor/rules/py-indexer.mdc already matches the shipped rule; left in place."
    else
      echo "  notice    existing .cursor/rules/py-indexer.mdc was left unchanged."
      echo "            Context and awareness guidance from this kit version was not applied."
      echo "            To update only that rule, copy:"
      echo "              ${src}"
      echo "              -> ${dest}"
      echo "            Re-running with --force replaces the rule and other non-preserved kit files."
      echo "            repos.json is never overwritten."
    fi
  fi
}

_py_indexer_mcp_ready() {
  local exe="$1"
  local json
  json="$(_py_indexer_probe "${exe}" || true)"
  [[ -n "${json}" ]] || return 1
  python3 -c 'import json,sys; d=json.loads(sys.argv[1]); raise SystemExit(0 if d.get("mcp_ready") is True else 1)' "${json}"
}

# Leave an existing serve registration alone until the shared app can import FastMCP.
# A CLI-only executable is not written into .cursor/mcp.json.
_hold_py_indexer_mcp() {
  local exe="$1"
  local mcp_path="${TARGET_DIR}/.cursor/mcp.json"
  local fragment_path="${TARGET_DIR}/.repo-kit/tools/py-indexer/mcp.fragment.json"
  local config_path="${TARGET_DIR}/.repo-kit/tools/py-indexer/repos.json"
  local tool_root="${TARGET_DIR}/.repo-kit/tools/py-indexer"
  local desired hold_out status

  mkdir -p "$(dirname "${fragment_path}")"
  desired="$(python3 - "${exe}" "${config_path}" <<'PY'
import json, sys
command, config = sys.argv[1], sys.argv[2]
print(json.dumps({
    "type": "stdio",
    "command": command,
    "args": ["--config", config, "serve"],
}, indent=2, sort_keys=True))
PY
)"
  python3 - "${fragment_path}" "${desired}" <<'PY'
import json, os, sys
path, desired = sys.argv[1], json.loads(sys.argv[2])
doc = {"mcpServers": {"py-indexer": desired}}
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, indent=2)
    fh.write("\n")
os.replace(tmp, path)
PY
  echo "  wrote     ${fragment_path#"${TARGET_DIR}"/} (not active until the shared app is MCP-ready)"

  hold_out="$(python3 - "${mcp_path}" "${exe}" "${tool_root}" "${TARGET_DIR}" <<'PY'
import json, os, sys
from pathlib import Path

mcp_path, exe, tool_root, target = sys.argv[1:]
tool = Path(tool_root)
mcp = Path(mcp_path)
legacy = {
    "type": "stdio",
    "command": "${workspaceFolder}/.repo-kit/tools/py-indexer/.venv/bin/python",
    "args": [
        "${workspaceFolder}/.repo-kit/tools/py-indexer/bin/py-indexer",
        "serve",
    ],
}
abs_legacy = {
    "type": "stdio",
    "command": str(tool / ".venv" / "bin" / "python"),
    "args": [str(tool / "bin" / "py-indexer"), "serve"],
}
legacy_keys = {"type", "command", "args"}
runtime_ok = (tool / ".venv" / "bin" / "python").exists() and (tool / "bin" / "py-indexer").exists()

def emit(status: str, *lines: str) -> None:
    for line in lines:
        print(line)
    print("STATUS=" + status)
    raise SystemExit(0)

def is_exact_legacy(existing) -> bool:
    if not isinstance(existing, dict) or set(existing.keys()) != legacy_keys:
        return False
    if existing.get("type") != "stdio":
        return False
    cmd = existing.get("command")
    args = existing.get("args")
    if not isinstance(cmd, str) or not isinstance(args, list) or len(args) != 2:
        return False
    if not all(isinstance(item, str) for item in args) or args[1] != "serve":
        return False
    return (cmd, args[0]) in {
        (legacy["command"], legacy["args"][0]),
        (abs_legacy["command"], abs_legacy["args"][0]),
    }

expected_config = tool / "repos.json"

def identifies_project_config(arg: str) -> bool:
    candidate = Path(arg)
    if not candidate.is_absolute():
        candidate = Path(target) / candidate
    try:
        return candidate.resolve() == expected_config.resolve()
    except OSError:
        return False

def is_stock_shared_shape(existing) -> bool:
    # Stock shape is only type/command/args. Extra fields or arguments stay.
    if not isinstance(existing, dict) or set(existing.keys()) != legacy_keys:
        return False
    if existing.get("type") != "stdio":
        return False
    cmd = existing.get("command")
    args = existing.get("args")
    if not isinstance(cmd, str) or not isinstance(args, list) or len(args) != 3:
        return False
    if not all(isinstance(item, str) for item in args):
        return False
    if args[0] != "--config" or args[2] != "serve":
        return False
    try:
        return os.path.realpath(cmd) == os.path.realpath(exe)
    except OSError:
        return cmd == exe

def is_exact_shared(existing) -> bool:
    # The config argument must identify this project's repos.json.
    if not is_stock_shared_shape(existing):
        return False
    return identifies_project_config(existing["args"][1])

if not mcp.is_file():
    emit(
        "CLI_ONLY",
        "  mcp       shared CLI is available at " + exe + "; MCP was not registered",
        "            because the shared app cannot import mcp.server.fastmcp.FastMCP",
    )

try:
    raw = mcp.read_text(encoding="utf-8")
    doc = json.loads(raw) if raw.strip() else {}
except Exception as exc:  # noqa: BLE001
    emit(
        "UNPARSEABLE:" + str(exc),
        "  keep      could not parse " + str(mcp) + "; left untouched",
    )

if not isinstance(doc, dict):
    emit("UNPARSEABLE:top-level JSON must be an object", "  keep      mcp.json is not an object; left untouched")
servers = doc.get("mcpServers")
if servers is None:
    emit(
        "CLI_ONLY",
        "  mcp       shared CLI is available at " + exe + "; MCP was not registered",
        "            because the shared app cannot import mcp.server.fastmcp.FastMCP",
    )
if not isinstance(servers, dict):
    emit("UNPARSEABLE:mcpServers must be an object", "  keep      mcpServers is not an object; left untouched")

existing = servers.get("py-indexer")
if existing is None:
    emit(
        "CLI_ONLY",
        "  mcp       shared CLI is available at " + exe + "; MCP was not registered",
        "            because the shared app cannot import mcp.server.fastmcp.FastMCP",
    )
if is_exact_legacy(existing):
    emit(
        "LEGACY_ACTIVE",
        "  mcp       shared CLI is available at " + exe + "; legacy MCP remains active",
    )
if is_exact_shared(existing):
    if runtime_ok:
        servers["py-indexer"] = legacy
        tmp = str(mcp) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, mcp)
        emit(
            "RESTORED_LEGACY",
            "  mcp       restored the legacy MCP registration; the shared executable is not MCP-ready",
            "  mcp       shared CLI is available at " + exe + "; legacy MCP remains active",
        )
    emit(
        "CLI_ONLY_BROKEN",
        "  mcp       registration points at a CLI-only executable, so serve will not work",
        "            the previous project runtime is gone, so the legacy registration cannot be restored",
        "            install mcp==1.30.0 into the shared virtualenv, then re-run",
    )
if is_stock_shared_shape(existing):
    emit(
        "DIVERGENT",
        "  keep      py-indexer MCP entry uses a different config than .repo-kit/tools/py-indexer/repos.json; left untouched",
        "            reconcile it manually with mcp.fragment.json after the shared app is MCP-ready",
    )
emit(
    "DIVERGENT",
    "  keep      existing py-indexer MCP entry differs; left untouched",
    "            reconcile manually with the fragment after the shared app is MCP-ready",
)
PY
)"
  status="$(printf '%s\n' "${hold_out}" | sed -n 's/^STATUS=//p' | head -n 1)"
  printf '%s\n' "${hold_out}" | sed '/^STATUS=/d'
  PY_INDEXER_MCP_STATUS="${status}"
}

# Merge only the py-indexer MCP server entry into .cursor/mcp.json.
_merge_py_indexer_mcp_json() {
  local exe="$1"
  local mcp_path="${TARGET_DIR}/.cursor/mcp.json"
  local fragment_path="${TARGET_DIR}/.repo-kit/tools/py-indexer/mcp.fragment.json"
  local config_path="${TARGET_DIR}/.repo-kit/tools/py-indexer/repos.json"
  local desired rc merge_out

  PY_INDEXER_MCP_STATUS=""
  [[ -x "${exe}" ]] || die "py-indexer executable not usable: ${exe}"
  if ! _py_indexer_mcp_ready "${exe}"; then
    _hold_py_indexer_mcp "${exe}"
    return 0
  fi
  mkdir -p "$(dirname "${mcp_path}")" "$(dirname "${fragment_path}")"

  desired="$(python3 - "${exe}" "${config_path}" <<'PY'
import json, sys
command, config = sys.argv[1], sys.argv[2]
print(json.dumps({
    "type": "stdio",
    "command": command,
    "args": ["--config", config, "serve"],
}, indent=2, sort_keys=True))
PY
)"

  python3 - "${fragment_path}" "${desired}" <<'PY'
import json, os, sys
path, desired = sys.argv[1], json.loads(sys.argv[2])
doc = {"mcpServers": {"py-indexer": desired}}
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, indent=2)
    fh.write("\n")
os.replace(tmp, path)
PY
  echo "  wrote     ${fragment_path#"${TARGET_DIR}"/}"

  if [[ ! -f "${mcp_path}" ]]; then
    python3 - "${mcp_path}" "${desired}" <<'PY'
import json, os, sys
path, desired = sys.argv[1], json.loads(sys.argv[2])
doc = {"mcpServers": {"py-indexer": desired}}
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, indent=2)
    fh.write("\n")
os.replace(tmp, path)
PY
    echo "  add        .cursor/mcp.json (py-indexer)"
    PY_INDEXER_MCP_STATUS="MERGED"
    return 0
  fi

  set +e
  merge_out="$(python3 - "${mcp_path}" "${desired}" "${TARGET_DIR}" <<'PY'
import json, os, sys

path, desired, target = sys.argv[1], json.loads(sys.argv[2]), sys.argv[3]
target = target.rstrip("/")
tool = target + "/.repo-kit/tools/py-indexer"
legacy_keys = {"type", "command", "args"}
legacy_cmds = {
    "${workspaceFolder}/.repo-kit/tools/py-indexer/.venv/bin/python",
    tool + "/.venv/bin/python",
}
legacy_scripts = {
    "${workspaceFolder}/.repo-kit/tools/py-indexer/bin/py-indexer",
    tool + "/bin/py-indexer",
}

def is_exact_legacy(existing):
    """Repo-kit's old generated entry for this target, with no extra fields."""
    if not isinstance(existing, dict) or set(existing.keys()) != legacy_keys:
        return False
    if existing.get("type") != "stdio":
        return False
    cmd = existing.get("command")
    args = existing.get("args")
    if not isinstance(cmd, str) or cmd not in legacy_cmds:
        return False
    if not isinstance(args, list) or len(args) != 2:
        return False
    if not all(isinstance(item, str) for item in args):
        return False
    return args[0] in legacy_scripts and args[1] == "serve"

try:
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()
    doc = json.loads(raw) if raw.strip() else {}
except Exception as exc:  # noqa: BLE001
    print(f"UNPARSEABLE:{exc}")
    sys.exit(2)

if not isinstance(doc, dict):
    print("UNPARSEABLE:top-level JSON must be an object")
    sys.exit(2)

servers = doc.get("mcpServers")
if servers is None:
    servers = {}
    doc["mcpServers"] = servers
if not isinstance(servers, dict):
    print("UNPARSEABLE:mcpServers must be an object")
    sys.exit(2)

existing = servers.get("py-indexer")
if existing is not None:
    if json.loads(json.dumps(existing, sort_keys=True)) == json.loads(json.dumps(desired, sort_keys=True)):
        print("UNCHANGED")
        sys.exit(0)
    if is_exact_legacy(existing):
        servers["py-indexer"] = desired
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
        print("MIGRATED_LEGACY")
        sys.exit(0)
    print("DIVERGENT")
    sys.exit(3)

servers["py-indexer"] = desired
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, indent=2)
    fh.write("\n")
os.replace(tmp, path)
print("MERGED")
PY
)"
  rc=$?
  set -e
  PY_INDEXER_MCP_STATUS="${merge_out%%$'\n'*}"

  case "${rc}" in
    0) ;;
    2)
      warn "could not parse ${mcp_path}; left untouched"
      echo "  use fragment: ${fragment_path#"${TARGET_DIR}"/}"
      echo "  merge the py-indexer entry manually, then validate JSON"
      ;;
    3)
      warn "existing .cursor/mcp.json py-indexer entry differs; left untouched (even with --force)"
      echo "  reconcile manually with: ${fragment_path#"${TARGET_DIR}"/}"
      ;;
    *)
      die "mcp.json merge failed (exit ${rc})"
      ;;
  esac
}

# Yes only when the user types yes. Install consent and REPO_KIT_TOOL_ASSUME_YES do not count.
_prompt_yn_explicit_no() {
  local prompt="$1"
  local reply
  if [[ ! -t 0 ]]; then
    echo "  skip      ${prompt}"
    echo "            Re-run this command in a terminal and answer y to remove them."
    return 1
  fi
  if ! read -r -p "${prompt} [y/N] " reply; then
    echo "  skip      no answer"
    return 1
  fi
  case "${reply}" in
    y|Y|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

# List positively identified legacy runtime files. Does not delete.
_py_indexer_legacy_plan() {
  local tool_root="$1"
  python3 - "${tool_root}" <<'PY'
import hashlib, json, os, re, sys
from pathlib import Path

tool_root = Path(sys.argv[1])
req = (
    b"# Optional MCP dependency. Indexing and CLI search work without it.\n"
    b"# Pin matched to FastMCP stdio API used by py_indexer.mcp_server.\n"
    b"mcp==1.30.0\n"
)
mcp_example = (
    b"{\n"
    b'  "mcpServers": {\n'
    b'    "py-indexer": {\n'
    b'      "type": "stdio",\n'
    b'      "command": "${workspaceFolder}/.repo-kit/tools/py-indexer/.venv/bin/python",\n'
    b'      "args": [\n'
    b'        "${workspaceFolder}/.repo-kit/tools/py-indexer/bin/py-indexer",\n'
    b'        "serve"\n'
    b"      ]\n"
    b"    }\n"
    b"  }\n"
    b"}\n"
)
# sha256 of the project-local files shipped before the shared install
# (063b9df^:tools/py-indexer/files/.repo-kit/tools/py-indexer/).
launcher_sha = "224d49224db8b64ba51c25a876a6d563ce44f0e5e5d43b0b9c9e1fa217fdba4d"
pkg_sha = {
    "__init__.py": "95a9606016c6f9bf4db959d9c894ccf8da015ae3d08962727b4ddd4d0c72ac13",
    "__main__.py": "b6698a5af5d86627c750eace445f61f14918b40c70880bb0e3cc32adca09c7f2",
    "budgets.py": "ea666f188cc8dccf15d581f54060d2750724162d050b7ffdd11e7435589a80f7",
    "chunk.py": "1f244cba8d66a57dc6c8b1509c12ddbc4c93168eba8b74ba5e509e65f37ddfb5",
    "cli.py": "b05b54817a443a0ed46b28151164be4ccb72125b1a87f1a84d6fe486685b04e4",
    "config.py": "a69be8cb22678cbad31fe57dd158327f16bc29724cdbb63456b38608f63a0e4c",
    "exclude.py": "1cbceb676767afdfc12d26d49fe1d911237eb0a7e4b7affb4ed3152ea9b66837",
    "gitinfo.py": "e09455f9f1a3b2e20d56ec230cdb1bd7b7ee20fe3f838d162ce502be68fc74f3",
    "index_cmd.py": "49aa3d40ad95541cb15a5b1a36d47338f935790f6147cfc4a9f14e03361e77d3",
    "mcp_server.py": "7413b4aee1139e1576824b8b11d269d893b19f0ebb43e1153cf9c2fe84e95de8",
    "paths.py": "5fc3a37a8c6d944d86596b037be1f15cb0710c715060ff291e2633dd03d81e83",
    "read_cmd.py": "7ed24c5b6b5778e7ab758f1f9c3177a77de4b5ab97feb9b056b2a652e9b7ef91",
    "search_cmd.py": "450face3392ed4f212515bd9e203c0ad3e087499b55621e2ea10263cfa4d5320",
    "status_cmd.py": "d78eb453c6619db4f2f63810d3609206700d00f0cf5dfbcfff4be559a4046f3b",
    "store.py": "34c8bb1068351cfefa727f7ffe756453afc6b8c215d40432ec6d9d44965bb3f0",
}
safe_index = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.sqlite3(-wal|-shm)?$")
remove, keep = [], []

def plain_dir(path: Path) -> bool:
    return path.is_dir() and not path.is_symlink()

def add_remove(path: Path) -> None:
    remove.append(str(path))

def add_keep(path: Path, reason: str) -> None:
    keep.append({"path": str(path), "reason": reason})

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

bin_dir = tool_root / "bin"
if bin_dir.exists() or bin_dir.is_symlink():
    if not plain_dir(bin_dir):
        add_keep(bin_dir, "not a plain directory; left in place")
    else:
        children = list(bin_dir.iterdir())
        launcher = bin_dir / "py-indexer"
        if (
            len(children) == 1
            and children[0].name == "py-indexer"
            and launcher.is_file()
            and not launcher.is_symlink()
            and digest(launcher) == launcher_sha
        ):
            add_remove(bin_dir)
        elif any(child.name != "py-indexer" for child in children):
            add_keep(bin_dir, "contains files other than the legacy launcher; left in place")
        else:
            add_keep(
                bin_dir,
                "bin/py-indexer does not match the shipped legacy launcher; left in place. "
                "Remove that directory yourself after confirming you use the shared CLI.",
            )

pkg = tool_root / "py_indexer"
if pkg.exists() or pkg.is_symlink():
    if not plain_dir(pkg):
        add_keep(pkg, "not a plain directory; left in place")
    else:
        unknown = False
        modified = False
        saw_file = False
        for dirpath, dirnames, filenames in os.walk(pkg):
            rel_dir = Path(dirpath).relative_to(pkg)
            if rel_dir != Path("."):
                unknown = True
            if any(name != "__pycache__" for name in dirnames):
                unknown = True
            for name in filenames:
                saw_file = True
                if name not in pkg_sha:
                    unknown = True
                    continue
                file_path = Path(dirpath) / name
                if file_path.is_symlink() or not file_path.is_file() or digest(file_path) != pkg_sha[name]:
                    modified = True
        if unknown:
            add_keep(pkg, "contains files that are not the shipped legacy package; left in place")
        elif modified or not saw_file:
            add_keep(
                pkg,
                "a shipped legacy module was modified or could not be verified; left in place. "
                "Remove that directory yourself after confirming nothing else imports it.",
            )
        else:
            add_remove(pkg)

venv = tool_root / ".venv"
if venv.exists() or venv.is_symlink():
    add_keep(
        venv,
        "virtualenv ownership cannot be verified; left intact. "
        "After the shared MCP server works, remove it yourself: rm -rf " + str(venv),
    )

index = tool_root / "index"
if index.exists() or index.is_symlink():
    if not plain_dir(index):
        add_keep(index, "not a plain directory; left in place")
    else:
        bad = False
        for child in index.iterdir():
            if child.is_dir() or child.is_symlink() or not safe_index.fullmatch(child.name):
                bad = True
                break
        if bad:
            add_keep(index, "contains entries other than legacy <id>.sqlite3 databases; left in place")
        else:
            add_remove(index)

def maybe_exact_file(name: str, expected: bytes) -> None:
    path = tool_root / name
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or not path.is_file():
        add_keep(path, "not a regular file; left in place")
        return
    if path.read_bytes() == expected:
        add_remove(path)
    else:
        add_keep(path, "contents differ from the shipped legacy file; left in place")

maybe_exact_file("requirements.txt", req)
maybe_exact_file("mcp.example.json", mcp_example)
print(json.dumps({"remove": remove, "keep": keep}))
PY
}

_py_indexer_legacy_cleanup() {
  local target="$1"
  local tool_root="${target}/.repo-kit/tools/py-indexer"
  local cache_indexes plan exe kind path filtered

  if [[ -n "${XDG_CACHE_HOME:-}" ]]; then
    cache_indexes="${XDG_CACHE_HOME}/py-indexer/indexes"
  else
    cache_indexes="${HOME}/.cache/py-indexer/indexes"
  fi
  if [[ -d "${cache_indexes}" ]]; then
    local entry
    for entry in "${cache_indexes}"/*; do
      [[ -d "${entry}" ]] || continue
      echo "  keep      cache directory left in place (not a legacy project index): ${entry}"
    done
  fi

  [[ -d "${tool_root}" ]] || return 0
  plan="$(_py_indexer_legacy_plan "${tool_root}")"

  if ! exe="$(_py_indexer_find_verified)"; then
    python3 - "${plan}" <<'PY'
import json, sys
doc = json.loads(sys.argv[1])
if not doc["remove"] and not doc["keep"]:
    raise SystemExit(0)
print("  legacy    old py-indexer project-local install files:")
for item in doc["keep"]:
    print(f"  keep      {item['path']} ({item['reason']})")
for path in doc["remove"]:
    print(f"            {path}")
PY
    echo "  keep      no verified shared py-indexer; project-local runtime left in place"
    return 0
  fi

  # Decide the MCP registration before offering to delete anything it still runs.
  if [[ -z "${PY_INDEXER_MCP_STATUS:-}" ]]; then
    if [[ -f "${target}/.cursor/mcp.json" ]]; then
      _merge_py_indexer_mcp_json "${exe}"
    else
      PY_INDEXER_MCP_STATUS="ABSENT"
    fi
  fi

  case "${PY_INDEXER_MCP_STATUS}" in
    UNPARSEABLE*)
      echo "  keep      mcp.json is invalid; not deleting files it might reference"
      return 0
      ;;
  esac

  plan="$(python3 - "${plan}" "${PY_INDEXER_MCP_STATUS}" "${target}/.cursor/mcp.json" "${tool_root}" <<'PY'
import json, os, sys
from pathlib import Path

plan = json.loads(sys.argv[1])
status, mcp_path, tool_root = sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])
root = tool_root.resolve()
runtime = {root / "bin", root / "py_indexer", root / ".venv"}
hold = status in {"LEGACY_ACTIVE", "RESTORED_LEGACY", "CLI_ONLY_BROKEN"}
refs = []
if status == "DIVERGENT" and mcp_path.is_file():
    try:
        doc = json.loads(mcp_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        doc = {}
    entry = {}
    if isinstance(doc, dict):
        servers = doc.get("mcpServers")
        if isinstance(servers, dict) and isinstance(servers.get("py-indexer"), dict):
            entry = servers["py-indexer"]

    def walk(obj):
        if isinstance(obj, str):
            refs.append(obj)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)
        elif isinstance(obj, dict):
            for item in obj.values():
                walk(item)

    walk(entry)
    workspace = str(mcp_path.parent.parent)
    expanded = []
    for value in refs:
        value = value.replace("${workspaceFolder}", workspace)
        if value.startswith("/"):
            expanded.append(os.path.abspath(value))
    refs = expanded

def covers(removal: Path, ref: str) -> bool:
    try:
        return os.path.commonpath([os.path.abspath(removal), ref]) == os.path.abspath(removal)
    except ValueError:
        return False

kept = list(plan["keep"])
remove = []
for item in plan["remove"]:
    path = Path(item)
    if hold and (path.resolve() in runtime or any(path.resolve() == rt or rt in path.resolve().parents for rt in runtime)):
        kept.append({
            "path": item,
            "reason": "legacy MCP remains active, so this runtime stays. Shared CLI is available separately.",
        })
        continue
    if any(covers(path, ref) for ref in refs):
        kept.append({"path": item, "reason": "still referenced by .cursor/mcp.json; left in place"})
        continue
    remove.append(item)
print(json.dumps({"remove": remove, "keep": kept}))
PY
)"

  python3 - "${plan}" <<'PY'
import json, sys
doc = json.loads(sys.argv[1])
if not doc["remove"] and not doc["keep"]:
    raise SystemExit(0)
print("  legacy    old py-indexer project-local install files:")
for item in doc["keep"]:
    print(f"  keep      {item['path']} ({item['reason']})")
for path in doc["remove"]:
    print(f"            {path}")
print("            repos.json and excludes.txt are kept. Cache *.sqlite3 files are kept.")
print("            Directories that do not match the shipped baseline stay. Remove those yourself.")
PY

  if ! python3 -c 'import json,sys; d=json.loads(sys.argv[1]); raise SystemExit(0 if d["remove"] else 1)' "${plan}"; then
    return 0
  fi

  if ! _prompt_yn_explicit_no "Remove the old py-indexer paths listed above?"; then
    echo "  skip      old py-indexer files left in place"
    return 0
  fi

  while IFS= read -r path; do
    [[ -n "${path}" ]] || continue
    case "${path}" in
      "${tool_root}/"*)
        rm -rf -- "${path}"
        echo "  removed   ${path}"
        ;;
      *)
        echo "  keep      refused path outside the tool directory: ${path}"
        ;;
    esac
  done < <(python3 -c 'import json,sys; [print(p) for p in json.loads(sys.argv[1])["remove"]]' "${plan}")
}

install_py_indexer_tool() {
  local tool_root="${TARGET_DIR}/.repo-kit/tools/py-indexer"

  echo "tool: py-indexer"
  _ensure_py_indexer_shared
  [[ -n "${PY_INDEXER_EXE:-}" && -x "${PY_INDEXER_EXE}" ]] \
    || die "shared py-indexer executable missing after ensure"

  _seed_py_indexer_repos_json "${tool_root}"
  _ensure_py_indexer_gitignore
  _copy_py_indexer_cursor_rule
  _merge_py_indexer_mcp_json "${PY_INDEXER_EXE}"
  _py_indexer_legacy_cleanup "${TARGET_DIR}"

  echo "  py-indexer ready (shared app + project config)"
  echo "  next: edit ${tool_root#"${TARGET_DIR}"/}/repos.json, then: py-indexer index --all"
  echo "  (or: ${PY_INDEXER_EXE} --config ${tool_root}/repos.json index --all)"
}


install_tools() {
  local name
  [[ ${#SELECTED_TOOLS[@]} -gt 0 ]] || return 0

  resolve_tool_dependencies
  echo "tools: ${RESOLVED_TOOLS[*]}"

  for name in "${RESOLVED_TOOLS[@]}"; do
    case "${name}" in
      py-indexer) install_py_indexer_tool ;;
      *)
        # Generic copy-only tools (future): files/ only.
        copy_tool_files "${name}"
        ;;
    esac
  done
}

# Parse common CLI: [target] [--module ...] [--ext <name>] [--tool <name>] [--force] [--list] [--help]
# Sets: TARGET_DIR, SELECTED_MODULES, SELECTED_EXTENSIONS, SELECTED_TOOLS, FORCE_COPY, DO_LIST
parse_common_args() {
  TARGET_DIR=""
  SELECTED_MODULES=()
  SELECTED_EXTENSIONS=()
  SELECTED_TOOLS=()
  FORCE_COPY=0
  DO_LIST=0
  SHOW_HELP=0

  discover_modules
  discover_tools

  local arg name matched
  local known_tools_msg
  if [[ ${#DECLARED_TOOLS[@]} -gt 0 ]]; then
    known_tools_msg="${DECLARED_TOOLS[*]}"
  else
    known_tools_msg="(none)"
  fi

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
      --tool)
        [[ $# -gt 0 ]] || die "--tool requires a name (e.g. --tool py-indexer)"
        name="$1"
        shift
        [[ -n "${name}" ]] || die "--tool requires a name (e.g. --tool py-indexer)"
        tool_exists "${name}" || die "unknown tool '${name}' (known: ${known_tools_msg})"
        if ! array_contains "${name}" "${SELECTED_TOOLS[@]+"${SELECTED_TOOLS[@]}"}"; then
          SELECTED_TOOLS+=("${name}")
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
        [[ "${matched}" -eq 1 ]] || die "unknown flag '${arg}' (known modules: ${DECLARED_MODULES[*]}; extensions via --ext: ${KNOWN_EXTENSIONS[*]}; tools via --tool: ${known_tools_msg})"
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
