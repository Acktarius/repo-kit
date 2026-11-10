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
from py_indexer.relate import _STATUS_RANK, weaker
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
    if selector["line"] is not None:
        own = next((item for item in opened if item["repo_id"] == selector["repo"]), None)
        if own is None or own not in readable:
            state = own["state"] if own is not None else "unavailable"
            status = "structural_incompatible" if state == "incompatible" else "structural_unavailable"
            return _fit(
                _empty(
                    tool="awareness" if awareness else "context",
                    status=status,
                    snapshots=snapshots,
                    warnings=warnings,
                    query=selector["path"],
                )
            )
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
        truncation["completeness"] = "budget"
        truncation["reason"] = "hard_cap"
        truncation["omitted_known"] = False
        truncation["omitted_relationships"] = None
        unresolved["omitted"] = None
        unresolved["omitted_known"] = False
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
    _apply_freshness(opened, body)
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
    expanded: dict[tuple, int] = {}
    emitted: dict[str, dict] = {}
    emitted_sites: set = set()
    unresolved_shown = []
    unresolved_extra = 0
    intermediate = 0
    stopped_early = False
    depth_boundary = False
    omitted_ambiguity = 0
    unresolved_uncounted = False
    queue = [(root, 0, "resolved", [])]
    by_repo = {item["repo_id"]: item for item in readable}
    view = _Visibility()
    while queue and len(produced) < limit and intermediate < INTERMEDIATE_CAP:
        node, depth, path_status, via = queue.pop(0)
        intermediate += 1
        key = (node["repo_id"], node["kind"], node["id"])
        rank = _STATUS_RANK[path_status]
        previous = expanded.get(key)
        if previous is not None and rank >= previous:
            continue
        if depth >= depth_limit:
            depth_boundary = True
            continue
        expanded[key] = rank
        item = by_repo.get(node["repo_id"])
        if item is None or item["conn"] is None:
            continue
        edges, overflow = _edges_from(cfg, readable, item, node, view)
        if overflow:
            stopped_early = True
        for edge in edges:
            if not _keep_edge(view, by_repo, edge):
                continue
            edge_status = edge["status"]
            next_status = weaker(path_status, edge_status)
            site_id = edge.get("_source_site_id")
            terminal = bool(edge.get("_terminal"))
            direction, neighbor = _traversal(node, edge)
            prior = emitted.get(edge["id"])
            if prior is not None:
                if (
                    prior.get("_path_node") == key
                    and _STATUS_RANK[next_status] < _STATUS_RANK[prior["path_status"]]
                ):
                    prior["path_status"] = next_status
                    prior["via"] = via + [{"id": edge["id"], "status": edge_status, "kind": edge["kind"]}]
                    if neighbor and edge_status in {"resolved", "candidate"} and not terminal:
                        queue.append((neighbor, depth + 1, next_status, prior["via"]))
                continue
            edge["traversal"] = direction
            edge["traversal_neighbor"] = neighbor
            edge["path_status"] = next_status
            edge["depth"] = depth + 1
            edge["via"] = via + [{"id": edge["id"], "status": edge_status, "kind": edge["kind"]}]
            edge["_path_node"] = key
            if terminal or edge_status == "unresolved":
                if terminal and site_id is not None and site_id in emitted_sites:
                    continue
                edge.pop("_source_site_id", None)
                edge.pop("_terminal", None)
                if len(unresolved_shown) < 20:
                    unresolved_shown.append(edge)
                    emitted[edge["id"]] = edge
                    if site_id is not None and not terminal:
                        emitted_sites.add(site_id)
                else:
                    unresolved_extra += 1
                    unresolved_uncounted = True
                continue
            if len(produced) >= limit:
                stopped_early = True
                continue
            edge.pop("_source_site_id", None)
            edge.pop("_terminal", None)
            produced.append(edge)
            emitted[edge["id"]] = edge
            if site_id is not None:
                emitted_sites.add(site_id)
            if edge_status == "ambiguous" or edge.get("expansion") == "stopped_ambiguity":
                omitted_ambiguity += len(edge.get("alternatives") or [])
                continue
            if neighbor and edge_status in {"resolved", "candidate"}:
                queue.append((neighbor, depth + 1, next_status, edge["via"]))
    for edge in produced + unresolved_shown:
        edge.pop("_path_node", None)
        edge.pop("_source_site_id", None)
        edge.pop("_terminal", None)
    produced.sort(
        key=lambda edge: (
            {"resolved": 0, "candidate": 1, "ambiguous": 2, "unresolved": 3}[edge["status"]],
            edge["depth"],
            edge.get("target_repo_id") or "",
            edge["kind"],
            edge["id"],
        )
    )
    budget = stopped_early or intermediate >= INTERMEDIATE_CAP or (len(produced) >= limit and bool(queue))
    if budget:
        completeness = "budget"
        truncated = True
        reason = "budget"
        omitted_known = False
        omitted = None
        unresolved_omitted = None
    elif depth_boundary:
        completeness = "depth"
        truncated = False
        reason = None
        omitted_known = False
        omitted = None
        unresolved_omitted = None
    else:
        completeness = "complete"
        truncated = False
        reason = None
        omitted_known = True
        omitted = 0
        unresolved_omitted = unresolved_extra
    truncation = {
        "truncated": truncated,
        "completeness": completeness,
        "reason": reason,
        "depth_limit": depth_limit,
        "omitted_relationships": omitted,
        "omitted_known": omitted_known,
        "expansion_stopped_ambiguity": omitted_ambiguity,
    }
    unresolved = {
        "shown": len(unresolved_shown),
        "omitted": unresolved_omitted,
        "omitted_known": unresolved_omitted is not None,
        "sites": unresolved_shown,
    }
    return produced, unresolved, truncation


