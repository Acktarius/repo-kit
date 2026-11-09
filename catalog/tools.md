# Tool catalog

Human-readable mirror of `tools/*/manifest.sh`.

Install with `--tool <name>` on `init.sh` / `sync-cursor.sh` (repeatable; combinable with modules and `--ext`). Tool-only installs are allowed. Explicitly requested tools install fully under `sync-cursor.sh` (same treatment as `--ext`).

## py-indexer

- **Description:** Local cross-repo lexical code retrieval (user-wide CLI + read-only stdio MCP)
- **Depends:** —
- **Provides (per user):**
  - Shared application in `$XDG_DATA_HOME/py-indexer/venv` (or `~/.local/share/py-indexer/venv`)
  - `py-indexer` console command under `$XDG_BIN_HOME` / `~/.local/bin`
  - One index database per checkout directory under `$XDG_CACHE_HOME/py-indexer/indexes/` (or `~/.cache/py-indexer/indexes/`). A later index of that directory replaces the file.
- **Provides (per project):**
  - `.repo-kit/tools/py-indexer/repos.json` (seeded once from kit example if missing)
  - `.cursor/rules/py-indexer.mdc`
  - Merge of `py-indexer` into `.cursor/mcp.json` when safe (absolute exe + `--config` + `serve`)
  - `.repo-kit/tools/py-indexer/mcp.fragment.json` for manual merge fallback
- **Preserves:** existing `repos.json` across reinstall/`--force`; never overwrites divergent custom MCP entries (known legacy repo-kit MCP shape is migrated)
- **Host checks:** `python3`, venv/ensurepip, SQLite FTS5; consent before install/upgrade and before PATH profile changes; never `sudo pip`
- **Does not:** copy the application, project-local `.venv`, or indexes into target projects; require the `python` language module; clone repos; auto-index; embed/vector-search; mutate indexes over MCP
- **Notes:** One shared app serves many projects. Upgrading it affects all of them. Local retrieval does not make hosted-model inference local.
