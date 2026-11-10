#!/usr/bin/env python3
"""Structural index, context, and awareness. Grammar cases skip without parsers."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG_PARENT = ROOT / "tools" / "py-indexer" / "src"
import sys

sys.path.insert(0, str(PKG_PARENT))

from py_indexer.config import load_config  # noqa: E402
from py_indexer.context_cmd import SelectorError, awareness_report, context_report  # noqa: E402
from py_indexer import extract as extract_mod  # noqa: E402
from py_indexer.extract import extract_file  # noqa: E402
from py_indexer.index_cmd import index_repository  # noqa: E402
from py_indexer.search_cmd import search  # noqa: E402
from py_indexer.structural import structural_ready  # noqa: E402


def _git_init(path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _config(target: Path, repos: list[dict]) -> object:
    tool = target / ".repo-kit" / "tools" / "py-indexer"
    tool.mkdir(parents=True, exist_ok=True)
    cfg_path = tool / "repos.json"
    cfg_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_repo": repos[0]["id"],
                "defaults": {
                    "max_results": 8,
                    "max_snippet_chars": 400,
                    "max_total_chars": 4000,
                    "chunk_lines": 40,
                    "chunk_overlap_lines": 5,
                    "max_file_bytes": 100000,
                },
                "repositories": repos,
            }
        ),
        encoding="utf-8",
    )
    return load_config(cfg_path, project_root=target)


class StructuralOfflineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["XDG_CACHE_HOME"] = str(self.tmp / "cache")
        self.target = self.tmp / "app"
        self.target.mkdir()
        _git_init(self.target)
        _write(self.target / "src" / "note.py", "def lexical_only_marker():\n    return 1\n")
        _write(self.target / "src" / "plain.c", "int c_only(void) { return 1; }\n")
        self.cfg = _config(
            self.target,
            [
                {
                    "id": "app",
                    "root": ".",
                    "role": "working",
                    "related": [],
                    "include": [],
                    "exclude": [],
                }
            ],
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_lexical_search_survives_without_a_structural_claim(self) -> None:
        index_repository(self.cfg, "app")
        found = search(self.cfg, "lexical_only_marker")
        self.assertTrue(any(hit.path.endswith("note.py") for hit in found.hits))
        report = context_report(self.cfg, query="lexical_only_marker")
        self.assertIn(report["selection"]["status"], {"not_found", "selected", "ambiguous"})
        if not structural_ready():
            coverage = report["structural_coverage"]["app"]["c"]
            self.assertEqual(coverage["status"], "lexical_only")

    def test_selector_groups_are_exclusive(self) -> None:
        with self.assertRaises(SelectorError):
            context_report(self.cfg, symbol_id="s1_abc", query="nope")
        with self.assertRaises(SelectorError):
            context_report(self.cfg, repo="app", path="src/note.py")

    def test_candidate_path_is_not_promoted_and_ambiguity_is_visible(self) -> None:
        index_repository(self.cfg, "app")
        import sqlite3

        from py_indexer.store import open_index

        db = self.cfg.db_path("app")
        conn = open_index(
            db,
            "app",
            checkout=self.target,
            fingerprint=self.cfg.content_fingerprint("app"),
        )
        try:
            conn.execute(
                """
                INSERT INTO symbols(
                  symbol_id, identity_key, path, language, kind, name, qualified_name,
                  signature, params, scope_json, anon_ord, body_hash
                ) VALUES
                  ('sA','kA','src/note.py','python','function','alpha','alpha','alpha()','()','[]',NULL,NULL),
                  ('sB','kB','src/note.py','python','function','beta','beta','beta()','()','[]',NULL,NULL),
                  ('sC','kC','src/note.py','python','function','gamma','gamma','gamma()','()','[]',NULL,NULL),
                  ('sD','kD','src/note.py','python','function','delta','delta','delta()','()','[]',NULL,NULL),
                  ('sE','kE','src/note.py','python','function','epsilon','epsilon','epsilon()','()','[]',NULL,NULL)
                """
            )
            conn.execute(
                """
                INSERT INTO occurrences(
                  symbol_id, path, role, start_line, start_col, end_line, end_col, start_byte, end_byte
                ) VALUES
                  ('sA','src/note.py','decl_and_def',1,1,1,1,0,1),
                  ('sB','src/note.py','decl_and_def',2,1,2,1,0,1),
                  ('sC','src/note.py','decl_and_def',3,1,3,1,0,1)
                """
            )
            conn.execute(
                """
                INSERT INTO sites(
                  site_id, path, site_kind, start_line, start_col, end_line, end_col, start_byte, end_byte,
                  enclosing_symbol_id, rule_id, resolution, expression_text, payload_json,
                  evidence_truncated
                ) VALUES (
                  1,'src/note.py','call',1,1,1,4,0,4,'sA','lang.call','unresolved','dynamic()',
                  '{}',0
                )
                """
            )
            conn.execute(
                """
                INSERT INTO relationships(
                  kind, status, source_site_id, source_symbol_id, target_symbol_id, target_key,
                  rule_id, reason, evidence_json, evidence_truncated
                ) VALUES
                  ('call','candidate',NULL,'sA','sB','beta','name.unique','unique name','[]',0),
                  ('call','resolved',NULL,'sB','sC','gamma','bind.scope','scope','[]',0),
                  ('call','ambiguous',1,'sA','sD','delta','name.many','many','[]',0),
                  ('call','ambiguous',1,'sA','sE','epsilon','name.many','many','[]',0)
                """
            )
        finally:
            conn.close()
        aware = awareness_report(self.cfg, symbol_id="sA", depth=2, limit=40)
        by_target = {}
        for edge in aware["relationships"]:
            by_target.setdefault(edge["target"].get("symbol_id"), edge)
        self.assertEqual(by_target["sB"]["status"], "candidate")
        self.assertEqual(by_target["sC"]["path_status"], "candidate")
        self.assertEqual(by_target["sC"]["status"], "resolved")
        ambiguous = [edge for edge in aware["relationships"] if edge["status"] == "ambiguous"]
        self.assertEqual(len(ambiguous), 1)
        self.assertEqual(ambiguous[0]["expansion"], "stopped_ambiguity")
        self.assertGreaterEqual(len(ambiguous[0]["alternatives"]), 1)
        self.assertTrue(aware["unresolved"]["shown"] >= 1)
        limited = awareness_report(self.cfg, symbol_id="sA", depth=2, limit=1)
        self.assertTrue(limited["truncation"]["truncated"])


@unittest.skipUnless(structural_ready(), "pinned tree-sitter parsers are not installed")
class StructuralGrammarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["XDG_CACHE_HOME"] = str(self.tmp / "cache")
        self.web = self.tmp / "web"
        self.svc = self.tmp / "svc"
        for path in (self.web, self.svc):
            path.mkdir()
            _git_init(path)
        _write(
            self.web / "src" / "api.ts",
            """
