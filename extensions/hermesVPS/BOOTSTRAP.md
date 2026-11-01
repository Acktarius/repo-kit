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
| Artifact helper | `/opt/data/hermes-review/bin/hermes-vps-artifacts` |
| Rules / tasks | under the policy prefix |
| Source repository | `/opt/data/repositories/<target-id>` (from `run.json`) |
| Run root | `/opt/data/review-runs/<target-id>/<run-id>/` (from `run.json`) |

If the install prefix differs, the operator must use that prefix consistently.
Non-default prefixes are not auto-discovered from this file's location.

The three trees (policy, source, run output) must be distinct.

## `run.json` vs `manifest.json` vs `targets.json`

- **`targets.json`:** operator-maintained registry: `target-id` → exact
  `active_run_json` path.
- **`run.json`:** operator-prepared run configuration (authoritative identity,
  commit, output). Never modify. `phase_request.phase` is legacy/informational;
  the CLI `--phase` flag is authoritative.
- **`manifest.json`:** artifact index, maintained exclusively by
  `bin/hermes-vps-artifacts`. Agents and the runner must not hand-edit it.

## Runner CLI compatibility note

**`--phase NNN` is required** on `hermes-vps-review`. Callers that previously
omitted `--phase` (implying phase 010) must now pass `--phase 010` explicitly.

## Preferred setup before phase 010

```text
/opt/data/hermes-review/bin/init-hermes-review https://github.com/org/repo.git
```

## Short commands (when skills are registered)

```text
/hermes-vps-010 repoX
/hermes-vps-020 repoX
/hermes-vps-030 repoX
/hermes-vps-040 repoX
/hermes-vps-050 repoX auth-module ← priority_area required
/hermes-vps-060 repoX
/hermes-vps-070 repoX C-001       ← candidate_id required
/hermes-vps-080 repoX C-001       ← candidate_id required (actionable 070)
/hermes-vps-remediate repoX       ← regenerate export (automatic after last 070)
```

## One-line upload fallback (for any phase)

Replace `NNN` with the phase number and `repoX` with the registry key:

```text
Read /opt/data/hermes-review/BOOTSTRAP.md and execute only phase NNN for target repoX using /opt/data/hermes-review/targets.json; stop if validation fails.
```

### How this bootstrap routes that request (any phase)

1. Treat the target token as a registry key only (not a path fragment).
2. Run validation:

   ```text
   /opt/data/hermes-review/bin/hermes-vps-review \
     --phase NNN \
     --registry /opt/data/hermes-review/targets.json \
     --target-id <target-id>
   ```

   For phases 070 and 080, also pass `--trigger-input <subject_id>`.

3. Non-zero exit → report failure and **stop**.
4. Zero exit → follow the generated phase instructions (task/rules).
   Write the report (and payload JSON for phases 060/070).
   Then call `hermes-vps-artifacts register` with appropriate flags.
   Then stop.
5. Do not advance phases, contact Roomote/GitHub/MCP, or modify source/policy.

## Phase gate sequence

| Phase | Prerequisites | Special inputs |
|-------|--------------|----------------|
| 010 | none | — |
| 020 | 010 | — |
| 030 | 010, 020 | — |
| 040 | 010, 020, 030 | network authorization; `--payload-json vuln-intel-record.json` required |
| 050 | 010, 020 | priority_area (one per invocation; repeated, selected per priority) |
| 060 | 040 OR 050 (every selected 050 priority) | `--payload-json triage-payload.json` required |
| 070 | 060 | candidate_id (one per invocation); `--payload-json finding-record.json` required |
| 080 | 060, 070 (actionable), 040 | candidate_id (one per invocation); `--payload-json plan-080-*.json` required |
| generate-findings | 060 + all 070s + 040 (freshness) | `--require-fresh-intel` optional |

Every report starts with the REPORT IDENTITY HEADER line (`<!-- hermes-vps-report: {...} -->`)
printed by `hermes-vps-review`; it records the exact inputs analyzed.  Registration
rejects the report if any selected input changed during the phase (see Rule 005).

## Tools

**Runner:** Python 3 and Git. Fail clearly if missing.

**Intelligence collector:** `bin/hermes-vps-collect-intel` (Python 3, stdlib only).
Invoked by Hermes as part of phase-040 task; not called directly by operator.
All endpoint URLs centralized in `lib/hermes_vps_intel.py INTEL_SOURCES`.

**Not required:** `hermes` CLI, `gh`, Docker, sudo, MCP, Roomote filesystem.

## Stop conditions

Validation failure; missing `reports/` directory; `reports/` escaping the run
root; missing required policy/task/template files for the requested phase;
source path not the non-bare worktree root; dirty tree or SHA mismatch;
`schema_version` not exact integer `1`; unknown target id; registry/run
policy-prefix mismatch; inaccessible policy/task/registry/run files; missing
`--trigger-input` for repeated phases; cross-subject supersession attempt.
