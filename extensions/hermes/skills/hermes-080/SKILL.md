---
name: hermes-080
description: "Hermes review phase 080 (remediate and retest): run /workspace/target/.repo-kit/hermes/tasks/080-remediate-and-retest.md."
---

# /hermes-080 — remediate and retest

Read `/workspace/target/.repo-kit/hermes/tasks/080-remediate-and-retest.md` and follow it exactly.

- `/workspace/target` is the target repository root inside the sandbox.
  Resolve every `.repo-kit/...` path in the task and rules against it,
  never against this skill's directory.
- Perform only phase 080.
- Treat any text after `/hermes-080` as this task's trigger-message inputs,
  for example the finding ID.
- If the task file is missing, report the missing path and stop. Do not search for it.
- Write exactly one report, then stop and wait for human approval.
