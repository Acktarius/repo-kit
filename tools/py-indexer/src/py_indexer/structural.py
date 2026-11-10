"""Structural schema, verified parser pins, and analysis fingerprints.

Lexical schema stays at ``SCHEMA_VERSION``. Structural tables are additive.
The analysis fingerprint changes when rules or the verified parser matrix
change. It does not change just because this process cannot import parsers.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

from py_indexer.store import _meta_get, set_meta

STRUCTURAL_SCHEMA_VERSION = 2
EXTRACTOR_VERSION = 1
RULES_VERSION = 4
CONST_RESOLVE_VERSION = 1

NODE_CAP = 200_000
SYMBOL_CAP = 5_000
SITE_CAP = 5_000
EVIDENCE_CHARS = 240
EVIDENCE_ITEMS = 4
SIGNATURE_CHARS = 500
EXPRESSION_CHARS = 200

CONTEXT_DEFAULT_LIMIT = 20
CONTEXT_HARD_LIMIT = 50
AWARENESS_DEFAULT_DEPTH = 2
AWARENESS_HARD_DEPTH = 3
AWARENESS_DEFAULT_LIMIT = 40
AWARENESS_HARD_LIMIT = 80
ALTERNATIVE_CAP = 8
HOP_CANDIDATE_CAP = 100
INTERMEDIATE_CAP = 200
OUTPUT_BYTE_CAP = 48_000

# Filled by the same-process smoke parse on 2026-11-09.
# tree-sitter 0.26.1 accepts grammar ABI 13 through 15.
RUNTIME_PIN = {
    "package": "tree-sitter",
    "version": "0.26.1",
    "language_version": 15,
    "min_compatible": 13,
}
PARSER_PINS = {
    "cpp": {
        "package": "tree-sitter-cpp",
        "version": "0.23.4",
        "module": "tree_sitter_cpp",
        "symbol": "language",
        "abi": 14,
    },
    "javascript": {
        "package": "tree-sitter-javascript",
        "version": "0.25.0",
        "module": "tree_sitter_javascript",
        "symbol": "language",
        "abi": 15,
    },
    "typescript": {
        "package": "tree-sitter-typescript",
        "version": "0.23.2",
        "module": "tree_sitter_typescript",
        "symbol": "language_typescript",
        "abi": 14,
    },
    "tsx": {
        "package": "tree-sitter-typescript",
        "version": "0.23.2",
        "module": "tree_sitter_typescript",
        "symbol": "language_tsx",
        "abi": 14,
    },
    "rust": {
        "package": "tree-sitter-rust",
        "version": "0.24.2",
        "module": "tree_sitter_rust",
        "symbol": "language",
        "abi": 15,
    },
}

CPP_EXTENSIONS = {
    ".cc",
    ".cpp",
    ".cxx",
    ".c++",
    ".hh",
    ".hpp",
    ".hxx",
    ".h",
    ".ipp",
    ".tcc",
}
JS_EXTENSIONS = {".js", ".jsx", ".mjs", ".cjs"}
TS_EXTENSIONS = {".ts", ".mts", ".cts"}
TSX_EXTENSIONS = {".tsx"}
RUST_EXTENSIONS = {".rs"}
LEXICAL_ONLY_C = {".c"}

META_STRUCTURAL_SCHEMA = "structural_schema_version"
META_ANALYSIS_FINGERPRINT = "analysis_fingerprint"
META_PARSER_RUNTIME = "parser_runtime"
META_STRUCTURAL_STATUS = "structural_status"
META_SNAPSHOT = "snapshot_id"
META_INDEXED_DIRTY = "indexed_dirty"

_PROBE: dict | None = None


def structural_language(path: str) -> str | None:
    """Parser language for a relative path, or None when this file is not parsed.

    ``.h`` uses the C++ grammar. ``.c`` stays lexical-only.
    """
    ext = "." + path.lower().rsplit(".", 1)[-1] if "." in path else ""
    if ext in LEXICAL_ONLY_C:
        return None
    if ext in CPP_EXTENSIONS:
        return "cpp"
    if ext in JS_EXTENSIONS:
        return "javascript"
    if ext in TS_EXTENSIONS:
        return "typescript"
    if ext in TSX_EXTENSIONS:
        return "tsx"
    if ext in RUST_EXTENSIONS:
        return "rust"
    return None


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def code_fingerprint() -> str:
    """Fingerprint of rules and the verified pin matrix. Independent of schema."""
    payload = {
        "structural_schema_version": STRUCTURAL_SCHEMA_VERSION,
        "extractor_version": EXTRACTOR_VERSION,
        "rules_version": RULES_VERSION,
        "const_resolve": CONST_RESOLVE_VERSION,
        "node_cap": NODE_CAP,
        "symbol_cap": SYMBOL_CAP,
        "site_cap": SITE_CAP,
        "runtime": RUNTIME_PIN,
        "parsers": PARSER_PINS,
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def probe_parsers() -> dict:
    """Load the pinned grammars once. Never downloads and never raises."""
    global _PROBE
    if _PROBE is not None:
        return _PROBE
    out: dict = {
        "runtime": {"status": "missing", **RUNTIME_PIN},
        "languages": {},
    }
    try:
        import importlib.metadata as metadata
        from tree_sitter import (  # type: ignore
            LANGUAGE_VERSION,
            MIN_COMPATIBLE_LANGUAGE_VERSION,
            Language,
        )
    except Exception as exc:  # noqa: BLE001
        out["runtime"]["status"] = "missing"
        out["runtime"]["detail"] = type(exc).__name__
        for lang in PARSER_PINS:
            out["languages"][lang] = "missing"
        _PROBE = out
        return out

    runtime_version = _dist_version(metadata, "tree-sitter")
    abi_ok = (
        runtime_version == RUNTIME_PIN["version"]
        and int(LANGUAGE_VERSION) == RUNTIME_PIN["language_version"]
        and int(MIN_COMPATIBLE_LANGUAGE_VERSION) == RUNTIME_PIN["min_compatible"]
    )
    out["runtime"]["status"] = "ready" if abi_ok else "mismatch"
    out["runtime"]["loaded_version"] = runtime_version
    out["runtime"]["language_version"] = int(LANGUAGE_VERSION)
    out["runtime"]["min_compatible"] = int(MIN_COMPATIBLE_LANGUAGE_VERSION)
    if not abi_ok:
        for lang in PARSER_PINS:
            out["languages"][lang] = "runtime_mismatch"
        _PROBE = out
        return out

    import importlib

    for lang, pin in PARSER_PINS.items():
        try:
            if _dist_version(metadata, pin["package"]) != pin["version"]:
                out["languages"][lang] = "version_mismatch"
                continue
            module = importlib.import_module(pin["module"])
            capsule = getattr(module, pin["symbol"])()
            language = Language(capsule)
            abi = int(language.abi_version)
            if abi != pin["abi"]:
                out["languages"][lang] = "abi_mismatch"
                continue
            if not (
                MIN_COMPATIBLE_LANGUAGE_VERSION <= abi <= LANGUAGE_VERSION
            ):
                out["languages"][lang] = "abi_out_of_range"
                continue
            out["languages"][lang] = "ready"
            out.setdefault("_languages", {})[lang] = language
        except Exception:  # noqa: BLE001
            out["languages"][lang] = "missing"
    _PROBE = out
    return out


def _dist_version(metadata, name: str) -> str:
    try:
        return metadata.version(name)
    except Exception:  # noqa: BLE001
        return ""


def reset_probe_for_tests() -> None:
    global _PROBE
    _PROBE = None


def language_ready(lang: str) -> bool:
    return probe_parsers()["languages"].get(lang) == "ready"


def loaded_language(lang: str):
    probe_parsers()
    return (_PROBE or {}).get("_languages", {}).get(lang)


def runtime_token() -> str:
    probe = probe_parsers()
    payload = {
        "runtime": probe["runtime"].get("status"),
        "languages": probe["languages"],
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()[:16]


def file_fingerprint() -> str:
    return code_fingerprint() + ":" + runtime_token()


def structural_ready() -> bool:
    probe = probe_parsers()
    return probe["runtime"].get("status") == "ready" and all(
        probe["languages"].get(lang) == "ready" for lang in PARSER_PINS
    )


def clip(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True


_SCHEMA = """
CREATE TABLE IF NOT EXISTS file_structure (
  path TEXT PRIMARY KEY REFERENCES files(path) ON DELETE CASCADE,
  language TEXT NOT NULL,
  status TEXT NOT NULL,
  parser_fingerprint TEXT NOT NULL,
  error_count INTEGER NOT NULL,
  truncated INTEGER NOT NULL,
  detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS symbols (
  symbol_id TEXT PRIMARY KEY,
  identity_key TEXT NOT NULL UNIQUE,
  path TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE,
  language TEXT NOT NULL,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  qualified_name TEXT NOT NULL,
  signature TEXT NOT NULL,
  params TEXT NOT NULL,
  scope_json TEXT NOT NULL,
  anon_ord INTEGER,
  body_hash TEXT
);
CREATE TABLE IF NOT EXISTS occurrences (
  occurrence_id INTEGER PRIMARY KEY,
  symbol_id TEXT NOT NULL REFERENCES symbols(symbol_id) ON DELETE CASCADE,
  path TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE,
  role TEXT NOT NULL,
  start_line INTEGER NOT NULL,
  start_col INTEGER NOT NULL,
  end_line INTEGER NOT NULL,
  end_col INTEGER NOT NULL,
  start_byte INTEGER NOT NULL,
  end_byte INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sites (
  site_id INTEGER PRIMARY KEY,
  path TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE,
  site_kind TEXT NOT NULL,
  start_line INTEGER NOT NULL,
  start_col INTEGER NOT NULL,
  end_line INTEGER NOT NULL,
  end_col INTEGER NOT NULL,
  start_byte INTEGER NOT NULL,
  end_byte INTEGER NOT NULL,
  enclosing_symbol_id TEXT,
  rule_id TEXT NOT NULL,
  resolution TEXT NOT NULL,
  expression_text TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  http_method TEXT,
  http_path TEXT,
  http_suffix TEXT,
  http_boundary TEXT,
  http_rev TEXT,
  dispatch_key TEXT,
  norm_name TEXT,
  norm_spec TEXT,
  norm_tail TEXT,
  handler_key TEXT,
  handler_symbol_id TEXT,
  exec_id TEXT,
  exec_args_norm TEXT,
  net_host TEXT,
  net_port INTEGER,
  net_role TEXT,
  net_wildcard INTEGER,
  rpc_command TEXT,
  evidence_truncated INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS relationships (
  relationship_id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,
  status TEXT NOT NULL,
  source_site_id INTEGER REFERENCES sites(site_id) ON DELETE CASCADE,
  source_symbol_id TEXT,
  target_symbol_id TEXT,
  target_key TEXT NOT NULL DEFAULT '',
  rule_id TEXT NOT NULL,
  reason TEXT NOT NULL,
  evidence_json TEXT NOT NULL,
  evidence_truncated INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_symbols_path ON symbols(path);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_qualified ON symbols(qualified_name);
CREATE INDEX IF NOT EXISTS idx_occurrences_symbol ON occurrences(symbol_id);
CREATE INDEX IF NOT EXISTS idx_occurrences_line ON occurrences(path, start_line);
CREATE INDEX IF NOT EXISTS idx_sites_enclosing ON sites(enclosing_symbol_id);
CREATE INDEX IF NOT EXISTS idx_sites_kind ON sites(site_kind, resolution);
CREATE INDEX IF NOT EXISTS idx_sites_http ON sites(http_method, http_path)
  WHERE http_method IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sites_http_path ON sites(http_path)
  WHERE http_path IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sites_http_rev ON sites(http_rev)
  WHERE http_rev IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sites_http_suffix ON sites(http_boundary, http_suffix)
  WHERE http_suffix IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sites_exec ON sites(exec_id)
  WHERE exec_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sites_net ON sites(net_port, net_role)
  WHERE net_port IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sites_rpc ON sites(rpc_command)
  WHERE rpc_command IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_rel_kind_status ON relationships(kind, status);
CREATE INDEX IF NOT EXISTS idx_rel_source_sym ON relationships(source_symbol_id);
CREATE INDEX IF NOT EXISTS idx_rel_target_sym ON relationships(target_symbol_id);
CREATE INDEX IF NOT EXISTS idx_rel_rule ON relationships(rule_id, status);
"""


def ensure_structural_schema(conn: sqlite3.Connection) -> None:
    """Create structural tables. Drop them first when the schema version is unknown."""
    ver = _meta_get(conn, META_STRUCTURAL_SCHEMA)
    if ver is not None and ver != str(STRUCTURAL_SCHEMA_VERSION):
        for name in (
            "relationships",
            "sites",
            "occurrences",
            "symbols",
            "file_structure",
        ):
            conn.execute(f"DROP TABLE IF EXISTS {name}")
        ver = None
    for statement in _SCHEMA.split(";"):
        sql = statement.strip()
        if sql:
            conn.execute(sql)
    if ver is None:
        set_meta(conn, META_STRUCTURAL_SCHEMA, str(STRUCTURAL_SCHEMA_VERSION))


def structural_tables_present(conn: sqlite3.Connection) -> bool:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    names = {row["name"] for row in rows}
    return {"file_structure", "symbols", "occurrences", "sites", "relationships"} <= names


def structural_read_state(conn: sqlite3.Connection) -> str:
    """ready, partial, unavailable, or incompatible.

    Partial data is readable. A schema or analysis-fingerprint mismatch is not.
    """
    if not structural_tables_present(conn):
        return "unavailable"
    ver = _meta_get(conn, META_STRUCTURAL_SCHEMA)
    if ver is None:
        return "unavailable"
    if ver != str(STRUCTURAL_SCHEMA_VERSION):
        return "incompatible"
    stored = _meta_get(conn, META_ANALYSIS_FINGERPRINT)
    if stored is None:
        return "unavailable"
    if stored != code_fingerprint():
        return "incompatible"
    status = _meta_get(conn, META_STRUCTURAL_STATUS) or "ready"
    if status not in ("ready", "partial", "unavailable"):
        return "incompatible"
    return status


def coverage_summary(conn: sqlite3.Connection) -> dict:
    """Per-language structural coverage, including the .c lexical-only limit."""
    summary = {
        "cpp": {"status": "unsupported"},
        "javascript": {"status": "unsupported"},
        "typescript": {"status": "unsupported"},
        "tsx": {"status": "unsupported"},
        "rust": {"status": "unsupported"},
        "c": {
            "status": "lexical_only",
            "note": ".c is not parsed; .h is parsed with the C++ grammar",
        },
    }
    if not structural_tables_present(conn):
        return summary
    rows = conn.execute(
        "SELECT language, status, COUNT(*) AS n FROM file_structure GROUP BY language, status"
    ).fetchall()
    by_lang: dict[str, dict[str, int]] = {}
    for row in rows:
        by_lang.setdefault(row["language"] or "other", {})[row["status"]] = int(row["n"])
    for lang in ("cpp", "javascript", "typescript", "tsx", "rust"):
        counts = by_lang.get(lang, {})
        if not counts:
            summary[lang]["status"] = (
                "ready" if language_ready(lang) else "parser_unavailable"
            )
            continue
        if "failed" in counts or "partial" in counts:
            summary[lang]["status"] = "partial"
        elif "parser_unavailable" in counts and "ok" not in counts:
            summary[lang]["status"] = "parser_unavailable"
        elif "ok" in counts:
            summary[lang]["status"] = "ready"
        else:
            summary[lang]["status"] = next(iter(counts))
        summary[lang]["files"] = counts
    c_counts = by_lang.get("c", {})
    if c_counts:
        summary["c"]["files"] = c_counts
    return summary
