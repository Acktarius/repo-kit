---
name: biome-review
description: >-
  Review Biome diagnostics for a file and apply only safe, intention-preserving
  fixes after code-aware inspection. Use when the user asks to fix Biome lint
  issues, clean diagnostics on the current file, or review Biome findings.
---

# Biome review

For the current file:

1. Run:
   `npx biome lint <file>`

2. Read the diagnostics and inspect the actual code before editing.

3. Apply fixes carefully, case by case:
   - Remove unused imports if they are clearly dead.
   - Remove unused variables only if they are genuinely dead code and not part of work-in-progress structure.
   - For unused parameters, prefer renaming to `_param` **only** when the parameter must be kept for a required callback arity, interface contract, middleware signature, or destructuring symmetry where removing it would change behavior or break a type contract. In all other cases, remove the parameter or fix the underlying pattern (e.g. collapse explicit Promise constructor antipatterns, use optional catch binding `catch { }` instead of `catch (_e) { }`).
   - Replace `==` with `===` and `!=` with `!==` only when strict equality preserves the intended behavior.
   - Preserve patterns like `value == null` when the intent is to match both `null` and `undefined`.
   - Prefer the smallest possible edit.
   - If intent is ambiguous, do not change the code; instead, explain the ambiguity briefly.
   - Do not perform unrelated refactors.
   - Do not run `npx biome lint <file> --write`.

4. After making changes, run:
   `npx biome lint <file>`

5. If diagnostics remain:
   - Apply another careful pass only for obvious, safe fixes, or
   - Stop and report which findings need manual judgment.

## Editing policy

- Keep runtime behavior unchanged unless the lint issue clearly indicates a bug.
- Keep signatures stable unless a parameter is unquestionably unnecessary.
- Explain each change briefly in terms of safety and intent.
- Bias toward under-fixing rather than over-fixing.
