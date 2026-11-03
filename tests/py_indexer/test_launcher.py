#!/usr/bin/env python3
"""Unit tests for the py-indexer bin launcher (venv detection + broken venv)."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = (
    ROOT
    / "tools"
    / "py-indexer"
    / "files"
    / ".repo-kit"
    / "tools"
    / "py-indexer"
    / "bin"
    / "py-indexer"
)


def _load_launcher():
    # Extensionless bin/py-indexer needs an explicit SourceFileLoader.
    loader = importlib.machinery.SourceFileLoader(
        "py_indexer_bin_launcher", str(LAUNCHER)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class PreferVenvTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load_launcher()
        self.tmp = Path(tempfile.mkdtemp())
        self.venv = self.tmp / ".venv"
        self.venv_python = self.venv / "bin" / "python"
        self.venv_python.parent.mkdir(parents=True)
        self.venv_python.write_text("#!/bin/sh\n", encoding="utf-8")
        self.venv_python.chmod(0o755)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_skips_when_already_in_tool_venv(self) -> None:
        calls: list[tuple[str, list[str]]] = []

        def boom(path: str, args: list[str]) -> None:
            calls.append((path, args))
            raise AssertionError("must not re-exec inside tool venv")

        with (
            mock.patch.object(self.mod.sys, "prefix", str(self.venv)),
            mock.patch.object(self.mod.os, "execv", side_effect=boom),
        ):
            self.mod._prefer_venv(self.tmp)
        self.assertEqual(calls, [])

    def test_reexec_from_system_prefix(self) -> None:
        calls: list[tuple[str, list[str]]] = []

        def capture(path: str, args: list[str]) -> None:
            calls.append((path, list(args)))
            raise SystemExit(0)

        with (
            mock.patch.object(self.mod.sys, "prefix", "/usr"),
            mock.patch.object(self.mod.sys, "argv", ["py-indexer", "validate-config"]),
            mock.patch.object(self.mod.os, "execv", side_effect=capture),
            self.assertRaises(SystemExit) as ctx,
        ):
            self.mod._prefer_venv(self.tmp)

        # capture raises SystemExit(0); real execv never returns.
        self.assertEqual(ctx.exception.code, 0)
        self.assertEqual(len(calls), 1)
        path, args = calls[0]
        self.assertEqual(path, str(self.venv_python))
        self.assertEqual(args[0], str(self.venv_python))
        self.assertTrue(args[1].endswith("/bin/py-indexer"))
        self.assertEqual(args[2:], ["validate-config"])

    def test_reexec_from_unrelated_venv(self) -> None:
        other = self.tmp / "other-venv"
        calls: list[str] = []

        def capture(path: str, args: list[str]) -> None:
            calls.append(path)
            raise SystemExit(0)

        with (
            mock.patch.object(self.mod.sys, "prefix", str(other)),
            mock.patch.object(self.mod.sys, "argv", ["py-indexer", "status"]),
            mock.patch.object(self.mod.os, "execv", side_effect=capture),
            self.assertRaises(SystemExit),
        ):
            self.mod._prefer_venv(self.tmp)

        self.assertEqual(calls, [str(self.venv_python)])

    def test_noop_when_venv_absent(self) -> None:
        bare = self.tmp / "bare"
        bare.mkdir()
        with mock.patch.object(self.mod.os, "execv") as execv:
            self.mod._prefer_venv(bare)
        execv.assert_not_called()

    def test_missing_interpreter_fails(self) -> None:
        self.venv_python.unlink()
        with (
            mock.patch.object(self.mod.sys, "prefix", "/usr"),
            self.assertRaises(SystemExit) as ctx,
        ):
            self.mod._prefer_venv(self.tmp)
        self.assertEqual(ctx.exception.code, 1)

    def test_dangling_symlink_fails(self) -> None:
        self.venv_python.unlink()
        self.venv_python.symlink_to(self.tmp / "missing-python-binary")
        with (
            mock.patch.object(self.mod.sys, "prefix", "/usr"),
            self.assertRaises(SystemExit) as ctx,
        ):
            self.mod._prefer_venv(self.tmp)
        self.assertEqual(ctx.exception.code, 1)

    def test_non_executable_fails(self) -> None:
        self.venv_python.chmod(0o644)
        with (
            mock.patch.object(self.mod.sys, "prefix", "/usr"),
            self.assertRaises(SystemExit) as ctx,
        ):
            self.mod._prefer_venv(self.tmp)
        self.assertEqual(ctx.exception.code, 1)

    def test_execv_failure_fails_cleanly(self) -> None:
        with (
            mock.patch.object(self.mod.sys, "prefix", "/usr"),
            mock.patch.object(
                self.mod.os,
                "execv",
                side_effect=OSError(8, "Exec format error"),
            ),
            self.assertRaises(SystemExit) as ctx,
        ):
            self.mod._prefer_venv(self.tmp)
        self.assertEqual(ctx.exception.code, 1)


class LauncherSubprocessTests(unittest.TestCase):
    """Subprocess checks including paths/args with spaces."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="py-indexer launch "))

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_broken_venv_cases_and_spaces(self) -> None:
        import json
        import shutil

        other_cwd = self.tmp / "cwd with spaces"
        other_cwd.mkdir(parents=True)
        target = self.tmp / "project with spaces" / "app"
        tool = target / ".repo-kit" / "tools" / "py-indexer"
        shutil.copytree(
            ROOT
            / "tools"
            / "py-indexer"
            / "files"
            / ".repo-kit"
            / "tools"
            / "py-indexer",
            tool,
        )
        (tool / "index").mkdir(parents=True, exist_ok=True)
        cfg = {
            "schema_version": 1,
            "active_repo": "app",
            "defaults": {
                "max_results": 5,
                "max_snippet_chars": 100,
                "max_total_chars": 1000,
                "chunk_lines": 40,
                "chunk_overlap_lines": 5,
                "max_file_bytes": 10000,
            },
            "repositories": [
                {
                    "id": "app",
                    "root": ".",
                    "role": "working",
                    "related": [],
                    "include": [],
                    "exclude": [],
                }
            ],
        }
        (tool / "repos.json").write_text(json.dumps(cfg), encoding="utf-8")
        launcher = tool / "bin" / "py-indexer"
        launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR)
        cfg_path = tool / "repos.json"

        def run_case() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [
                    sys.executable,
                    str(launcher),
                    "--config",
                    str(cfg_path),
                    "validate-config",
                ],
                cwd=str(other_cwd),
                capture_output=True,
                text=True,
                timeout=20,
            )

        # Absent .venv → fallback works.
        proc = run_case()
        self.assertEqual(proc.returncode, 0, proc.stderr)

        venv_bin = tool / ".venv" / "bin"
        venv_bin.mkdir(parents=True)

        # Missing interpreter.
        proc = run_case()
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("missing", proc.stderr.lower())
        self.assertEqual(proc.stdout, "")

        # Dangling symlink.
        py = venv_bin / "python"
        py.symlink_to(tool / "no such python")
        proc = run_case()
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("dangling", proc.stderr.lower())
        self.assertEqual(proc.stdout, "")

        # Non-executable regular file.
        py.unlink()
        py.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        py.chmod(0o644)
        proc = run_case()
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("not executable", proc.stderr.lower())
        self.assertEqual(proc.stdout, "")


if __name__ == "__main__":
    unittest.main()
