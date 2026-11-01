---
name: hermes-vps-080
description: "hermesVPS phase 080 gate 1 (remediation plan with provenance): validate via hermes-vps-review for one candidate, build provenance payload, follow tasks/080-remediate-and-retest.md, register with --payload-json."
---

# /hermes-vps-080 — remediation plan, gate 1 (hermesVPS)

```text
/hermes-vps-080 <target-id> <candidate_id>
```

`<candidate_id>` is required (e.g. `C-001`): the phase-060 candidate whose
phase-070 assessment is confirmed, suspected, or needs-investigation.
One candidate per invocation.  This implements gate 1 (remediation plan)
only. Gates 2–5 require separate explicit authorization.

## Steps

1. ```text
   /opt/data/hermes-review/bin/hermes-vps-review \
     --phase 080 \
     --registry /opt/data/hermes-review/targets.json \
     --target-id <target-id> \
     --trigger-input <candidate_id>
   ```
2. Non-zero exit → report and stop.
3. Resolve provenance inputs from manifest:
   - `selected_by_phase["040"]` → intel artifact ID and its `payload_sha256`
   - `selected_by_subject["070"][candidate_id]` → assessed finding artifact ID and its `payload_sha256`
4. Assess intel freshness (default threshold: 24h) from the phase-040 payload.
5. Build `plan-080-<candidate_id>.json` provenance payload per `tasks/080-remediate-and-retest.md`.
6. Follow `tasks/080-remediate-and-retest.md` for the named candidate exactly.
7. Write one Markdown report.
8. Register with `--subject-id <candidate_id>` and `--payload-json`:
   ```text
   <policy_prefix>/bin/hermes-vps-artifacts register \
     --run-json <run_json_path> --phase 080 \
     --subject-id <candidate_id> \
     --source-report <report.md> \
     --payload-json <plan-080-<candidate_id>.json>
   ```
9. After consultation prompt: **stop**.

## Explicit non-authorizations

- Do NOT apply patches, edit source, run tests, update findings, commit, push, or run CI.
- Gates 2–5 require separate authorization; they are not performed here.
- A remediation plan does not change the finding status to `fixed`.
- Cross-subject supersession is rejected by the helper.
- ACCEPT is optional.
