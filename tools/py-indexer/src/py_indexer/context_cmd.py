"""Read-only context and awareness retrieval.

Cross-repository edges are assembled here from each checkout's own rows.
"""

from __future__ import annotations

import json
from collections import defaultdict

from py_indexer.config import AppConfig, ConfigError
from py_indexer.exclude import git_ignored_paths, indexed_path_visible, load_exclude_rules
from py_indexer.gitinfo import git_head, worktree_dirty_paths
from py_indexer.paths import safe_join
from py_indexer.relate import weaker
from py_indexer.search_cmd import resolve_search_repos
from py_indexer.store import IndexError_, open_index, read_meta
from py_indexer.structural import (
    ALTERNATIVE_CAP,
    AWARENESS_DEFAULT_DEPTH,
    AWARENESS_DEFAULT_LIMIT,
    AWARENESS_HARD_DEPTH,
    AWARENESS_HARD_LIMIT,
    CONTEXT_DEFAULT_LIMIT,
    CONTEXT_HARD_LIMIT,
    HOP_CANDIDATE_CAP,
    INTERMEDIATE_CAP,
    META_INDEXED_DIRTY,
    META_SNAPSHOT,
    OUTPUT_BYTE_CAP,
    coverage_summary,
    structural_read_state,
)
from py_indexer.store import _meta_get

_HTTP_QUERY = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")


class SelectorError(ConfigError):
    """The caller combined selectors or omitted one."""


def context_report(cfg: AppConfig, **kwargs) -> dict:
    return _report(cfg, awareness=False, **kwargs)


def awareness_report(cfg: AppConfig, **kwargs) -> dict:
    return _report(cfg, awareness=True, **kwargs)


def _report(cfg: AppConfig, *, awareness: bool, **kwargs) -> dict:
    selector = _selector(kwargs, awareness=awareness)
    limit = _clamp_limit(kwargs.get("limit"), awareness)
    depth_limit = _clamp_depth(kwargs.get("depth")) if awareness else (1, False)
    repo_ids = _repo_ids(cfg, kwargs, selector)
    opened = _open_repos(cfg, repo_ids)
    try:
        return _assemble(
            cfg,
            opened,
            selector,
            limit=limit,
            depth_limit=depth_limit,
            awareness=awareness,
            requested_snapshot=kwargs.get("snapshot_id"),
        )
    finally:
        for item in opened:
            conn = item.get("conn")
            if conn is not None:
                conn.close()


def _selector(kwargs: dict, *, awareness: bool) -> dict:
    symbol_id = (kwargs.get("symbol_id") or "").strip()
    query = (kwargs.get("query") or "").strip()
    repo = (kwargs.get("repo") or "").strip()
    path = (kwargs.get("path") or "").strip()
    line = kwargs.get("line")
    groups = 0
    if symbol_id:
        groups += 1
    if query:
        groups += 1
    place = bool(repo or path or line is not None)
    if place:
        groups += 1
    if groups != 1:
        raise SelectorError(
            "pass exactly one selector: symbol_id, or repo+path+line, or query"
        )
    if place and not (repo and path and line is not None):
        raise SelectorError("repo, path, and line are required together")
    if line is not None and int(line) < 1:
        raise SelectorError("line must be >= 1")
    if kwargs.get("repos") and not query:
        raise SelectorError("repos filters a query selector")
    _ = awareness
    return {
        "symbol_id": symbol_id,
        "query": query,
        "repo": repo,
        "path": path,
        "line": int(line) if line is not None else None,
    }


def _clamp_limit(limit, awareness: bool) -> tuple[int, bool]:
    default = AWARENESS_DEFAULT_LIMIT if awareness else CONTEXT_DEFAULT_LIMIT
    hard = AWARENESS_HARD_LIMIT if awareness else CONTEXT_HARD_LIMIT
    if limit is None:
        return default, False
    value = int(limit)
    if value < 1:
        raise SelectorError("limit must be >= 1")
    if value > hard:
        return hard, True
    return value, False


def _clamp_depth(depth) -> tuple[int, bool]:
    if depth is None:
        return AWARENESS_DEFAULT_DEPTH, False
    value = int(depth)
    if value < 1:
        raise SelectorError("depth must be >= 1")
    if value > AWARENESS_HARD_DEPTH:
        return AWARENESS_HARD_DEPTH, True
    return value, False


