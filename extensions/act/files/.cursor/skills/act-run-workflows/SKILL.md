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
.repo-kit/scripts/act-run-workflows.sh [--list] [--all] [--event EVENT] [--workflow NAME] [workflow-file ...]
```

Run from the repository root (or pass `--root PATH`).

## Eligible workflows

**Default discovery** (no arguments): filenames containing `npm-audit` or `ci-check`.

**Force one workflow:**

```bash
.repo-kit/scripts/act-run-workflows.sh --workflow ci.yml
.repo-kit/scripts/act-run-workflows.sh .github/workflows/ci.yml
```

**List or run all secrets-free workflows:**

```bash
.repo-kit/scripts/act-run-workflows.sh --list --all
.repo-kit/scripts/act-run-workflows.sh --all
```

Explicit paths and `--workflow` still skip any file that references `${{ secrets.* }}`.

## Secrets exclusion (mandatory)

Skip any workflow that references `${{ secrets.* }}`.

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

1. `--list --all` when the user has not named a specific workflow.
2. Run eligible workflows; summarize stdout/stderr and exit code.
3. If `docker info` fails and the user is not in the `docker` group, tell them:

   ```bash
   sudo usermod -aG docker $USER
   newgrp docker   # or log out and back in
   ```

4. If `docker` or `act` is missing, suggest `./scripts/init.sh <target> --ext act`.
5. Do not install Docker or act yourself unless the user explicitly asks.

## Output

Report:

- eligible workflows run (path + event)
- skipped workflows (path + reason)
- act job failures with relevant log excerpts
