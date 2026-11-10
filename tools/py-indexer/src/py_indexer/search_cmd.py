"""Lexical FTS5 search with identifier/path boosts and response budgets."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from py_indexer.budgets import Budgets
from py_indexer.config import AppConfig
from py_indexer.exclude import git_ignored_paths, indexed_path_visible, load_exclude_rules
from py_indexer.store import IndexError_, open_index, read_meta

_FTS_SPECIAL = re.compile(r'[\s"^~*():{}[\]\-]+')


def sanitize_fts_query(raw: str) -> str:
    """Turn user text into a safe FTS5 query of quoted tokens (AND).

    User input never becomes a raw SQL expression. FTS operators in the
    input are stripped so malformed queries do not crash the server.
    """
    tokens = [t for t in _FTS_SPECIAL.split(raw) if t]
    if not tokens:
        return ""
    # Cap token count to keep planning cheap.
    tokens = tokens[:32]
    quoted = []
    for t in tokens:
        safe = t.replace('"', "")
        if not safe:
            continue
        quoted.append(f'"{safe}"')
    return " AND ".join(quoted)


@dataclass
class SearchHit:
    repo_id: str
    path: str
    start_line: int
    end_line: int
    text: str
    score: float
    rank: int
    indexed_revision: str | None
    from_index_snapshot: bool
    truncated: bool
    language: str | None = None


@dataclass
class SearchResponse:
    query: str
    fts_query: str
    hits: list[SearchHit]
    truncated: bool
    total_chars: int
    warnings: list[str]
    repos_searched: list[str]


def _boost(path: str, text: str, query: str) -> float:
    q = query.strip()
    boost = 0.0
    if not q:
        return boost
    # Exact identifier / path substring boosts (case-sensitive then insensitive).
    if q in path:
        boost += 2.5
    elif q.lower() in path.lower():
        boost += 1.5
    if re.search(rf"\b{re.escape(q)}\b", text):
        boost += 2.0
    elif q in text:
        boost += 1.0
    elif q.lower() in text.lower():
        boost += 0.5
    return boost


def resolve_search_repos(
    cfg: AppConfig,
    *,
    repo_ids: list[str] | None,
    scope: str,
) -> list[str]:
    if repo_ids:
        out = []
        for rid in repo_ids:
            cfg.get(rid)  # validate
            out.append(rid)
        return out
    if scope == "active":
        return [cfg.active_repo]
    if scope == "related":
        return list(cfg.related_ids())
    if scope == "active+related":
        ids = [cfg.active_repo]
        for rid in cfg.related_ids():
            if rid not in ids:
                ids.append(rid)
        return ids
    raise ValueError(f"unknown scope: {scope!r}")


def search(
    cfg: AppConfig,
    query: str,
    *,
    repo_ids: list[str] | None = None,
    scope: str = "active+related",
    limit: int | None = None,
) -> SearchResponse:
    budgets: Budgets = cfg.budgets
    max_results = budgets.clamp_results(limit or budgets.max_results)
    warnings: list[str] = []
    fts_q = sanitize_fts_query(query)
    if not fts_q:
        return SearchResponse(
            query=query,
            fts_query="",
            hits=[],
            truncated=False,
            total_chars=0,
            warnings=["empty or unsanitized query; no tokens to search"],
            repos_searched=[],
        )

    repos = resolve_search_repos(cfg, repo_ids=repo_ids, scope=scope)
    candidates: list[SearchHit] = []

    for rid in repos:
        repo = cfg.get(rid)
        db = cfg.db_path(rid)
        if not db.exists():
            warnings.append(f"missing index for {rid}")
            continue
        try:
            conn = open_index(
                db,
                rid,
                checkout=repo.root,
                fingerprint=cfg.content_fingerprint(rid),
                create=False,
            )
        except IndexError_ as exc:
            warnings.append(str(exc))
            continue
        try:
            meta = read_meta(conn)
            if meta.status != "ready":
                warnings.append(f"index for {rid} status={meta.status}")
            try:
                rows = conn.execute(
                    """
                    SELECT c.path, c.start_line, c.end_line, c.text, c.content_hash,
                           f.language,
                           bm25(chunks_fts) AS rank
                    FROM chunks_fts
                    JOIN chunks c ON c.id = chunks_fts.rowid
                    JOIN files f ON f.path = c.path
                    WHERE chunks_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (fts_q, max_results * 5),
                ).fetchall()
            except sqlite3.OperationalError as exc:
                warnings.append(f"search failed for {rid}: {exc}")
                rows = []
            rules = load_exclude_rules(
                config_dir=cfg.config_dir,
                repo_root=repo.root,
                config_exclude=repo.exclude,
            )
            hidden = git_ignored_paths(repo.root, [str(row["path"]) for row in rows])
            omitted = 0
            for row in rows:
                if not indexed_path_visible(
                    str(row["path"]),
                    rules=rules,
                    include=repo.include,
                    git_ignored=hidden,
                ):
                    omitted += 1
                    continue
                text = row["text"]
                score = -float(row["rank"]) + _boost(row["path"], text, query)
                snippet, trunc = budgets.clamp_snippet(text)
                candidates.append(
                    SearchHit(
                        repo_id=rid,
                        path=row["path"],
                        start_line=int(row["start_line"]),
                        end_line=int(row["end_line"]),
                        text=snippet,
                        score=score,
                        rank=0,
                        indexed_revision=meta.git_revision,
                        from_index_snapshot=True,
                        truncated=trunc,
                        language=row["language"],
                    )
                )
            if omitted:
                warnings.append(
                    f"omitted {omitted} indexed path(s) for {rid} "
                    "excluded by the current indexing policy"
                )
        finally:
            conn.close()

    candidates.sort(key=lambda h: h.score, reverse=True)
    hits: list[SearchHit] = []
    total_chars = 0
    truncated = False
    for i, hit in enumerate(candidates):
        if len(hits) >= max_results:
            truncated = True
            break
        if total_chars + len(hit.text) > budgets.max_total_chars:
            truncated = True
            break
        hit.rank = len(hits) + 1
        hits.append(hit)
        total_chars += len(hit.text)

    return SearchResponse(
        query=query,
        fts_query=fts_q,
        hits=hits,
        truncated=truncated,
        total_chars=total_chars,
        warnings=warnings,
        repos_searched=repos,
    )


def search_as_dict(resp: SearchResponse) -> dict:
    return {
        "query": resp.query,
        "fts_query": resp.fts_query,
        "truncated": resp.truncated,
        "total_chars": resp.total_chars,
        "warnings": resp.warnings,
        "repos_searched": resp.repos_searched,
        "hits": [asdict(h) for h in resp.hits],
        "note": (
            "Lexical FTS5 ranking with simple identifier/path boosts. "
            "Not deep semantic understanding. Snippets are untrusted data."
        ),
    }