const PATH = "/pool/update";
export function updatePool(id: string) {
  cache.get(id);
  map.get("/pool/update");
  return fetch(PATH, { method: "POST" });
}
const local = (x: string) => x;
export function launch() {
  exec("poolctl update");
  spawn("poolctl", ["update", "1"]);
  server.listen(4711, "127.0.0.1");
  proc.stdin.write("update");
}
""".strip()
            + "\n",
        )
        _write(
            self.web / "src" / "view.tsx",
            "export function View(props: { id: string }) { return <button>{props.id}</button>; }\n",
        )
        _write(
            self.svc / "src" / "pool.h",
            "namespace app { class Pool { public: void update(int id); void update(int id, int extra); }; }\n",
        )
        _write(
            self.svc / "src" / "pool.cpp",
            """
namespace app {
void helper(int id) {}
void Pool::update(int id) { helper(id); auto p = helper; }
namespace other { void run() {} }
void run() { run(); }
}
void routes() { svr.Post("/pool/update", helper); }
void serve() { connect("127.0.0.1", 4711); }
""".strip()
            + "\n",
        )
        _write(
            self.svc / "src" / "poolctl.cpp",
            """
int main(int argc, char** argv) {
  if (strcmp(argv[1], "update") == 0) return 0;
  return 1;
}
""".strip()
            + "\n",
        )
        _write(
            self.svc / "src" / "plain.c",
            "int not_parsed(void) { return 1; }\n",
        )
        _write(self.svc / "src" / "lib.rs", "pub fn update_pool(id: &str) {}\n")
        self.cfg = _config(
            self.web,
            [
                {
                    "id": "web",
                    "root": ".",
                    "role": "working",
                    "related": ["svc"],
                    "include": [],
                    "exclude": [],
                },
                {
                    "id": "svc",
                    "root": str(self.svc),
                    "role": "reference",
                    "related": [],
                    "include": [],
                    "exclude": [],
                },
            ],
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_cross_repo_http_chain_and_limits(self) -> None:
        before = extract_mod.EXTRACT_CALLS
        index_repository(self.cfg, "web")
        index_repository(self.cfg, "svc")
        parsed = extract_mod.EXTRACT_CALLS - before
        self.assertGreater(parsed, 0)
        again = extract_mod.EXTRACT_CALLS
        index_repository(self.cfg, "web")
        self.assertEqual(extract_mod.EXTRACT_CALLS, again)
        _write(self.web / "src" / "api.ts", (self.web / "src" / "api.ts").read_text(encoding="utf-8") + "\n")
        index_repository(self.cfg, "web")
        self.assertGreater(extract_mod.EXTRACT_CALLS, again)

        c_file = extract_file("src/plain.c", "int not_parsed(void) { return 1; }\n")
        self.assertEqual(c_file.status, "lexical_only")
        header = extract_file("src/pool.h", (self.svc / "src" / "pool.h").read_text(encoding="utf-8"))
        self.assertEqual(header.language, "cpp")
        self.assertTrue(any(sym.name == "update" for sym in header.symbols))

        report = awareness_report(
            self.cfg,
            repo="web",
            path="src/api.ts",
            line=3,
            depth=2,
            limit=40,
        )
        self.assertEqual(report["selection"]["status"], "selected")
        kinds = {edge["kind"] for edge in report["relationships"]}
        self.assertIn("http_request_to_handler", kinds)
        http_edges = [edge for edge in report["relationships"] if edge["kind"] == "http_request_to_handler"]
        self.assertTrue(all(edge["status"] in {"candidate", "ambiguous"} for edge in http_edges))
        self.assertTrue(all(edge["path_status"] != "resolved" or edge["status"] == "resolved" for edge in report["relationships"]))
        http_text = json.dumps(http_edges)
        self.assertNotIn("cache.get", http_text)
        self.assertNotIn("map.get", http_text)


def _line(path: Path, text: str) -> int:
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if text in line:
            return number
    raise AssertionError(text)


def _stored(cfg, repo: str, checkout: Path) -> tuple[list[dict], list[dict]]:
    from py_indexer.store import open_index

    conn = open_index(
        cfg.db_path(repo),
        repo,
        checkout=checkout,
        fingerprint=cfg.content_fingerprint(repo),
    )
    try:
        sites = [dict(row) for row in conn.execute("SELECT * FROM sites")]
        symbols = [dict(row) for row in conn.execute("SELECT * FROM symbols")]
    finally:
        conn.close()
    return sites, symbols


def _rpc(*entries: str) -> str:
    body = "\n  ".join(entries)
    return f"""
