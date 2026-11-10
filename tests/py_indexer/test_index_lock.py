#!/usr/bin/env python3
"""Multiprocess tests for the checkout index lock and publication."""

from __future__ import annotations

import json
import multiprocessing
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG_PARENT = ROOT / "tools" / "py-indexer" / "src"
sys.path.insert(0, str(PKG_PARENT))

from py_indexer.config import load_config  # noqa: E402
from py_indexer.index_cmd import index_repository  # noqa: E402
from py_indexer.search_cmd import search  # noqa: E402
from py_indexer.store import IndexLockTimeout, checkout_index_lock  # noqa: E402

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


def _worker_fail(cache: str, cfg_path: str, project: str) -> str:
    os.environ["XDG_CACHE_HOME"] = cache
    os.environ["PY_INDEXER_TEST_FAIL_BEFORE_PUBLISH"] = "1"
    try:
        cfg = load_config(Path(cfg_path), project_root=Path(project))
        index_repository(cfg, "working")
    except RuntimeError as exc:
        return f"fail:{exc}"
    except Exception as exc:  # noqa: BLE001
        return f"err:{type(exc).__name__}:{exc}"
    return "unexpected-success"


def _worker_delayed(cache: str, cfg_path: str, project: str, delay: str) -> str:
    os.environ["XDG_CACHE_HOME"] = cache
    os.environ["PY_INDEXER_TEST_PUBLISH_DELAY"] = delay
    os.environ.pop("PY_INDEXER_TEST_FAIL_BEFORE_PUBLISH", None)
    try:
        cfg = load_config(Path(cfg_path), project_root=Path(project))
        index_repository(cfg, "working")
    except Exception as exc:  # noqa: BLE001
        return f"err:{type(exc).__name__}:{exc}"
    return "ok"


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


def _worker_hold(cache: str, db: str, ready: str, release: str) -> str:
    os.environ["XDG_CACHE_HOME"] = cache
    path = Path(db)
    try:
        with checkout_index_lock(path, timeout_sec=5):
            Path(ready).write_text("ready", encoding="utf-8")
            deadline = time.time() + 10
            while not Path(release).exists():
                if time.time() > deadline:
                    return "release-timeout"
                time.sleep(0.05)
    except Exception as exc:  # noqa: BLE001
        return f"err:{type(exc).__name__}:{exc}"
    return "ok"


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

        opened = None
        mismatch = None
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
                mismatch = exc
                continue
            opened = cfg
            conn.close()
            break
        self.assertIsNotNone(opened)
        self.assertIsNotNone(mismatch)
        self.assertIn("index policy mismatch", str(mismatch))

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
        delayed = CTX.Process(
            target=_worker_delayed,
            args=(str(self.cache), str(self.cfg_path), str(self.project), "0.4"),
        )
        delayed.start()
        delayed.join(60)
        stop.write_text("stop", encoding="utf-8")
        reader.join(60)
        self.assertFalse(delayed.is_alive())
        self.assertFalse(reader.is_alive())
        self.assertEqual(delayed.exitcode, 0)
        self.assertEqual(reader.exitcode, 0)
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
        proc = CTX.Process(
            target=_worker_fail,
            args=(str(self.cache), str(self.cfg_path), str(self.project)),
        )
        proc.start()
        proc.join(60)
        self.assertFalse(proc.is_alive())
        self.assertEqual(proc.exitcode, 0)
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
        holder = CTX.Process(
            target=_worker_hold,
            args=(str(self.cache), str(db), str(ready), str(release)),
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
