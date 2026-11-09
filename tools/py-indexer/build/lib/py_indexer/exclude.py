"""File selection / exclusions for indexing and read_code.

Layers (all apply; any match excludes):
1. Hard-coded directory/file/secret rules
2. Packaged ``default_excludes.txt`` (shipped with the application)
3. Legacy project ``excludes.txt`` beside ``repos.json`` (deprecated overlay)
4. Per-repo ``.py-indexer-ignore`` (optional overlay)
5. ``repos.json`` repository ``exclude`` globs
6. Git ignore rules when available (``git ls-files --exclude-standard``;
   otherwise nested ``.gitignore`` parse)

Not a guaranteed secret scanner.
"""

from __future__ import annotations

import fnmatch
import os
import subprocess
from importlib import resources
from pathlib import Path

HARD_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "bower_components",
    "vendor",
    "dist",
    "build",
    "out",
    "target",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".idea",
    "coverage",
    ".next",
    ".nuxt",
    ".turbo",
    "Pods",
    "DerivedData",
}

HARD_FILE_GLOBS = [
    "*.pyc",
    "*.pyo",
    "*.so",
    "*.dylib",
    "*.dll",
    "*.exe",
    "*.o",
    "*.a",
    "*.class",
    "*.jar",
    "*.wasm",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.webp",
    "*.ico",
    "*.pdf",
    "*.zip",
    "*.tar",
    "*.gz",
    "*.7z",
    "*.rar",
    "*.woff*",
    "*.ttf",
    "*.otf",
    "*.mp3",
    "*.mp4",
    "*.mov",
    "*.sqlite3",
    "*.db",
    "*.bin",
    "*.map",
]

SECRETISH_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "credentials.json",
    "service-account.json",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "private.key",
    "private-key.pem",
    "wallet.dat",
    "secret.key",
    "secrets.yaml",
    "secrets.yml",
    "secrets.json",
    ".npmrc",
}

SECRETISH_SUFFIXES = (
    ".pem",
    ".p12",
    ".pfx",
    ".keystore",
    ".jks",
)

SECRETISH_ALLOW_BASENAMES = {
    ".env.example",
    ".env.sample",
    ".env.template",
}

DEFAULT_INCLUDE_GLOBS = [
    "*.ts",
    "*.tsx",
    "*.js",
    "*.jsx",
    "*.mjs",
    "*.cjs",
    "*.json",
    "*.md",
    "*.mdx",
    "*.txt",
    "*.toml",
    "*.yaml",
    "*.yml",
    "*.py",
    "*.rs",
    "*.go",
    "*.c",
    "*.cc",
    "*.cpp",
    "*.cxx",
    "*.h",
    "*.hh",
    "*.hpp",
    "*.java",
    "*.kt",
    "*.swift",
    "*.rb",
    "*.php",
    "*.cs",
    "*.fs",
    "*.scala",
    "*.sh",
    "*.bash",
    "*.zsh",
    "*.ps1",
    "*.cmake",
    "CMakeLists.txt",
    "Makefile",
    "Dockerfile",
    "Dockerfile.*",
    "*.dockerfile",
    "*.sql",
    "*.graphql",
    "*.proto",
    "*.css",
    "*.scss",
    "*.less",
    "*.html",
    "*.htm",
    "*.vue",
    "*.svelte",
    "*.lock",
    "Cargo.toml",
    "package.json",
    "pyproject.toml",
    "requirements*.txt",
    "go.mod",
    "go.sum",
    "*.gradle",
    "*.xml",
]


def language_for(path: str) -> str:
    ext = Path(path.lower()).suffix
    mapping = {
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".py": "python",
        ".rs": "rust",
        ".go": "go",
        ".c": "c",
        ".h": "c",
        ".cc": "cpp",
        ".cpp": "cpp",
        ".hpp": "cpp",
        ".md": "markdown",
        ".json": "json",
        ".toml": "toml",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".sh": "shell",
        ".css": "css",
        ".html": "html",
        ".sql": "sql",
    }
    return mapping.get(ext, ext.lstrip(".") or "text")


def _strip_pattern(pattern: str) -> tuple[str, bool, bool]:
    """Return (pattern, anchored, dir_only)."""
    pat = pattern.strip()
    anchored = pat.startswith("/")
    if anchored:
        pat = pat[1:]
    dir_only = pat.endswith("/")
    if dir_only:
        pat = pat.rstrip("/")
    return pat, anchored, dir_only


