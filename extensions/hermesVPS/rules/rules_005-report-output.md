# Rule 005 — Report output and artefact boundary (hermesVPS)

## Purpose

Define the only permitted write location for hermesVPS phase reports during
read-only review phases, and how versioned artefacts are named.

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
  `run.json`, or `manifest.json` unless the human explicitly approves a
  separate action with exact destination and content.
- `run.json` is operator-authored configuration; agents and the runner must
  not modify it.
- `manifest.json` is operator-maintained. Agents must not update it
  automatically. Procedural ownership is not OS-enforced against a same-UID
  writer.

## Reports directory

`<run_root>/reports/` must already exist as a real directory strictly inside
the resolved run root before `hermes-vps-review` will print a phase prompt.
A missing `reports/` directory is a validation failure (actionable: the
operator must create that exact directory). Symlinks that resolve outside the
run root, or into the source or policy trees, are rejected.

Before writing, reconfirm that `reports/` and the selected report path still
remain inside the approved run-root reports directory and that the selected
output still does not exist (including dangling symlinks). Preflight
validation cannot prevent later concurrent filesystem changes.

If `reports/` is missing at write time, **do not create it** unless the human
separately approved creating that exact directory. Prefer stopping with
completion state `blocked` naming the missing path. The runner never creates
or repairs directories.

## Phase report naming

Produce exactly one primary Markdown report per requested write:

```text
<run_root>/reports/phase-NNN-hermes-vN.md
```

Example: `phase-010-hermes-v1.md`

- Never overwrite an existing report.
- If the selected version already exists, stop or choose a new version only
  when the human explicitly selected that new version in the request/`run.json`.
- Do not auto-pick “newest” prior reports as prerequisites.

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
10. next human approval required  

Use `templates/phase-010-report.md` for phase 010 structure when applicable.

## After the report (gates; not automatic)

Keep states distinct:

1. Hermes report produced  
2. Roomote review produced (optional in the initial manual workflow)  
3. Human acceptance recorded (exact artifact versions)  
4. Next phase explicitly requested by a human  

Roomote review is optional; absence must be recorded accurately if acceptance
proceeds without it. Human acceptance of phase 010 artefacts is required
before a dependent phase 020 may be requested. Acceptance alone does not
start phase 020.

## Boundary

Reports are review artefacts, not approval to change source code.
Stop after writing the requested phase report. Do not advance automatically.
Do not create an extra manifest-update file.
