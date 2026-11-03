#!/usr/bin/env python3
"""E2E: launch serve using the installer-generated .cursor/mcp.json exactly.

Requires an explicitly supplied interpreter that already has the pinned MCP SDK:

  export PY_INDEXER_MCP_PYTHON=/path/to/python   # must: import mcp
  python3 -m unittest test_mcp_generated_config

Does not download packages. Does not use ``python -m py_indexer`` or
``validate-config`` as a stand-in for ``serve``.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_TOKEN = "PyIndexerMcpGenCfgToken_7f3a9c"

MCP_PYTHON = os.environ.get("PY_INDEXER_MCP_PYTHON", "").strip()


def _skip_reason() -> str | None:
    if not MCP_PYTHON:
        return (
            "PY_INDEXER_MCP_PYTHON not set; skip MCP generated-config e2e "
            "(offline default). Set the env var to a python with mcp==1.30.x, "
            "or PY_INDEXER_MCP_STRICT=1 to fail."
        )
    mcp_py = Path(MCP_PYTHON)
    if not mcp_py.exists():
        return f"PY_INDEXER_MCP_PYTHON is not a file: {MCP_PYTHON}"
    probe = subprocess.run(
        [str(mcp_py), "-c", "import mcp; import mcp.client.stdio; import sys; print(sys.prefix)"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if probe.returncode != 0:
        return (
            f"PY_INDEXER_MCP_PYTHON cannot import mcp: {MCP_PYTHON}\n"
            f"{probe.stderr.strip()}"
        )
    supplied_prefix = Path(probe.stdout.strip()).resolve()
    # Compare environment prefixes (not resolved executables — venv may symlink).
    if supplied_prefix != Path(sys.prefix).resolve():
        if os.environ.get("PY_INDEXER_MCP_ALLOW_ANY_RUNNER", "0") != "1":
            return (
                "test runner must run under PY_INDEXER_MCP_PYTHON's environment "
                f"(runner_prefix={sys.prefix}, supplied_prefix={supplied_prefix})"
            )
    return None


_REASON = _skip_reason()


def _resolve_workspace_placeholders(value: str, workspace: Path) -> str:
    return value.replace("${workspaceFolder}", str(workspace))


def _assert_mcp_tool_ok(result, *, label: str) -> str:
    """Return text payload; fail on protocol or application-level errors."""
    if getattr(result, "isError", False):
        raise AssertionError(f"{label}: MCP result isError=True: {result}")
    if not result.content:
        raise AssertionError(f"{label}: empty MCP content: {result}")
    text = result.content[0].text
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        # index_status / tools may return JSON; require parseable JSON here.
        raise AssertionError(f"{label}: non-JSON tool payload: {text[:200]!r}") from None
    if isinstance(payload, dict) and "error" in payload:
        raise AssertionError(f"{label}: application error payload: {payload}")
    return text


@unittest.skipIf(_REASON is not None, _REASON or "skip")
class GeneratedMcpConfigE2E(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="py-indexer-mcp-e2e-"))
        self.workspace = self.tmp / "project with spaces" / "app"
        self.workspace.mkdir(parents=True)
        self.foreign_cwd = self.tmp / "unrelated cwd"
        self.foreign_cwd.mkdir()
        subprocess.run(["git", "init", "-q", str(self.workspace)], check=True)

        env = os.environ.copy()
        env["REPO_KIT_TOOL_SKIP_DEPS"] = "1"
        env.pop("REPO_KIT_TOOL_ASSUME_YES", None)
        init = subprocess.run(
            [str(ROOT / "scripts" / "init.sh"), str(self.workspace), "--tool", "py-indexer"],
            cwd=str(self.foreign_cwd),
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        if init.returncode != 0:
            raise RuntimeError(f"init failed:\n{init.stdout}\n{init.stderr}")

        self.tool = self.workspace / ".repo-kit" / "tools" / "py-indexer"
        self.mcp_json = self.workspace / ".cursor" / "mcp.json"
        self.assertTrue(self.mcp_json.is_file(), "installer must write .cursor/mcp.json")

        # Provision tool .venv from the supplied MCP interpreter (offline).
        # Note: ``--system-site-packages`` only exposes *OS* site-packages, not
        # another venv's. Point a .pth at the supplied env's purelib instead.
        venv = self.tool / ".venv"
        if venv.exists():
            shutil.rmtree(venv)
        subprocess.run(
            [MCP_PYTHON, "-m", "venv", "--clear", str(venv)],
            check=True,
            timeout=60,
        )
        purelib = subprocess.run(
            [
                MCP_PYTHON,
                "-c",
                "import sysconfig; print(sysconfig.get_path('purelib'))",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
        sp_dirs = list((venv / "lib").glob("python*/site-packages"))
        self.assertTrue(sp_dirs, "tool venv site-packages missing")
        (sp_dirs[0] / "zz_py_indexer_mcp_supplied.pth").write_text(
            purelib + "\n", encoding="utf-8"
        )
        probe = subprocess.run(
            [str(venv / "bin" / "python"), "-c", "import mcp"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)

        # Prove host python (likely without mcp) is distinct when possible.
        self.host_python = shutil.which("python3") or sys.executable

        src = self.workspace / "src" / "fixture.ts"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text(
            f"// fixture for generated MCP config e2e\nexport const {FIXTURE_TOKEN} = 42;\n",
            encoding="utf-8",
        )
        cfg = {
            "schema_version": 1,
            "active_repo": "app",
            "defaults": {
                "max_results": 8,
                "max_snippet_chars": 800,
                "max_total_chars": 8000,
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
        (self.tool / "repos.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")

        index = subprocess.run(
            [str(self.tool / "bin" / "py-indexer"), "index", "--all"],
            cwd=str(self.foreign_cwd),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(index.returncode, 0, index.stderr)

        # Import MCP client from the supplied environment only.
        from mcp import ClientSession, StdioServerParameters  # noqa: WPS433
        from mcp.client.stdio import stdio_client  # noqa: WPS433

        self.ClientSession = ClientSession
        self.StdioServerParameters = StdioServerParameters
        self.stdio_client = stdio_client

    async def asyncTearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _launch_from_mcp_json(self):
        doc = json.loads(self.mcp_json.read_text(encoding="utf-8"))
        entry = doc["mcpServers"]["py-indexer"]
        command = _resolve_workspace_placeholders(entry["command"], self.workspace)
        args = [
            _resolve_workspace_placeholders(a, self.workspace) for a in entry["args"]
        ]
        self.assertTrue(command.endswith("/.venv/bin/python"), command)
        self.assertEqual(args[-1], "serve", args)
        self.assertTrue(args[0].endswith("/bin/py-indexer"), args)
        # Exact generated shape: no -m py_indexer.
        self.assertNotIn("-m", args)
        return self.StdioServerParameters(
            command=command,
            args=args,
            cwd=str(self.foreign_cwd),
            env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
        )

    async def _exercise_session(self, server) -> None:
        async with self.stdio_client(server) as (read, write):
            async with self.ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=30)
                tools = await asyncio.wait_for(session.list_tools(), timeout=30)
                names = {t.name for t in tools.tools}
                self.assertEqual(names, {"search_code", "read_code", "index_status"})

                status = await asyncio.wait_for(
                    session.call_tool("index_status", {}), timeout=30
                )
                status_text = _assert_mcp_tool_ok(status, label="index_status")
                status_payload = json.loads(status_text)
                self.assertEqual(status_payload.get("active_repo"), "app")
                repo_ids = {r["id"] for r in status_payload.get("repositories", [])}
                self.assertIn("app", repo_ids)

                found = await asyncio.wait_for(
                    session.call_tool(
                        "search_code",
                        {"query": FIXTURE_TOKEN, "scope": "active"},
                    ),
                    timeout=30,
                )
                found_text = _assert_mcp_tool_ok(found, label="search_code")
                found_payload = json.loads(found_text)
                self.assertGreaterEqual(len(found_payload.get("hits", [])), 1)
                joined = json.dumps(found_payload)
                self.assertIn(FIXTURE_TOKEN, joined)

                read = await asyncio.wait_for(
                    session.call_tool(
                        "read_code",
                        {
                            "repo_id": "app",
                            "path": "src/fixture.ts",
                            "start_line": 1,
                            "end_line": 5,
                        },
                    ),
                    timeout=30,
                )
                read_text = _assert_mcp_tool_ok(read, label="read_code")
                read_payload = json.loads(read_text)
                self.assertIn(FIXTURE_TOKEN, read_payload.get("text", ""))

    async def test_exact_generated_mcp_json_serve(self) -> None:
        server = self._launch_from_mcp_json()
        await asyncio.wait_for(self._exercise_session(server), timeout=90)

    async def test_direct_bin_serve_reexec_into_tool_venv(self) -> None:
        """Direct bin/py-indexer serve from outside the tool venv must re-exec.

        Records ``sys.prefix`` from the server process via a fixture-only
        site-packages ``.pth`` line (``import ...`` lines are executed by
        site.py). A ``sitecustomize.py`` in that directory is not used: the
        stdlib ``sitecustomize`` is imported first, so a fixture module of the
        same name never runs. The ``.pth`` is processed only for this venv, so
        the marker proves the selected environment even when the host
        interpreter already has ``mcp``. It does not print and is not shipped.
        """
        marker = self.tmp / "server-prefix.txt"
        if marker.exists():
            marker.unlink()
        site_dirs = list((self.tool / ".venv" / "lib").glob("python*/site-packages"))
        self.assertTrue(site_dirs, "tool venv site-packages missing")
        line = (
            "import pathlib, sys; pathlib.Path("
            + repr(str(marker))
            + ").write_text(sys.prefix, encoding='utf-8')"
        )
        (site_dirs[0] / "zz_py_indexer_prefix_probe.pth").write_text(
            line + "\n", encoding="utf-8"
        )

        launcher = self.tool / "bin" / "py-indexer"
        server = self.StdioServerParameters(
            command=self.host_python,
            args=[str(launcher), "serve"],
            cwd=str(self.foreign_cwd),
            env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
        )
        await asyncio.wait_for(self._exercise_session(server), timeout=90)
        self.assertTrue(marker.is_file(), "server process did not record sys.prefix")
        recorded = Path(marker.read_text(encoding="utf-8").strip()).resolve()
        self.assertEqual(recorded, (self.tool / ".venv").resolve())


if __name__ == "__main__":
    unittest.main()
