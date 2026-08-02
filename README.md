# repo-kit

Portable starter kit for Cursor-based repository standards.

Copy selected **modules** into a target repo. repo-kit is the source of truth; targets commit copied files (no symlinks).

Optional **extensions** (via `--ext`) install non-module tooling such as Continue, OpenSpec, and Forgekit.

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
  extensions/
    continue/       # Continue rules/prompts + ai-*.sh (not a module)
    openspec/       # OpenSpec CLI + project init
    forge/          # Forgekit (depends on openspec)
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

List modules and extensions:

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
./scripts/init.sh /path/to/project --ext continue
./scripts/init.sh /path/to/project --ext openspec
./scripts/init.sh /path/to/project --ext forge
./scripts/init.sh /path/to/project --typescript --ext continue
```

Sync only Cursor assets (`.cursor/`) into an existing project (extensions still install fully when `--ext` is passed):

```bash
./scripts/sync-cursor.sh /path/to/project --typescript --security
./scripts/sync-cursor.sh /path/to/project --react --force
./scripts/sync-cursor.sh /path/to/project --ext continue
./scripts/sync-cursor.sh /path/to/project --ext forge
```

Existing files are **skipped** unless `--force` is passed.

## Extensions

| Extension | Notes |
|-----------|-------|
| `continue` | Checks/prompts for `cn`, `python3`, `grep`, `gh`, `curl`, `rg`; copies `.continue/{rules,prompts}`; copies `ai-*.sh` to `.repo-kit/scripts/` (`ai-commit`, `ai-context`, `ai-dep`, `ai-prompter`, `ai-git-issue`); writes `.repo-kit/bashrc_repokit` and hooks `~/.bashrc` |
| `openspec` | `npm i -g @fission-ai/openspec@latest`; `openspec init --tools cursor` in target if needed |
| `forge` | Depends on `openspec` (always installed first). Then `npm i -g @izkac/forgekit@latest`, `forgekit install --skills forge --agents cursor --openspec --force`, and `forge init --cursor --openspec` in target if needed |

```bash
./scripts/init.sh /path/to/project --ext continue
./scripts/init.sh /path/to/project --ext openspec
./scripts/init.sh /path/to/project --ext forge   # also installs openspec
source ~/.bashrc   # activate PATH + aliases (continue)
```

`--ext forge` always resolves `openspec` first. Re-run project inits with `--force`.

Forgekit: [izkac/forgekit](https://github.com/izkac/forgekit). OpenSpec: [@fission-ai/openspec](https://www.npmjs.com/package/@fission-ai/openspec).

## License

repo-kit is licensed under the [MIT License](LICENSE).

Optional extensions pull in third-party tools with their own licenses:

| Tool | Package | License |
|------|---------|---------|
| Forgekit | [`@izkac/forgekit`](https://www.npmjs.com/package/@izkac/forgekit) | [MIT](https://github.com/izkac/forgekit/blob/main/LICENSE) |
| OpenSpec | [`@fission-ai/openspec`](https://www.npmjs.com/package/@fission-ai/openspec) | [MIT](https://github.com/Fission-AI/OpenSpec/blob/main/LICENSE) |

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
