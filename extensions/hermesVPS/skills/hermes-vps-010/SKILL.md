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

4. Immediately before writing the report, recheck: clean worktree, HEAD SHA,
   that `reports/` and the selected output path still remain inside the
   approved run-root reports directory (not source/policy), and that the
   selected output still does not exist (including dangling symlinks).
   Preflight validation cannot prevent later concurrent filesystem changes.

5. Write the report to any new filename under the REPORTS DIR from the prompt.
   Then call the ARTIFACT REGISTRATION command from the prompt with the absolute
   path of the report you just wrote:

   ```text
   <policy_prefix>/bin/hermes-vps-artifacts register \
     --run-json <run_json_path> \
     --phase 010 \
     --source-report <absolute-path-to-your-report>
   ```

   If registration fails after the report is saved, follow the retry command
   printed by the helper.

6. After the consultation prompt is printed: **stop**.

## Explicit non-authorizations

- Runner success validates inputs; it does **not** prove OS isolation.
- Structural/hash checks by the artifact helper do not prove factual correctness.
- No source modification, scanner, build, test, install, or network
  permission is implied beyond the approved read-only inventory scope.
- No phase advancement, publication, Roomote invocation, GitHub action, or
  pull request is authorized.
- Reading or installing this skill does **not** execute a phase.
- ACCEPT is optional; normal progression does not require it.

## Missing inputs

If the runner, registry, bootstrap, or task files are inaccessible, stop and
name the gap. Do not search for substitutes.
