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
