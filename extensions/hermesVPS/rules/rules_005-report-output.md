# Rule 005 — Report output and artefact boundary (hermesVPS)

## Purpose

Define the only permitted write location for hermesVPS phase reports during
read-only review phases, how versioned artefacts are named, and how the
artifact index is updated automatically after a report is finalized.

## Prerequisites

- Apply `rules_000-safety-and-scope.md` throughout.

## Policy, source, and output paths

Three trees must remain distinct (from `run.json`):

1. **Policy prefix** — installed hermesVPS toolkit (read-only to the agent)
2. **Source path** — Git repository under analysis (read-only default)
3. **Run root** — generated artefacts for this run ID

- Read policy only from the registered `policy_prefix`.
- Write generated Hermes phase reports only to:
  `<run_root>/reports/`
- Never write outside the approved run root during read-only review phases.
- Do not modify application source, configuration, dependencies, lockfiles,
  tests, documentation, git metadata, CI configuration, policy files,
  or `run.json`.
- `run.json` is operator-authored configuration; agents and the runner must
  not modify it.
- `manifest.json` is maintained exclusively by `hermes-vps-artifacts`.
  Agents must not hand-edit it. Procedural ownership is not OS-enforced
  against a same-UID writer.

## Reports directory

`<run_root>/reports/` must already exist as a real directory strictly inside
the resolved run root before `hermes-vps-review` will print a phase prompt.
A missing `reports/` directory is a validation failure (actionable: the
operator must create that exact directory). Symlinks that resolve outside the
run root, or into the source or policy trees, are rejected.

Before writing, reconfirm that `reports/` still remains inside the approved
run-root reports directory. Preflight validation cannot prevent later
concurrent filesystem changes.

If `reports/` is missing at write time, **do not create it** unless the human
separately approved creating that exact directory. Prefer stopping with
completion state `blocked` naming the missing path. The runner never creates
or repairs directories.

## Phase report naming

The report file name is determined by `hermes-vps-artifacts register`, which
auto-selects the next unused version:

```text
<run_root>/reports/phase-NNN-hermes-vN.md
```

Example: `phase-010-hermes-v1.md`

- Version is selected automatically; do not hard-code or pre-determine it.
- Never overwrite an existing report.
- Do not auto-pick "newest" prior reports as prerequisites.

## Write-then-register flow

After producing a report:

1. Write the report to any filename under `reports/` (the final versioned
   name is assigned by the registration helper).
2. Call `hermes-vps-artifacts register --run-json PATH --phase NNN
   --source-report /abs/path/to/your/report.md`.
3. The helper: acquires the per-run lock → auto-selects the next version →
   copies the report to its final versioned path → computes SHA-256 →
   appends to the artifact index → atomically writes `manifest.json` →
   prints the consultation prompt.
4. If registration fails after the report is saved (saved-but-unregistered):
   follow the exact retry command printed by the helper; do not re-run the
   phase or overwrite the report.
5. After the consultation prompt is printed: **STOP**.

Structural and hash checks do not prove factual correctness of report content.

## Required report contents

Each report must state:

1. phase number and name
2. UTC creation time
3. run ID, approved source, full commit SHA, working-tree state
4. rules consulted
5. exact prerequisite artifact IDs used (none for phase 010)
6. actions actually performed
7. evidence and paths examined
8. limitations, failures, and coverage gaps
9. completion state (`complete` | `blocked` | `incomplete`)
10. next human gate required

Use `templates/phase-010-report.md` for phase 010 structure when applicable.

## After registration (gates; not automatic)

Keep states distinct:

1. Report finalized and registered (artifact index updated)
2. Optional second-opinion review (use consultation prompt from the helper)
3. Next phase explicitly requested by a human

Second-opinion review is optional. Normal progression does not require a
separate acceptance file. Requesting the next phase authorizes use of the
displayed selected inputs only — not source changes or PRs.

## Boundary

Reports are review artefacts, not approval to change source code.
Stop after registration. Do not advance automatically.