def pattern_matches(path: str, pattern: str, *, is_dir: bool = False) -> bool:
    """gitignore-ish glob match against a repo-relative posix path."""
    pat, anchored, dir_only = _strip_pattern(pattern)
    if not pat:
        return False
    if dir_only and not is_dir:
        # Directory patterns also exclude descendants.
        prefix = pat
        if path == prefix or path.startswith(prefix + "/"):
            return True
        # also allow glob dir names like build*
        parts = path.split("/")
        for i, _part in enumerate(parts):
            prefix_path = "/".join(parts[: i + 1])
            if anchored:
                if fnmatch.fnmatch(prefix_path, pat):
                    return True
            elif fnmatch.fnmatch(parts[i], pat) or fnmatch.fnmatch(prefix_path, pat):
                return True
        return False

    if anchored:
        return fnmatch.fnmatch(path, pat) or path == pat

    base = Path(path).name
    if fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(base, pat):
        return True
    return any(fnmatch.fnmatch(part, pat) for part in path.split("/"))


def _match_any(path: str, patterns: list[str], *, is_dir: bool = False) -> bool:
    return any(pattern_matches(path, p, is_dir=is_dir) for p in patterns)


class IgnoreRuleSet:
    """Ordered gitignore-style rules with negation support."""

    def __init__(self) -> None:
        self.rules: list[tuple[str, bool]] = []  # (raw pattern, negate)

    def add_lines(self, lines: list[str]) -> None:
        for line in lines:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            negate = s.startswith("!")
            if negate:
                s = s[1:].strip()
            if not s:
                continue
            self.rules.append((s, negate))

    def add_file(self, path: Path) -> None:
        if not path.is_file():
            return
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        self.add_lines(text.splitlines())

    def ignored(self, rel_posix: str, *, is_dir: bool = False) -> bool:
        ignored = False
        for pat, negate in self.rules:
            if pattern_matches(rel_posix, pat, is_dir=is_dir):
                ignored = not negate
        return ignored


def _packaged_default_exclude_lines() -> list[str]:
    try:
        text = resources.files("py_indexer").joinpath("default_excludes.txt").read_text(
            encoding="utf-8"
        )
    except (FileNotFoundError, OSError, TypeError):
        # Editable / incomplete installs: fall back to sibling file.
        sibling = Path(__file__).with_name("default_excludes.txt")
        if not sibling.is_file():
            return []
        text = sibling.read_text(encoding="utf-8")
    return text.splitlines()


def load_exclude_rules(
    *,
    config_dir: Path | None = None,
    tool_root: Path | None = None,
    repo_root: Path,
    config_exclude: list[str] | None = None,
) -> IgnoreRuleSet:
    """Load exclusion layers.

    ``tool_root`` is accepted as a deprecated alias for ``config_dir`` (legacy tests).
    """
    rules = IgnoreRuleSet()
    rules.add_lines(_packaged_default_exclude_lines())
    overlay_dir = config_dir if config_dir is not None else tool_root
    if overlay_dir is not None:
        # Deprecated: project-local excludes.txt beside repos.json.
        rules.add_file(overlay_dir / "excludes.txt")
    rules.add_file(repo_root / ".py-indexer-ignore")
    if config_exclude:
        rules.add_lines(config_exclude)
    return rules


