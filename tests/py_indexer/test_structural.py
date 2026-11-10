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
                ) VALUES
                  (1,'src/note.py','call',1,1,1,4,0,4,'sA','name.many','unresolved','overloaded()','{}',0),
                  (2,'src/note.py','call',2,1,2,4,0,4,'sA','lang.call','unresolved','dynamic()','{}',0)
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
        self.assertFalse(aware["truncation"]["truncated"])
        self.assertEqual(aware["truncation"]["completeness"], "depth")
        self.assertIsNone(aware["truncation"]["omitted_relationships"])
        self.assertGreater(aware["truncation"]["expansion_stopped_ambiguity"], 0)
        limited = awareness_report(self.cfg, symbol_id="sA", depth=2, limit=1)
        self.assertTrue(limited["truncation"]["truncated"])
        self.assertEqual(limited["truncation"]["completeness"], "budget")
        self.assertIsNone(limited["truncation"]["omitted_relationships"])


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


def _call_rows(cfg, repo: str, checkout: Path) -> list[dict]:
    from py_indexer.store import open_index

    conn = open_index(
        cfg.db_path(repo),
        repo,
        checkout=checkout,
        fingerprint=cfg.content_fingerprint(repo),
    )
    try:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT r.status, r.rule_id, r.reason, r.target_symbol_id,
                       s.expression_text AS expression_text,
                       src.qualified_name AS source_name,
                       tgt.qualified_name AS target_name
                FROM relationships r
                LEFT JOIN sites s ON s.site_id = r.source_site_id
                LEFT JOIN symbols src ON src.symbol_id = r.source_symbol_id
                LEFT JOIN symbols tgt ON tgt.symbol_id = r.target_symbol_id
                WHERE r.kind = 'call'
                """
            )
        ]
    finally:
        conn.close()


def _call(rows: list[dict], source: str, expression: str) -> dict:
    found = [
        row
        for row in rows
        if row["source_name"] == source and row["expression_text"] == expression
    ]
    if len(found) != 1:
        raise AssertionError(f"{source} {expression}: {found}")
    return found[0]


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

    def test_qualified_calls_follow_scope_and_exact_components(self) -> None:
        cpp = """
