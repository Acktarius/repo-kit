#!/usr/bin/env python3
"""Scan git-tracked files for personal data and optionally replace it.

Stdlib only. Run through scrub-personal-data.sh.
"""

from __future__ import annotations

import argparse
import fnmatch
import ipaddress
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

TOKENS_REL = Path(".repo-kit") / "personal-tokens.txt"
TOKEN_DELIM = "->"
DEFAULT_TOKEN_PLACEHOLDER = "<redacted>"
IP_PLACEHOLDER = "<ip-address>"
EMAIL_PLACEHOLDER = "<email>"
ENV_PATTERNS = (".env", ".env.*", "*.env")
SKIP_PATTERNS = ("package-lock.json",)
ENCODING = "utf-8"
ERRORS = "surrogateescape"  # round-trips non-UTF-8 bytes unchanged

# Loopback (127.0.0.0/8) and documentation ranges are intentionally absent.
PERSONAL_NETWORKS = tuple(
    ipaddress.IPv4Network(n)
    for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16")
)

IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\d|\.\d)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
EMAIL_ALLOW_LOCAL = {"git"}
EMAIL_ALLOW_DOMAINS = ("example.com", "example.org", "example.net", "users.noreply.github.com")
FIX_SELECTION_RE = re.compile(r"^\d+(,\d+)*$")

HELP_EPILOG = f"""\
detectors:
  ip     10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16 -> {IP_PLACEHOLDER}
         (loopback such as 127.0.0.1 and public addresses are not reported)
  email  any address except git@... and example.com/.org/.net, GitHub noreply -> {EMAIL_PLACEHOLDER}
  token  whole-word, case-insensitive lines from {TOKENS_REL}
  env    tracked .env, .env.*, *.env files (reported, never rewritten)
  skip   package-lock.json (generated; not scanned)

{TOKENS_REL} format:
  one token per line; lines starting with # are comments; a missing file means no tokens.
  "token -> <placeholder>" splits on the first "{TOKEN_DELIM}", so a token cannot contain "{TOKEN_DELIM}".
  without a placeholder the default is {DEFAULT_TOKEN_PLACEHOLDER}. other characters are matched literally.

numbering:
  findings are sorted by file path, then line, then column, and numbered from 1.
  --fix rescans before applying, so numbers refer to the current files.
  if files changed since the report, run the report again before --fix N,M.

undo:
  --fix refuses files with unstaged changes. stage or commit them first;
  afterwards `git diff` shows exactly what changed and `git restore -- <path>` undoes it.

examples:
  scrub-personal-data.sh
  scrub-personal-data.sh docs --fix
  scrub-personal-data.sh --fix 1,3
"""


@dataclass
class Finding:
    path: str
    line: int  # 1-based; 0 for whole-file findings
    start: int
    end: int
    kind: str
    value: str
    replacement: str | None  # None means not rewritable

    def describe(self) -> str:
        if self.kind == "env":
            return f"{self.path}  env  tracked env file  (untrack or remove; not auto-fixed)"
        return f"{self.path}:{self.line}  {self.kind}  {self.value}  -> {self.replacement}"


def die(msg: str, code: int = 2) -> None:
    print(f"scrub-personal-data: {msg}", file=sys.stderr)
    sys.exit(code)


def warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr)


def run_git(root: Path | None, args: list[str]) -> bytes:
    cmd = ["git"] + (["-C", str(root)] if root else []) + args
    try:
        return subprocess.run(cmd, check=True, capture_output=True).stdout
    except FileNotFoundError:
        die("git is not installed")
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode(ENCODING, "replace").strip()
        die(f"git {args[0]} failed: {detail or exc.returncode}")


def split_z(out: bytes) -> list[str]:
    return [f for f in out.decode(ENCODING, ERRORS).split("\0") if f]


def git_root() -> Path:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except FileNotFoundError:
        die("git is not installed")
    except subprocess.CalledProcessError:
        die("not inside a git repository")
    return Path(out)


