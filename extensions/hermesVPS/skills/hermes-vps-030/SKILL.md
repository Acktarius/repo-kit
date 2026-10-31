---
name: hermes-vps-030
description: "hermesVPS phase 030 (scanner plan): validate via hermes-vps-review, then follow tasks/030-scan-plan.md."
---

# /hermes-vps-030 — scanner selection and execution plan (hermesVPS)

```text
/hermes-vps-030 <target-id>
```

## Steps

1. ```text
   /opt/data/hermes-review/bin/hermes-vps-review \
     --phase 030 \
     --registry /opt/data/hermes-review/targets.json \
     --target-id <target-id>
   ```
2. Non-zero exit → report and stop.
3. Follow `tasks/030-scan-plan.md` exactly.
4. Write report, then register:
   ```text
   <policy_prefix>/bin/hermes-vps-artifacts register \
     --run-json <run_json_path> --phase 030 --source-report <path>
   ```
5. After consultation prompt: **stop**.

## Explicit non-authorizations

- No scanners are installed or run in this phase (plan only).
- No phase advancement, source modification, network access, or PR.
- ACCEPT is optional.
