"""Shared fixtures for contre-attaque tests. No live network: every request goes to FakeTransport."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from typing import Any

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODULE = os.path.join(ROOT, "modules", "contre-attaque", "files")
SCRIPTS = os.path.join(MODULE, ".cursor", "skills", "contre-attaque", "scripts")
SECURITY = os.path.join(ROOT, "modules", "security", "files", "security")
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
sys.path.insert(0, SCRIPTS)

import ca_intel  # noqa: E402
import contre_attaque  # noqa: E402

NOW = "2026-11-02T17:00:00Z"


def fixture(name: str) -> Any:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return json.load(fh)


class FakeTransport:
    """Serves OSV/NVD/KEV/vendor fixtures. fail = set of provider names that return HTTP 500."""

    def __init__(self, osv_index: dict[tuple[str, str, str], list[str]] | None = None,
                 osv_vulns: dict[str, Any] | None = None, nvd_items: list[dict[str, Any]] | None = None,
                 kev: dict[str, Any] | None = None, fail: set[str] | None = None,
                 nvd_page_size: int | None = None, vendor: dict[str, bytes] | None = None) -> None:
        self.osv_index = osv_index or {}
        self.osv_vulns = osv_vulns or {}
        self.nvd_items = nvd_items or []
        self.kev = kev if kev is not None else fixture("kev.json")
        self.fail = fail or set()
        self.nvd_page_size = nvd_page_size
        self.vendor = vendor or {}
        self.calls: list[tuple[str, str, Any]] = []

    def __call__(self, method: str, url: str, body: bytes | None, headers: dict[str, str]) -> tuple[int, bytes, str]:
        self.calls.append((method, url, json.loads(body) if body else None))
        src = ca_intel.INTEL_SOURCES
        if url == src["osv"]["querybatch"]:
            if "osv" in self.fail:
                return 500, b"", "HTTP 500"
            queries = json.loads(body)["queries"]
            results = []
            for q in queries:
                key = (q["package"]["ecosystem"], q["package"]["name"], q["version"])
                ids = self.osv_index.get(key, [])
                results.append({"vulns": [{"id": i, "modified": self.osv_vulns[i]["modified"]} for i in ids]}
                               if ids else {})
            return 200, json.dumps({"results": results}).encode(), ""
        if url.startswith("https://api.osv.dev/v1/vulns/"):
            if "osv-vuln" in self.fail:
                return 500, b"", "HTTP 500"
            vid = urllib.parse.unquote(url.rsplit("/", 1)[1])
            rec = self.osv_vulns.get(vid)
            return (200, json.dumps(rec).encode(), "") if rec else (404, b"", "HTTP 404")
        if url.startswith(src["nvd"]["cves"]):
            if "nvd" in self.fail:
                return 500, b"", "HTTP 500"
            params = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
            if "cveId" in params:
                items = [i for i in self.nvd_items if i["id"] == params["cveId"]]
                return 200, json.dumps({"totalResults": len(items), "vulnerabilities": [{"cve": i} for i in items]}).encode(), ""
            lo, hi = ca_intel.parse_ts(params["lastModStartDate"]), ca_intel.parse_ts(params["lastModEndDate"])
            items = [i for i in self.nvd_items if lo <= ca_intel.parse_ts(i["lastModified"]) <= hi]
            start = int(params.get("startIndex", 0))
            size = self.nvd_page_size or int(params.get("resultsPerPage", 2000))
            page = items[start:start + size]
            if "nvd-page2" in self.fail and start > 0:
                return 500, b"", "HTTP 500"
            return 200, json.dumps({"totalResults": len(items), "startIndex": start,
                                    "vulnerabilities": [{"cve": i} for i in page]}).encode(), ""
        if url == src["kev"]["json_feed"]:
            if "kev" in self.fail:
                return 500, b"", "HTTP 500"
            return 200, json.dumps(self.kev).encode(), ""
        if url in self.vendor:
            return 200, self.vendor[url], ""
        return 404, b"", "HTTP 404"


def standard_transport(**overrides: Any) -> FakeTransport:
    osv = fixture("osv-vulns.json")
    kwargs: dict[str, Any] = {
        "osv_vulns": osv,
        "osv_index": {
            ("npm", "lodash", "4.17.20"): ["GHSA-29mw-wpgm-hmr9"],
            ("PyPI", "requests", "2.28.0"): ["GHSA-j8r2-6x86-q33q", "PYSEC-2023-74"],
        },
        "nvd_items": fixture("nvd-items.json"),
    }
    kwargs.update(overrides)
    return FakeTransport(**kwargs)


def write(root: str, rel: str, text: str) -> None:
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path) or root, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _git(root: str, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


class RepoCase(unittest.TestCase):
    """Temporary git repo with npm + PyPI lockfiles, a Dockerfile, and the security store."""

    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="ca-test-")
        _git(self.root, "init", "-q")
        _git(self.root, "config", "user.email", "t@example.com")
        _git(self.root, "config", "user.name", "Test")
        write(self.root, "package-lock.json", json.dumps({
            "name": "app", "lockfileVersion": 3,
            "packages": {"": {"name": "app"}, "node_modules/lodash": {"version": "4.17.20"}},
        }))
        write(self.root, "requirements.txt", "requests==2.28.0\n")
        write(self.root, "Dockerfile", "FROM python:3.11.4-slim\nRUN pip install -r requirements.txt\n")
        write(self.root, "app/server.py", "import requests\n\ndef fetch(url):\n    return requests.get(url, proxies=None)\n")
        os.makedirs(os.path.join(self.root, "security"))
        for name in ("findings-reviewed.json", "findings.schema.json", "accepted-risks.md"):
            shutil.copy(os.path.join(SECURITY, name), os.path.join(self.root, "security", name))
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "init")
        self.consent()

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def cli(self, *argv: str, transport: Any = None, now: str = NOW) -> tuple[int, Any]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = contre_attaque.main(["--root", self.root, "--now", now, *argv], transport=transport,
                                       sleep=lambda _s: None)
        text = buf.getvalue()
        try:
            return code, json.loads(text)
        except json.JSONDecodeError:
            return code, text

    def consent(self, grant: str = "osv,nvd,kev,vendor") -> None:
        code, _ = self.cli("consent", "--grant", grant)
        assert code == 0

    def start(self, *period: str, transport: Any = None, now: str = NOW) -> dict[str, Any]:
        code, out = self.cli("start", *period, transport=transport or standard_transport(), now=now)
        self.assertEqual(code, 0, out)
        return out

    def state(self) -> dict[str, Any]:
        with open(os.path.join(self.root, ".repo-kit", "contre-attaque", "state.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def findings(self) -> dict[str, Any]:
        with open(os.path.join(self.root, "security", "findings-reviewed.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def item(self, out: dict[str, Any], name: str, advisory: str | None = None) -> dict[str, Any]:
        for it in out["worklist"]:
            if it["component"]["name"] == name and (advisory is None or it["advisory"] == advisory):
                return it
        raise AssertionError(f"no worklist item for {name} {advisory or ''}: "
                             f"{[(i['component']['name'], i['advisory']) for i in out['worklist']]}")

    def decide(self, run_id: str, cid: str, status: str, *extra: str, now: str = NOW) -> tuple[int, Any]:
        return self.cli("decide", "--run", run_id, "--candidate", cid, "--status", status,
                        "--confidence", "high", "--rationale", f"test rationale for {status}", *extra, now=now)


def deep(obj: Any) -> Any:
    return copy.deepcopy(obj)
