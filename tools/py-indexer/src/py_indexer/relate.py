"""Rebuild local relationships from stored facts. Does not reparse files.

Cross-repository edges are not stored. Unresolved sites stay in ``sites``.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

from py_indexer.structural import ALTERNATIVE_CAP, EVIDENCE_CHARS, EVIDENCE_ITEMS, clip

REBUILD_MS = 0

_FUNCTION_KINDS = {"function", "method", "constructor", "operator"}
_STATUS_RANK = {"unresolved": 0, "ambiguous": 1, "candidate": 2, "resolved": 3}


def write_file_facts(conn, path: str, result, fingerprint: str) -> None:
    """Replace structural rows for one path. Lexical file row must already exist."""
    conn.execute("DELETE FROM occurrences WHERE path = ?", (path,))
    conn.execute("DELETE FROM sites WHERE path = ?", (path,))
    conn.execute("DELETE FROM symbols WHERE path = ?", (path,))
    conn.execute(
        """
        INSERT INTO file_structure(
          path, language, status, parser_fingerprint, error_count, truncated, detail
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
          language=excluded.language,
          status=excluded.status,
          parser_fingerprint=excluded.parser_fingerprint,
          error_count=excluded.error_count,
          truncated=excluded.truncated,
          detail=excluded.detail
        """,
        (
            path,
            result.language,
            result.status,
            fingerprint,
            result.error_count,
            1 if result.truncated else 0,
            result.detail,
        ),
    )
    seen: set[str] = set()
    for symbol in result.symbols:
        if symbol.symbol_id not in seen:
            conn.execute(
                """
                INSERT INTO symbols(
                  symbol_id, identity_key, path, language, kind, name, qualified_name,
                  signature, params, scope_json, anon_ord, body_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol.symbol_id,
                    symbol.identity_key,
                    symbol.path,
                    symbol.language,
                    symbol.kind,
                    symbol.name,
                    symbol.qualified_name,
                    symbol.signature,
                    symbol.params,
                    _scope_json(symbol),
                    symbol.anon_ord,
                    symbol.body_hash,
                ),
            )
            seen.add(symbol.symbol_id)
        conn.execute(
            """
            INSERT INTO occurrences(
              symbol_id, path, role, start_line, start_col, end_line, end_col,
              start_byte, end_byte
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol.symbol_id,
                symbol.path,
                symbol.role,
                symbol.start_line,
                symbol.start_col,
                symbol.end_line,
                symbol.end_col,
                symbol.start_byte,
                symbol.end_byte,
            ),
        )
    for site in result.sites:
        payload, cut = _payload(site.payload)
        conn.execute(
            """
            INSERT INTO sites(
              path, site_kind, start_line, start_col, end_line, end_col, start_byte,
              end_byte, enclosing_symbol_id, rule_id, resolution, expression_text,
              payload_json, http_method, http_path, http_suffix, http_boundary, http_rev,
              dispatch_key, norm_name, norm_spec, norm_tail, handler_key, handler_symbol_id,
              exec_id, exec_args_norm, net_host, net_port, net_role, net_wildcard, rpc_command,
              evidence_truncated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                site.path,
                site.site_kind,
                site.start_line,
                site.start_col,
                site.end_line,
                site.end_col,
                site.start_byte,
                site.end_byte,
                site.enclosing_symbol_id,
                site.rule_id,
                site.resolution,
                site.expression_text,
                payload,
                site.http_method,
                site.http_path,
                site.http_suffix,
                site.http_boundary,
                site.http_rev,
                site.dispatch_key,
                site.norm_name,
                site.norm_spec,
                site.norm_tail,
                site.handler_key,
                site.handler_symbol_id,
                site.exec_id,
                site.exec_args_norm,
                site.net_host,
                site.net_port,
                site.net_role,
                site.net_wildcard,
                site.rpc_command,
                1 if cut or site.evidence_truncated else 0,
            ),
        )


