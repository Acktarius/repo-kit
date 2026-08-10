---
name: act-run-workflows
description: >-
  Run secrets-free GitHub Actions workflows locally with nektos/act and Docker.
  Use when the user asks to run npm audit locally, test CI locally, run act,
  execute ci-check or npm-audit workflows, or validate GitHub Actions without
  pushing.
---

# Act — local GitHub Actions

Run selected workflows from `.github/workflows/` on the host via [nektos/act](https://github.com/nektos/act) and Docker.

## Entrypoint

Always use the project script:

```bash
.repo-kit/scripts/act-run-workflows.sh [--list] [--event EVENT] [workflow-file ...]
```

Run from the repository root (or pass `--root PATH`).

## Eligible workflows

Auto-discovery matches filenames containing:

- `npm-audit` (e.g. `npm-audit.yaml`)
- `ci-check` (e.g. `ci-check.yml`)

Explicit file arguments are allowed but still secrets-filtered.

## Secrets exclusion (mandatory)

Skip any workflow that references `${{ secrets.* }}`.

Examples that must **never** be run locally:

- `security-check.yml` (uses `${{ secrets.GITHUB_TOKEN }}`)

Do not pass real secrets to act. The script uses `--secret-file /dev/null` for eligible runs.

## Runner and Node

Project `.actrc` maps `ubuntu-latest` to the medium runner image:

```text
-P ubuntu-latest=catthehacker/ubuntu:act-latest
```

Node version comes from each workflow's `actions/setup-node` step (not from act itself).

## Event selection

Default event order when inferring from `on:`:

1. `pull_request`
2. `push`
3. `workflow_dispatch`

Override with `--event NAME` when needed.

## Agent workflow

1. `--list` when the user has not named a specific workflow.
2. Run eligible workflows; summarize stdout/stderr and exit code.
3. If `docker` or `act` is missing, or `docker info` fails, suggest:

   ```bash
   ./scripts/init.sh <target> --ext act
   ```

4. Do not install Docker or act yourself unless the user explicitly asks.

## Output

Report:

- eligible workflows run (path + event)
- skipped workflows (path + reason)
- act job failures with relevant log excerpts
