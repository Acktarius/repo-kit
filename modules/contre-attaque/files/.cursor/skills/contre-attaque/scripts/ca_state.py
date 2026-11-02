"""contre-attaque state: layout, locking, atomic writes, validation, evidence, reuse policy."""
from __future__ import annotations

import base64
import contextlib
import fcntl
import hashlib
import json
import os
import re
import socket
import subprocess
import time
from datetime import datetime, timedelta
from typing import Any, Iterator

from ca_intel import iso, parse_ts

STATE_SCHEMA_VERSION = 1
STATE_REL = os.path.join(".repo-kit", "contre-attaque")
GITIGNORE_BODY = "# contre-attaque local working data (see docs/contre-attaque.md)\n*\n!.gitignore\n"
LOCK_TIMEOUT_SECONDS = 120
MAX_CACHE_AGE_DAYS = 30
MAX_ITEMS_PER_RUN = 25
STALE_RUN_HOURS = 24
MAX_EXCERPT_LINES = 20
MAX_EXCERPT_CHARS = 2000
APPLICABILITY = ("affected", "not_affected", "fixed", "under_investigation")
JUSTIFICATIONS = (
    "component_not_present",
    "vulnerable_code_not_present",
    "vulnerable_code_not_in_execute_path",
    "vulnerable_code_cannot_be_controlled_by_adversary",
    "inline_mitigations_already_exist",
)


class StateError(Exception):
    pass


# ---------------------------------------------------------------------------
# Layout and atomic IO
# ---------------------------------------------------------------------------

def state_dir(root: str) -> str:
    return os.path.join(root, STATE_REL)


def ensure_layout(root: str) -> str:
    base = state_dir(root)
    for sub in ("", "runs", "evidence", "imports"):
        os.makedirs(os.path.join(base, sub), exist_ok=True)
    gi = os.path.join(base, ".gitignore")
    if not os.path.exists(gi):
        write_text_atomic(gi, GITIGNORE_BODY)
    return base


def write_text_atomic(path: str, text: str) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}.{time.monotonic_ns()}"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.lexists(tmp):
            os.unlink(tmp)


def write_json_atomic(path: str, data: Any) -> None:
    write_text_atomic(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _no_dup_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in pairs:
        if k in out:
            raise StateError(f"duplicate JSON key {k!r}")
        out[k] = v
    return out


def load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh, object_pairs_hook=_no_dup_keys)


@contextlib.contextmanager
def locked(root: str, timeout: float = LOCK_TIMEOUT_SECONDS) -> Iterator[None]:
    """Exclusive inter-process lock for every state or findings mutation."""
    path = os.path.join(ensure_layout(root), ".lock")
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise StateError(f"timed out after {timeout}s waiting for {path}")
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------
# Minimal JSON Schema validation (keyword subset; unknown keywords fail closed)
# ---------------------------------------------------------------------------

_ANNOTATIONS = {"$schema", "$id", "title", "description", "default", "format", "$comment"}
_KEYWORDS = {"type", "const", "enum", "required", "properties", "additionalProperties",
             "items", "pattern", "minimum", "minItems"}


def _type_ok(value: Any, typ: str) -> bool:
    return {
        "null": value is None,
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "string": isinstance(value, str),
        "array": isinstance(value, list),
        "object": isinstance(value, dict),
    }[typ]


