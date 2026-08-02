#!/usr/bin/env bash
set -euo pipefail

show_help() {
  cat <<'USAGE'
Usage:
  ai-prompter.sh [text...]
  ai-prompter.sh --stdin
  ai-prompter.sh --file <path>
  ai-prompter.sh help

Purpose:
  Convert rough engineering notes into a structured, Cursor-ready Markdown prompt
  without using any external model.

Output format:
  # Context
  # Findings
  # Goal
  # Task
  # References

Examples:
  ai-prompter.sh "I hope there is no security issue in src/lib/qr-decode.ts"
  printf 'investigate rate limiter issue in api and suggest patch' | ai-prompter.sh --stdin
  ai-prompter.sh --file notes/task.txt
USAGE
}

collect_input() {
  local mode="${1:-args}"
  shift || true
  case "$mode" in
    args)
      [[ $# -gt 0 ]] || { echo "No input text provided." >&2; exit 1; }
      printf '%s\n' "$*"
      ;;
    stdin)
      cat
      ;;
    file)
      local path="${1:-}"
      [[ -n "$path" ]] || { echo "--file requires a path" >&2; exit 1; }
      [[ -f "$path" ]] || { echo "File not found: $path" >&2; exit 1; }
      cat "$path"
      ;;
    *)
      echo "Unknown input mode: $mode" >&2
      exit 1
      ;;
  esac
}

main() {
  local mode="args"
  local file_path=""

  if [[ $# -eq 0 ]]; then
    show_help
    exit 1
  fi

  case "$1" in
    help|-h|--help)
      show_help
      exit 0
      ;;
    --stdin)
      mode="stdin"
      shift
      ;;
    --file)
      mode="file"
      shift
      file_path="${1:-}"
      [[ -n "$file_path" ]] || { echo "--file requires a path" >&2; exit 1; }
      shift
      ;;
  esac

  local raw_input
  if [[ "$mode" == "args" ]]; then
    raw_input="$(collect_input args "$@")"
  elif [[ "$mode" == "stdin" ]]; then
    raw_input="$(collect_input stdin)"
  else
    raw_input="$(collect_input file "$file_path")"
  fi

  RAW_INPUT="$raw_input" python3 - <<'PY'
import os
import re
import textwrap

raw = os.environ.get("RAW_INPUT", "").strip()
if not raw:
    raise SystemExit("No input text provided.")

text = " ".join(raw.split())
lower = text.lower()

url_re = re.compile(r'https?://[^\s<>"\')\]]+')
cmd_re = re.compile(r'`([^`]+)`|\b(?:git|npm|pnpm|yarn|bun|node|python3?|pytest|cargo|go|docker|kubectl|curl|wget|make|cmake|grep|rg|sed|awk|bash|sh)\b[^\n;|]*')
path_re = re.compile(r'(?:(?:\./|\.\./|/)?(?:[\w.-]+/)+[\w.-]+|[\w./-]+\.(?:ts|tsx|js|jsx|mjs|cjs|py|rs|go|java|kt|swift|cpp|cc|c|h|hpp|json|yaml|yml|toml|md|sh|sql|html|css))')
error_re = re.compile(r'\b(?:error|exception|traceback|failed|failure|denied|timeout|unauthorized|forbidden|security issue|vulnerability|bug)\b', re.I)

urls = []
for m in url_re.findall(text):
    u = m.rstrip('.,);]')
    if u not in urls:
        urls.append(u)

paths = []
for m in path_re.findall(text):
    p = m.rstrip('.,);]')
    if p not in paths:
        paths.append(p)

commands = []
for match in cmd_re.finditer(text):
    cmd = match.group(1) if match.group(1) else match.group(0)
    cmd = cmd.strip().rstrip('.,')
    if cmd and cmd not in commands:
        commands.append(cmd)

keyword_map = {
    'security': 'security review',
    'vulnerability': 'security review',
    'bug': 'bug investigation',
    'error': 'bug investigation',
    'refactor': 'refactor planning',
    'cleanup': 'refactor planning',
    'performance': 'performance review',
    'slow': 'performance review',
    'optimize': 'performance review',
    'test': 'test review',
    'failing': 'test review',
    'review': 'code review',
    'audit': 'code review',
    'readme': 'documentation update',
    'docs': 'documentation update',
    'document': 'documentation update',
}

