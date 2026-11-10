#!/usr/bin/env bash
# Migrate a target project to the current repo-kit layout version.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/migrate.sh <target> [--force]
  ./scripts/migrate.sh --help

Upgrade a target project's repo-kit layout to the kit VERSION.
Missing .repo-kit/version is treated as <= 1.0.1 (1.0.0 when legacy .chat/ exists, else 1.0.1).

Steps for 1.0.0 -> 1.0.1:
  - move .chat/ contents to .repo-kit/chat/ (preserves user data)

Steps for <= 1.0.1 -> 1.0.2:
  - move .findings/ contents to .repo-kit/findings/ (preserves user data)
  - upgrade root .gitignore (.findings/ -> .repo-kit/findings/)
  - write .repo-kit/version
  - refresh base module .cursor/ assets (force overwrite)

If an older project-local py-indexer install is present, migrate lists those files
and asks before removing them. Answering y is the cleanup. REPO_KIT_TOOL_ASSUME_YES
does not answer that question. Removal runs only when a shared py-indexer CLI is
already installed, and only for positively identified legacy files. repos.json,
excludes.txt, customized requirements, unknown files inside a legacy directory,
and every directory under ~/.cache/py-indexer/indexes/ are left in place.
If .cursor/mcp.json is invalid, or its py-indexer entry was not migrated and still
names a legacy path, that path is not deleted.

Re-run when already up to date skips cursor refresh unless --force.
The py-indexer cleanup question still runs when old paths are present.

Examples:
  ./scripts/migrate.sh /path/to/project
  ./scripts/migrate.sh /path/to/project --force
EOF
}

FORCE_CURSOR=0
SHOW_HELP=0
TARGET_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force)
      FORCE_CURSOR=1
      ;;
    --help|-h)
      SHOW_HELP=1
      ;;
    -*)
      die "unknown flag '$1'"
      ;;
    *)
      if [[ -n "${TARGET_DIR}" ]]; then
        die "unexpected argument '$1' (target already set to '${TARGET_DIR}')"
      fi
      TARGET_DIR="$1"
      ;;
  esac
  shift
done

if [[ "${SHOW_HELP}" -eq 1 ]]; then
  usage
  exit 0
fi

[[ -n "${TARGET_DIR}" ]] || {
  usage >&2
  die "missing target path"
}

mkdir -p "${TARGET_DIR}"
TARGET_DIR="$(cd "${TARGET_DIR}" && pwd)"

KIT_VERSION="$(read_kit_version)"
INSTALLED_VERSION="$(read_installed_version "${TARGET_DIR}")"
START_VERSION="${INSTALLED_VERSION}"
MIGRATED=0

echo "migrating ${TARGET_DIR}"
echo "  installed:  ${INSTALLED_VERSION}"
echo "  kit:        ${KIT_VERSION}"
echo

if version_ge "${INSTALLED_VERSION}" "${KIT_VERSION}"; then
  if [[ "${FORCE_CURSOR}" -eq 0 ]]; then
    echo "up to date (${INSTALLED_VERSION} >= ${KIT_VERSION})"
  else
    echo "up to date; refreshing base .cursor/ assets (--force)"
  fi
else
  # 1.0.0 -> 1.0.1: relocate chat handoff from root .chat/ to .repo-kit/chat/
  if version_lt "${INSTALLED_VERSION}" "1.0.1"; then
    echo "step 1.0.1: relocate chat"
    migrate_chat_to_repo_kit "${TARGET_DIR}"
    INSTALLED_VERSION="1.0.1"
    MIGRATED=1
    echo
  fi

  if version_lt "${INSTALLED_VERSION}" "1.0.2"; then
    echo "step 1.0.2: relocate findings"
    migrate_findings_to_repo_kit "${TARGET_DIR}"
    INSTALLED_VERSION="1.0.2"
    MIGRATED=1
    echo
  fi

  write_installed_version "${TARGET_DIR}" "${KIT_VERSION}"
  INSTALLED_VERSION="${KIT_VERSION}"
fi

# Advice is separate from deletion. A yes is not honored without a verified shared
# CLI, and ASSUME_YES does not count as that yes.
_py_indexer_legacy_cleanup "${TARGET_DIR}"
echo

# Refresh base .cursor/ assets after layout migration or --force.
if [[ "${MIGRATED}" -eq 1 ]] || [[ "${FORCE_CURSOR}" -eq 1 ]]; then
  echo "sync base .cursor/ assets"
  discover_modules
  SELECTED_MODULES=("base")
  resolve_dependencies
  CURSOR_ONLY=1
  FORCE_COPY=1
  install_modules
  echo
fi

echo "migration complete"
echo "  version: ${START_VERSION} -> ${INSTALLED_VERSION}"