def validate_schema(value: Any, schema: dict[str, Any], label: str = "$") -> None:
    unknown = set(schema) - _KEYWORDS - _ANNOTATIONS
    if unknown:
        raise StateError(f"schema at {label} uses unsupported keywords {sorted(unknown)}")
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(value, t) for t in types):
            raise StateError(f"{label}: expected {'|'.join(types)}, got {type(value).__name__}")
    if "const" in schema and value != schema["const"]:
        raise StateError(f"{label}: must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise StateError(f"{label}: {value!r} not in {schema['enum']!r}")
    if isinstance(value, str) and "pattern" in schema and not re.search(schema["pattern"], value):
        raise StateError(f"{label}: {value!r} does not match {schema['pattern']!r}")
    if _type_ok(value, "number") and "minimum" in schema and value < schema["minimum"]:
        raise StateError(f"{label}: below minimum {schema['minimum']}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                raise StateError(f"{label}: missing required field {key!r}")
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key, sub in value.items():
            if key in props:
                validate_schema(sub, props[key], f"{label}.{key}")
            elif extra is False:
                raise StateError(f"{label}: unexpected field {key!r}")
            elif isinstance(extra, dict):
                validate_schema(sub, extra, f"{label}.{key}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise StateError(f"{label}: needs at least {schema['minItems']} item(s)")
        for i, item in enumerate(value):
            if "items" in schema:
                validate_schema(item, schema["items"], f"{label}[{i}]")


_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "references", "state.schema.json")


def state_schema() -> dict[str, Any]:
    return load_json(_SCHEMA_PATH)


# ---------------------------------------------------------------------------
# State document
# ---------------------------------------------------------------------------

def empty_state(now: datetime) -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "created_at_utc": iso(now),
        "runs": [],
        "checkpoints": {"osv": None, "nvd": None, "kev": None},
        "candidates": {},
        "assessments": {},
        "stale": {},
        "queue": [],
        "evidence": {},
        "findings": {},
    }


def state_path(root: str) -> str:
    return os.path.join(state_dir(root), "state.json")


def load_state(root: str, now: datetime) -> dict[str, Any]:
    path = state_path(root)
    if not os.path.exists(path):
        return empty_state(now)
    try:
        state = load_json(path)
    except (OSError, ValueError) as exc:
        raise StateError(f"cannot read {path}: {exc}; restore it or move it aside") from exc
    if not isinstance(state, dict) or state.get("schema_version") != STATE_SCHEMA_VERSION:
        raise StateError(f"{path}: unsupported schema_version {state.get('schema_version')!r}")
    state.setdefault("stale", {})
    validate_schema(state, state_schema(), "state")
    return state


def save_state(root: str, state: dict[str, Any]) -> None:
    validate_schema(state, state_schema(), "state")
    write_json_atomic(state_path(root), state)


def find_run(state: dict[str, Any], run_id: str) -> dict[str, Any]:
    for run in state["runs"]:
        if run["run_id"] == run_id:
            return run
    raise StateError(f"unknown run {run_id!r}")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def interrupt(run: dict[str, Any], now: datetime, reason: str) -> None:
    run["outcome"] = "interrupted"
    run["completed_at_utc"] = None
    run["interrupted_detected_at_utc"] = iso(now)
    run["interrupted_reason"] = reason


def recover_interrupted(state: dict[str, Any], now: datetime) -> list[str]:
    """Mark runs that died mid-flight as interrupted. Their queue items stay queued.

    A run spans many helper invocations, so after its worklist is issued it stays
    active until finish/abandon; only the collecting phase is tied to a process.
    """
    host = socket.gethostname()
    recovered = []
    for run in state["runs"]:
        if run["outcome"] != "running":
            continue
        started = parse_ts(run["started_at_utc"])
        too_old = started is not None and now - started > timedelta(hours=STALE_RUN_HOURS)
        dead = (run.get("phase") != "assessing" and run.get("host") == host
                and not _pid_alive(int(run.get("pid") or 0)))
        if dead or too_old:
            interrupt(run, now, "start process exited before issuing a worklist" if dead
                      else f"no finish within {STALE_RUN_HOURS} hours")
            recovered.append(run["run_id"])
    return recovered


def active_run(state: dict[str, Any]) -> dict[str, Any] | None:
    return next((r for r in state["runs"] if r["outcome"] == "running"), None)


# ---------------------------------------------------------------------------
# Git and file evidence
# ---------------------------------------------------------------------------

TOOL_OWNED_FILES = ("security/findings-reviewed.json", "security/accepted-risks.md", "security/threat-model.md")


def tool_owned(path: str) -> bool:
    """Review records and repo-kit working data; edits to them are not source changes."""
    return path.startswith(".repo-kit/") or path in TOOL_OWNED_FILES


def _git(root: str, *args: str) -> str | None:
    try:
        proc = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


def git_info(root: str) -> dict[str, Any]:
    """Commit, dirty paths, and a source fingerprint covering every tracked and
    untracked (non-ignored) file outside tool-owned paths. None when git is unavailable."""
    commit = (_git(root, "rev-parse", "HEAD") or "").strip() or None
    branch = (_git(root, "rev-parse", "--abbrev-ref", "HEAD") or "").strip() or None
    porcelain = _git(root, "status", "--porcelain", "-z", "--untracked-files=all")
    index = _git(root, "ls-files", "-s", "-z")
    dirty: list[str] = []
    entries = (porcelain or "").split("\0")
    i = 0
    while i < len(entries):
        rec = entries[i]
        i += 1
        if len(rec) < 4:
            continue
        if rec[0] in "RC":
            i += 1
        if not tool_owned(rec[3:]):
            dirty.append(rec[3:])
    dirty.sort()
    h = hashlib.sha256()
    for path in dirty:
        h.update(f"{path}\0{file_sha256(root, path) or 'absent'}\0".encode())
    source_fp = None
    if porcelain is not None and index is not None:
        blobs: dict[str, str] = {}
        for rec in index.split("\0"):
            if "\t" in rec:
                meta, path = rec.split("\t", 1)
                blobs[path] = meta.split()[1]
        for path in dirty:
            blobs[path] = "worktree:" + (file_sha256(root, path) or "absent")
        s = hashlib.sha256()
        for path in sorted(p for p in blobs if not tool_owned(p)):
            s.update(f"{path}\0{blobs[path]}\0".encode())
        source_fp = s.hexdigest()
    return {
        "commit": commit,
        "branch": branch,
        "dirty_paths": dirty[:200],
        "dirty_count": len(dirty),
        "dirty_fingerprint": h.hexdigest() if dirty else None,
        "source_fingerprint": source_fp,
        "note": None if commit else "not a git checkout or git unavailable; source commit unknown",
    }


def safe_repo_path(root: str, rel: str) -> str:
    if "\x00" in rel or os.path.isabs(rel):
        raise StateError(f"evidence path must be repository-relative: {rel!r}")
    full = os.path.realpath(os.path.join(root, rel))
    real_root = os.path.realpath(root)
    if os.path.commonpath([full, real_root]) != real_root:
        raise StateError(f"evidence path escapes the repository: {rel!r}")
    return full


def file_sha256(root: str, rel: str) -> str | None:
    try:
        full = safe_repo_path(root, rel)
    except StateError:
        return None
    if not os.path.isfile(full):
        return None
    h = hashlib.sha256()
    with open(full, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


_SECRET_PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|$)", re.DOTALL),
     "[REDACTED PRIVATE KEY]"),
    (re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED AWS KEY]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[REDACTED GITHUB TOKEN]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), "[REDACTED SLACK TOKEN]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), "[REDACTED JWT]"),
    (re.compile(r"(?i)\b([A-Za-z0-9_.-]*(password|passwd|secret|token|api[_-]?key|private[_-]?key)[A-Za-z0-9_.-]*)"
                r"(\s*[:=]\s*)(['\"]?)[^\s'\"]{4,}\4"), r"\1\3\4[REDACTED]\4"),
    (re.compile(r"(?i)(://[^/\s:@]+:)[^@\s/]+@"), r"\1[REDACTED]@"),
]


