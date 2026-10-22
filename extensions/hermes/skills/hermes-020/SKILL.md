---
name: hermes-020
description: "Hermes review phase 020 (threat model): run /workspace/target/.repo-kit/hermes/tasks/020-threat-model.md."
---

# /hermes-020 — threat model

Read `/workspace/target/.repo-kit/hermes/tasks/020-threat-model.md` and follow it exactly.

- `/workspace/target` is the target repository root inside the sandbox.
  Resolve every `.repo-kit/...` path in the task and rules against it,
  never against this skill's directory.
- Perform only phase 020.
- Treat any text after `/hermes-020` as this task's trigger-message inputs.
- If the task file is missing, report the missing path and stop. Do not search for it.
- Write exactly one report, then stop and wait for human approval.