def _traversal(node, edge) -> tuple[str, dict | None]:
    """Return incoming/outgoing and the neighbor to queue.

    The relationship's source and target fields stay in semantic order.
    """
    source_id = (edge.get("source") or {}).get("symbol_id")
    target_id = edge.get("target_symbol_id")
    if (
        node["kind"] == "symbol"
        and target_id == node["id"]
        and source_id
        and source_id != node["id"]
    ):
        return "incoming", {
            "repo_id": edge["source"].get("repo_id") or node["repo_id"],
            "kind": "symbol",
            "id": source_id,
        }
    if target_id and edge.get("target_repo_id"):
        return "outgoing", {
            "repo_id": edge["target_repo_id"],
            "kind": "symbol",
            "id": target_id,
        }
    return "outgoing", None


def _edges_from(cfg, readable, item, node, view) -> tuple[list[dict], bool]:
    conn = item["conn"]
    edges = []
    overflow = False
    by_repo = {entry["repo_id"]: entry for entry in readable}
    if node["kind"] == "symbol":
        rows = conn.execute(
            """
            SELECT * FROM relationships
            WHERE source_symbol_id = ? OR target_symbol_id = ?
            ORDER BY relationship_id
            LIMIT ?
            """,
            (node["id"], node["id"], HOP_CANDIDATE_CAP + 1),
        ).fetchall()
        if len(rows) > HOP_CANDIDATE_CAP:
            overflow = True
            rows = rows[:HOP_CANDIDATE_CAP]
        local = _group_local(item, rows)
        for edge in local:
            if _keep_edge(view, by_repo, edge):
                edges.append(edge)
        sites = conn.execute(
            """
            SELECT * FROM sites
            WHERE enclosing_symbol_id = ?
            ORDER BY site_id
            LIMIT ?
            """,
            (node["id"], HOP_CANDIDATE_CAP + 1),
        ).fetchall()
        if len(sites) > HOP_CANDIDATE_CAP:
            overflow = True
            sites = sites[:HOP_CANDIDATE_CAP]
    else:
        site = conn.execute("SELECT * FROM sites WHERE site_id = ?", (node["id"],)).fetchone()
        sites = [site] if site is not None else []
    for site in sites:
        if site is None or not view.allow(item, site["path"]):
            continue
        cross = _cross(cfg, readable, item, site, view)
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
    return edges, overflow


