"""Per-checkout SQLite FTS5 store.

Writers take an exclusive flock on ``<db>.lock`` for the whole index lifecycle
(see ``checkout_index_lock``). The published database is one file in rollback
journal mode. A replacement is built in ``<db>.staging`` and published with
``os.replace`` after fsync. Live WAL/SHM bundles are never renamed.

Crash recovery (under the same lock):

- Staging without ``<db>.staging.complete`` is discarded. The canonical file stays.
- A ready staging file with that marker is published (crash after fsync, before replace).
- ``<db>.prev`` is restored only when the canonical file is missing or unusable,
  then removed. A usable canonical file causes ``.prev`` to be deleted.
- Lock wait defaults to 60s (``IndexLockTimeout``). The last published file is unchanged.

Readers do not take the lock. A reader that already opened a rollback-journal
file keeps that inode across ``os.replace``. Later opens see the replacement.

A canonical database still in WAL mode, or one that still has ``-wal``/``-shm``
files, is not replaced and those files are not unlinked while another process
has them open. Indexing then raises ``IndexWalBusy`` and leaves that bundle
in place. Stop the old process and run index again. Each publication also
keeps a full extra copy at ``<database>.staging`` until the replace finishes.
"""

from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - repo-kit targets Linux
    fcntl = None  # type: ignore[assignment]

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


class IndexWalBusy(IndexError_):
    """A WAL-mode canonical index is still open in another process.

    Replacing the database or unlinking ``-wal``/``-shm`` would drop committed
    frames those processes still need. The canonical path is left unchanged.
    """


class IndexLockTimeout(TimeoutError):
    """Timed out waiting for the checkout-wide index lock."""

    def __init__(self, db_path: Path, timeout_sec: float) -> None:
        self.db_path = db_path
        self.timeout_sec = timeout_sec
        super().__init__(
            f"timed out after {timeout_sec:g}s waiting for the checkout index lock "
            f"({db_path}.lock). Another py-indexer index is still publishing this "
            "checkout. Retry after it finishes. The last published database is unchanged."
        )


def policy_mismatch_message(checkout: str, path: Path) -> str:
    """One database cannot serve two indexing policies for the same checkout."""
    return (
        f"index policy mismatch for checkout {checkout}: "
        f"database {path} was built with a different indexing policy. "
        "One database per checkout cannot hold two policies at once. "
        "This request will not use that snapshot. "
        "Run py-indexer index to replace that same database with the current policy."
    )


@dataclass
class IndexMeta:
    schema_version: int
    repo_id: str
    git_revision: str | None
    indexed_at: str | None
    status: str
    chunk_count: int
    file_count: int


def staging_path(db_path: Path) -> Path:
    return Path(str(db_path) + ".staging")


def _complete_marker(db_path: Path) -> Path:
    return Path(str(db_path) + ".staging.complete")


def _prev_path(db_path: Path) -> Path:
    return Path(str(db_path) + ".prev")


def _sidecar_paths(path: Path) -> list[Path]:
    return [Path(str(path) + suffix) for suffix in ("-wal", "-shm", "-journal")]


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        return


def _unlink_bundle(path: Path) -> None:
    _unlink_quiet(path)
    for side in _sidecar_paths(path):
        _unlink_quiet(side)