def _repo_ids(cfg: AppConfig, kwargs: dict, selector: dict) -> list[str]:
    if selector["repo"]:
        cfg.get(selector["repo"])
        ids = [selector["repo"]]
        for rid in cfg.related_ids(selector["repo"]):
            if rid not in ids:
                ids.append(rid)
        return ids
    repos = kwargs.get("repos") or None
    scope = kwargs.get("scope") or "active+related"
    return resolve_search_repos(cfg, repo_ids=repos, scope=scope)


def _open_repos(cfg: AppConfig, repo_ids: list[str]) -> list[dict]:
    opened = []
    for repo_id in repo_ids:
        repo = cfg.get(repo_id)
        db = cfg.db_path(repo_id)
        item = {
            "repo_id": repo_id,
            "repo": repo,
            "config_dir": cfg.config_dir,
            "conn": None,
            "state": "unavailable",
            "warning": None,
        }
        if not db.exists():
            item["warning"] = f"missing index for {repo_id}"
            opened.append(item)
            continue
        try:
            conn = open_index(
                db,
                repo_id,
                checkout=repo.root,
                fingerprint=cfg.content_fingerprint(repo_id),
                create=False,
            )
        except IndexError_ as exc:
            item["warning"] = str(exc)
            opened.append(item)
            continue
        item["conn"] = conn
        item["state"] = structural_read_state(conn)
        item["meta"] = read_meta(conn)
        opened.append(item)
    return opened


def _assemble(cfg, opened, selector, *, limit, depth_limit, awareness, requested_snapshot) -> dict:
    limit_n, limit_clamped = limit
    depth_n, depth_clamped = depth_limit
    warnings = []
    snapshots = []
    readable = []
    for item in opened:
        if item["warning"]:
            warnings.append(item["warning"])
        snap = _snapshot(cfg, item, requested_snapshot)
        snapshots.append(snap)
        warnings.extend(snap["warnings"])
        if item["conn"] is not None and item["state"] in {"ready", "partial"}:
            readable.append(item)
    if not readable:
        state = "structural_unavailable"
        if any(item["state"] == "incompatible" for item in opened):
            state = "structural_incompatible"
        return _empty(
            tool="awareness" if awareness else "context",
            status=state,
            snapshots=snapshots,
            warnings=warnings,
            query=selector["query"],
        )

    found = _select(readable, selector)
    if found["status"] != "selected":
        body = _empty(
            tool="awareness" if awareness else "context",
            status=found["status"],
            snapshots=snapshots,
            warnings=warnings,
            query=selector["query"] or selector["symbol_id"],
        )
        body["selection"]["candidates"] = found.get("candidates") or []
        body["structural_coverage"] = {
            item["repo_id"]: coverage_summary(item["conn"]) for item in readable
        }
        return _fit(body)

    root = found["root"]
    relationships, unresolved, truncation = _walk(
        cfg,
        readable,
        root,
        depth_limit=depth_n,
        limit=limit_n,
    )
    if limit_clamped or depth_clamped:
        truncation["truncated"] = True
        truncation["reason"] = "hard_cap"
    body = {
        "tool": "awareness" if awareness else "context",
        "selection": found["selection"],
        "snapshots": snapshots,
        "relationships": relationships,
        "unresolved": unresolved,
        "truncation": truncation,
        "warnings": warnings,
        "fallback": None,
        "structural_coverage": {
            item["repo_id"]: coverage_summary(item["conn"]) for item in readable
        },
    }
    if awareness:
        body["depth_limit"] = depth_n
    return _fit(body)


def _select(readable, selector) -> dict:
    if selector["symbol_id"]:
        hits = []
        for item in readable:
            row = item["conn"].execute(
                "SELECT * FROM symbols WHERE symbol_id = ?",
                (selector["symbol_id"],),
            ).fetchone()
            if row is not None and _visible(item, row["path"]):
                hits.append((item, dict(row)))
        if len(hits) == 1:
            return {"status": "selected", "root": _symbol_root(hits[0]), "selection": _selection(hits[0])}
        if len(hits) > 1:
            return {
                "status": "ambiguous",
                "candidates": [_candidate(item, row) for item, row in hits[:ALTERNATIVE_CAP]],
            }
        return {"status": "stale_or_unknown", "candidates": []}
    if selector["line"] is not None:
        item = next(entry for entry in readable if entry["repo_id"] == selector["repo"])
        return _select_line(item, selector["path"], selector["line"])
    return _select_query(readable, selector["query"])


