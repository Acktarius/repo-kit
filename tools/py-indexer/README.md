# tool: py-indexer

Private, local, cross-repository **lexical** code retrieval for Cursor.

Installed into a target as `.repo-kit/tools/py-indexer/` (copy-based; no symlink to this kit).

## Prerequisites

Before install, the target machine needs **Python 3** with the **venv** module (`ensurepip`). On Debian/Ubuntu:

```bash
sudo apt install python3 python3-venv
```

Without `python3-venv`, the installer cannot create `.venv/` (`python3 -m venv` fails).

## Install

```bash
./scripts/init.sh /path/to/project --tool py-indexer
# combine freely:
./scripts/init.sh /path/to/project --typescript --ext continue --tool py-indexer
# tool-only is allowed:
./scripts/init.sh /path/to/project --tool py-indexer
```

`sync-cursor.sh --tool py-indexer` installs the tool **fully** (same treatment as `--ext`).

Does **not** require the `python` language module.

## After install

1. Edit `.repo-kit/tools/py-indexer/repos.json` (seeded once; never overwritten).
2. Review `.repo-kit/tools/py-indexer/excludes.txt` (`.env`, `build/`, secrets, …). Optional overlay: `<repo>/.py-indexer-ignore`. Gitignored paths are skipped automatically.
3. Index: `.repo-kit/tools/py-indexer/bin/py-indexer index --all`
4. Search: `.repo-kit/tools/py-indexer/bin/py-indexer search 'symbol' --json`
5. Enable the `py-indexer` server in Cursor MCP (`.cursor/mcp.json` is merge-updated when safe).

See the installed `README.md` under `.repo-kit/tools/py-indexer/` for full docs.

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