intent = 'engineering task'
for k, v in keyword_map.items():
    if k in lower:
        intent = v
        break

context = []
context.append(text[0].upper() + text[1:] if len(text) > 1 else text.upper())
if paths:
    context.append('Relevant paths mentioned: ' + ', '.join(paths) + '.')
if urls:
    context.append('Relevant URLs mentioned: ' + ', '.join(urls) + '.')

findings = []
if any(tok in lower for tok in ['i think', 'i hope', 'maybe', 'might', 'possibly', 'could be']):
    findings.append('The request is phrased as a concern or hypothesis rather than a confirmed issue.')
if paths:
    findings.append('The request names specific files or paths that should be inspected first.')
else:
    findings.append('No concrete file path was provided, so repository discovery may be needed first.')
if not urls and not commands and not error_re.search(text):
    findings.append('No external reference, command, or concrete error output was provided.')
if error_re.search(text):
    findings.append('The request mentions a possible error, bug, or security-related concern that should be validated with code inspection and tests.')

if 'security' in lower or 'vulnerability' in lower:
    goal = 'Assess the referenced code for security weaknesses and identify any credible risk.'
    task = [
        'Locate and inspect the referenced code paths and nearby call sites.',
        'Assess trust boundaries, input validation, parsing, decoding, authentication, authorization, and error handling.',
        'Check for unsafe assumptions, injection paths, denial-of-service risks, secret exposure, and misuse of untrusted data.',
        'Suggest minimal code changes or mitigations if a credible weakness is found.',
        'Summarize whether the concern appears real, low risk, or unsupported by current evidence.',
    ]
elif any(k in lower for k in ['bug', 'error', 'failing', 'failure', 'exception']):
    goal = 'Assess the reported issue, identify likely root causes, and outline a safe fix path.'
    task = [
        'Locate the affected code paths, tests, and recent changes related to the issue.',
        'Assess likely failure points, invariants, edge cases, and error handling behavior.',
        'Suggest a minimal code change and any tests needed to validate the fix.',
        'Verify whether the issue is reproducible, expected behavior, or no longer present.',
    ]
elif any(k in lower for k in ['refactor', 'cleanup']):
    goal = 'Assess the current implementation and outline a safe refactor plan.'
    task = [
        'Locate the relevant modules, symbols, and dependencies.',
        'Assess coupling, duplication, naming, boundaries, and test coverage.',
        'Suggest a staged refactor plan with low-risk intermediate steps.',
        'Identify regressions to watch for and tests to run after changes.',
    ]
elif any(k in lower for k in ['performance', 'slow', 'optimize']):
    goal = 'Assess likely performance bottlenecks and identify the most useful optimization targets.'
    task = [
        'Locate the relevant hot paths, loops, I/O, queries, or expensive allocations.',
        'Assess algorithmic cost, repeated work, caching opportunities, and avoidable latency.',
        'Suggest targeted code changes or measurement steps before broad optimization.',
        'Summarize the expected impact and verification approach.',
    ]
else:
    goal = 'Clarify the request, inspect the relevant code, and propose the next best engineering action.'
    task = [
        'Locate the relevant files, symbols, and call sites.',
        'Assess current behavior, assumptions, and nearby tests or documentation.',
        'Suggest code changes, follow-up questions, or validation steps based on what is found.',
        'Summarize the most likely next action for implementation or review.',
    ]

references = []
for p in paths:
    references.append(p)
for u in urls:
    references.append(u)
for c in commands:
    references.append(c)
if not references:
    references.append('None explicitly provided.')

def bullets(items):
    return '\n'.join(f'- {item}' for item in items)

print('# Context')
for line in context:
    print(line)
print()
print('# Findings')
print(bullets(findings[:4]))
print()
print('# Goal')
print(goal)
print()
print('# Task')
print(bullets(task))
print()
print('# References')
print(bullets(references))
PY
}

main "$@"
