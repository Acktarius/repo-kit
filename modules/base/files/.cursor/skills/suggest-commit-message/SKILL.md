---
name: suggest-commit-message
description: >-
  Suggest a Conventional Commits message from staged git changes. Use when the
  user asks for a commit message, wants help committing staged files, mentions
  commitlint, or is preparing a PR commit.
---

# Suggest commit message

Analyze **staged** changes only and propose a message that passes this repo's
commitlint (`commitlint.config.mjs`) when present.

## Gather context

Run in parallel:

```bash
git status --short
git diff --cached --stat
git diff --cached
```

If nothing is staged, say so and stop — do not suggest a message for unstaged work.

Read `commitlint.config.mjs` when present. Default allowed types (override from
config when it differs):

`feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`, `build`, `revert`

Rules:

- Header: `<type>: <subject>` (optional scope: `<type>(scope): <subject>`)
- Subject max **100** characters, imperative mood, no trailing period
- **Blank line** between header and body
- Body bullets use `-`, not `*`

## Pick the type

| Type | When |
|------|------|
| `feat` | New user-facing behaviour |
| `fix` | Bug fix |
| `refactor` | Behaviour-preserving restructure |
| `test` | Tests only |
| `docs` | Documentation only |
| `chore` | Tooling, deps, misc maintenance |
| `ci` | CI / workflow changes |
| `build` | Build system or bundler |
| `perf` | Performance improvement |
| `revert` | Reverts a prior commit |

Prefer one type for the whole changeset. If staged changes mix unrelated concerns,
say so and suggest splitting the commit.

## Output format

Reply with **exactly** this structure (fill in content; omit empty sections):

```markdown
<type>: <subject>

short version:
- <what changed, outcome-focused, no file paths>
- …

long version:
- in `<path/to/file>`: <what changed in this file>
- in `<path/to/file2>`: <what changed in this file>
```

Then add a ready-to-paste block for the actual commit (commitlint-valid):

```markdown
## Ready to commit

\`\`\`
<type>: <subject>

- <bullet from short version>
- …
\`\`\`
```

The **Ready to commit** block is header + blank line + short-version bullets only
(no "short version"/"long version" labels). Keep body concise (3–6 bullets).

## Quality bar

- Subject states **why/outcome**, not a file list
- Short version: user-visible or architectural summary
- Long version: one bullet per staged file (merge trivial files only when obvious)
- Do **not** invent changes not present in the diff
- Do **not** run `git commit` unless the user explicitly asks

## Example

Staged: QR scan button on address fields in address-book and messages pages.

```markdown
feat: add QR scan button to wallet address fields

short version:
- add camera QR scan to address inputs on address book and messages compose
- show scan button below 1024px (lg:hidden) with input padding for the icon
- rename scan handlers to applyScannedDraft for consistency across pages

long version:
- in `app/(wallet)/wallet/address-book/page.tsx`: wrap address input with AddressQrScanButton and applyScannedDraft
- in `app/(wallet)/wallet/messages/page.tsx`: same scan UI on compose recipient field, wired to recipient state
- in `app/(wallet)/wallet/send/page.tsx`: rename applyScannedSendDraft to applyScannedDraft

## Ready to commit

\`\`\`
feat: add QR scan button to wallet address fields

- add camera QR scan to address inputs on address book and messages compose
- show scan button below 1024px with input padding for the icon
- rename scan handlers to applyScannedDraft across send, messages, and address book
\`\`\`
```
