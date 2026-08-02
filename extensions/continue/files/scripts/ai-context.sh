#!/usr/bin/env bash
set -euo pipefail

MAX_BYTES_DEFAULT=120000
RG_CONTEXT_DEFAULT=2
GREP_CONTEXT_DEFAULT=2
DIFF_UNIFIED_DEFAULT=3

show_help() {
  cat <<'USAGE'
Usage:
  ai-context.sh rg <pattern> [path]
  ai-context.sh grep <pattern> [path]
  ai-context.sh diff
  ai-context.sh staged-diff
  ai-context.sh files <file1> [file2 ...]
  ai-context.sh help

Purpose:
  Gather deterministic local context, then use Continue CLI (cn -p) with local Qwen
  to format the result into Markdown that is easy to paste into Cursor or Kilo.

Environment variables:
  CONTINUE_CMD           Continue command, default: cn -p --silent
  AICTX_MAX_BYTES        Max raw input bytes sent to Continue, default: 120000
  AICTX_RG_CONTEXT       rg context lines, default: 2
  AICTX_GREP_CONTEXT     grep context lines, default: 2
  AICTX_DIFF_UNIFIED     git --no-pager diff unified lines, default: 3

Examples:
  ai-context.sh rg "AuthMiddleware" src/
  ai-context.sh grep "TODO" .
  ai-context.sh diff
  ai-context.sh staged-diff
  ai-context.sh files src/config.ts src/auth.ts
USAGE
}

CONTINUE_CMD="${CONTINUE_CMD:-cn -p --silent}"
AICTX_MAX_BYTES="${AICTX_MAX_BYTES:-$MAX_BYTES_DEFAULT}"
AICTX_RG_CONTEXT="${AICTX_RG_CONTEXT:-$RG_CONTEXT_DEFAULT}"
AICTX_GREP_CONTEXT="${AICTX_GREP_CONTEXT:-$GREP_CONTEXT_DEFAULT}"
AICTX_DIFF_UNIFIED="${AICTX_DIFF_UNIFIED:-$DIFF_UNIFIED_DEFAULT}"

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

build_prompt() {
  local mode="$1"
  cat <<EOF2
You are formatting shell command output for later AI-assisted coding work.
Respond directly in plain Markdown.
Do not call tools.
Do not output JSON.
Do not output XML.
Do not emit function-call syntax.
Do not explain your process.
Preserve filenames, paths, line numbers, symbols, and code snippets exactly when present.
Do not invent files or changes that are not in the input.

The content below came from a local developer machine.
The mode is: $mode

Format the output with these sections:
# Summary
# Key files
# Important matches or hunks
# Suggested prompt for Cursor or Kilo

Rules for the last section:
- Write a compact prompt another coding agent can use.
- Mention exact files and symbols when available.
- Keep it actionable and implementation-oriented.
- If the input is insufficient, say what to inspect next.
EOF2
}

trim_bytes() {
  python3 - "$AICTX_MAX_BYTES" <<'PY'
import sys
limit = int(sys.argv[1])
data = sys.stdin.buffer.read()
if len(data) <= limit:
    sys.stdout.buffer.write(data)
else:
    head = data[:limit]
    notice = b"\n\n[TRUNCATED_BY_AI_CONTEXT]\nInput exceeded byte limit and was truncated.\n"
    sys.stdout.buffer.write(head + notice)
PY
}

run_continue() {
  local mode="$1"
  local prompt
  prompt="$(build_prompt "$mode")"
  local bin
  bin="$(command_bin "$CONTINUE_CMD")"

  if ! cmd_exists "$bin"; then
    echo "Continue command not found: $CONTINUE_CMD" >&2
    echo "Set CONTINUE_CMD, for example: export CONTINUE_CMD='cn -p --silent'" >&2
    exit 127
  fi

  eval "$CONTINUE_CMD \"$prompt\""
}

emit_header() {
  local mode="$1"
  local cmd="$2"
  cat <<EOF2
# AI_CONTEXT_RAW
mode: $mode
cwd: $(pwd)
command: $cmd
max_bytes: $AICTX_MAX_BYTES
EOF2
}

mode_rg() {
  require_cmd rg
  local pattern="${1:?missing pattern}"
  local path="${2:-.}"
  {
    emit_header "rg" "rg -n -C $AICTX_RG_CONTEXT --hidden --glob '!.git' '$pattern' '$path'"
    echo
    echo "## RAW_OUTPUT"
    rg -n -C "$AICTX_RG_CONTEXT" --hidden --glob '!.git' "$pattern" "$path" || true
  } | trim_bytes | run_continue "rg"
}

mode_grep() {
  require_cmd grep
  local pattern="${1:?missing pattern}"
  local path="${2:-.}"
  {
    emit_header "grep" "grep -RIn -C $AICTX_GREP_CONTEXT --exclude-dir=.git '$pattern' '$path'"
    echo
    echo "## RAW_OUTPUT"
    grep -RIn -C "$AICTX_GREP_CONTEXT" --exclude-dir=.git "$pattern" "$path" || true
  } | trim_bytes | run_continue "grep"
}

mode_diff() {
  require_cmd git
  {
    emit_header "diff" "git --no-pager diff --stat && git --no-pager diff --name-only && git --no-pager diff --unified=$AICTX_DIFF_UNIFIED"
    echo
    echo "## DIFF_STAT"
    git --no-pager diff --stat || true
    echo
    echo "## CHANGED_FILES"
    git --no-pager diff --name-only || true
    echo
    echo "## PATCH"
    git --no-pager diff --unified="$AICTX_DIFF_UNIFIED" || true
  } | trim_bytes | run_continue "git --no-pager diff"
}

mode_staged_diff() {
  require_cmd git
  {
    emit_header "staged-diff" "git --no-pager diff --cached --stat && git --no-pager diff --cached --name-only && git --no-pager diff --cached --unified=$AICTX_DIFF_UNIFIED"
    echo
    echo "## DIFF_STAT"
    git --no-pager diff --cached --stat || true
    echo
    echo "## CHANGED_FILES"
    git --no-pager diff --cached --name-only || true
    echo
    echo "## PATCH"
    git --no-pager diff --cached --unified="$AICTX_DIFF_UNIFIED" || true
  } | trim_bytes | run_continue "git --no-pager diff --cached"
}

mode_files() {
  require_cmd sed
  if [[ $# -lt 1 ]]; then
    echo "files mode requires at least one file path" >&2
    exit 1
  fi
  {
    emit_header "files" "cat selected files"
    for f in "$@"; do
      echo
      echo "## FILE: $f"
      if [[ -f "$f" ]]; then
        sed -n '1,250p' "$f"
      else
        echo "[MISSING_FILE] $f"
      fi
    done
  } | trim_bytes | run_continue "files"
}

main() {
  local mode="${1:-help}"
  case "$mode" in
    rg)
      shift
      [[ $# -ge 1 ]] || { echo "rg mode requires a pattern" >&2; exit 1; }
      mode_rg "$@"
      ;;
    grep)
      shift
      [[ $# -ge 1 ]] || { echo "grep mode requires a pattern" >&2; exit 1; }
      mode_grep "$@"
      ;;
    diff)
      shift
      mode_diff "$@"
      ;;
    staged-diff)
      shift
      mode_staged_diff "$@"
      ;;
    files)
      shift
      mode_files "$@"
      ;;
    help|-h|--help)
      show_help
      ;;
    *)
      echo "Unknown mode: $mode" >&2
      show_help
      exit 1
      ;;
  esac
}

main "$@"