def _group_local(item, rows) -> list[dict]:
    groups: dict[tuple, list] = defaultdict(list)
    singles = []
    symbol_ids = []
    site_ids = []
    for row in rows:
        if row["source_symbol_id"]:
            symbol_ids.append(row["source_symbol_id"])
        if row["target_symbol_id"]:
            symbol_ids.append(row["target_symbol_id"])
        if row["source_site_id"] is not None:
            site_ids.append(row["source_site_id"])
    locations = _symbol_locations(item, symbol_ids)
    sites = _site_locations(item, site_ids)
    for row in rows:
        if row["status"] == "ambiguous" and row["source_site_id"] is not None:
            groups[(row["kind"], row["source_site_id"], row["rule_id"])].append(row)
        else:
            singles.append(_local_edge(item, row, [], locations, sites))
    out = []
    for grouped in groups.values():
        primary = grouped[0]
        alternatives = []
        ordered = sorted(grouped, key=lambda row: (row["target_key"] or "", row["target_symbol_id"] or "", row["relationship_id"]))
        for row in ordered[:ALTERNATIVE_CAP]:
            place = locations.get(row["target_symbol_id"]) or {}
            alternatives.append(
                {
                    "repo_id": item["repo_id"],
                    "symbol_id": row["target_symbol_id"],
                    "name": row["target_key"],
                    "path": place.get("path"),
                    "start_line": place.get("start_line"),
                }
            )
        edge = _local_edge(item, primary, alternatives, locations, sites)
        edge["expansion"] = "stopped_ambiguity"
        edge["alternatives_truncated"] = len(ordered) > ALTERNATIVE_CAP
        out.append(edge)
    out.extend(singles)
    return out


def _local_edge(item, row, alternatives: list, locations: dict, sites: dict) -> dict:
    target_repo = item["repo_id"]
    source_place = locations.get(row["source_symbol_id"]) or {}
    site_place = sites.get(row["source_site_id"]) or {}
    target_place = locations.get(row["target_symbol_id"]) or {}
    source = {
        "repo_id": item["repo_id"],
        "symbol_id": row["source_symbol_id"],
        "path": site_place.get("path") or source_place.get("path"),
        "start_line": site_place.get("start_line") or source_place.get("start_line"),
    }
    target = {
        "repo_id": target_repo,
        "symbol_id": row["target_symbol_id"],
        "name": row["target_key"],
        "path": target_place.get("path"),
        "start_line": target_place.get("start_line"),
    }
    return {
        "id": f"{item['repo_id']}:rel:{row['relationship_id']}",
        "kind": row["kind"],
        "status": row["status"],
        "rule_id": row["rule_id"],
        "reason": row["reason"],
        "source": source,
        "target": target,
        "target_symbol_id": row["target_symbol_id"],
        "target_repo_id": target_repo if row["target_symbol_id"] else None,
        "alternatives": alternatives,
        "_source_site_id": row["source_site_id"],
        "evidence": _load_list(row["evidence_json"]),
        "evidence_truncated": bool(row["evidence_truncated"]),
        "expansion": None,
    }


def _symbol_locations(item, symbol_ids: list) -> dict:
    ids = [symbol_id for symbol_id in dict.fromkeys(symbol_ids) if symbol_id]
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    found = {}
    rank = {"definition": 0, "decl_and_def": 1, "declaration": 2}
    rows = item["conn"].execute(
        f"""
        SELECT symbol_id, path, start_line, role
        FROM occurrences
        WHERE symbol_id IN ({marks})
        ORDER BY start_line, symbol_id
        """,
        ids,
    ).fetchall()
    best = {}
    for row in rows:
        score = rank.get(row["role"], 9)
        current = best.get(row["symbol_id"])
        if current is None or score < current[0]:
            best[row["symbol_id"]] = (score, row["path"], row["start_line"])
    for symbol_id, (_score, path, line) in best.items():
        found[symbol_id] = {"path": path, "start_line": line}
    missing = [symbol_id for symbol_id in ids if symbol_id not in found]
    if missing:
        marks = ",".join("?" for _ in missing)
        for row in item["conn"].execute(
            f"SELECT symbol_id, path FROM symbols WHERE symbol_id IN ({marks})",
            missing,
        ):
            found[row["symbol_id"]] = {"path": row["path"], "start_line": None}
    return found


