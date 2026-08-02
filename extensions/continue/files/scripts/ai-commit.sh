#!/usr/bin/env bash
set -euo pipefail

CONTINUE_CMD_DEFAULT='cn -p --silent'
PATCH_CONTEXT_DEFAULT=3
MAX_BYTES_DEFAULT=100000

CONTINUE_CMD="${CONTINUE_CMD:-$CONTINUE_CMD_DEFAULT}"
AICOMMIT_PATCH_CONTEXT="${AICOMMIT_PATCH_CONTEXT:-$PATCH_CONTEXT_DEFAULT}"
AICOMMIT_MAX_BYTES="${AICOMMIT_MAX_BYTES:-$MAX_BYTES_DEFAULT}"

DEFAULT_EXCLUDES=(
  ':(exclude)AGENTS.md'
  ':(exclude)CLAUDE.md'
  ':(exclude)README.md'
  ':(exclude)package-lock.json'
  ':(exclude)pnpm-lock.yaml'
  ':(exclude)yarn.lock'
  ':(exclude)bun.lockb'
  ':(exclude)tsconfig.tsbuildinfo'
  ':(exclude)test-results/**'
  ':(exclude)coverage/**'
  ':(exclude)dist/**'
  ':(exclude)build/**'
  ':(exclude).next/**'
)

show_help() {
  cat <<'USAGE'
Usage:
  ai-commit-v2.sh [--patch] [--run] [--commit] [--all-staged] [--include <path> ...]
  ai-commit-v2.sh help

Purpose:
  Show staged files and staged diff summary, then suggest or run a Continue CLI
  command that generates a cleaner commit message from staged changes.

Options:
  --patch          Also print the staged patch used for prompting
  --run            Run Continue and print the generated commit message
  --commit         Run Continue and commit using the cleaned generated message
  --all-staged     Do not exclude generated/noisy files from the AI prompt
  --include PATH   Force-include a specific path by removing its default exclusion

Environment variables:
  CONTINUE_CMD            Continue command, default: cn -p --silent
  AICOMMIT_PATCH_CONTEXT  Unified diff context lines, default: 3
  AICOMMIT_MAX_BYTES      Max staged diff bytes sent to Continue, default: 100000

Examples:
  ai-commit-v2.sh
  ai-commit-v2.sh --run
  ai-commit-v2.sh --commit
  ai-commit-v2.sh --all-staged --run
  ai-commit-v2.sh --include AGENTS.md --run
USAGE
}

cmd_exists() {
  command -v "$1" >/dev/null 2>&1
}

require_cmd() {
  if ! cmd_exists "$1"; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

command_bin() {
  awk '{print $1}' <<<"$1"
}

ensure_git_repo() {
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
    echo "Not inside a Git repository." >&2
    exit 1
  }
}

all_staged_files() {
  git --no-pager diff --cached --name-only
}

ensure_staged_changes() {
  if [[ -z "$(all_staged_files)" ]]; then
    echo "No staged changes found." >&2
    exit 1
  fi
}

build_prompt() {
  cat <<'EOF2'
Generate a single-line commit message for these staged changes.
Prefer conventional commit style if the change type is reasonably clear.
Maximum 72 characters.
Output only the commit message.
No body.
No attribution.
No co-author lines.
No quotes.
No Markdown.
No JSON.
No XML.
No explanations.
If the staged changes mix unrelated work, choose a safe, broad message.
EOF2
}

trim_bytes() {
  python3 - "$AICOMMIT_MAX_BYTES" <<'PY'
import sys
limit = int(sys.argv[1])
data = sys.stdin.buffer.read()
if len(data) <= limit:
    sys.stdout.buffer.write(data)
else:
    head = data[:limit]
    notice = b"\n\n[TRUNCATED_BY_AI_COMMIT]\nStaged diff exceeded byte limit and was truncated.\n"
    sys.stdout.buffer.write(head + notice)
PY
}

clean_message() {
  awk '
    BEGIN { IGNORECASE=1 }
    /^Generated with / { next }
    /^Co-Authored-By:/ { next }
    /^Co-authored-by:/ { next }
    /^$/ { if (seen == 0) next; else exit }
    {
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", $0)
      if ($0 == "") next
      print
      seen=1
      exit
    }
  ' | sed 's/^"//; s/"$//; s/^[`[:space:]]*//; s/[`[:space:]]*$//'
}

