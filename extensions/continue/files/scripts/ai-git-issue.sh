#!/usr/bin/env bash
set -euo pipefail

CONTINUE_CMD_DEFAULT='cn -p --silent'
FINDINGS_DIR_DEFAULT='.repo-kit/findings'

CONTINUE_CMD="${CONTINUE_CMD:-$CONTINUE_CMD_DEFAULT}"

show_help() {
  cat <<'USAGE'
Usage:
  ai-git-issue.sh [--dir DIR] [--file PATH] [--dry-run] [--label LABEL]...
  ai-git-issue.sh help

Purpose:
  Read local finding Markdown under .repo-kit/findings/, use Continue CLI
  (cn -p) to draft a structured GitHub issue, then create one issue per
  finding via gh.

Options:
  --dir DIR       Findings directory (default: .repo-kit/findings)
  --file PATH     Process a single finding file instead of all *.md in --dir
  --dry-run       Print title/body; do not call gh issue create
  --label LABEL   Pass --label to gh (repeatable)

Environment variables:
  CONTINUE_CMD    Continue command, default: cn -p --silent

Examples:
  ai-git-issue.sh --dry-run
  ai-git-issue.sh --file .repo-kit/findings/01-nonce-reuse.md
  ai-git-issue.sh --label security --label finding
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

git_root() {
  git rev-parse --show-toplevel
}

build_prompt() {
  cat <<'EOF'
Rewrite the finding below into a GitHub issue draft.

Output format (exactly):
1) First line: TITLE: <short actionable issue title>
2) Then a blank line
3) Then Markdown body with these sections only:

## Finding
(what is wrong; concise)

## Threat
(who/what can exploit it and how; concrete)

## Risk level
Critical | High | Medium | Low  (pick one)

## Suggested solution
Concept or approach only — ideas and design direction.
Do NOT include code, patches, diffs, or command paste-blocks.

Rules:
- No preamble before TITLE:
- No JSON, XML, or tool-call syntax
- Do not invent facts absent from the finding
- Keep Suggested solution non-code
EOF
}

draft_issue() {
  local finding_path="$1"
  local prompt raw_out
  prompt="$(build_prompt)"

  local bin
  bin="$(command_bin "$CONTINUE_CMD")"
  if ! cmd_exists "$bin"; then
    echo "Continue command not found: $CONTINUE_CMD" >&2
    echo "Set CONTINUE_CMD, for example: export CONTINUE_CMD='cn -p --silent'" >&2
    exit 127
  fi

  raw_out="$(
    {
      echo "----- FINDING FILE: $(basename "$finding_path") -----"
      echo
      cat "$finding_path"
    } | eval "$CONTINUE_CMD \"$prompt\""
  )"

  FINDING_PATH="$finding_path" RAW_OUT="$raw_out" python3 - <<'PY'
import os
import re
import sys

raw = os.environ.get("RAW_OUT", "").strip()
path = os.environ.get("FINDING_PATH", "")
if not raw:
    print(f"empty Continue output for {path}", file=sys.stderr)
    sys.exit(1)

lines = raw.splitlines()
title = ""
body_start = 0
for i, line in enumerate(lines):
    m = re.match(r"(?i)^TITLE:\s*(.+)\s*$", line.strip())
    if m:
        title = m.group(1).strip().strip('"').strip("'")
        body_start = i + 1
        break

if not title:
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            title = re.sub(r"^#+\s*", "", s).strip()
            body_start = i + 1
            break
        title = s[:120]
        body_start = i + 1
        break

if not title:
    print(f"could not parse TITLE from Continue output for {path}", file=sys.stderr)
    sys.exit(1)

body_lines = lines[body_start:]
while body_lines and not body_lines[0].strip():
    body_lines.pop(0)
body = "\n".join(body_lines).strip()
if not body:
    print(f"empty issue body for {path}", file=sys.stderr)
    sys.exit(1)

print("<<<TITLE>>>")
print(title)
print("<<<BODY>>>")
print(body)
print("<<<END>>>")
PY
}

