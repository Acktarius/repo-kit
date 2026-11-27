---
name: slice
description: >-
  Assess roadmap slice status from docs/roadmap.md, docs/progress.md,
  docs/DECISIONS.md, and chat-context when present. Use when the user runs
  /slice, asks what's next, whatsup, which slice to work on, or names a
  slice to continue.
---

# Slice status

Answer from the project's tracked plan and related notes. Keep the reply short.
Ask which slice to work on when more than one option is open.

## Inputs

Read only what is needed:

| Source | When |
| --- | --- |
| `docs/roadmap.md` | Always — Goals, Status table, and the target slice section(s) |
| `docs/progress.md` | Entries that mention the target slice or the open milestone |
| `docs/DECISIONS.md` | `DEC-XXXX` linked from that slice or named in related progress |
| `.repo-kit/chat/current.md` (and `current.json` if useful) | If present — notes tagged or clearly about that slice |

If a path is missing, say so and continue with what exists.

## Modes

### `/slice` (no number) — what's next

1. From the Status table, list open (⬜) slices in order.
2. Name the smallest incomplete slice that is unblocked (depends-on satisfied).
3. Name the nearest **milestone** called out under Goals (e.g. MVP) and which open slices close it.
4. One short line per candidate: incomplete / in progress / blocked — and what's left (from **Done when** and progress **Next**).
5. End with a question: which slice to work on (suggest the default).

Example shape:

```text
Slice 3 is incomplete (handoff dwell still open).
Slice 4 closes the MVP milestone.
Open before that: 3, then 4.
Which one do you want to work on? (default: 3)
```

### `/slice N` — one slice

1. Read slice **N** in the roadmap (Goal, Depends on, Done so far, Done when, pitfalls).
2. Assess: **not started** / **in progress** / **done** / **blocked** (missing dependency or DEC).
3. What's left: unchecked **Done when** items, minus what progress already recorded.
4. Related notes: pull only matching bullets from progress, DECISIONS, and chat-context.
5. Suggest the immediate next check or task for that slice. If blocked, say what must land first.
6. If the user already asked to work on it, stop after the assessment and the first next step — do not expand into other slices unless they ask.

## Rules

- Prefer the roadmap wording over inventing new requirements.
- Do not dump entire files into the chat; summarize.
- Never invent ✅ — only the Status table and progress evidence count.
- Respect `no-personal-data`: no names, hostnames, emails, or IPs in any write-back.
- If the user finishes work in-session, remind them to tick the roadmap, append progress, and add a DEC when CLI/path/default/format changed (see `.cursor/rules/roadmap-progress.mdc`).
