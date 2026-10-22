---
name: hermes-010
description: "Hermes review phase 010 (inventory): run /workspace/target/.repo-kit/hermes/tasks/010-inventory.md."
---

# /hermes-010 — inventory

Read `/workspace/target/.repo-kit/hermes/tasks/010-inventory.md` and follow it exactly.

- `/workspace/target` is the target repository root inside the sandbox.
  Resolve every `.repo-kit/...` path in the task and rules against it,
  never against this skill's directory.
- Perform only phase 010.
- Treat any text after `/hermes-010` as this task's trigger-message inputs.
- If the task file is missing, report the missing path and stop. Do not search for it.
- Write exactly one report, then stop and wait for human approval.