def _fsync_file(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _connect(path: Path, *, delete_journal: bool = False) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        conn = sqlite3.connect(str(path), timeout=60.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=60000")
        # Published databases stay single-file. Do not switch a live file to WAL:
        # replacing an open WAL bundle is not safe for concurrent readers.
        if delete_journal:
            conn.execute("PRAGMA journal_mode=DELETE")
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
        (META_STATUS, "building"),
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
        conn = _connect(path, delete_journal=True)
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
            raise IndexError_(policy_mismatch_message(checkout_s, path))
        if status == "building":
            conn.close()
            raise IndexError_(f"index for {repo_id} is incomplete at {path}")
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
    _unlink_bundle(path)
    return open_index(
        path, repo_id, checkout=checkout, fingerprint=fingerprint, create=True
    )


def snapshot_ready(path: Path) -> bool:
    """True when ``path`` is a finished index (status ready, current schema)."""
    if not path.is_file():
        return False
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=60.0)
    except sqlite3.DatabaseError:
        return False
    try:
        conn.row_factory = sqlite3.Row
        status = conn.execute(
            "SELECT value FROM meta WHERE key = ?", (META_STATUS,)
        ).fetchone()
        schema = conn.execute(
            "SELECT value FROM meta WHERE key = ?", (META_SCHEMA,)
        ).fetchone()
    except sqlite3.DatabaseError:
        return False
    finally:
        conn.close()
    if status is None or schema is None:
        return False
    try:
        schema_ok = int(schema["value"]) == SCHEMA_VERSION
    except (TypeError, ValueError):
        return False
    return schema_ok and str(status["value"]) == "ready"


def _wal_sidecars(db_path: Path) -> list[Path]:
    return [Path(str(db_path) + suffix) for suffix in ("-wal", "-shm")]


def _wal_bundle_present(db_path: Path) -> bool:
    """True when the canonical file is WAL mode or still has WAL sidecars."""
    if any(path.exists() for path in _wal_sidecars(db_path)):
        return True
    if not db_path.is_file():
        return False
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=0.3)
    except sqlite3.OperationalError:
        # A lock without a sidecar is a rollback-journal reader or writer.
        # Replacing that file leaves the open inode intact.
        return False
    except sqlite3.DatabaseError:
        return False
    try:
        row = conn.execute("PRAGMA journal_mode").fetchone()
    except sqlite3.OperationalError:
        return any(path.exists() for path in _wal_sidecars(db_path))
    finally:
        conn.close()
    return row is not None and str(row[0]).lower() == "wal"


def _file_inodes(paths: list[Path]) -> set[tuple[int, int]]:
    found: set[tuple[int, int]] = set()
    for path in paths:
        try:
            st = path.stat()
        except OSError:
            continue
        found.add((st.st_dev, st.st_ino))
    return found


def _processes_holding_inodes(inodes: set[tuple[int, int]]) -> list[str]:
    """Pids, other than this one, that have any of ``inodes`` open.

    ``["unknown"]`` when ``/proc`` cannot answer. Fail closed in that case.
    Stat of ``/proc/<pid>/fd/<n>`` follows the open file, including an inode
    whose directory entry was already replaced.
    """
    if not inodes:
        return []
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return ["unknown"]
    me = os.getpid()
    holders: list[str] = []
    saw_other_fds = False
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return ["unknown"]
    other = [entry for entry in entries if entry.name.isdigit() and int(entry.name) != me]
    for entry in other:
        try:
            fds = list((entry / "fd").iterdir())
        except OSError:
            continue
        saw_other_fds = True
        for fd in fds:
            try:
                st = os.stat(fd)
            except OSError:
                continue
            if (st.st_dev, st.st_ino) in inodes:
                holders.append(entry.name)
                break
    if other and not saw_other_fds:
        return ["unknown"]
    return holders


def ensure_wal_replace_allowed(db_path: Path) -> None:
    """Refuse to replace a WAL canonical index that another process has open."""
    if not _wal_bundle_present(db_path):
        return
    holders = _processes_holding_inodes(_file_inodes([db_path, *_wal_sidecars(db_path)]))
    if not holders:
        return
    if holders == ["unknown"]:
        detail = "this process cannot see whether another program has the files open"
    else:
        detail = "pid " + ", ".join(holders)
    raise IndexWalBusy(
        f"WAL index at {db_path} is still in use ({detail}). "
        "Stop py-indexer and any other program using this index, then run "
        "py-indexer index again. The upgrade will not replace this database "
        "or remove its -wal/-shm files while they are open. "
        "Content that is still only in the WAL stays on this path."
    )


