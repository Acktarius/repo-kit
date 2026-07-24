# repo-kit

Portable starter kit for Cursor-based repository standards.

Copy selected **modules** into a target repo. repo-kit is the source of truth; targets commit copied files (no symlinks).

## Layout

```text
repo-kit/
  modules/
    base/
    typescript/     # owns package-preferences
    react/
    security/
    cpp11/
    rust/
  scripts/
    init.sh
    list-modules.sh
    sync-cursor.sh
  catalog/
    modules.md
  README.md
```

Each module has `files/` (ready to copy) and `manifest.sh` (name, description, depends, conflicts).

## Usage

List modules:

```bash
./scripts/list-modules.sh
```

Initialize a project (resolves dependencies, detects conflicts):

```bash
./scripts/init.sh /path/to/project --typescript --security
./scripts/init.sh /path/to/project --react --security
./scripts/init.sh /path/to/project --cpp11
./scripts/init.sh /path/to/project --rust --security
./scripts/init.sh /path/to/project --base --force
```

Sync only Cursor assets (`.cursor/`) into an existing project:

```bash
./scripts/sync-cursor.sh /path/to/project --typescript --security
./scripts/sync-cursor.sh /path/to/project --react --force
```

Existing files are **skipped** unless `--force` is passed.

## Module lanes

| Module | Depends | Conflicts | Notes |
|--------|---------|-----------|-------|
| `base` | — | — | Neutral scaffolding only |
| `typescript` | `base` | `cpp11`, `rust` | package-preferences, Biome, tsconfig, CI |
| `react` | `typescript` | `cpp11`, `rust` | React conventions skill + docs |
| `security` | `base` | — | Portable hardening plan, review, findings, triage, and CI workflow |
| `cpp11` | `base` | `typescript`, `react`, `rust` | clang-format, CMake |
| `rust` | `base` | `typescript`, `react`, `cpp11` | rustfmt + Cursor guidance |

`--react` pulls in `typescript` and `base` automatically (including package-preferences).

## Recommended workflow

1. Keep this repo as the source of truth.
2. Copy assets into each target repository with `init.sh` or `sync-cursor.sh`.
3. Commit copied files in each target repo.
4. Update the `.npmrc` placeholder (from `typescript`) with your exact policy before broad reuse.

## Catalog

See [catalog/modules.md](catalog/modules.md).
