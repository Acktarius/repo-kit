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

Re-run when already up to date is a no-op unless --force (cursor refresh only).

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
    exit 0
  fi
  echo "up to date; refreshing base .cursor/ assets (--force)"
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
