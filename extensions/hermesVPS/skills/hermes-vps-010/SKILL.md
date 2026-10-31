---
name: hermes-vps-010
description: "hermesVPS phase 010 (inventory): resolve an operator registry target, validate via hermes-vps-review, then follow tasks/010-inventory.md."
---

# /hermes-vps-010 — inventory (hermesVPS)

Normal operator invocation:

```text
/hermes-vps-010 <target-id>
```

Example: `/hermes-vps-010 repoX`

## Deployment binding (not universal)

This skill body uses the **documented default policy prefix**:

```text
/opt/data/hermes-review
```

That path is a deployment binding for the common upload layout. It is **not**
discovered from this skill’s install directory and is **not** overridden by
undocumented environment variables. If the operator installs under another
prefix, the registered skill copy must be rendered or edited to that prefix
before use. A non-default prefix does **not** work automatically.

## Arguments

- Require **exactly one** trailing token after `/hermes-vps-010` as `<target-id>`.
- Reject missing or extra tokens; stop.
- Treat `<target-id>` as a **registry key only**. Never build source or run
  paths by concatenating the identifier.
- Do not invent or increment a report version.

## Steps

1. Using the terminal tool, invoke the runner with **argv-style** arguments
   (separate arguments; do not `eval`; do not embed the target id in an
   interpolated shell script string). Equivalent command:

   ```text
   /opt/data/hermes-review/bin/hermes-vps-review \
     --registry /opt/data/hermes-review/targets.json \
     --target-id <target-id>
   ```

   Pass `<target-id>` as its own argv element after `--target-id`.

2. If the runner exits non-zero, report the failure and **stop**. Do not
   perform inventory work, invent paths, or write a report.

3. If the runner exits zero, follow the **generated** phase-010 instructions
   exactly (they point at `tasks/010-inventory.md` and the rules). Rules and
   tasks remain the source of truth; do not substitute remembered methodology.

4. Before writing the report, recheck clean worktree and HEAD SHA
   (preflight can race with later filesystem changes).

5. Write only the approved report path from the prompt. Then **stop**.

## Explicit non-authorizations

- Runner success validates inputs; it does **not** prove OS isolation.
- No source modification, scanner, build, test, install, or network
  permission is implied beyond the approved read-only inventory scope.
- No phase advancement, publication, Roomote invocation, GitHub action, or
  pull request is authorized.
- Reading or installing this skill does **not** execute a phase.

## Missing inputs

If the runner, registry, bootstrap, or task files are inaccessible, stop and
name the gap. Do not search for substitutes.