create_or_preview() {
  local finding_path="$1"
  local dry_run="$2"
  shift 2
  local labels=("$@")

  local parsed title body tmp_body
  parsed="$(draft_issue "$finding_path")"

  # Extract TITLE and BODY from marked Continue output
  eval "$(
    PARSED="$parsed" python3 - <<'PY'
import os
import shlex
import sys

text = os.environ.get("PARSED", "").splitlines()
try:
    i = text.index("<<<TITLE>>>")
    j = text.index("<<<BODY>>>")
    k = text.index("<<<END>>>")
except ValueError:
    print("could not parse Continue draft markers", file=sys.stderr)
    sys.exit(1)

title = "\n".join(text[i + 1 : j]).strip()
body = "\n".join(text[j + 1 : k]).strip()
if not title or not body:
    print("empty title or body after parse", file=sys.stderr)
    sys.exit(1)

print(f"title={shlex.quote(title)}")
print(f"body={shlex.quote(body)}")
PY
  )"

  echo "---- $(basename "$finding_path") ----"
  echo "TITLE: $title"
  echo
  echo "$body"
  echo

  if [[ "$dry_run" -eq 1 ]]; then
    echo "[dry-run] skipped gh issue create"
    echo
    return 0
  fi

  tmp_body="$(mktemp)"
  printf '%s\n' "$body" >"$tmp_body"

  local gh_args=(issue create --title "$title" --body-file "$tmp_body")
  local label
  for label in "${labels[@]+"${labels[@]}"}"; do
    gh_args+=(--label "$label")
  done

  local url
  if ! url="$(gh "${gh_args[@]}")"; then
    rm -f "$tmp_body"
    echo "gh issue create failed for $finding_path" >&2
    exit 1
  fi
  rm -f "$tmp_body"
  echo "created: $url"
  echo
}

main() {
  local findings_dir="$FINDINGS_DIR_DEFAULT"
  local single_file=""
  local dry_run=0
  local labels=()

  if [[ $# -eq 0 ]]; then
    :
  fi

  while [[ $# -gt 0 ]]; do
    case "$1" in
      help|-h|--help)
        show_help
        exit 0
        ;;
      --dir)
        shift
        findings_dir="${1:-}"
        [[ -n "$findings_dir" ]] || { echo "--dir requires a path" >&2; exit 1; }
        shift
        ;;
      --file)
        shift
        single_file="${1:-}"
        [[ -n "$single_file" ]] || { echo "--file requires a path" >&2; exit 1; }
        shift
        ;;
      --dry-run)
        dry_run=1
        shift
        ;;
      --label)
        shift
        [[ -n "${1:-}" ]] || { echo "--label requires a value" >&2; exit 1; }
        labels+=("$1")
        shift
        ;;
      *)
        echo "Unknown argument: $1" >&2
        show_help >&2
        exit 1
        ;;
    esac
  done

  require_cmd git
  require_cmd python3
  require_cmd gh
  ensure_git_repo

  local root files=()
  root="$(git_root)"

  if [[ -n "$single_file" ]]; then
    if [[ "$single_file" != /* ]]; then
      if [[ -f "$single_file" ]]; then
        single_file="$(cd "$(dirname "$single_file")" && pwd)/$(basename "$single_file")"
      elif [[ -f "$root/$single_file" ]]; then
        single_file="$root/$single_file"
      fi
    fi
    [[ -f "$single_file" ]] || {
      echo "Finding file not found: $single_file" >&2
      exit 1
    }
    files=("$single_file")
  else
    if [[ "$findings_dir" != /* ]]; then
      if [[ -d "$findings_dir" ]]; then
        findings_dir="$(cd "$findings_dir" && pwd)"
      elif [[ -d "$root/$findings_dir" ]]; then
        findings_dir="$root/$findings_dir"
      fi
    fi
    if [[ ! -d "$findings_dir" ]]; then
      echo "Findings directory not found: $findings_dir" >&2
      echo "Expected .repo-kit/findings/*.md from crypto-security-review." >&2
      exit 1
    fi
    shopt -s nullglob
    files=("$findings_dir"/*.md)
    shopt -u nullglob
    if [[ ${#files[@]} -eq 0 ]]; then
      echo "No finding Markdown files in $findings_dir" >&2
      exit 1
    fi
    # sort by name (01-… before 02-…)
    IFS=$'\n' files=($(printf '%s\n' "${files[@]}" | sort))
    unset IFS
  fi

  local f
  for f in "${files[@]}"; do
    create_or_preview "$f" "$dry_run" "${labels[@]+"${labels[@]}"}"
  done
}

main "$@"
