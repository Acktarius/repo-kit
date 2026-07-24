---
name: react-standards
description: Apply React app structure, component conventions, and testing guidance for this repo.
---

# React standards

Use this skill when adding or refactoring React components, hooks, routes, or tests.

## Structure

- Prefer a clear `src/` layout (`components/`, `hooks/`, `pages/` or `routes/`, `lib/`).
- Keep one primary responsibility per component file.
- Colocate small helpers with the feature; share only when reused.

## Components

- Prefer function components.
- Keep props explicit and typed.
- Avoid unnecessary wrappers, cards, or layout chrome unless interaction requires it.
- Prefer composition over deep prop drilling; introduce context only when many consumers need the same state.

## State and effects

- Prefer local state first; lift only when needed.
- Keep effects focused; clean up subscriptions and timers.
- Follow the project's React Compiler / memo guidance — do not add `useMemo`/`useCallback` by default unless the repo already relies on them.

## Testing

- Prefer testing user-visible behavior over implementation details.
- Cover critical paths and failure states.
- Keep tests next to the feature or under a consistent `__tests__` / `*.test.tsx` convention.
