---
name: hermes-060
description: "Hermes review phase 060 (validate and triage): run /workspace/target/.repo-kit/hermes/tasks/060-validate-and-triage.md."
---

# /hermes-060 — validate and triage

Read `/workspace/target/.repo-kit/hermes/tasks/060-validate-and-triage.md` and follow it exactly.

- `/workspace/target` is the target repository root inside the sandbox.
  Resolve every `.repo-kit/...` path in the task and rules against it,
  never against this skill's directory.
- Perform only phase 060.
- Treat any text after `/hermes-060` as this task's trigger-message inputs.
- If the task file is missing, report the missing path and stop. Do not search for it.
- Write exactly one report, then stop and wait for human approval.
