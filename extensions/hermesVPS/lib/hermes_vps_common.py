"""Shared hermesVPS validation helpers (stdlib only).

Used by bin/hermes-vps-review, bin/init-hermes-review, and
bin/hermes-vps-artifacts so validation rules stay in one place.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from typing import Any

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
# ASCII start + length; additional "." / ".." / embedded ".." bans in validate_identifier.
IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
PHASE_RE = re.compile(r"^[0-9]{3}$")

REQUIRED_POLICY_REL = [
    "BOOTSTRAP.md",
    "rules/rules_000-safety-and-scope.md",
    "rules/rules_005-report-output.md",
    "rules/rules_010-inventory.md",
    "tasks/010-inventory.md",
    "templates/phase-010-report.md",
    "security-assets/findings.schema.json",
    "security-assets/README.md",
]
# Legacy fallback used when the phases module is unavailable (should not occur in normal use).


class ValidationError(Exception):
    pass


class DuplicateKeyError(ValueError):
    """Raised when a JSON object contains a repeated key."""


def die(msg: str, code: int = 2) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def require_cmd(name: str) -> str:
    from shutil import which

    path = which(name)
    if not path:
        die(f"required command not found on PATH: {name}")
    return path


def object_pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise DuplicateKeyError(f"duplicate JSON object key: {key!r}")
        out[key] = value
    return out


def load_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh, object_pairs_hook=object_pairs_hook)
    except FileNotFoundError as exc:
        raise ValidationError(f"missing file: {path}") from exc
    except OSError as exc:
        raise ValidationError(f"cannot read {path}: {exc}") from exc
    except DuplicateKeyError as exc:
        raise ValidationError(f"invalid JSON in {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(
            f"malformed JSON in {path}: {exc.msg} at line {exc.lineno} col {exc.colno}"
        ) from exc


def write_json_atomic(path: str, data: Any) -> None:
    """Write JSON via a same-directory temp file and os.replace."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    tmp_path = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            if os.path.lexists(tmp_path):
                os.unlink(tmp_path)
        except OSError:
            pass
        raise