def discard_staging(db_path: Path) -> None:
    """Remove an unpublished staging bundle and its completion marker."""
    _unlink_bundle(staging_path(db_path))
    _unlink_quiet(_complete_marker(db_path))


def publish_staging(db_path: Path) -> None:
    """Atomically replace the canonical database with a finished staging file.

    The staging connection must already be closed. The file is a single
    rollback-journal database (no WAL sidecar). ``os.replace`` publishes it.
    A WAL canonical bundle that another process still has open is left in
    place, including its ``-wal`` and ``-shm`` files. Unused sidecars are
    removed only after that check. Rollback-journal readers keep the previous
    inode; later opens see the replacement.
    """
    staging = staging_path(db_path)
    if not staging.is_file():
        raise IndexError_(f"missing staging index for publish: {staging}")
    ensure_wal_replace_allowed(db_path)
    previous_inodes = _file_inodes([db_path, *_wal_sidecars(db_path)])
    _fsync_file(staging)
    marker = _complete_marker(db_path)
    marker.write_text("ok\n", encoding="utf-8")
    _fsync_file(marker)
    _fsync_dir(db_path.parent)
    os.replace(staging, db_path)
    _fsync_dir(db_path.parent)
    _unlink_quiet(marker)
    # A process that still has the pre-replace inode open needs the WAL
    # sidecars. Leave them. Do not unlink as a substitute for that process
    # exiting.
    if not _processes_holding_inodes(previous_inodes):
        for side in _sidecar_paths(db_path):
            _unlink_quiet(side)
    _unlink_bundle(_prev_path(db_path))
    _unlink_bundle(staging)


def recover_index_artifacts(db_path: Path) -> None:
    """Apply crash recovery for one checkout database. Caller holds the lock."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    staging = staging_path(db_path)
    marker = _complete_marker(db_path)
    if marker.is_file() and staging.is_file() and snapshot_ready(staging):
        ensure_wal_replace_allowed(db_path)
        os.replace(staging, db_path)
        try:
            _fsync_dir(db_path.parent)
        except OSError:
            pass
    elif staging.exists() or any(side.exists() for side in _sidecar_paths(staging)):
        _unlink_bundle(staging)
    _unlink_quiet(marker)

    prev = _prev_path(db_path)
    prev_exists = prev.exists() or any(side.exists() for side in _sidecar_paths(prev))
    if not prev_exists:
        return
    if snapshot_ready(db_path):
        _unlink_bundle(prev)
        return
    if prev.is_file() and snapshot_ready(prev):
        os.replace(prev, db_path)
        for suffix in ("-wal", "-shm", "-journal"):
            src = Path(str(prev) + suffix)
            if src.exists():
                os.replace(src, Path(str(db_path) + suffix))
        return
    _unlink_bundle(prev)


def backup_database(src: Path, dest: Path) -> None:
    """Copy ``src`` into a new single-file database at ``dest``."""
    _unlink_bundle(dest)
    src_conn = sqlite3.connect(str(src), timeout=60.0)
    try:
        src_conn.execute("PRAGMA busy_timeout=60000")
        dest_conn = sqlite3.connect(str(dest), timeout=60.0)
        try:
            src_conn.backup(dest_conn)
            dest_conn.execute("PRAGMA journal_mode=DELETE")
            dest_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            dest_conn.close()
    finally:
        src_conn.close()
    for side in _sidecar_paths(dest):
        _unlink_quiet(side)


@contextmanager
def checkout_index_lock(db_path: Path, timeout_sec: float = 60.0) -> Iterator[None]:
    """Exclusive interprocess lock for one checkout's index lifecycle.

    The lock file is ``<canonical-db>.lock`` and is not removed (waiters may
    still have it open). Locking is per open-file description via ``flock``.
    """
    if fcntl is None:
        raise IndexError_("checkout index lock requires fcntl (Linux)")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = Path(str(db_path) + ".lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o644)
    deadline = time.monotonic() + timeout_sec
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise IndexLockTimeout(db_path, timeout_sec) from None
                time.sleep(0.05)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)
