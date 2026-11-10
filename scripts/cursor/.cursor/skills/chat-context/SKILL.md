---
name: chat-context
description: >-
  Summarize an active coding session into compact structured handoff context
  under .repo-kit/chat/. Use when the user asks to save chat context, write a
  session handoff, checkpoint progress, or prepare continuation for a future
  session.
---

# Chat context

Capture the active session into compact, continuation-focused context. Do not
dump the raw transcript.

## Output locations

| File | Role |
|------|------|
| `.repo-kit/chat/current.json` | Machine-readable state |
| `.repo-kit/chat/current.md` | Human-readable handoff |
| `.repo-kit/chat/sessions/` | Optional timestamped snapshots |
| `.repo-kit/chat/decisions/` | Optional durable decision notes |
| `.repo-kit/chat/archive/` | Optional archived handoffs |

Templates (schema reference):

- [templates/current.json](templates/current.json)
- [templates/current.md](templates/current.md)

Layout details: [references/layout.md](references/layout.md)

## Capture fields

Always capture:

- title
- timestamp
- goal
- constraints
- decisions made
- unresolved questions
- relevant files
- relevant commands
- artifacts
- next step
- notes
- tags

## Rules

- Keep summaries compact and continuation-focused.
- Do not dump raw transcript.
- Preserve decisions, constraints, file paths, and next actions.
- Write machine-readable state to `current.json`.
- Write human-readable handoff to `current.md`.
- Create optional timestamped snapshots in `.repo-kit/chat/sessions/`.

## Privacy — never log

**Never write any of the following into `.repo-kit/chat/` files** (including
`current.*`, `sessions/`, `decisions/`, `archive/`), confirmations, or notes:

- Secrets: passwords, API keys, tokens, credentials, private keys, connection
  strings with credentials, `.env` values, auth headers/cookies
- Phone numbers
- Email addresses
- IP addresses (IPv4 or IPv6)

If the session needs the *fact* that something sensitive was used, redact it:
write a placeholder (e.g. `[REDACTED_TOKEN]`, `[REDACTED_EMAIL]`) or refer by
role/path only (`"API key from CI secret"`, `".env:DATABASE_URL"`). Strip
sensitive values from copied commands, logs, URLs, and error messages before
writing. When merging an existing handoff, remove any of the above if present.

## Workflow

1. Read existing `.repo-kit/chat/current.json` / `.repo-kit/chat/current.md`
   when present; merge forward rather than discarding prior handoff unless the
   user asks to reset.
2. Infer fields from the conversation and repo evidence (paths, commands run,
   decisions stated). Prefer concrete paths and short bullets. Scrub per
   **Privacy — never log** before writing.
3. Set `timestamp` to ISO-8601 UTC (e.g. `2026-07-24T21:08:00Z`).
4. Write `.repo-kit/chat/current.json` using the template schema (camelCase keys).
5. Write `.repo-kit/chat/current.md` using the template section layout.
6. When checkpointing or the user asks to snapshot, also copy both files to:
   `.repo-kit/chat/sessions/YYYYMMDD-HHMMSS-<slug>.json` and `.md`
   (`slug` from a short kebab-case title fragment).
7. Reply with a one-line confirmation: title, next step, and paths written
   (still no secrets/PII).

## Compactness

- One sentence (or short bullet list) per field group.
- `relevantFiles` / `relevantCommands`: only what the next session needs.
- `decisionsMade`: outcome + why in one line each.
- `nextStep`: a single actionable sentence.