def _site_locations(item, site_ids: list) -> dict:
    ids = [site_id for site_id in dict.fromkeys(site_ids) if site_id is not None]
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    rows = item["conn"].execute(
        f"SELECT site_id, path, start_line FROM sites WHERE site_id IN ({marks})",
        ids,
    ).fetchall()
    return {row["site_id"]: {"path": row["path"], "start_line": row["start_line"]} for row in rows}


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
        "_source_site_id": site["site_id"],
        "_terminal": True,
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
        "_source_site_id": site["site_id"],
        "_terminal": True,
    }


def _cross(cfg, readable, item, site, view) -> list[dict]:
    spec = _match_spec(site)
    if spec is None:
        return []
    hits = []
    for other in sorted(readable, key=lambda entry: entry["repo_id"]):
        if other["conn"] is None:
            continue
        rows = other["conn"].execute(spec["sql"], spec["args"]).fetchall()
        for row in rows:
            if other["repo_id"] == item["repo_id"] and row["site_id"] == site["site_id"]:
                continue
            if row["site_kind"] == site["site_kind"]:
                continue
            if not view.allow(other, row["path"]):
                continue
            hits.append((other, row))
            if len(hits) > ALTERNATIVE_CAP:
                break
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
            "sql": "SELECT * FROM sites WHERE exec_id = ? ORDER BY site_id LIMIT ?",
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
                    ORDER BY site_id
                    LIMIT ?
                """,
                "args": (site["net_port"], opposite, site["net_host"], ALTERNATIVE_CAP + 1),
                "kind": "net_endpoint",
                "reason": "literal endpoint match is not a confirmed deployment",
            }
        return {
            "sql": "SELECT * FROM sites WHERE net_port = ? AND net_role = ? ORDER BY site_id LIMIT ?",
            "args": (site["net_port"], opposite, ALTERNATIVE_CAP + 1),
            "kind": "net_endpoint",
            "reason": "port match without a host is ambiguous",
        }
    if site["rpc_command"]:
        return {
            "sql": "SELECT * FROM sites WHERE rpc_command = ? ORDER BY site_id LIMIT ?",
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
                ORDER BY site_id
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
                ORDER BY site_id
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
            ORDER BY site_id
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


class _Visibility:
    """Cache include, exclude, and gitignore decisions for one request."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], bool] = {}

    def allow(self, item, path: str) -> bool:
        if not path:
            return False
        key = (item["repo_id"], path)
        if key not in self._cache:
            self._cache[key] = _visible(item, path)
        return self._cache[key]


def _keep_edge(view: _Visibility, by_repo: dict, edge: dict) -> bool:
    """Drop an edge whose source, target, or every alternative is now hidden."""

    def allowed(repo_id: str | None, path: str | None) -> bool:
        if not path:
            return True
        item = by_repo.get(repo_id or "")
        return item is not None and view.allow(item, path)

    source = edge.get("source") or {}
    target = edge.get("target") or {}
    if not allowed(source.get("repo_id"), source.get("path")):
        return False
    if not allowed(target.get("repo_id"), target.get("path")):
        return False
    if edge.get("alternatives"):
        kept = []
        for alt in edge["alternatives"]:
            if allowed(alt.get("repo_id"), alt.get("path")):
                kept.append(alt)
        edge["alternatives"] = kept
        if not kept:
            return False
    return True


def _freshness_warning(warning: str) -> bool:
    return (
        warning.startswith("current commit differs")
        or warning.startswith("index includes uncommitted")
        or warning.startswith("relevant working-tree")
        or warning.startswith("working tree freshness")
    )


