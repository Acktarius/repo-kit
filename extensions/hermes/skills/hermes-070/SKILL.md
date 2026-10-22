---
name: hermes-070
description: "Hermes review phase 070 (reviewed findings): run /workspace/target/.repo-kit/hermes/tasks/070-reviewed-findings.md."
---

# /hermes-070 — reviewed findings

Read `/workspace/target/.repo-kit/hermes/tasks/070-reviewed-findings.md` and follow it exactly.

- `/workspace/target` is the target repository root inside the sandbox.
  Resolve every `.repo-kit/...` path in the task and rules against it,
  never against this skill's directory.
- Perform only phase 070.
- Treat any text after `/hermes-070` as this task's trigger-message inputs,
  for example the candidate ID.
- If the task file is missing, report the missing path and stop. Do not search for it.
- Write exactly one report, then stop and wait for human approval.
