# act-run-workflows

Run secrets-free GitHub Actions workflows locally with act (Docker).

Read `.cursor/skills/act-run-workflows/SKILL.md` and follow it.

## Instructions

1. When scope is unclear, run `.repo-kit/scripts/act-run-workflows.sh --list --all` first.
2. To force a workflow (e.g. this repo's `ci.yml`): `.repo-kit/scripts/act-run-workflows.sh --workflow ci.yml`
3. Report skipped workflows and why (especially `${{ secrets.* }}` usage).
4. Never attempt to run workflows that require GitHub secrets.

If preflight fails with docker permission denied, the user is usually not in the `docker` group:

```bash
sudo usermod -aG docker $USER
newgrp docker
```

If `docker` or `act` is missing, install via:

```bash
./scripts/init.sh <target> --ext act
```
