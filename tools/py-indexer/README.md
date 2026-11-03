# tool: py-indexer

Private, local, cross-repository **lexical** code retrieval for Cursor.

Installed into a target as `.repo-kit/tools/py-indexer/` (copy-based; no symlink to this kit).

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