build_pathspec_args() {
  local use_all="$1"
  shift
  local includes=("$@")
  local args=()

  if [[ "$use_all" -eq 1 ]]; then
    printf '%s\n' "."
    return 0
  fi

  args+=(".")
  local skip
  for ex in "${DEFAULT_EXCLUDES[@]}"; do
    skip=0
    for inc in "${includes[@]}"; do
      if [[ "$ex" == ":(exclude)$inc" || "$ex" == ":(exclude)$inc/**" ]]; then
        skip=1
        break
      fi
    done
    if [[ "$skip" -eq 0 ]]; then
      args+=("$ex")
    fi
  done

  printf '%s\n' "${args[@]}"
}

collect_filtered_diff() {
  local use_all="$1"
  shift
  local includes=("$@")
  mapfile -t pathspecs < <(build_pathspec_args "$use_all" "${includes[@]}")
  git --no-pager diff --cached --unified="$AICOMMIT_PATCH_CONTEXT" -- "${pathspecs[@]}"
}

collect_filtered_name_only() {
  local use_all="$1"
  shift
  local includes=("$@")
  mapfile -t pathspecs < <(build_pathspec_args "$use_all" "${includes[@]}")
  git --no-pager diff --cached --name-only -- "${pathspecs[@]}"
}

collect_filtered_stat() {
  local use_all="$1"
  shift
  local includes=("$@")
  mapfile -t pathspecs < <(build_pathspec_args "$use_all" "${includes[@]}")
  git --no-pager diff --cached --stat -- "${pathspecs[@]}"
}

suggested_command() {
  cat <<EOF2
git --no-pager diff --cached --unified=$AICOMMIT_PATCH_CONTEXT | $CONTINUE_CMD "$(build_prompt | tr '\n' ' ' | sed 's/  */ /g')"
EOF2
}

print_summary() {
  local use_all="$1"
  shift
  local includes=("$@")

  echo "# STAGED_FILES_ALL"
  all_staged_files
  echo
  echo "# STAGED_FILES_FOR_AI"
  collect_filtered_name_only "$use_all" "${includes[@]}" || true
  echo
  echo "# STAGED_STAT_FOR_AI"
  collect_filtered_stat "$use_all" "${includes[@]}" || true
  echo
  echo "# SUGGESTED_COMMAND"
  suggested_command
}

print_patch() {
  local use_all="$1"
  shift
  local includes=("$@")
  echo
  echo "# STAGED_PATCH_FOR_AI"
  collect_filtered_diff "$use_all" "${includes[@]}" || true
}

run_continue() {
  local use_all="$1"
  shift
  local includes=("$@")

  local bin
  bin="$(command_bin "$CONTINUE_CMD")"
  if ! cmd_exists "$bin"; then
    echo "Continue command not found: $CONTINUE_CMD" >&2
    echo "Set CONTINUE_CMD, for example: export CONTINUE_CMD='cn -p --silent'" >&2
    exit 127
  fi

  local prompt
  prompt="$(build_prompt)"
  collect_filtered_diff "$use_all" "${includes[@]}" | trim_bytes | eval "$CONTINUE_CMD \"$prompt\"" | clean_message
}

commit_with_generated_message() {
  local use_all="$1"
  shift
  local includes=("$@")

  local msg
  msg="$(run_continue "$use_all" "${includes[@]}")"
  if [[ -z "${msg// }" ]]; then
    echo "Generated commit message is empty." >&2
    exit 1
  fi

  echo "# GENERATED_COMMIT_MESSAGE"
  echo "$msg"
  echo
  printf '%s\n' "$msg" | git commit -F -
}

main() {
  require_cmd git
  require_cmd python3
  require_cmd awk
  require_cmd sed
  ensure_git_repo
  ensure_staged_changes

  local show_patch=0
  local do_run=0
  local do_commit=0
  local use_all=0
  local includes=()

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --patch)
        show_patch=1
        shift
        ;;
      --run)
        do_run=1
        shift
        ;;
      --commit)
        do_commit=1
        shift
        ;;
      --all-staged)
        use_all=1
        shift
        ;;
      --include)
        shift
        [[ $# -gt 0 ]] || { echo "--include requires a path" >&2; exit 1; }
        includes+=("$1")
        shift
        ;;
      help|-h|--help)
        show_help
        exit 0
        ;;
      *)
        echo "Unknown argument: $1" >&2
        show_help
        exit 1
        ;;
    esac
  done

  print_summary "$use_all" "${includes[@]}"

  if [[ "$show_patch" -eq 1 ]]; then
    print_patch "$use_all" "${includes[@]}"
  fi

  if [[ "$do_run" -eq 1 ]]; then
    echo
    echo "# GENERATED_COMMIT_MESSAGE"
    run_continue "$use_all" "${includes[@]}"
  fi

  if [[ "$do_commit" -eq 1 ]]; then
    echo
    commit_with_generated_message "$use_all" "${includes[@]}"
  fi
}

main "$@"