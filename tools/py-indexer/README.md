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

## One database per checkout

Each resolved checkout directory has one SQLite file under the user cache.
Projects that point at that directory share it. A second worktree is a different
directory, so it gets a different file.

The file stores one indexing policy. That policy is the hash of chunk settings,
`include` / `exclude`, the selection-rule version, legacy `excludes.txt`,
`.py-indexer-ignore`, checkout `.gitignore` files, `.git/info/exclude`, and the
global Git excludes file when Git reports one. If the project you are searching
from hashes to something else, search and status refuse the snapshot and say so.
They do not return its hits and they do not create a second database.
`py-indexer index` replaces that same file with the policy of the project you
run it from. The other project then sees a policy mismatch until it indexes again.

Search also drops a hit the current exclude rules or Git ignore would reject,
even when the fingerprint matches.

## Index lock and recovery

`py-indexer index` takes an exclusive lock on `<database>.lock` for the whole
rebuild: recovery, a fresh read of the policy, staging, and publication.
Wait timeout is 60 seconds. On timeout the published file is left as it was.

The new database is written to `<database>.staging` as a single rollback-journal
file, fsynced, then published with an atomic replace. The previous file is not
renamed, and a live WAL bundle is not moved. A reader that already has the file
open keeps that inode and finishes on it. The next open sees the replacement.

If publication fails, staging is deleted and the last canonical file remains.
After a crash:

- staging without `<database>.staging.complete` is discarded
- ready staging with that marker is published
- `<database>.prev` is restored only when the canonical file is missing or unusable

A successful index removes staging, the completion marker, `-wal`/`-shm`, and `.prev`.

## Migration from project-local installs

Older installs copied `bin/`, `py_indexer/`, `.venv/`, and `index/` into each project.

On init/sync the installer:

1. Ensures the shared application. A CLI-only install (`REPO_KIT_TOOL_SKIP_DEPS=1`)
   is reported as CLI-only. A normal setup that finds the CLI without
   `mcp.server.fastmcp.FastMCP` offers to install `mcp==1.30.0` into the existing
   virtualenv. That repair does not reinstall the application. PATH profile edits
   stay behind their own consent and are updated when the managed block's bin
   directory changed.
2. Rewrites only an exact legacy MCP entry for this project: `type`/`command`/`args`
   alone, command this project's `.venv/bin/python`, args this project's
   `bin/py-indexer` and `serve` (either `${workspaceFolder}` or this project's
   absolute path). Extra `env`/`cwd` fields, or another checkout's paths, are
   left untouched and `mcp.fragment.json` is written for a manual merge.
3. Preserves `repos.json` and any legacy `excludes.txt` (still honored as an overlay)
4. Does **not** copy old SQLite DBs into the new cache namespace — run `py-indexer index --all`

`init.sh`, `sync-cursor.sh`, and `migrate.sh` list identified legacy files and
ask before deleting any of them. `REPO_KIT_TOOL_ASSUME_YES` does not answer that
question. Deletion runs only when a shared CLI is already verified, and only for
these artifacts:

- `bin/` when its only entry is the regular file `bin/py-indexer`
- `py_indexer/` when it contains only the shipped legacy modules (and `__pycache__`)
- `.venv/` when it has `pyvenv.cfg` and `bin/python`
- `index/` when it contains only `<repo-id>.sqlite3` plus `-wal`/`-shm`
- `requirements.txt` and `mcp.example.json` when their bytes match the shipped legacy files

Anything else in those directories is left, and the directory is not removed.
`repos.json` and `excludes.txt` are never removed. Directories under
`~/.cache/py-indexer/indexes/` are never treated as obsolete. If `.cursor/mcp.json`
cannot be parsed, nothing is deleted. If the `py-indexer` entry was not migrated
and still names a legacy path, that path is not deleted.

Fold custom `excludes.txt` patterns into `repos.json` `exclude` when you no longer
want that overlay, then delete `excludes.txt` yourself. Until you do, that file
is part of the indexing policy for projects that still have it.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `py-indexer: command not found` | `export PATH="$HOME/.local/bin:$PATH"` (or your `XDG_BIN_HOME`); re-run init to add an idempotent bashrc marker if desired. Cursor MCP does not need PATH — it uses the absolute executable. |
| MCP fails with missing mcp | Install `mcp==1.30.0` into the shared user venv (see Offline install). |
| Wrong/missing indexes | Check `py-indexer status` → each repository `index.path`. A policy mismatch names that file and does not search it. `py-indexer index` replaces the same file. |
| `index policy mismatch` | Another project indexed this checkout with different excludes, `excludes.txt`, `.py-indexer-ignore`, or Git ignore inputs. One database cannot hold both. Index from the project whose policy should win. |
| Divergent MCP entry left alone | Compare `.repo-kit/tools/py-indexer/mcp.fragment.json` and merge manually. |
| Lock timeout | Another `py-indexer index` holds `<database>.lock`. Wait, then retry. The last published database is unchanged. |

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
