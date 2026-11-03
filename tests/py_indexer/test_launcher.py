#!/usr/bin/env python3
"""Unit tests for the py-indexer bin launcher (venv detection)."""

from __future__ import annotations

import importlib.util
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
            self.assertRaises(SystemExit),
        ):
            self.mod._prefer_venv(self.tmp)

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

    def test_noop_when_venv_missing(self) -> None:
        bare = self.tmp / "bare"
        bare.mkdir()
        with mock.patch.object(self.mod.os, "execv") as execv:
            self.mod._prefer_venv(bare)
        execv.assert_not_called()


if __name__ == "__main__":
    unittest.main()