def to_pathspecs(root: Path, paths: list[str]) -> list[str]:
    specs = []
    for p in paths:
        try:
            specs.append(str(Path(p).resolve().relative_to(root)))
        except ValueError:
            die(f"path outside repository: {p}")
    return specs


def tracked_files(root: Path, pathspecs: list[str]) -> list[str]:
    return sorted(split_z(run_git(root, ["ls-files", "-z", "--", *pathspecs])))


def unstaged_files(root: Path, files: list[str]) -> set[str]:
    if not files:
        return set()
    return set(split_z(run_git(root, ["diff", "--name-only", "-z", "--", *files])))


def load_tokens(root: Path) -> list[tuple[str, str]]:
    path = root / TOKENS_REL
    if not path.exists():
        return []
    try:
        content = path.read_text(encoding=ENCODING)
    except (OSError, UnicodeDecodeError) as exc:
        die(f"cannot read {TOKENS_REL}: {exc}")
    tokens = []
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        token, sep, placeholder = line.partition(TOKEN_DELIM)
        token, placeholder = token.strip(), placeholder.strip()
        if not token:
            continue
        tokens.append((token, placeholder if sep and placeholder else DEFAULT_TOKEN_PLACEHOLDER))
    # Longest first so a full token wins over a shorter token it contains.
    tokens.sort(key=lambda t: len(t[0]), reverse=True)
    return tokens


def token_regex(token: str) -> re.Pattern[str]:
    return re.compile(r"(?<!\w)" + re.escape(token) + r"(?!\w)", re.IGNORECASE)


def is_personal_ip(text: str) -> bool:
    try:
        ip = ipaddress.IPv4Address(text)
    except ValueError:
        return False
    return any(ip in net for net in PERSONAL_NETWORKS)


def is_allowed_email(text: str) -> bool:
    local, _, domain = text.partition("@")
    domain = domain.lower()
    if local.lower() in EMAIL_ALLOW_LOCAL:
        return True
    return any(domain == d or domain.endswith("." + d) for d in EMAIL_ALLOW_DOMAINS)


def matches(rel: str, patterns: tuple[str, ...]) -> bool:
    name = Path(rel).name
    return any(fnmatch.fnmatch(name, pat) for pat in patterns)


