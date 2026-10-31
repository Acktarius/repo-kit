---
name: hermes-vps-070
description: "hermesVPS phase 070 (reviewed findings): validate via hermes-vps-review for one candidate, then follow tasks/070-reviewed-findings.md."
---

# /hermes-vps-070 — reviewed findings (hermesVPS)

```text
/hermes-vps-070 <target-id> <candidate_id>
```

`<candidate_id>` is required (e.g. `C-001`).  Each candidate requires a
separate invocation.  Revising one candidate does not affect others.

## Steps

1. ```text
   /opt/data/hermes-review/bin/hermes-vps-review \
     --phase 070 \
     --registry /opt/data/hermes-review/targets.json \
     --target-id <target-id> \
     --trigger-input <candidate_id>
   ```
2. Non-zero exit → report and stop.
3. Follow `tasks/070-reviewed-findings.md` for the named candidate exactly.
4. Write:
   - One Markdown report
   - One JSON finding-record payload (`finding-record.schema.json`);
     `candidate_id` must match `<candidate_id>`
5. Register **both** with `--subject-id <candidate_id>`:
   ```text
   <policy_prefix>/bin/hermes-vps-artifacts register \
     --run-json <run_json_path> --phase 070 \
     --subject-id <candidate_id> \
     --source-report <report.md> \
     --payload-json <finding-record.json>
   ```
6. After consultation prompt: **stop**.

## Explicit non-authorizations

- No SG-NNN ID allocation, findings store writes, source modification, or PR.
- `assessment_disposition` is distinct from canonical `status`; do not conflate them.
- Never set `status = "fixed"` because remediation is planned.
- Cross-subject supersession is rejected by the helper.
- ACCEPT is optional.
