#!/usr/bin/env python3
"""MCP integration tests (requires mcp==1.30.x in the active interpreter)."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG_PARENT = ROOT / "tools" / "py-indexer" / "files" / ".repo-kit" / "tools" / "py-indexer"
sys.path.insert(0, str(PKG_PARENT))

try:
    import mcp  # noqa: F401
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    HAS_MCP = True
except Exception:  # noqa: BLE001
    HAS_MCP = False

from py_indexer.config import load_config  # noqa: E402
from py_indexer.index_cmd import index_repository  # noqa: E402
from py_indexer.mcp_server import list_tool_names_for_tests  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@unittest.skipUnless(HAS_MCP, "mcp package not installed; skip MCP integration")
class McpIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.target = self.tmp / "app"
        self.tool = self.target / ".repo-kit" / "tools" / "py-indexer"
        shutil.copytree(PKG_PARENT, self.tool, dirs_exist_ok=True)
        (self.tool / "index").mkdir(exist_ok=True)
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
        (self.tool / "repos.json").write_text(json.dumps(cfg), encoding="utf-8")
        self.cfg = load_config(self.tool / "repos.json", target_root=self.target, tool_root=self.tool)
        index_repository(self.cfg, "app")

    async def asyncTearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_initialize_list_search_read(self) -> None:
        self.assertEqual(
            set(list_tool_names_for_tests()),
            {"search_code", "read_code", "index_status"},
        )
        server = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "py_indexer",
                "--config",
                str(self.tool / "repos.json"),
                "serve",
            ],
            env={
                **os.environ,
                "PYTHONPATH": str(self.tool) + os.pathsep + os.environ.get("PYTHONPATH", ""),
            },
        )
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {t.name for t in tools.tools}
                self.assertEqual(names, {"search_code", "read_code", "index_status"})

                status = await session.call_tool("index_status", {})
                status_text = status.content[0].text
                self.assertIn("app", status_text)

                found = await session.call_tool(
                    "search_code", {"query": "mcpProbeToken", "scope": "active"}
                )
                payload = json.loads(found.content[0].text)
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
                read_payload = json.loads(read.content[0].text)
                self.assertIn("mcpProbeToken", read_payload.get("text", ""))


if __name__ == "__main__":
    unittest.main()
