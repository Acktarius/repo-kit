---
name: hermes-vps-060
description: "hermesVPS phase 060 (validate and triage): validate via hermes-vps-review, then follow tasks/060-validate-and-triage.md."
---

# /hermes-vps-060 — validate and triage (hermesVPS)

```text
/hermes-vps-060 <target-id>
```

## Steps

1. ```text
   /opt/data/hermes-review/bin/hermes-vps-review \
     --phase 060 \
     --registry /opt/data/hermes-review/targets.json \
     --target-id <target-id>
   ```
2. Non-zero exit → report and stop.
3. Follow `tasks/060-validate-and-triage.md` exactly.
4. Write:
   - One Markdown report
   - One JSON triage payload (`triage-payload.schema.json`), assigning stable candidate_ids
5. Register **both** with:
   ```text
   <policy_prefix>/bin/hermes-vps-artifacts register \
     --run-json <run_json_path> --phase 060 \
     --source-report <report.md> \
     --payload-json <triage-payload.json>
   ```
6. After consultation prompt: **stop**.

## Explicit non-authorizations

- No SG-NNN ID allocation, findings store modification, or PR.
- No exploit execution or target code execution.
- ACCEPT is optional.
