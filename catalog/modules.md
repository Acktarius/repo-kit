# Module catalog

Human-readable mirror of `modules/*/manifest.sh`.

## base

- **Description:** Minimal repository scaffolding
- **Depends:** —
- **Conflicts:** —
- **Provides:** `docs/repo-kit.md`, `docs/.gitkeep`

## typescript

- **Description:** TypeScript/Node setup with package-preferences, Biome, scripts, docs, and CI
- **Depends:** `base`
- **Conflicts:** `cpp11`, `rust`
- **Provides:**
  - `.cursor/commands/package-preferences.md`
  - `.cursor/skills/package-preferences/SKILL.md`
  - `.biome.json`, `.gitattributes`, `.npmrc`, `tsconfig.json`
  - `.github/workflows/ci-check.yml`
  - `docs/typescript-standards.md`

## react

- **Description:** React conventions and React-specific Cursor skills
- **Depends:** `typescript` (and thus `base`)
- **Conflicts:** `cpp11`, `rust`
- **Provides:**
  - `.cursor/skills/react-standards/SKILL.md`
  - `docs/react-standards.md`

## security

- **Description:** Repo-aware security planning, review, findings, triage, remediation, and CI
- **Depends:** `base`
- **Conflicts:** —
- **Provides:**
  - `.cursor/commands/00-security-plan-hardening.md` through `05-security-triage-findings.md`
  - `.cursor/skills/security-hardening/SKILL.md`
  - `.cursor/rules/20-security-planner.mdc`, `30-security-reviewer.mdc`, and `40-security-triage.mdc`
  - `.github/workflows/security-check.yml`
  - `security/` threat-model, findings, accepted-risk, schema, and template workflow

## cpp11

- **Description:** C++11 scaffolding, clang-format, CMake, and Cursor guidance
- **Depends:** `base`
- **Conflicts:** `typescript`, `react`, `rust`
- **Provides:**
  - `.cursor/commands/cpp11-setup.md`
  - `.cursor/skills/cpp11-standards/SKILL.md`
  - `.clang-format`, `CMakeLists.txt`
  - `docs/cpp11-guidelines.md`

## rust

- **Description:** Rust scaffolding, rustfmt, and Cursor guidance
- **Depends:** `base`
- **Conflicts:** `typescript`, `react`, `cpp11`
- **Provides:**
  - `.cursor/commands/rust-setup.md`
  - `.cursor/skills/rust-standards/SKILL.md`
  - `rustfmt.toml`
  - `docs/rust-guidelines.md`
