# tool: py-indexer

Private, local, cross-repository **lexical** code retrieval for Cursor.

**Once per user:** the application installs into a user-owned virtualenv
(`$XDG_DATA_HOME/py-indexer/venv` or `~/.local/share/py-indexer/venv`) with a
`py-indexer` command under `$XDG_BIN_HOME` / `~/.local/bin`.

**Per project:** only configuration and Cursor integration are written:

- `.repo-kit/tools/py-indexer/repos.json` (seeded once; never overwritten)
- `.cursor/rules/py-indexer.mdc`
- `.cursor/mcp.json` merge (absolute executable + `--config` + `serve`)

**Indexes** live under `$XDG_CACHE_HOME/py-indexer/indexes/` (or `~/.cache/py-indexer/indexes/`).
There is one database per checkout directory. Indexing that directory again,
from any project, replaces that same file. Two worktrees stay separate because
they are different directories.

Updating the shared application affects every project that uses it.

Local indexing does **not** make Cursor model inference local: returned snippets
may still be sent to the selected model provider.

## Prerequisites

- **Python 3** with the **venv** module (`ensurepip`). On Debian/Ubuntu:
  `sudo apt install python3 python3-venv`
- SQLite **FTS5** in that Python build

The installer never uses `sudo pip` or modifies the OS-managed Python environment.

## Install

```bash
./scripts/init.sh /path/to/project --tool py-indexer
# combine freely:
./scripts/init.sh /path/to/project --typescript --ext continue --tool py-indexer
# tool-only is allowed:
./scripts/init.sh /path/to/project --tool py-indexer
```

`sync-cursor.sh --tool py-indexer` installs the tool fully (same treatment as `--ext`).

Consent:

- Shared app install / upgrade asks interactively (or `REPO_KIT_TOOL_ASSUME_YES=1`)
- Non-interactive runs refuse network/install without assume-yes
- `REPO_KIT_TOOL_SKIP_DEPS=1` installs the app offline **without** `mcp` (CLI works; `serve` needs `mcp==1.30.0`)
- PATH profile changes are separate consent; MCP uses the absolute executable and does not require shell PATH

Does **not** require the `python` language module.

## After install

1. Edit `.repo-kit/tools/py-indexer/repos.json` (seeded once; never overwritten, including `--force`).
2. Optional per-repo overlay: `<repo>/.py-indexer-ignore`. Project-specific globs go in `repos.json` `exclude`. Packaged defaults ship with the app.
3. Index / search / status (from anywhere under the project, or with `--config`):

```bash
py-indexer validate-config
py-indexer index --all
py-indexer search 'example_symbol' --json
py-indexer status
```

4. Enable the `py-indexer` server in Cursor MCP (`.cursor/mcp.json` is merge-updated when safe).

Explicit config:

```bash
py-indexer --config /abs/path/to/repos.json validate-config
# Nonstandard config path (not …/.repo-kit/tools/py-indexer/repos.json):
py-indexer --config /tmp/custom.json --project-root /path/to/project status
```

## Offline install

```bash
REPO_KIT_TOOL_ASSUME_YES=1 REPO_KIT_TOOL_SKIP_DEPS=1 \
  ./scripts/init.sh /path/to/project --tool py-indexer
# Later, for MCP serve:
~/.local/share/py-indexer/venv/bin/python -m pip install 'mcp==1.30.0'
# or from a wheelhouse:
…/python -m pip install --no-index --find-links=/path/to/wheels 'mcp==1.30.0'
```

## Migration from project-local installs

Older installs copied `bin/`, `py_indexer/`, `.venv/`, and `index/` into each project.

On init/sync the installer:

1. Ensures the shared application and rewrites a **known legacy** MCP entry
   (venv python + `bin/py-indexer serve`) to the new absolute command shape
2. Preserves `repos.json` and any legacy `excludes.txt` (still honored as an overlay)
3. Does **not** copy old SQLite DBs into the new cache namespace — run `py-indexer index --all`
4. Does **not** delete legacy trees automatically

`init.sh`, `sync-cursor.sh`, and `migrate.sh` ask before removing old project-local
`bin/`, `py_indexer/`, `.venv/`, `index/`, and obsolete cache directories. Answering
`y` is the cleanup. `repos.json`, `excludes.txt`, and current
`~/.cache/py-indexer/indexes/*.sqlite3` files stay. Fold custom `excludes.txt`
patterns into `repos.json` `exclude` when you no longer want that overlay, then
delete `excludes.txt` yourself.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `py-indexer: command not found` | `export PATH="$HOME/.local/bin:$PATH"` (or your `XDG_BIN_HOME`); re-run init to add an idempotent bashrc marker if desired. Cursor MCP does not need PATH — it uses the absolute executable. |
| MCP fails with missing mcp | Install `mcp==1.30.0` into the shared user venv (see Offline install). |
| Wrong/missing indexes | Check `py-indexer status` → each repository `index.path`. A settings change replaces that same file on the next `index`. |
| Divergent MCP entry left alone | Compare `.repo-kit/tools/py-indexer/mcp.fragment.json` and merge manually. |

## Tests

```bash
# Offline default (stdlib + installer; skips MCP e2e)
bash tests/py-indexer.sh

# Supply an interpreter that already has mcp==1.30.x (no download)
PY_INDEXER_MCP_PYTHON=/path/to/python-with-mcp bash tests/py-indexer.sh

# Require MCP coverage
PY_INDEXER_MCP_STRICT=1 PY_INDEXER_MCP_PYTHON=/path/to/python-with-mcp bash tests/py-indexer.sh

# Explicit networked bootstrap only when you opt in
PY_INDEXER_MCP_BOOTSTRAP=1 bash tests/py-indexer.sh
```