class GitIgnoreMatcher:
    """Parse root + nested .gitignore files (fallback when git CLI unavailable)."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.global_rules = IgnoreRuleSet()
        self.global_rules.add_file(self.root / ".gitignore")
        self._nested: dict[str, IgnoreRuleSet] = {}

    def load_nested(self, rel_dir: str, path: Path) -> None:
        gi = path / ".gitignore"
        if not gi.is_file():
            return
        rs = IgnoreRuleSet()
        rs.add_file(gi)
        self._nested[rel_dir] = rs

    def ignored(self, rel_posix: str, is_dir: bool = False) -> bool:
        if self.global_rules.ignored(rel_posix, is_dir=is_dir):
            return True
        parts = rel_posix.split("/")
        last = len(parts) - (0 if is_dir else 1)
        for i in range(max(0, last)):
            parent = "/".join(parts[: i + 1])
            nested = self._nested.get(parent)
            if nested is None:
                continue
            rest = "/".join(parts[i + 1 :])
            if rest and nested.ignored(rest, is_dir=is_dir):
                return True
        return False


def is_secretish(rel_posix: str) -> bool:
    base = Path(rel_posix).name
    lower = base.lower()
    if lower in SECRETISH_ALLOW_BASENAMES or base in SECRETISH_ALLOW_BASENAMES:
        return False
    if lower in SECRETISH_NAMES or base in SECRETISH_NAMES:
        return True
    if lower.startswith(".env."):
        return True
    return any(lower.endswith(suf) for suf in SECRETISH_SUFFIXES)


def should_skip_dir(name: str, config_dir: Path | None, current: Path) -> bool:
    if name in HARD_DIR_NAMES:
        return True
    # Skip legacy project-local index/.venv under the config directory.
    if name in {"index", ".venv"} and config_dir is not None:
        try:
            current.resolve().relative_to(config_dir.resolve())
            return True
        except ValueError:
            pass
    return False


def is_binary_sample(sample: bytes) -> bool:
    if b"\x00" in sample:
        return True
    if not sample:
        return False
    textish = sum(1 for b in sample if b in (9, 10, 13) or 32 <= b <= 126)
    return (textish / len(sample)) < 0.85


def is_git_work_tree(root: Path) -> bool:
    return (root / ".git").exists()


def git_non_ignored_files(root: Path) -> set[str] | None:
    """Paths not ignored by Git, or None if Git unavailable."""
    if not is_git_work_tree(root):
        return None
    try:
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "-z",
                "-c",
                "-o",
                "--exclude-standard",
            ],
            check=False,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    out: set[str] = set()
    for item in proc.stdout.split(b"\0"):
        if not item:
            continue
        out.add(item.decode("utf-8", errors="replace"))
    return out


def path_is_excluded(
    rel_posix: str,
    *,
    exclude_rules: IgnoreRuleSet,
    is_dir: bool = False,
) -> bool:
    parts = [p for p in rel_posix.split("/") if p]
    if any(p in HARD_DIR_NAMES for p in parts[:-1]):
        return True
    if is_dir and parts and parts[-1] in HARD_DIR_NAMES:
        return True
    if not is_dir:
        if is_secretish(rel_posix):
            return True
        base = Path(rel_posix).name
        if _match_any(rel_posix, HARD_FILE_GLOBS) or _match_any(base, HARD_FILE_GLOBS):
            return True
    return exclude_rules.ignored(rel_posix, is_dir=is_dir)


def iter_candidate_files(
    root: Path,
    *,
    include: list[str],
    exclude: list[str],
    max_file_bytes: int,
    config_dir: Path | None = None,
    tool_root: Path | None = None,
):
    """Yield (rel_posix, absolute Path) for indexable files. Does not follow dir symlinks."""
    root = root.resolve()
    overlay = config_dir if config_dir is not None else tool_root
    exclude_rules = load_exclude_rules(
        config_dir=overlay, repo_root=root, config_exclude=exclude
    )
    include_globs = include or DEFAULT_INCLUDE_GLOBS
    git_allow = git_non_ignored_files(root)

    def _accept_file(rel: str, path: Path) -> bool:
        if path_is_excluded(rel, exclude_rules=exclude_rules, is_dir=False):
            return False
        if overlay is not None:
            try:
                path.resolve().relative_to(overlay.resolve())
                return False
            except ValueError:
                pass
        if not _match_any(rel, include_globs):
            return False
        try:
            size = path.stat().st_size
        except OSError:
            return False
        if size > max_file_bytes:
            return False
        try:
            with path.open("rb") as fh:
                sample = fh.read(8192)
        except OSError:
            return False
        if is_binary_sample(sample):
            return False
        return True

    if git_allow is not None:
        for rel in sorted(git_allow):
            path = root / rel
            if path.is_symlink():
                try:
                    resolved = path.resolve()
                    resolved.relative_to(root)
                except (OSError, ValueError):
                    continue
                path = resolved
            if not path.is_file():
                continue
            if _accept_file(rel, path):
                yield rel, path
        return

    gi = GitIgnoreMatcher(root)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        rel_current = (
            ""
            if current.resolve() == root
            else current.resolve().relative_to(root).as_posix()
        )
        if rel_current:
            gi.load_nested(rel_current, current)

        keep: list[str] = []
        for name in list(dirnames):
            child = current / name
            if child.is_symlink():
                continue
            if should_skip_dir(name, overlay, child):
                continue
            rel_dir = child.relative_to(root).as_posix()
            if path_is_excluded(rel_dir, exclude_rules=exclude_rules, is_dir=True):
                continue
            if gi.ignored(rel_dir, is_dir=True):
                continue
            if overlay is not None:
                try:
                    child.resolve().relative_to(overlay.resolve())
                    continue
                except ValueError:
                    pass
            keep.append(name)
        dirnames[:] = sorted(keep)

        for name in filenames:
            path = current / name
            if path.is_symlink():
                try:
                    resolved = path.resolve()
                    resolved.relative_to(root)
                except (OSError, ValueError):
                    continue
                path = resolved
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if gi.ignored(rel, is_dir=False):
                continue
            if _accept_file(rel, path):
                yield rel, path
