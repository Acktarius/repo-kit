#!/usr/bin/env python3
"""Git-backed ignore filtering, including info/exclude and linked worktrees."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "py-indexer" / "src"))

from py_indexer.exclude import git_ignored_paths, policy_material  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


class GitIgnoreFilterTests(unittest.TestCase):
    def test_check_ignore_uses_info_exclude_and_repo_excludes(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="py-indexer-git-"))
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(tmp)], check=False))
        repo = tmp / "repo"
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@example.com")
        _git(repo, "config", "user.name", "t")
        (repo / "keep.ts").write_text("export const keep = 1;\n", encoding="utf-8")
        _git(repo, "add", "keep.ts")
        _git(repo, "commit", "-q", "-m", "init")

        info = Path(_git(repo, "rev-parse", "--git-path", "info/exclude"))
        if not info.is_absolute():
            info = repo / info
        info.parent.mkdir(parents=True, exist_ok=True)
        info.write_text("secret-info.ts\n", encoding="utf-8")
        excludes = repo / "repo-excludes.txt"
        excludes.write_text("secret-local.ts\n", encoding="utf-8")
        _git(repo, "config", "core.excludesFile", str(excludes))

        ignored = git_ignored_paths(repo, ["secret-info.ts", "secret-local.ts", "keep.ts"])
        self.assertIn("secret-info.ts", ignored)
        self.assertIn("secret-local.ts", ignored)
        self.assertNotIn("keep.ts", ignored)

        material = policy_material(None, repo)
        self.assertIn("secret-info.ts", material["git_info_exclude"]["text"])
        self.assertEqual(material["core_excludes"]["path"], str(excludes))
        self.assertIn("secret-local.ts", material["core_excludes"]["text"])

        worktree = tmp / "linked"
        _git(repo, "worktree", "add", "-q", str(worktree))
        self.assertTrue((worktree / ".git").is_file())
        linked = git_ignored_paths(worktree, ["secret-info.ts", "keep.ts"])
        self.assertIn("secret-info.ts", linked)
        self.assertNotIn("keep.ts", linked)
        linked_material = policy_material(None, worktree)
        self.assertIn("secret-info.ts", linked_material["git_info_exclude"]["text"])
        self.assertIn("secret-local.ts", linked_material["core_excludes"]["text"])


if __name__ == "__main__":
    unittest.main()