struct Svc {{
  bool on_get_height();
  bool on_other();
}};
void note() {{}}
bool Svc::on_get_height() {{ note(); return true; }}
bool Svc::on_other() {{ return false; }}
const char* cors = "Access-Control-Allow-Methods: POST, GET";
std::unordered_map<std::string, Handler> routes = {{
  {{ "/getheight", {{ wrap(&Svc::on_get_height), true }} }},
  {{ "/getheight2", {{ wrap(&Svc::on_other), true }} }},
  {body}
}};
void Svc::process(const HttpRequest& request, HttpResponse& response) {{
  const auto& url = request.getUrl();
  auto it = routes.find(url);
}}
"""


_NORMALIZER = """
export function normalizeNodeUrl(url: string): string {
  const trimmed = url.trim();
  if (!trimmed) return trimmed;
  return trimmed.endsWith("/") ? trimmed : `${trimmed}/`;
}
"""


@unittest.skipUnless(structural_ready(), "pinned tree-sitter parsers are not installed")
class HttpSuffixFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["XDG_CACHE_HOME"] = str(self.tmp / "cache")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _world(self, name: str, web_files: dict, svc_files: dict, exclude=None):
        base = self.tmp / name
        web = base / "web"
        svc = base / "svc"
        web.mkdir(parents=True)
        svc.mkdir()
        _git_init(web)
        _git_init(svc)
        for rel, text in web_files.items():
            _write(web / rel, text if text.endswith("\n") else text + "\n")
        for rel, text in svc_files.items():
            _write(svc / rel, text if text.endswith("\n") else text + "\n")
        cfg = _config(
            web,
            [
                {
                    "id": "web",
                    "root": ".",
                    "role": "working",
                    "related": ["svc"],
                    "include": [],
                    "exclude": list(exclude or []),
                },
                {
                    "id": "svc",
                    "root": str(svc),
                    "role": "reference",
                    "related": [],
                    "include": [],
                    "exclude": [],
                },
            ],
        )
        index_repository(cfg, "web")
        index_repository(cfg, "svc")
        return cfg, web, svc

    def test_conditional_suffix_reaches_handler_without_storing_full_path(self) -> None:
        client = _NORMALIZER + """
export function probe(nodeUrl: string) {
  const normalized = normalizeNodeUrl(nodeUrl);
  return fetch(`${normalized}getheight`, { method: "GET" });
}
"""
        empty_only = """
