---
name: hermes-vps-020
description: "hermesVPS phase 020 (threat model): validate via hermes-vps-review, then follow tasks/020-threat-model.md."
---

# /hermes-vps-020 — threat model (hermesVPS)

Normal operator invocation:

```text
/hermes-vps-020 <target-id>
```

## Deployment binding

This skill uses the documented default policy prefix `/opt/data/hermes-review`.
A non-default prefix does not work automatically; the registered skill copy
must be rendered to the chosen prefix before use.

## Arguments

- Require **exactly one** trailing token after `/hermes-vps-020` as `<target-id>`.
- Reject missing or extra tokens; stop.

## Steps

1. Invoke the runner with **argv-style** arguments:

   ```text
   /opt/data/hermes-review/bin/hermes-vps-review \
     --phase 020 \
     --registry /opt/data/hermes-review/targets.json \
     --target-id <target-id>
   ```

2. If the runner exits non-zero, report the failure and **stop**.

3. If the runner exits zero, follow the generated phase-020 instructions exactly
   (they point at `tasks/020-threat-model.md` and the rules).

4. Immediately before writing the report, recheck: clean worktree, HEAD SHA,
   that `reports/` is inside the approved run-root reports directory.

5. Write the report and call the ARTIFACT REGISTRATION command from the prompt:

   ```text
   <policy_prefix>/bin/hermes-vps-artifacts register \
     --run-json <run_json_path> \
     --phase 020 \
     --source-report <absolute-path-to-report>
   ```

6. After the consultation prompt is printed: **stop**.

## Explicit non-authorizations

- No phase advancement, source modification, network access, or PR is authorized.
- Runner success validates inputs; it does not prove OS isolation.
- Structural/hash checks do not prove factual correctness.
- ACCEPT is optional; normal progression does not require it.