def read_text(path: Path, rel: str) -> str | None:
    """Return file text, or None for binary (silent) and unreadable (warned) files."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        warn(f"skipped {rel}: {exc.strerror or exc}")
        return None
    if b"\0" in data[:8192]:
        return None
    return data.decode(ENCODING, ERRORS)


def scan_line(rel: str, lineno: int, line: str, patterns) -> list[Finding]:
    hits: list[Finding] = []
    for regex, placeholder in patterns:
        for m in regex.finditer(line):
            hits.append(Finding(rel, lineno, m.start(), m.end(), "token", m.group(), placeholder))
    for m in EMAIL_RE.finditer(line):
        if not is_allowed_email(m.group()):
            hits.append(Finding(rel, lineno, m.start(), m.end(), "email", m.group(), EMAIL_PLACEHOLDER))
    for m in IPV4_RE.finditer(line):
        if is_personal_ip(m.group()):
            hits.append(Finding(rel, lineno, m.start(), m.end(), "ip", m.group(), IP_PLACEHOLDER))

    # Drop overlaps: earliest start wins, then the longest span.
    hits.sort(key=lambda f: (f.start, -(f.end - f.start)))
    kept: list[Finding] = []
    last_end = -1
    for f in hits:
        if f.start >= last_end:
            kept.append(f)
            last_end = f.end
    return kept


def scan(root: Path, files: list[str], tokens) -> list[Finding]:
    patterns = [(token_regex(t), p) for t, p in tokens]
    findings: list[Finding] = []
    for rel in files:
        if matches(rel, SKIP_PATTERNS):
            continue
        if matches(rel, ENV_PATTERNS):
            findings.append(Finding(rel, 0, 0, 0, "env", "", None))
            continue
        text = read_text(root / rel, rel)
        if text is None:
            continue
        for lineno, line in enumerate(text.splitlines(keepends=True), start=1):
            findings.extend(scan_line(rel, lineno, line, patterns))
    findings.sort(key=lambda f: (f.path, f.line, f.start))
    return findings


def parse_selection(value: str, total: int) -> set[int]:
    if value == "all":
        return set(range(1, total + 1))
    if not FIX_SELECTION_RE.match(value):
        die(f"--fix expects numbers like 1,3 (got {value!r}); put paths before --fix")
    picked = {int(n) for n in value.split(",")}
    bad = sorted(n for n in picked if n < 1 or n > total)
    if bad:
        die(f"--fix numbers out of range 1..{total}: {','.join(map(str, bad))}")
    return picked


def apply_fixes(root: Path, selected: list[Finding]) -> list[str]:
    """Rewrite files in place; return the paths actually changed."""
    by_file: dict[str, list[Finding]] = {}
    for f in selected:
        by_file.setdefault(f.path, []).append(f)

    changed = []
    for rel, items in by_file.items():
        path = root / rel
        text = read_text(path, rel)
        if text is None:
            continue
        lines = text.splitlines(keepends=True)
        for f in sorted(items, key=lambda f: (f.line, f.start), reverse=True):
            lines[f.line - 1] = lines[f.line - 1][: f.start] + f.replacement + lines[f.line - 1][f.end :]
        try:
            with open(path, "w", encoding=ENCODING, errors=ERRORS, newline="") as fh:
                fh.write("".join(lines))
        except OSError as exc:
            warn(f"could not write {rel}: {exc.strerror or exc}")
            continue
        changed.append(rel)
    return changed


def main() -> int:
    sys.stdout.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(
        prog="scrub-personal-data.sh",
        description=(
            "Report personal data in git-tracked files as a numbered list. "
            "--fix replaces findings with placeholders."
        ),
        epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("paths", nargs="*", help="limit the scan to these paths (default: whole repo)")
    parser.add_argument(
        "--fix",
        nargs="?",
        const="all",
        metavar="N,M",
        help="replace every rewritable finding, or only the numbered ones (e.g. 1,3)",
    )
    args = parser.parse_args()

    root = git_root()
    files = tracked_files(root, to_pathspecs(root, args.paths))
    tokens = load_tokens(root)
    if not tokens:
        print(f"note: no tokens loaded; list usernames and hostnames in {TOKENS_REL} (see .example)")

    findings = scan(root, files, tokens)
    if not findings:
        print(f"clean: {len(files)} tracked file(s) scanned")
        return 0

    if args.fix is None:
        for i, f in enumerate(findings, start=1):
            print(f"[{i}] {f.describe()}")
        print(f"{len(findings)} finding(s). Fix: --fix  or  --fix 1,3")
        return 1

    picked = parse_selection(args.fix, len(findings))
    dirty = unstaged_files(root, sorted({findings[i - 1].path for i in picked}))
    selected = []
    for i, f in enumerate(findings, start=1):
        if i not in picked:
            continue
        if f.replacement is None:
            print(f"[{i}] refused: {f.describe()}")
        elif f.path in dirty:
            print(f"[{i}] refused: {f.path} has unstaged changes; stage or commit it first")
        else:
            print(f"[{i}] fix  {f.describe()}")
            selected.append(f)

    changed = apply_fixes(root, selected)
    remaining = scan(root, files, tokens)
    fixed = sum(1 for f in selected if f.path in changed)
    print(f"fixed {fixed} finding(s) in {len(changed)} file(s); {len(remaining)} remain")
    if changed:
        print("review: git diff -- " + " ".join(changed))
        print("undo:   git restore -- " + " ".join(changed))
    return 1 if remaining else 0


if __name__ == "__main__":
    sys.exit(main())