def _select_line(item, path: str, line: int) -> dict:
    if not _visible(item, path):
        return {"status": "not_found", "candidates": []}
    rows = item["conn"].execute(
        """
        SELECT s.*, o.start_line AS occ_start, o.end_line AS occ_end
        FROM occurrences o
        JOIN symbols s ON s.symbol_id = o.symbol_id
        WHERE o.path = ? AND o.start_line <= ? AND o.end_line >= ?
        """,
        (path, line, line),
    ).fetchall()
    if rows:
        best = min(rows, key=lambda row: (row["occ_end"] - row["occ_start"], row["occ_start"]))
        pair = (item, dict(best))
        return {"status": "selected", "root": _symbol_root(pair), "selection": _selection(pair)}
    site = item["conn"].execute(
        """
        SELECT * FROM sites
        WHERE path = ? AND start_line <= ? AND end_line >= ?
        ORDER BY start_line
        LIMIT 1
        """,
        (path, line, line),
    ).fetchone()
    if site is not None and site["enclosing_symbol_id"]:
        row = item["conn"].execute(
            "SELECT * FROM symbols WHERE symbol_id = ?",
            (site["enclosing_symbol_id"],),
        ).fetchone()
        if row is not None:
            pair = (item, dict(row))
            return {"status": "selected", "root": _symbol_root(pair), "selection": _selection(pair)}
    return {"status": "not_found", "candidates": []}


def _select_query(readable, query: str) -> dict:
    method, path = _http_query(query)
    hits = []
    if method:
        for item in readable:
            rows = item["conn"].execute(
                """
                SELECT * FROM sites
                WHERE http_method = ? AND http_path = ?
                LIMIT ?
                """,
                (method, path, ALTERNATIVE_CAP + 1),
            ).fetchall()
            for row in rows:
                if _visible(item, row["path"]):
                    hits.append((item, dict(row), "site"))
    else:
        for item in readable:
            rows = item["conn"].execute(
                """
                SELECT * FROM symbols
                WHERE qualified_name = ? OR name = ?
                LIMIT ?
                """,
                (query, query, ALTERNATIVE_CAP + 1),
            ).fetchall()
            exact = [row for row in rows if row["qualified_name"] == query]
            chosen = exact or list(rows)
            for row in chosen:
                if _visible(item, row["path"]):
                    hits.append((item, dict(row), "symbol"))
    if len(hits) == 1 and hits[0][2] == "symbol":
        pair = (hits[0][0], hits[0][1])
        return {"status": "selected", "root": _symbol_root(pair), "selection": _selection(pair)}
    if len(hits) == 1 and hits[0][2] == "site":
        return {"status": "selected", "root": _site_root(hits[0][0], hits[0][1]), "selection": _site_selection(hits[0][0], hits[0][1])}
    if len(hits) > 1:
        candidates = []
        for item, row, kind in hits[:ALTERNATIVE_CAP]:
            if kind == "symbol":
                candidates.append(_candidate(item, row))
            else:
                candidates.append(
                    {
                        "repo_id": item["repo_id"],
                        "path": row["path"],
                        "start_line": row["start_line"],
                        "kind": row["site_kind"],
                        "name": row.get("http_method") or row["site_kind"],
                    }
                )
        return {"status": "ambiguous", "candidates": candidates}
    return {"status": "not_found", "candidates": []}


