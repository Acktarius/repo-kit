---
name: hermes-040
description: "Hermes review phase 040 (dependency advisories): run /workspace/target/.repo-kit/hermes/tasks/040-dependency-advisories.md."
---

# /hermes-040 — dependency advisories

Read `/workspace/target/.repo-kit/hermes/tasks/040-dependency-advisories.md` and follow it exactly.

- `/workspace/target` is the target repository root inside the sandbox.
  Resolve every `.repo-kit/...` path in the task and rules against it,
  never against this skill's directory.
- Perform only phase 040.
- Treat any text after `/hermes-040` as this task's trigger-message inputs.
- If the task file is missing, report the missing path and stop. Do not search for it.
- Write exactly one report, then stop and wait for human approval.
