---
name: hermes-050
description: "Hermes review phase 050 (source review): run /workspace/target/.repo-kit/hermes/tasks/050-source-review.md."
---

# /hermes-050 — source review

Read `/workspace/target/.repo-kit/hermes/tasks/050-source-review.md` and follow it exactly.

- `/workspace/target` is the target repository root inside the sandbox.
  Resolve every `.repo-kit/...` path in the task and rules against it,
  never against this skill's directory.
- Perform only phase 050.
- Treat any text after `/hermes-050` as this task's trigger-message inputs.
- If the task file is missing, report the missing path and stop. Do not search for it.
- Write exactly one report, then stop and wait for human approval.
