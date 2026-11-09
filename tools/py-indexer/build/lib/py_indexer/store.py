"""Per-repository SQLite FTS5 store with WAL and schema guards."""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from py_indexer import SCHEMA_VERSION
from py_indexer.chunk import Chunk
from py_indexer.paths import is_safe_repo_id

META_SCHEMA = "schema_version"
META_REPO = "repo_id"
META_CHECKOUT = "checkout"
META_FINGERPRINT = "content_fingerprint"
META_GIT = "git_revision"
META_INDEXED_AT = "indexed_at"
META_STATUS = "status"  # ready | building | corrupt


class IndexError_(RuntimeError):
    """Index open / schema failure."""


@dataclass
class IndexMeta:
    schema_version: int
    repo_id: str
    git_revision: str | None
    indexed_at: str | None
    status: str
    chunk_count: int
    file_count: int


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        conn = sqlite3.connect(str(path), timeout=60.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=60000")
    except sqlite3.DatabaseError as exc:
        raise IndexError_(f"corrupt index at {path}: {exc}") from exc
    return conn


def _init_schema(
    conn: sqlite3.Connection,
    repo_id: str,
    *,
    checkout: str,
    fingerprint: str,
) -> None:
    # executescript() auto-commits; do not wrap it in BEGIN/COMMIT.
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS files (
          path TEXT PRIMARY KEY,
          content_hash TEXT NOT NULL,
          size INTEGER NOT NULL,
          mtime_ns INTEGER NOT NULL,
          language TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chunks (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          path TEXT NOT NULL,
          start_line INTEGER NOT NULL,
          end_line INTEGER NOT NULL,
          content_hash TEXT NOT NULL,
          text TEXT NOT NULL,
          FOREIGN KEY(path) REFERENCES files(path) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path);
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
          text,
          path UNINDEXED,
          start_line UNINDEXED,
          end_line UNINDEXED,
          content='chunks',
          content_rowid='id'
        );
        CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
          INSERT INTO chunks_fts(rowid, text, path, start_line, end_line)
          VALUES (new.id, new.text, new.path, new.start_line, new.end_line);
        END;
        CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
          INSERT INTO chunks_fts(chunks_fts, rowid, text, path, start_line, end_line)
          VALUES ('delete', old.id, old.text, old.path, old.start_line, old.end_line);
        END;
        CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
          INSERT INTO chunks_fts(chunks_fts, rowid, text, path, start_line, end_line)
          VALUES ('delete', old.id, old.text, old.path, old.start_line, old.end_line);
          INSERT INTO chunks_fts(rowid, text, path, start_line, end_line)
          VALUES (new.id, new.text, new.path, new.start_line, new.end_line);
        END;
        """
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        (META_SCHEMA, str(SCHEMA_VERSION)),
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        (META_REPO, repo_id),
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        (META_CHECKOUT, checkout),
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        (META_FINGERPRINT, fingerprint),
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        (META_STATUS, "ready"),
    )


def _meta_get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def open_index(
    path: Path,
    repo_id: str,
    *,
    checkout: Path,
    fingerprint: str,
    create: bool = False,
) -> sqlite3.Connection:
    if not is_safe_repo_id(repo_id):
        raise IndexError_(f"unsafe repository id: {repo_id!r}")
    checkout_s = str(checkout.resolve())
    if not path.exists():
        if not create:
            raise IndexError_(f"missing index for {repo_id}: {path}")
        conn = _connect(path)
        try:
            # Verify FTS5
            conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_probe USING fts5(x)")
            conn.execute("DROP TABLE IF EXISTS _fts5_probe")
            _init_schema(conn, repo_id, checkout=checkout_s, fingerprint=fingerprint)
        except Exception:
            conn.close()
            raise
        return conn

    conn = _connect(path)
    try:
        # Detect corruption / wrong schema early.
        try:
            ver = _meta_get(conn, META_SCHEMA)
            status = _meta_get(conn, META_STATUS)
            stored_checkout = _meta_get(conn, META_CHECKOUT)
            stored_fp = _meta_get(conn, META_FINGERPRINT)
        except sqlite3.DatabaseError as exc:
            conn.close()
            raise IndexError_(f"corrupt index for {repo_id}: {exc}") from exc

        if ver is None:
            conn.close()
            raise IndexError_(f"index for {repo_id} missing schema_version metadata")
        if int(ver) != SCHEMA_VERSION:
            conn.close()
            raise IndexError_(
                f"incompatible index schema for {repo_id}: got {ver}, expected {SCHEMA_VERSION}"
            )
        if stored_checkout not in (None, checkout_s):
            conn.close()
            raise IndexError_(
                f"index checkout mismatch for {repo_id}: stored {stored_checkout!r}"
            )
        if stored_fp != fingerprint:
            conn.close()
            raise IndexError_(
                f"index settings changed for {checkout_s}; re-run index to replace {path}"
            )
        if status == "corrupt":
            conn.close()
            raise IndexError_(f"index for {repo_id} marked corrupt")
        # Ensure core tables exist
        tables = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            ).fetchall()
        }
        for need in ("meta", "files", "chunks", "chunks_fts"):
            if need not in tables:
                conn.close()
                raise IndexError_(f"index for {repo_id} missing table {need}")
    except IndexError_:
        raise
    except Exception as exc:  # noqa: BLE001
        conn.close()
        raise IndexError_(f"failed opening index for {repo_id}: {exc}") from exc
    return conn


@contextmanager
def locked_write(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def read_meta(conn: sqlite3.Connection) -> IndexMeta:
    chunk_count = conn.execute("SELECT COUNT(*) AS c FROM chunks").fetchone()["c"]
    file_count = conn.execute("SELECT COUNT(*) AS c FROM files").fetchone()["c"]
    return IndexMeta(
        schema_version=int(_meta_get(conn, META_SCHEMA) or "0"),
        repo_id=_meta_get(conn, META_REPO) or "",
        git_revision=_meta_get(conn, META_GIT),
        indexed_at=_meta_get(conn, META_INDEXED_AT),
        status=_meta_get(conn, META_STATUS) or "unknown",
        chunk_count=int(chunk_count),
        file_count=int(file_count),
    )


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        (key, value),
    )


def upsert_file(
    conn: sqlite3.Connection,
    *,
    path: str,
    content_hash: str,
    size: int,
    mtime_ns: int,
    language: str,
    chunks: list[Chunk],
) -> None:
    conn.execute("DELETE FROM chunks WHERE path = ?", (path,))
    conn.execute(
        """
        INSERT INTO files(path, content_hash, size, mtime_ns, language)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
          content_hash=excluded.content_hash,
          size=excluded.size,
          mtime_ns=excluded.mtime_ns,
          language=excluded.language
        """,
        (path, content_hash, size, mtime_ns, language),
    )
    for ch in chunks:
        conn.execute(
            """
            INSERT INTO chunks(path, start_line, end_line, content_hash, text)
            VALUES (?, ?, ?, ?, ?)
            """,
            (path, ch.start_line, ch.end_line, ch.content_hash, ch.text),
        )


def delete_file(conn: sqlite3.Connection, path: str) -> None:
    conn.execute("DELETE FROM chunks WHERE path = ?", (path,))
    conn.execute("DELETE FROM files WHERE path = ?", (path,))


def list_files(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    rows = conn.execute("SELECT path, content_hash, size, mtime_ns, language FROM files").fetchall()
    return {r["path"]: r for r in rows}


def stamp_success(
    conn: sqlite3.Connection,
    *,
    git_revision: str | None,
    repo_id: str,
    checkout: Path,
    fingerprint: str,
) -> None:
    set_meta(conn, META_STATUS, "ready")
    set_meta(conn, META_REPO, repo_id)
    set_meta(conn, META_CHECKOUT, str(checkout.resolve()))
    set_meta(conn, META_FINGERPRINT, fingerprint)
    set_meta(conn, META_INDEXED_AT, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    if git_revision is not None:
        set_meta(conn, META_GIT, git_revision)


def rebuild_empty(
    path: Path,
    repo_id: str,
    *,
    checkout: Path,
    fingerprint: str,
) -> sqlite3.Connection:
    """Replace a broken index with a fresh empty schema (caller deletes old file first)."""
    if path.exists():
        path.unlink()
    for suffix in ("-wal", "-shm"):
        side = Path(str(path) + suffix)
        if side.exists():
            side.unlink()
    return open_index(
        path, repo_id, checkout=checkout, fingerprint=fingerprint, create=True
    )