def _walk(cfg, readable, root, *, depth_limit: int, limit: int) -> tuple[list, dict, dict]:
    produced = []
    seen = set()
    unresolved_shown = []
    unresolved_extra = 0
    intermediate = 0
    stopped_early = False
    omitted_ambiguity = 0
    queue = [(root, 0, "resolved", [])]
    by_repo = {item["repo_id"]: item for item in readable}
    while queue and len(produced) < limit and intermediate < INTERMEDIATE_CAP:
        node, depth, path_status, via = queue.pop(0)
        intermediate += 1
        key = (node["repo_id"], node["kind"], node["id"])
        if key in seen:
            continue
        seen.add(key)
        if depth >= depth_limit:
            continue
        item = by_repo.get(node["repo_id"])
        if item is None or item["conn"] is None:
            continue
        edges = _edges_from(cfg, readable, item, node)
        if len(edges) > HOP_CANDIDATE_CAP:
            edges = edges[:HOP_CANDIDATE_CAP]
            stopped_early = True
        for edge in edges:
            edge_status = edge["status"]
            next_status = weaker(path_status, edge_status)
            edge["path_status"] = next_status
            edge["depth"] = depth + 1
            edge["via"] = via + [{"id": edge["id"], "status": edge_status, "kind": edge["kind"]}]
            if edge_status == "unresolved":
                if len(unresolved_shown) < 20:
                    unresolved_shown.append(edge)
                else:
                    unresolved_extra += 1
                continue
            if len(produced) >= limit:
                stopped_early = True
                break
            produced.append(edge)
            if edge_status == "ambiguous" or edge.get("expansion") == "stopped_ambiguity":
                omitted_ambiguity += len(edge.get("alternatives") or [])
                continue
            if edge_status in {"resolved", "candidate"} and edge.get("target_symbol_id"):
                queue.append(
                    (
                        {
                            "repo_id": edge["target_repo_id"],
                            "kind": "symbol",
                            "id": edge["target_symbol_id"],
                        },
                        depth + 1,
                        next_status,
                        edge["via"],
                    )
                )
    produced.sort(
        key=lambda edge: (
            {"resolved": 0, "candidate": 1, "ambiguous": 2, "unresolved": 3}[edge["status"]],
            edge["depth"],
            edge.get("target_repo_id") or "",
            edge["kind"],
            edge["id"],
        )
    )
    truncation = {
        "truncated": stopped_early or intermediate >= INTERMEDIATE_CAP,
        "reason": "budget" if stopped_early else None,
        "omitted_relationships": None if stopped_early else 0,
        "omitted_known": not stopped_early,
        "expansion_stopped_ambiguity": omitted_ambiguity,
    }
    unresolved = {
        "shown": len(unresolved_shown),
        "omitted": unresolved_extra if not stopped_early else None,
        "omitted_known": not stopped_early,
        "sites": unresolved_shown,
    }
    return produced, unresolved, truncation


def _edges_from(cfg, readable, item, node) -> list[dict]:
    conn = item["conn"]
    edges = []
    if node["kind"] == "symbol":
        rows = conn.execute(
            """
            SELECT * FROM relationships
            WHERE source_symbol_id = ? OR target_symbol_id = ?
            LIMIT ?
            """,
            (node["id"], node["id"], HOP_CANDIDATE_CAP + 1),
        ).fetchall()
        edges.extend(_group_local(item, rows))
        sites = conn.execute(
            "SELECT * FROM sites WHERE enclosing_symbol_id = ?",
            (node["id"],),
        ).fetchall()
    else:
        site = conn.execute("SELECT * FROM sites WHERE site_id = ?", (node["id"],)).fetchone()
        sites = [site] if site is not None else []
    for site in sites:
        if site is None or not _visible(item, site["path"]):
            continue
        cross = _cross(cfg, readable, item, site)
        if site["site_kind"] == "http_client" and not cross and (
            site["resolution"] == "unresolved" or site["http_suffix"] or site["http_path"]
        ):
            edges.append(_unmatched_http(item, site))
        elif site["resolution"] == "unresolved" and site["site_kind"] in {
            "call",
            "http_route",
            "process_spawn",
            "net_connect",
            "net_listen",
            "rpc_send",
            "rpc_dispatch",
        }:
            edges.append(_terminal_site(item, site))
        edges.extend(cross)
    return edges


def _group_local(item, rows) -> list[dict]:
    groups: dict[tuple, list] = defaultdict(list)
    singles = []
    for row in rows:
        if row["status"] == "ambiguous" and row["source_site_id"] is not None:
            groups[(row["kind"], row["source_site_id"], row["rule_id"])].append(row)
        else:
            singles.append(_local_edge(item, row, alternatives=[]))
    out = []
    for grouped in groups.values():
        primary = grouped[0]
        alternatives = []
        for row in grouped[:ALTERNATIVE_CAP]:
            alternatives.append(
                {
                    "repo_id": item["repo_id"],
                    "symbol_id": row["target_symbol_id"],
                    "name": row["target_key"],
                }
            )
        edge = _local_edge(item, primary, alternatives)
        edge["expansion"] = "stopped_ambiguity"
        edge["alternatives_truncated"] = len(grouped) > ALTERNATIVE_CAP
        out.append(edge)
    out.extend(singles)
    return out


def _local_edge(item, row, alternatives: list) -> dict:
    target_repo = item["repo_id"]
    return {
        "id": f"{item['repo_id']}:rel:{row['relationship_id']}",
        "kind": row["kind"],
        "status": row["status"],
        "rule_id": row["rule_id"],
        "reason": row["reason"],
        "source": {
            "repo_id": item["repo_id"],
            "symbol_id": row["source_symbol_id"],
        },
        "target": {
            "repo_id": target_repo,
            "symbol_id": row["target_symbol_id"],
            "name": row["target_key"],
        },
        "target_symbol_id": row["target_symbol_id"],
        "target_repo_id": target_repo if row["target_symbol_id"] else None,
        "alternatives": alternatives,
        "evidence": _load_list(row["evidence_json"]),
        "evidence_truncated": bool(row["evidence_truncated"]),
        "expansion": None,
    }


