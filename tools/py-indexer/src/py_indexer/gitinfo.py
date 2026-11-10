"""Optional Git metadata via the git CLI when available. Never runs user input."""

from __future__ import annotations

import subprocess
from pathlib import Path


def git_head(repo_root: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    rev = proc.stdout.strip()
    return rev or None


def is_git_repo(repo_root: Path) -> bool:
    return (repo_root / ".git").exists()


def _status_paths(repo_root: Path) -> set[str] | None:
    """Dirty paths from porcelain status, or None when git cannot answer.

    The set is for the caller to intersect with indexed paths. It is not stored.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain=v1", "-z"],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    found: set[str] = set()
    for entry in proc.stdout.split(b"\0"):
        if len(entry) < 4:
            continue
        path = entry[3:].decode("utf-8", "replace").replace("\\", "/")
        if path:
            found.add(path)
    return found


def _status_covers(path: str, dirty: set[str]) -> bool:
    """True when ``path`` is dirty, including an untracked parent directory.

    Porcelain reports a wholly untracked directory as ``src/`` rather than
    each file inside it.
    """
    if path in dirty:
        return True
    parent = path
    while "/" in parent:
        parent = parent.rsplit("/", 1)[0]
        if parent + "/" in dirty:
            return True
    return False


def indexed_content_is_dirty(repo_root: Path, indexed_paths: set[str]) -> bool | None:
    """True when an indexed path was uncommitted. None when git cannot answer."""
    dirty = _status_paths(repo_root)
    if dirty is None:
        return None
    return any(_status_covers(path, dirty) for path in indexed_paths)


def worktree_dirty_paths(repo_root: Path, paths: list[str]) -> list[str] | None:
    """Dirty paths among ``paths`` only. None when git cannot answer."""
    dirty = _status_paths(repo_root)
    if dirty is None:
        return None
    return sorted(path for path in paths if _status_covers(path, dirty))
