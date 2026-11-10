"""Path safety helpers for configured repository roots."""

from __future__ import annotations

import os
import re
from pathlib import Path

SAFE_REPO_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def is_safe_repo_id(repo_id: str) -> bool:
    return bool(SAFE_REPO_ID_RE.fullmatch(repo_id))


def tool_root_from_package() -> Path:
    """Installed tool root: .../py-indexer/ (parent of py_indexer package)."""
    return Path(__file__).resolve().parent.parent


def resolve_target_root(explicit: Path | None = None) -> Path:
    """Target repository root (directory that contains .repo-kit/tools/py-indexer)."""
    if explicit is not None:
        return explicit.resolve()
    # .../<target>/.repo-kit/tools/py-indexer
    return tool_root_from_package().parent.parent.parent


def resolve_repo_root(target_root: Path, configured: str) -> Path:
    """Resolve a configured checkout path against the target repository root."""
    raw = configured.strip()
    if not raw:
        raise ValueError("repository root path is empty")
    if "://" in raw or raw.startswith("git@"):
        raise ValueError(f"remote URLs are not allowed as repository roots: {raw!r}")
    path = Path(raw)
    if not path.is_absolute():
        path = (target_root / path).resolve()
    else:
        path = path.resolve()
    return path


def safe_join(root: Path, rel: str) -> Path:
    """Join root + relative path; reject escapes and absolute inputs."""
    if not rel or rel.startswith("/") or rel.startswith("\\"):
        raise ValueError(f"path must be repository-relative: {rel!r}")
    if "\\" in rel:
        raise ValueError(f"use forward slashes in relative paths: {rel!r}")
    parts = Path(rel).parts
    if any(p in ("", ".") for p in parts):
        # allow '.' segments? better reject weirdness except normal files
        pass
    if ".." in parts:
        raise ValueError(f"path traversal rejected: {rel!r}")
    candidate = (root / rel).resolve()
    root_resolved = root.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"path escapes repository root: {rel!r}") from exc
    return candidate


def is_under_root(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def index_db_path(tool_root: Path, repo_id: str) -> Path:
    if not is_safe_repo_id(repo_id):
        raise ValueError(f"unsafe repository id for index path: {repo_id!r}")
    return tool_root / "index" / f"{repo_id}.sqlite3"