export function keep(url: string): string {
  if (!url) return url;
  return url;
}
export function emptyOnly(nodeUrl: string) {
  const kept = keep(nodeUrl);
  return fetch(`${kept}getheight`, { method: "GET" });
}
"""
        cfg, web, svc = self._world(
            "unique",
            {"src/client.ts": client, "src/empty.ts": empty_only},
            {"src/rpc.cpp": _rpc()},
        )
        sites, _symbols = _stored(cfg, "web", web)
        client_sites = [
            row for row in sites if row["site_kind"] == "http_client" and row["path"] == "src/client.ts"
        ]
        self.assertEqual(len(client_sites), 1)
        self.assertIsNone(client_sites[0]["http_path"])
        self.assertEqual(client_sites[0]["http_suffix"], "getheight")
        self.assertEqual(client_sites[0]["http_boundary"], "conditional_slash")
        self.assertEqual(client_sites[0]["http_method"], "GET")
        normalizer = [row for row in sites if row["site_kind"] == "normalizer"]
        self.assertEqual(len(normalizer), 1)
        self.assertEqual(normalizer[0]["expression_text"], "normalizeNodeUrl")
        self.assertTrue(json.loads(normalizer[0]["payload_json"])["empty_unseparated"])
        empty_sites = [row for row in sites if row["path"] == "src/empty.ts" and row["site_kind"] == "http_client"]
        self.assertEqual(len(empty_sites), 1)
        self.assertIsNone(empty_sites[0]["http_suffix"])
        self.assertIsNone(empty_sites[0]["http_path"])
        self.assertEqual(empty_sites[0]["resolution"], "unresolved")

        svc_sites, svc_symbols = _stored(cfg, "svc", svc)
        routes = [row for row in svc_sites if row["site_kind"] == "http_route"]
        self.assertEqual({row["http_path"] for row in routes}, {"/getheight", "/getheight2"})
        self.assertTrue(all(row["http_method"] is None for row in routes))
        height = next(row for row in routes if row["http_path"] == "/getheight")
        handlers = [row for row in svc_symbols if row["qualified_name"] == "Svc::on_get_height"]
        self.assertEqual(len(handlers), 2)
        self.assertIn(height["handler_symbol_id"], {row["symbol_id"] for row in handlers})

        line = _line(web / "src" / "client.ts", "function probe")
        context = context_report(cfg, repo="web", path="src/client.ts", line=line)
        awareness = awareness_report(
            cfg, repo="web", path="src/client.ts", line=line, depth=2, limit=40
        )
        http = [edge for edge in context["relationships"] if edge["kind"] == "http_request_to_handler"]
        self.assertEqual(len(http), 1)
        edge = http[0]
        self.assertEqual(edge["status"], "candidate")
        self.assertEqual(edge["path_status"], "candidate")
        self.assertEqual(edge["target_symbol_id"], height["handler_symbol_id"])
        self.assertEqual(edge["target"]["name"], "/getheight")
        self.assertIn("unknown base path could invalidate this match", edge["reason"])
        self.assertIn("empty normalizer input does not add a slash", edge["reason"])
        self.assertIn("absent method is not copied from the other side", edge["reason"])
        self.assertTrue(all(len(item) < 80 for item in edge["evidence"]))
        self.assertNotIn("fetch(", " ".join(edge["evidence"]))
        relationship_text = json.dumps(context["relationships"])
        for snap in context["snapshots"]:
            self.assertIsNotNone(snap["snapshot_id"])
            self.assertNotIn(snap["snapshot_id"], relationship_text)
        self.assertNotIn("indexed_at", relationship_text)
        self.assertEqual({snap["repo_id"] for snap in context["snapshots"]}, {"web", "svc"})

        followed = [
            item
            for item in awareness["relationships"]
            if item["source"].get("symbol_id") == height["handler_symbol_id"]
        ]
        self.assertTrue(followed)
        self.assertTrue(all(item["path_status"] == "candidate" for item in followed))
        aware_http = [
            edge for edge in awareness["relationships"] if edge["kind"] == "http_request_to_handler"
        ]
        self.assertEqual(aware_http[0]["path_status"], "candidate")
        self.assertEqual(aware_http[0]["target_symbol_id"], height["handler_symbol_id"])

    def test_literal_suffix_keeps_prefix_base_uncertain(self) -> None:
        client = """
export function probe(base: string, fullUrl: string, suffix: string) {
  fetch(`${base}/getheight`);
  fetch(`${base}/foo/getheight`);
  fetch(`${base}getheight`);
  fetch(`${base}${suffix}`);
  fetch(fullUrl);
}
"""
        cfg, web, svc = self._world(
            "prefix",
            {"src/client.ts": client},
            {
                "src/rpc.cpp": _rpc(
                    '{ "/api/getheight", { wrap(&Svc::on_get_height), true } },'
                )
            },
        )
        sites, _symbols = _stored(cfg, "web", web)
        by_suffix = {row["http_suffix"]: row for row in sites if row["site_kind"] == "http_client"}
        self.assertIsNone(by_suffix["/getheight"]["http_path"])
        self.assertEqual(by_suffix["/getheight"]["http_boundary"], "literal_slash")
        self.assertEqual(by_suffix["/foo/getheight"]["http_boundary"], "literal_slash")
        self.assertIsNone(by_suffix["/getheight"]["http_method"])
        unresolved = [row for row in sites if row["site_kind"] == "http_client" and row["http_suffix"] is None]
        self.assertEqual(len(unresolved), 3)
        self.assertTrue(all(row["http_path"] is None and row["resolution"] == "unresolved" for row in unresolved))

        line = _line(web / "src" / "client.ts", "function probe")
        report = context_report(cfg, repo="web", path="src/client.ts", line=line)
        http = [edge for edge in report["relationships"] if edge["kind"] == "http_request_to_handler"]
        self.assertEqual(len(http), 1)
        self.assertEqual(http[0]["status"], "ambiguous")
        self.assertEqual(http[0]["expansion"], "stopped_ambiguity")
        self.assertIsNone(http[0]["target_symbol_id"])
        names = {item["name"] for item in http[0]["alternatives"]}
        self.assertEqual(names, {"/getheight", "/api/getheight"})
        self.assertIn("unknown base path could invalidate this match", http[0]["reason"])
        self.assertNotIn("empty normalizer input", http[0]["reason"])
        loose = [
            edge
            for edge in report["unresolved"]["sites"]
            if edge["evidence"] == ["suffix /foo/getheight"]
        ]
        self.assertEqual(len(loose), 1)
        self.assertIn("unknown base path could invalidate this match", loose[0]["reason"])
        dynamic = [
            edge for edge in report["unresolved"]["sites"] if edge["evidence"] == ["dynamic url"]
        ]
        self.assertEqual(len(dynamic), 3)
        self.assertNotIn("/getheight2", json.dumps(http))
        _ = svc

    def test_unrelated_slash_dispatch_is_not_an_http_route(self) -> None:
        client = """
