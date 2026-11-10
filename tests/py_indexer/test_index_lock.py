#!/usr/bin/env python3
"""Multiprocess tests for the checkout index lock and publication."""

from __future__ import annotations

import json
import multiprocessing
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG_PARENT = ROOT / "tools" / "py-indexer" / "src"
sys.path.insert(0, str(PKG_PARENT))

from py_indexer.chunk import chunk_lines, content_hash  # noqa: E402
from py_indexer.config import load_config  # noqa: E402
from py_indexer.index_cmd import index_repository  # noqa: E402
from py_indexer.search_cmd import search  # noqa: E402
from py_indexer.store import (  # noqa: E402
    IndexLockTimeout,
    IndexWalBusy,
    backup_database,
    checkout_index_lock,
    locked_write,
    open_index,
    stamp_success,
    upsert_file,
)

CTX = multiprocessing.get_context("fork")


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _config(root: Path, checkout: Path, *, exclude: list[str] | None = None) -> dict:
    return {
        "schema_version": 1,
        "active_repo": "working",
        "defaults": {
            "max_results": 8,
            "max_snippet_chars": 400,
            "max_total_chars": 4000,
            "chunk_lines": 40,
            "chunk_overlap_lines": 5,
            "max_file_bytes": 100000,
        },
        "repositories": [
            {
                "id": "working",
                "root": str(checkout),
                "role": "working",
                "related": [],
                "include": [],
                "exclude": exclude or [],
            }
        ],
    }


def _worker_index(cache: str, cfg_path: str, project: str) -> None:
    os.environ["XDG_CACHE_HOME"] = cache
    os.environ.pop("PY_INDEXER_TEST_FAIL_BEFORE_PUBLISH", None)
    os.environ.pop("PY_INDEXER_TEST_PUBLISH_DELAY", None)
    cfg = load_config(Path(cfg_path), project_root=Path(project))
    index_repository(cfg, "working")


def _worker_fail(cache: str, cfg_path: str, project: str, result) -> None:
    os.environ["XDG_CACHE_HOME"] = cache
    os.environ["PY_INDEXER_TEST_FAIL_BEFORE_PUBLISH"] = "1"
    try:
        cfg = load_config(Path(cfg_path), project_root=Path(project))
        index_repository(cfg, "working")
    except RuntimeError as exc:
        result.put(f"fail:{exc}")
        return
    except Exception as exc:  # noqa: BLE001
        result.put(f"err:{type(exc).__name__}:{exc}")
        return
    result.put("unexpected-success")


def _worker_delayed(cache: str, cfg_path: str, project: str, delay: str, result) -> None:
    os.environ["XDG_CACHE_HOME"] = cache
    os.environ["PY_INDEXER_TEST_PUBLISH_DELAY"] = delay
    os.environ.pop("PY_INDEXER_TEST_FAIL_BEFORE_PUBLISH", None)
    try:
        cfg = load_config(Path(cfg_path), project_root=Path(project))
        index_repository(cfg, "working")
    except Exception as exc:  # noqa: BLE001
        result.put(f"err:{type(exc).__name__}:{exc}")
        return
    result.put("ok")


def _worker_reader(cache: str, cfg_path: str, project: str, stop: str, result: str) -> None:
    os.environ["XDG_CACHE_HOME"] = cache
    os.environ.pop("PY_INDEXER_TEST_FAIL_BEFORE_PUBLISH", None)
    os.environ.pop("PY_INDEXER_TEST_PUBLISH_DELAY", None)
    cfg = load_config(Path(cfg_path), project_root=Path(project))
    hits = 0
    errors: list[str] = []
    while not Path(stop).exists():
        try:
            resp = search(cfg, "alphaUnique", repo_ids=["working"])
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
            continue
        if resp.hits:
            hits += 1
        for warning in resp.warnings:
            if "policy mismatch" not in warning and "omitted" not in warning:
                errors.append(warning)
        time.sleep(0.02)
    Path(result).write_text(json.dumps({"hits": hits, "errors": errors}), encoding="utf-8")


