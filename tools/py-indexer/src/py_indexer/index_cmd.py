"""Incremental indexing into the one database for a checkout.

The writer holds ``checkout_index_lock`` across recovery, identity/policy
revalidation, staging, and publication. ``BEGIN IMMEDIATE`` still wraps the
SQL write, but only on the staging connection. The canonical file is replaced
with ``os.replace`` after the staging database is closed and fsynced.

``PY_INDEXER_TEST_FAIL_BEFORE_PUBLISH=1`` raises after a successful staging
build and before replace (tests). ``PY_INDEXER_TEST_PUBLISH_DELAY`` sleeps for
that many seconds in the same window. ``PY_INDEXER_TEST_WAL_GATE_DELAY`` sleeps
after the pre-replace ``/proc`` check and before SQLite is asked to leave WAL
mode. ``PY_INDEXER_TEST_WAL_GATE_READY`` is a file written at the start of that
sleep. None of these are set in normal use.
"""

from __future__ import annotations

import hashlib
import json
import os
import time

from py_indexer.chunk import chunk_lines, content_hash
from py_indexer.config import AppConfig
from py_indexer.exclude import iter_candidate_files, language_for
from py_indexer.extract import extract_file
from py_indexer.gitinfo import git_head, indexed_content_is_dirty
from py_indexer.relate import rebuild_relationships, write_file_facts
from py_indexer.store import (
    backup_database,
    checkout_index_lock,
    ensure_wal_replace_allowed,
    delete_file,
    discard_staging,
    list_files,
    locked_write,
    open_index,
    publish_staging,
    read_meta,
    recover_index_artifacts,
    set_meta,
    snapshot_ready,
    staging_path,
    stamp_success,
    upsert_file,
    META_STATUS,
    _meta_get,
)
from py_indexer.structural import (
    META_ANALYSIS_FINGERPRINT,
    META_INDEXED_DIRTY,
    META_PARSER_RUNTIME,
    META_SNAPSHOT,
    META_STRUCTURAL_STATUS,
    code_fingerprint,
    ensure_structural_schema,
    file_fingerprint,
    runtime_token,
)


def _file_hash_and_text(path: Path, max_bytes: int) -> tuple[str, str, int, int]:
    data = path.read_bytes()
    if len(data) > max_bytes:
        raise OSError("file exceeds max_file_bytes")
    text = data.decode("utf-8", errors="replace")
    st = path.stat()
    return content_hash(text), text, st.st_size, getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))


def _test_publish_gate() -> None:
    delay = os.environ.get("PY_INDEXER_TEST_PUBLISH_DELAY", "").strip()
    if delay:
        time.sleep(float(delay))
    if os.environ.get("PY_INDEXER_TEST_FAIL_BEFORE_PUBLISH") == "1":
        raise RuntimeError("injected failure before index publish")


def index_repository(cfg: AppConfig, repo_id: str) -> dict:
    repo = cfg.get(repo_id)
    db_path = cfg.db_path(repo_id)
    conn = None
    with checkout_index_lock(db_path):
        # Refuse a WAL bundle /proc can already see open, before this process
        # opens it. A reader that arrives later still blocks the replace:
        # publication waits until SQLite leaves WAL mode.
        ensure_wal_replace_allowed(db_path)
        recover_index_artifacts(db_path)
        # Policy is read again after the lock so a concurrent writer cannot
        # publish a different snapshot underneath this decision.
        fingerprint = cfg.content_fingerprint(repo_id)
        discard_staging(db_path)
        incremental = False
        if snapshot_ready(db_path):
            try:
                existing = open_index(
                    db_path,
                    repo_id,
                    checkout=repo.root,
                    fingerprint=fingerprint,
                    create=False,
                )
            except Exception:
                existing = None
            if existing is not None:
                existing.close()
                incremental = True
        try:
            if incremental:
                backup_database(db_path, staging_path(db_path))
                conn = open_index(
                    staging_path(db_path),
                    repo_id,
                    checkout=repo.root,
                    fingerprint=fingerprint,
                    create=False,
                )
            else:
                conn = open_index(
                    staging_path(db_path),
                    repo_id,
                    checkout=repo.root,
                    fingerprint=fingerprint,
                    create=True,
                )
            stats = _index_into(conn, cfg, repo_id)
            conn.close()
            conn = None
            _test_publish_gate()
            publish_staging(db_path)
            return stats
        except Exception:
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
                conn = None
            discard_staging(db_path)
            raise


