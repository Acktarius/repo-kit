# hermesVPS — Hermes review workflow for VPS / portal upload

## Status

Phase **010 inventory** vertical slice with:

- rules/tasks/templates;
- validation runner (`bin/hermes-vps-review`);
- operator target registry (`targets.json`);
- thin skill adapter `skills/hermes-vps-010/` for `/hermes-vps-010 <target-id>`;
- security schema copy and fixture tests.

This extension does **not** replace `extensions/hermes/`. Local Hermes remains
unchanged.

**Not implemented yet:** installer/packaging automation, phases 020–080,
Roomote/GitHub/MCP automation, verified portal skill discovery.

## Normal operator UX

When the hermesVPS skill is **registered** in the agent skill directory used
by the running Hermes session:

```text
/hermes-vps-010 repoX
```

The skill resolves `repoX` through operator-maintained `targets.json`, runs
the validation/print runner, then follows the generated phase-010 task
instructions. The verbose runner output is an **internal execution contract**
and diagnostic fallback — not what the operator should paste every time.

### One-line upload fallback (not a slash command)

Until skill discovery is verified for a deployment, use this copy-ready line:

```text
Read /opt/data/hermes-review/BOOTSTRAP.md and execute only phase 010 for target repoX using /opt/data/hermes-review/targets.json; stop if validation fails.
```

`BOOTSTRAP.md` routes that request through the **same** registry + runner
validation as the skill. Uploading the runtime directory does **not** register
skills.

## Default prefix vs configurable install

Documentation and the shipped skill body use the deployment binding:

```text
/opt/data/hermes-review
```

That is **not** a universal path. Future install/registration must render or
otherwise set the chosen prefix in the registered skill. Non-default prefixes
do **not** work automatically. No undocumented environment variables or agent
config keys are defined for prefix override. The policy root is **not**
inferred from the skill’s install directory.

## Target registry

Operator-maintained file at `<policy_prefix>/targets.json`
(see `templates/targets.example.json`):

```json
{
  "schema_version": 1,
  "policy_prefix": "/opt/data/hermes-review",
  "targets": {
    "repoX": {
      "active_run_json": "/opt/data/review-runs/repoX/<run-id>/run.json"
    }
  }
}
```

- Maps a registry key to an **exact** `active_run_json` path.
- Does not scan for newest runs or infer from cwd.
- Target ids: ASCII `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`, plus reject `.`,
  `..`, and any id containing `..` (so `a..b` is invalid).
- Ids are keys only — never concatenated into filesystem paths.
- Duplicate JSON object keys (including duplicate target ids) are **rejected**
  by the runner parser (no silent last-wins).
- Registry `policy_prefix` must agree with the selected run’s `policy_prefix`
  after normalization.
- Selected run must request phase **010**; other phases are rejected.

## Runner v1 (validate + print only)

Mutually exclusive modes:

```bash
# Mode A
bin/hermes-vps-review --run-json /absolute/path/to/run.json

# Mode B (short-command / fallback path)
bin/hermes-vps-review \
  --registry /opt/data/hermes-review/targets.json \
  --target-id repoX
```

Optional: `--report-version N` (default 1, or from `run.json` when set).
The skill must not invent or auto-increment versions.

Rejects: mixed modes; `--registry` without `--target-id` (and vice versa);
repeated single-value flags; unexpected positionals; validation failures.

**Does not:** create directories/reports, update configs, launch Hermes,
mutate git, contact GitHub/Roomote/MCP, or authorize the next phase.

Dependencies: **Python 3** and **Git**. No package installs.

## Skill registration (documentation only)

Separate from the self-contained policy payload:

1. Operator reviews `skills/hermes-vps-010/SKILL.md`.
2. Operator copies it into the **verified** Hermes skills root for that
   deployment under a distinct namespace (for example
   `…/skills/repo-kit-hermes-vps/hermes-vps-010/`), **not** over local
   `/hermes-010` / `repo-kit-hermes`.
3. Operator confirms the skill’s embedded prefix matches the install prefix.
4. Portal discovery/hot reload is **unverified** — confirm per deployment.

This repository does **not** write to live `~/.hermes` or modify Hermes
services as part of hermesVPS.

## `run.json` versus `manifest.json`

| File | Owner | Role |
|------|-------|------|
| `run.json` | Operator; immutable during the run | Authoritative identity, commit, output, phase, prerequisites |
| `manifest.json` | Operator-maintained | Produced artefacts / acceptance; must agree on overlapping identity |

Hermes writes only the phase report. Neither Hermes nor the runner updates
the manifest automatically.

## Phase 010 gate

1. Report produced  
2. Optional Roomote review  
3. Human acceptance of exact artefact versions  
4. Separate explicit request required before phase 020  

## What upload mode does not require

`hermes` CLI, `gh`, Docker, sudo, systemd, GitHub/MCP bridges, shared
Roomote filesystem, or automatic skill discovery.

## Provenance

See `PROVENANCE.md`.
