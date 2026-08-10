# `.repo-kit/chat/` layout

Project-local handoff store created by `scripts/init.sh` when the `base`
module is installed.

```text
.repo-kit/
  version             # installed repo-kit layout version
  chat/
    current.json      # live machine-readable state
    current.md        # live human-readable handoff
    sessions/         # optional timestamped snapshots
    decisions/        # optional durable decision notes
    archive/          # optional archived handoffs
```

## JSON keys

Use camelCase keys matching `templates/current.json`:

`title`, `timestamp`, `goal`, `constraints`, `decisionsMade`,
`unresolvedQuestions`, `relevantFiles`, `relevantCommands`, `artifacts`,
`nextStep`, `notes`, `tags`.

Array fields hold short strings. Prefer paths relative to the repo root.

Never store secrets, phone numbers, email addresses, or IP addresses in any
`.repo-kit/chat/` file. Redact before write; see `SKILL.md` → Privacy.
