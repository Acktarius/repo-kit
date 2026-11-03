"""Index / config status reporting."""

from __future__ import annotations

from pathlib import Path

from py_indexer.config import AppConfig
from py_indexer.gitinfo import git_head
from py_indexer.paths import index_db_path
from py_indexer.store import IndexError_, open_index, read_meta


def status_report(cfg: AppConfig) -> dict:
    repos = []
    for rid, repo in cfg.repositories.items():
        entry: dict = {
            "id": rid,
            "role": repo.role,
            "root": str(repo.root),
            "related": list(repo.related),
            "git_head": git_head(repo.root),
            "index": None,
            "warnings": [],
        }
        db = index_db_path(cfg.tool_root, rid)
        if not db.exists():
            entry["warnings"].append("missing index")
            repos.append(entry)
            continue
        try:
            conn = open_index(cfg.tool_root, rid, create=False)
        except IndexError_ as exc:
            entry["warnings"].append(str(exc))
            repos.append(entry)
            continue
        try:
            meta = read_meta(conn)
            entry["index"] = {
                "path": str(db),
                "schema_version": meta.schema_version,
                "status": meta.status,
                "files": meta.file_count,
                "chunks": meta.chunk_count,
                "indexed_at": meta.indexed_at,
                "indexed_git_revision": meta.git_revision,
                "freshness_note": (
                    "indexed_git_revision is Git HEAD at index time; "
                    "working-tree files may still differ."
                ),
            }
            if meta.git_revision and entry["git_head"] and meta.git_revision != entry["git_head"]:
                entry["warnings"].append(
                    "Git HEAD moved since index; re-run index to refresh committed snapshot metadata"
                )
        finally:
            conn.close()
        repos.append(entry)

    return {
        "schema_version": cfg.schema_version,
        "active_repo": cfg.active_repo,
        "config_path": str(cfg.config_path),
        "tool_root": str(cfg.tool_root),
        "budgets": {
            "max_results": cfg.budgets.max_results,
            "max_snippet_chars": cfg.budgets.max_snippet_chars,
            "max_total_chars": cfg.budgets.max_total_chars,
            "max_file_bytes": cfg.budgets.max_file_bytes,
        },
        "repositories": repos,
        "privacy_note": (
            "Local indexing does not make Cursor model inference local; "
            "returned snippets may be sent to the selected model provider."
        ),
    }