def rebuild_relationships(conn) -> dict:
    """Delete and recreate local relationship rows from symbols and sites."""
    global REBUILD_MS
    started = time.perf_counter()
    _refresh_derived_http(conn)
    symbols = [dict(row) for row in conn.execute("SELECT * FROM symbols")]
    sites = [dict(row) for row in conn.execute("SELECT * FROM sites")]
    roles: dict[str, set[str]] = defaultdict(set)
    for row in conn.execute("SELECT symbol_id, role FROM occurrences"):
        roles[row["symbol_id"]].add(row["role"])
    by_id = {row["symbol_id"]: row for row in symbols}
    conn.execute("DELETE FROM relationships")
    rows = []
    rows.extend(_bind_sites(symbols, sites, by_id, roles))
    rows.extend(_pair_declarations(symbols, roles))
    for row in rows:
        evidence, truncated = _evidence(row.pop("evidence"))
        conn.execute(
            """
            INSERT INTO relationships(
              kind, status, source_site_id, source_symbol_id, target_symbol_id,
              target_key, rule_id, reason, evidence_json, evidence_truncated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["kind"],
                row["status"],
                row.get("source_site_id"),
                row.get("source_symbol_id"),
                row.get("target_symbol_id"),
                row.get("target_key") or "",
                row["rule_id"],
                row["reason"],
                evidence,
                1 if truncated else 0,
            ),
        )
    REBUILD_MS = int((time.perf_counter() - started) * 1000)
    return {"relationships": len(rows), "relationship_rebuild_ms": REBUILD_MS}


def _bind_sites(symbols, sites, by_id, roles) -> list[dict]:
    out = []
    imports = [site for site in sites if site["site_kind"] == "import"]
    for site in sites:
        if site["site_kind"] not in {"call", "reference"}:
            if site["site_kind"] == "http_route" and site["rule_id"] != "http.cpp.table":
                out.extend(_handler_binding(site, symbols, sites, by_id, imports, roles))
            continue
        payload = _load(site["payload_json"])
        if payload.get("unavailable"):
            out.append(
                _rel(
                    kind="reference" if site["site_kind"] == "reference" else "call",
                    status="unresolved",
                    rule_id="lang.call",
                    reason="call fact is unavailable",
                    source_site_id=site["site_id"],
                    source_symbol_id=site["enclosing_symbol_id"],
                    evidence=[site["expression_text"]],
                )
            )
            continue
        name = payload.get("callee") or payload.get("name") or ""
        status, rule, targets, reason = _resolve_name(
            name,
            payload,
            site,
            symbols,
            imports,
            by_id,
            roles,
        )
        kind = "reference" if site["site_kind"] == "reference" else "call"
        if not targets:
            out.append(
                _rel(
                    kind=kind,
                    status="unresolved",
                    rule_id=rule,
                    reason=reason,
                    source_site_id=site["site_id"],
                    source_symbol_id=site["enclosing_symbol_id"],
                    evidence=[site["expression_text"]],
                )
            )
            continue
        status, rule, targets, reason = _cap(status, rule, targets, reason)
        for target in targets:
            out.append(
                _rel(
                    kind=kind,
                    status=status,
                    rule_id=rule,
                    reason=reason,
                    source_site_id=site["site_id"],
                    source_symbol_id=site["enclosing_symbol_id"],
                    target_symbol_id=target["symbol_id"],
                    target_key=target["qualified_name"],
                    evidence=[site["expression_text"], target["signature"] or target["name"]],
                )
            )
    return out


def _handler_binding(site, symbols, sites, by_id, imports, roles) -> list[dict]:
    payload = _load(site["payload_json"])
    if payload.get("unavailable"):
        return []
    handler = payload.get("handler") or ""
    if not handler:
        return []
    status, rule, targets, reason = _resolve_name(
        handler,
        {"callee": handler, "args": None, "receiver": "", "qualifier": ""},
        site,
        symbols,
        imports,
        by_id,
        roles,
    )
    if status != "resolved" or len(targets) != 1:
        return []
    return [
        _rel(
            kind="handler_binding",
            status="resolved",
            rule_id=rule,
            reason="route handler argument is a direct binding",
            source_site_id=site["site_id"],
            source_symbol_id=site["enclosing_symbol_id"],
            target_symbol_id=targets[0]["symbol_id"],
            target_key=targets[0]["qualified_name"],
            evidence=[site["expression_text"], targets[0]["name"]],
        )
    ]


def _resolve_name(name, payload, site, symbols, imports, by_id, roles):
    if not name or name.startswith("<anonymous"):
        return "unresolved", "lang.call", [], "callee is not a named binding"
    qualifier = payload.get("qualifier") or ""
    receiver = payload.get("receiver") or ""
    arg_count = payload.get("args")
    if qualifier:
        scope = _call_scope(site, by_id)
        if scope is None:
            return "unresolved", "bind.qualified", [], "caller scope is not available"
        return _qualified(name, qualifier, arg_count, symbols, scope, roles)
    if receiver and receiver not in {"this", "self"}:
        return "unresolved", "lang.call", [], "receiver type is not known from syntax"
    scoped = _scope_lookup(name, site, symbols, by_id)
    if scoped:
        return _finish_hits(scoped, arg_count, "bind.scope", "enclosing scope binding")
    imported = _import_lookup(name, site, symbols, imports)
    if imported is not None:
        return imported
    return _checkout_name(name, symbols)


def _call_scope(site, by_id):
    """Lexical frames around the call. None when the stored scope is unusable.

    An empty list is a known global scope.
    """
    enclosing_id = site.get("enclosing_symbol_id")
    if not enclosing_id or enclosing_id not in by_id:
        return []
    return _scope_frame(by_id[enclosing_id].get("scope_json"))


def _scope_frame(raw) -> list | None:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return None
    if isinstance(value, dict):
        if value.get("unavailable"):
            return None
        scope = value.get("scope")
        return list(scope) if isinstance(scope, list) else None
    if isinstance(value, list):
        return value
    return None


def _scope_names(labels: list) -> list[str]:
    names = []
    for label in labels:
        text = str(label)
        kind, _, name = text.partition(":")
        if name and kind in {"namespace", "class", "struct"}:
            names.append(name)
        elif text and ":" not in text:
            names.append(text)
    return names


def _plain_component(part: str) -> bool:
    return bool(part) and all(char.isalnum() or char == "_" for char in part)


def _component_exists(symbols, prefix: list[str], anchor: str) -> bool:
    head = prefix + [anchor]
    for row in symbols:
        if row["qualified_name"].split("::")[: len(head)] == head:
            return True
    return False


def _exact_qualified(symbols, components: list[str]) -> list:
    want = "::".join(components)
    return [
        row
        for row in symbols
        if row["qualified_name"] == want and row["kind"] in _FUNCTION_KINDS and row["name"] == components[-1]
    ]


def _collapse_same_signature(hits, roles) -> list:
    """Prefer one definition when a declaration and definition share a signature."""
    groups: dict[tuple, list] = defaultdict(list)
    for row in hits:
        groups[(row["qualified_name"], _stored_param_key(row["scope_json"]) or row["params"])].append(row)
    chosen = []
    for group in groups.values():
        definitions = [
            row
            for row in group
            if roles.get(row["symbol_id"], set()) & {"definition", "decl_and_def"}
        ]
        if len(definitions) == 1:
            chosen.append(definitions[0])
        elif definitions:
            chosen.extend(definitions)
        else:
            chosen.append(group[0])
    return chosen


def _qualified(name, qualifier, arg_count, symbols, scope_labels, roles):
    """Bind a qualified call from the caller's lexical scope.

    Components match exactly. A relative qualifier stops at the first scope
    that contains its first component. Absolute qualification starts at the
    global scope. Aliases, using directives, and inheritance are not searched.
    """
    text = str(qualifier).strip()
    absolute = text.startswith("::")
    parts = [part for part in text.split("::") if part]
    if any(not _plain_component(part) for part in parts) or not _plain_component(name):
        return "unresolved", "bind.qualified", [], "qualifier is not a supported lexical path"
    if not parts and not absolute:
        return "unresolved", "bind.qualified", [], "qualifier is not a supported lexical path"
    frames = _scope_names(scope_labels)
    if absolute:
        hits = _exact_qualified(symbols, parts + [name])
        if not hits:
            return "unresolved", "bind.qualified", [], "absolute qualifier has no symbol"
        return _finish_hits(
            _collapse_same_signature(hits, roles),
            arg_count,
            "bind.qualified",
            "absolute qualified name",
        )
    for length in range(len(frames), -1, -1):
        prefix = frames[:length]
        if not _component_exists(symbols, prefix, parts[0]):
            continue
        hits = _exact_qualified(symbols, prefix + parts + [name])
        if not hits:
            return (
                "unresolved",
                "bind.qualified",
                [],
                "qualifier is in this scope but the member is not",
            )
        return _finish_hits(
            _collapse_same_signature(hits, roles),
            arg_count,
            "bind.qualified",
            "lexical qualified name",
        )
    return "unresolved", "bind.qualified", [], "qualifier is not in the caller scope"


def _scope_lookup(name, site, symbols, by_id) -> list[dict]:
    enclosing_id = site.get("enclosing_symbol_id")
    chain: list[str] = []
    if enclosing_id and enclosing_id in by_id:
        sym = by_id[enclosing_id]
        chain = _stored_scope(sym["scope_json"]) + [f"{sym['kind']}:{sym['name']}"]
    for length in range(len(chain), -1, -1):
        prefix = tuple(chain[:length])
        hits = [
            row
            for row in symbols
            if row["path"] == site["path"]
            and row["name"] == name
            and tuple(_stored_scope(row["scope_json"])) == prefix
            and row["kind"] in _FUNCTION_KINDS | {"class", "struct"}
        ]
        if hits:
            return hits
    return []


def _import_lookup(name, site, symbols, imports):
    for imp in imports:
        if imp["path"] != site["path"]:
            continue
        payload = _load(imp["payload_json"])
        spec = str(payload.get("specifier") or "")
        if not spec.startswith("."):
            continue
        for item in payload.get("names") or []:
            if item.get("local") != name:
                continue
            target = _relative_spec(site["path"], spec)
            exported = item.get("exported") or name
            hits = [
                row
                for row in symbols
                if row["name"] == exported and _same_module(row["path"], target)
            ]
            if len(hits) == 1:
                return "resolved", "bind.import", hits, "relative named import"
            if len(hits) > 1:
                return _finish_hits(hits, None, "bind.import", "imported name has several symbols")
    return None


def _checkout_name(name, symbols):
    hits = [row for row in symbols if row["name"] == name and row["kind"] in _FUNCTION_KINDS]
    if len(hits) == 1:
        return (
            "candidate",
            "name.unique",
            hits,
            "unique name is not a scope, import, or qualified binding",
        )
    if len(hits) > 1:
        return (
            "ambiguous",
            "name.many",
            hits,
            "same name in more than one scope; uniqueness is not a binding",
        )
    return "unresolved", "lang.call", [], "no supported binding"


def _finish_hits(hits, arg_count, rule, reason):
    if len(hits) == 1:
        return "resolved", rule, hits, reason
    if arg_count is not None:
        arity_hits = [row for row in hits if _arity(row["params"]) == arg_count and not _variadic(row["params"])]
        if len(arity_hits) == 1:
            return "resolved", "bind.arity", arity_hits, "one overload matches the call arity"
        if len(arity_hits) > 1:
            return "ambiguous", "bind.arity", arity_hits, "several overloads match the call arity"
    return "ambiguous", rule, hits, "several symbols match this static rule"


def _pair_declarations(symbols, roles) -> list[dict]:
    groups: dict[tuple, list] = defaultdict(list)
    for row in symbols:
        if row["language"] != "cpp" or row["kind"] not in _FUNCTION_KINDS:
            continue
        key = _stored_param_key(row["scope_json"])
        if not key:
            continue
        groups[(row["qualified_name"], key)].append(row)
    out = []
    for group in groups.values():
        decls = [row for row in group if "declaration" in roles.get(row["symbol_id"], set())]
        defs = [row for row in group if "definition" in roles.get(row["symbol_id"], set())]
        if len(decls) == 1 and len(defs) == 1 and decls[0]["symbol_id"] != defs[0]["symbol_id"]:
            out.append(
                _rel(
                    kind="cpp_decl_def",
                    status="candidate",
                    rule_id="cpp.decl_def",
                    reason="same qualified source signature; declaration and definition stay distinct",
                    source_symbol_id=decls[0]["symbol_id"],
                    target_symbol_id=defs[0]["symbol_id"],
                    target_key=defs[0]["qualified_name"],
                    evidence=[decls[0]["signature"], defs[0]["signature"]],
                )
            )
        elif len(decls) > 1 or len(defs) > 1:
            for decl in decls[:ALTERNATIVE_CAP]:
                for definition in defs[:ALTERNATIVE_CAP]:
                    out.append(
                        _rel(
                            kind="cpp_decl_def",
                            status="ambiguous",
                            rule_id="cpp.decl_def",
                            reason="more than one declaration or definition shares this signature",
                            source_symbol_id=decl["symbol_id"],
                            target_symbol_id=definition["symbol_id"],
                            target_key=definition["qualified_name"],
                            evidence=[decl["signature"], definition["signature"]],
                        )
                    )
    return out


def _cap(status, rule, targets, reason):
    if len(targets) <= ALTERNATIVE_CAP:
        return status, rule, targets, reason
    return status, rule, targets[:ALTERNATIVE_CAP], reason + "; alternatives truncated"


def _arity(params: str) -> int | None:
    text = (params or "").strip()
    if text in {"", "()"}:
        return 0
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    if not text:
        return 0
    if "..." in text or "*args" in text or "* " in text:
        return None
    return text.count(",") + 1


def _variadic(params: str) -> bool:
    text = params or ""
    return "..." in text or "..." in text or "*args" in text


def _relative_spec(from_path: str, spec: str) -> str:
    base = Path(from_path).parent
    joined = (base / spec).as_posix()
    parts: list[str] = []
    for part in joined.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def _same_module(symbol_path: str, target: str) -> bool:
    stem_target = target
    for ext in (
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".d.ts",
    ):
        if symbol_path == target + ext or symbol_path == target:
            return True
        stem_target = stem_target
    return Path(symbol_path).with_suffix("").as_posix() == target or symbol_path == target


def _rel(**kwargs) -> dict:
    kwargs.setdefault("evidence", [])
    return kwargs


def _load(raw: str) -> dict:
    try:
        value = json.loads(raw if raw else "{}")
    except json.JSONDecodeError:
        return {"unavailable": True, "reason": "malformed payload"}
    if isinstance(value, dict):
        return value
    return {"unavailable": True, "reason": "payload is not an object"}


_PAYLOAD_CAP = 1000
_PAYLOAD_KEEP = (
    "callee",
    "qualifier",
    "receiver",
    "args",
    "handler",
    "classification",
    "path_known",
    "specifier",
    "names",
    "command",
)


def _payload_text(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _shrink_payload(payload: dict) -> dict:
    kept = {"truncated": True}
    for key in _PAYLOAD_KEEP:
        if key not in payload:
            continue
        value = payload[key]
        if isinstance(value, str) and len(value) > 160:
            kept[key] = value[:160]
        elif isinstance(value, list):
            kept[key] = value[:8]
        elif isinstance(value, (int, float, bool)) or value is None:
            kept[key] = value
        elif isinstance(value, str):
            kept[key] = value
    return kept


def _payload(payload: dict) -> tuple[str, bool]:
    """Store a site payload as valid JSON within the byte cap.

    Oversized values are shortened before serialization. The result is never a
    sliced JSON string and never an empty object standing in for a lost fact.
    """
    if not isinstance(payload, dict):
        return (
            _payload_text({"unavailable": True, "reason": "payload is not an object"}),
            True,
        )
    raw = _payload_text(payload)
    if len(raw.encode("utf-8")) <= _PAYLOAD_CAP:
        return raw, False
    shrunk = _shrink_payload(payload)
    raw = _payload_text(shrunk)
    if len(raw.encode("utf-8")) <= _PAYLOAD_CAP:
        return raw, True
    return (
        _payload_text({"unavailable": True, "reason": "payload exceeded the stored fact budget"}),
        True,
    )


def _evidence(items: list[str]) -> tuple[str, bool]:
    truncated = False
    kept = []
    for item in items[:EVIDENCE_ITEMS]:
        text, cut = clip(str(item), EVIDENCE_CHARS)
        truncated = truncated or cut
        kept.append(text)
    if len(items) > EVIDENCE_ITEMS:
        truncated = True
    return json.dumps(kept, ensure_ascii=True), truncated


def _refresh_derived_http(conn) -> None:
    """Recompute suffix and handler links from stored facts.

    The request file keeps its raw normalizer dependency. A changed
    normalizer file updates the derived suffix here without reparsing the
    request.
    """
    facts: dict[tuple[str, str], dict] = {}
    dupes: set[tuple[str, str]] = set()
    rows = conn.execute(
        """
        SELECT s.path AS path, sym.name AS name, s.payload_json AS payload
        FROM sites s
        JOIN symbols sym ON sym.symbol_id = s.enclosing_symbol_id
        WHERE s.site_kind = 'normalizer'
        """
    )
    for row in rows:
        key = (row["path"], row["name"])
        if key in facts:
            dupes.add(key)
        facts[key] = _load(row["payload"])
    for key in dupes:
        facts.pop(key, None)

    pending = conn.execute(
        """
        SELECT site_id, path, norm_name, norm_spec, norm_tail
        FROM sites
        WHERE norm_tail IS NOT NULL AND norm_name IS NOT NULL
        """
    ).fetchall()
    for site in pending:
        fact = _normalizer_fact(conn, facts, site["path"], site["norm_spec"] or "", site["norm_name"])
        if fact and fact.get("boundary") == "conditional_slash":
            conn.execute(
                """
                UPDATE sites
                SET http_suffix = ?, http_boundary = 'conditional_slash',
                    http_path = NULL, resolution = 'candidate'
                WHERE site_id = ?
                """,
                (site["norm_tail"], site["site_id"]),
            )
        else:
            conn.execute(
                """
                UPDATE sites
                SET http_suffix = NULL, http_boundary = NULL, http_path = NULL,
                    resolution = 'unresolved'
                WHERE site_id = ?
                """,
                (site["site_id"],),
            )

    _bind_handler_pointers(conn)


def _normalizer_fact(conn, facts: dict, from_path: str, spec: str, name: str) -> dict | None:
    paths = _normalizer_files(conn, from_path, spec)
    if len(paths) != 1:
        return None
    return facts.get((paths[0], name))


def _normalizer_files(conn, from_path: str, spec: str) -> list[str]:
    if spec == "":
        return [from_path]
    if not spec.startswith("."):
        return []
    resolved = _strict_relative(from_path, spec)
    if not resolved:
        return []
    rows = [row["path"] for row in conn.execute("SELECT path FROM files")]
    return [path for path in rows if _same_module(path, resolved)]


def _strict_relative(from_path: str, spec: str) -> str | None:
    """Resolve one relative specifier. Excess '..' is outside the checkout."""
    parts = list(Path(from_path).parent.parts)
    for part in Path(spec).parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
            continue
        if part.startswith("/") or part == "":
            return None
        parts.append(part)
    return "/".join(parts)


def _scope_json(symbol) -> str:
    if symbol.param_key:
        return json.dumps(
            {"scope": symbol.scope, "param_key": symbol.param_key},
            ensure_ascii=True,
        )
    return json.dumps(symbol.scope, ensure_ascii=True)


def _stored_scope(raw) -> list:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if isinstance(value, dict):
        scope = value.get("scope") or []
        return list(scope) if isinstance(scope, list) else []
    if isinstance(value, list):
        return value
    return []


def _stored_param_key(raw) -> str | None:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return None
    if isinstance(value, dict):
        key = value.get("param_key")
        return key if isinstance(key, str) and key else None
    return None


def _bind_handler_pointers(conn) -> None:
    """Bind a member pointer from its recorded lexical scope.

    A missing scope is unknown context and stays unresolved. An empty scope
    is known global scope. Lookup stops at the first scope that contains the
    first qualifier.
    """
    symbols = [dict(row) for row in conn.execute("SELECT * FROM symbols")]
    roles: dict[str, set[str]] = defaultdict(set)
    for row in conn.execute("SELECT symbol_id, role FROM occurrences"):
        roles[row["symbol_id"]].add(row["role"])
    sites = conn.execute(
        """
        SELECT site_id, path, handler_key, payload_json
        FROM sites
        WHERE handler_key IS NOT NULL AND handler_key != ''
        """
    ).fetchall()
    for site in sites:
        payload = _load(site["payload_json"])
        decision = _resolve_member_pointer(
            site["path"],
            site["handler_key"],
            payload,
            symbols,
            roles,
        )
        payload["handler_binding"] = decision["binding"]
        if decision["alternatives"]:
            payload["handler_alternatives"] = decision["alternatives"]
        else:
            payload.pop("handler_alternatives", None)
        payload["handler_alternatives_truncated"] = decision["truncated"]
        conn.execute(
            """
            UPDATE sites
            SET handler_symbol_id = ?, payload_json = ?
            WHERE site_id = ?
            """,
            (
                decision["symbol_id"],
                json.dumps(payload, ensure_ascii=True, sort_keys=True),
                site["site_id"],
            ),
        )


def _resolve_member_pointer(path, handler_key, payload, symbols, roles) -> dict:
    empty = {"binding": "unresolved", "symbol_id": None, "alternatives": [], "truncated": False}
    if "handler_scope" not in payload or not isinstance(payload.get("handler_scope"), list):
        return empty
    parts = [part for part in str(handler_key).split("::") if part]
    if len(parts) < 2:
        return empty
    absolute = bool(payload.get("handler_absolute"))
    lexical = [str(item) for item in payload["handler_scope"]]
    resolved = _resolve_qualifiers(parts[:-1], lexical, absolute, symbols, path)
    if resolved is None or resolved.get("status") != "class":
        return empty
    members = _class_members(resolved["symbol"], parts[-1], symbols, path)
    return _choose_handler(members, roles)


def _resolve_qualifiers(qualifiers, lexical, absolute, symbols, path) -> dict | None:
    if absolute:
        starts = [[]]
    else:
        frame = list(lexical)
        starts = []
        while True:
            starts.append(list(frame))
            if not frame:
                break
            frame.pop()
    for start in starts:
        found = _resolve_from(qualifiers, start, symbols, path)
        if found.get("status") == "missing":
            continue
        return found
    return None


def _resolve_from(qualifiers, start, symbols, path) -> dict:
    current = list(start)
    for index, component in enumerate(qualifiers):
        limited = _anonymous_scope(current)
        classes = _classes_named(symbols, component, current, path, limited)
        namespace = _namespace_exists(symbols, current, component, path, limited)
        if classes and namespace:
            return {"status": "ambiguous"}
        if len(classes) > 1:
            return {"status": "ambiguous"}
        if len(classes) == 1:
            current = _stored_scope(classes[0]["scope_json"]) + [
                f"{classes[0]['kind']}:{classes[0]['name']}"
            ]
            if index == len(qualifiers) - 1:
                return {"status": "class", "symbol": classes[0]}
            continue
        if namespace:
            current = current + [f"namespace:{component}"]
            continue
        return {"status": "missing" if index == 0 else "unresolved"}
    return {"status": "unresolved"}


def _classes_named(symbols, name, scope, path, limited) -> list[dict]:
    found = []
    for row in symbols:
        if row["kind"] not in {"class", "struct"} or row["name"] != name:
            continue
        if _stored_scope(row["scope_json"]) != scope:
            continue
        if limited and row["path"] != path:
            continue
        found.append(row)
    return found


def _namespace_exists(symbols, scope, name, path, limited) -> bool:
    prefix = list(scope) + [f"namespace:{name}"]
    for row in symbols:
        if limited and row["path"] != path:
            continue
        stored = _stored_scope(row["scope_json"])
        if stored[: len(prefix)] == prefix:
            return True
    return False


def _anonymous_scope(scope) -> bool:
    return any(label == "namespace:<anonymous>" for label in scope)


def _class_members(class_symbol, member_name, symbols, path) -> list[dict]:
    class_scope = _stored_scope(class_symbol["scope_json"])
    expected = [_label_name(label) for label in class_scope] + [class_symbol["name"]]
    file_local = _anonymous_scope(class_scope)
    found = []
    for row in symbols:
        if row["kind"] not in _FUNCTION_KINDS or row["name"] != member_name:
            continue
        scope = _stored_scope(row["scope_json"])
        if not scope or _label_kind(scope[-1]) not in {"class", "struct"}:
            continue
        if [_label_name(label) for label in scope] != expected:
            continue
        if (file_local or _anonymous_scope(scope)) and row["path"] != path:
            continue
        found.append(row)
    return found


def _label_name(label: str) -> str:
    return label.split(":", 1)[1] if ":" in label else label


def _label_kind(label: str) -> str:
    return label.split(":", 1)[0] if ":" in label else ""


def _choose_handler(members, roles) -> dict:
    empty = {"binding": "unresolved", "symbol_id": None, "alternatives": [], "truncated": False}
    if not members:
        return empty
    keys = [_stored_param_key(row["scope_json"]) for row in members]
    if any(key is None for key in keys):
        return _ambiguous_handlers(members, roles, "incomplete signature")
    if len(set(keys)) != 1:
        return _ambiguous_handlers(members, roles, "overload")
    defs = [row for row in members if "definition" in roles.get(row["symbol_id"], set())]
    if len(defs) == 1:
        return {
            "binding": "definition",
            "symbol_id": defs[0]["symbol_id"],
            "alternatives": [],
            "truncated": False,
        }
    if len(defs) > 1:
        return _ambiguous_handlers(defs, roles, "multiple definitions")
    return empty


def _ambiguous_handlers(members, roles, _reason) -> dict:
    ordered = sorted(members, key=lambda row: (row["path"], row["qualified_name"], row["symbol_id"]))
    shown = ordered[:ALTERNATIVE_CAP]
    alternatives = []
    for row in shown:
        role_set = roles.get(row["symbol_id"], set())
        if "definition" in role_set:
            role = "definition"
        elif "declaration" in role_set:
            role = "declaration"
        else:
            role = "unknown"
        alternatives.append(
            {
                "symbol_id": row["symbol_id"],
                "name": row["qualified_name"],
                "path": row["path"],
                "role": role,
            }
        )
    return {
        "binding": "ambiguous",
        "symbol_id": None,
        "alternatives": alternatives,
        "truncated": len(ordered) > ALTERNATIVE_CAP,
    }


def weaker(left: str, right: str) -> str:
    if _STATUS_RANK[left] <= _STATUS_RANK[right]:
        return left
    return right
