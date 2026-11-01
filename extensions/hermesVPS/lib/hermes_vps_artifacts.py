"""hermesVPS artifact helper logic.

This module is the ONLY writer of manifest.json.
All writes go through the per-run fcntl lock and atomic replacement.

Structural/hash checks do not prove factual correctness of report content.
Reviewer identity is recorded as declared and unauthenticated.
"""

from __future__ import annotations

import argparse
import datetime
import fcntl
import json
import os
import re
import shlex
import shutil
import sys
from typing import Any

# Prevent __pycache__ writes under the policy tree when imported.
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

_EXT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _EXT_ROOT not in sys.path:
    sys.path.insert(0, _EXT_ROOT)

from lib.hermes_vps_common import (  # noqa: E402
    ValidationError,
    die,
    expect_type,
    is_within,
    load_json,
    load_schema,
    sha256_file,
    validate_identifier,
    validate_manifest_identity,
    validate_run,
    validate_schema,
    write_json_atomic,
)
from lib.hermes_vps_intel import assess_freshness  # noqa: E402
from lib.hermes_vps_phases import (  # noqa: E402
    PHASE_TABLE,
    REPEATED_PHASES,
    VALID_PHASES,
)
from lib.hermes_vps_resolver import (  # noqa: E402
    artifact_problems,
    current_selection,
    execution_inputs,
    file_problems,
    find_artifact,
    load_artifact_payload,
    prerequisite_hashes,
    read_report_header,
    resolve_prerequisites,
    triage_candidate_ids,
)


# ---------------------------------------------------------------------------
# Per-run exclusive lock
# ---------------------------------------------------------------------------