def sha256_file(path: str) -> str:
    """Return lowercase hex SHA-256 of the file at path."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def expect_type(value: Any, typ: type | tuple[type, ...], label: str) -> Any:
    if not isinstance(value, typ):
        raise ValidationError(f"{label}: expected {typ}, got {type(value).__name__}")
    return value


def expect_str(value: Any, label: str) -> str:
    s = expect_type(value, str, label)
    if s.strip() == "":
        raise ValidationError(f"{label}: must be a non-empty string")
    return s


def validate_identifier(value: str, label: str) -> str:
    """Registry/run identifiers: ASCII set/length, never '.', '..', or embedded '..'."""
    if value in (".", ".."):
        raise ValidationError(f"{label}: identifier must not be '.' or '..'")
    if ".." in value:
        raise ValidationError(f"{label}: identifier must not contain '..'")
    if not IDENT.match(value):
        raise ValidationError(
            f"{label}: must match ^[A-Za-z0-9][A-Za-z0-9._-]{{0,127}}$ "
            f"and must not contain '..' (got {value!r})"
        )
    return value


def realpath_abs(path: str, label: str) -> str:
    if not os.path.isabs(path):
        raise ValidationError(f"{label}: must be an absolute path")
    if "\x00" in path:
        raise ValidationError(f"{label}: NUL byte not allowed")
    parts = path.split(os.sep)
    if ".." in parts:
        raise ValidationError(f"{label}: path must not contain '..' segments")
    try:
        return os.path.realpath(path)
    except OSError as exc:
        raise ValidationError(f"{label}: cannot resolve path: {exc}") from exc


def is_within(child: str, parent: str) -> bool:
    child_r = os.path.realpath(child)
    parent_r = os.path.realpath(parent)
    try:
        common = os.path.commonpath([child_r, parent_r])
    except ValueError:
        return False
    return common == parent_r


def is_strictly_within(child: str, parent: str) -> bool:
    """True when child resolves under parent and is not the parent itself."""
    child_r = os.path.realpath(child)
    parent_r = os.path.realpath(parent)
    if child_r == parent_r:
        return False
    return is_within(child_r, parent_r)


def expect_schema_version_1(value: Any, label: str) -> None:
    """Require exact JSON integer 1 (reject bool true and float 1.0)."""
    if type(value) is not int or value != 1:
        raise ValidationError(
            f"{label} must be integer 1 (exact int; not bool, string, or float)"
        )


def git(args: list[str], cwd: str | None = None) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise ValidationError(f"failed to execute git: {exc}") from exc
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        where = cwd if cwd is not None else os.getcwd()
        raise ValidationError(f"git {' '.join(args)} failed in {where}: {err}")
    return proc.stdout.strip()


def validate_worktree_root(source_path: str) -> str:
    """Require non-bare worktree whose toplevel equals resolved source_path."""
    if not os.path.isdir(source_path):
        raise ValidationError(f"source.path is not a directory: {source_path}")
    try:
        inside_worktree = git(["rev-parse", "--is-inside-work-tree"], cwd=source_path)
    except ValidationError as exc:
        raise ValidationError(
            f"source.path is not a usable Git worktree: {source_path}"
        ) from exc
    if inside_worktree != "true":
        raise ValidationError(
            "source.path must be an actual non-bare Git worktree "
            f"(git rev-parse --is-inside-work-tree returned {inside_worktree!r}): "
            f"{source_path}"
        )
    toplevel = git(["rev-parse", "--show-toplevel"], cwd=source_path)
    try:
        worktree_root = os.path.realpath(toplevel)
    except OSError as exc:
        raise ValidationError(
            f"cannot resolve Git worktree root for source.path: {exc}"
        ) from exc
    if worktree_root != source_path:
        raise ValidationError(
            "source.path must equal the resolved Git worktree root "
            f"(source.path={source_path!r}, worktree_root={worktree_root!r})"
        )
    return worktree_root


def validate_run(
    data: Any,
    *,
    expected_policy_prefix: str | None = None,
) -> dict[str, Any]:
    expect_type(data, dict, "run.json root")
    expect_schema_version_1(data.get("schema_version"), "run.json schema_version")

    run_id = validate_identifier(expect_str(data.get("run_id"), "run_id"), "run_id")

    policy_prefix_raw = expect_str(data.get("policy_prefix"), "policy_prefix")
    policy_prefix = realpath_abs(policy_prefix_raw, "policy_prefix")
    if not os.path.isdir(policy_prefix):
        raise ValidationError(f"policy_prefix is not a directory: {policy_prefix}")
    if expected_policy_prefix is not None and policy_prefix != expected_policy_prefix:
        raise ValidationError(
            "registry/run policy_prefix mismatch after normalization: "
            f"registry={expected_policy_prefix!r} run.json={policy_prefix!r}"
        )

    source = expect_type(data.get("source"), dict, "source")
    source_path_raw = expect_str(source.get("path"), "source.path")
    source_path = realpath_abs(source_path_raw, "source.path")
    source_identity = expect_str(source.get("identity"), "source.identity")
    source_commit = expect_str(source.get("commit"), "source.commit").lower()
    if not FULL_SHA.match(source_commit):
        raise ValidationError("source.commit must be a full 40-char lowercase hex SHA")
    require_clean = source.get("require_clean_worktree", True)
    if not isinstance(require_clean, bool):
        raise ValidationError("source.require_clean_worktree must be a boolean")
    if require_clean is not True:
        raise ValidationError("v1 requires source.require_clean_worktree == true")

    output = expect_type(data.get("output"), dict, "output")
    run_root_raw = expect_str(output.get("run_root"), "output.run_root")
    run_root = realpath_abs(run_root_raw, "output.run_root")

    phase_request = expect_type(data.get("phase_request"), dict, "phase_request")
    phase = expect_str(phase_request.get("phase"), "phase_request.phase")
    if not PHASE_RE.match(phase):
        raise ValidationError("phase_request.phase must be a 3-digit string")
    # NOTE: phase value is treated as legacy/informational metadata.
    # The CLI --phase flag is authoritative for which phase is being executed.
    # No equality gate here; validate_run accepts any valid 3-digit phase string.
    phase_name = phase_request.get("phase_name") or ""

    if "report_version" in phase_request:
        print(
            "deprecation warning: phase_request.report_version in run.json is no longer "
            "used; version is selected automatically by hermes-vps-artifacts register; "
            "remove phase_request.report_version from run.json",
            file=sys.stderr,
        )

    prereq = expect_type(data.get("prerequisites"), dict, "prerequisites")
    artifacts = prereq.get("artifacts")
    expect_type(artifacts, list, "prerequisites.artifacts")

    toolkit = data.get("toolkit") or {}
    toolkit_revision: str
    if isinstance(toolkit, dict):
        tr = toolkit.get("toolkit_revision")
        toolkit_revision = tr if isinstance(tr, str) and tr.strip() else "unknown"
    else:
        toolkit_revision = "unknown"

    # Check policy files for the phase in run.json (informational phase value).
    # The runner additionally calls validate_phase_policy_files() for the CLI phase.
    try:
        from lib.hermes_vps_phases import abs_policy_files_for_phase, PHASE_TABLE  # noqa: PLC0415
        if phase in PHASE_TABLE:
            abs_policy_files = abs_policy_files_for_phase(policy_prefix, phase)
        else:
            abs_policy_files = {rel: os.path.join(policy_prefix, rel) for rel in REQUIRED_POLICY_REL}
    except ImportError:
        abs_policy_files = {rel: os.path.join(policy_prefix, rel) for rel in REQUIRED_POLICY_REL}

    missing = [p for p in abs_policy_files.values() if not os.path.isfile(p)]
    if missing:
        raise ValidationError(
            "missing required policy/task/template files:\n  " + "\n  ".join(missing)
        )

    validate_worktree_root(source_path)

    head = git(["rev-parse", "HEAD"], cwd=source_path).lower()
    if head != source_commit:
        raise ValidationError(
            f"source.commit mismatch: run.json has {source_commit}, checkout HEAD is {head}"
        )
    porcelain = git(["status", "--porcelain"], cwd=source_path)
    if porcelain:
        raise ValidationError(
            "source worktree is dirty; v1 requires a clean tree. "
            "git status --porcelain output present"
        )

    if not os.path.isdir(run_root):
        raise ValidationError(
            f"output.run_root does not exist (runner does not create it): {run_root}"
        )
    if is_within(run_root, source_path):
        raise ValidationError("output.run_root must not be inside the source checkout")
    if is_within(run_root, policy_prefix):
        raise ValidationError("output.run_root must not be inside the policy prefix")
    if source_path == policy_prefix:
        raise ValidationError("source.path and policy_prefix must be distinct")

    reports_dir_join = os.path.join(run_root, "reports")
    if not os.path.lexists(reports_dir_join):
        raise ValidationError(
            "reports directory missing; create "
            f"{reports_dir_join} before validation "
            "(runner does not create directories or print a phase prompt until it exists)"
        )
    if not os.path.isdir(reports_dir_join) and not os.path.islink(reports_dir_join):
        raise ValidationError(
            f"reports path exists but is not a directory: {reports_dir_join}"
        )
    try:
        reports_dir = os.path.realpath(reports_dir_join)
    except OSError as exc:
        raise ValidationError(f"cannot resolve reports directory: {exc}") from exc
    if not os.path.isdir(reports_dir):
        raise ValidationError(
            "reports path does not resolve to a directory: "
            f"{reports_dir_join} -> {reports_dir}"
        )
    if not is_strictly_within(reports_dir, run_root):
        raise ValidationError(
            "resolved reports/ must remain strictly inside the run root "
            f"(reports={reports_dir!r}, run_root={run_root!r})"
        )
    if is_within(reports_dir, source_path):
        raise ValidationError(
            "resolved reports/ must not resolve into the source checkout "
            f"(reports={reports_dir!r})"
        )
    if is_within(reports_dir, policy_prefix):
        raise ValidationError(
            "resolved reports/ must not resolve into the policy prefix "
            f"(reports={reports_dir!r})"
        )

    manifest_path = os.path.join(run_root, "manifest.json")
    manifest_note = "absent (valid empty starting state)"
    if os.path.isfile(manifest_path):
        manifest = load_json(manifest_path)
        expect_type(manifest, dict, "manifest.json root")
        # Build a partial ctx for the identity check (full ctx not yet assembled).
        _partial_ctx = {
            "run_id": run_id,
            "source_identity": source_identity,
            "source_path_raw": source_path_raw,
            "source_path": source_path,
            "source_commit": source_commit,
            "policy_prefix": policy_prefix,
        }
        validate_manifest_identity(manifest, _partial_ctx)
        arts = manifest.get("artifacts", [])
        expect_type(arts, list, "manifest.artifacts")
        manifest_note = f"present with {len(arts)} artifact entr(y/ies); auto-maintained by hermes-vps-artifacts"

    boundaries = data.get("boundaries")
    if boundaries is not None:
        expect_type(boundaries, dict, "boundaries")
        claims = boundaries.get("claims_os_readonly_source")
        if claims is not False:
            raise ValidationError(
                "boundaries.claims_os_readonly_source must be false "
                "(upload mode must not claim OS-enforced read-only)"
            )
        roots = boundaries.get("allowed_write_roots")
        if roots is not None:
            expect_type(roots, list, "boundaries.allowed_write_roots")
            ok = False
            for r in roots:
                rs = expect_str(r, "boundaries.allowed_write_roots[]")
                if realpath_abs(rs, "boundaries.allowed_write_roots[]") == run_root:
                    ok = True
            if not ok:
                raise ValidationError(
                    "output.run_root is not listed in boundaries.allowed_write_roots "
                    "after path resolution"
                )

    return {
        "run_id": run_id,
        "policy_prefix": policy_prefix,
        "policy_prefix_raw": policy_prefix_raw,
        "source_path": source_path,
        "source_path_raw": source_path_raw,
        "source_identity": source_identity,
        "source_commit": source_commit,
        "run_root": run_root,
        "run_root_raw": run_root_raw,
        # run.json-recorded phase/phase_name: legacy/informational; CLI --phase is authoritative.
        "run_json_phase": phase,
        "run_json_phase_name": phase_name,
        # Keep "phase" for backward compatibility with callers that read ctx["phase"]
        "phase": phase,
        "phase_name": phase_name,
        "reports_dir": reports_dir,
        "toolkit_revision": toolkit_revision,
        "manifest_path": manifest_path,
        "manifest_note": manifest_note,
        "abs_policy_files": abs_policy_files,
    }


def validate_manifest_identity(manifest: dict[str, Any], ctx: dict[str, Any]) -> None:
    """Raise ValidationError if manifest identity fields conflict with run context."""
    m_run = validate_identifier(
        expect_str(manifest.get("run_id"), "manifest.run_id"), "manifest.run_id"
    )
    if m_run != ctx["run_id"]:
        raise ValidationError(
            f"manifest/run identity mismatch: run_id {ctx['run_id']!r} vs manifest {m_run!r}"
        )
    m_source = expect_type(manifest.get("source"), dict, "manifest.source")
    for key, expected in (
        ("identity", ctx["source_identity"]),
        ("path", ctx["source_path_raw"]),
        ("commit", ctx["source_commit"]),
    ):
        got = expect_str(m_source.get(key), f"manifest.source.{key}")
        if key == "commit":
            got = got.lower()
        if key == "path":
            if realpath_abs(got, "manifest.source.path") != ctx["source_path"]:
                raise ValidationError(
                    "manifest/run identity mismatch: source.path does not resolve equally"
                )
        elif got != expected:
            raise ValidationError(
                f"manifest/run identity mismatch: source.{key}: "
                f"run.json={expected!r} manifest={got!r}"
            )
    m_policy = expect_type(manifest.get("policy"), dict, "manifest.policy")
    m_prefix = expect_str(m_policy.get("prefix"), "manifest.policy.prefix")
    if realpath_abs(m_prefix, "manifest.policy.prefix") != ctx["policy_prefix"]:
        raise ValidationError(
            "manifest/run identity mismatch: policy.prefix does not resolve equally"
        )


# ---------------------------------------------------------------------------
# Minimal JSON Schema validator (stdlib only)
#
# Supports the keyword subset used by templates/*.schema.json.  Any other
# structural keyword raises, so a schema edit can never be silently unenforced.
# ---------------------------------------------------------------------------

_SCHEMA_ANNOTATIONS = {"$schema", "title", "description", "default", "format", "$comment"}
_SCHEMA_KEYWORDS = {
    "type", "const", "enum", "required", "properties",
    "additionalProperties", "items", "pattern", "minimum", "minItems",
}


def _schema_type_ok(value: Any, typ: str) -> bool:
    if typ == "null":
        return value is None
    if typ == "boolean":
        return isinstance(value, bool)
    if typ == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if typ == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if typ == "string":
        return isinstance(value, str)
    if typ == "array":
        return isinstance(value, list)
    if typ == "object":
        return isinstance(value, dict)
    raise ValidationError(f"schema uses unsupported type {typ!r}")


def validate_schema(value: Any, schema: dict[str, Any], label: str = "$") -> None:
    """Raise ValidationError at the first violation of schema by value."""
    unknown = set(schema) - _SCHEMA_KEYWORDS - _SCHEMA_ANNOTATIONS
    if unknown:
        raise ValidationError(f"schema at {label} uses unsupported keywords: {sorted(unknown)}")

    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_schema_type_ok(value, t) for t in types):
            raise ValidationError(
                f"{label}: expected type {'|'.join(types)}, got {type(value).__name__}"
            )
    if "const" in schema and value != schema["const"]:
        raise ValidationError(f"{label}: must equal {schema['const']!r}, got {value!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValidationError(f"{label}: {value!r} not in {schema['enum']!r}")

    if isinstance(value, str) and "pattern" in schema:
        if not re.search(schema["pattern"], value):
            raise ValidationError(f"{label}: {value!r} does not match {schema['pattern']!r}")
    if (
        isinstance(value, (int, float)) and not isinstance(value, bool)
        and "minimum" in schema and value < schema["minimum"]
    ):
        raise ValidationError(f"{label}: {value!r} is below minimum {schema['minimum']!r}")

    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                raise ValidationError(f"{label}: missing required field {key!r}")
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key, sub in value.items():
            if key in props:
                validate_schema(sub, props[key], f"{label}.{key}")
            elif extra is False:
                raise ValidationError(f"{label}: unexpected field {key!r}")
            elif isinstance(extra, dict):
                validate_schema(sub, extra, f"{label}.{key}")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise ValidationError(f"{label}: needs at least {schema['minItems']} item(s)")
        if "items" in schema:
            for i, item in enumerate(value):
                validate_schema(item, schema["items"], f"{label}[{i}]")


def load_schema(policy_prefix: str, name: str) -> dict[str, Any]:
    """Load templates/<name> from the policy prefix (fail closed if absent)."""
    path = os.path.join(policy_prefix, "templates", name)
    schema = load_json(path)
    if not isinstance(schema, dict):
        raise ValidationError(f"schema {path} must be a JSON object")
    return schema


def resolve_registry(registry_path: str, target_id: str) -> tuple[str, str]:
    """Return (absolute run.json path, normalized registry policy_prefix)."""
    validate_identifier(target_id, "--target-id")
    reg = load_json(registry_path)
    expect_type(reg, dict, "targets.json root")
    expect_schema_version_1(
        reg.get("schema_version"), "targets.json schema_version"
    )
    policy_raw = expect_str(reg.get("policy_prefix"), "targets.json policy_prefix")
    policy_prefix = realpath_abs(policy_raw, "targets.json policy_prefix")
    if not os.path.isdir(policy_prefix):
        raise ValidationError(
            f"targets.json policy_prefix is not a directory: {policy_prefix}"
        )

    targets = expect_type(reg.get("targets"), dict, "targets.json targets")
    if target_id not in targets:
        known = ", ".join(sorted(targets)) if targets else "(none)"
        raise ValidationError(
            f"unknown target id {target_id!r}; known targets: {known}"
        )
    entry = expect_type(targets[target_id], dict, f"targets[{target_id!r}]")
    run_json_raw = expect_str(
        entry.get("active_run_json"), f"targets[{target_id!r}].active_run_json"
    )
    run_json_path = realpath_abs(
        run_json_raw, f"targets[{target_id!r}].active_run_json"
    )
    if not os.path.isfile(run_json_path):
        raise ValidationError(
            f"active_run_json is not a file for target {target_id!r}: {run_json_path}"
        )
    # Never concatenate target_id into filesystem paths; only use the configured path.
    return run_json_path, policy_prefix
