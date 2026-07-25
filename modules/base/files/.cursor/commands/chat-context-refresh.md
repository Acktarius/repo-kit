# chat-context-save

Create or update the repo-local chat context handoff.

Read `.cursor/skills/chat-context/SKILL.md` and follow it.

## Tasks

1. Read the recent chat and current task context.
2. Summarize only the durable, high-signal information needed to resume work.
3. Update `.chat/current.json` using the project schema.
4. Update `.chat/current.md` as the human-readable summary.
5. Create a timestamped snapshot in `.chat/sessions/` if this is a milestone, branch switch, or significant decision point.

## Rules

- Do not dump raw transcript.
- Keep only goal, constraints, decisions made, unresolved questions, relevant files, relevant commands, artifacts, next step, notes, and tags.
- Prefer compact wording.
- Preserve exact file paths and commands when known.
- If `.chat/` does not exist, instruct the user to run project init or create it safely if project conventions allow.
