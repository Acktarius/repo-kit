---
name: scrub-personal-data
description: >-
  Find and replace personal data (usernames, names, hostnames, private IPs,
  emails, tracked .env files) in git-tracked files with
  .repo-kit/scripts/scrub-personal-data.sh. Use when the user asks to scrub,
  sanitize, or check for leaked personal info, an IP address, or a username,
  or before publishing docs, notes, or a release.
---

# Scrub personal data

Policy lives in `.cursor/rules/no-personal-data.mdc`. This skill runs the check.

## 1. Report

```bash
.repo-kit/scripts/scrub-personal-data.sh [PATH...]
```

- Exit `0`: clean. Say so and stop.
- Exit `1`: show the numbered report to the user as printed.
- Exit `2`: usage or git error. Show the message.
- Exit `127` or "No such file": python3 or the script is missing. Suggest
  `./scripts/init.sh <project> --base` from the repo-kit checkout, or installing python3.

If the output starts with `note: no tokens loaded`, tell the user to create the
tokens file. Names and usernames are not detected without it:

```bash
cp .repo-kit/personal-tokens.txt.example .repo-kit/personal-tokens.txt
```

Never print, quote, or summarize the contents of `.repo-kit/personal-tokens.txt`.

## 2. Ask, then fix

Ask which numbers to fix. Do not fix without an answer. Then run one of:

```bash
.repo-kit/scripts/scrub-personal-data.sh --fix 1,3
.repo-kit/scripts/scrub-personal-data.sh --fix
.repo-kit/scripts/scrub-personal-data.sh docs --fix
```

- Run `--fix` right after the report. Numbers come from a fresh scan, so if any
  file changed in between, report again first.
- Paths go before `--fix`.
- `refused: ... unstaged changes`: the file must be staged or committed first so
  the fix can be undone. Suggest `git add <path>` and let the user decide.
- `refused: ... env`: tracked env files are never rewritten. Suggest
  `git rm --cached <path>` and adding it to `.gitignore`.

## 3. Confirm

Re-run the report. Pass on the `review:` and `undo:` commands the script printed.
Mention that values already in git history are not removed by this tool.