def _index_into(conn, cfg: AppConfig, repo_id: str) -> dict:
    repo = cfg.get(repo_id)
    seen: set[str] = set()
    added = modified = unchanged = deleted = 0

    with locked_write(conn):
        set_meta(conn, META_STATUS, "building")
        ensure_structural_schema(conn)
        structure_fp = file_fingerprint()
        existing = list_files(conn)
        for rel, path in iter_candidate_files(
            repo.root,
            include=repo.include,
            exclude=repo.exclude,
            max_file_bytes=cfg.budgets.max_file_bytes,
            config_dir=cfg.config_dir,
        ):
            seen.add(rel)
            try:
                digest, text, size, mtime_ns = _file_hash_and_text(
                    path, cfg.budgets.max_file_bytes
                )
            except OSError:
                continue
            prev = existing.get(rel)
            lexical_same = prev is not None and prev["content_hash"] == digest
            if lexical_same and _structure_current(conn, rel, structure_fp):
                unchanged += 1
                continue
            if not lexical_same:
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
            else:
                unchanged += 1
            write_file_facts(conn, rel, extract_file(rel, text), structure_fp)

        for old_path in list(existing):
            if old_path not in seen:
                delete_file(conn, old_path)
                deleted += 1

        started = time.perf_counter()
        rebuilt = rebuild_relationships(conn)
        rebuild_ms = int((time.perf_counter() - started) * 1000)
        dirty = indexed_content_is_dirty(repo.root, seen)
        stamp_success(
            conn,
            git_revision=git_head(repo.root),
            repo_id=repo_id,
            checkout=repo.root,
            fingerprint=cfg.content_fingerprint(repo_id),
        )
        set_meta(conn, META_ANALYSIS_FINGERPRINT, code_fingerprint())
        set_meta(conn, META_PARSER_RUNTIME, runtime_token())
        set_meta(conn, META_INDEXED_DIRTY, "1" if dirty else "0" if dirty is False else "")
        set_meta(conn, META_STRUCTURAL_STATUS, _structural_status(conn))
        set_meta(conn, META_SNAPSHOT, _snapshot_id(conn))
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
        "structural_status": _meta_get(conn, META_STRUCTURAL_STATUS),
        "relationship_rebuild_ms": rebuild_ms,
        "relationships": rebuilt["relationships"],
    }


def _structure_current(conn, path: str, fingerprint: str) -> bool:
    row = conn.execute(
        "SELECT parser_fingerprint FROM file_structure WHERE path = ?",
        (path,),
    ).fetchone()
    return row is not None and row["parser_fingerprint"] == fingerprint


def _structural_status(conn) -> str:
    rows = conn.execute("SELECT DISTINCT status FROM file_structure").fetchall()
    statuses = {row["status"] for row in rows}
    if statuses & {"partial", "failed", "parser_unavailable"}:
        return "partial"
    if not statuses:
        return "unavailable"
    return "ready"


def _snapshot_id(conn) -> str:
    payload = {
        "analysis": _meta_get(conn, META_ANALYSIS_FINGERPRINT),
        "policy": _meta_get(conn, "content_fingerprint"),
        "git": _meta_get(conn, "git_revision"),
        "at": _meta_get(conn, "indexed_at"),
        "dirty": _meta_get(conn, META_INDEXED_DIRTY),
        "structural": _meta_get(conn, META_STRUCTURAL_STATUS),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "snap_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def index_all(cfg: AppConfig) -> list[dict]:
    return [index_repository(cfg, rid) for rid in cfg.repositories]
