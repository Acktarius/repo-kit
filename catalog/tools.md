# Tool catalog

Human-readable mirror of `tools/*/manifest.sh`.

Install with `--tool <name>` on `init.sh` / `sync-cursor.sh` (repeatable; combinable with modules and `--ext`). Tool-only installs are allowed. Explicitly requested tools install fully under `sync-cursor.sh` (same treatment as `--ext`).

## py-indexer

- **Description:** Local cross-repo lexical code retrieval (CLI + read-only stdio MCP)
- **Depends:** —
- **Provides:**
  - `.repo-kit/tools/py-indexer/bin/py-indexer`
  - `.repo-kit/tools/py-indexer/py_indexer/`
  - `.repo-kit/tools/py-indexer/repos.example.json` (+ seeded `repos.json` if missing)
  - `.repo-kit/tools/py-indexer/excludes.txt` (secret/build globs; plus Git ignore + optional `.py-indexer-ignore`)
  - `.repo-kit/tools/py-indexer/mcp.example.json`
  - `.repo-kit/tools/py-indexer/requirements.txt` (`mcp==1.30.0`)
  - `.repo-kit/tools/py-indexer/README.md`
  - `.repo-kit/tools/py-indexer/index/` (runtime DBs)
  - `.cursor/rules/py-indexer.mdc`
  - Merge of `py-indexer` into `.cursor/mcp.json` when safe
- **Preserves:** existing `repos.json`, `excludes.txt`, `index/`, `.venv/` across reinstall/`--force`
- **Host checks:** `python3`, venv/ensurepip, SQLite FTS5; prompts before networked `pip install`
- **Does not:** require the `python` language module; clone repos; auto-index; embed/vector-search; mutate indexes over MCP
