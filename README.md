# repo-kit

Portable starter kit for Cursor-based repository standards.

Copy selected **modules** into a target repo. repo-kit is the source of truth; targets commit copied files (no symlinks).

Optional **extensions** (via `--ext`) install non-module tooling such as Continue, OpenSpec, and Forgekit.

Optional **tools** (via `--tool`) install copy-based local tooling under `.repo-kit/tools/` (for example `py-indexer`).

## Layout

```text
repo-kit/
  modules/
    base/
    typescript/     # owns package-preferences
    react/
    security/
    contre-attaque/ # lookback CVE/advisory review (depends on security)
    cpp11/
    rust/
    python/
  extensions/
    continue/       # Continue + Cursor dispatch rules, AGENTS.md, ai-*.sh
    openspec/       # OpenSpec CLI + project init
    forge/          # Forgekit (depends on openspec)
    act/            # nektos/act + local workflow runner script
  tools/
    py-indexer/     # local cross-repo lexical retrieval (CLI + stdio MCP)
  scripts/
    init.sh
    list-modules.sh
    sync-cursor.sh
    migrate.sh
  VERSION
  catalog/
    modules.md
    tools.md
  README.md
```

Each module has `files/` (ready to copy) and `manifest.sh` (name, description, depends, conflicts, and optional `MODULE_PRESERVE` paths that are never overwritten, even with `--force`).

Each tool has `files/` and `manifest.sh` (`TOOL_NAME`, `TOOL_DESC`, optional `TOOL_DEPENDS` / `TOOL_PRESERVE`). Tools are discovered from `tools/*/manifest.sh`.

## Usage

List modules, extensions, and tools:

```bash
./scripts/list-modules.sh
```

Initialize a project (resolves dependencies, detects conflicts):

```bash
./scripts/init.sh /path/to/project --typescript --security
./scripts/init.sh /path/to/project --react --security
./scripts/init.sh /path/to/project --cpp11
./scripts/init.sh /path/to/project --rust --security
./scripts/init.sh /path/to/project --python
./scripts/init.sh /path/to/project --contre-attaque   # also installs security
./scripts/init.sh /path/to/project --base --force
./scripts/init.sh /path/to/project --ext continue
./scripts/init.sh /path/to/project --ext openspec
./scripts/init.sh /path/to/project --ext forge
./scripts/init.sh /path/to/project --ext act
./scripts/init.sh /path/to/project --tool py-indexer
./scripts/init.sh /path/to/project --typescript --ext continue --tool py-indexer
```

Sync only Cursor assets (`.cursor/`) into an existing project (extensions and tools still install fully when `--ext` / `--tool` is passed):

```bash
./scripts/sync-cursor.sh /path/to/project --typescript --security
./scripts/sync-cursor.sh /path/to/project --react --force
./scripts/sync-cursor.sh /path/to/project --python
./scripts/sync-cursor.sh /path/to/project --ext continue
./scripts/sync-cursor.sh /path/to/project --ext forge
./scripts/sync-cursor.sh /path/to/project --ext act
./scripts/sync-cursor.sh /path/to/project --tool py-indexer
```

Existing files are **skipped** unless `--force` is passed. Preserved paths (reviewed security findings, accepted risks, threat model, contre-attaque state ignore file) are reported as `preserve` and never overwritten; missing ones are created.

Then, in Cursor in the target project: `/contre-attaque 3days` (default 7 days). See `docs/contre-attaque.md` in the target.

## Versioning

Kit release version is in [`VERSION`](VERSION) (currently **1.0.2**). Target projects record their installed layout version in `.repo-kit/version`.

| Version | Layout |
|---------|--------|
| missing | Pre-versioning; treated as **<= 1.0.1** (1.0.0 when root `.chat/` exists, else 1.0.1) |
| 1.0.0 | Root `.chat/` handoff store |
| 1.0.1 | `.repo-kit/chat/` handoff store; root `.findings/` for crypto review notes |
| 1.0.2 | `.repo-kit/chat/` + gitignored `.repo-kit/findings/` + `.repo-kit/version` |

Migrate an existing project to the current kit version (moves `.chat/` → `.repo-kit/chat/`, `.findings/` → `.repo-kit/findings/`, bumps version, refreshes base `.cursor/` assets):

```bash
./scripts/migrate.sh /path/to/project
./scripts/migrate.sh /path/to/project --force   # refresh .cursor/ when already up to date
```

Fresh installs via `init.sh` with `--base` get layout **1.0.2** automatically.

## Extensions