export function probe() {
  return fetch("/getheight", { method: "GET" });
}
"""
        cpp = """
bool Svc::on_get_height() { return true; }
std::unordered_map<std::string, Handler> commands = {
  { "/getheight", { wrap(&Svc::on_get_height), true } },
};
void run(const std::string& command) {
  auto it = commands.find(command);
}
"""
        cfg, web, svc = self._world(
            "dispatch",
            {"src/client.ts": client},
            {"src/rpc.cpp": cpp},
        )
        sites, _symbols = _stored(cfg, "svc", svc)
        table = [row for row in sites if row["dispatch_key"] == "/getheight"]
        self.assertEqual(len(table), 1)
        self.assertEqual(table[0]["site_kind"], "dispatch")
        self.assertIsNone(table[0]["http_path"])
        self.assertIn("HTTP request-path lookup not established", table[0]["payload_json"])
        line = _line(web / "src" / "client.ts", "function probe")
        report = context_report(cfg, repo="web", path="src/client.ts", line=line)
        self.assertFalse(
            any(edge["kind"] == "http_request_to_handler" for edge in report["relationships"])
        )
        self.assertTrue(any(edge["evidence"] == ["path /getheight"] for edge in report["unresolved"]["sites"]))

    def test_two_http_tables_stop_expansion(self) -> None:
        client = _NORMALIZER + """
export function probe(nodeUrl: string) {
  const normalized = normalizeNodeUrl(nodeUrl);
  return fetch(`${normalized}getheight`, { method: "GET" });
}
"""
        cpp = """
struct Svc { bool on_get_height(); };
struct Other { bool on_get_height(); };
bool Svc::on_get_height() { return true; }
bool Other::on_get_height() { return true; }
std::unordered_map<std::string, Handler> routes = {
  { "/getheight", { wrap(&Svc::on_get_height), true } },
};
std::unordered_map<std::string, Handler> extra = {
  { "/getheight", { wrap(&Other::on_get_height), true } },
};
void Svc::process(const HttpRequest& request) {
  const auto& url = request.getUrl();
  auto it = routes.find(url);
  auto more = extra.find(request.getUrl());
}
"""
        cfg, web, svc = self._world(
            "ambiguous",
            {"src/client.ts": client},
            {"src/rpc.cpp": cpp},
        )
        sites, _symbols = _stored(cfg, "svc", svc)
        routes = [row for row in sites if row["site_kind"] == "http_route"]
        handlers = {row["handler_symbol_id"] for row in routes}
        self.assertEqual(len(handlers), 2)
        self.assertNotIn(None, handlers)
        line = _line(web / "src" / "client.ts", "function probe")
        report = awareness_report(
            cfg, repo="web", path="src/client.ts", line=line, depth=2, limit=40
        )
        http = [edge for edge in report["relationships"] if edge["kind"] == "http_request_to_handler"]
        self.assertEqual(len(http), 1)
        self.assertEqual(http[0]["status"], "ambiguous")
        self.assertEqual(http[0]["expansion"], "stopped_ambiguity")
        self.assertIsNone(http[0]["target_symbol_id"])
        self.assertEqual(
            {item["symbol_id"] for item in http[0]["alternatives"]},
            handlers,
        )
        sources = {edge["source"].get("symbol_id") for edge in report["relationships"]}
        self.assertTrue(handlers.isdisjoint(sources))

    def test_changed_import_drops_suffix_without_rereading_client(self) -> None:
        client = """
import { normalizeNodeUrl } from "./norm";
export function probe(nodeUrl: string) {
  const normalized = normalizeNodeUrl(nodeUrl);
  return fetch(`${normalized}getheight`, { method: "GET" });
}
"""
        cfg, web, svc = self._world(
            "import",
            {"src/client.ts": client, "src/norm.ts": _NORMALIZER},
            {"src/rpc.cpp": _rpc()},
        )
        sites, _symbols = _stored(cfg, "web", web)
        row = next(item for item in sites if item["site_kind"] == "http_client")
        self.assertEqual(row["http_suffix"], "getheight")
        self.assertEqual(row["norm_spec"], "./norm")
        self.assertIsNone(row["http_path"])
        _write(
            web / "src" / "norm.ts",
            "export function normalizeNodeUrl(url: string): string {\n  return url;\n}\n",
        )
        before = extract_mod.EXTRACT_CALLS
        index_repository(cfg, "web")
        self.assertEqual(extract_mod.EXTRACT_CALLS - before, 1)
        sites, _symbols = _stored(cfg, "web", web)
        row = next(item for item in sites if item["site_kind"] == "http_client")
        self.assertIsNone(row["http_suffix"])
        self.assertIsNone(row["http_path"])
        self.assertEqual(row["resolution"], "unresolved")
        self.assertEqual(row["norm_tail"], "getheight")
        _ = svc

    def test_exclusion_and_escape_do_not_supply_a_normalizer(self) -> None:
        client = """
