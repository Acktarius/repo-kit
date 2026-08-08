#!/usr/bin/env bash
# Initialize a project by copying selected repo-kit modules.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/init.sh <target> --<module> [--<module> ...] [--ext <name>] [--force]
  ./scripts/init.sh <target> --ext continue
  ./scripts/init.sh <target> --ext openspec
  ./scripts/init.sh <target> --ext forge
  ./scripts/init.sh --list
  ./scripts/init.sh --help

Copy selected modules (and their dependencies) into <target>.
Optionally install extensions with --ext (continue, openspec, forge).
--ext forge always installs openspec first.
Existing files are skipped unless --force is passed.

Examples:
  ./scripts/init.sh /path/to/project --typescript --security
  ./scripts/init.sh /path/to/project --react --security
  ./scripts/init.sh /path/to/project --cpp11
  ./scripts/init.sh /path/to/project --rust --security
  ./scripts/init.sh /path/to/project --python
  ./scripts/init.sh /path/to/project --base --force
  ./scripts/init.sh /path/to/project --ext continue
  ./scripts/init.sh /path/to/project --ext openspec
  ./scripts/init.sh /path/to/project --ext forge
  ./scripts/init.sh /path/to/project --typescript --ext continue
  ./scripts/init.sh --list
EOF
}

parse_common_args "$@"

if [[ "${SHOW_HELP}" -eq 1 ]]; then
  usage
  exit 0
fi

# Allow --list without a target
if [[ "${DO_LIST}" -eq 1 ]]; then
  list_modules
  exit 0
fi

[[ -n "${TARGET_DIR}" ]] || {
  usage >&2
  die "missing target path"
}
if [[ ${#SELECTED_MODULES[@]} -eq 0 && ${#SELECTED_EXTENSIONS[@]} -eq 0 ]]; then
  usage >&2
  die "select at least one module (e.g. --typescript) or --ext (continue|openspec|forge)"
fi

# Resolve absolute target for cleaner summary paths
mkdir -p "${TARGET_DIR}"
TARGET_DIR="$(cd "${TARGET_DIR}" && pwd)"

if [[ ${#SELECTED_MODULES[@]} -gt 0 ]]; then
  resolve_dependencies
  detect_conflicts
  echo "installing into ${TARGET_DIR}"
  echo "resolved: ${RESOLVED_MODULES[*]}"
  echo
  CURSOR_ONLY=0
  # install_modules copies module files/ (including base .chat seeds + chat-context
  # skill) and ensures .chat/{sessions,decisions,archive} via mkdir -p.
  install_modules
else
  echo "installing into ${TARGET_DIR}"
  echo "resolved: (no modules)"
  echo
fi

install_extensions
