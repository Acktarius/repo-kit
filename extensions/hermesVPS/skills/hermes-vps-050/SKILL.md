---
name: hermes-vps-050
description: "hermesVPS phase 050 (source review): validate via hermes-vps-review for one review priority, then follow tasks/050-source-review.md."
---

# /hermes-vps-050 — source and configuration review (hermesVPS)

```text
/hermes-vps-050 <target-id> <priority_area>
```

`<priority_area>` is required: a short identifier (e.g. `auth-module`) naming
one prioritized review area from the phase-020 report.  One priority per
invocation; each priority is registered under its own subject.

## Steps

1. ```text
   /opt/data/hermes-review/bin/hermes-vps-review \
     --phase 050 \
     --registry /opt/data/hermes-review/targets.json \
     --target-id <target-id> \
     --trigger-input <priority_area>
   ```
2. Non-zero exit → report and stop.
3. Follow `tasks/050-source-review.md` exactly for that one review priority.
4. Write report, then register:
   ```text
   <policy_prefix>/bin/hermes-vps-artifacts register \
     --run-json <run_json_path> --phase 050 \
     --subject-id <priority_area> \
     --source-report <path>
   ```
5. After consultation prompt: **stop**.

## Explicit non-authorizations

- Scanner execution requires explicit trigger-message approval.
- One review priority per invocation; a separate invocation is required for each additional priority.
- No source modification, PR, or phase advancement.
- ACCEPT is optional.