namespace inner { void run() {} }
namespace outer {
namespace inner { void run() {} }
void relative() { inner::run(); }
}
void absolute() { ::inner::run(); }
struct Svc { void run(); };
void Svc::run() {}
struct OtherSvc { void run(); };
void OtherSvc::run() {}
void use_svc() { Svc::run(); }
namespace box {
struct Svc { void stop(); };
void Svc::stop() {}
void missing() { Svc::run(); }
}
namespace n {
void run(int);
void run(char);
void ambiguous() { n::run(1); }
}
struct Pair { void run(int); };
void Pair::run(int) { return; }
void call_pair() { Pair::run(1); }
void call_alias() { Alias::run(); }
"""
        cfg, root = self._svc("qual", {"src/q.cpp": cpp})
        rows = _call_rows(cfg, "svc", root)
        relative = _call(rows, "outer::relative", "inner::run()")
        self.assertEqual(relative["status"], "resolved")
        self.assertEqual(relative["rule_id"], "bind.qualified")
        self.assertEqual(relative["target_name"], "outer::inner::run")
        absolute = _call(rows, "absolute", "::inner::run()")
        self.assertEqual(absolute["status"], "resolved")
        self.assertEqual(absolute["target_name"], "inner::run")
        svc = _call(rows, "use_svc", "Svc::run()")
        self.assertEqual(svc["status"], "resolved")
        self.assertEqual(svc["target_name"], "Svc::run")
        missing = _call(rows, "box::missing", "Svc::run()")
        self.assertEqual(missing["status"], "unresolved")
        self.assertIsNone(missing["target_name"])
        overloads = [
            row
            for row in rows
            if row["source_name"] == "n::ambiguous" and row["expression_text"] == "n::run(1)"
        ]
        self.assertEqual(len(overloads), 2)
        self.assertTrue(all(row["status"] == "ambiguous" for row in overloads))
        self.assertTrue(all(row["target_name"] == "n::run" for row in overloads))
        paired = _call(rows, "call_pair", "Pair::run(1)")
        self.assertEqual(paired["status"], "resolved")
        self.assertEqual(paired["target_name"], "Pair::run")
        alias = _call(rows, "call_alias", "Alias::run()")
        self.assertEqual(alias["status"], "unresolved")
        symbols = {row["symbol_id"]: row for row in _stored(cfg, "svc", root)[1]}
        ambiguous_id = next(
            row["symbol_id"] for row in symbols.values() if row["qualified_name"] == "n::ambiguous"
        )
        aware = awareness_report(cfg, symbol_id=ambiguous_id, depth=1, limit=20)
        shown = [edge for edge in aware["relationships"] if edge["kind"] == "call"]
        self.assertEqual(len(shown), 1)
        self.assertEqual(shown[0]["status"], "ambiguous")
        self.assertEqual(shown[0]["expansion"], "stopped_ambiguity")
        self.assertGreaterEqual(len(shown[0]["alternatives"]), 2)


def _commit_all(path: Path) -> None:
    import subprocess

    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "t"], check=True)


def _open_db(cfg, repo: str, checkout: Path):
    from py_indexer.store import open_index

    return open_index(
        cfg.db_path(repo),
        repo,
        checkout=checkout,
        fingerprint=cfg.content_fingerprint(repo),
    )


class RetrievalRemediationTests(StructuralOfflineTests):
    def _index(self):
        index_repository(self.cfg, "app")
        return _open_db(self.cfg, "app", self.target)

    def test_incoming_edge_is_emitted_once_with_its_source_site(self) -> None:
        conn = self._index()
        try:
            conn.execute(
                """
                INSERT INTO symbols(
                  symbol_id, identity_key, path, language, kind, name, qualified_name,
                  signature, params, scope_json, anon_ord, body_hash
                ) VALUES
                  ('sCaller','kCaller','src/note.py','python','function','caller','caller','caller()','()','[]',NULL,NULL),
                  ('sMid','kMid','src/note.py','python','function','mid','mid','mid()','()','[]',NULL,NULL),
                  ('sLeaf','kLeaf','src/note.py','python','function','leaf','leaf','leaf()','()','[]',NULL,NULL)
                """
            )
            conn.execute(
                """
                INSERT INTO occurrences(
                  symbol_id, path, role, start_line, start_col, end_line, end_col, start_byte, end_byte
                ) VALUES
                  ('sCaller','src/note.py','decl_and_def',1,1,6,1,0,1),
                  ('sMid','src/note.py','decl_and_def',8,1,10,1,0,1),
                  ('sLeaf','src/note.py','decl_and_def',12,1,13,1,0,1)
                """
            )
            conn.execute(
                """
                INSERT INTO sites(
                  site_id, path, site_kind, start_line, start_col, end_line, end_col, start_byte, end_byte,
                  enclosing_symbol_id, rule_id, resolution, expression_text, payload_json, evidence_truncated
                ) VALUES
                  (10,'src/note.py','call',4,1,4,6,0,1,'sCaller','lang.call','unresolved','mid()','{}',0),
                  (11,'src/note.py','call',9,1,9,7,0,1,'sMid','lang.call','unresolved','leaf()','{}',0),
                  (12,'src/note.py','call',5,1,5,10,0,1,'sCaller','lang.call','unresolved','mystery()','{}',0)
                """
            )
            conn.execute(
                """
                INSERT INTO relationships(
                  kind, status, source_site_id, source_symbol_id, target_symbol_id, target_key,
                  rule_id, reason, evidence_json, evidence_truncated
                ) VALUES
                  ('call','resolved',10,'sCaller','sMid','mid','bind.scope','scope','["mid()"]',0),
                  ('call','resolved',11,'sMid','sLeaf','leaf','bind.scope','scope','["leaf()"]',0)
                """
            )
        finally:
            conn.close()
        aware = awareness_report(self.cfg, symbol_id="sLeaf", depth=2, limit=20)
        ids = [edge["id"] for edge in aware["relationships"]]
        self.assertEqual(ids, sorted(set(ids), key=ids.index))
        to_leaf = [edge for edge in aware["relationships"] if edge["target"]["symbol_id"] == "sLeaf"]
        self.assertEqual(len(to_leaf), 1)
        self.assertEqual(to_leaf[0]["traversal"], "incoming")
        self.assertEqual(to_leaf[0]["source"]["symbol_id"], "sMid")
        self.assertEqual(to_leaf[0]["target"]["symbol_id"], "sLeaf")
        self.assertEqual(to_leaf[0]["traversal_neighbor"]["id"], "sMid")
        self.assertEqual(to_leaf[0]["source"]["path"], "src/note.py")
        self.assertEqual(to_leaf[0]["source"]["start_line"], 9)
        self.assertEqual(to_leaf[0]["target"]["path"], "src/note.py")
        self.assertEqual(to_leaf[0]["target"]["start_line"], 12)
        self.assertNotIn("_source_site_id", to_leaf[0])
        from_caller = [edge for edge in aware["relationships"] if edge["source"]["symbol_id"] == "sCaller"]
        self.assertEqual(len(from_caller), 1)
        self.assertEqual(from_caller[0]["traversal"], "incoming")
        self.assertEqual(from_caller[0]["target"]["symbol_id"], "sMid")
        direct = context_report(self.cfg, symbol_id="sCaller")
        self.assertEqual(direct["truncation"]["completeness"], "depth")
        self.assertFalse(direct["truncation"]["truncated"])
        self.assertEqual(direct["truncation"]["depth_limit"], 1)
        self.assertIsNone(direct["truncation"]["omitted_relationships"])
        self.assertEqual(
            [edge["target"]["symbol_id"] for edge in direct["relationships"]],
            ["sMid"],
        )
        unresolved = [edge["target"].get("expression") for edge in direct["unresolved"]["sites"]]
        self.assertIn("mystery()", unresolved)
        self.assertNotIn("mid()", unresolved)

    def test_gitignore_change_refuses_the_snapshot(self) -> None:
        _write(self.target / "src" / "hidden.py", "def hidden_fn():\n    return 1\n")
        conn = self._index()
        try:
            conn.execute(
                """
                INSERT INTO symbols(
                  symbol_id, identity_key, path, language, kind, name, qualified_name,
                  signature, params, scope_json, anon_ord, body_hash
                ) VALUES (
                  'sHide','kHide','src/hidden.py','python','function','hidden_fn',
                  'hidden_fn','hidden_fn()','()','[]',NULL,NULL
                )
                """
            )
        finally:
            conn.close()
        _write(self.target / ".gitignore", "src/hidden.py\n")
        report = awareness_report(self.cfg, symbol_id="sHide", depth=2, limit=20)
        blob = json.dumps(report)
        self.assertEqual(report["selection"]["status"], "structural_unavailable")
        self.assertEqual(report["relationships"], [])
        self.assertNotIn("hidden.py", blob)
        self.assertNotIn("sHide", blob)
        self.assertTrue(any("index policy mismatch" in warning for warning in report["warnings"]))

    def test_eligible_snapshot_filters_hidden_targets(self) -> None:
        _write(self.target / "src" / "hidden.py", "def hidden_fn():\n    return 1\n")
        _write(self.target / ".gitignore", "src/hidden.py\n")
        conn = self._index()
        try:
            conn.execute(
                """
                INSERT INTO files(path, content_hash, size, mtime_ns, language)
                VALUES ('src/hidden.py', 'hidden', 1, 0, 'python')
                """
            )
            conn.execute(
                """
                INSERT INTO symbols(
                  symbol_id, identity_key, path, language, kind, name, qualified_name,
                  signature, params, scope_json, anon_ord, body_hash
                ) VALUES
                  ('sCall','kCall','src/note.py','python','function','caller','caller','caller()','()','[]',NULL,NULL),
                  ('sKeep','kKeep','src/note.py','python','function','keep','keep','keep()','()','[]',NULL,NULL),
                  ('sHide','kHide','src/hidden.py','python','function','hidden_fn','hidden_fn','hidden_fn()','()','[]',NULL,NULL),
                  ('sSecret','kSecret','src/hidden.py','python','function','secret','secret','secret()','()','[]',NULL,NULL)
                """
            )
            conn.execute(
                """
                INSERT INTO occurrences(
                  symbol_id, path, role, start_line, start_col, end_line, end_col, start_byte, end_byte
                ) VALUES
                  ('sCall','src/note.py','decl_and_def',1,1,1,1,0,1),
                  ('sKeep','src/note.py','decl_and_def',2,1,2,1,0,1),
                  ('sHide','src/hidden.py','decl_and_def',1,1,1,1,0,1),
                  ('sSecret','src/hidden.py','decl_and_def',2,1,2,1,0,1)
                """
            )
            conn.execute(
                """
                INSERT INTO sites(
                  site_id, path, site_kind, start_line, start_col, end_line, end_col, start_byte, end_byte,
                  enclosing_symbol_id, rule_id, resolution, expression_text, payload_json, evidence_truncated
                ) VALUES
                  (1,'src/note.py','call',2,1,2,6,0,1,'sCall','lang.call','unresolved','keep()','{}',0),
                  (2,'src/note.py','call',3,1,3,12,0,1,'sCall','lang.call','unresolved','hidden_fn()','{}',0),
                  (3,'src/hidden.py','call',1,1,1,8,0,1,'sHide','lang.call','unresolved','secret()','{}',0),
                  (4,'src/note.py','call',4,1,4,10,0,1,'sCall','lang.call','unresolved','missing()','{}',0),
                  (5,'src/note.py','call',5,1,5,6,0,1,'sCall','name.many','unresolved','twin()','{}',0)
                """
            )
            conn.execute(
                """
                INSERT INTO relationships(
                  kind, status, source_site_id, source_symbol_id, target_symbol_id, target_key,
                  rule_id, reason, evidence_json, evidence_truncated
                ) VALUES
                  ('call','resolved',1,'sCall','sKeep','keep','bind.scope','scope','["keep()"]',0),
                  ('call','candidate',2,'sCall','sHide','hidden_fn','name.unique','unique','["hidden_fn()"]',0),
                  ('call','resolved',3,'sHide','sSecret','secret','bind.scope','scope','["secret()"]',0),
                  ('call','ambiguous',5,'sCall','sKeep','twin','name.many','many','[]',0),
                  ('call','ambiguous',5,'sCall','sHide','twin','name.many','many','[]',0)
                """
            )
        finally:
            conn.close()
        report = awareness_report(self.cfg, symbol_id="sCall", depth=2, limit=20)
        blob = json.dumps(report)
        self.assertNotIn("hidden.py", blob)
        self.assertNotIn("sSecret", blob)
        self.assertNotIn("sHide", blob)
        kept = [edge for edge in report["relationships"] if edge["status"] == "resolved"]
        self.assertEqual(report["selection"]["status"], "selected")
        self.assertEqual([edge["target"]["symbol_id"] for edge in kept], ["sKeep"])
        self.assertFalse(any("index policy mismatch" in warning for warning in report["warnings"]))
        self.assertEqual(kept[0]["source"]["path"], "src/note.py")
        ambiguous = [edge for edge in report["relationships"] if edge["status"] == "ambiguous"]
        self.assertEqual(len(ambiguous), 1)
        self.assertEqual(ambiguous[0]["expansion"], "stopped_ambiguity")
        self.assertEqual([alt["path"] for alt in ambiguous[0]["alternatives"]], ["src/note.py"])
        self.assertEqual(ambiguous[0]["status"], "ambiguous")
        expressions = [edge["target"].get("expression") for edge in report["unresolved"]["sites"]]
        self.assertIn("missing()", expressions)
        self.assertNotIn("keep()", expressions)

    def test_exact_budget_and_hop_cap_leave_omissions_unknown(self) -> None:
        conn = self._index()
        try:
            conn.execute(
                """
                INSERT INTO symbols(
                  symbol_id, identity_key, path, language, kind, name, qualified_name,
                  signature, params, scope_json, anon_ord, body_hash
                ) VALUES
                  ('sRoot','kRoot','src/note.py','python','function','root','root','root()','()','[]',NULL,NULL),
                  ('sHop','kHop','src/note.py','python','function','hop','hop','hop()','()','[]',NULL,NULL),
                  ('sTail','kTail','src/note.py','python','function','tail','tail','tail()','()','[]',NULL,NULL)
                """
            )
            conn.execute(
                """
                INSERT INTO occurrences(
                  symbol_id, path, role, start_line, start_col, end_line, end_col, start_byte, end_byte
                ) VALUES
                  ('sRoot','src/note.py','decl_and_def',1,1,1,1,0,1),
                  ('sHop','src/note.py','decl_and_def',2,1,2,1,0,1),
                  ('sTail','src/note.py','decl_and_def',3,1,3,1,0,1)
                """
            )
            conn.execute(
                """
                INSERT INTO relationships(
                  kind, status, source_site_id, source_symbol_id, target_symbol_id, target_key,
                  rule_id, reason, evidence_json, evidence_truncated
                ) VALUES
                  ('call','resolved',NULL,'sRoot','sHop','hop','bind.scope','scope','[]',0),
                  ('call','resolved',NULL,'sHop','sTail','tail','bind.scope','scope','[]',0)
                """
            )
        finally:
            conn.close()
        limited = awareness_report(self.cfg, symbol_id="sRoot", depth=3, limit=1)
        self._assert_budget(limited)
        self.assertEqual([edge["target"]["symbol_id"] for edge in limited["relationships"]], ["sHop"])
        conn = _open_db(self.cfg, "app", self.target)
        try:
            conn.execute("DELETE FROM relationships")
            conn.executemany(
                """
                INSERT INTO relationships(
                  kind, status, source_site_id, source_symbol_id, target_symbol_id, target_key,
                  rule_id, reason, evidence_json, evidence_truncated
                ) VALUES ('call','resolved',NULL,'sRoot','sHop','hop','bind.scope','scope','[]',0)
                """,
                [()] * 101,
            )
        finally:
            conn.close()
        overflow = awareness_report(self.cfg, symbol_id="sRoot", depth=1, limit=80)
        self._assert_budget(overflow)
        self.assertLessEqual(len(overflow["relationships"]), 100)

    def test_serialized_report_respects_the_byte_cap(self) -> None:
        from py_indexer.context_cmd import serialize_report
        from py_indexer.structural import OUTPUT_BYTE_CAP

        conn = self._index()
        try:
            conn.execute(
                """
                INSERT INTO symbols(
                  symbol_id, identity_key, path, language, kind, name, qualified_name,
                  signature, params, scope_json, anon_ord, body_hash
                ) VALUES
                  ('sRoot','kRoot','src/note.py','python','function','root','root','root()','()','[]',NULL,NULL),
                  ('sHop','kHop','src/note.py','python','function','hop','hop','hop()','()','[]',NULL,NULL)
                """
            )
            conn.execute(
                """
                INSERT INTO occurrences(
                  symbol_id, path, role, start_line, start_col, end_line, end_col, start_byte, end_byte
                ) VALUES ('sRoot','src/note.py','decl_and_def',1,1,1,1,0,1)
                """
            )
            evidence = json.dumps(["e" * 1800])
            conn.executemany(
                """
                INSERT INTO relationships(
                  kind, status, source_site_id, source_symbol_id, target_symbol_id, target_key,
                  rule_id, reason, evidence_json, evidence_truncated
                ) VALUES ('call','resolved',NULL,'sRoot','sHop','hop','bind.scope','scope',?,0)
                """,
                [(evidence,)] * 40,
            )
        finally:
            conn.close()
        report = awareness_report(self.cfg, symbol_id="sRoot", depth=1, limit=80)
        text = serialize_report(report)
        self.assertLessEqual(len(text.encode("utf-8")), OUTPUT_BYTE_CAP)
        self.assertEqual(json.loads(text)["selection"]["symbol_id"], "sRoot")
        self.assertEqual(report["selection"]["status"], "selected")
        self._assert_budget(report)
        self.assertEqual(report["truncation"]["reason"], "output_bytes")
        self.assertTrue(report["snapshots"])

    def test_payload_over_the_cap_round_trips(self) -> None:
        from py_indexer.relate import _load, _payload

        text, cut = _payload({"callee": "run", "qualifier": "Svc", "blob": "x" * 4000, "args": 1})
        self.assertTrue(cut)
        loaded = json.loads(text)
        self.assertIsInstance(loaded, dict)
        again = _load(text)
        self.assertNotEqual(again, {})
        self.assertTrue(again.get("truncated") or again.get("unavailable"))
        if again.get("unavailable"):
            self.assertTrue(again.get("reason"))
        else:
            self.assertEqual(again["callee"], "run")
            self.assertEqual(again["qualifier"], "Svc")
            self.assertNotIn("blob", again)
        huge = {
            key: "y" * 400
            for key in (
                "callee",
                "qualifier",
                "receiver",
                "handler",
                "classification",
                "path_known",
                "specifier",
                "command",
            )
        }
        huge["names"] = ["n" * 80] * 20
        text2, _cut2 = _payload(huge)
        json.loads(text2)
        again2 = _load(text2)
        self.assertNotEqual(again2, {})
        self.assertTrue(again2.get("unavailable") or again2.get("truncated"))
        if again2.get("unavailable"):
            self.assertIn("reason", again2)
        malformed = _load('{"callee":')
        self.assertTrue(malformed.get("unavailable"))
        self.assertNotEqual(malformed, {})
        self.assertTrue(_load("[]").get("unavailable"))

    def test_unreadable_selected_repository_is_structured(self) -> None:
        lib = self.tmp / "lib"
        web = self.tmp / "web"
        lib.mkdir()
        web.mkdir()
        _git_init(lib)
        _git_init(web)
        _write(lib / "src" / "a.py", "def alpha():\n    return 1\n")
        _write(web / "src" / "b.ts", "export function beta() { return 1 }\n")
        cfg = _config(
            web,
            [
                {
                    "id": "web",
                    "root": ".",
                    "role": "working",
                    "related": ["lib"],
                    "include": [],
                    "exclude": [],
                },
                {
                    "id": "lib",
                    "root": str(lib),
                    "role": "reference",
                    "related": [],
                    "include": [],
                    "exclude": [],
                },
            ],
        )
        index_repository(cfg, "lib")
        missing = context_report(cfg, repo="web", path="src/b.ts", line=1)
        self.assertEqual(missing["selection"]["status"], "structural_unavailable")
        self.assertEqual(missing["relationships"], [])
        self.assertTrue(any(snap["repo_id"] == "lib" for snap in missing["snapshots"]))
        index_repository(cfg, "web")
        conn = _open_db(cfg, "web", web)
        try:
            conn.execute("UPDATE meta SET value = ? WHERE key = 'analysis_fingerprint'", ("stale",))
        finally:
            conn.close()
        bad = context_report(cfg, repo="web", path="src/b.ts", line=1)
        self.assertEqual(bad["selection"]["status"], "structural_incompatible")
        self.assertEqual(bad["relationships"], [])

    def test_freshness_uses_only_contributing_paths(self) -> None:
        from py_indexer.context_cmd import _refresh_snapshot

        _commit_all(self.target)
        self._index().close()
        self._insert_note_symbol()
        current = context_report(self.cfg, symbol_id="sNote")
        self.assertEqual(current["snapshots"][0]["freshness"], "current")
        _write(self.target / "src" / "extra.ts", "export const extra = 1\n")
        untouched = context_report(self.cfg, symbol_id="sNote")
        self.assertEqual(untouched["snapshots"][0]["freshness"], "current")
        _write(self.target / "src" / "note.py", "def lexical_only_marker():\n    return 2\n")
        changed = context_report(self.cfg, symbol_id="sNote")
        self.assertEqual(changed["snapshots"][0]["freshness"], "worktree_changed")

        fresh = self.tmp / "fresh"
        fresh.mkdir()
        _git_init(fresh)
        _write(fresh / "src" / "note.py", "def lexical_only_marker():\n    return 1\n")
        cfg = _config(
            fresh,
            [{"id": "app", "root": ".", "role": "working", "related": [], "include": [], "exclude": []}],
        )
        saved_target, self.target, self.cfg = self.target, fresh, cfg
        try:
            index_repository(cfg, "app")
            _commit_all(fresh)
            self._insert_note_symbol()
            dirty = context_report(cfg, symbol_id="sNote")
            self.assertEqual(dirty["snapshots"][0]["freshness"], "dirty_at_index")
        finally:
            self.target, self.cfg = saved_target, self.cfg

        moved = self.tmp / "moved"
        moved.mkdir()
        _git_init(moved)
        _write(moved / "src" / "note.py", "def lexical_only_marker():\n    return 1\n")
        _commit_all(moved)
        cfg = _config(
            moved,
            [{"id": "app", "root": ".", "role": "working", "related": [], "include": [], "exclude": []}],
        )
        index_repository(cfg, "app")
        self.target, self.cfg = moved, cfg
        self._insert_note_symbol()
        _write(moved / "src" / "note.py", "def lexical_only_marker():\n    return 3\n")
        _commit_all(moved)
        jumped = context_report(cfg, symbol_id="sNote")
        self.assertEqual(jumped["snapshots"][0]["freshness"], "commit_moved")
        shutil.rmtree(moved / ".git")
        refused = context_report(cfg, symbol_id="sNote")
        self.assertEqual(refused["selection"]["status"], "structural_unavailable")
        self.assertEqual(refused["relationships"], [])
        self.assertTrue(any("index policy mismatch" in warning for warning in refused["warnings"]))
        calls = []

        def spy(root, paths):
            calls.append(list(paths))
            return []

        import py_indexer.context_cmd as context_mod

        original = context_mod.worktree_dirty_paths
        context_mod.worktree_dirty_paths = spy
        try:
            item = {"repo": type("Repo", (), {"root": moved})()}
            snap = {
                "warnings": [],
                "indexed_commit": "abc",
                "current_commit": "abc",
                "indexed_dirty": False,
            }
            _refresh_snapshot(snap, item, [])
            self.assertEqual(calls, [])
            self.assertEqual(snap["freshness"], "current")
            context_mod.worktree_dirty_paths = lambda root, paths: None
            unknown = {
                "warnings": [],
                "indexed_commit": "abc",
                "current_commit": "abc",
                "indexed_dirty": False,
            }
            _refresh_snapshot(unknown, item, ["src/note.py"])
            self.assertEqual(unknown["freshness"], "unknown")
            self.assertTrue(any("could not answer" in warning for warning in unknown["warnings"]))
        finally:
            context_mod.worktree_dirty_paths = original

    def _assert_budget(self, report) -> None:
        truncation = report["truncation"]
        unresolved = report["unresolved"]
        self.assertTrue(truncation["truncated"])
        self.assertEqual(truncation["completeness"], "budget")
        self.assertFalse(truncation["omitted_known"])
        self.assertIsNone(truncation["omitted_relationships"])
        self.assertIsNone(unresolved["omitted"])
        self.assertFalse(unresolved["omitted_known"])

    def test_configured_exclude_refuses_the_snapshot(self) -> None:
        _write(self.target / "src" / "hidden.py", "def hidden_fn():\n    return 1\n")
        conn = self._index()
        try:
            conn.execute(
                """
                INSERT INTO symbols(
                  symbol_id, identity_key, path, language, kind, name, qualified_name,
                  signature, params, scope_json, anon_ord, body_hash
                ) VALUES (
                  'sHide','kHide','src/hidden.py','python','function','hidden_fn',
                  'hidden_fn','hidden_fn()','()','[]',NULL,NULL
                )
                """
            )
        finally:
            conn.close()
        _write(self.cfg.config_dir / "excludes.txt", "src/hidden.py\n")
        report = awareness_report(self.cfg, symbol_id="sHide", depth=2, limit=20)
        blob = json.dumps(report)
        self.assertEqual(report["selection"]["status"], "structural_unavailable")
        self.assertEqual(report["relationships"], [])
        self.assertNotIn("hidden.py", blob)
        self.assertNotIn("sHide", blob)
        self.assertTrue(any("index policy mismatch" in warning for warning in report["warnings"]))

    def test_hidden_source_is_filtered(self) -> None:
        _write(self.target / "src" / "hidden.py", "def hidden_fn():\n    return 1\n")
        _write(self.target / ".gitignore", "src/hidden.py\n")
        conn = self._index()
        try:
            conn.execute(
                """
                INSERT INTO files(path, content_hash, size, mtime_ns, language)
                VALUES ('src/hidden.py', 'hidden', 1, 0, 'python')
                """
            )
            conn.execute(
                """
                INSERT INTO symbols(
                  symbol_id, identity_key, path, language, kind, name, qualified_name,
                  signature, params, scope_json, anon_ord, body_hash
                ) VALUES
                  ('sVisible','kVisible','src/note.py','python','function','visible','visible','visible()','()','[]',NULL,NULL),
                  ('sSibling','kSibling','src/note.py','python','function','sibling','sibling','sibling()','()','[]',NULL,NULL),
                  ('sHidden','kHidden','src/hidden.py','python','function','hidden_fn','hidden_fn','hidden_fn()','()','[]',NULL,NULL)
                """
            )
            conn.execute(
                """
                INSERT INTO occurrences(
                  symbol_id, path, role, start_line, start_col, end_line, end_col, start_byte, end_byte
                ) VALUES
                  ('sVisible','src/note.py','decl_and_def',1,1,1,1,0,1),
                  ('sSibling','src/note.py','decl_and_def',2,1,2,1,0,1),
                  ('sHidden','src/hidden.py','decl_and_def',1,1,1,1,0,1)
                """
            )
            conn.execute(
                """
                INSERT INTO sites(
                  site_id, path, site_kind, start_line, start_col, end_line, end_col, start_byte, end_byte,
                  enclosing_symbol_id, rule_id, resolution, expression_text, payload_json, evidence_truncated
                ) VALUES
                  (1,'src/note.py','call',2,1,2,8,0,1,'sSibling','lang.call','unresolved','visible()','{}',0),
                  (2,'src/hidden.py','call',1,1,1,8,0,1,'sHidden','lang.call','unresolved','visible()','{}',0),
                  (3,'src/hidden.py','call',2,1,2,8,0,1,'sHidden','lang.call','unresolved','secret()','{}',0)
                """
            )
            conn.execute(
                """
                INSERT INTO relationships(
                  kind, status, source_site_id, source_symbol_id, target_symbol_id, target_key,
                  rule_id, reason, evidence_json, evidence_truncated
                ) VALUES
                  ('call','resolved',1,'sSibling','sVisible','visible','bind.scope','scope','["visible()"]',0),
                  ('call','resolved',2,'sHidden','sVisible','visible','bind.scope','scope','["visible()"]',0)
                """
            )
        finally:
            conn.close()
        report = awareness_report(self.cfg, symbol_id="sVisible", depth=2, limit=20)
        blob = json.dumps(report)
        self.assertEqual(report["selection"]["status"], "selected")
        sources = [edge["source"]["symbol_id"] for edge in report["relationships"]]
        self.assertEqual(sources, ["sSibling"])
        self.assertNotIn("sHidden", blob)
        self.assertNotIn("hidden.py", blob)
        self.assertNotIn("secret()", blob)
        self.assertFalse(any("index policy mismatch" in warning for warning in report["warnings"]))

    def test_omitted_relationship_keeps_its_unresolved_terminal(self) -> None:
        conn = self._index()
        try:
            conn.execute(
                """
                INSERT INTO symbols(
                  symbol_id, identity_key, path, language, kind, name, qualified_name,
                  signature, params, scope_json, anon_ord, body_hash
                ) VALUES
                  ('sRoot','kRoot','src/note.py','python','function','root','root','root()','()','[]',NULL,NULL),
                  ('sKeep','kKeep','src/note.py','python','function','keep','keep','keep()','()','[]',NULL,NULL),
                  ('sOther','kOther','src/note.py','python','function','other','other','other()','()','[]',NULL,NULL)
                """
            )
            conn.execute(
                """
                INSERT INTO occurrences(
                  symbol_id, path, role, start_line, start_col, end_line, end_col, start_byte, end_byte
                ) VALUES
                  ('sRoot','src/note.py','decl_and_def',1,1,1,1,0,1),
                  ('sKeep','src/note.py','decl_and_def',2,1,2,1,0,1),
                  ('sOther','src/note.py','decl_and_def',3,1,3,1,0,1)
                """
            )
            conn.execute(
                """
                INSERT INTO sites(
                  site_id, path, site_kind, start_line, start_col, end_line, end_col, start_byte, end_byte,
                  enclosing_symbol_id, rule_id, resolution, expression_text, payload_json, evidence_truncated
                ) VALUES
                  (10,'src/note.py','call',2,1,2,6,0,1,'sRoot','lang.call','unresolved','keep()','{}',0),
                  (11,'src/note.py','call',3,1,3,7,0,1,'sRoot','lang.call','unresolved','other()','{}',0),
                  (12,'src/note.py','call',4,1,4,9,0,1,'sRoot','lang.call','unresolved','mystery()','{}',0)
                """
            )
            conn.execute(
                """
                INSERT INTO relationships(
                  kind, status, source_site_id, source_symbol_id, target_symbol_id, target_key,
                  rule_id, reason, evidence_json, evidence_truncated
                ) VALUES
                  ('call','resolved',10,'sRoot','sKeep','keep','bind.scope','scope','["keep()"]',0),
                  ('call','resolved',11,'sRoot','sOther','other','bind.scope','scope','["other()"]',0)
                """
            )
        finally:
            conn.close()
        report = awareness_report(self.cfg, symbol_id="sRoot", depth=2, limit=1)
        self._assert_budget(report)
        self.assertEqual([edge["target"]["symbol_id"] for edge in report["relationships"]], ["sKeep"])
        expressions = [edge["target"].get("expression") for edge in report["unresolved"]["sites"]]
        self.assertIn("other()", expressions)
        self.assertIn("mystery()", expressions)
        self.assertNotIn("keep()", expressions)

    def test_candidate_incoming_path_stays_candidate(self) -> None:
        conn = self._index()
        try:
            self._insert_chain(
                conn,
                ("sHere", "sMid", "sSrc", "sTail"),
                (
                    ("sSrc", "sMid", "candidate"),
                    ("sMid", "sHere", "resolved"),
                    ("sSrc", "sTail", "resolved"),
                ),
            )
        finally:
            conn.close()
        report = awareness_report(self.cfg, symbol_id="sHere", depth=3, limit=20)
        by_pair = {
            (edge["source"]["symbol_id"], edge["target"]["symbol_id"]): edge
            for edge in report["relationships"]
        }
        self.assertEqual(by_pair[("sSrc", "sMid")]["path_status"], "candidate")
        self.assertEqual(by_pair[("sSrc", "sTail")]["path_status"], "candidate")
        self.assertEqual(by_pair[("sMid", "sHere")]["path_status"], "resolved")

    def test_two_paths_do_not_resolve_the_weaker_one(self) -> None:
        conn = self._index()
        try:
            self._insert_chain(
                conn,
                ("sR", "sA", "sB", "sC", "sD"),
                (
                    ("sR", "sA", "resolved"),
                    ("sR", "sB", "candidate"),
                    ("sA", "sC", "resolved"),
                    ("sB", "sC", "resolved"),
                    ("sC", "sD", "resolved"),
                ),
            )
        finally:
            conn.close()
        report = awareness_report(self.cfg, symbol_id="sR", depth=3, limit=20)
        by_pair = {
            (edge["source"]["symbol_id"], edge["target"]["symbol_id"]): edge
            for edge in report["relationships"]
        }
        self.assertEqual(by_pair[("sA", "sC")]["path_status"], "resolved")
        self.assertEqual(by_pair[("sC", "sD")]["path_status"], "candidate")
        self.assertTrue(any(hop["status"] == "candidate" for hop in by_pair[("sC", "sD")]["via"]))
        for edge in report["relationships"]:
            if edge["status"] == "candidate" or any(hop["status"] == "candidate" for hop in edge["via"]):
                self.assertEqual(edge["path_status"], "candidate")

    def test_oversized_sections_stay_inside_the_byte_cap(self) -> None:
        from py_indexer.context_cmd import _fit, serialize_report
        from py_indexer.structural import OUTPUT_BYTE_CAP

        def check(body: dict) -> dict:
            fitted = _fit(body)
            text = serialize_report(fitted)
            self.assertLessEqual(len(text.encode("utf-8")), OUTPUT_BYTE_CAP)
            self.assertEqual(json.loads(text)["truncation"]["completeness"], "budget")
            self._assert_budget(fitted)
            return fitted

        huge = "p" * 4000
        check(
            {
                "selection": {
                    "status": "selected",
                    "symbol_id": "sRoot",
                    "signature": "S" * 100000,
                    "locations": [{"path": huge, "start_line": 1}] * 40,
                    "candidates": [{"name": huge}] * 20,
                },
                "snapshots": [{"repo_id": "app", "warnings": []}],
                "relationships": [],
                "unresolved": {"shown": 0, "omitted": 0, "omitted_known": True, "sites": []},
                "truncation": {"truncated": False, "omitted_relationships": 0, "omitted_known": True},
                "warnings": [],
            }
        )
        check(
            {
                "selection": {"status": "selected", "symbol_id": "sRoot", "locations": [], "candidates": []},
                "snapshots": [{"repo_id": "app", "warnings": []}],
                "relationships": [],
                "unresolved": {"shown": 0, "omitted": 0, "omitted_known": True, "sites": []},
                "truncation": {"truncated": False, "omitted_relationships": 0, "omitted_known": True},
                "warnings": ["w" * 8000] * 20,
            }
        )
        fitted_snap = check(
            {
                "selection": {"status": "selected", "symbol_id": "sRoot", "locations": [], "candidates": []},
                "snapshots": [{"repo_id": "app", "indexed_commit": "c" * 90000, "warnings": ["s" * 90000]}],
                "relationships": [],
                "unresolved": {"shown": 0, "omitted": 0, "omitted_known": True, "sites": []},
                "truncation": {"truncated": False, "omitted_relationships": 0, "omitted_known": True},
                "warnings": [],
            }
        )
        self.assertLess(len(fitted_snap["snapshots"][0]["indexed_commit"]), 90000)
        check(
            {
                "selection": {"status": "selected", "symbol_id": "sRoot", "locations": [], "candidates": []},
                "snapshots": [{"repo_id": "app", "warnings": []}],
                "relationships": [],
                "unresolved": {
                    "shown": 30,
                    "omitted": 0,
                    "omitted_known": True,
                    "sites": [
                        {
                            "id": f"site-{index}",
                            "status": "unresolved",
                            "evidence": ["e" * 4000],
                            "source": {"path": "src/note.py"},
                            "target": {"expression": "mystery()"},
                        }
                        for index in range(30)
                    ],
                },
                "truncation": {"truncated": False, "omitted_relationships": 0, "omitted_known": True},
                "warnings": [],
            }
        )

    def test_every_budget_stop_marks_counts_unknown(self) -> None:
        from py_indexer.context_cmd import _open_repos, _walk

        conn = self._index()
        try:
            self._insert_chain(conn, ("sRoot", "sHop"), (("sRoot", "sHop", "resolved"),))
        finally:
            conn.close()
        clamped = awareness_report(self.cfg, symbol_id="sRoot", depth=99, limit=20)
        self._assert_budget(clamped)
        self.assertEqual(clamped["truncation"]["reason"], "hard_cap")
        self.assertEqual(clamped["depth_limit"], 3)

        conn = _open_db(self.cfg, "app", self.target)
        try:
            conn.execute("DELETE FROM relationships")
            hubs = [f"sH{index}" for index in range(100)]
            leaves = [f"sL{index}" for index in range(300)]
            conn.executemany(
                """
                INSERT INTO symbols(
                  symbol_id, identity_key, path, language, kind, name, qualified_name,
                  signature, params, scope_json, anon_ord, body_hash
                ) VALUES (?, ?, 'src/note.py','python','function', ?, ?, '()','()','[]',NULL,NULL)
                """,
                [(name, "k" + name, name, name + "()") for name in hubs + leaves],
            )
            conn.executemany(
                """
                INSERT INTO relationships(
                  kind, status, source_site_id, source_symbol_id, target_symbol_id, target_key,
                  rule_id, reason, evidence_json, evidence_truncated
                ) VALUES ('call','resolved',NULL,?,?,'hop','bind.scope','scope','[]',0)
                """,
                [("sRoot", name) for name in hubs]
                + [(hubs[index // 3], leaves[index]) for index in range(300)],
            )
        finally:
            conn.close()
        opened = _open_repos(self.cfg, ["app"])
        try:
            readable = [item for item in opened if item["conn"] is not None]
            _rels, unresolved, truncation = _walk(
                self.cfg,
                readable,
                {"repo_id": "app", "kind": "symbol", "id": "sRoot"},
                depth_limit=2,
                limit=10000,
            )
        finally:
            for item in opened:
                if item["conn"] is not None:
                    item["conn"].close()
        self._assert_budget({"truncation": truncation, "unresolved": unresolved})

    def _insert_chain(self, conn, names: tuple[str, ...], edges: tuple[tuple[str, str, str], ...]) -> None:
        conn.executemany(
            """
            INSERT INTO symbols(
              symbol_id, identity_key, path, language, kind, name, qualified_name,
              signature, params, scope_json, anon_ord, body_hash
            ) VALUES (?, ?, 'src/note.py','python','function', ?, ?, '()','()','[]',NULL,NULL)
            """,
            [(name, "k" + name, name, name + "()") for name in names],
        )
        conn.executemany(
            """
            INSERT INTO occurrences(
              symbol_id, path, role, start_line, start_col, end_line, end_col, start_byte, end_byte
            ) VALUES (?, 'src/note.py','decl_and_def',1,1,1,1,0,1)
            """,
            [(name,) for name in names],
        )
        conn.executemany(
            """
            INSERT INTO relationships(
              kind, status, source_site_id, source_symbol_id, target_symbol_id, target_key,
              rule_id, reason, evidence_json, evidence_truncated
            ) VALUES ('call', ?, NULL, ?, ?, ?, 'bind.scope','scope','[]',0)
            """,
            [(status, source, target, target) for source, target, status in edges],
        )

    def _insert_note_symbol(self) -> None:
        conn = _open_db(self.cfg, "app", self.target)
        try:
            conn.execute(
                """
                INSERT INTO symbols(
                  symbol_id, identity_key, path, language, kind, name, qualified_name,
                  signature, params, scope_json, anon_ord, body_hash
                ) VALUES (
                  'sNote','kNote','src/note.py','python','function','lexical_only_marker',
                  'lexical_only_marker','lexical_only_marker()','()','[]',NULL,NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO occurrences(
                  symbol_id, path, role, start_line, start_col, end_line, end_col, start_byte, end_byte
                ) VALUES ('sNote','src/note.py','decl_and_def',1,1,2,1,0,1)
                """
            )
        finally:
            conn.close()
