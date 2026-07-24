---
name: package-preferences
description: Apply Node/TypeScript package manager, Biome, scripts, and typecheck preferences for this repo.
---

# Package preferences

Use this skill when adding dependencies, editing `package.json`, configuring lint/format, or setting up TypeScript checks.

## Package manager

- Honor `.npmrc` as the policy file for this repo.
- Treat `.npmrc` placeholders as incomplete until filled with the org's exact registry/auth/engine policy.
- Prefer a single package manager per repo; do not mix lockfiles.

## Tooling defaults

- **Format / lint:** Biome via `.biome.json`. Prefer `biome check` / `biome format` over adding ESLint/Prettier unless the project already depends on them.
- **Types:** Keep `tsconfig.json` strict. Prefer `tsc --noEmit` for typecheck.
- **Scripts:** Expect and maintain:
  - `lint` — Biome check (or project equivalent)
  - `typecheck` — `tsc --noEmit`
  - `test` — when tests exist

## Adding dependencies

- Prefer well-maintained packages with clear licenses.
- Pin ranges consistently with existing `package.json` style.
- Do not commit secrets, tokens, or private registry credentials into `.npmrc` examples.

## Out of scope

- React-specific structure (see `react-standards` when that skill is present).
- Security review of dependencies (see `security-review` when that skill is present).
