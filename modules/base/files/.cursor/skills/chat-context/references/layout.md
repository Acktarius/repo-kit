# `.chat/` layout

Project-local handoff store created by `scripts/init.sh` when the `base`
module is installed.

```text
.chat/
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
