# act-run-workflows

Run secrets-free GitHub Actions workflows locally with act (Docker).

Read `.cursor/skills/act-run-workflows/SKILL.md` and follow it.

## Instructions

1. When scope is unclear, run `.repo-kit/scripts/act-run-workflows.sh --list` first.
2. Run `.repo-kit/scripts/act-run-workflows.sh` for eligible workflows only.
3. Report skipped workflows and why (especially `${{ secrets.* }}` usage).
4. Never attempt to run workflows that require GitHub secrets.

If preflight fails (missing `docker`, `act`, or unreachable daemon), tell the user to install the act extension:

```bash
./scripts/init.sh <target> --ext act
```