def _worker_wal_reader(db: str, stop: str, result: str) -> None:
    import sqlite3 as _sqlite

    conn = _sqlite.connect(db, timeout=5)
    seen = 0
    errors: list[str] = []
    while not Path(stop).exists():
        try:
            row = conn.execute("SELECT text FROM chunks").fetchone()
            if row and "walOnlyToken" in row[0]:
                seen += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
        time.sleep(0.05)
    final = ""
    try:
        row = conn.execute("SELECT text FROM chunks").fetchone()
        final = row[0] if row else ""
    except Exception as exc:  # noqa: BLE001
        final = f"err:{exc}"
    conn.close()
    Path(result).write_text(
        json.dumps({"seen": seen, "errors": errors, "final": final}),
        encoding="utf-8",
    )


def _worker_hold(cache: str, db: str, ready: str, release: str, result) -> None:
    os.environ["XDG_CACHE_HOME"] = cache
    path = Path(db)
    try:
        with checkout_index_lock(path, timeout_sec=5):
            Path(ready).write_text("ready", encoding="utf-8")
            deadline = time.time() + 10
            while not Path(release).exists():
                if time.time() > deadline:
                    result.put("release-timeout")
                    return
                time.sleep(0.05)
    except Exception as exc:  # noqa: BLE001
        result.put(f"err:{type(exc).__name__}:{exc}")
        return
    result.put("ok")


class IndexLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="py-indexer-lock-"))
        self.cache = self.tmp / "cache"
        self.cache.mkdir()
        os.environ["XDG_CACHE_HOME"] = str(self.cache)
        os.environ.pop("PY_INDEXER_TEST_FAIL_BEFORE_PUBLISH", None)
        os.environ.pop("PY_INDEXER_TEST_PUBLISH_DELAY", None)
        self.checkout = self.tmp / "checkout"
        self.project = self.tmp / "project"
        self.tool = self.project / ".repo-kit" / "tools" / "py-indexer"
        self.tool.mkdir(parents=True)
        _git_init(self.checkout)
        _write(self.checkout / "src" / "main.ts", "export function alphaUnique() { return 1; }\n")
        self.cfg_path = self.tool / "repos.json"
        self.cfg_path.write_text(
            json.dumps(_config(self.project, self.checkout)),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        os.environ.pop("PY_INDEXER_TEST_FAIL_BEFORE_PUBLISH", None)
        os.environ.pop("PY_INDEXER_TEST_PUBLISH_DELAY", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _cfg(self):
        return load_config(self.cfg_path, project_root=self.project)

    def _db(self) -> Path:
        return self._cfg().db_path("working")

    def _leftovers(self, db: Path) -> list[Path]:
        names = [
            Path(str(db) + ".staging"),
            Path(str(db) + ".staging.complete"),
            Path(str(db) + ".prev"),
            Path(str(db) + "-wal"),
            Path(str(db) + "-shm"),
        ]
        return [path for path in names if path.exists()]

    def test_concurrent_first_creation(self) -> None:
        args = (str(self.cache), str(self.cfg_path), str(self.project))
        procs = [CTX.Process(target=_worker_index, args=args) for _ in range(2)]
        for proc in procs:
            proc.start()
        for proc in procs:
            proc.join(60)
            self.assertFalse(proc.is_alive())
            self.assertEqual(proc.exitcode, 0)
        db = self._db()
        self.assertTrue(db.is_file())
        self.assertEqual(self._leftovers(db), [])
        resp = search(self._cfg(), "alphaUnique", repo_ids=["working"])
        self.assertTrue(resp.hits)

    def test_concurrent_incremental(self) -> None:
        index_repository(self._cfg(), "working")
        _write(self.checkout / "src" / "extra.ts", "export const extraUnique = 2;\n")
        args = (str(self.cache), str(self.cfg_path), str(self.project))
        procs = [CTX.Process(target=_worker_index, args=args) for _ in range(2)]
        for proc in procs:
            proc.start()
        for proc in procs:
            proc.join(60)
            self.assertFalse(proc.is_alive())
            self.assertEqual(proc.exitcode, 0)
        db = self._db()
        self.assertEqual(self._leftovers(db), [])
        resp = search(self._cfg(), "extraUnique", repo_ids=["working"])
        self.assertTrue(resp.hits)
        self.assertEqual(list(self.cache.rglob("*.sqlite3")).__len__(), 1)

    def test_concurrent_settings_rebuilds(self) -> None:
        other = self.tmp / "other"
        other_tool = other / ".repo-kit" / "tools" / "py-indexer"
        other_tool.mkdir(parents=True)
        other_cfg_path = other_tool / "repos.json"
        other_cfg_path.write_text(
            json.dumps(_config(other, self.checkout, exclude=["*.generated.ts"])),
            encoding="utf-8",
        )
        broad = self._cfg()
        narrow = load_config(other_cfg_path, project_root=other)
        self.assertEqual(broad.db_path("working"), narrow.db_path("working"))
        self.assertNotEqual(
            broad.content_fingerprint("working"),
            narrow.content_fingerprint("working"),
        )
        procs = [
            CTX.Process(
                target=_worker_index,
                args=(str(self.cache), str(self.cfg_path), str(self.project)),
            ),
            CTX.Process(
                target=_worker_index,
                args=(str(self.cache), str(other_cfg_path), str(other)),
            ),
        ]
        for proc in procs:
            proc.start()
        for proc in procs:
            proc.join(60)
            self.assertFalse(proc.is_alive())
            self.assertEqual(proc.exitcode, 0)
        db = broad.db_path("working")
        self.assertTrue(db.is_file())
        self.assertEqual(self._leftovers(db), [])
        from py_indexer.store import open_index

        outcomes = []
        for cfg in (broad, narrow):
            try:
                conn = open_index(
                    db,
                    "working",
                    checkout=self.checkout,
                    fingerprint=cfg.content_fingerprint("working"),
                    create=False,
                )
            except Exception as exc:  # noqa: BLE001
                outcomes.append(("mismatch", str(exc)))
                continue
            conn.close()
            outcomes.append(("ok", cfg))
        self.assertEqual([kind for kind, _ in outcomes].count("ok"), 1, outcomes)
        self.assertEqual([kind for kind, _ in outcomes].count("mismatch"), 1, outcomes)
        mismatch = next(detail for kind, detail in outcomes if kind == "mismatch")
        self.assertIn("index policy mismatch", mismatch)

    def test_readers_during_rebuild(self) -> None:
        index_repository(self._cfg(), "working")
        stop = self.tmp / "stop"
        result = self.tmp / "reader.json"
        reader = CTX.Process(
            target=_worker_reader,
            args=(str(self.cache), str(self.cfg_path), str(self.project), str(stop), str(result)),
        )
        reader.start()
        time.sleep(0.1)
        _write(self.checkout / "src" / "main.ts", "export function alphaUnique() { return 9; }\n")
        delayed_result = CTX.Queue()
        delayed = CTX.Process(
            target=_worker_delayed,
            args=(str(self.cache), str(self.cfg_path), str(self.project), "0.4", delayed_result),
        )
        delayed.start()
        delayed.join(60)
        stop.write_text("stop", encoding="utf-8")
        reader.join(60)
        self.assertFalse(delayed.is_alive())
        self.assertFalse(reader.is_alive())
        self.assertEqual(delayed.exitcode, 0)
        self.assertEqual(reader.exitcode, 0)
        self.assertEqual(delayed_result.get(timeout=5), "ok")
        report = json.loads(result.read_text(encoding="utf-8"))
        self.assertEqual(report["errors"], [], report)
        self.assertGreater(report["hits"], 0, report)
        db = self._db()
        self.assertEqual(self._leftovers(db), [])
        resp = search(self._cfg(), "alphaUnique", repo_ids=["working"])
        self.assertTrue(resp.hits)

    def test_failed_rebuild_keeps_snapshot(self) -> None:
        index_repository(self._cfg(), "working")
        db = self._db()
        before = db.read_bytes()
        failed = CTX.Queue()
        proc = CTX.Process(
            target=_worker_fail,
            args=(str(self.cache), str(self.cfg_path), str(self.project), failed),
        )
        proc.start()
        proc.join(60)
        self.assertFalse(proc.is_alive())
        self.assertEqual(proc.exitcode, 0)
        self.assertEqual(failed.get(timeout=5), "fail:injected failure before index publish")
        self.assertEqual(db.read_bytes(), before)
        self.assertEqual(self._leftovers(db), [])
        resp = search(self._cfg(), "alphaUnique", repo_ids=["working"])
        self.assertTrue(resp.hits)
        self.assertFalse(any("policy mismatch" in w for w in resp.warnings))

    def test_lock_timeout(self) -> None:
        db = self.cache / "py-indexer" / "indexes" / "held.sqlite3"
        db.parent.mkdir(parents=True)
        ready = self.tmp / "ready"
        release = self.tmp / "release"
        held = CTX.Queue()
        holder = CTX.Process(
            target=_worker_hold,
            args=(str(self.cache), str(db), str(ready), str(release), held),
        )
        holder.start()
        deadline = time.time() + 5
        while not ready.exists():
            self.assertLess(time.time(), deadline, "holder did not acquire the lock")
            time.sleep(0.05)
        started = time.monotonic()
        with self.assertRaises(IndexLockTimeout):
            with checkout_index_lock(db, timeout_sec=0.3):
                pass
        self.assertGreaterEqual(time.monotonic() - started, 0.25)
        release.write_text("go", encoding="utf-8")
        holder.join(10)
        self.assertEqual(holder.exitcode, 0)
        self.assertEqual(held.get(timeout=5), "ok")

    def _write_uncheckpointed_wal(self) -> Path:
        """Canonical WAL index whose searchable token exists only in the WAL.

        SQLite checkpoints a WAL when the last connection closes. The writer
        disables that so the committed row stays in ``-wal`` after close.
        """
        token = "walOnlyToken"
        _write(self.checkout / "src" / "main.ts", f"export const {token} = 1;\n")
        cfg = self._cfg()
        db = cfg.db_path("working")
        fingerprint = cfg.content_fingerprint("working")
        created = open_index(
            db,
            "working",
            checkout=self.checkout,
            fingerprint=fingerprint,
            create=True,
        )
        created.close()
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        self._no_checkpoint_on_close(conn)
        mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        self.assertEqual(str(mode).lower(), "wal")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        text = (self.checkout / "src" / "main.ts").read_text(encoding="utf-8")
        with locked_write(conn):
            upsert_file(
                conn,
                path="src/main.ts",
                content_hash=content_hash(text),
                size=len(text.encode()),
                mtime_ns=0,
                language="typescript",
                chunks=chunk_lines(text, chunk_lines=40, overlap=5),
            )
            stamp_success(
                conn,
                git_revision=None,
                repo_id="working",
                checkout=self.checkout,
                fingerprint=fingerprint,
            )
        conn.close()
        self.assertNotIn(token.encode(), db.read_bytes())
        wal = Path(str(db) + "-wal")
        self.assertTrue(wal.is_file())
        self.assertIn(token.encode(), wal.read_bytes())
        check = sqlite3.connect(db)
        self._no_checkpoint_on_close(check)
        try:
            stored = check.execute("SELECT text FROM chunks").fetchone()[0]
        finally:
            check.close()
        self.assertIn(token, stored)
        self.assertNotIn(token.encode(), db.read_bytes())
        return db

    def _no_checkpoint_on_close(self, conn: sqlite3.Connection) -> None:
        import ctypes
        import ctypes.util

        lib = ctypes.CDLL(ctypes.util.find_library("sqlite3"))
        lib.sqlite3_db_filename.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.sqlite3_db_filename.restype = ctypes.c_char_p
        lib.sqlite3_db_config.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        lib.sqlite3_db_config.restype = ctypes.c_int
        # CPython sqlite3.Connection stores the sqlite3* immediately after PyObject_HEAD.
        raw = ctypes.cast(id(conn), ctypes.POINTER(ctypes.c_void_p))
        ptr = raw[2]
        name = lib.sqlite3_db_filename(ptr, b"main")
        self.assertTrue(name, "sqlite3 connection pointer was not found")
        out = ctypes.c_int()
        rc = lib.sqlite3_db_config(ptr, 1006, 1, ctypes.byref(out))
        self.assertEqual(rc, 0, "SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE failed")

    def test_wal_upgrade_preserves_uncheckpointed_content(self) -> None:
        db = self._write_uncheckpointed_wal()
        main = db.read_bytes()
        wal = Path(str(db) + "-wal")
        wal_bytes = wal.read_bytes()
        self.assertNotIn(b"walOnlyToken", main)
        self.assertIn(b"walOnlyToken", wal_bytes)
        side = self.tmp / "wal-backup.sqlite3"
        backup_database(db, side)
        self.assertIn(b"walOnlyToken", side.read_bytes())
        # backup's connection close may checkpoint. Put the uncheckpointed
        # bundle back so the upgrade itself starts from that state.
        db.write_bytes(main)
        wal.write_bytes(wal_bytes)
        Path(str(db) + "-shm").unlink(missing_ok=True)
        self.assertNotIn(b"walOnlyToken", db.read_bytes())
        inode_before = db.stat().st_ino
        stats = index_repository(self._cfg(), "working")
        self.assertGreaterEqual(stats["unchanged"], 1, stats)
        self.assertEqual(stats["added"], 0, stats)
        self.assertEqual(self._db(), db)
        self.assertNotEqual(db.stat().st_ino, inode_before)
        mode = sqlite3.connect(db).execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(str(mode).lower(), "delete")
        self.assertFalse(Path(str(db) + "-wal").exists())
        self.assertFalse(Path(str(db) + "-shm").exists())
        self.assertEqual(len(list(self.cache.rglob("*.sqlite3"))), 1)
        resp = search(self._cfg(), "walOnlyToken", repo_ids=["working"])
        self.assertTrue(resp.hits)

    def test_wal_upgrade_leaves_active_reader(self) -> None:
        db = self._write_uncheckpointed_wal()
        inode = db.stat().st_ino
        wal = Path(str(db) + "-wal")
        wal_inode = wal.stat().st_ino
        stop = self.tmp / "wal-stop"
        result = self.tmp / "wal-reader.json"
        proc = CTX.Process(
            target=_worker_wal_reader,
            args=(str(db), str(stop), str(result)),
        )
        proc.start()
        time.sleep(0.2)
        with self.assertRaises(IndexWalBusy) as raised:
            index_repository(self._cfg(), "working")
        self.assertIn("still in use", str(raised.exception))
        self.assertIn("will not replace", str(raised.exception))
        self.assertEqual(db.stat().st_ino, inode)
        self.assertTrue(wal.is_file())
        self.assertEqual(wal.stat().st_ino, wal_inode)
        self.assertTrue(Path(str(db) + "-shm").exists())
        stop.write_text("stop", encoding="utf-8")
        proc.join(10)
        self.assertEqual(proc.exitcode, 0)
        report = json.loads(result.read_text(encoding="utf-8"))
        self.assertEqual(report["errors"], [], report)
        self.assertGreater(report["seen"], 0, report)
        self.assertIn("walOnlyToken", report["final"])
        mode = sqlite3.connect(db).execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(str(mode).lower(), "wal")

    def test_success_drops_prev(self) -> None:
        index_repository(self._cfg(), "working")
        db = self._db()
        prev = Path(str(db) + ".prev")
        prev.write_bytes(b"stale")
        index_repository(self._cfg(), "working")
        self.assertFalse(prev.exists())
        self.assertEqual(self._leftovers(db), [])


if __name__ == "__main__":
    unittest.main()