def _unmatched_http(item, site) -> dict:
    suffix = site["http_suffix"]
    path = site["http_path"]
    if suffix:
        label = "suffix " + suffix
        reason = (
            "suffix candidate; an unknown base path could invalidate this match; "
            "no indexed counterpart"
        )
    elif path:
        label = "path " + path
        reason = "path match is not a deployment binding; no indexed counterpart"
    else:
        label = "dynamic url"
        reason = "dynamic url; full path is not known"
    if site["http_boundary"] == "conditional_slash":
        reason += "; empty normalizer input does not add a slash"
    return {
        "id": f"{item['repo_id']}:site:{site['site_id']}",
        "kind": site["site_kind"],
        "status": "unresolved",
        "rule_id": site["rule_id"],
        "reason": reason,
        "source": {"repo_id": item["repo_id"], "path": site["path"], "start_line": site["start_line"]},
        "target": {"name": label},
        "target_symbol_id": None,
        "target_repo_id": None,
        "alternatives": [],
        "evidence": [label],
        "evidence_truncated": False,
        "expansion": None,
    }


def _terminal_site(item, site) -> dict:
    return {
        "id": f"{item['repo_id']}:site:{site['site_id']}",
        "kind": site["site_kind"],
        "status": "unresolved",
        "rule_id": site["rule_id"],
        "reason": "unresolved site",
        "source": {"repo_id": item["repo_id"], "path": site["path"], "start_line": site["start_line"]},
        "target": {"expression": site["expression_text"]},
        "target_symbol_id": None,
        "target_repo_id": None,
        "alternatives": [],
        "evidence": [site["expression_text"]],
        "evidence_truncated": bool(site["evidence_truncated"]),
        "expansion": None,
    }


def _cross(cfg, readable, item, site) -> list[dict]:
    spec = _match_spec(site)
    if spec is None:
        return []
    hits = []
    for other in readable:
        if other["conn"] is None:
            continue
        rows = other["conn"].execute(spec["sql"], spec["args"]).fetchall()
        for row in rows:
            if other["repo_id"] == item["repo_id"] and row["site_id"] == site["site_id"]:
                continue
            if row["site_kind"] == site["site_kind"]:
                continue
            if not _visible(other, row["path"]):
                continue
            hits.append((other, row))
            if len(hits) > ALTERNATIVE_CAP:
                break
    if not hits:
        return []
    status = "ambiguous" if len(hits) > 1 or _wildcard_pair(site, hits) else "candidate"
    shown = hits[:ALTERNATIVE_CAP]
    http = spec["kind"] == "http_request_to_handler"
    alternatives = [
        {
            "repo_id": other["repo_id"],
            "path": row["path"],
            "start_line": row["start_line"],
            "symbol_id": (row["handler_symbol_id"] or row["enclosing_symbol_id"]) if http else row["enclosing_symbol_id"],
            "name": _site_label(row) if http else row["expression_text"],
        }
        for other, row in shown
    ]
    target_other, target_row = shown[0]
    reason = _http_reason(site, target_row) if http else spec["reason"]
    if status != "candidate":
        reason = reason + "; several counterparts"
    symbol = None
    expansion = "stopped_ambiguity" if status == "ambiguous" else None
    truncated = len(hits) > ALTERNATIVE_CAP
    if status == "candidate":
        symbol = (target_row["handler_symbol_id"] or target_row["enclosing_symbol_id"]) if http else target_row["enclosing_symbol_id"]
    if http and status == "candidate":
        handlers, handler_cut = _handler_alternatives(target_row)
        if handlers:
            alternatives = [
                {**alt, "repo_id": target_other["repo_id"]} for alt in handlers
            ]
            symbol = None
            expansion = "stopped_ambiguity"
            truncated = truncated or handler_cut
            reason = reason + "; handler binding is ambiguous"
            route_target = {
                "repo_id": target_other["repo_id"],
                "path": target_row["path"],
                "start_line": target_row["start_line"],
                "symbol_id": None,
                "name": _site_label(target_row),
            }
        else:
            route_target = alternatives[0]
    else:
        route_target = alternatives[0]
    edge = {
        "id": f"{item['repo_id']}:x:{site['site_id']}:{target_other['repo_id']}:{target_row['site_id']}",
        "kind": spec["kind"],
        "status": status,
        "rule_id": site["rule_id"],
        "reason": reason,
        "source": {
            "repo_id": item["repo_id"],
            "path": site["path"],
            "start_line": site["start_line"],
            "symbol_id": site["enclosing_symbol_id"],
        },
        "target": route_target,
        "target_symbol_id": symbol,
        "target_repo_id": target_other["repo_id"] if status == "candidate" and symbol else None,
        "alternatives": alternatives if status == "ambiguous" or expansion == "stopped_ambiguity" else [],
        "evidence": _http_evidence(site, target_row) if http else [
            f"{item['repo_id']} {site['path']}:{site['start_line']}",
            f"{target_other['repo_id']} {target_row['path']}:{target_row['start_line']}",
        ],
        "evidence_truncated": bool(site["evidence_truncated"] or target_row["evidence_truncated"]),
        "expansion": expansion,
        "alternatives_truncated": truncated,
    }
    _ = cfg
    return [edge]