import { normalizeNodeUrl } from "./hidden";
import { joinUrl } from "../../outside";
export function probe(nodeUrl: string) {
  const normalized = normalizeNodeUrl(nodeUrl);
  const joined = joinUrl(nodeUrl);
  fetch(`${normalized}getheight`, { method: "GET" });
  fetch(`${joined}status`, { method: "GET" });
}
"""
        cfg, web, _svc = self._world(
            "boundary",
            {
                "src/client.ts": client,
                "src/hidden.ts": _NORMALIZER.replace("normalizeNodeUrl", "normalizeNodeUrl"),
                "outside.ts": _NORMALIZER.replace("normalizeNodeUrl", "joinUrl"),
            },
            {"src/rpc.cpp": _rpc()},
            exclude=["src/hidden.ts"],
        )
        sites, _symbols = _stored(cfg, "web", web)
        paths = {row["path"] for row in sites}
        self.assertNotIn("src/hidden.ts", paths)
        clients = [row for row in sites if row["site_kind"] == "http_client"]
        self.assertEqual(len(clients), 2)
        self.assertTrue(all(row["http_suffix"] is None and row["http_path"] is None for row in clients))
        self.assertTrue(all(row["resolution"] == "unresolved" for row in clients))
        self.assertTrue((web / "outside.ts").is_file())
        self.assertTrue((web / "src" / "hidden.ts").is_file())


def _process(table: str) -> str:
    return f"""
void process(const HttpRequest& request) {{
  const auto& url = request.getUrl();
  auto it = {table}.find(url);
}}
"""


@unittest.skipUnless(structural_ready(), "pinned tree-sitter parsers are not installed")
class HandlerBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["XDG_CACHE_HOME"] = str(self.tmp / "cache")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _svc(self, name: str, files: dict):
        root = self.tmp / name
        root.mkdir(parents=True)
        _git_init(root)
        for rel, text in files.items():
            _write(root / rel, text if text.endswith("\n") else text + "\n")
        cfg = _config(
            root,
            [
                {
                    "id": "svc",
                    "root": ".",
                    "role": "working",
                    "related": [],
                    "include": [],
                    "exclude": [],
                }
            ],
        )
        index_repository(cfg, "svc")
        return cfg, root

    def _bound(self, cfg, root, route: str = "/getheight"):
        sites, symbols = _stored(cfg, "svc", root)
        row = next(
            site
            for site in sites
            if site["site_kind"] == "http_route" and site["http_path"] == route
        )
        symbol = next(
            (item for item in symbols if item["symbol_id"] == row["handler_symbol_id"]),
            None,
        )
        return row, symbol, symbols

    def test_namespace_pointer_traverses_definition_and_keeps_http_candidate(self) -> None:
        header = """
namespace cn {
struct RpcServer {
  bool on_get_height(const Req& req, Resp& res);
};
}
"""
        cpp = """
