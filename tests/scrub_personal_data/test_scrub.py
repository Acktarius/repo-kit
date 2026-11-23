"""Black-box tests for scrub-personal-data.sh against throwaway git repos."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "modules" / "base" / "files" / ".repo-kit" / "scripts"


class ScrubTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        scripts = self.repo / ".repo-kit" / "scripts"
        scripts.mkdir(parents=True)
        for name in ("scrub-personal-data.sh", "scrub-personal-data.py"):
            shutil.copy2(SCRIPTS / name, scripts / name)
        self.launcher = scripts / "scrub-personal-data.sh"

    def tearDown(self) -> None:
        for p in self.tmp.rglob("*"):
            if not p.is_symlink():
                p.chmod(0o700 if p.is_dir() else 0o600)
        shutil.rmtree(self.tmp)

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.repo), *args], check=True, capture_output=True, text=True
        ).stdout

    def write(self, rel: str, content: str | bytes, add: bool = True) -> Path:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_bytes(content.encode())
        if add:
            self.git("add", "--", rel)
        return path

    def tokens(self, content: str) -> None:
        self.write(".repo-kit/personal-tokens.txt", content, add=False)

    def run_scrub(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run(
            [str(self.launcher), *args],
            cwd=cwd or self.repo,
            capture_output=True,
            text=True,
            env=env,
        )

    def findings(self, out: str) -> list[str]:
        return [line for line in out.splitlines() if line.startswith("[")]


class ReportTests(ScrubTestCase):
    def test_not_a_git_repo(self) -> None:
        outside = self.tmp / "plain"
        outside.mkdir()
        r = self.run_scrub(cwd=outside)
        self.assertEqual(r.returncode, 2)
        self.assertIn("not inside a git repository", r.stderr)

    def test_empty_repo_is_clean(self) -> None:
        shutil.rmtree(self.repo / ".repo-kit")
        shutil.copytree(SCRIPTS, self.tmp / "scripts")
        self.launcher = self.tmp / "scripts" / "scrub-personal-data.sh"
        r = self.run_scrub()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("clean: 0 tracked file(s)", r.stdout)

    def test_missing_tokens_file_is_a_note(self) -> None:
        self.write("a.md", "nothing here\n")
        r = self.run_scrub()
        self.assertEqual(r.returncode, 0)
        self.assertIn("note: no tokens loaded", r.stdout)

    def test_allowed_values_are_not_reported(self) -> None:
        self.write(
            "a.md",
            "loopback 127.0.0.1 and 127.1.2.3\n"
            "public 8.8.8.8, docs 192.0.2.1 198.51.100.7 203.0.113.9\n"
            "version 10.0.0.1.2 and 1.2.3.4\n"
            "edge 172.15.0.1 172.32.0.1 0.0.0.0\n"
            "git@github.com user@example.com 1+x@users.noreply.github.com\n",
        )
        r = self.run_scrub()
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_private_ranges_and_link_local(self) -> None:
        self.write("a.md", "10.1.2.3 172.16.0.1 172.31.255.255 192.168.8.124 169.254.1.1.\n")
        r = self.run_scrub()
        self.assertEqual(r.returncode, 1)
        values = [line.split()[3] for line in self.findings(r.stdout)]
        self.assertEqual(values, ["10.1.2.3", "172.16.0.1", "172.31.255.255", "192.168.8.124", "169.254.1.1"])

    def test_order_is_path_then_line_then_column(self) -> None:
        self.write("b.md", "x 10.0.0.2\n")
        self.write("a.md", "bob@corp.io then 10.0.0.1\nline2 192.168.0.1\n")
        r = self.run_scrub()
        self.assertEqual(
            self.findings(r.stdout),
            [
                "[1] a.md:1  email  bob@corp.io  -> <email>",
                "[2] a.md:1  ip  10.0.0.1  -> <ip-address>",
                "[3] a.md:2  ip  192.168.0.1  -> <ip-address>",
                "[4] b.md:1  ip  10.0.0.2  -> <ip-address>",
            ],
        )

    def test_tokens_whole_word_case_insensitive(self) -> None:
        self.tokens("# comment\n\nJohn -> <your-user-name>\nmy-box\n")
        self.write("a.md", "username = john\nJohnson stays\nhost MY-BOX up\n")
        r = self.run_scrub()
        self.assertEqual(
            self.findings(r.stdout),
            [
                "[1] a.md:1  token  john  -> <your-user-name>",
                "[2] a.md:3  token  MY-BOX  -> <redacted>",
            ],
        )

    def test_token_splits_on_first_arrow_and_escapes_regex(self) -> None:
        self.tokens("a.b->x -> y\n")
        self.write("a.md", "aXb a.b\n")
        r = self.run_scrub()
        self.assertEqual(self.findings(r.stdout), ["[1] a.md:1  token  a.b  -> x -> y"])

    def test_longer_token_wins_overlap(self) -> None:
        self.tokens("john\njohn.doe -> <full>\n")
        self.write("a.md", "john.doe@corp.io\n")
        r = self.run_scrub()
        self.assertEqual(len(self.findings(r.stdout)), 1)
        self.assertIn("email  john.doe@corp.io", r.stdout)

    def test_tracked_env_reported_not_scanned(self) -> None:
        self.write(".env", "HOST=10.0.0.1\n")
        self.write("conf/prod.env", "x\n")
        r = self.run_scrub()
        self.assertEqual(r.returncode, 1)
        lines = self.findings(r.stdout)
        self.assertEqual(len(lines), 2)
        self.assertTrue(all("tracked env file" in line for line in lines))

    def test_package_lock_skipped(self) -> None:
        self.write("package-lock.json", '{"resolved": "http://10.0.0.1/x", "author": "bob@corp.io"}\n')
        self.write("web/package-lock.json", '{"host": "192.168.0.1"}\n')
        self.assertEqual(self.run_scrub().returncode, 0)

    def test_untracked_files_ignored(self) -> None:
        self.write("a.md", "10.0.0.1\n", add=False)
        self.assertEqual(self.run_scrub().returncode, 0)

    def test_path_argument_limits_scope(self) -> None:
        self.write("docs/a.md", "10.0.0.1\n")
        self.write("src/b.md", "10.0.0.2\n")
        r = self.run_scrub("docs")
        self.assertEqual(self.findings(r.stdout), ["[1] docs/a.md:1  ip  10.0.0.1  -> <ip-address>"])

    def test_binary_skipped_unreadable_warned(self) -> None:
        self.write("bin.dat", b"\x00\x01 10.0.0.1")
        locked = self.write("locked.md", "10.0.0.1\n")
        locked.chmod(0)
        if os.access(locked, os.R_OK):
            self.skipTest("running as a user that ignores file permissions")
        self.write("ok.md", "10.0.0.3\n")
        r = self.run_scrub()
        self.assertIn("warning: skipped locked.md", r.stderr)
        self.assertEqual(self.findings(r.stdout), ["[1] ok.md:1  ip  10.0.0.3  -> <ip-address>"])


class FixTests(ScrubTestCase):
    def test_fix_selected_only(self) -> None:
        self.tokens("John -> <your-user-name>\n")
        path = self.write("a.md", "node 192.168.8.124\nusername = John\nmail bob@corp.io\n")
        r = self.run_scrub("--fix", "1,3")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(path.read_text(), "node <ip-address>\nusername = John\nmail <email>\n")
        self.assertIn("undo:   git restore -- a.md", r.stdout)

    def test_fix_all_then_clean(self) -> None:
        self.tokens("John -> <your-user-name>\n")
        path = self.write("a.md", "node 192.168.8.124 and 10.0.0.1\nusername = John\n")
        r = self.run_scrub("--fix")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(path.read_text(), "node <ip-address> and <ip-address>\nusername = <your-user-name>\n")
        self.assertEqual(self.run_scrub().returncode, 0)

    def test_fix_path_before_flag(self) -> None:
        a = self.write("docs/a.md", "10.0.0.1\n")
        b = self.write("src/b.md", "10.0.0.2\n")
        self.run_scrub("docs", "--fix")
        self.assertEqual(a.read_text(), "<ip-address>\n")
        self.assertEqual(b.read_text(), "10.0.0.2\n")

    def test_bad_selection(self) -> None:
        self.write("a.md", "10.0.0.1\n")
        r = self.run_scrub("--fix", "docs")
        self.assertEqual(r.returncode, 2)
        self.assertIn("put paths before --fix", r.stderr)
        r = self.run_scrub("--fix", "2")
        self.assertEqual(r.returncode, 2)
        self.assertIn("out of range", r.stderr)

    def test_env_refused(self) -> None:
        path = self.write(".env", "HOST=10.0.0.1\n")
        r = self.run_scrub("--fix")
        self.assertEqual(r.returncode, 1)
        self.assertIn("refused", r.stdout)
        self.assertEqual(path.read_text(), "HOST=10.0.0.1\n")

    def test_unstaged_file_refused_then_undo_with_git(self) -> None:
        path = self.write("a.md", "v1\n")
        path.write_text("v2 10.0.0.1\n")
        r = self.run_scrub("--fix")
        self.assertEqual(r.returncode, 1)
        self.assertIn("unstaged changes", r.stdout)
        self.assertEqual(path.read_text(), "v2 10.0.0.1\n")

        self.git("add", "a.md")
        self.assertEqual(self.run_scrub("--fix").returncode, 0)
        self.assertEqual(path.read_text(), "v2 <ip-address>\n")
        self.git("restore", "--", "a.md")
        self.assertEqual(path.read_text(), "v2 10.0.0.1\n")

    def test_preserves_non_utf8_bytes_and_crlf(self) -> None:
        path = self.write("a.md", b"caf\xe9\r\nip 10.0.0.1\r\n")
        self.assertEqual(self.run_scrub("--fix").returncode, 0)
        self.assertEqual(path.read_bytes(), b"caf\xe9\r\nip <ip-address>\r\n")


if __name__ == "__main__":
    unittest.main()