def _apply_freshness(opened, body: dict) -> None:
    paths: dict[str, set[str]] = defaultdict(set)
    for loc in (body.get("selection") or {}).get("locations") or []:
        if loc.get("repo_id") and loc.get("path"):
            paths[loc["repo_id"]].add(loc["path"])
    buckets = [body.get("relationships") or []]
    buckets.append((body.get("unresolved") or {}).get("sites") or [])
    for bucket in buckets:
        for edge in bucket:
            for side in ("source", "target"):
                block = edge.get(side) or {}
                if block.get("repo_id") and block.get("path"):
                    paths[block["repo_id"]].add(block["path"])
            for alt in edge.get("alternatives") or []:
                if alt.get("repo_id") and alt.get("path"):
                    paths[alt["repo_id"]].add(alt["path"])
    by_id = {item["repo_id"]: item for item in opened}
    for snap in body.get("snapshots") or []:
        item = by_id.get(snap["repo_id"])
        if item is None or item.get("repo") is None:
            continue
        _refresh_snapshot(snap, item, sorted(paths.get(snap["repo_id"], [])))
    kept = []
    seen = set()
    for warning in body.get("warnings") or []:
        if _freshness_warning(warning) or warning in seen:
            continue
        kept.append(warning)
        seen.add(warning)
    for snap in body.get("snapshots") or []:
        for warning in snap.get("warnings") or []:
            if warning in seen:
                continue
            kept.append(warning)
            seen.add(warning)
    body["warnings"] = kept


def _refresh_snapshot(snap: dict, item, paths: list[str]) -> None:
    warnings = [warning for warning in snap.get("warnings") or [] if not _freshness_warning(warning)]
    indexed = snap.get("indexed_commit")
    current = snap.get("current_commit")
    relevant = worktree_dirty_paths(item["repo"].root, paths) if paths else []
    if paths and relevant is None:
        snap["freshness"] = "unknown"
        warnings.append("working tree freshness is unknown because Git could not answer")
    elif indexed and current and indexed != current:
        snap["freshness"] = "commit_moved"
        warnings.append(
            "current commit differs from the indexed commit; "
            f"run py-indexer index --repo {item['repo_id']}"
        )
    elif relevant:
        snap["freshness"] = "worktree_changed"
        warnings.append(
            "relevant working-tree paths changed after indexing; "
            f"run py-indexer index --repo {item['repo_id']}"
        )
    elif snap.get("indexed_dirty"):
        snap["freshness"] = "dirty_at_index"
        warnings.append(
            "index includes uncommitted content and does not exactly represent "
            f"{indexed or 'its base commit'}"
        )
    elif current and indexed and current == indexed:
        snap["freshness"] = "current"
    else:
        snap["freshness"] = "unknown"
        if current is None or indexed is None:
            warnings.append("working tree freshness is unknown because Git could not answer")
    snap["warnings"] = warnings


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


def serialize_report(body: dict) -> str:
    """Canonical CLI and MCP payload. Byte caps use this exact text."""
    return json.dumps(body, indent=2, ensure_ascii=True, sort_keys=True)


def _report_bytes(body: dict) -> int:
    return len(serialize_report(body).encode("utf-8"))


