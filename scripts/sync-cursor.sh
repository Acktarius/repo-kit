#!/usr/bin/env bash
# Sync only .cursor/ assets from selected modules into a target project.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/sync-cursor.sh <target> --<module> [--<module> ...] [--ext <name>] [--tool <name>] [--force]
  ./scripts/sync-cursor.sh <target> --ext continue
  ./scripts/sync-cursor.sh <target> --ext openspec
  ./scripts/sync-cursor.sh <target> --ext forge
  ./scripts/sync-cursor.sh <target> --ext act
  ./scripts/sync-cursor.sh <target> --ext hermes
  ./scripts/sync-cursor.sh <target> --tool py-indexer
  ./scripts/sync-cursor.sh --list
  ./scripts/sync-cursor.sh --help

Copy only files under each selected module's files/.cursor/ into <target>/.cursor/.
Optionally install extensions with --ext (continue, openspec, forge, act, hermes).
Optionally install tools with --tool (repeatable). Explicitly requested tools install
fully (same treatment as --ext), not Cursor-assets-only.
--ext forge always installs openspec first.
--ext hermes also installs the security module and its dependency (base) in full,
including non-Cursor files such as .github/workflows/security-check.yml.
That copy does not run the workflow, scan the tree, start a review, or change remotes.
Other modules named on this command stay cursor-only.
Dependencies and conflicts are resolved the same way as init.sh.
Existing files are skipped unless --force is passed.
Preserved security records are never overwritten, including with --force.

Examples:
  ./scripts/sync-cursor.sh /path/to/project --typescript --security
  ./scripts/sync-cursor.sh /path/to/project --react --force
  ./scripts/sync-cursor.sh /path/to/project --cpp11
  ./scripts/sync-cursor.sh /path/to/project --python
  ./scripts/sync-cursor.sh /path/to/project --ext continue
  ./scripts/sync-cursor.sh /path/to/project --ext forge
  ./scripts/sync-cursor.sh /path/to/project --ext act
  ./scripts/sync-cursor.sh /path/to/project --ext hermes
  ./scripts/sync-cursor.sh /path/to/project --tool py-indexer
  ./scripts/sync-cursor.sh /path/to/project --base --ext continue --force
  ./scripts/sync-cursor.sh --list
EOF
}

parse_common_args "$@"

if [[ "${SHOW_HELP}" -eq 1 ]]; then
  usage
  exit 0
fi

if [[ "${DO_LIST}" -eq 1 ]]; then
  list_modules
  exit 0
fi

[[ -n "${TARGET_DIR}" ]] || {
  usage >&2
  die "missing target path"
}
if [[ ${#SELECTED_MODULES[@]} -eq 0 && ${#SELECTED_EXTENSIONS[@]} -eq 0 && ${#SELECTED_TOOLS[@]} -eq 0 ]]; then
  usage >&2
  die "select at least one module (e.g. --typescript), --ext (continue|openspec|forge|act|hermes), or --tool (e.g. py-indexer)"
fi

mkdir -p "${TARGET_DIR}"
TARGET_DIR="$(cd "${TARGET_DIR}" && pwd)"

note_extension_module_dependencies

if [[ ${#SELECTED_MODULES[@]} -gt 0 ]]; then
  resolve_dependencies
  detect_conflicts
  if [[ ${#EXTENSION_MODULE_SEEDS[@]} -gt 0 ]]; then
    echo "syncing into ${TARGET_DIR}"
  else
    echo "syncing .cursor/ into ${TARGET_DIR}"
  fi
  echo "resolved: ${RESOLVED_MODULES[*]}"
  echo
  install_synced_modules
else
  echo "syncing into ${TARGET_DIR}"
  echo "resolved: (no modules)"
  echo
fi

install_extensions
# Explicit tools install fully (like --ext), not Cursor-only.
install_tools
