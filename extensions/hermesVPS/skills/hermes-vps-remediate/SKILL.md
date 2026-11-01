---
name: hermes-vps-remediate
description: "hermesVPS findings export: regenerate and register the consolidated findings handoff (it is generated automatically after the last phase-070 assessment)."
---

# /hermes-vps-remediate — generate findings export (hermesVPS)

```text
/hermes-vps-remediate <target-id>
```

The export is generated automatically when the last phase-070 assessment for
the current run is registered.  Use this skill to regenerate it afterwards,
for example to include phase-080 plans registered since then.

## Steps

1. Identify the `run.json` path for `<target-id>` from the registry:
   ```text
   /opt/data/hermes-review/targets.json
   ```

2. Run `generate-findings`:
   ```text
   /opt/data/hermes-review/bin/hermes-vps-artifacts generate-findings \
     --run-json <run_json_path>
   ```

3. If the command exits non-zero, report the failure and **stop**.

4. Read the printed findings handoff prompt.  If the export is **PARTIAL**
   (missing or stale candidate assessments), do not describe it as a complete
   remediation handoff.  Return the partial export to the operator with the
   list of missing assessments.

5. If the export is **COMPLETE**, attach or paste the contents of the findings
   file as directed by the handoff prompt.

6. **Stop**.  Do not start remediation without a separate explicit human request.

## Explicit non-authorizations

- Does not start phase 080 automatically.
- Does not modify the source repository or findings store.
- Does not commit, push, or create a PR.
- A COMPLETE export does not authorize remediation; that requires explicit request.