| Extension | Notes |
|-----------|-------|
| `continue` | Checks/prompts for `cn`, `python3`, `grep`, `gh`, `curl`, `rg`; copies `.cursor/rules/{continue-sidekick,dispatch}.mdc` and `AGENTS.md`; copies `.continue/{rules,prompts}`; copies `ai-*.sh` to `.repo-kit/scripts/` (`ai-commit`, `ai-context`, `ai-dep`, `ai-prompter`, `ai-git-issue`); writes `.repo-kit/.bashrc_continue` and hooks `~/.bashrc` |
| `openspec` | `npm i -g @fission-ai/openspec@latest`; `openspec init --tools cursor` in target if needed |
| `forge` | Depends on `openspec` (always installed first). Then `npm i -g @izkac/forgekit@latest`, `forgekit install --skills forge --agents cursor --openspec --force`, and `forge init --cursor --openspec` in target if needed |
| `act` | Checks/prompts for `docker` (daemon reachable) and `act`; copies `.cursor/commands/act-run-workflows.md`, `.cursor/skills/act-run-workflows/`, `act-run-workflows.sh` to `.repo-kit/scripts/`, and project `.actrc` (ubuntu-latest → medium runner image) |

```bash
./scripts/init.sh /path/to/project --ext continue
./scripts/init.sh /path/to/project --ext openspec
./scripts/init.sh /path/to/project --ext forge   # also installs openspec
./scripts/init.sh /path/to/project --ext act
source ~/.bashrc   # activate PATH + aliases (continue)
```

`--ext forge` always resolves `openspec` first. Re-run project inits with `--force`.

Forgekit: [izkac/forgekit](https://github.com/izkac/forgekit). OpenSpec: [@fission-ai/openspec](https://www.npmjs.com/package/@fission-ai/openspec). act: [nektos/act](https://github.com/nektos/act).

## License

repo-kit is licensed under the [MIT License](LICENSE).

Optional extensions pull in third-party tools with their own licenses:

| Tool | Package | License |
|------|---------|---------|
| Forgekit | [`@izkac/forgekit`](https://www.npmjs.com/package/@izkac/forgekit) | [MIT](https://github.com/izkac/forgekit/blob/main/LICENSE) |
| OpenSpec | [`@fission-ai/openspec`](https://www.npmjs.com/package/@fission-ai/openspec) | [MIT](https://github.com/Fission-AI/OpenSpec/blob/main/LICENSE) |
| act | [nektos/act](https://github.com/nektos/act) | [MIT](https://github.com/nektos/act/blob/master/LICENSE) |

## Module lanes

| Module | Depends | Conflicts | Notes |
|--------|---------|-----------|-------|
| `base` | — | — | Neutral scaffolding only |
| `typescript` | `base` | `cpp11`, `rust` | package-preferences, Biome, tsconfig, CI |
| `react` | `typescript` | `cpp11`, `rust` | React conventions skill + docs |
| `security` | `base` | — | Portable hardening plan, review, findings, triage, and CI workflow |
| `contre-attaque` | `security` | — | `/contre-attaque 3days`: lookback CVE/advisory applicability, agent-generated findings, coding-agent handoff |
| `cpp11` | `base` | `typescript`, `react`, `rust` | clang-format, CMake |
| `rust` | `base` | `typescript`, `react`, `cpp11` | rustfmt + Cursor guidance |
| `python` | `base` | — | Ruff, Pyright, pytest config + Cursor guidance |

`--react` pulls in `typescript` and `base` automatically (including package-preferences).

## Recommended workflow

1. Keep this repo as the source of truth.
2. Copy assets into each target repository with `init.sh` or `sync-cursor.sh`.
3. Commit copied files in each target repo.
4. Update the `.npmrc` placeholder (from `typescript`) with your exact policy before broad reuse.

## Tools

| Tool | Notes |
|------|-------|
| `py-indexer` | Local SQLite FTS5 lexical retrieval across explicitly configured related checkouts; CLI + read-only stdio MCP. Installs under `.repo-kit/tools/py-indexer/`. Does not require the `python` module. |

```bash
./scripts/init.sh /path/to/project --tool py-indexer
# then in the target:
.repo-kit/tools/py-indexer/bin/py-indexer index --all
.repo-kit/tools/py-indexer/bin/py-indexer search 'symbol' --json
```

See [catalog/tools.md](catalog/tools.md) and `tools/py-indexer/README.md`.

## Catalog

See [catalog/modules.md](catalog/modules.md) and [catalog/tools.md](catalog/tools.md).