def _match_spec(site) -> dict | None:
    http = _http_match(site)
    if http is not None:
        return http
    if site["exec_id"]:
        return {
            "sql": "SELECT * FROM sites WHERE exec_id = ? LIMIT ?",
            "args": (site["exec_id"], ALTERNATIVE_CAP + 1),
            "kind": "process_invocation",
            "reason": "executable basename match is not a unique producer binding",
        }
    if site["net_port"] is not None and site["net_role"]:
        opposite = "connect" if site["net_role"] == "listen" else "listen"
        if site["net_host"]:
            return {
                "sql": """
                    SELECT * FROM sites
                    WHERE net_port = ? AND net_role = ? AND (net_host = ? OR net_wildcard = 1)
                    LIMIT ?
                """,
                "args": (site["net_port"], opposite, site["net_host"], ALTERNATIVE_CAP + 1),
                "kind": "net_endpoint",
                "reason": "literal endpoint match is not a confirmed deployment",
            }
        return {
            "sql": "SELECT * FROM sites WHERE net_port = ? AND net_role = ? LIMIT ?",
            "args": (site["net_port"], opposite, ALTERNATIVE_CAP + 1),
            "kind": "net_endpoint",
            "reason": "port match without a host is ambiguous",
        }
    if site["rpc_command"]:
        return {
            "sql": "SELECT * FROM sites WHERE rpc_command = ? LIMIT ?",
            "args": (site["rpc_command"], ALTERNATIVE_CAP + 1),
            "kind": "rpc_command",
            "reason": "command string match is not a language-level call",
        }
    return None


def _method_clause() -> str:
    return "(http_method IS NULL OR ? IS NULL OR http_method = ?)"


def _http_match(site) -> dict | None:
    kind = site["site_kind"]
    if kind not in {"http_client", "http_route"}:
        return None
    opposite = "http_route" if kind == "http_client" else "http_client"
    method = site["http_method"]
    limit = ALTERNATIVE_CAP + 1
    if site["http_path"] and kind == "http_client":
        return {
            "sql": f"""
                SELECT * FROM sites
                WHERE site_kind = ? AND http_path = ? AND {_method_clause()}
                LIMIT ?
            """,
            "args": (opposite, site["http_path"], method, method, limit),
            "kind": "http_request_to_handler",
            "reason": "path match is not a deployment binding",
        }
    if site["http_path"] and kind == "http_route":
        suffixes = _literal_suffixes(site["http_path"])
        marks = ", ".join("?" for _ in suffixes) or "?"
        segment = site["http_path"].rsplit("/", 1)[-1]
        return {
            "sql": f"""
                SELECT * FROM sites
                WHERE site_kind = ? AND (
                  http_path = ?
                  OR (http_boundary = 'literal_slash' AND http_suffix IN ({marks}))
                  OR (http_boundary = 'conditional_slash' AND http_suffix = ?)
                ) AND {_method_clause()}
                LIMIT ?
            """,
            "args": (opposite, site["http_path"], *suffixes, segment, method, method, limit),
            "kind": "http_request_to_handler",
            "reason": "suffix candidate; an unknown base path could invalidate this match",
        }
    suffix = site["http_suffix"]
    boundary = site["http_boundary"]
    if not suffix:
        return None
    lookup = suffix if boundary == "literal_slash" and suffix.startswith("/") else None
    if boundary == "conditional_slash" and "/" not in suffix:
        lookup = "/" + suffix
    if not lookup:
        return None
    rev = lookup[::-1]
    return {
        "sql": f"""
            SELECT * FROM sites
            WHERE site_kind = ? AND http_rev >= ? AND http_rev < ? AND {_method_clause()}
            LIMIT ?
        """,
        "args": (opposite, rev, rev + "\uffff", method, method, limit),
        "kind": "http_request_to_handler",
        "reason": "suffix candidate; an unknown base path could invalidate this match",
    }


