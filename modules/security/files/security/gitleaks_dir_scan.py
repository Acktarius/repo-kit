#!/usr/bin/env python3
"""Run one prepared-directory Gitleaks scan and normalize its JSON report.

Supported platform is Linux with POSIX O_NOFOLLOW and resource.RLIMIT_FSIZE.
Supported tool contract is Gitleaks v8.30.1, commit
83d9cd684c87d95d656c1458ef04895a7f1cbd8e. The fixed command is `dir` with
built-in rules. This program does not search PATH, does not run a version
or help command, and does not accept a caller-supplied argument vector.

The executable digest is a SHA-256 of the file bytes compared with the
caller-supplied digest. It is not a signature and does not authenticate a
publisher. The caller-supplied version, rules identity, and other provenance
fields stay claims. Approval is not verified. Invoking this program is not
human approval.

Preflight rejects symlink entries, special files, `.git`, `.gitleaks.toml`,
and `.gitleaksignore`, and enforces the caller bounds. Preflight is not a
sandbox. A same-user process can change the snapshot after those checks.
This program does not enforce OS network confinement or OS filesystem
isolation. RLIMIT_FSIZE is a hard ceiling on regular-file writes by the
child. It does not bound pipe writes. Pipe bytes are retained only up to
the stream cap, then discarded while the process group is killed.

Raw scanner output may still contain secrets when redaction is on. It stays
in a private directory outside the snapshot. Cleanup removes that directory.
Cleanup is not secure erasure. If cleanup fails, this program does not
publish a handoff and reports cleanup failed.

The normalizer implementation is gitleaks_handoff.py in this directory.
A published handoff is a new file. Existing outputs are left in place.
The findings store is not written.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import importlib.util
import json
import os
import re
import resource
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_IO = 3
EXIT_TOOL = 4
EXIT_REPORT = 5
EXIT_LIMIT = 6

PROFILE = "gitleaks-dir-builtin-v8.30.1"
CONTRACT_VERSION = "v8.30.1"
CONTRACT_REVISION = "83d9cd684c87d95d656c1458ef04895a7f1cbd8e"

HARD_REPORT_BYTES = 1_048_576
MAX_TIMEOUT_SECONDS = 120
MAX_SNAPSHOT_FILES = 1000
MAX_SNAPSHOT_BYTES = 32 * 1024 * 1024
MAX_FILE_BYTES = 1_000_000
MAX_STREAM_BYTES = 65_536
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_REJECTED_NAMES = frozenset({".git", ".gitleaks.toml", ".gitleaksignore"})
_HANDOFF = None


class ScanFailure(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _StreamCap:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.retained = bytearray()
        self.overflow = threading.Event()

    def add(self, chunk: bytes) -> None:
        if self.overflow.is_set():
            return
        room = self.limit - len(self.retained)
        if len(chunk) <= room:
            self.retained += chunk
            return
        if room > 0:
            self.retained += chunk[:room]
        self.overflow.set()


def fixed_argv(executable: str, snapshot: str, report_path: str, ignore_path: str) -> list[str]:
    """Argument vector for the one supported directory mode."""
    return [
        executable,
        "dir",
        "--no-banner",
        "--redact=100",
        "--log-level",
        "error",
        "--report-format",
        "json",
        "--report-path",
        report_path,
        "--exit-code",
        "2",
        "--max-archive-depth",
        "0",
        "--max-decode-depth",
        "0",
        "--ignore-gitleaks-allow",
        "--gitleaks-ignore-path",
        ignore_path,
        "--max-target-megabytes",
        "1",
        snapshot,
    ]


def fixed_env(private_dir: str) -> dict[str, str]:
    """Allowlisted child environment. The host environment is not copied."""
    return {"TMPDIR": private_dir, "LANG": "C", "LC_ALL": "C"}


def _handoff_module():
    global _HANDOFF
    if _HANDOFF is not None:
        return _HANDOFF
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gitleaks_handoff.py")
    spec = importlib.util.spec_from_file_location("gitleaks_handoff_for_dir_scan", path)
    if spec is None or spec.loader is None:
        raise ScanFailure(EXIT_IO, "normalization failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _HANDOFF = module
    return module


def _lexical_absolute(path: str) -> str:
    if not isinstance(path, str) or path == "" or "\x00" in path or not path.startswith("/"):
        raise ScanFailure(EXIT_USAGE, "invalid arguments")
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts[1:]):
        raise ScanFailure(EXIT_USAGE, "invalid arguments")
    return path


def _contains(parent: str, child: str) -> bool:
    if parent == child:
        return True
    prefix = parent if parent.endswith("/") else parent + "/"
    return child.startswith(prefix)


def _require_platform() -> None:
    names = ("O_NOFOLLOW", "O_CLOEXEC", "O_EXCL")
    if os.name != "posix" or any(not hasattr(os, name) for name in names):
        raise ScanFailure(EXIT_IO, "required limits are unavailable")
    if not hasattr(resource, "RLIMIT_FSIZE") or not hasattr(resource, "RLIMIT_CPU"):
        raise ScanFailure(EXIT_IO, "required limits are unavailable")
    if not hasattr(signal, "SIGKILL"):
        raise ScanFailure(EXIT_IO, "required limits are unavailable")


def _bound(value: int, upper: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > upper:
        raise ScanFailure(EXIT_USAGE, "invalid arguments")
    return value


def _digest_file(path: str) -> str:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError:
        raise ScanFailure(EXIT_IO, "executable rejected") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o111 == 0:
            raise ScanFailure(EXIT_IO, "executable rejected")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        return digest.hexdigest()
    except ScanFailure:
        raise
    except OSError:
        raise ScanFailure(EXIT_IO, "executable rejected") from None
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def _ancestor_is(start: str, target: os.stat_result) -> bool:
    current = start
    seen: set[tuple[int, int]] = set()
    while True:
        try:
            info = os.lstat(current)
        except OSError:
            raise ScanFailure(EXIT_IO, "output rejected") from None
        if stat.S_ISLNK(info.st_mode):
            raise ScanFailure(EXIT_IO, "output rejected")
        ident = (info.st_dev, info.st_ino)
        if ident in seen:
            raise ScanFailure(EXIT_IO, "output rejected")
        seen.add(ident)
        if ident == (target.st_dev, target.st_ino):
            return True
        parent = os.path.dirname(current)
        if parent == current:
            return False
        current = parent


def _inspect_snapshot(snapshot: str, max_files: int, max_bytes: int) -> None:
    try:
        root_info = os.lstat(snapshot)
    except OSError:
        raise ScanFailure(EXIT_IO, "snapshot rejected") from None
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        raise ScanFailure(EXIT_IO, "snapshot rejected")
    files = 0
    total = 0
    stack = [snapshot]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as scanned:
                entries = list(scanned)
        except OSError:
            raise ScanFailure(EXIT_IO, "snapshot rejected") from None
        for entry in entries:
            try:
                if entry.is_symlink():
                    raise ScanFailure(EXIT_IO, "snapshot rejected")
                if entry.name in _REJECTED_NAMES:
                    raise ScanFailure(EXIT_IO, "snapshot rejected")
                if entry.is_dir(follow_symlinks=False):
                    stack.append(entry.path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    raise ScanFailure(EXIT_IO, "snapshot rejected")
                info = entry.stat(follow_symlinks=False)
            except ScanFailure:
                raise
            except OSError:
                raise ScanFailure(EXIT_IO, "snapshot rejected") from None
            if not stat.S_ISREG(info.st_mode):
                raise ScanFailure(EXIT_IO, "snapshot rejected")
            if info.st_size > MAX_FILE_BYTES:
                raise ScanFailure(EXIT_IO, "snapshot rejected")
            files += 1
            total += info.st_size
            if files > max_files or total > max_bytes:
                raise ScanFailure(EXIT_IO, "snapshot rejected")


def _prepare_output(output_parent: str, handoff_path: str, snapshot: str) -> os.stat_result:
    try:
        parent_info = os.lstat(output_parent)
        snap_info = os.lstat(snapshot)
    except OSError:
        raise ScanFailure(EXIT_IO, "output rejected") from None
    if stat.S_ISLNK(parent_info.st_mode) or not stat.S_ISDIR(parent_info.st_mode):
        raise ScanFailure(EXIT_IO, "output rejected")
    if _contains(snapshot, output_parent) or _contains(output_parent, snapshot):
        raise ScanFailure(EXIT_IO, "output rejected")
    if _ancestor_is(output_parent, snap_info) or _ancestor_is(snapshot, parent_info):
        raise ScanFailure(EXIT_IO, "output rejected")
    try:
        os.lstat(handoff_path)
    except FileNotFoundError:
        return snap_info
    except OSError:
        raise ScanFailure(EXIT_IO, "output rejected") from None
    raise ScanFailure(EXIT_IO, "output rejected")


def _limit_setter(timeout_seconds: int):
    def apply() -> None:
        resource.setrlimit(resource.RLIMIT_FSIZE, (HARD_REPORT_BYTES, HARD_REPORT_BYTES))
        resource.setrlimit(resource.RLIMIT_CPU, (timeout_seconds, timeout_seconds))

    return apply


def _kill_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except OSError:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            return


def _drain(fd: int, cap: _StreamCap, failed: list[bool]) -> None:
    try:
        while True:
            try:
                chunk = os.read(fd, 65536)
            except InterruptedError:
                continue
            if not chunk:
                return
            cap.add(chunk)
    except OSError:
        failed.append(True)


def _signal_name(code: int) -> int | None:
    if code < 0:
        return -code
    if code > 128:
        return code - 128
    return None


def _report_at_ceiling(path: str) -> bool:
    """True when a regular report reached the hard file-size ceiling.

    The check uses lstat and does not read or follow the path. A child can
    stop on EFBIG and exit on its own instead of dying from the signal.
    """
    try:
        info = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        return False
    return info.st_size >= HARD_REPORT_BYTES


def _read_report(path: str, limit: int) -> tuple[bytes, os.stat_result]:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        raise ScanFailure(EXIT_REPORT, "report missing") from None
    except OSError:
        raise ScanFailure(EXIT_REPORT, "report missing") from None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ScanFailure(EXIT_REPORT, "report missing")
    if info.st_size > limit or info.st_size > HARD_REPORT_BYTES:
        raise ScanFailure(EXIT_LIMIT, "report oversized")
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ScanFailure(EXIT_REPORT, "report missing") from None
        raise ScanFailure(EXIT_REPORT, "report missing") from None
    try:
        chunks: list[bytes] = []
        total = 0
        while total <= limit:
            try:
                chunk = os.read(fd, min(65536, limit + 1 - total))
            except InterruptedError:
                continue
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if total > limit:
            raise ScanFailure(EXIT_LIMIT, "report oversized")
        return b"".join(chunks), info
    except ScanFailure:
        raise
    except OSError:
        raise ScanFailure(EXIT_REPORT, "report missing") from None
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def _remove_tree(path: str | None) -> bool:
    if path is None:
        return True
    try:
        shutil.rmtree(path)
    except OSError:
        return False
    return not os.path.lexists(path)


def _store_capped(private_dir: str, name: str, data: bytes) -> None:
    path = os.path.join(private_dir, name)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except OSError:
        return
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                return
            view = view[written:]
        os.fchmod(fd, 0o600)
    except OSError:
        return
    finally:
        try:
            os.close(fd)
        except OSError:
            return


def _claims(args: argparse.Namespace) -> dict[str, str]:
    handoff = _handoff_module()
    try:
        return {
            "checkId": handoff._check_id(args.check_id),
            "sourceRevision": handoff._claim(args.source_revision),
            "workingTree": handoff._claim(args.working_tree),
            "toolVersion": handoff._claim(args.tool_version),
            "rulesIdentity": handoff._claim(args.rules_identity),
            "reportProvenance": handoff._claim(args.report_provenance),
            "scannerOutcome": "completed",
        }
    except handoff.HandoffError:
        raise ScanFailure(EXIT_USAGE, "invalid arguments") from None


def _run(args: argparse.Namespace) -> int:
    _require_platform()
    executable = _lexical_absolute(args.executable)
    snapshot = _lexical_absolute(args.snapshot)
    output_parent = _lexical_absolute(args.output_parent)
    if not _NAME.fullmatch(args.handoff_name):
        raise ScanFailure(EXIT_USAGE, "invalid arguments")
    supplied = args.executable_sha256.lower()
    if not _DIGEST.fullmatch(supplied):
        raise ScanFailure(EXIT_USAGE, "invalid arguments")
    timeout = _bound(args.timeout_seconds, MAX_TIMEOUT_SECONDS)
    max_files = _bound(args.max_snapshot_files, MAX_SNAPSHOT_FILES)
    max_bytes = _bound(args.max_snapshot_bytes, MAX_SNAPSHOT_BYTES)
    max_report = _bound(args.max_report_bytes, HARD_REPORT_BYTES)
    max_stream = _bound(args.max_stream_bytes, MAX_STREAM_BYTES)
    claims = _claims(args)
    observed = _digest_file(executable)
    if observed != supplied:
        raise ScanFailure(EXIT_IO, "executable digest mismatch")
    if _contains(snapshot, executable):
        raise ScanFailure(EXIT_IO, "snapshot rejected")
    _inspect_snapshot(snapshot, max_files, max_bytes)
    handoff_path = output_parent + "/" + args.handoff_name
    _prepare_output(output_parent, handoff_path, snapshot)

    try:
        private = tempfile_dir(output_parent)
    except OSError:
        raise ScanFailure(EXIT_IO, "output rejected") from None
    failure: ScanFailure | None = None
    payload: bytes | None = None
    report_info: os.stat_result | None = None
    report_bytes = 0
    tool_exit = None
    started = time.monotonic()
    try:
        report_path = private + "/report.json"
        ignore_path = private + "/absent-gitleaksignore"
        argv = fixed_argv(executable, snapshot, report_path, ignore_path)
        env = fixed_env(private)
        stdout_cap = _StreamCap(max_stream)
        stderr_cap = _StreamCap(max_stream)
        drain_failed: list[bool] = []
        try:
            proc = subprocess.Popen(
                argv,
                cwd=private,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                start_new_session=True,
                preexec_fn=_limit_setter(timeout),
            )
        except (OSError, subprocess.SubprocessError):
            raise ScanFailure(EXIT_IO, "spawn failed") from None
        if proc.stdout is None or proc.stderr is None:
            _kill_group(proc.pid)
            proc.wait(timeout=5)
            raise ScanFailure(EXIT_IO, "spawn failed")
        threads = [
            threading.Thread(target=_drain, args=(proc.stdout.fileno(), stdout_cap, drain_failed)),
            threading.Thread(target=_drain, args=(proc.stderr.fileno(), stderr_cap, drain_failed)),
        ]
        for thread in threads:
            thread.start()
        deadline = started + timeout
        requested = None
        try:
            while proc.poll() is None:
                if stdout_cap.overflow.is_set() or stderr_cap.overflow.is_set():
                    requested = "stream limit"
                    _kill_group(proc.pid)
                    break
                if time.monotonic() >= deadline:
                    requested = "timeout"
                    _kill_group(proc.pid)
                    break
                time.sleep(0.02)
            try:
                tool_exit = proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _kill_group(proc.pid)
                try:
                    tool_exit = proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    tool_exit = None
                    if requested is None:
                        requested = "tool failure"
        finally:
            for thread in threads:
                thread.join(timeout=5)
            for pipe in (proc.stdout, proc.stderr):
                try:
                    pipe.close()
                except OSError:
                    pass
        elapsed_ms = int((time.monotonic() - started) * 1000)
        _store_capped(private, "stdout.log", bytes(stdout_cap.retained))
        _store_capped(private, "stderr.log", bytes(stderr_cap.retained))
        if drain_failed or any(thread.is_alive() for thread in threads):
            failure = ScanFailure(EXIT_TOOL, "tool failure")
        elif stdout_cap.overflow.is_set() or stderr_cap.overflow.is_set():
            failure = ScanFailure(EXIT_LIMIT, "stream limit")
        elif requested == "timeout":
            failure = ScanFailure(EXIT_LIMIT, "timeout")
        elif requested == "tool failure":
            failure = ScanFailure(EXIT_TOOL, "tool failure")
        else:
            signum = _signal_name(tool_exit if tool_exit is not None else 1)
            if signum == getattr(signal, "SIGXFSZ", -1) or _report_at_ceiling(report_path):
                failure = ScanFailure(EXIT_LIMIT, "file size limit")
            elif signum == getattr(signal, "SIGXCPU", -1):
                failure = ScanFailure(EXIT_LIMIT, "timeout")
            elif tool_exit not in (0, 2):
                failure = ScanFailure(EXIT_TOOL, "tool failure")
            else:
                try:
                    raw, report_info = _read_report(report_path, max_report)
                    report_bytes = len(raw)
                    handoff = _handoff_module()
                    payload = handoff.build_handoff(raw, claims)
                    document = json.loads(payload.decode("utf-8"))
                    records = document["counts"]["records"]
                    if (tool_exit == 0 and records != 0) or (tool_exit == 2 and records == 0):
                        failure = ScanFailure(EXIT_TOOL, "outcome mismatch")
                        payload = None
                except ScanFailure as exc:
                    failure = exc
                    payload = None
                except handoff.HandoffError as exc:
                    payload = None
                    if exc.code == handoff.EXIT_LIMIT:
                        failure = ScanFailure(EXIT_LIMIT, "report oversized")
                    elif exc.code in (handoff.EXIT_MALFORMED, handoff.EXIT_UNSUPPORTED):
                        failure = ScanFailure(EXIT_REPORT, "report malformed")
                    else:
                        failure = ScanFailure(EXIT_REPORT, "normalization failed")
                except (UnicodeError, KeyError, TypeError, json.JSONDecodeError):
                    payload = None
                    failure = ScanFailure(EXIT_REPORT, "normalization failed")
        if failure is not None:
            raise failure
        if payload is None or report_info is None or tool_exit not in (0, 2):
            raise ScanFailure(EXIT_REPORT, "normalization failed")
        if not _remove_tree(private):
            raise ScanFailure(EXIT_IO, "cleanup failed")
        private = None
        handoff = _handoff_module()
        try:
            handoff._write_output(handoff_path, payload, report_info, report_path)
        except handoff.HandoffError:
            raise ScanFailure(EXIT_IO, "publication failed") from None
        status = {
            "schemaVersion": 1,
            "launcher": "gitleaks-dir-scan",
            "profile": PROFILE,
            "contractVersion": CONTRACT_VERSION,
            "contractRevision": CONTRACT_REVISION,
            "process": "exited",
            "toolExit": tool_exit,
            "toolDetection": "none" if tool_exit == 0 else "findings",
            "normalization": "published",
            "publication": "created",
            "cleanup": "removed",
            "observed": {
                "executableSha256": observed,
                "elapsedMilliseconds": elapsed_ms,
                "reportBytes": report_bytes,
            },
            "callerClaimsVerified": False,
            "approvalVerified": False,
            "isolationEnforced": False,
            "networkConfined": False,
            "preflightIsASandbox": False,
            "cleanupIsSecureErasure": False,
            "executableDigestAuthenticatesPublisher": False,
        }
        sys.stdout.write(json.dumps(status, indent=2, sort_keys=True) + "\n")
        return EXIT_OK
    except ScanFailure as exc:
        removed = _remove_tree(private)
        if not removed:
            raise ScanFailure(EXIT_IO, "cleanup failed") from None
        raise


def tempfile_dir(parent: str) -> str:
    path = tempfile_mkdtemp(parent)
    os.chmod(path, 0o700)
    return path


def tempfile_mkdtemp(parent: str) -> str:
    import tempfile

    return tempfile.mkdtemp(prefix=".gitleaks-dir-scan-", dir=parent)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gitleaks_dir_scan.py", add_help=True)
    parser.add_argument("--executable", required=True)
    parser.add_argument("--executable-sha256", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--output-parent", required=True)
    parser.add_argument("--handoff-name", required=True)
    parser.add_argument("--check-id", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--working-tree", required=True)
    parser.add_argument("--tool-version", required=True)
    parser.add_argument("--rules-identity", required=True)
    parser.add_argument("--report-provenance", required=True)
    parser.add_argument("--timeout-seconds", required=True, type=int)
    parser.add_argument("--max-snapshot-files", required=True, type=int)
    parser.add_argument("--max-snapshot-bytes", required=True, type=int)
    parser.add_argument("--max-report-bytes", required=True, type=int)
    parser.add_argument("--max-stream-bytes", required=True, type=int)

    def reject(_message: str) -> None:
        print("gitleaks-dir-scan: invalid arguments", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)

    parser.error = reject  # type: ignore[method-assign]
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        return _run(args)
    except ScanFailure as exc:
        print(f"gitleaks-dir-scan: {exc.message}", file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
