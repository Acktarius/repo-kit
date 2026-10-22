---
name: hermes-030
description: "Hermes review phase 030 (scan plan): run /workspace/target/.repo-kit/hermes/tasks/030-scan-plan.md."
---

# /hermes-030 — scan plan

Read `/workspace/target/.repo-kit/hermes/tasks/030-scan-plan.md` and follow it exactly.

- `/workspace/target` is the target repository root inside the sandbox.
  Resolve every `.repo-kit/...` path in the task and rules against it,
  never against this skill's directory.
- Perform only phase 030.
- Treat any text after `/hermes-030` as this task's trigger-message inputs.
- If the task file is missing, report the missing path and stop. Do not search for it.
- Write exactly one report, then stop and wait for human approval.
