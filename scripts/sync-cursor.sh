#!/usr/bin/env bash
# Sync only .cursor/ assets from selected modules into a target project.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/sync-cursor.sh <target> --<module> [--<module> ...] [--force]
  ./scripts/sync-cursor.sh --list
  ./scripts/sync-cursor.sh --help

Copy only files under each selected module's files/.cursor/ into <target>/.cursor/.
Dependencies and conflicts are resolved the same way as init.sh.
Existing files are skipped unless --force is passed.

Examples:
  ./scripts/sync-cursor.sh /path/to/project --typescript --security
  ./scripts/sync-cursor.sh /path/to/project --react --force
  ./scripts/sync-cursor.sh /path/to/project --cpp11
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
[[ ${#SELECTED_MODULES[@]} -gt 0 ]] || {
  usage >&2
  die "select at least one module (e.g. --typescript) or use --list"
}

mkdir -p "${TARGET_DIR}"
TARGET_DIR="$(cd "${TARGET_DIR}" && pwd)"

resolve_dependencies
detect_conflicts

echo "syncing .cursor/ into ${TARGET_DIR}"
echo "resolved: ${RESOLVED_MODULES[*]}"
echo
CURSOR_ONLY=1
install_modules