class RunLock:
    """Advisory exclusive lock on <run_root>/.hermes-artifacts.lock.

    This is a Unix fcntl advisory lock — not an OS security boundary
    against non-cooperating writers.
    """

    _held: set[str] = set()

    def __init__(self, run_root: str) -> None:
        self._path = os.path.join(run_root, ".hermes-artifacts.lock")
        self._key = os.path.realpath(self._path)
        self._fh: Any = None

    def __enter__(self) -> "RunLock":
        # flock on a second descriptor in the same process would self-deadlock.
        if self._key in RunLock._held:
            raise RuntimeError(f"recursive RunLock acquisition for {self._path}")
        self._fh = open(self._path, "w", encoding="utf-8")
        fcntl.flock(self._fh, fcntl.LOCK_EX)
        RunLock._held.add(self._key)
        return self

    def __exit__(self, *_: object) -> None:
        if self._fh is not None:
            try:
                fcntl.flock(self._fh, fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None
                RunLock._held.discard(self._key)


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------

def _utcnow() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_or_init_manifest(manifest_path: str, ctx: dict[str, Any]) -> dict[str, Any]:
    """Load existing manifest (validating identity) or build an empty new one."""
    if os.path.isfile(manifest_path):
        m = load_json(manifest_path)
        expect_type(m, dict, "manifest.json root")
        validate_manifest_identity(m, ctx)
        if "artifacts" not in m:
            m["artifacts"] = []
        expect_type(m["artifacts"], list, "manifest.artifacts")
        if "selected_by_phase" not in m:
            m["selected_by_phase"] = {}
        expect_type(m["selected_by_phase"], dict, "manifest.selected_by_phase")
        if "selected_by_subject" not in m:
            m["selected_by_subject"] = {}
        expect_type(m["selected_by_subject"], dict, "manifest.selected_by_subject")
        return m
    return {
        "schema_version": 1,
        "run_id": ctx["run_id"],
        "source": {
            "identity": ctx["source_identity"],
            "path": ctx["source_path_raw"],
            "commit": ctx["source_commit"],
        },
        "policy": {
            "prefix": ctx["policy_prefix_raw"],
            "toolkit_revision": ctx["toolkit_revision"],
        },
        "artifacts": [],
        "selected_by_phase": {},
        # subject-scoped selection for repeated phases (050, 070, 080)
        # structure: {"050": {"auth": ...}, "070": {"C-001": "phase-070-hermes-v1"}, "080": {"C-001": ...}}
        "selected_by_subject": {},
    }


def _next_version(manifest: dict[str, Any], phase: str) -> int:
    """Return the lowest unused positive integer version for phase."""
    used: set[int] = set()
    for art in manifest.get("artifacts", []):
        if (
            isinstance(art, dict)
            and art.get("kind") == "hermes_phase_report"
            and art.get("phase") == phase
        ):
            v = art.get("version")
            if isinstance(v, int) and not isinstance(v, bool):
                used.add(v)
    n = 1
    while n in used:
        n += 1
    return n


def _next_findings_version(manifest: dict[str, Any]) -> int:
    """Return the lowest unused positive integer version for findings_export artifacts."""
    used: set[int] = set()
    for art in manifest.get("artifacts", []):
        if isinstance(art, dict) and art.get("kind") == "findings_export":
            v = art.get("version")
            if isinstance(v, int) and not isinstance(v, bool):
                used.add(v)
    n = 1
    while n in used:
        n += 1
    return n




def _check_duplicate_id(manifest: dict[str, Any], artifact_id: str, sha: str) -> None:
    """Raise ValidationError if artifact_id already exists with a different SHA."""
    existing = find_artifact(manifest, artifact_id)
    if existing is not None and existing.get("sha256") != sha:
        raise ValidationError(
            f"artifact {artifact_id!r} already registered with different SHA-256; "
            "cannot overwrite a registered artifact"
        )


def _check_duplicate_phase_version(
    manifest: dict[str, Any], phase: str, version: int, artifact_id: str
) -> None:
    """Raise ValidationError if phase+version is used by a different ID."""
    for art in manifest.get("artifacts", []):
        if (
            isinstance(art, dict)
            and art.get("phase") == phase
            and art.get("version") == version
            and art.get("id") != artifact_id
        ):
            raise ValidationError(
                f"phase {phase} version {version} is already registered "
                f"as {art.get('id')!r}; cannot register {artifact_id!r} with the same version"
            )


def _update_selection(
    manifest: dict[str, Any], phase: str, subject_id: str | None, artifact_id: str
) -> None:
    """Repeated phases select per subject; all other phases select per phase."""
    if phase in REPEATED_PHASES:
        manifest.setdefault("selected_by_subject", {}).setdefault(phase, {})[subject_id] = artifact_id
    else:
        manifest["selected_by_phase"][phase] = artifact_id


# ---------------------------------------------------------------------------
# Consultation prompt
# ---------------------------------------------------------------------------

def _print_consult_prompt(
    ctx: dict[str, Any],
    artifact_id: str,
    final_path: str,
    sha: str,
    manifest_path: str,
    run_json_path: str,
    phase: str,
    version: int,
    subject_id: str | None = None,
) -> None:
    artifacts_bin = os.path.join(ctx["policy_prefix"], "bin", "hermes-vps-artifacts")
    phase_info = PHASE_TABLE.get(phase)
    phase_title = phase_info.phase_name if phase_info else phase
    subject_line = f"Subject ID:     {subject_id}\n" if subject_id else ""
    revise_payload = (
        " \\\n      --payload-json /absolute/path/to/revised-payload.json"
        if phase_info is not None and phase_info.payload_required else ""
    )
    text = f"""\
======== hermesVPS consultation prompt (hermes-vps-artifacts) ========
NOTE: Structural/hash checks do not prove factual correctness of report content.

Artifact ID:    {artifact_id}
Phase:          {phase} ({phase_title})
Version:        {version}
{subject_line}Source commit:  {ctx['source_commit']}
Report SHA-256: {sha}
Report path:    {final_path}
Artifact index: {manifest_path}
Run ID:         {ctx['run_id']}

If the second agent CANNOT access those local paths, provide:
  1. Full text of the report (paste or attach)
  2. Relevant artifact index entry from manifest.json
  3. Confirm source commit and report SHA-256 are accurate

STOP. Do not start the next phase without a separate explicit human request.

---- Advanced diagnostics (not required for normal progression) ----
  ACCEPT (record second-opinion review, no selection change):
    {artifacts_bin} accept \\
      --run-json {run_json_path} \\
      --artifact-id {artifact_id} \\
      --reviewer-identity "declared-name-or-id"

  REVISE (import corrected report, supersedes this artifact):
    {artifacts_bin} revise \\
      --run-json {run_json_path} \\
      --source-report /absolute/path/to/revised.md \\
      --supersedes {artifact_id} \\
      --reviewer-identity "declared-name-or-id"{revise_payload}
======== end consultation prompt ========
"""
    print(text)


# ---------------------------------------------------------------------------
# Bundle validation (report completion state + payload schema/identity)
# ---------------------------------------------------------------------------

_STATE_LINE_RE = re.compile(
    r"^\s*-?\s*(?:completion\s+state|state)\s*:\s*(complete|incomplete|blocked)\s*$",
    re.IGNORECASE,
)


def declared_completion(report_path: str, header: dict[str, Any]) -> str:
    """Return the header's completion state; body 'State:' lines must agree with it.

    Accepted body forms: 'State: `complete`' and '- **Completion state:** `blocked`'.
    """
    states: set[str] = set()
    with open(report_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = _STATE_LINE_RE.match(line.replace("*", "").replace("`", ""))
            if m:
                states.add(m.group(1).lower())
    declared = header["completion_state"]
    if states - {declared}:
        raise ValidationError(
            f"report body declares completion state(s) {sorted(states)} but the identity "
            f"header declares {declared!r}: {report_path}"
        )
    return declared


def _validate_payload(
    ctx: dict[str, Any], phase: str, subject_id: str | None, path: str
) -> dict[str, Any]:
    """Full schema, mandatory source identity, and subject identity for a payload."""
    info = PHASE_TABLE[phase]
    try:
        data = load_json(path)
    except ValidationError as exc:
        raise ValidationError(f"--payload-json: {exc}") from exc
    try:
        validate_schema(data, load_schema(ctx["policy_prefix"], info.payload_schema), "payload")
    except ValidationError as exc:
        raise ValidationError(f"--payload-json fails {info.payload_schema}: {exc}") from exc
    if data["source_commit"] != ctx["source_commit"]:
        raise ValidationError(
            f"--payload-json: source_commit {data['source_commit']!r} does not match "
            f"run commit {ctx['source_commit']!r}; payload was produced for a different checkout"
        )
    if info.repeated and data.get(info.trigger_label) != subject_id:
        raise ValidationError(
            f"--payload-json: {info.trigger_label} {data.get(info.trigger_label)!r} "
            f"!= --subject-id {subject_id!r}"
        )
    if phase == "060":
        ids = [c["candidate_id"] for c in data["candidates"]]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValidationError(f"--payload-json: duplicate candidate_id values {dupes}")
    return data


def _completion_status(phase: str, declared: str, payload: dict[str, Any]) -> str:
    if phase == "070":
        disposition = payload["assessment_disposition"]
        if (disposition == "blocked") != (declared == "blocked"):
            raise ValidationError(
                f"report declares completion state {declared!r} but payload "
                f"assessment_disposition is {disposition!r}; a blocked assessment must "
                "be declared blocked in both"
            )
    return declared


def _check_payload_against_manifest(
    manifest: dict[str, Any],
    run_root: str,
    phase: str,
    subject_id: str | None,
    data: dict[str, Any],
    prereq_ids: list[str],
) -> list[str]:
    """Cross-artifact identity checks; returns extra provenance prerequisite IDs."""
    if phase == "060":
        claimed = data.get("assessed_report_ids")
        if claimed is not None and sorted(set(claimed)) != sorted(prereq_ids):
            raise ValidationError(
                f"payload assessed_report_ids {sorted(set(claimed))} differ from the "
                f"resolved phase-060 inputs {sorted(prereq_ids)}"
            )
    if phase == "070":
        claimed = data.get("prerequisite_artifact_id")
        sel_060 = current_selection(manifest, "060", None)
        if claimed is not None and claimed != sel_060:
            raise ValidationError(
                f"payload prerequisite_artifact_id {claimed!r} is not the selected phase-060 {sel_060!r}"
            )
    if phase == "080":
        sel_040 = current_selection(manifest, "040", None)
        if data["intel_artifact_id"] != sel_040:
            raise ValidationError(
                f"phase-080 plan pins intel_artifact_id {data['intel_artifact_id']!r} but the "
                f"selected phase-040 is {sel_040!r}"
            )
        problems = artifact_problems(manifest, run_root, sel_040)
        if problems:
            raise ValidationError(f"phase-040 {sel_040} is not usable: " + "; ".join(problems))
        if data["intel_artifact_sha256"] != find_artifact(manifest, sel_040).get("payload_sha256"):
            raise ValidationError(
                f"phase-080 plan intel_artifact_sha256 does not match the payload SHA-256 of {sel_040}"
            )
        sel_070 = current_selection(manifest, "070", subject_id)
        if data["assessed_finding_artifact_id"] != sel_070:
            raise ValidationError(
                f"phase-080 plan pins assessed_finding_artifact_id "
                f"{data['assessed_finding_artifact_id']!r} but the selected phase-070 for "
                f"{subject_id!r} is {sel_070!r}"
            )
        entry_070 = find_artifact(manifest, sel_070)
        if data["assessed_finding_sha256"] != entry_070.get("payload_sha256"):
            raise ValidationError(
                f"phase-080 plan assessed_finding_sha256 does not match the payload SHA-256 of {sel_070}"
            )
        finding_id = data.get("finding_id")
        if finding_id is not None:
            proposed_id = load_artifact_payload(run_root, entry_070)["proposed_finding"].get("id")
            if finding_id != proposed_id:
                raise ValidationError(
                    f"phase-080 plan finding_id {finding_id!r} != phase-070 proposed_finding.id "
                    f"{proposed_id!r} for {subject_id!r}"
                )
        return [sel_040]
    return []


# ---------------------------------------------------------------------------
# Destination paths, exclusive creation, recovery
# ---------------------------------------------------------------------------

def _validate_destination_path(
    final_path: str, reports_dir: str, ctx: dict[str, Any]
) -> None:
    """Raise ValidationError if final_path escapes reports_dir or enters source/policy."""
    try:
        resolved = os.path.realpath(os.path.dirname(final_path))
    except OSError as exc:
        raise ValidationError(
            f"cannot resolve destination directory for {final_path}: {exc}"
        ) from exc
    if resolved != os.path.realpath(reports_dir):
        raise ValidationError(
            f"destination path must be directly inside reports dir "
            f"(got {final_path!r}, reports={reports_dir!r})"
        )
    if is_within(final_path, ctx["source_path"]):
        raise ValidationError(
            "destination must not be inside the source checkout"
        )
    if is_within(final_path, ctx["policy_prefix"]):
        raise ValidationError(
            "destination must not be inside the policy prefix"
        )


def _exclusive_copy(src: str, dest: str, expected_sha: str) -> None:
    """Create dest with O_EXCL|O_NOFOLLOW and copy src into it.

    An existing regular file with identical content is accepted (retry of a
    saved-but-unregistered bundle); anything else at dest is a collision.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(dest, flags, 0o644)
    except FileExistsError:
        if os.path.islink(dest) or not os.path.isfile(dest):
            raise ValidationError(f"destination exists and is not a regular file: {dest}") from None
        if sha256_file(dest) != expected_sha:
            raise ValidationError(
                f"destination already exists with different content: {dest}; "
                "registered files are never overwritten"
            ) from None
        return
    with os.fdopen(fd, "wb") as out, open(src, "rb") as inp:
        shutil.copyfileobj(inp, out)
        out.flush()
        os.fsync(out.fileno())
    if sha256_file(dest) != expected_sha:
        raise ValidationError(f"SHA-256 mismatch after copy to {dest}")


def _write_json_exclusive(path: str, data: Any) -> None:
    """Atomically create path with JSON content; never replaces an existing file."""
    tmp_path = f"{path}.tmp.{os.getpid()}"
    with open(tmp_path, "x", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    try:
        os.link(tmp_path, path)
    except FileExistsError:
        raise ValidationError(f"{path} already exists; refusing to overwrite") from None
    finally:
        os.unlink(tmp_path)


def _recovery_command(ctx: dict[str, Any], subcommand: str, argv: list[str]) -> str:
    artifacts_bin = os.path.join(ctx["policy_prefix"], "bin", "hermes-vps-artifacts")
    return shlex.join([artifacts_bin, subcommand, *argv])


def _not_registered(reason: str, written: list[str], recovery: str) -> int:
    saved = "".join(f"  {p} (SHA-256: {sha256_file(p)})\n" for p in written if os.path.isfile(p))
    print(
        f"error: bundle NOT registered.\nReason: {reason}\n"
        + (f"Files already written:\n{saved}" if saved else "")
        + f"Safe retry (same operation, all arguments preserved):\n  {recovery}",
        file=sys.stderr,
    )
    return 1


# ---------------------------------------------------------------------------
# Shared commit path for register and revise
# ---------------------------------------------------------------------------

def _commit_bundle(  # noqa: C901
    ctx: dict[str, Any],
    run_json_path: str,
    *,
    subcommand: str,
    argv: list[str],
    phase: str,
    subject_id: str | None,
    source_report: str,
    payload_json_path: str | None,
    supersedes: str | None = None,
    reviewer: str | None = None,
) -> int:
    info = PHASE_TABLE[phase]
    if info.payload_required and not payload_json_path:
        die(f"phase {phase} requires --payload-json ({info.phase_name} structured payload)")
    if not info.payload_required and payload_json_path:
        die(f"phase {phase} does not use --payload-json; remove that flag")
    for label, path in (("--source-report", source_report), ("--payload-json", payload_json_path)):
        if path is None:
            continue
        if not os.path.isabs(path):
            die(f"{label} must be an absolute path")
        if not os.path.isfile(path):
            die(f"{label} not found: {path}")

    try:
        header = read_report_header(source_report, ctx, phase, subject_id)
        declared = declared_completion(source_report, header)
        payload = _validate_payload(ctx, phase, subject_id, payload_json_path) if payload_json_path else {}
        completion_status = _completion_status(phase, declared, payload)
    except ValidationError as exc:
        die(str(exc))
    src_sha = sha256_file(source_report)
    payload_sha = sha256_file(payload_json_path) if payload_json_path else None

    run_root = ctx["run_root"]
    reports_dir = ctx["reports_dir"]
    manifest_path = ctx["manifest_path"]
    recovery = _recovery_command(ctx, subcommand, argv)

    with RunLock(run_root):
        try:
            manifest = _load_or_init_manifest(manifest_path, ctx)
        except ValidationError as exc:
            die(str(exc))

        # Bundle-aware retry detection: report AND payload must both match.
        for art in manifest["artifacts"]:
            if not (
                isinstance(art, dict)
                and art.get("kind") == "hermes_phase_report"
                and art.get("phase") == phase
                and art.get("subject_id") == subject_id
                and art.get("sha256") == src_sha
            ):
                continue
            if art.get("payload_sha256") != payload_sha:
                if supersedes is not None:
                    continue  # revising the payload under an unchanged report
                die(
                    f"artifact {art['id']!r} already has this report with a DIFFERENT payload; "
                    "this is not a safe retry. To change the payload, revise the current "
                    "selection with both the report and the new payload."
                )
            if supersedes is not None and art.get("supersedes") != supersedes:
                die(f"identical bundle is already registered as {art['id']!r}; nothing to revise")
            print(
                f"(idempotent: bundle already registered as {art['id']!r}; no changes made)",
                file=sys.stderr,
            )
            _print_consult_prompt(
                ctx, art["id"], os.path.join(run_root, art["path"]), src_sha,
                manifest_path, run_json_path, phase, art["version"], subject_id=subject_id,
            )
            return _maybe_consolidate(ctx, manifest, run_json_path, art["id"]) if phase == "070" else 0

        if supersedes is not None:
            prior = find_artifact(manifest, supersedes)
            if prior is None or prior.get("kind") != "hermes_phase_report":
                die(f"artifact {supersedes!r} not found in manifest; cannot supersede it")
            if prior.get("phase") != phase or prior.get("subject_id") != subject_id:
                die(
                    f"cross-subject supersession rejected: {supersedes!r} is phase "
                    f"{prior.get('phase')} subject {prior.get('subject_id')!r}; "
                    f"revision is phase {phase} subject {subject_id!r}"
                )
            current = current_selection(manifest, phase, subject_id)
            if current != supersedes:
                die(f"can only supersede the current selection {current!r}, not {supersedes!r}")

        try:
            prereq_ids = resolve_prerequisites(manifest, run_root, phase, subject_id)
            prereq_ids += [
                i for i in _check_payload_against_manifest(
                    manifest, run_root, phase, subject_id, payload, prereq_ids
                ) if i not in prereq_ids
            ]
        except ValidationError as exc:
            die(f"prerequisite check failed: {exc}")

        current_inputs = execution_inputs(manifest, prereq_ids)
        if header["execution_inputs"] != current_inputs:
            analyzed = [i["id"] for i in header["execution_inputs"]]
            die(
                "execution inputs changed since the phase started; this report was not "
                "produced from the current selection and is NOT registered.\n"
                f"  analyzed (report header): {json.dumps(header['execution_inputs'])}\n"
                f"  current selection:        {json.dumps(current_inputs)}\n"
                f"  analyzed IDs {analyzed} vs current IDs {[i['id'] for i in current_inputs]}\n"
                f"Re-run hermes-vps-review --phase {phase} and redo the phase against the "
                "current inputs."
            )

        version = _next_version(manifest, phase)
        artifact_id = f"phase-{phase}-hermes-v{version}"
        final_path = os.path.join(reports_dir, f"{artifact_id}.md")
        payload_dest = os.path.join(reports_dir, f"payload-{phase}-{subject_id or 'all'}-v{version}.json")
        try:
            _check_duplicate_id(manifest, artifact_id, src_sha)
            _check_duplicate_phase_version(manifest, phase, version, artifact_id)
            _validate_destination_path(final_path, reports_dir, ctx)
            _validate_destination_path(payload_dest, reports_dir, ctx)
        except ValidationError as exc:
            die(str(exc))

        written: list[str] = []
        try:
            _exclusive_copy(source_report, final_path, src_sha)
            written.append(final_path)
            if payload_json_path:
                _exclusive_copy(payload_json_path, payload_dest, payload_sha)
                written.append(payload_dest)
        except (ValidationError, OSError) as exc:
            return _not_registered(str(exc), written, recovery)

        entry: dict[str, Any] = {
            "id": artifact_id,
            "kind": "hermes_phase_report",
            "phase": phase,
            "version": version,
            "path": os.path.relpath(final_path, run_root),
            "sha256": src_sha,
            "source_commit": ctx["source_commit"],
            "toolkit_revision": ctx["toolkit_revision"],
            "producer": f"hermes-vps-artifacts/{subcommand}",
            "created_at_utc": _utcnow(),
            "completion_status": completion_status,
            "prerequisite_artifacts": prereq_ids,
            "prerequisite_hashes": prerequisite_hashes(manifest, prereq_ids),
            "supersedes": supersedes,
            "reviews": [],
        }
        if reviewer is not None:
            entry["reviews"].append({
                "outcome": "REVISE",
                "artifact_id": artifact_id,
                "supersedes": supersedes,
                "reviewer_identity_declared": reviewer,
                "authenticated": False,
                "recorded_at_utc": _utcnow(),
            })
        if subject_id is not None:
            entry["subject_id"] = subject_id
        if payload_json_path:
            entry["payload_path"] = os.path.relpath(payload_dest, run_root)
            entry["payload_sha256"] = payload_sha

        manifest["artifacts"].append(entry)
        _update_selection(manifest, phase, subject_id, artifact_id)
        try:
            write_json_atomic(manifest_path, manifest)
        except OSError as exc:
            return _not_registered(f"index write failed: {exc}", written, recovery)

        _print_consult_prompt(
            ctx, artifact_id, final_path, src_sha, manifest_path, run_json_path, phase, version,
            subject_id=subject_id,
        )
        if completion_status != "complete":
            print(
                f"NOTE: {artifact_id} is registered as {completion_status!r}; it cannot serve "
                "as a prerequisite until a complete revision is registered.",
                file=sys.stderr,
            )
        if supersedes is not None:
            print(
                f"Revised: {artifact_id!r} supersedes {supersedes!r}. "
                f"Selection updated to {artifact_id!r}. Original preserved.",
                file=sys.stderr,
            )
        if phase == "070":
            return _maybe_consolidate(ctx, manifest, run_json_path, artifact_id)
    return 0


def cmd_register(args: argparse.Namespace, run_json_path: str) -> int:
    """Register a finalized report bundle; auto-selects next version."""
    try:
        ctx = validate_run(load_json(run_json_path), expected_policy_prefix=None)
    except ValidationError as exc:
        die(str(exc))

    phase = args.phase
    if phase not in VALID_PHASES:
        die(f"unknown phase {phase!r}; valid phases: {', '.join(sorted(VALID_PHASES))}")
    info = PHASE_TABLE[phase]
    subject_id: str | None = args.subject_id
    if info.subject_id_required:
        if not subject_id:
            die(f"phase {phase} requires --subject-id ({info.trigger_label})")
        try:
            validate_identifier(subject_id, "--subject-id")
        except ValidationError as exc:
            die(str(exc))
    elif subject_id:
        die(f"phase {phase} does not use --subject-id; remove that flag")

    argv = ["--run-json", run_json_path, "--phase", phase, "--source-report", args.source_report]
    if subject_id:
        argv += ["--subject-id", subject_id]
    if args.payload_json:
        argv += ["--payload-json", args.payload_json]
    return _commit_bundle(
        ctx, run_json_path, subcommand="register", argv=argv, phase=phase,
        subject_id=subject_id, source_report=args.source_report,
        payload_json_path=args.payload_json,
    )


# ---------------------------------------------------------------------------
# Subcommand: accept
# ---------------------------------------------------------------------------

def cmd_accept(args: argparse.Namespace, run_json_path: str) -> int:
    """Record a second-opinion ACCEPT against an exact artifact. Does not change selection."""
    data = load_json(run_json_path)
    try:
        ctx = validate_run(data, expected_policy_prefix=None)
    except ValidationError as exc:
        die(str(exc))

    artifact_id = args.artifact_id.strip()
    reviewer = args.reviewer_identity.strip()
    if not reviewer:
        die("--reviewer-identity must not be empty")

    review_file = getattr(args, "review_file", None)
    if review_file is not None:
        if not os.path.isabs(review_file):
            die("--review-file must be an absolute path")
        if not os.path.isfile(review_file):
            die(f"--review-file not found: {review_file}")

    run_root = ctx["run_root"]
    manifest_path = ctx["manifest_path"]

    with RunLock(run_root):
        if not os.path.isfile(manifest_path):
            die("manifest.json does not exist; no artifacts registered yet")
        try:
            manifest = _load_or_init_manifest(manifest_path, ctx)
        except ValidationError as exc:
            die(str(exc))

        entry = find_artifact(manifest, artifact_id)
        if entry is None:
            die(
                f"artifact {artifact_id!r} not found in manifest; "
                "cannot record ACCEPT against unknown artifact"
            )

        review_record: dict[str, Any] = {
            "outcome": "ACCEPT",
            "artifact_id": artifact_id,
            "reviewer_identity_declared": reviewer,
            "authenticated": False,
            "recorded_at_utc": _utcnow(),
        }
        if review_file is not None:
            review_record["review_file_sha256"] = sha256_file(review_file)
            review_record["review_file_note"] = (
                "SHA-256 of reviewer-supplied file; content not validated by helper"
            )

        if "reviews" not in entry or not isinstance(entry["reviews"], list):
            entry["reviews"] = []
        entry["reviews"].append(review_record)

        try:
            write_json_atomic(manifest_path, manifest)
        except OSError as exc:
            die(f"failed to update manifest: {exc}")

    print(
        f"ACCEPT recorded for artifact {artifact_id!r}.\n"
        f"Reviewer identity (declared, unauthenticated): {reviewer!r}\n"
        f"Selection unchanged. Normal progression does not require ACCEPT."
    )
    return 0


# ---------------------------------------------------------------------------
# Subcommand: revise
# ---------------------------------------------------------------------------

def cmd_revise(args: argparse.Namespace, run_json_path: str) -> int:
    """Import a revised bundle through the same validation path as register."""
    try:
        ctx = validate_run(load_json(run_json_path), expected_policy_prefix=None)
    except ValidationError as exc:
        die(str(exc))

    supersedes = args.supersedes.strip()
    reviewer = args.reviewer_identity.strip()
    if not reviewer:
        die("--reviewer-identity must not be empty")
    if not os.path.isfile(ctx["manifest_path"]):
        die("manifest.json does not exist; no artifacts registered yet")
    try:
        manifest = _load_or_init_manifest(ctx["manifest_path"], ctx)
    except ValidationError as exc:
        die(str(exc))
    prior = find_artifact(manifest, supersedes)
    if prior is None or prior.get("kind") != "hermes_phase_report":
        die(f"artifact {supersedes!r} not found in manifest; cannot supersede an unknown artifact")

    phase = prior["phase"]
    subject_id: str | None = prior.get("subject_id")
    if args.subject_id is not None and args.subject_id != subject_id:
        die(
            f"cross-subject supersession rejected: prior artifact {supersedes!r} has "
            f"subject_id {subject_id!r} but --subject-id is {args.subject_id!r}"
        )

    argv = [
        "--run-json", run_json_path, "--source-report", args.source_report,
        "--supersedes", supersedes, "--reviewer-identity", reviewer,
    ]
    if args.subject_id:
        argv += ["--subject-id", args.subject_id]
    if args.payload_json:
        argv += ["--payload-json", args.payload_json]
    return _commit_bundle(
        ctx, run_json_path, subcommand="revise", argv=argv, phase=phase,
        subject_id=subject_id, source_report=args.source_report,
        payload_json_path=args.payload_json, supersedes=supersedes, reviewer=reviewer,
    )


# ---------------------------------------------------------------------------
# Subcommand: selected
# ---------------------------------------------------------------------------

def cmd_selected(args: argparse.Namespace, run_json_path: str) -> int:
    """Read-only: print selected artifact(s) with integrity and staleness checks."""
    data = load_json(run_json_path)
    try:
        ctx = validate_run(data, expected_policy_prefix=None)
    except ValidationError as exc:
        die(str(exc))

    manifest_path = ctx["manifest_path"]
    run_root = ctx["run_root"]

    if not os.path.isfile(manifest_path):
        print("Manifest absent — no artifacts registered yet.")
        return 0

    try:
        manifest = load_json(manifest_path)
        expect_type(manifest, dict, "manifest.json root")
        validate_manifest_identity(manifest, ctx)
    except ValidationError as exc:
        die(str(exc))

    selected_by_phase: dict[str, str] = expect_type(
        manifest.get("selected_by_phase", {}), dict, "selected_by_phase"
    )
    selected_by_subject: dict[str, Any] = expect_type(
        manifest.get("selected_by_subject", {}), dict, "selected_by_subject"
    )
    filter_phase = getattr(args, "phase", None)

    phases = (
        [filter_phase]
        if filter_phase
        else sorted(set(list(selected_by_phase.keys()) + list(selected_by_subject.keys())))
    )

    if not phases:
        print("No selected artifacts.")
        return 0

    ok = True
    for ph in phases:
        if ph in REPEATED_PHASES:
            subj_map = selected_by_subject.get(ph, {})
            if not subj_map:
                print(f"  phase {ph}: (no subject-scoped selections)")
                continue
            for subj_id, art_id in sorted(subj_map.items()):
                ok = _print_artifact_status(manifest, run_root, ph, art_id, subject_id=subj_id) and ok
        else:
            art_id = selected_by_phase.get(ph)
            if art_id is None:
                print(f"  phase {ph}: (no selection)")
                continue
            ok = _print_artifact_status(manifest, run_root, ph, art_id) and ok

    if not ok:
        print("\nerror: one or more selected artifacts are not usable", file=sys.stderr)
        return 1
    return 0


def _print_artifact_status(
    manifest: dict[str, Any],
    run_root: str,
    phase: str,
    art_id: str,
    subject_id: str | None = None,
) -> bool:
    entry = find_artifact(manifest, art_id)
    subject_label = f" [{subject_id}]" if subject_id else ""
    if entry is None:
        print(
            f"  phase {phase}{subject_label}: ERROR — selected id {art_id!r} not in artifacts list",
            file=sys.stderr,
        )
        return False
    problems = artifact_problems(manifest, run_root, art_id)
    if entry.get("kind") == "findings_export":
        problems = file_problems(run_root, entry)
    status = "OK (complete, SHA-256 OK, current)" if not problems else "NOT USABLE"
    print(
        f"  phase {phase}{subject_label}: {art_id}\n"
        f"    path:   {os.path.join(run_root, entry.get('path', ''))}\n"
        f"    status: {entry.get('completion_status', '?')} — {status}"
        + "".join(f"\n      ! {p}" for p in problems)
    )
    return not problems


# ---------------------------------------------------------------------------
# Findings consolidation (generate-findings and automatic consolidation)
# ---------------------------------------------------------------------------

def _intel_readiness(
    manifest: dict[str, Any], run_root: str, hours: float, source: str, at_utc: str
) -> dict[str, Any]:
    """Freshness and coverage of the selected phase-040 payload (fail closed to unknown)."""
    sel_040 = current_selection(manifest, "040", None)

    def _unknown(reason: str) -> dict[str, Any]:
        return {
            "artifact_id": sel_040,
            "freshness": {
                "ok": None, "evaluated_at_utc": at_utc,
                "effective_threshold_hours": hours, "threshold_source": source,
                "limitations": [reason],
            },
            "coverage": {"notes": reason, "limitations": []},
        }

    if not sel_040:
        return _unknown("no phase-040 artifact selected")
    problems = artifact_problems(manifest, run_root, sel_040)
    if problems:
        return _unknown(f"phase-040 {sel_040} is not usable: " + "; ".join(problems))
    record = load_artifact_payload(run_root, find_artifact(manifest, sel_040))
    providers = record["providers"]
    return {
        "artifact_id": sel_040,
        "freshness": assess_freshness(record, hours, source, at_utc),
        "coverage": {
            "osv_status": providers["osv"]["status"],
            "nvd_status": providers["nvd"]["status"],
            "cisa_kev_status": providers["cisa_kev"]["status"],
            "total_matches": record["coverage"]["total_matches"],
            "kev_matches": record["coverage"]["kev_matches"],
            "collection_mode": record["collection_mode"],
            "collected_at_utc": record["collected_at_utc"],
            "limitations": [
                f"{name}: {p['status']}" for name, p in providers.items()
                if p["status"] not in ("success", "no_match")
            ],
        },
    }


_CANONICAL_FIELDS = {
    "id", "title", "status", "severity", "confidence",
    "firstSeen", "lastReviewed", "source", "files",
    "summary", "exploitPath", "remediation",
    "duplicateOf", "acceptedRiskId", "notes",
}


def _build_export(  # noqa: C901
    ctx: dict[str, Any],
    manifest: dict[str, Any],
    hours: float,
    source: str,
    require_fresh: bool,
) -> tuple[dict[str, Any], list[str]]:
    """Return (export document, exact input artifact IDs). Read-only."""
    run_root = ctx["run_root"]
    generated_at = _utcnow()
    intel = _intel_readiness(manifest, run_root, hours, source, generated_at)
    intel_ok = intel["freshness"].get("ok") is True
    limitations: list[str] = list(intel["freshness"].get("limitations", []))
    limitations += intel["coverage"].get("limitations", [])

    sel_060, candidate_ids = triage_candidate_ids(manifest, run_root)
    triage_problems = artifact_problems(manifest, run_root, sel_060)
    limitations += [f"phase-060 {sel_060}: {p}" for p in triage_problems]

    sbs_070 = manifest.get("selected_by_subject", {}).get("070", {})
    sbs_080 = manifest.get("selected_by_subject", {}).get("080", {})
    missing: list[str] = []
    stale: list[str] = []
    incomplete: list[str] = []
    stale_plans: list[str] = []
    used_070: dict[str, str] = {}
    used_080: dict[str, str] = {}
    findings: list[dict[str, Any]] = []
    dismissed: list[dict[str, Any]] = []

    for cid in candidate_ids:
        art_id = sbs_070.get(cid)
        if not art_id:
            missing.append(cid)
            continue
        entry = find_artifact(manifest, art_id)
        if entry is not None and entry.get("completion_status") != "complete":
            incomplete.append(cid)
            limitations.append(f"candidate {cid}: {art_id} is {entry.get('completion_status')!r}")
            continue
        problems = artifact_problems(manifest, run_root, art_id)
        if problems:
            stale.append(cid)
            limitations += [f"candidate {cid}: {art_id}: {p}" for p in problems]
            continue
        payload = load_artifact_payload(run_root, entry)
        used_070[cid] = art_id
        if payload["assessment_disposition"] == "dismissed":
            dismissed.append({
                "candidate_id": cid,
                "disposition": "dismissed",
                "rationale": payload.get("assessment_rationale"),
                "source_artifact": art_id,
            })
            continue

        plan_id = sbs_080.get(cid)
        if plan_id:
            plan_problems = artifact_problems(manifest, run_root, plan_id)
            if plan_problems:
                stale_plans.append(cid)
                limitations += [f"phase-080 plan {plan_id} for {cid}: {p}" for p in plan_problems]
                plan_id = None
            else:
                used_080[cid] = plan_id

        proposed = payload["proposed_finding"]
        finding: dict[str, Any] = {
            "candidate_id": cid,
            "finding_id": proposed.get("id"),
            "assessment_disposition": payload["assessment_disposition"],
            "assessment_rationale": payload.get("assessment_rationale"),
            "proposed_record": {k: v for k, v in proposed.items() if k in _CANONICAL_FIELDS},
            "affected_components": payload.get("affected_components", []),
            "impact": payload.get("impact"),
            "likelihood": payload.get("likelihood"),
            "evidence": payload.get("evidence", []),
            "unknowns": payload.get("unknowns", []),
            "blockers": payload.get("blockers", []),
            "source_artifact": art_id,
            "source_commit": entry["source_commit"],
            "remediation_plan_artifact": plan_id,
        }
        if plan_id and finding["proposed_record"].get("status") == "fixed":
            finding["proposed_record"]["status"] = "open"
            finding["_note"] = (
                "status reset from 'fixed' to 'open': a remediation plan does not "
                "constitute a fix; status must be updated only after verified remediation"
            )
        findings.append(finding)

    for cid, plan_id in sorted(sbs_080.items()):
        if cid not in candidate_ids:
            limitations.append(
                f"phase-080 plan {plan_id} for {cid!r} has no candidate in the current triage inventory"
            )

    if missing:
        limitations.append(f"missing assessments for: {', '.join(missing)}")
    complete = not (missing or stale or incomplete or triage_problems)
    policy_check_failed = require_fresh and not intel_ok

    coverage = {
        "total_candidates": len(candidate_ids),
        "assessed": len(used_070),
        "missing_assessments": missing,
        "stale_assessments": stale,
        "incomplete_assessments": incomplete,
        "complete": complete,
        "intel_collected_at_utc": intel["coverage"].get("collected_at_utc"),
        "intel_freshness_ok": intel["freshness"].get("ok"),
    }
    export = {
        "schema_version": 1,
        "generated_at_utc": generated_at,
        "run_id": ctx["run_id"],
        "source_commit": ctx["source_commit"],
        "source_identity": ctx["source_identity"],
        "toolkit_revision": ctx["toolkit_revision"],
        "complete": complete,
        "selected_artifact_ids": {"060": sel_060, "070": used_070, "080": used_080},
        "coverage": coverage,
        "readiness": {
            "intel": intel,
            "assessment": {
                "complete": complete,
                "missing_assessments": missing,
                "stale_assessments": stale,
                "incomplete_assessments": incomplete,
            },
            "provenance_080": {
                "findings_with_plans": len(used_080),
                "stale_plans": stale_plans,
            },
            "readiness_ok": complete and intel_ok and not stale_plans,
            "policy_check_failed": policy_check_failed,
            "limitations": limitations,
        },
        "findings": findings,
        "dismissed_candidates": dismissed,
    }
    inputs = [sel_060, *used_070.values(), *used_080.values()]
    if intel["artifact_id"] and intel["freshness"].get("ok") is not None:
        inputs.append(intel["artifact_id"])
    return export, list(dict.fromkeys(inputs))


def _write_findings_export(
    ctx: dict[str, Any],
    manifest: dict[str, Any],
    hours: float = 24.0,
    source: str = "default",
    require_fresh: bool = False,
) -> dict[str, Any]:
    """Build, schema-check, exclusively write, and register a findings export (lock held)."""
    export, inputs = _build_export(ctx, manifest, hours, source, require_fresh)
    validate_schema(export, load_schema(ctx["policy_prefix"], "findings-export.schema.json"), "export")
    version = _next_findings_version(manifest)
    path = os.path.join(ctx["reports_dir"], f"findings-v{version}.json")
    _validate_destination_path(path, ctx["reports_dir"], ctx)
    _write_json_exclusive(path, export)
    sha = sha256_file(path)
    manifest["artifacts"].append({
        "id": f"findings-v{version}",
        "kind": "findings_export",
        "version": version,
        "path": os.path.relpath(path, ctx["run_root"]),
        "sha256": sha,
        "source_commit": ctx["source_commit"],
        "toolkit_revision": ctx["toolkit_revision"],
        "producer": "hermes-vps-artifacts/generate-findings",
        "created_at_utc": _utcnow(),
        "completion_status": "complete" if export["complete"] else "partial",
        "prerequisite_artifacts": inputs,
        "prerequisite_hashes": prerequisite_hashes(manifest, inputs),
        "complete": export["complete"],
        "intel_freshness_ok": export["coverage"]["intel_freshness_ok"],
        "policy_check_failed": export["readiness"]["policy_check_failed"],
    })
    previous = manifest["selected_by_phase"].get("findings")
    manifest["selected_by_phase"]["findings"] = f"findings-v{version}"
    try:
        write_json_atomic(ctx["manifest_path"], manifest)
    except OSError as exc:
        # Never leave an unregistered export behind: a retry must be able to reuse this version.
        manifest["artifacts"].pop()
        manifest["selected_by_phase"]["findings"] = previous
        os.unlink(path)
        raise ValidationError(f"index write failed; unregistered export {path} removed: {exc}") from exc
    return {"path": path, "sha": sha, "version": version, "export": export}


def _consolidation_due(manifest: dict[str, Any], run_root: str) -> bool:
    """Defined completion point: every triaged candidate has a complete, current 070."""
    try:
        _, candidate_ids = triage_candidate_ids(manifest, run_root)
    except ValidationError:
        return False
    sbs_070 = manifest.get("selected_by_subject", {}).get("070", {})
    return bool(candidate_ids) and all(
        sbs_070.get(cid) and not artifact_problems(manifest, run_root, sbs_070[cid])
        for cid in candidate_ids
    )


EXIT_CONSOLIDATION_FAILED = 3


def _maybe_consolidate(
    ctx: dict[str, Any], manifest: dict[str, Any], run_json_path: str, registered_id: str
) -> int:
    """Run generate-findings automatically at the completion point.

    Called by _commit_bundle with the RunLock already held; it does not acquire
    the lock itself (RunLock refuses nested acquisition).  A failure here never
    unregisters the phase-070 artifact: it returns EXIT_CONSOLIDATION_FAILED and
    prints an export-only retry.
    """
    if not _consolidation_due(manifest, ctx["run_root"]):
        return 0
    try:
        _, inputs = _build_export(ctx, manifest, 24.0, "default", False)
        latest = find_artifact(manifest, manifest["selected_by_phase"].get("findings"))
        if latest is not None and latest.get("prerequisite_artifacts") == inputs:
            print(f"(findings already consolidated in {latest['id']}; no new export)", file=sys.stderr)
            return 0
        print(
            "All phase-070 assessments are complete; consolidating findings automatically.",
            file=sys.stderr,
        )
        result = _write_findings_export(ctx, manifest)
    except ValidationError as exc:
        print(
            f"error: automatic findings consolidation FAILED: {exc}\n"
            f"  The phase-070 artifact {registered_id!r} IS registered and selected; do not re-register it.\n"
            f"  Only the findings export is missing.  Export-only retry:\n"
            f"  {_recovery_command(ctx, 'generate-findings', ['--run-json', run_json_path])}",
            file=sys.stderr,
        )
        return EXIT_CONSOLIDATION_FAILED
    _print_findings_handoff_prompt(ctx, result, run_json_path)
    return 0


def cmd_generate_findings(args: argparse.Namespace, run_json_path: str) -> int:
    """Consolidate selected phase-070 payloads into a findings export snapshot.

    Exit codes:
      0  — success (export written and registered)
      1  — fatal error (nothing written or registered)
      2  — policy check failed (--require-fresh-intel, export still written and registered)
    """
    try:
        ctx = validate_run(load_json(run_json_path), expected_policy_prefix=None)
    except ValidationError as exc:
        die(str(exc))
    if not os.path.isfile(ctx["manifest_path"]):
        die("manifest.json does not exist; no artifacts registered yet")
    hours = args.freshness_hours if args.freshness_hours is not None else 24.0
    source = "cli" if args.freshness_hours is not None else "default"

    with RunLock(ctx["run_root"]):
        try:
            manifest = _load_or_init_manifest(ctx["manifest_path"], ctx)
            result = _write_findings_export(ctx, manifest, hours, source, args.require_fresh_intel)
        except ValidationError as exc:
            die(str(exc))

    readiness = result["export"]["readiness"]
    if readiness["limitations"]:
        print("WARNING: readiness limitations:\n" + "\n".join(
            f"  {lim}" for lim in readiness["limitations"]), file=sys.stderr)
    _print_findings_handoff_prompt(ctx, result, run_json_path)
    if readiness["policy_check_failed"]:
        print(
            "\nPOLICY CHECK FAILED: --require-fresh-intel is set but intelligence is not fresh.\n"
            f"  Findings export was written and registered: findings-v{result['version']}\n"
            "  This is a policy gate failure (exit 2), not a JSON write or registration failure.\n"
            "  To remediate: re-collect intelligence, revise the phase-040 artifact,\n"
            "  then re-run generate-findings.",
            file=sys.stderr,
        )
        return 2
    return 0


def _print_findings_handoff_prompt(
    ctx: dict[str, Any], result: dict[str, Any], run_json_path: str
) -> None:
    export = result["export"]
    coverage = export["coverage"]
    completeness = "COMPLETE" if export["complete"] else "PARTIAL"
    review_bin = os.path.join(ctx["policy_prefix"], "bin", "hermes-vps-review")
    print(f"""\
======== hermesVPS FINDINGS HANDOFF PROMPT (generate-findings) ========
NOTE: Structural/hash checks do not prove factual correctness of findings.
NOTE: A partial export is NOT a complete remediation handoff.

Assessment status:  {completeness}
Findings file:      {result['path']}
Findings SHA-256:   {result['sha']}
Version:            findings-v{result['version']}
Run ID:             {ctx['run_id']}
Source commit:      {ctx['source_commit']}

Coverage:
  Total candidates:   {coverage['total_candidates']}
  Assessed:           {coverage['assessed']}
  Missing:            {coverage['missing_assessments'] or '(none)'}
  Stale:              {coverage['stale_assessments'] or '(none)'}
  Incomplete/blocked: {coverage['incomplete_assessments'] or '(none)'}

HANDOFF INSTRUCTIONS:
  1. Verify the source commit and findings SHA-256 above are accurate.
  2. Attach or paste the full contents of the findings file to the remediation agent.
  3. Phase 080 (optional, one candidate per invocation) is keyed by candidate_id:
       {review_bin} --phase 080 --run-json {run_json_path} --trigger-input <candidate_id>
  4. If any assessments are missing, stale, or incomplete, resolve them before
     treating this export as a COMPLETE remediation handoff.

STOP. Do not start remediation without a separate explicit human request.
======== end findings handoff prompt ========
""")


# ---------------------------------------------------------------------------
# Subcommand: validate-findings
# ---------------------------------------------------------------------------

def cmd_validate_findings(args: argparse.Namespace, run_json_path: str) -> int:
    """Read-only: validate a findings export against the full schema and run identity."""
    try:
        ctx = validate_run(load_json(run_json_path), expected_policy_prefix=None)
    except ValidationError as exc:
        die(str(exc))

    findings_file = args.findings_file
    if not os.path.isabs(findings_file):
        die("--findings-file must be an absolute path")
    if not os.path.isfile(findings_file):
        die(f"--findings-file not found: {findings_file}")

    try:
        export = load_json(findings_file)
        validate_schema(export, load_schema(ctx["policy_prefix"], "findings-export.schema.json"), "export")
    except ValidationError as exc:
        die(f"findings file failed schema validation: {exc}")
    for key, expected in (
        ("run_id", ctx["run_id"]),
        ("source_commit", ctx["source_commit"]),
        ("source_identity", ctx["source_identity"]),
    ):
        if export[key] != expected:
            die(f"findings {key} {export[key]!r} does not match run.json {expected!r}")
    status = "COMPLETE" if export["complete"] else "PARTIAL"
    print(f"findings file validates OK\n  status:  {status}\n  file:    {findings_file}")
    return 0


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

class _Once(argparse.Action):
    """Reject repeated single-value flags."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        if getattr(namespace, self.dest, None) is not None:
            parser.error(f"{option_string} may only be specified once")
        setattr(namespace, self.dest, values)


def _add_run_json(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--run-json",
        required=True,
        action=_Once,
        help="Absolute path to operator-prepared run.json",
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    top = argparse.ArgumentParser(
        description=(
            "hermesVPS artifact helper — sole writer of manifest.json. "
            "Subcommands: register, accept, revise, selected, generate-findings, validate-findings."
        )
    )
    sub = top.add_subparsers(dest="subcommand", required=True)

    # --- register ---
    p_reg = sub.add_parser(
        "register",
        help="Register a finalized report; auto-selects next version.",
        description=(
            "Register a finalized report bundle.  Exit codes: 0 registered; 1 not registered; "
            "3 phase-070 registered but automatic findings consolidation failed "
            "(retry generate-findings only)."
        ),
    )
    _add_run_json(p_reg)
    p_reg.add_argument("--phase", required=True, action=_Once, help="Phase (e.g. 010)")
    p_reg.add_argument(
        "--source-report",
        required=True,
        action=_Once,
        help="Absolute path to the finalized report file to register",
    )
    p_reg.add_argument(
        "--subject-id",
        default=None,
        action=_Once,
        help="Subject identifier (050: priority_area; 070/080: candidate_id from phase-060)",
    )
    p_reg.add_argument(
        "--payload-json",
        default=None,
        action=_Once,
        help="Absolute path to structured JSON payload sidecar (required for 040/060/070/080)",
    )

    # --- accept ---
    p_acc = sub.add_parser(
        "accept",
        help="Record a second-opinion ACCEPT; does not change selection.",
    )
    _add_run_json(p_acc)
    p_acc.add_argument(
        "--artifact-id",
        required=True,
        action=_Once,
        help="Exact artifact ID to record ACCEPT against",
    )
    p_acc.add_argument(
        "--reviewer-identity",
        required=True,
        action=_Once,
        help="Declared reviewer identity (stored as declared; not authenticated)",
    )
    p_acc.add_argument(
        "--review-file",
        default=None,
        action=_Once,
        help="Optional absolute path to reviewer's written commentary file (SHA-256 recorded)",
    )

    # --- revise ---
    p_rev = sub.add_parser(
        "revise",
        help="Import revised report; copies to reports/, supersedes prior, updates selection.",
    )
    _add_run_json(p_rev)
    p_rev.add_argument(
        "--source-report",
        required=True,
        action=_Once,
        help="Absolute path to the revised report file (may be outside reports/)",
    )
    p_rev.add_argument(
        "--supersedes",
        required=True,
        action=_Once,
        help="Artifact ID being superseded",
    )
    p_rev.add_argument(
        "--reviewer-identity",
        required=True,
        action=_Once,
        help="Declared reviewer identity",
    )
    p_rev.add_argument(
        "--subject-id",
        default=None,
        action=_Once,
        help="Subject identifier (inferred from the superseded artifact; must match if given)",
    )
    p_rev.add_argument(
        "--payload-json",
        default=None,
        action=_Once,
        help=(
            "Absolute path to updated structured payload JSON "
            "(required when superseding a payload-required artifact, e.g. phase 070)"
        ),
    )

    # --- selected ---
    p_sel = sub.add_parser(
        "selected",
        help="Read-only: print selected artifact(s) and verify SHA-256.",
    )
    _add_run_json(p_sel)
    p_sel.add_argument(
        "--phase",
        default=None,
        action=_Once,
        help="Filter to a specific phase (e.g. 010); omit for all phases",
    )

    # --- generate-findings ---
    p_gf = sub.add_parser(
        "generate-findings",
        help=(
            "Consolidate selected phase-070 payloads into a findings export snapshot. "
            "Reads the phase-060 triage inventory for candidate list. "
            "Evaluates intelligence freshness from the selected phase-040 payload. "
            "Registers result as a findings_export artifact. "
            "Exit 0=success; 1=error; 2=policy check failed (--require-fresh-intel)."
        ),
    )
    _add_run_json(p_gf)
    p_gf.add_argument(
        "--require-fresh-intel",
        action="store_true",
        default=False,
        help=(
            "Fail with exit code 2 (not 1) if intelligence freshness requirement is not met. "
            "The export is still written and registered. "
            "This is a policy gate, not a write failure."
        ),
    )
    p_gf.add_argument(
        "--freshness-hours",
        type=float,
        default=None,
        help="Override freshness threshold in hours (default: 24.0).",
    )

    # --- validate-findings ---
    p_vf = sub.add_parser(
        "validate-findings",
        help="Read-only: validate a findings export file against the schema.",
    )
    _add_run_json(p_vf)
    p_vf.add_argument(
        "--findings-file",
        required=True,
        action=_Once,
        help="Absolute path to a findings-vN.json file to validate",
    )

    return top.parse_args(argv)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    if sys.version_info < (3, 8):
        die("Python 3.8+ required")

    args = parse_args(argv)

    run_json_raw: str = args.run_json
    if not os.path.isabs(run_json_raw):
        die("--run-json must be an absolute path")
    if ".." in run_json_raw.split(os.sep):
        die("--run-json must not contain '..' segments")
    run_json_path = os.path.realpath(run_json_raw)
    if not os.path.isfile(run_json_path):
        die(f"--run-json not a file: {run_json_path}")

    try:
        if args.subcommand == "register":
            return cmd_register(args, run_json_path)
        elif args.subcommand == "accept":
            return cmd_accept(args, run_json_path)
        elif args.subcommand == "revise":
            return cmd_revise(args, run_json_path)
        elif args.subcommand == "selected":
            return cmd_selected(args, run_json_path)
        elif args.subcommand == "generate-findings":
            return cmd_generate_findings(args, run_json_path)
        elif args.subcommand == "validate-findings":
            return cmd_validate_findings(args, run_json_path)
        else:
            die(f"unknown subcommand: {args.subcommand!r}")
    except ValidationError as exc:
        die(str(exc))
    return 0
