"""py-indexer command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from py_indexer import APP_NAME, COMPAT_VERSION, SCHEMA_VERSION, __version__
from py_indexer.config import ConfigError, load_config
from py_indexer.paths import cache_home
from py_indexer.index_cmd import index_all, index_repository
from py_indexer.read_cmd import read_as_dict, read_code
from py_indexer.search_cmd import search, search_as_dict
from py_indexer.status_cmd import status_report


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="py-indexer",
        description="Local cross-repository lexical code retrieval (SQLite FTS5).",
    )
    p.add_argument("--version", action="version", version=f"py-indexer {__version__}")
    p.add_argument(
        "--app-id",
        action="store_true",
        help="Print application identity JSON and exit (installer compatibility probe)",
    )
    p.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to repos.json (default: nearest .repo-kit/tools/py-indexer/repos.json)",
    )
    p.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help=(
            "Target project root for resolving repository roots. "
            "Required when --config is not at …/.repo-kit/tools/py-indexer/repos.json"
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=False)

    sub.add_parser("validate-config", help="Validate repos.json")

    p_index = sub.add_parser("index", help="Build or refresh indexes")
    g = p_index.add_mutually_exclusive_group(required=True)
    g.add_argument("--repo", metavar="ID", help="Index one repository id")
    g.add_argument("--all", action="store_true", help="Index every configured repository")

    p_search = sub.add_parser("search", help="Search indexed chunks")
    p_search.add_argument("query", help="Search query (lexical; sanitized for FTS5)")
    p_search.add_argument(
        "--repo",
        action="append",
        default=[],
        metavar="ID",
        help="Limit to repository id (repeatable)",
    )
    p_search.add_argument(
        "--scope",
        choices=("active", "related", "active+related"),
        default="active+related",
        help="Default scope when --repo is omitted",
    )
    p_search.add_argument("--json", action="store_true", help="Emit JSON")
    p_search.add_argument("--limit", type=int, default=None, help="Max hits (clamped)")

    p_read = sub.add_parser("read", help="Read a bounded live source range")
    p_read.add_argument("--repo", required=True, metavar="ID")
    p_read.add_argument("--path", required=True, help="Repository-relative path")
    p_read.add_argument("--start", type=int, required=True, dest="start_line")
    p_read.add_argument("--end", type=int, required=True, dest="end_line")
    p_read.add_argument("--json", action="store_true")

    sub.add_parser("status", help="Show config and index freshness")
    sub.add_parser("serve", help="Run read-only stdio MCP server")
    return p


_MCP_API = "mcp.server.fastmcp.FastMCP"


def _mcp_api_imports() -> bool:
    """True only when the FastMCP symbol ``serve`` actually imports."""
    try:
        from mcp.server.fastmcp import FastMCP  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def _print_app_id() -> int:
    # Probe FTS5 without requiring a config file. CLI readiness does not imply MCP.
    fts5 = False
    try:
        import sqlite3

        c = sqlite3.connect(":memory:")
        c.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        fts5 = True
    except Exception:  # noqa: BLE001
        fts5 = False
    mcp_ready = bool(fts5 and _mcp_api_imports())
    print(
        json.dumps(
            {
                "name": APP_NAME,
                "version": __version__,
                "compat_version": COMPAT_VERSION,
                "schema_version": SCHEMA_VERSION,
                "fts5": fts5,
                "cli_ready": fts5,
                "mcp_ready": mcp_ready,
                "mcp_api": _MCP_API,
            },
            indent=2,
        )
    )
    return 0 if fts5 else 1


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.app_id:
        return _print_app_id()

    if args.cmd is None:
        parser.error("a command is required (or pass --app-id / --version)")

    if args.cmd == "serve":
        from py_indexer.mcp_server import run_stdio_server

        return run_stdio_server(
            config_path=args.config,
            project_root=args.project_root,
        )

    try:
        cfg = load_config(args.config, project_root=args.project_root)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.cmd == "validate-config":
        print(
            json.dumps(
                {
                    "ok": True,
                    "active_repo": cfg.active_repo,
                    "repos": list(cfg.repositories),
                    "project_root": str(cfg.project_root),
                    "cache_dir": str(cache_home() / "indexes"),
                },
                indent=2,
            )
        )
        return 0

    if args.cmd == "index":
        try:
            if args.all:
                results = index_all(cfg)
            else:
                results = [index_repository(cfg, args.repo)]
        except Exception as exc:  # noqa: BLE001
            print(f"error: index failed: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(results, indent=2))
        return 0

    if args.cmd == "search":
        resp = search(
            cfg,
            args.query,
            repo_ids=args.repo or None,
            scope=args.scope,
            limit=args.limit,
        )
        if args.json:
            print(json.dumps(search_as_dict(resp), indent=2))
        else:
            for w in resp.warnings:
                print(f"warning: {w}", file=sys.stderr)
            if not resp.hits:
                print("(no hits)")
            for h in resp.hits:
                print(
                    f"#{h.rank} {h.repo_id}:{h.path}:{h.start_line}-{h.end_line} "
                    f"score={h.score:.3f} rev={h.indexed_revision or '-'} snapshot={h.from_index_snapshot}"
                )
                print(h.text)
                print("---")
            if resp.truncated:
                print("(response truncated by budget)", file=sys.stderr)
        return 0

    if args.cmd == "read":
        try:
            result = read_code(
                cfg,
                repo_id=args.repo,
                path=args.path,
                start_line=args.start_line,
                end_line=args.end_line,
            )
        except ConfigError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(read_as_dict(result), indent=2))
        else:
            print(
                f"{result.repo_id}:{result.path}:{result.start_line}-{result.end_line} "
                f"differs_from_index={result.differs_from_index}"
            )
            print(result.text)
        return 0

    if args.cmd == "status":
        print(json.dumps(status_report(cfg), indent=2))
        return 0

    parser.error(f"unknown command {args.cmd}")
    return 2
