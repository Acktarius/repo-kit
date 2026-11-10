# Step-by-step guidance

Ops/deploy workflow for Cursor agents in this repository.

## When it applies

User phrases like:

- “step by step”
- “one step at a time”
- “wait for my confirmation”
- “don’t dump all steps”

## Agent behavior

| Do | Don’t |
|----|--------|
| One numbered step per message | Full runbooks in one reply |
| Wait for `go` / `done` / `ok` / `continue` or pasted output | Assume readiness for step N+1 |
| Brief read of pasted output, then next step | Extra “optional” steps in the same message |

## Continue tokens

- `go`, `done`, `ok`, `continue` — proceed to next step
- Pasted command output — treat as step complete; diagnose if needed, then next step only

## Commands

Unless the user asked the agent to run commands, **suggest** commands for them to paste.

## Rule file

Enforced via `.cursor/rules/step-by-step.mdc` (`alwaysApply: true`).
