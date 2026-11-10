"""Load and validate repos.json."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from py_indexer.budgets import Budgets
from py_indexer.exclude import policy_material
from py_indexer.paths import (
    checkout_fingerprint,
    checkout_index_path,
    find_config_upward,
    is_safe_repo_id,
    is_standard_config_path,
    project_root_from_standard_config,
    resolve_repo_root,
)


class ConfigError(ValueError):
    """Invalid py-indexer configuration."""


@dataclass
class RepoConfig:
    id: str
    root: Path
    role: str
    related: list[str] = field(default_factory=list)
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    # Original configured root string (for fingerprinting).
    root_configured: str = "."


@dataclass
class AppConfig:
    schema_version: int
    active_repo: str
    repositories: dict[str, RepoConfig]
    budgets: Budgets
    chunk_lines: int
    chunk_overlap_lines: int
    project_root: Path
    config_path: Path
    # Directory containing repos.json (legacy excludes.txt overlay lives here).
    config_dir: Path

    def get(self, repo_id: str) -> RepoConfig:
        if repo_id not in self.repositories:
            raise ConfigError(f"unknown repository id: {repo_id!r}")
        return self.repositories[repo_id]

    def active(self) -> RepoConfig:
        return self.get(self.active_repo)

    def related_ids(self, repo_id: str | None = None) -> list[str]:
        base = self.get(repo_id or self.active_repo)
        return list(base.related)

    def content_fingerprint(self, repo_id: str) -> str:
        """Fingerprint of every input that changes what this checkout's index contains.

        Projects that disagree cannot keep separate contents in the one database
        for this checkout. Search refuses a snapshot built with a different policy
        instead of widening or narrowing it silently.
        """
        repo = self.get(repo_id)
        return checkout_fingerprint(
            schema_version=self.schema_version,
            chunk_lines=self.chunk_lines,
            chunk_overlap_lines=self.chunk_overlap_lines,
            max_file_bytes=self.budgets.max_file_bytes,
            include=repo.include,
            exclude=repo.exclude,
            policy=policy_material(self.config_dir, repo.root),
        )

    def db_path(self, repo_id: str) -> Path:
        return checkout_index_path(self.get(repo_id).root)

    # Back-compat alias used by older call sites / status output.
    @property
    def target_root(self) -> Path:
        return self.project_root

    @property
    def tool_root(self) -> Path:
        """Deprecated alias: config directory (legacy excludes overlay)."""
        return self.config_dir


def _require_dict(obj: Any, label: str) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise ConfigError(f"{label} must be an object")
    return obj


def _require_str(obj: Any, label: str) -> str:
    if not isinstance(obj, str) or not obj.strip():
        raise ConfigError(f"{label} must be a non-empty string")
    return obj


def _require_str_list(obj: Any, label: str) -> list[str]:
    if obj is None:
        return []
    if not isinstance(obj, list) or not all(isinstance(x, str) for x in obj):
        raise ConfigError(f"{label} must be an array of strings")
    return list(obj)


def resolve_config_path(
    config_path: Path | None = None,
    *,
    start: Path | None = None,
) -> Path:
    if config_path is not None:
        return config_path.expanduser().resolve()
    found = find_config_upward(start)
    if found is None:
        raise ConfigError(
            "no configuration found: pass --config PATH or run from a project "
            "containing .repo-kit/tools/py-indexer/repos.json"
        )
    return found


def resolve_project_root(
    config_path: Path,
    *,
    project_root: Path | None = None,
) -> Path:
    if project_root is not None:
        return project_root.expanduser().resolve()
    if is_standard_config_path(config_path):
        return project_root_from_standard_config(config_path)
    raise ConfigError(
        f"nonstandard config path requires --project-root: {config_path}"
    )


def load_config(
    config_path: Path | None = None,
    *,
    project_root: Path | None = None,
    target_root: Path | None = None,
    tool_root: Path | None = None,
) -> AppConfig:
    # target_root / tool_root kept as optional test overrides.
    path = resolve_config_path(config_path)
    if not path.is_file():
        raise ConfigError(f"missing config: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"malformed JSON in {path}: {exc}") from exc

    data = _require_dict(data, "config")
    schema_version = data.get("schema_version")
    if schema_version != 1:
        raise ConfigError(f"unsupported schema_version: {schema_version!r} (expected 1)")

    active_repo = _require_str(data.get("active_repo"), "active_repo")
    if not is_safe_repo_id(active_repo):
        raise ConfigError(f"unsafe active_repo id: {active_repo!r}")

    defaults = _require_dict(data.get("defaults") or {}, "defaults")
    budgets = Budgets(
        max_results=int(defaults.get("max_results", 12)),
        max_snippet_chars=int(defaults.get("max_snippet_chars", 1200)),
        max_total_chars=int(defaults.get("max_total_chars", 12000)),
        max_file_bytes=int(defaults.get("max_file_bytes", 524288)),
    )
    chunk_lines = int(defaults.get("chunk_lines", 80))
    chunk_overlap = int(defaults.get("chunk_overlap_lines", 10))
    if chunk_lines < 10 or chunk_overlap < 0 or chunk_overlap >= chunk_lines:
        raise ConfigError("invalid chunk_lines / chunk_overlap_lines")

    repos_raw = data.get("repositories")
    if not isinstance(repos_raw, list) or not repos_raw:
        raise ConfigError("repositories must be a non-empty array")

    if target_root is not None and project_root is None:
        project_root = target_root
    if tool_root is not None and project_root is None and is_standard_config_path(path):
        # Old tests passed tool_root = …/py-indexer; project is three parents up.
        project_root = tool_root.resolve().parent.parent.parent
    p_root = resolve_project_root(path, project_root=project_root)
    config_dir = path.parent.resolve()

    repositories: dict[str, RepoConfig] = {}
    for i, item in enumerate(repos_raw):
        item = _require_dict(item, f"repositories[{i}]")
        rid = _require_str(item.get("id"), f"repositories[{i}].id")
        if not is_safe_repo_id(rid):
            raise ConfigError(f"unsafe repository id: {rid!r}")
        if rid in repositories:
            raise ConfigError(f"duplicate repository id: {rid!r}")
        role = _require_str(item.get("role"), f"repositories[{i}].role")
        if role not in ("working", "reference"):
            raise ConfigError(f"repositories[{i}].role must be 'working' or 'reference'")
        root_s = _require_str(item.get("root"), f"repositories[{i}].root")
        try:
            root = resolve_repo_root(p_root, root_s)
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
        if not root.exists() or not root.is_dir():
            raise ConfigError(f"repository root missing or not a directory: {rid} -> {root}")
        include = _require_str_list(item.get("include"), f"repositories[{i}].include")
        exclude = _require_str_list(item.get("exclude"), f"repositories[{i}].exclude")
        repositories[rid] = RepoConfig(
            id=rid,
            root=root,
            role=role,
            related=_require_str_list(item.get("related"), f"repositories[{i}].related"),
            include=include,
            exclude=exclude,
            root_configured=root_s,
        )

    if active_repo not in repositories:
        raise ConfigError(f"active_repo {active_repo!r} not found in repositories")

    for rid, repo in repositories.items():
        for rel in repo.related:
            if rel not in repositories:
                raise ConfigError(f"repository {rid!r} related id unknown: {rel!r}")
            if rel == rid:
                raise ConfigError(f"repository {rid!r} cannot related to itself")

    return AppConfig(
        schema_version=schema_version,
        active_repo=active_repo,
        repositories=repositories,
        budgets=budgets,
        chunk_lines=chunk_lines,
        chunk_overlap_lines=chunk_overlap,
        project_root=p_root,
        config_path=path,
        config_dir=config_dir,
    )
