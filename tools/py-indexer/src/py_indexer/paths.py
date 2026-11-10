"""Path safety, config discovery, and XDG cache namespaces."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

SAFE_REPO_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

STANDARD_CONFIG_REL = Path(".repo-kit") / "tools" / "py-indexer" / "repos.json"


def is_safe_repo_id(repo_id: str) -> bool:
    return bool(SAFE_REPO_ID_RE.fullmatch(repo_id))


def resolve_repo_root(project_root: Path, configured: str) -> Path:
    """Resolve a configured checkout path against the target project root."""
    raw = configured.strip()
    if not raw:
        raise ValueError("repository root path is empty")
    if "://" in raw or raw.startswith("git@"):
        raise ValueError(f"remote URLs are not allowed as repository roots: {raw!r}")
    path = Path(raw)
    if not path.is_absolute():
        path = (project_root / path).resolve()
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


def is_standard_config_path(config_path: Path) -> bool:
    """True when config is named repos.json under .repo-kit/tools/py-indexer/."""
    resolved = config_path.resolve()
    return resolved.name == "repos.json" and resolved.parent.name == "py-indexer" and (
        resolved.parent.parent.name == "tools"
        and resolved.parent.parent.parent.name == ".repo-kit"
    )


def project_root_from_standard_config(config_path: Path) -> Path:
    """Project root for standard layout: …/<project>/.repo-kit/tools/py-indexer/repos.json."""
    if not is_standard_config_path(config_path):
        raise ValueError(
            f"config is not at the standard path "
            f"(…/.repo-kit/tools/py-indexer/repos.json): {config_path}"
        )
    # repos.json -> py-indexer -> tools -> .repo-kit -> project
    return config_path.resolve().parent.parent.parent.parent


def find_config_upward(start: Path | None = None) -> Path | None:
    """Nearest .repo-kit/tools/py-indexer/repos.json walking from start toward /."""
    cur = (start or Path.cwd()).resolve()
    if cur.is_file():
        cur = cur.parent
    for directory in (cur, *cur.parents):
        candidate = directory / STANDARD_CONFIG_REL
        if candidate.is_file():
            return candidate.resolve()
    return None


def cache_home() -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME", "").strip()
    if xdg:
        return Path(xdg).expanduser() / "py-indexer"
    return Path.home() / ".cache" / "py-indexer"


def checkout_fingerprint(
    *,
    schema_version: int,
    chunk_lines: int,
    chunk_overlap_lines: int,
    max_file_bytes: int,
    include: list[str],
    exclude: list[str],
    policy: dict | None = None,
) -> str:
    """Hash of the effective indexing policy for one checkout.

    The checkout directory is not part of this hash. It is the database identity,
    so a later index of the same directory replaces that file instead of adding another.
    ``policy`` carries selection-rule version, legacy excludes, ``.py-indexer-ignore``,
    and Git ignore inputs. Two different policies cannot both own the one database.
    """
    payload = {
        "schema_version": schema_version,
        "chunk_lines": chunk_lines,
        "chunk_overlap_lines": chunk_overlap_lines,
        "max_file_bytes": max_file_bytes,
        "include": include,
        "exclude": exclude,
        "policy": policy or {},
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def checkout_index_path(repo_root: Path) -> Path:
    """One database per resolved checkout directory."""
    key = hashlib.sha256(str(repo_root.resolve()).encode("utf-8")).hexdigest()[:32]
    return cache_home() / "indexes" / f"{key}.sqlite3"