def _fit(body: dict) -> dict:
    for bucket in (body.get("relationships") or [], (body.get("unresolved") or {}).get("sites") or []):
        for edge in bucket:
            edge.pop("_source_site_id", None)
            edge.pop("_terminal", None)
            edge.pop("_path_node", None)
    if _report_bytes(body) <= OUTPUT_BYTE_CAP:
        return body
    _mark_output_budget(body)
    while body.get("relationships") and _report_bytes(body) > OUTPUT_BYTE_CAP:
        body["relationships"].pop()
    unresolved = body.setdefault("unresolved", {"shown": 0, "omitted": None, "omitted_known": False, "sites": []})
    sites = unresolved.get("sites") or []
    while sites and _report_bytes(body) > OUTPUT_BYTE_CAP:
        sites.pop()
        unresolved["sites"] = sites
        unresolved["shown"] = len(sites)
    for edge in body.get("relationships") or []:
        alternatives = edge.get("alternatives") or []
        while alternatives and _report_bytes(body) > OUTPUT_BYTE_CAP:
            alternatives.pop()
            edge["alternatives"] = alternatives
            edge["alternatives_truncated"] = True
    _trim_text_sections(body)
    if _report_bytes(body) > OUTPUT_BYTE_CAP:
        body["relationships"] = []
        body["unresolved"] = {
            "shown": 0,
            "omitted": None,
            "omitted_known": False,
            "sites": [],
            "unavailable": True,
            "reason": "response exceeded the serialized byte cap",
        }
        body["structural_coverage"] = {
            "unavailable": True,
            "reason": "response exceeded the serialized byte cap",
        }
        body["warnings"] = ["analysis details omitted because the response budget was exceeded"]
        body["fallback"] = {"tool": "search_code", "query": None, "analysis": "unavailable"}
        for snap in body.get("snapshots") or []:
            snap["warnings"] = ["snapshot detail omitted because the response budget was exceeded"]
        selection = body.setdefault("selection", {})
        selection["locations"] = []
        selection["locations_unavailable"] = True
        selection["candidates"] = []
        body["selection"] = selection
        _trim_text_sections(body)
    if _report_bytes(body) > OUTPUT_BYTE_CAP:
        _clip_strings(body, 80)
        body["fallback"] = {"tool": "search_code", "query": None, "analysis": "unavailable"}
    return body


def _mark_output_budget(body: dict) -> None:
    truncation = body.setdefault("truncation", {})
    truncation["truncated"] = True
    truncation["completeness"] = "budget"
    truncation["reason"] = "output_bytes"
    truncation["omitted_known"] = False
    truncation["omitted_relationships"] = None
    unresolved = body.setdefault("unresolved", {"shown": 0, "omitted": None, "omitted_known": False, "sites": []})
    unresolved["omitted"] = None
    unresolved["omitted_known"] = False


def _trim_text_sections(body: dict) -> None:
    warnings = body.get("warnings") or []
    while warnings and _report_bytes(body) > OUTPUT_BYTE_CAP:
        warnings.pop()
        body["warnings"] = warnings
    selection = body.get("selection") or {}
    locations = selection.get("locations") or []
    while locations and _report_bytes(body) > OUTPUT_BYTE_CAP:
        locations.pop()
        selection["locations"] = locations
        selection["locations_omitted_known"] = False
    candidates = selection.get("candidates") or []
    while candidates and _report_bytes(body) > OUTPUT_BYTE_CAP:
        candidates.pop()
        selection["candidates"] = candidates
    for key in ("signature", "qualified_name", "name"):
        value = selection.get(key)
        while isinstance(value, str) and len(value) > 80 and _report_bytes(body) > OUTPUT_BYTE_CAP:
            selection[key] = value[: max(80, len(value) // 2)]
            selection["text_truncated"] = True
            value = selection[key]
    for snap in body.get("snapshots") or []:
        snap_warnings = snap.get("warnings") or []
        while snap_warnings and _report_bytes(body) > OUTPUT_BYTE_CAP:
            snap_warnings.pop()
            snap["warnings"] = snap_warnings
        for key, value in list(snap.items()):
            while isinstance(value, str) and len(value) > 80 and _report_bytes(body) > OUTPUT_BYTE_CAP:
                snap[key] = value[: max(80, len(value) // 2)]
                snap["text_truncated"] = True
                value = snap[key]


def _clip_strings(value, limit: int):
    if isinstance(value, str):
        return value[:limit]
    if isinstance(value, list):
        for index, item in enumerate(value):
            value[index] = _clip_strings(item, limit)
        return value
    if isinstance(value, dict):
        for key, item in list(value.items()):
            value[key] = _clip_strings(item, limit)
        return value
    return value


def _load_list(raw: str) -> list:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def _touch_worktree(root, paths) -> list[str] | None:
    """Compare a bounded path set. Used by freshness when callers pass paths."""
    return worktree_dirty_paths(root, paths)