def _literal_suffixes(path: str) -> list[str]:
    if not path.startswith("/"):
        return [path]
    found = [path]
    for index, char in enumerate(path):
        if index and char == "/":
            found.append(path[index:])
            if len(found) >= 8:
                break
    return found


def _handler_alternatives(row) -> tuple[list[dict], bool]:
    try:
        payload = json.loads(row["payload_json"] or "{}")
    except json.JSONDecodeError:
        return [], False
    if payload.get("handler_binding") != "ambiguous":
        return [], False
    alts = []
    for item in payload.get("handler_alternatives") or []:
        if not isinstance(item, dict):
            continue
        alts.append(
            {
                "path": item.get("path") or "",
                "start_line": row["start_line"],
                "symbol_id": item.get("symbol_id"),
                "name": item.get("name") or item.get("role") or "handler",
            }
        )
    return alts[:ALTERNATIVE_CAP], bool(payload.get("handler_alternatives_truncated"))


def _site_label(row) -> str:
    return row["http_path"] or row["http_suffix"] or row["handler_key"] or row["site_kind"]


def _http_reason(site, row) -> str:
    full = (
        site["http_path"]
        and row["http_path"]
        and site["http_path"] == row["http_path"]
        and not site["http_suffix"]
        and not row["http_suffix"]
    )
    parts = [
        "path match is not a deployment binding"
        if full
        else "suffix candidate; an unknown base path could invalidate this match"
    ]
    if site["http_boundary"] == "conditional_slash" or row["http_boundary"] == "conditional_slash":
        parts.append("empty normalizer input does not add a slash")
    if not site["http_method"] or not row["http_method"]:
        parts.append("absent method is not copied from the other side")
    return "; ".join(parts)


def _http_evidence(site, row) -> list[str]:
    items = []
    if site["http_suffix"]:
        items.append("suffix " + site["http_suffix"])
    elif site["http_path"]:
        items.append("path " + site["http_path"])
    if row["http_path"]:
        items.append("route " + row["http_path"])
    elif row["http_suffix"]:
        items.append("suffix " + row["http_suffix"])
    handler = row["handler_key"] or site["handler_key"]
    if handler:
        items.append("handler " + handler)
    return items[:4]


def _wildcard_pair(site, hits) -> bool:
    if site["net_wildcard"]:
        return True
    return any(row["net_wildcard"] for _, row in hits)


def _symbol_root(pair) -> dict:
    item, row = pair
    return {"repo_id": item["repo_id"], "kind": "symbol", "id": row["symbol_id"]}


def _site_root(item, row) -> dict:
    if row["enclosing_symbol_id"]:
        return {"repo_id": item["repo_id"], "kind": "symbol", "id": row["enclosing_symbol_id"]}
    return {"repo_id": item["repo_id"], "kind": "site", "id": row["site_id"]}


def _selection(pair) -> dict:
    item, row = pair
    locations = []
    for occ in item["conn"].execute(
        "SELECT * FROM occurrences WHERE symbol_id = ? ORDER BY start_line, role",
        (row["symbol_id"],),
    ):
        if _visible(item, occ["path"]):
            locations.append(
                {
                    "repo_id": item["repo_id"],
                    "path": occ["path"],
                    "role": occ["role"],
                    "start_line": occ["start_line"],
                    "start_col": occ["start_col"],
                    "end_line": occ["end_line"],
                    "end_col": occ["end_col"],
                }
            )
    snap = _meta_get(item["conn"], META_SNAPSHOT)
    return {
        "status": "selected",
        "symbol_id": row["symbol_id"],
        "repo_id": item["repo_id"],
        "snapshot_id": snap,
        "language": row["language"],
        "kind": row["kind"],
        "name": row["name"],
        "qualified_name": row["qualified_name"],
        "signature": row["signature"],
        "locations": locations,
        "candidates": [],
    }


def _site_selection(item, row) -> dict:
    return {
        "status": "selected",
        "symbol_id": row["enclosing_symbol_id"],
        "repo_id": item["repo_id"],
        "snapshot_id": _meta_get(item["conn"], META_SNAPSHOT),
        "language": "",
        "kind": row["site_kind"],
        "name": row["expression_text"],
        "qualified_name": row["expression_text"],
        "signature": "",
        "locations": [
            {
                "repo_id": item["repo_id"],
                "path": row["path"],
                "role": row["site_kind"],
                "start_line": row["start_line"],
                "start_col": row["start_col"],
                "end_line": row["end_line"],
                "end_col": row["end_col"],
            }
        ],
        "candidates": [],
    }