def redact(text: str) -> str:
    for pattern, repl in _SECRET_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def file_evidence(root: str, ref: str) -> dict[str, Any]:
    """Parse 'path', 'path:12' or 'path:12-30' into a hashed, redacted evidence entry."""
    m = re.match(r"^(.+?)(?::(\d+)(?:-(\d+))?)?$", ref)
    rel, start, end = m.group(1), m.group(2), m.group(3)
    full = safe_repo_path(root, rel)
    if not os.path.isfile(full):
        raise StateError(f"evidence file not found: {rel}")
    sha = file_sha256(root, rel)
    excerpt = None
    if start:
        a = int(start)
        b = min(int(end or start), a + MAX_EXCERPT_LINES - 1)
        with open(full, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
        if a < 1 or a > len(lines):
            raise StateError(f"{rel}: line {a} outside file ({len(lines)} lines)")
        excerpt = redact("\n".join(lines[a - 1:b]))[:MAX_EXCERPT_CHARS]
    return {"kind": "file", "path": os.path.normpath(rel), "line_start": int(start) if start else None,
            "line_end": int(end) if end else (int(start) if start else None), "sha256": sha, "excerpt": excerpt}


def store_evidence(root: str, data: bytes, meta: dict[str, Any]) -> str:
    """Content-addressed evidence file; returns the sha256 used as evidence ID."""
    sha = hashlib.sha256(data).hexdigest()
    path = os.path.join(ensure_layout(root), "evidence", f"{sha}.json")
    if not os.path.exists(path):
        try:
            body: Any = {"encoding": "utf-8", "text": data.decode("utf-8")}
        except UnicodeDecodeError:
            body = {"encoding": "base64", "text": base64.b64encode(data).decode()}
        record = {"sha256": sha, "stored_at_utc": meta.get("at_utc"),
                  "request": {k: meta.get(k) for k in ("provider", "method", "url", "status", "at_utc", "request_sha256")},
                  "body": body}
        write_json_atomic(path, record)
    return sha


def evidence_exists(root: str, sha: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", sha)) and os.path.isfile(
        os.path.join(state_dir(root), "evidence", f"{sha}.json"))


# ---------------------------------------------------------------------------
# Reuse policy and assessment queue
# ---------------------------------------------------------------------------

def code_dependent(assessment: dict[str, Any]) -> bool:
    """Decisions whose reasoning depends on repository code, not only on versions."""
    if assessment["applicability"] == "affected":
        return True
    return assessment["applicability"] == "not_affected" and assessment.get("justification") != "component_not_present"


def reuse_check(
    assessment: dict[str, Any] | None,
    candidate: dict[str, Any],
    root: str,
    now: datetime,
    kev_known: bool,
    source_fingerprint: str | None,
) -> list[str]:
    """Return reasons the stored decision cannot be reused; [] means reusable.

    Any change to the advisory, exploitation status, cited code/config, any
    source file (for code-dependent decisions), the component, or deployment
    evidence invalidates immediately. Age is only an upper bound.
    """
    if assessment is None:
        return ["not assessed yet"]
    reasons = []
    if code_dependent(assessment):
        if source_fingerprint is None or assessment.get("source_fingerprint") is None:
            reasons.append("source snapshot unavailable; code-dependent decision cannot be reused")
        elif assessment["source_fingerprint"] != source_fingerprint:
            reasons.append("repository source changed since this code-dependent decision")
    if assessment["applicability"] == "under_investigation":
        reasons.append("under_investigation is never cached")
    if candidate.get("advisory_revision") and assessment.get("advisory_revision") != candidate["advisory_revision"]:
        reasons.append("advisory revision changed")
    if assessment.get("component_fingerprint") != candidate.get("component_fingerprint"):
        reasons.append("component version or evidence tier changed")
    if assessment.get("deployment_fingerprint") != candidate.get("deployment_fingerprint"):
        reasons.append("runtime, image, SBOM, or deployment configuration changed")
    if not kev_known:
        reasons.append("exploitation status unknown this run (KEV not collected)")
    elif bool(assessment.get("kev_listed")) != bool(candidate.get("kev")):
        reasons.append("KEV exploitation status changed")
    for ev in assessment.get("evidence") or []:
        if ev.get("kind") == "file" and file_sha256(root, ev["path"]) != ev.get("sha256"):
            reasons.append(f"cited evidence changed: {ev['path']}")
    decided = parse_ts(assessment.get("decided_at_utc"))
    if decided is None or now - decided > timedelta(days=MAX_CACHE_AGE_DAYS):
        reasons.append(f"decision older than the {MAX_CACHE_AGE_DAYS}-day maximum cache age")
    return reasons


_SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, None: 4}