namespace other {
struct RpcServer {
  bool on_get_height();
};
bool RpcServer::on_get_height() { return false; }
}
namespace cn {
void note() {}
bool RpcServer::on_get_height(const Req&, Resp&) { note(); return true; }
std::unordered_map<std::string, Handler> routes = {
  { "/getheight", { wrap(&RpcServer::on_get_height), true } },
};
""" + _process("routes") + "}\n"
        client = _NORMALIZER + """
export function probe(nodeUrl: string) {
  const normalized = normalizeNodeUrl(nodeUrl);
  return fetch(`${normalized}getheight`, { method: "GET" });
}
"""
        base = self.tmp / "cross"
        web = base / "web"
        svc = base / "svc"
        web.mkdir(parents=True)
        svc.mkdir()
        _git_init(web)
        _git_init(svc)
        _write(web / "src" / "client.ts", client)
        _write(svc / "src" / "rpc.h", header)
        _write(svc / "src" / "rpc.cpp", cpp)
        cfg = _config(
            web,
            [
                {
                    "id": "web",
                    "root": ".",
                    "role": "working",
                    "related": ["svc"],
                    "include": [],
                    "exclude": [],
                },
                {
                    "id": "svc",
                    "root": str(svc),
                    "role": "reference",
                    "related": [],
                    "include": [],
                    "exclude": [],
                },
            ],
        )
        index_repository(cfg, "web")
        index_repository(cfg, "svc")
        sites, symbols = _stored(cfg, "svc", svc)
        route = next(row for row in sites if row["http_path"] == "/getheight")
        bound = next(row for row in symbols if row["symbol_id"] == route["handler_symbol_id"])
        self.assertEqual(bound["qualified_name"], "cn::RpcServer::on_get_height")
        self.assertEqual(bound["path"], "src/rpc.cpp")
        decls = [
            row
            for row in symbols
            if row["qualified_name"] == "cn::RpcServer::on_get_height" and row["path"] == "src/rpc.h"
        ]
        self.assertEqual(len(decls), 1)
        self.assertNotEqual(decls[0]["symbol_id"], bound["symbol_id"])
        line = _line(web / "src" / "client.ts", "function probe")
        awareness = awareness_report(
            cfg, repo="web", path="src/client.ts", line=line, depth=2, limit=40
        )
        http = [edge for edge in awareness["relationships"] if edge["kind"] == "http_request_to_handler"]
        self.assertEqual(len(http), 1)
        self.assertEqual(http[0]["status"], "candidate")
        self.assertEqual(http[0]["path_status"], "candidate")
        self.assertEqual(http[0]["target_symbol_id"], bound["symbol_id"])
        self.assertIsNone(http[0]["expansion"])
        followed = [
            edge
            for edge in awareness["relationships"]
            if edge["source"].get("symbol_id") == bound["symbol_id"]
        ]
        self.assertTrue(followed)
        self.assertTrue(all(edge["path_status"] == "candidate" for edge in followed))
        self.assertTrue(
            any(edge["kind"] == "cpp_decl_def" and edge["status"] == "candidate" for edge in followed)
            or any(
                edge["kind"] == "cpp_decl_def" and edge["target_symbol_id"] == bound["symbol_id"]
                for edge in awareness["relationships"]
            )
        )

    def test_inner_class_hides_outer_and_missing_member_stays_unresolved(self) -> None:
        cpp = """
namespace outer {
struct Svc { void run(); };
void Svc::run() { return; }
namespace inner {
  struct Svc { void run(); void stop(); };
  void Svc::run() { return; }
  std::unordered_map<std::string, Handler> routes = {
    { "/getheight", { wrap(&Svc::run), true } },
  };
""" + _process("routes") + """
  namespace hidden {
    struct Svc { void stop(); };
    std::unordered_map<std::string, Handler> other = {
      { "/stop", { wrap(&Svc::run), true } },
    };
""" + _process("other").replace("void process", "void process_hidden") + """
  }
}
}
"""
        cfg, root = self._svc("hide", {"src/rpc.cpp": cpp})
        sites, symbols = _stored(cfg, "svc", root)
        inner = next(row for row in sites if row["http_path"] == "/getheight")
        bound = next(row for row in symbols if row["symbol_id"] == inner["handler_symbol_id"])
        self.assertEqual(bound["qualified_name"], "outer::inner::Svc::run")
        hidden = next(row for row in sites if row["http_path"] == "/stop")
        self.assertIsNone(hidden["handler_symbol_id"])
        self.assertEqual(json.loads(hidden["payload_json"])["handler_binding"], "unresolved")

    def test_header_overload_and_duplicate_definitions_stop(self) -> None:
        header = """
struct Svc {
  void run();
  void run(int code);
};
"""
        cpp = """
void note() {}
void Svc::run() { note(); }
struct Dup { void run(); };
void Dup::run() { note(); }
void Dup::run() { note(); }
std::unordered_map<std::string, Handler> routes = {
  { "/getheight", { wrap(&Svc::run), true } },
};
std::unordered_map<std::string, Handler> dups = {
  { "/dup", { wrap(&Dup::run), true } },
};
void process(const HttpRequest& request) {
  const auto& url = request.getUrl();
  routes.find(url);
  dups.find(url);
}
"""
        client = """
export function probe(base: string) {
  return fetch(`${base}/getheight`, { method: "GET" });
}
"""
        cfg, root = self._svc(
            "over",
            {"src/svc.h": header, "src/svc.cpp": cpp, "src/client.ts": client},
        )
        sites, _symbols = _stored(cfg, "svc", root)
        by_path = {row["http_path"]: row for row in sites if row["site_kind"] == "http_route"}
        for path in ("/getheight", "/dup"):
            self.assertIsNone(by_path[path]["handler_symbol_id"])
            payload = json.loads(by_path[path]["payload_json"])
            self.assertEqual(payload["handler_binding"], "ambiguous")
            self.assertGreaterEqual(len(payload["handler_alternatives"]), 2)
        report = context_report(
            cfg, repo="svc", path="src/client.ts", line=_line(root / "src" / "client.ts", "function probe")
        )
        http = [edge for edge in report["relationships"] if edge["kind"] == "http_request_to_handler"]
        self.assertEqual(len(http), 1)
        self.assertEqual(http[0]["status"], "candidate")
        self.assertEqual(http[0]["path_status"], "candidate")
        self.assertEqual(http[0]["expansion"], "stopped_ambiguity")
        self.assertIsNone(http[0]["target_symbol_id"])
        self.assertGreaterEqual(len(http[0]["alternatives"]), 2)

    def test_global_scope_binds_and_missing_scope_does_not(self) -> None:
        cpp = """
struct Svc { void run(); };
void note() {}
void Svc::run() { note(); }
std::unordered_map<std::string, Handler> routes = {
  { "/getheight", { wrap(&Svc::run), true } },
};
""" + _process("routes")
        cfg, root = self._svc("global", {"src/svc.cpp": cpp})
        route, symbol, _symbols = self._bound(cfg, root)
        self.assertEqual(symbol["qualified_name"], "Svc::run")
        payload = json.loads(route["payload_json"])
        self.assertEqual(payload["handler_scope"], [])
        self.assertFalse(payload["handler_absolute"])
        from py_indexer.relate import rebuild_relationships
        from py_indexer.store import open_index

        conn = open_index(
            cfg.db_path("svc"),
            "svc",
            checkout=root,
            fingerprint=cfg.content_fingerprint("svc"),
        )
        try:
            payload.pop("handler_scope")
            payload.pop("handler_absolute", None)
            conn.execute(
                "UPDATE sites SET payload_json = ?, handler_symbol_id = NULL WHERE site_id = ?",
                (json.dumps(payload), route["site_id"]),
            )
            rebuild_relationships(conn)
            conn.commit()
            refreshed = conn.execute(
                "SELECT handler_symbol_id, payload_json FROM sites WHERE site_id = ?",
                (route["site_id"],),
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNone(refreshed["handler_symbol_id"])
        self.assertEqual(json.loads(refreshed["payload_json"])["handler_binding"], "unresolved")

    def test_anonymous_namespace_stays_in_its_file(self) -> None:
        shared = """
namespace {
struct Svc { void run(); };
void Svc::run() { return; }
}
"""
        cpp = shared + """
namespace {
std::unordered_map<std::string, Handler> routes = {
  { "/getheight", { wrap(&Svc::run), true } },
};
""" + _process("routes") + "}\n"
        cfg, root = self._svc("anon", {"src/a.cpp": cpp, "src/b.cpp": shared})
        _route, symbol, symbols = self._bound(cfg, root)
        self.assertEqual(symbol["path"], "src/a.cpp")
        other = [
            row
            for row in symbols
            if row["qualified_name"].endswith("Svc::run") and row["path"] == "src/b.cpp"
        ]
        self.assertTrue(other)
        self.assertNotEqual(symbol["symbol_id"], other[0]["symbol_id"])

    def test_parameter_names_pair_and_qualifiers_do_not(self) -> None:
        cpp = """
struct Box {
  void take(void (*cb)(int x));
  void unnamed(const int&, char*);
  void run();
  void run() const;
};
void note() {}
void Box::take(void (*cb)(int name)) { note(); }
void Box::unnamed(const int& value, char* text) { note(); }
void Box::run() { note(); }
void Box::run() const { note(); }
std::unordered_map<std::string, Handler> routes = {
  { "/take", { wrap(&Box::take), true } },
  { "/plain", { wrap(&Box::unnamed), true } },
  { "/run", { wrap(&Box::run), true } },
};
""" + _process("routes")
        cfg, root = self._svc("params", {"src/box.cpp": cpp})
        sites, symbols = _stored(cfg, "svc", root)
        by_path = {row["http_path"]: row for row in sites if row["site_kind"] == "http_route"}
        take = next(row for row in symbols if row["symbol_id"] == by_path["/take"]["handler_symbol_id"])
        plain = next(row for row in symbols if row["symbol_id"] == by_path["/plain"]["handler_symbol_id"])
        self.assertEqual(take["qualified_name"], "Box::take")
        self.assertEqual(plain["qualified_name"], "Box::unnamed")
        self.assertIsNone(by_path["/run"]["handler_symbol_id"])
        self.assertEqual(json.loads(by_path["/run"]["payload_json"])["handler_binding"], "ambiguous")
        from py_indexer.store import open_index

        conn = open_index(
            cfg.db_path("svc"),
            "svc",
            checkout=root,
            fingerprint=cfg.content_fingerprint("svc"),
        )
        try:
            pairs = conn.execute(
                """
                SELECT s.qualified_name AS source_name, s.scope_json AS source_scope,
                       t.scope_json AS target_scope, r.status
                FROM relationships r
                JOIN symbols s ON s.symbol_id = r.source_symbol_id
                JOIN symbols t ON t.symbol_id = r.target_symbol_id
                WHERE r.kind = 'cpp_decl_def' AND r.status = 'candidate'
                  AND s.name IN ('take', 'unnamed', 'run')
                """
            ).fetchall()
        finally:
            conn.close()
        from py_indexer.relate import _stored_param_key

        paired = {row["source_name"] for row in pairs}
        self.assertIn("Box::take", paired)
        self.assertIn("Box::unnamed", paired)
        run_keys = set()
        for row in pairs:
            if row["source_name"] != "Box::run":
                continue
            source_key = _stored_param_key(row["source_scope"])
            target_key = _stored_param_key(row["target_scope"])
            self.assertEqual(source_key, target_key)
            run_keys.add(source_key)
        self.assertEqual(run_keys, {"()", "() const"})

    def test_absolute_qualifier_uses_the_named_namespace(self) -> None:
        cpp = """
namespace other {
struct RpcServer { void on_get_height(); };
void note() {}
void RpcServer::on_get_height() { note(); }
}
namespace cn {
struct RpcServer { void on_get_height(); };
void RpcServer::on_get_height() { return; }
std::unordered_map<std::string, Handler> routes = {
  { "/getheight", { wrap(&::other::RpcServer::on_get_height), true } },
};
""" + _process("routes") + "}\n"
        cfg, root = self._svc("abs", {"src/rpc.cpp": cpp})
        _route, symbol, _symbols = self._bound(cfg, root)
        self.assertEqual(symbol["qualified_name"], "other::RpcServer::on_get_height")
