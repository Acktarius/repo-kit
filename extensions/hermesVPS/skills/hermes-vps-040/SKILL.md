---
name: hermes-vps-040
description: "hermesVPS phase 040 (dependency advisories + vuln intel): validate via hermes-vps-review, collect intelligence, write report, register with payload."
---

# /hermes-vps-040 — dependency identification and advisory matching (hermesVPS)

```text
/hermes-vps-040 <target-id>
```

## Steps

1. ```text
   <policy_prefix>/bin/hermes-vps-review \
     --phase 040 \
     --registry <policy_prefix>/targets.json \
     --target-id <target-id>
   ```
2. Non-zero exit → report and stop.
3. Check trigger message for explicit network-access authorization.
4. Run intelligence collection:
   - If authorized: `<policy_prefix>/bin/hermes-vps-collect-intel --run-json <run_json_path> --output <run_root>/reports/vuln-intel.json --mode live --packages-json <packages-json-path>`
   - If not authorized: `<policy_prefix>/bin/hermes-vps-collect-intel --run-json <run_json_path> --output <run_root>/reports/vuln-intel.json --mode not-authorized`
   - If importing prior evidence: `<policy_prefix>/bin/hermes-vps-collect-intel --run-json <run_json_path> --output <run_root>/reports/vuln-intel.json --mode imported --import-evidence <prior-record-path>`
   - All endpoint URLs are in `lib/hermes_vps_intel.py INTEL_SOURCES` — do not hardcode URLs.
5. Follow `tasks/040-dependency-advisories.md` exactly.
6. Write report, then register:
   ```text
   <policy_prefix>/bin/hermes-vps-artifacts register \
     --run-json <run_json_path> --phase 040 \
     --source-report <path> \
     --payload-json <run_root>/reports/vuln-intel.json
   ```
7. After consultation prompt: **stop**.

## Explicit non-authorizations

- Network access requires explicit trigger-message approval.
- No dependency modification, source modification, or PR.
- ACCEPT is optional.
