#!/usr/bin/env python3
"""Lightweight MCP smoke (optional).

Prefer ``test_mcp_generated_config.py``. This module stays as a narrow SDK smoke
and is skipped unless ``PY_INDEXER_MCP_PYTHON`` selects the current interpreter.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG_PARENT = ROOT / "tools" / "py-indexer" / "src"
sys.path.insert(0, str(PKG_PARENT))

MCP_PYTHON = os.environ.get("PY_INDEXER_MCP_PYTHON", "").strip()


def _runner_is_supplied_mcp_python() -> bool:
    if not MCP_PYTHON:
        return False
    try:
        import subprocess

        probe = subprocess.run(
            [MCP_PYTHON, "-c", "import sys; print(sys.prefix)"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if probe.returncode != 0:
            return False
        return Path(probe.stdout.strip()).resolve() == Path(sys.prefix).resolve()
    except OSError:
        return False


def _has_mcp() -> bool:
    try:
        import mcp  # noqa: F401
        from mcp import ClientSession, StdioServerParameters  # noqa: F401
        from mcp.client.stdio import stdio_client  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


_SKIP = None
if not MCP_PYTHON:
    _SKIP = "PY_INDEXER_MCP_PYTHON not set (offline default)"
elif not _runner_is_supplied_mcp_python():
    _SKIP = "runner is not PY_INDEXER_MCP_PYTHON"
elif not _has_mcp():
    _SKIP = "mcp package not importable in PY_INDEXER_MCP_PYTHON"

from py_indexer.config import load_config  # noqa: E402
from py_indexer.index_cmd import index_repository  # noqa: E402
from py_indexer.mcp_server import list_tool_names_for_tests  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@unittest.skipIf(_SKIP is not None, _SKIP or "skip")
class McpIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        self.ClientSession = ClientSession
        self.StdioServerParameters = StdioServerParameters
        self.stdio_client = stdio_client

        self.tmp = Path(tempfile.mkdtemp())
        os.environ["XDG_CACHE_HOME"] = str(self.tmp / "cache")
        self.target = self.tmp / "app"
        self.tool = self.target / ".repo-kit" / "tools" / "py-indexer"
        self.tool.mkdir(parents=True)
        _write(self.target / "src" / "hello.ts", "export const mcpProbeToken = 1;\n")
        cfg = {
            "schema_version": 1,
            "active_repo": "app",
            "defaults": {
                "max_results": 5,
                "max_snippet_chars": 500,
                "max_total_chars": 5000,
                "chunk_lines": 40,
                "chunk_overlap_lines": 5,
                "max_file_bytes": 100000,
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
        self.cfg_path = self.tool / "repos.json"
        self.cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        self.cfg = load_config(self.cfg_path, project_root=self.target)
        index_repository(self.cfg, "app")

    async def asyncTearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_initialize_list_search_read(self) -> None:
        self.assertEqual(
            set(list_tool_names_for_tests()),
            {"search_code", "read_code", "index_status", "context", "awareness"},
        )
        server = self.StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "py_indexer",
                "--config",
                str(self.cfg_path),
                "serve",
            ],
            env={
                **{k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
                "PYTHONPATH": str(PKG_PARENT),
                "XDG_CACHE_HOME": str(self.tmp / "cache"),
            },
        )
        async with self.stdio_client(server) as (read, write):
            async with self.ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {t.name for t in tools.tools}
                self.assertEqual(names, {"search_code", "read_code", "index_status", "context", "awareness"})

                status = await session.call_tool("index_status", {})
                self.assertFalse(getattr(status, "isError", False))
                status_text = status.content[0].text
                self.assertIn("app", status_text)
                status_payload = json.loads(status_text)
                self.assertNotIn("error", status_payload)

                found = await session.call_tool(
                    "search_code", {"query": "mcpProbeToken", "scope": "active"}
                )
                self.assertFalse(getattr(found, "isError", False))
                payload = json.loads(found.content[0].text)
                self.assertNotIn("error", payload)
                self.assertGreaterEqual(len(payload.get("hits", [])), 1)

                read = await session.call_tool(
                    "read_code",
                    {
                        "repo_id": "app",
                        "path": "src/hello.ts",
                        "start_line": 1,
                        "end_line": 2,
                    },
                )
                self.assertFalse(getattr(read, "isError", False))
                read_payload = json.loads(read.content[0].text)
                self.assertNotIn("error", read_payload)
                self.assertIn("mcpProbeToken", read_payload.get("text", ""))


if __name__ == "__main__":
    unittest.main()
