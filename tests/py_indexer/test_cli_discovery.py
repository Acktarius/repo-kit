#!/usr/bin/env python3
"""CLI discovery, --config/--project-root, and app-id (stdlib, offline)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "tools" / "py-indexer" / "src"
sys.path.insert(0, str(PKG))

class AppIdTests(unittest.TestCase):
    def test_app_id_json(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-c", "from py_indexer.cli import main; raise SystemExit(main(['--app-id']))"],
            cwd=str(PKG.parent),
            env={**os.environ, "PYTHONPATH": str(PKG)},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["name"], "py-indexer")
        self.assertEqual(doc["compat_version"], "0.3.2")
        self.assertEqual(doc["version"], "0.3.2")
        self.assertEqual(doc["capability"], "staging-publish")
        self.assertEqual(doc["structural_schema_version"], 2)
        self.assertEqual(doc["rules_version"], 3)
        self.assertEqual(len(doc["analysis_fingerprint"]), 64)
        self.assertIsInstance(doc["structural_ready"], bool)
        self.assertTrue(doc["fts5"])
        self.assertTrue(doc["cli_ready"])
        self.assertIsInstance(doc["mcp_ready"], bool)
        self.assertEqual(doc["mcp_api"], "mcp.server.fastmcp.FastMCP")


class DiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="py-indexer-cli "))
        self.cache = self.tmp / "cache"
        self.cache.mkdir()
        self.env = {
            **os.environ,
            "PYTHONPATH": str(PKG),
            "XDG_CACHE_HOME": str(self.cache),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        self.project = self.tmp / "proj"
        nested = self.project / "deep" / "nested"
        nested.mkdir(parents=True)
        tool = self.project / ".repo-kit" / "tools" / "py-indexer"
        tool.mkdir(parents=True)
        (self.project / "src").mkdir()
        (self.project / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
        cfg = {
            "schema_version": 1,
            "active_repo": "proj",
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
                    "id": "proj",
                    "root": ".",
                    "role": "working",
                    "related": [],
                    "include": [],
                    "exclude": [],
                }
            ],
        }
        self.cfg_path = tool / "repos.json"
        self.cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        self.nested = nested

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "py_indexer", *args],
            cwd=str(cwd),
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_upward_discovery(self) -> None:
        proc = self._run(["validate-config"], cwd=self.nested)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["project_root"], str(self.project.resolve()))

    def test_explicit_config_unrelated_cwd(self) -> None:
        other = self.tmp / "elsewhere"
        other.mkdir()
        proc = self._run(
            ["--config", str(self.cfg_path), "validate-config"],
            cwd=other,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_nonstandard_config_needs_project_root(self) -> None:
        custom = self.tmp / "custom.json"
        custom.write_text(self.cfg_path.read_text(encoding="utf-8"), encoding="utf-8")
        proc = self._run(["--config", str(custom), "validate-config"], cwd=self.tmp)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("project-root", proc.stderr)
        proc2 = self._run(
            [
                "--config",
                str(custom),
                "--project-root",
                str(self.project),
                "validate-config",
            ],
            cwd=self.tmp,
        )
        self.assertEqual(proc2.returncode, 0, proc2.stderr)

    def test_missing_config_errors(self) -> None:
        empty = self.tmp / "empty"
        empty.mkdir()
        proc = self._run(["validate-config"], cwd=empty)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no configuration found", proc.stderr)


if __name__ == "__main__":
    unittest.main()
