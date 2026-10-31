# hermesVPS bootstrap (read ≠ execute)

## Purpose

This document tells Hermes (or any operator) how to start a **single** review
phase in upload / VPS mode. Reading this file does **not** authorize or start
a phase. A separate, explicit human request is required.

If any required path or input is missing or inaccessible, **stop**. Do not
guess paths, infer the latest report, or invent repository identity.

## Absolute paths (operator fills these)

Default documented deployment binding (not universal):

| Role | Absolute path (example) |
|------|-------------------------|
| Policy prefix | `/opt/data/hermes-review` |
| This bootstrap | `/opt/data/hermes-review/BOOTSTRAP.md` |
| Target registry | `/opt/data/hermes-review/targets.json` |
| Initializer | `/opt/data/hermes-review/bin/init-hermes-review` |
| Runner | `/opt/data/hermes-review/bin/hermes-vps-review` |
| Shared library | `/opt/data/hermes-review/lib/hermes_vps_common.py` |
| Rules / tasks | under the policy prefix |
| Source repository | `/opt/data/repositories/<target-id>` (from `run.json`) |
| Run root | `/opt/data/review-runs/<target-id>/<run-id>/` (from `run.json`) |

If the install prefix differs, the operator must use that prefix consistently
in registry, `run.json`, and any registered skill copy. Non-default prefixes
are not auto-discovered from this file’s location.

The three trees (policy, source, run output) must be distinct.

## `run.json` vs `manifest.json` vs `targets.json`

- **`targets.json`:** operator-maintained registry: `target-id` → exact
  `active_run_json` path. Do not scan for runs or newest reports.
- **`run.json`:** operator-prepared run configuration (authoritative identity,
  commit, output, phase). Hermes and the runner must **not** modify it.
- **`manifest.json`:** operator-maintained artefact/acceptance index. Optional
  at empty phase-010 start. Hermes must **not** update it automatically
  (procedural; not OS-enforced).

## Preferred setup before phase 010

Operators should normally create the run with:

```text
/opt/data/hermes-review/bin/init-hermes-review https://github.com/org/repo.git
```

(or `python3 …/bin/init-hermes-review …` if the execute bit was lost). That
creates the source checkout (if needed), run root, empty `reports/`, `run.json`,
and registry entry, then validates. It does **not** start analysis and does
**not** register skills.

## Short command (when skill is registered)

```text
/hermes-vps-010 repoX
```

Registration is a separate opt-in step. Uploading this directory does **not**
register slash commands. See README for documentation-only registration notes.

## One-line upload fallback (natural language; not a slash command)

Copy-ready line (replace `repoX` with the approved registry key):

```text
Read /opt/data/hermes-review/BOOTSTRAP.md and execute only phase 010 for target repoX using /opt/data/hermes-review/targets.json; stop if validation fails.
```

### How this bootstrap routes that request

When the human asks for phase 010 for a **target** via the fallback (or
equivalent wording that names a registry target):

1. Treat the target token as a registry key only (not a path fragment).
2. Run validation through the same runner the skill uses:

   ```text
   /opt/data/hermes-review/bin/hermes-vps-review \
     --registry /opt/data/hermes-review/targets.json \
     --target-id <target-id>
   ```

   Use separate argv elements; do not `eval`; do not invent shell scripts that
   interpolate unvalidated text into executable syntax.

3. If the runner exits non-zero → report failure and **stop**.
4. If the runner exits zero → follow the generated phase-010 instructions
   (task/rules). Write only the approved report. Then stop.
5. Do not advance phases, contact Roomote/GitHub/MCP, or modify source/policy.

Direct `--run-json` use remains valid for operators who already know the exact
run path; registry mode is required for target-id short commands / fallback.

## Tools

**Runner:** Python 3 and Git. Fail clearly if missing; do not install packages.
Do not claim they exist in the portal until checked.

**Not required:** `hermes` CLI, `gh`, Docker, sudo, MCP, Roomote filesystem,
or a full repo-kit checkout.

## After the Hermes report (010 gate)

1. Human reviews the report.  
2. Optionally hand off to Roomote.  
3. Human acceptance of exact artifact versions.  
4. Separate explicit human request required before phase 020.  

## Stop conditions

Initializer failure (invalid GitHub HTTPS URL; target-id owner collision;
missing `--activate-new-run` when replacing an active run; existing run
directory; dirty or mismatched existing source; clone/auth failure);
validation failure; missing `reports/` directory; `reports/` or selected
output escaping the run root (including symlinks into source/policy/elsewhere);
report collision (including dangling output symlinks); source path that is not
the non-bare worktree root; dirty tree or SHA mismatch; `schema_version` not
exact integer `1`; unknown or invalid target id; registry/run policy-prefix
mismatch; wrong phase in the selected run; inaccessible
policy/task/registry/run files.