def _candidate(item, row) -> dict:
    return {
        "symbol_id": row["symbol_id"],
        "repo_id": item["repo_id"],
        "qualified_name": row["qualified_name"],
        "signature": row["signature"],
        "path": row["path"],
        "start_line": row["start_line"] if "start_line" in row.keys() else None,
    }


def _snapshot(cfg, item, requested) -> dict:
    meta = item.get("meta")
    conn = item.get("conn")
    indexed = meta.git_revision if meta else None
    indexed_at = meta.indexed_at if meta else None
    dirty = _meta_get(conn, META_INDEXED_DIRTY) if conn else None
    current = git_head(item["repo"].root) if item.get("repo") else None
    warnings = []
    freshness = "unknown"
    if item["state"] == "incompatible":
        warnings.append("structural fingerprint or schema is incompatible; run py-indexer index")
    elif item["state"] == "unavailable":
        warnings.append("structural index is unavailable; run py-indexer index")
    if indexed and current and indexed != current:
        freshness = "commit_moved"
        warnings.append(
            "current commit differs from the indexed commit; "
            f"run py-indexer index --repo {item['repo_id']}"
        )
    elif dirty == "1":
        freshness = "dirty_at_index"
        warnings.append(
            "index includes uncommitted content and does not exactly represent "
            f"{indexed or 'its base commit'}"
        )
    elif current and indexed and current == indexed:
        freshness = "current"
    snap_id = _meta_get(conn, META_SNAPSHOT) if conn else None
    if requested and snap_id and requested != snap_id:
        warnings.append("requested snapshot_id does not match the current snapshot")
    _ = cfg
    return {
        "repo_id": item["repo_id"],
        "snapshot_id": snap_id,
        "indexed_commit": indexed,
        "indexed_at": indexed_at,
        "indexed_dirty": dirty == "1",
        "current_commit": current,
        "freshness": freshness,
        "structural": item["state"],
        "warnings": warnings,
    }


def _visible(item, path: str) -> bool:
    if not path:
        return False
    try:
        safe_join(item["repo"].root, path)
    except ValueError:
        return False
    rules = load_exclude_rules(
        config_dir=item.get("config_dir"),
        repo_root=item["repo"].root,
        config_exclude=item["repo"].exclude,
    )
    hidden = git_ignored_paths(item["repo"].root, [path])
    return indexed_path_visible(
        path,
        rules=rules,
        include=item["repo"].include,
        git_ignored=hidden,
    )


def _http_query(query: str) -> tuple[str | None, str | None]:
    parts = query.split(None, 1)
    if len(parts) == 2 and parts[0].upper() in _HTTP_QUERY and parts[1].startswith("/"):
        return parts[0].upper(), parts[1].split("?", 1)[0].rstrip("/") or "/"
    return None, None


def _empty(*, tool, status, snapshots, warnings, query) -> dict:
    hint = "py-indexer index --all" if "structural" in status else "search_code"
    return {
        "tool": tool,
        "selection": {
            "status": status,
            "symbol_id": None,
            "locations": [],
            "candidates": [],
        },
        "snapshots": snapshots,
        "relationships": [],
        "unresolved": {"shown": 0, "omitted": 0, "omitted_known": True, "sites": []},
        "truncation": {
            "truncated": False,
            "reason": None,
            "omitted_relationships": 0,
            "omitted_known": True,
        },
        "warnings": warnings,
        "fallback": {"tool": hint, "query": query},
        "structural_coverage": {},
    }


def _fit(body: dict) -> dict:
    encoded = json.dumps(body, ensure_ascii=True)
    if len(encoded.encode("utf-8")) <= OUTPUT_BYTE_CAP:
        return body
    while body["relationships"] and len(json.dumps(body, ensure_ascii=True).encode("utf-8")) > OUTPUT_BYTE_CAP:
        body["relationships"].pop()
        body["truncation"]["truncated"] = True
        body["truncation"]["reason"] = "output_bytes"
        body["truncation"]["omitted_known"] = False
        body["truncation"]["omitted_relationships"] = None
    return body


def _load_list(raw: str) -> list:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def _touch_worktree(root, paths) -> list[str]:
    """Compare a bounded path set. Used by freshness when callers pass paths."""
    return worktree_dirty_paths(root, paths)
