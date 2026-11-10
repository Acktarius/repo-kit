"""Incremental indexing into per-repo SQLite databases."""

from __future__ import annotations

from pathlib import Path

from py_indexer.chunk import chunk_lines, content_hash
from py_indexer.config import AppConfig
from py_indexer.exclude import iter_candidate_files, language_for
from py_indexer.gitinfo import git_head
from py_indexer.paths import index_db_path
from py_indexer.store import (
    IndexError_,
    delete_file,
    list_files,
    locked_write,
    open_index,
    read_meta,
    stamp_success,
    upsert_file,
)


def _file_hash_and_text(path: Path, max_bytes: int) -> tuple[str, str, int, int]:
    data = path.read_bytes()
    if len(data) > max_bytes:
        raise OSError("file exceeds max_file_bytes")
    text = data.decode("utf-8", errors="replace")
    st = path.stat()
    return content_hash(text), text, st.st_size, getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))


def _aside_path(db_path: Path) -> Path:
    return db_path.with_suffix(db_path.suffix + ".prev")


def _unlink_db_bundle(path: Path) -> None:
    if path.exists():
        path.unlink()
    for suffix in ("-wal", "-shm"):
        side = Path(str(path) + suffix)
        if side.exists():
            side.unlink()


def index_repository(cfg: AppConfig, repo_id: str) -> dict:
    tool_root = cfg.tool_root
    db_path = index_db_path(tool_root, repo_id)

    conn = None
    if db_path.exists():
        try:
            conn = open_index(tool_root, repo_id, create=False)
        except IndexError_:
            conn = None

    if conn is None:
        # Preserve previous file until a replacement is successfully built.
        aside = None
        if db_path.exists():
            aside = _aside_path(db_path)
            _unlink_db_bundle(aside)
            db_path.rename(aside)
            for suffix in ("-wal", "-shm"):
                src = Path(str(db_path) + suffix)
                # After rename of main file, wal/shm may still use old name; move if present
                # (SQLite usually keeps them beside the active name; after rename they may remain.)
                if src.exists():
                    src.rename(Path(str(aside) + suffix))
        try:
            conn = open_index(tool_root, repo_id, create=True)
            stats = _index_into(conn, cfg, repo_id)
            if aside is not None:
                _unlink_db_bundle(aside)
            return stats
        except Exception:
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
            _unlink_db_bundle(db_path)
            if aside is not None and aside.exists():
                aside.rename(db_path)
                for suffix in ("-wal", "-shm"):
                    src = Path(str(aside) + suffix)
                    if src.exists():
                        src.rename(Path(str(db_path) + suffix))
            raise
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass

    assert conn is not None
    try:
        return _index_into(conn, cfg, repo_id)
    finally:
        conn.close()


def _index_into(conn, cfg: AppConfig, repo_id: str) -> dict:
    repo = cfg.get(repo_id)
    seen: set[str] = set()
    added = modified = unchanged = deleted = 0

    with locked_write(conn):
        existing = list_files(conn)
        for rel, path in iter_candidate_files(
            repo.root,
            include=repo.include,
            exclude=repo.exclude,
            max_file_bytes=cfg.budgets.max_file_bytes,
            tool_root=cfg.tool_root,
        ):
            seen.add(rel)
            try:
                digest, text, size, mtime_ns = _file_hash_and_text(
                    path, cfg.budgets.max_file_bytes
                )
            except OSError:
                continue
            prev = existing.get(rel)
            if prev is not None and prev["content_hash"] == digest:
                unchanged += 1
                continue
            chunks = chunk_lines(
                text,
                chunk_lines=cfg.chunk_lines,
                overlap=cfg.chunk_overlap_lines,
            )
            upsert_file(
                conn,
                path=rel,
                content_hash=digest,
                size=size,
                mtime_ns=mtime_ns,
                language=language_for(rel),
                chunks=chunks,
            )
            if prev is None:
                added += 1
            else:
                modified += 1

        for old_path in list(existing):
            if old_path not in seen:
                delete_file(conn, old_path)
                deleted += 1

        stamp_success(conn, git_revision=git_head(repo.root))
        meta = read_meta(conn)

    return {
        "repo_id": repo_id,
        "added": added,
        "modified": modified,
        "unchanged": unchanged,
        "deleted": deleted,
        "files": meta.file_count,
        "chunks": meta.chunk_count,
        "git_revision": meta.git_revision,
        "indexed_at": meta.indexed_at,
    }


def index_all(cfg: AppConfig) -> list[dict]:
    return [index_repository(cfg, rid) for rid in cfg.repositories]
