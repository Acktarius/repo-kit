#!/usr/bin/env python3
"""Stdlib unit tests for py-indexer (no mcp / no network)."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

# Load package from kit source files/ tree (not an installed target).
ROOT = Path(__file__).resolve().parents[2]
PKG_PARENT = ROOT / "tools" / "py-indexer" / "files" / ".repo-kit" / "tools" / "py-indexer"
import sys

sys.path.insert(0, str(PKG_PARENT))

from py_indexer.chunk import chunk_lines  # noqa: E402
from py_indexer.config import ConfigError, load_config  # noqa: E402
from py_indexer.exclude import iter_candidate_files  # noqa: E402
from py_indexer.index_cmd import index_repository  # noqa: E402
from py_indexer.paths import is_safe_repo_id, safe_join  # noqa: E402
from py_indexer.read_cmd import read_code  # noqa: E402
from py_indexer.search_cmd import sanitize_fts_query, search  # noqa: E402
from py_indexer.store import IndexError_, open_index  # noqa: E402


def _git_init(path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class PathsTests(unittest.TestCase):
    def test_safe_repo_id(self) -> None:
        self.assertTrue(is_safe_repo_id("conceal-core"))
        self.assertFalse(is_safe_repo_id("../x"))
        self.assertFalse(is_safe_repo_id("a/b"))

    def test_safe_join_rejects_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(ValueError):
                safe_join(root, "../etc/passwd")


class ChunkTests(unittest.TestCase):
    def test_chunk_windows(self) -> None:
        text = "\n".join(f"line{i}" for i in range(1, 101))
        chunks = chunk_lines(text, chunk_lines=40, overlap=10)
        self.assertGreaterEqual(len(chunks), 3)
        self.assertEqual(chunks[0].start_line, 1)
        self.assertEqual(chunks[0].end_line, 40)


class ConfigTests(unittest.TestCase):
    def test_validation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "app"
            tool = target / ".repo-kit" / "tools" / "py-indexer"
            tool.mkdir(parents=True)
            (target / "src").mkdir(parents=True)
            cfg_path = tool / "repos.json"
            cfg_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "active_repo": "app",
                        "defaults": {
                            "max_results": 5,
                            "max_snippet_chars": 200,
                            "max_total_chars": 2000,
                            "chunk_lines": 40,
                            "chunk_overlap_lines": 5,
                            "max_file_bytes": 100000,
                        },
                        "repositories": [
                            {
                                "id": "app",
                                "root": ".",
                                "role": "working",
                                "related": ["missing"],
                                "include": [],
                                "exclude": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError):
                load_config(cfg_path, target_root=target, tool_root=tool)


class IndexSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.target = self.tmp / "working"
        self.ref = self.tmp / "reference"
        self.tool = self.target / ".repo-kit" / "tools" / "py-indexer"
        self.tool.mkdir(parents=True)
        (self.tool / "index").mkdir()
        _git_init(self.target)
        _git_init(self.ref)
        _write(self.target / "src" / "main.ts", "export function alphaUnique() {\n  return 1;\n}\n")
        _write(self.ref / "lib" / "util.ts", "export function betaUnique() {\n  return 2;\n}\n")
        _write(self.target / ".env", "SECRET=1\n")
        _write(self.target / "src" / "big.bin", "\x00\x01\x02binary")
        cfg = {
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
                    "root": ".",
                    "role": "working",
                    "related": ["reference"],
                    "include": [],
                    "exclude": [],
                },
                {
                    "id": "reference",
                    "root": str(self.ref),
                    "role": "reference",
                    "related": [],
                    "include": [],
                    "exclude": [],
                },
            ],
        }
        self.cfg_path = self.tool / "repos.json"
        self.cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        self.cfg = load_config(self.cfg_path, target_root=self.target, tool_root=self.tool)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_exclusions_and_related_search(self) -> None:
        _write(self.tool / "excludes.txt", "build/\n.env\n*.pem\n")
        _write(self.target / "build" / "out.js", "shouldNotIndexBuildArtifact()\n")
        _write(self.target / "src" / "ok.ts", "export const keepMe = 1;\n")
        _write(self.target / ".gitignore", "ignored-secret.ts\nbuild/\n")
        _write(self.target / "ignored-secret.ts", "export const leakToken = 1;\n")
        _write(self.target / ".py-indexer-ignore", "src/skip-me.ts\n")
        _write(self.target / "src" / "skip-me.ts", "export const skipMe = 1;\n")
        # Commit so git ls-files sees tracked paths; ignored files stay untracked+ignored.
        import subprocess

        subprocess.run(["git", "-C", str(self.target), "add", "src", ".gitignore"], check=True)
        subprocess.run(
            ["git", "-C", str(self.target), "commit", "-q", "-m", "seed"],
            check=True,
        )

        paths = [rel for rel, _ in iter_candidate_files(
            self.target,
            include=[],
            exclude=[],
            max_file_bytes=100000,
            tool_root=self.tool,
        )]
        self.assertIn("src/main.ts", paths)
        self.assertIn("src/ok.ts", paths)
        self.assertNotIn(".env", paths)
        self.assertNotIn("build/out.js", paths)
        self.assertNotIn("ignored-secret.ts", paths)
        self.assertNotIn("src/skip-me.ts", paths)

        index_repository(self.cfg, "working")
        index_repository(self.cfg, "reference")

        resp = search(self.cfg, "betaUnique", scope="active+related")
        repos = {h.repo_id for h in resp.hits}
        self.assertIn("reference", repos)

        only = search(self.cfg, "alphaUnique", repo_ids=["working"])
        self.assertTrue(all(h.repo_id == "working" for h in only.hits))
        self.assertTrue(all(h.from_index_snapshot for h in only.hits))

        leak = search(self.cfg, "leakToken", repo_ids=["working"])
        self.assertEqual(leak.hits, [])
        build_hit = search(self.cfg, "shouldNotIndexBuildArtifact", repo_ids=["working"])
        self.assertEqual(build_hit.hits, [])

    def test_unusual_query_and_budgets(self) -> None:
        # Operators / punctuation must not crash; tokens become quoted AND terms.
        q = sanitize_fts_query('^^^ """ OR AND * ((boom~~')
        self.assertNotIn("*", q)
        self.assertTrue(q == "" or "AND" in q or q.startswith('"'))
        index_repository(self.cfg, "working")
        from py_indexer.budgets import Budgets

        self.cfg.budgets = Budgets(
            max_results=2,
            max_snippet_chars=40,
            max_total_chars=50,
            max_file_bytes=self.cfg.budgets.max_file_bytes,
        )
        resp = search(self.cfg, "alphaUnique")
        self.assertLessEqual(resp.total_chars, self.cfg.budgets.max_total_chars)

    def test_incremental_add_modify_delete(self) -> None:
        index_repository(self.cfg, "working")
        _write(self.target / "src" / "new.ts", "export const gammaUnique = 3;\n")
        _write(self.target / "src" / "main.ts", "export function alphaUnique() {\n  return 42;\n}\n")
        (self.target / "src" / "new.ts").write_text("export const gammaUnique = 3;\n", encoding="utf-8")
        stats = index_repository(self.cfg, "working")
        self.assertGreaterEqual(stats["added"] + stats["modified"], 1)
        (self.target / "src" / "new.ts").unlink()
        stats2 = index_repository(self.cfg, "working")
        self.assertGreaterEqual(stats2["deleted"], 1)
        resp = search(self.cfg, "gammaUnique", repo_ids=["working"])
        self.assertEqual(resp.hits, [])

    def test_working_tree_differs_from_index(self) -> None:
        index_repository(self.cfg, "working")
        _write(self.target / "src" / "main.ts", "export function alphaUnique() {\n  return 99;\n}\n")
        result = read_code(
            self.cfg, repo_id="working", path="src/main.ts", start_line=1, end_line=3
        )
        self.assertTrue(result.differs_from_index)
        self.assertFalse(result.from_index_snapshot)

    def test_symlink_escape_and_traversal(self) -> None:
        outside = self.tmp / "secret.txt"
        outside.write_text("nope", encoding="utf-8")
        link = self.target / "src" / "escape.ts"
        try:
            link.symlink_to(outside)
        except OSError:
            self.skipTest("symlinks unavailable")
        # Indexer should not leave root via file symlink target outside
        index_repository(self.cfg, "working")
        with self.assertRaises(Exception):
            read_code(self.cfg, repo_id="working", path="../secret.txt", start_line=1, end_line=1)

    def test_corrupt_and_missing_index(self) -> None:
        resp = search(self.cfg, "alphaUnique")
        self.assertTrue(any("missing index" in w for w in resp.warnings))
        index_repository(self.cfg, "working")
        db = self.tool / "index" / "working.sqlite3"
        db.write_bytes(b"not a database")
        with self.assertRaises(IndexError_):
            open_index(self.tool, "working", create=False)

    def test_concurrent_read_during_update(self) -> None:
        index_repository(self.cfg, "working")
        errors: list[str] = []

        def reader() -> None:
            for _ in range(20):
                try:
                    search(self.cfg, "alphaUnique", repo_ids=["working"])
                except Exception as exc:  # noqa: BLE001
                    errors.append(str(exc))
                time.sleep(0.01)

        t = threading.Thread(target=reader)
        t.start()
        for i in range(5):
            _write(self.target / "src" / "main.ts", f"export function alphaUnique() {{ return {i}; }}\n")
            index_repository(self.cfg, "working")
        t.join()
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