def queue_priority(candidate: dict[str, Any], attempts: int) -> list[Any]:
    """KEV first, then least-attempted, in-window, most severe, oldest."""
    return [
        0 if candidate.get("kev") else 1,
        attempts,
        0 if candidate.get("window_reasons") else 1,
        _SEV_RANK.get(candidate.get("severity"), 4),
        candidate.get("first_seen_utc") or "",
        candidate["candidate_id"],
    ]


def invalidate(state: dict[str, Any], cid: str, reasons: list[str], run_id: str, now: datetime) -> None:
    """Move a decision out of the current set; it is kept only as history."""
    a = state["assessments"].pop(cid, None)
    if a is not None:
        state["stale"][cid] = {"assessment": a, "reasons": sorted(set(reasons)),
                               "invalidated_at_utc": iso(now), "run_id": run_id}


def enqueue(state: dict[str, Any], cid: str, reasons: list[str], now: datetime) -> None:
    for item in state["queue"]:
        if item["candidate_id"] == cid:
            item["reasons"] = sorted(set(item["reasons"]) | set(reasons))
            return
    state["queue"].append({"candidate_id": cid, "enqueued_at_utc": iso(now),
                           "reasons": sorted(set(reasons)), "attempts": 0})


def dequeue(state: dict[str, Any], cid: str) -> None:
    state["queue"] = [q for q in state["queue"] if q["candidate_id"] != cid]


def sorted_queue(state: dict[str, Any]) -> list[str]:
    cands = state["candidates"]
    items = [q for q in state["queue"] if q["candidate_id"] in cands]
    items.sort(key=lambda q: queue_priority(cands[q["candidate_id"]], q["attempts"]))
    return [q["candidate_id"] for q in items]
