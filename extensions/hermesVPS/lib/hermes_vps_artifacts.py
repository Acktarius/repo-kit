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
    expect_str,
    expect_type,
    is_within,
    load_json,
    realpath_abs,
    resolve_selected_prereqs,
    sha256_file,
    validate_manifest_identity,
    validate_run,
    write_json_atomic,
)
from lib.hermes_vps_phases import (  # noqa: E402
    PHASE_TABLE,
    REPEATED_PHASES,
    PAYLOAD_PHASES,
    VALID_PHASES,
)

ARTIFACT_ID_RE = __import__("re").compile(r"^phase-[0-9]{3}-hermes-v[0-9]+$")
PAYLOAD_ID_RE = __import__("re").compile(r"^payload-[0-9]{3}-[^/]+$")
CANDIDATE_ID_RE = __import__("re").compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


# ---------------------------------------------------------------------------
# Per-run exclusive lock
# ---------------------------------------------------------------------------

class RunLock:
    """Advisory exclusive lock on <run_root>/.hermes-artifacts.lock.

    This is a Unix fcntl advisory lock — not an OS security boundary
    against non-cooperating writers.
    """

    def __init__(self, run_root: str) -> None:
        self._path = os.path.join(run_root, ".hermes-artifacts.lock")
        self._fh: Any = None

    def __enter__(self) -> "RunLock":
        self._fh = open(self._path, "w", encoding="utf-8")
        fcntl.flock(self._fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *_: object) -> None:
        if self._fh is not None:
            try:
                fcntl.flock(self._fh, fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None


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
        # subject-scoped selection for repeated phases (070, 080)
        # structure: {"070": {"C-001": "phase-070-hermes-v1"}, "080": {"SG-001": "phase-080-hermes-v1"}}
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


def _find_by_sha(manifest: dict[str, Any], phase: str, sha: str) -> dict[str, Any] | None:
    """Return the first phase artifact entry that matches sha, or None."""
    for art in manifest.get("artifacts", []):
        if (
            isinstance(art, dict)
            and art.get("kind") == "hermes_phase_report"
            and art.get("phase") == phase
            and art.get("sha256") == sha
        ):
            return art
    return None


def _find_by_id(manifest: dict[str, Any], artifact_id: str) -> dict[str, Any] | None:
    for art in manifest.get("artifacts", []):
        if isinstance(art, dict) and art.get("id") == artifact_id:
            return art
    return None


def _check_duplicate_id(manifest: dict[str, Any], artifact_id: str, sha: str) -> None:
    """Raise ValidationError if artifact_id already exists with a different SHA."""
    existing = _find_by_id(manifest, artifact_id)
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


def _update_subject_selection(
    manifest: dict[str, Any], phase: str, subject_id: str, artifact_id: str
) -> None:
    """Update selected_by_subject[phase][subject_id] = artifact_id."""
    sbs = manifest.setdefault("selected_by_subject", {})
    if not isinstance(sbs, dict):
        sbs = {}
        manifest["selected_by_subject"] = sbs
    if phase not in sbs or not isinstance(sbs[phase], dict):
        sbs[phase] = {}
    sbs[phase][subject_id] = artifact_id


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

If the second agent CANNOT access those local paths, you must provide:
  1. The full text of the report (paste or attach the file contents)
  2. The relevant artifact index entry (paste the JSON entry from manifest.json)
  3. Confirm the source commit and report SHA-256 above are accurate

Second-opinion commands (agent may run; not required for normal progression):
  ACCEPT (record review, no selection change):
    {artifacts_bin} accept \\
      --run-json {run_json_path} \\
      --artifact-id {artifact_id} \\
      --reviewer-identity "declared-name-or-id"

  REVISE (import corrected report, update selection):
    {artifacts_bin} revise \\
      --run-json {run_json_path} \\
      --source-report /absolute/path/to/revised.md \\
      --supersedes {artifact_id} \\
      --reviewer-identity "declared-name-or-id"

STOP. Do not start the next phase without a separate explicit human request.
======== end consultation prompt ========
"""
    print(text)


# ---------------------------------------------------------------------------
# Destination-path validation
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


def _saved_but_unregistered(
    final_path: str, sha: str, run_json_path: str, phase: str, reason: str
) -> None:
    print(
        f"error: Report saved at {final_path} (SHA-256: {sha}) but NOT registered.\n"
        f"Reason: {reason}\n"
        f"Safe retry: hermes-vps-artifacts register "
        f"--run-json {run_json_path} --phase {phase} --source-report {final_path}",
        file=sys.stderr,
    )


# ---------------------------------------------------------------------------
# Subcommand: register
# ---------------------------------------------------------------------------

def cmd_register(args: argparse.Namespace, run_json_path: str) -> int:  # noqa: C901
    """Register a finalized report; auto-selects next version."""
    data = load_json(run_json_path)
    try:
        ctx = validate_run(data, expected_policy_prefix=None)
    except ValidationError as exc:
        die(str(exc))

    phase = args.phase
    if phase not in VALID_PHASES:
        die(f"unknown phase {phase!r}; valid phases: {', '.join(sorted(VALID_PHASES))}")

    phase_info = PHASE_TABLE[phase]

    # subject_id required for repeated phases
    subject_id: str | None = getattr(args, "subject_id", None)
    if phase_info.subject_id_required:
        if not subject_id:
            die(f"phase {phase} requires --subject-id ({phase_info.trigger_label})")
        subject_id = subject_id.strip()
        if not CANDIDATE_ID_RE.match(subject_id):
            die(f"--subject-id must match ^[A-Za-z0-9][A-Za-z0-9._-]{{0,127}}$ (got {subject_id!r})")
    elif subject_id:
        die(f"phase {phase} does not use --subject-id; remove that flag")

    # payload_json optional for payload phases
    payload_json_path: str | None = getattr(args, "payload_json", None)
    if phase_info.payload_required and not payload_json_path:
        die(f"phase {phase} requires --payload-json ({phase_info.phase_name} structured payload)")
    if not phase_info.payload_required and payload_json_path:
        die(f"phase {phase} does not use --payload-json; remove that flag")

    source_report = args.source_report
    if not os.path.isabs(source_report):
        die("--source-report must be an absolute path")
    if not os.path.isfile(source_report):
        die(f"--source-report not found: {source_report}")

    if payload_json_path:
        if not os.path.isabs(payload_json_path):
            die("--payload-json must be an absolute path")
        if not os.path.isfile(payload_json_path):
            die(f"--payload-json not found: {payload_json_path}")
        # Validate it's valid JSON
        try:
            _load_payload_json(payload_json_path, phase, subject_id)
        except ValidationError as exc:
            die(str(exc))

    run_root = ctx["run_root"]
    reports_dir = ctx["reports_dir"]
    manifest_path = ctx["manifest_path"]

    with RunLock(run_root):
        try:
            manifest = _load_or_init_manifest(manifest_path, ctx)
        except ValidationError as exc:
            die(str(exc))

        # Compute SHA-256 of source report
        try:
            src_sha = sha256_file(source_report)
        except OSError as exc:
            die(f"cannot read --source-report: {exc}")

        # Idempotency: already registered with same SHA for this phase?
        existing = _find_by_sha(manifest, phase, src_sha)
        if existing is not None:
            # For repeated phases, also check subject_id matches
            if subject_id is not None and existing.get("subject_id") != subject_id:
                # Same SHA registered under a different subject — that's fine; allow re-registration
                pass
            else:
                existing_rel = existing.get("path", "")
                existing_abs = os.path.join(run_root, existing_rel)
                print(
                    f"(idempotent: artifact {existing['id']!r} already registered "
                    f"with this SHA-256; no changes made)",
                    file=sys.stderr,
                )
                _print_consult_prompt(
                    ctx,
                    existing["id"],
                    existing_abs,
                    src_sha,
                    manifest_path,
                    run_json_path,
                    phase,
                    existing["version"],
                    subject_id=existing.get("subject_id"),
                )
                return 0

        # Auto-select next version
        version = _next_version(manifest, phase)
        artifact_id = f"phase-{phase}-hermes-v{version}"
        final_name = f"phase-{phase}-hermes-v{version}.md"
        final_path = os.path.join(reports_dir, final_name)

        # Check for same ID with different content
        try:
            _check_duplicate_id(manifest, artifact_id, src_sha)
            _check_duplicate_phase_version(manifest, phase, version, artifact_id)
        except ValidationError as exc:
            die(str(exc))

        # Validate final_path is inside reports_dir and not source/policy
        try:
            _validate_destination_path(final_path, reports_dir, ctx)
        except ValidationError as exc:
            die(str(exc))

        # Handle retry: final path already exists
        if os.path.lexists(final_path):
            if os.path.isfile(final_path):
                existing_sha = sha256_file(final_path)
                if existing_sha == src_sha:
                    pass  # Retry scenario: file already copied; just register
                else:
                    die(
                        f"report path already exists with different content: {final_path}\n"
                        "Collision — cannot overwrite. "
                        "If this is a new revision, use 'hermes-vps-artifacts revise'."
                    )
            else:
                die(f"destination path exists but is not a regular file: {final_path}")
        else:
            try:
                shutil.copy2(source_report, final_path)
            except OSError as exc:
                die(f"failed to copy report to {final_path}: {exc}")

        # Verify SHA after copy
        try:
            final_sha = sha256_file(final_path)
        except OSError as exc:
            _saved_but_unregistered(final_path, src_sha, run_json_path, phase, str(exc))
            return 1
        if final_sha != src_sha:
            _saved_but_unregistered(
                final_path,
                src_sha,
                run_json_path,
                phase,
                f"SHA mismatch after copy: expected={src_sha} got={final_sha}",
            )
            return 1

        # Handle payload JSON if provided
        payload_rel: str | None = None
        payload_sha: str | None = None
        if payload_json_path:
            payload_fname = f"payload-{phase}-{subject_id}-v{version}.json"
            payload_dest = os.path.join(reports_dir, payload_fname)
            try:
                _validate_destination_path(payload_dest, reports_dir, ctx)
            except ValidationError as exc:
                die(str(exc))
            if not os.path.lexists(payload_dest):
                try:
                    shutil.copy2(payload_json_path, payload_dest)
                except OSError as exc:
                    die(f"failed to copy payload JSON to {payload_dest}: {exc}")
            payload_sha = sha256_file(payload_dest)
            payload_rel = os.path.relpath(payload_dest, run_root)

        # Relative path stored in manifest
        rel_path = os.path.relpath(final_path, run_root)

        # Phase-080 provenance: validate referenced artifact IDs/hashes against manifest
        extra_prereqs: list[str] = []
        if phase == "080" and payload_json_path:
            p080_payload = _load_payload_json(payload_json_path, "080", subject_id)
            intel_art_id = p080_payload.get("intel_artifact_id", "")
            intel_art_sha = p080_payload.get("intel_artifact_sha256", "")
            finding_art_id = p080_payload.get("assessed_finding_artifact_id", "")
            finding_art_sha = p080_payload.get("assessed_finding_sha256", "")

            # Validate intel artifact
            intel_art = _find_by_id(manifest, intel_art_id)
            if intel_art is None:
                die(
                    f"phase-080 payload references intel_artifact_id {intel_art_id!r} "
                    "which is not registered in manifest"
                )
            recorded_intel_sha = intel_art.get("payload_sha256") or intel_art.get("sha256", "")
            if intel_art_sha and recorded_intel_sha and intel_art_sha != recorded_intel_sha:
                die(
                    f"phase-080 payload intel_artifact_sha256 {intel_art_sha[:16]}… "
                    f"does not match manifest record {recorded_intel_sha[:16]}…"
                )

            # Validate assessed finding artifact
            finding_art = _find_by_id(manifest, finding_art_id)
            if finding_art is None:
                die(
                    f"phase-080 payload references assessed_finding_artifact_id {finding_art_id!r} "
                    "which is not registered in manifest"
                )
            recorded_finding_sha = finding_art.get("sha256", "")
            if finding_art_sha and recorded_finding_sha and finding_art_sha != recorded_finding_sha:
                die(
                    f"phase-080 payload assessed_finding_sha256 {finding_art_sha[:16]}… "
                    "does not match manifest record"
                )

            extra_prereqs = [intel_art_id, finding_art_id]
            # Warn if intel_artifact_id differs from current selected 040
            current_040 = manifest.get("selected_by_phase", {}).get("040")
            if current_040 and intel_art_id != current_040:
                print(
                    f"WARNING: phase-080 plan uses intel artifact {intel_art_id!r} but "
                    f"current selected phase-040 is {current_040!r}. "
                    "This mismatch will be detected by generate-findings.",
                    file=sys.stderr,
                )

        entry: dict[str, Any] = {
            "id": artifact_id,
            "kind": "hermes_phase_report",
            "phase": phase,
            "version": version,
            "path": rel_path,
            "sha256": final_sha,
            "source_commit": ctx["source_commit"],
            "toolkit_revision": ctx["toolkit_revision"],
            "producer": "hermes-vps-artifacts/register",
            "created_at_utc": _utcnow(),
            "completion_status": "complete",
            "prerequisite_artifacts": extra_prereqs,
            "supersedes": None,
            "reviews": [],
        }
        if subject_id is not None:
            entry["subject_id"] = subject_id
        if payload_rel is not None:
            entry["payload_path"] = payload_rel
            entry["payload_sha256"] = payload_sha

        manifest["artifacts"].append(entry)

        # Update selection: repeated phases use selected_by_subject, others use selected_by_phase
        if phase in REPEATED_PHASES and subject_id is not None:
            _update_subject_selection(manifest, phase, subject_id, artifact_id)
            # Also update selected_by_phase to the most recent for informational purposes;
            # not authoritative for repeated phases.
            manifest["selected_by_phase"][phase] = artifact_id
        else:
            manifest["selected_by_phase"][phase] = artifact_id

        try:
            write_json_atomic(manifest_path, manifest)
        except OSError as exc:
            _saved_but_unregistered(
                final_path, final_sha, run_json_path, phase, f"index write failed: {exc}"
            )
            return 1

    _print_consult_prompt(
        ctx, artifact_id, final_path, final_sha, manifest_path, run_json_path, phase, version,
        subject_id=subject_id,
    )
    return 0


def _load_payload_json(path: str, phase: str, subject_id: str | None) -> dict[str, Any]:
    """Load and minimally validate a structured payload JSON file."""
    try:
        data = load_json(path)
    except ValidationError as exc:
        raise ValidationError(f"--payload-json: {exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError("--payload-json: must be a JSON object")
    # Minimal structural check: must have schema_version and phase
    sv = data.get("schema_version")
    if not isinstance(sv, int) or sv < 1:
        raise ValidationError("--payload-json: schema_version must be a positive integer")
    recorded_phase = data.get("phase")
    if recorded_phase != phase:
        raise ValidationError(
            f"--payload-json: phase field {recorded_phase!r} != --phase {phase!r}"
        )
    # For repeated phases, verify subject_id is present
    if phase in REPEATED_PHASES:
        payload_subject_key = PHASE_TABLE[phase].trigger_label
        payload_subject = data.get(payload_subject_key) or data.get("subject_id")
        if payload_subject and subject_id and payload_subject != subject_id:
            raise ValidationError(
                f"--payload-json: {payload_subject_key} {payload_subject!r} "
                f"!= --subject-id {subject_id!r}"
            )

    # Phase-040 specific validation (vuln-intel-record)
    if phase == "040":
        valid_modes = {"live", "imported", "not_authorized", "partial"}
        mode = data.get("collection_mode", "")
        if mode not in valid_modes:
            raise ValidationError(
                f"--payload-json: collection_mode {mode!r} not in {sorted(valid_modes)}"
            )
        if "collected_at_utc" not in data:
            raise ValidationError("--payload-json: missing required field 'collected_at_utc'")
        if "providers" not in data or not isinstance(data.get("providers"), dict):
            raise ValidationError("--payload-json: missing or invalid 'providers' object")
        for pname in ("osv", "nvd", "cisa_kev"):
            if pname not in data["providers"]:
                raise ValidationError(f"--payload-json: missing provider {pname!r} in providers")

    # Phase-080 specific validation (plan provenance)
    if phase == "080":
        required_080 = (
            "intel_artifact_id", "intel_artifact_sha256",
            "assessed_finding_artifact_id", "assessed_finding_sha256",
            "intel_freshness_at_plan_time",
        )
        for field in required_080:
            val = data.get(field)
            if not val:
                raise ValidationError(
                    f"--payload-json: phase-080 plan requires non-empty field {field!r}"
                )
        # Validate freshness snapshot has required sub-fields
        freshness_snap = data.get("intel_freshness_at_plan_time", {})
        for sub in ("evaluated_at_utc", "effective_threshold_hours", "freshness_ok"):
            if sub not in freshness_snap:
                raise ValidationError(
                    f"--payload-json: intel_freshness_at_plan_time missing field {sub!r}"
                )

    return data


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

        entry = _find_by_id(manifest, artifact_id)
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

def cmd_revise(args: argparse.Namespace, run_json_path: str) -> int:  # noqa: C901
    """Import an external revised report, register it, update selection."""
    data = load_json(run_json_path)
    try:
        ctx = validate_run(data, expected_policy_prefix=None)
    except ValidationError as exc:
        die(str(exc))

    supersedes_id = args.supersedes.strip()
    reviewer = args.reviewer_identity.strip()
    if not reviewer:
        die("--reviewer-identity must not be empty")
    source_report = args.source_report
    if not os.path.isabs(source_report):
        die("--source-report must be an absolute path")
    if not os.path.isfile(source_report):
        die(f"--source-report not found: {source_report}")

    run_root = ctx["run_root"]
    reports_dir = ctx["reports_dir"]
    manifest_path = ctx["manifest_path"]

    with RunLock(run_root):
        if not os.path.isfile(manifest_path):
            die("manifest.json does not exist; no artifacts registered yet")
        try:
            manifest = _load_or_init_manifest(manifest_path, ctx)
        except ValidationError as exc:
            die(str(exc))

        prior = _find_by_id(manifest, supersedes_id)
        if prior is None:
            die(
                f"artifact {supersedes_id!r} not found in manifest; "
                "cannot supersede an unknown artifact"
            )

        phase = prior.get("phase", "")
        prior_subject = prior.get("subject_id")

        # Cross-subject supersession rejection: --supersedes must match subject_id if provided
        new_subject_id: str | None = getattr(args, "subject_id", None)
        if new_subject_id:
            new_subject_id = new_subject_id.strip()
        if prior_subject is not None and new_subject_id is not None:
            if new_subject_id != prior_subject:
                die(
                    f"cross-subject supersession rejected: prior artifact {supersedes_id!r} "
                    f"has subject_id {prior_subject!r} but --subject-id is {new_subject_id!r}; "
                    "supersedes must refer to the same phase and subject"
                )
        # Infer subject_id from prior if not explicitly provided
        if new_subject_id is None and prior_subject is not None:
            new_subject_id = prior_subject

        # Payload handling for revised artifacts
        payload_json_path: str | None = getattr(args, "payload_json", None)
        try:
            from hermes_vps_phases import PHASE_TABLE  # type: ignore[import]
            phase_info_for_revise = PHASE_TABLE.get(phase)
            payload_required_for_phase = (
                phase_info_for_revise is not None and phase_info_for_revise.payload_required
            )
        except ImportError:
            payload_required_for_phase = False
        if payload_required_for_phase and not payload_json_path:
            die(
                f"phase {phase} requires a structured payload; "
                "provide --payload-json for the revised artifact"
            )
        if payload_json_path:
            if not os.path.isabs(payload_json_path):
                die("--payload-json must be an absolute path")
            if not os.path.isfile(payload_json_path):
                die(f"--payload-json not found: {payload_json_path}")
            try:
                _load_payload_json(payload_json_path, phase, new_subject_id)
            except ValidationError as exc:
                die(str(exc))

        try:
            src_sha = sha256_file(source_report)
        except OSError as exc:
            die(f"cannot read --source-report: {exc}")

        # Check if this exact SHA is already registered (idempotent revise retry)
        existing = _find_by_sha(manifest, phase, src_sha)
        if existing is not None and existing["id"] != supersedes_id:
            # For repeated phases, check subject matches
            if new_subject_id is not None and existing.get("subject_id") != new_subject_id:
                pass  # Different subject — not an idempotent match
            else:
                existing_rel = existing.get("path", "")
                existing_abs = os.path.join(run_root, existing_rel)
                print(
                    f"(idempotent: revised artifact {existing['id']!r} already registered "
                    "with this SHA-256; no changes made)",
                    file=sys.stderr,
                )
                _print_consult_prompt(
                    ctx,
                    existing["id"],
                    existing_abs,
                    src_sha,
                    manifest_path,
                    run_json_path,
                    phase,
                    existing["version"],
                    subject_id=existing.get("subject_id"),
                )
                return 0

        version = _next_version(manifest, phase)
        artifact_id = f"phase-{phase}-hermes-v{version}"
        final_name = f"phase-{phase}-hermes-v{version}.md"
        final_path = os.path.join(reports_dir, final_name)

        try:
            _check_duplicate_id(manifest, artifact_id, src_sha)
            _check_duplicate_phase_version(manifest, phase, version, artifact_id)
            _validate_destination_path(final_path, reports_dir, ctx)
        except ValidationError as exc:
            die(str(exc))

        if os.path.lexists(final_path):
            if os.path.isfile(final_path):
                if sha256_file(final_path) == src_sha:
                    pass  # retry scenario
                else:
                    die(
                        f"destination already exists with different content: {final_path}"
                    )
            else:
                die(f"destination path exists but is not a regular file: {final_path}")
        else:
            try:
                shutil.copy2(source_report, final_path)
            except OSError as exc:
                die(f"failed to copy report to {final_path}: {exc}")

        try:
            final_sha = sha256_file(final_path)
        except OSError as exc:
            _saved_but_unregistered(final_path, src_sha, run_json_path, phase, str(exc))
            return 1
        if final_sha != src_sha:
            _saved_but_unregistered(
                final_path,
                src_sha,
                run_json_path,
                phase,
                f"SHA mismatch after copy: expected={src_sha} got={final_sha}",
            )
            return 1

        rel_path = os.path.relpath(final_path, run_root)

        review_record: dict[str, Any] = {
            "outcome": "REVISE",
            "artifact_id": artifact_id,
            "supersedes": supersedes_id,
            "reviewer_identity_declared": reviewer,
            "authenticated": False,
            "recorded_at_utc": _utcnow(),
        }

        # Copy payload for revised artifact if provided
        payload_path_rel: str | None = None
        payload_sha: str | None = None
        if payload_json_path:
            payload_fname = f"payload-{phase}-{new_subject_id}-v{version}.json"
            payload_dest = os.path.join(reports_dir, payload_fname)
            try:
                shutil.copy2(payload_json_path, payload_dest)
            except OSError as exc:
                die(f"failed to copy --payload-json to {payload_dest}: {exc}")
            try:
                payload_sha = sha256_file(payload_dest)
            except OSError as exc:
                die(f"cannot read copied payload: {exc}")
            payload_path_rel = os.path.relpath(payload_dest, run_root)

        entry: dict[str, Any] = {
            "id": artifact_id,
            "kind": "hermes_phase_report",
            "phase": phase,
            "version": version,
            "path": rel_path,
            "sha256": final_sha,
            "source_commit": ctx["source_commit"],
            "toolkit_revision": ctx["toolkit_revision"],
            "producer": "hermes-vps-artifacts/revise",
            "created_at_utc": _utcnow(),
            "completion_status": "complete",
            "prerequisite_artifacts": prior.get("prerequisite_artifacts", []),
            "supersedes": supersedes_id,
            "reviews": [review_record],
        }
        if new_subject_id is not None:
            entry["subject_id"] = new_subject_id
        if payload_path_rel is not None:
            entry["payload_path"] = payload_path_rel
            entry["payload_sha256"] = payload_sha

        manifest["artifacts"].append(entry)

        # Update selections
        if phase in REPEATED_PHASES and new_subject_id is not None:
            _update_subject_selection(manifest, phase, new_subject_id, artifact_id)
            manifest["selected_by_phase"][phase] = artifact_id
        else:
            manifest["selected_by_phase"][phase] = artifact_id

        try:
            write_json_atomic(manifest_path, manifest)
        except OSError as exc:
            _saved_but_unregistered(
                final_path, final_sha, run_json_path, phase, f"index write failed: {exc}"
            )
            return 1

    _print_consult_prompt(
        ctx, artifact_id, final_path, final_sha, manifest_path, run_json_path, phase, version,
        subject_id=new_subject_id,
    )
    print(
        f"Revised: {artifact_id!r} supersedes {supersedes_id!r}. "
        f"Selection updated to {artifact_id!r}. Original preserved.",
        file=sys.stderr,
    )
    return 0


# ---------------------------------------------------------------------------
# Subcommand: selected
# ---------------------------------------------------------------------------

def cmd_selected(args: argparse.Namespace, run_json_path: str) -> int:
    """Read-only: print selected artifact(s) and verify SHA-256."""
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
        # For repeated phases, use subject-scoped selection
        if ph in REPEATED_PHASES:
            subj_map = selected_by_subject.get(ph, {})
            if not subj_map:
                print(f"  phase {ph}: (no subject-scoped selections)")
                continue
            for subj_id, art_id in sorted(subj_map.items()):
                ok = ok and _print_artifact_status(manifest, run_root, ph, art_id, subject_id=subj_id)
        else:
            art_id = selected_by_phase.get(ph)
            if art_id is None:
                print(f"  phase {ph}: (no selection)")
                continue
            ok = ok and _print_artifact_status(manifest, run_root, ph, art_id)

    if not ok:
        print("\nerror: one or more selected artifacts failed verification", file=sys.stderr)
        return 1
    return 0


def _print_artifact_status(
    manifest: dict[str, Any],
    run_root: str,
    phase: str,
    art_id: str,
    subject_id: str | None = None,
) -> bool:
    entry = _find_by_id(manifest, art_id)
    subject_label = f" [{subject_id}]" if subject_id else ""
    if entry is None:
        print(
            f"  phase {phase}{subject_label}: ERROR — selected id {art_id!r} not in artifacts list",
            file=sys.stderr,
        )
        return False
    rel_path = entry.get("path", "")
    abs_path = os.path.join(run_root, rel_path)
    recorded_sha = entry.get("sha256", "")
    sha_status = "(no SHA recorded)"
    ok = True
    if recorded_sha and os.path.isfile(abs_path):
        actual = sha256_file(abs_path)
        if actual == recorded_sha:
            sha_status = f"SHA-256 OK ({recorded_sha[:16]}…)"
        else:
            sha_status = f"SHA-256 MISMATCH (recorded={recorded_sha[:16]}… actual={actual[:16]}…)"
            ok = False
    elif not os.path.isfile(abs_path):
        sha_status = "FILE MISSING"
        ok = False
    print(
        f"  phase {phase}{subject_label}: {art_id}\n"
        f"    path:   {abs_path}\n"
        f"    status: {entry.get('completion_status', '?')}\n"
        f"    {sha_status}"
    )
    return ok


# ---------------------------------------------------------------------------
# Subcommand: generate-findings
# ---------------------------------------------------------------------------

def _assess_intel_freshness_from_manifest(
    manifest: dict[str, Any],
    run_root: str,
    threshold_hours: float,
    threshold_source: str,
    at_utc: str | None = None,
) -> dict[str, Any]:
    """Load selected phase-040 payload and assess freshness. Returns readiness.intel dict."""
    try:
        from hermes_vps_intel import assess_freshness as _af  # type: ignore[import]
    except ImportError:
        return {
            "artifact_id": None,
            "freshness": {"ok": None, "limitations": ["hermes_vps_intel not importable"]},
            "coverage": {"notes": "intel library not available"},
        }

    sel_040 = manifest.get("selected_by_phase", {}).get("040")
    if not sel_040:
        return {
            "artifact_id": None,
            "freshness": {
                "ok": None,
                "evaluated_at_utc": at_utc or _utcnow(),
                "effective_threshold_hours": threshold_hours,
                "threshold_source": threshold_source,
                "limitations": ["no phase-040 artifact selected"],
            },
            "coverage": {"notes": "no vuln-intel evidence registered"},
        }

    art_040 = _find_by_id(manifest, sel_040)
    if art_040 is None:
        return {
            "artifact_id": sel_040,
            "freshness": {
                "ok": None,
                "limitations": [f"artifact {sel_040!r} not found in manifest"],
            },
            "coverage": {"notes": "selected 040 artifact not found"},
        }

    # Try to load payload
    payload_rel = art_040.get("payload_path")
    if not payload_rel:
        return {
            "artifact_id": sel_040,
            "freshness": {
                "ok": None,
                "limitations": ["phase-040 artifact has no payload_path"],
            },
            "coverage": {"notes": "no payload registered for 040"},
        }

    payload_abs = os.path.join(run_root, payload_rel)
    if not os.path.isfile(payload_abs):
        return {
            "artifact_id": sel_040,
            "freshness": {
                "ok": None,
                "limitations": [f"payload file missing: {payload_abs}"],
            },
            "coverage": {"notes": "payload file not found"},
        }

    # Verify payload SHA
    recorded_sha = art_040.get("payload_sha256", "")
    if recorded_sha:
        actual_sha = sha256_file(payload_abs)
        if actual_sha != recorded_sha:
            return {
                "artifact_id": sel_040,
                "freshness": {
                    "ok": None,
                    "limitations": [
                        f"payload SHA mismatch — stale or tampered: "
                        f"recorded={recorded_sha[:16]}… actual={actual_sha[:16]}…"
                    ],
                },
                "coverage": {"notes": "payload integrity check failed"},
            }

    try:
        with open(payload_abs, encoding="utf-8") as fh:
            intel_record = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "artifact_id": sel_040,
            "freshness": {"ok": None, "limitations": [f"payload read error: {exc}"]},
            "coverage": {"notes": "payload unreadable"},
        }

    freshness = _af(intel_record, threshold_hours, threshold_source, at_utc)

    providers = intel_record.get("providers", {})
    coverage_notes: list[str] = []
    for pname, pdata in providers.items():
        if isinstance(pdata, dict) and pdata.get("status") not in ("success", "no_match"):
            coverage_notes.append(f"{pname}: {pdata.get('status', 'unknown')}")

    return {
        "artifact_id": sel_040,
        "freshness": freshness,
        "coverage": {
            "osv_status": providers.get("osv", {}).get("status"),
            "nvd_status": providers.get("nvd", {}).get("status"),
            "cisa_kev_status": providers.get("cisa_kev", {}).get("status"),
            "total_matches": intel_record.get("coverage", {}).get("total_matches", 0),
            "kev_matches": intel_record.get("coverage", {}).get("kev_matches", 0),
            "collection_mode": intel_record.get("collection_mode"),
            "collected_at_utc": intel_record.get("collected_at_utc"),
            "limitations": coverage_notes,
        },
    }


def cmd_generate_findings(args: argparse.Namespace, run_json_path: str) -> int:  # noqa: C901
    """Consolidate all selected phase-070 payloads into a findings export snapshot.

    Exit codes:
      0  — success (export written and registered)
      1  — fatal error (nothing written or registered)
      2  — policy check failed (--require-fresh-intel, export still written and registered)
    """
    data = load_json(run_json_path)
    try:
        ctx = validate_run(data, expected_policy_prefix=None)
    except ValidationError as exc:
        die(str(exc))

    manifest_path = ctx["manifest_path"]
    run_root = ctx["run_root"]
    reports_dir = ctx["reports_dir"]
    policy_prefix = ctx["policy_prefix"]

    require_fresh_intel: bool = getattr(args, "require_fresh_intel", False)
    freshness_hours: float = getattr(args, "freshness_hours", None) or 24.0
    freshness_source = "cli" if getattr(args, "freshness_hours", None) else "default"

    if not os.path.isfile(manifest_path):
        die("manifest.json does not exist; no artifacts registered yet")

    with RunLock(run_root):
        try:
            manifest = _load_or_init_manifest(manifest_path, ctx)
        except ValidationError as exc:
            die(str(exc))

        # --- Assess intelligence freshness (phase 040 payload) ---
        generated_at = _utcnow()
        intel_readiness = _assess_intel_freshness_from_manifest(
            manifest, run_root, freshness_hours, freshness_source, at_utc=generated_at
        )
        intel_freshness_ok: bool = bool(intel_readiness.get("freshness", {}).get("ok"))
        intel_limitations: list[str] = intel_readiness.get("freshness", {}).get("limitations", [])
        coverage_limitations: list[str] = intel_readiness.get("coverage", {}).get("limitations", [])

        if intel_limitations or not intel_freshness_ok:
            lvl = "WARNING"
            print(
                f"{lvl}: intelligence freshness check:\n"
                + "\n".join(f"  {lim}" for lim in intel_limitations or ["no fresh intel"]),
                file=sys.stderr,
            )

        # --- Resolve phase 060 triage payload (defines candidate inventory) ---
        sel_060 = manifest.get("selected_by_phase", {}).get("060")
        if not sel_060:
            die("no selected phase-060 artifact; validate-and-triage must complete before generate-findings")
        art_060 = _find_by_id(manifest, sel_060)
        if art_060 is None:
            die(f"selected phase-060 artifact {sel_060!r} not found in manifest")
        triage_payload = _load_registered_payload(art_060, run_root, "060", None)
        candidates: list[dict[str, Any]] = triage_payload.get("candidates", [])
        if not isinstance(candidates, list):
            die("phase-060 triage payload: candidates must be a list")

        candidate_ids: list[str] = [c.get("candidate_id", "") for c in candidates if isinstance(c, dict)]
        candidate_ids = [c for c in candidate_ids if c]

        # --- Resolve selected 070 artifacts per candidate ---
        sbs_070: dict[str, str] = manifest.get("selected_by_subject", {}).get("070", {})

        assessed: list[str] = []
        missing_assessments: list[str] = []
        stale_assessments: list[str] = []
        findings: list[dict[str, Any]] = []
        dismissed: list[dict[str, Any]] = []

        errors: list[str] = []

        for cid in candidate_ids:
            art_070_id = sbs_070.get(cid)
            if art_070_id is None:
                missing_assessments.append(cid)
                continue
            art_070 = _find_by_id(manifest, art_070_id)
            if art_070 is None:
                errors.append(f"selected phase-070 artifact {art_070_id!r} for candidate {cid!r} not in manifest")
                continue

            # Verify SHA integrity
            rel_070 = art_070.get("path", "")
            abs_070 = os.path.join(run_root, rel_070)
            if not os.path.isfile(abs_070):
                errors.append(f"phase-070 artifact {art_070_id!r} report file missing: {abs_070}")
                stale_assessments.append(cid)
                continue
            recorded_sha = art_070.get("sha256", "")
            if recorded_sha:
                actual_sha = sha256_file(abs_070)
                if actual_sha != recorded_sha:
                    errors.append(
                        f"phase-070 artifact {art_070_id!r} SHA-256 mismatch "
                        f"(recorded={recorded_sha[:16]}… actual={actual_sha[:16]}…)"
                    )
                    stale_assessments.append(cid)
                    continue

            # Load the structured finding payload
            try:
                finding_payload = _load_registered_payload(art_070, run_root, "070", cid)
            except ValidationError as exc:
                errors.append(f"candidate {cid!r}: {exc}")
                continue

            proposed = finding_payload.get("proposed_finding", {})
            disposition = finding_payload.get("assessment_disposition", "unknown")

            if disposition in ("dismissed", "rejected"):
                dismissed.append({
                    "candidate_id": cid,
                    "disposition": disposition,
                    "rationale": finding_payload.get("assessment_rationale", ""),
                    "source_artifact": art_070_id,
                })
            elif disposition in ("confirmed", "suspected", "needs-investigation", "blocked"):
                # Resolve optional phase-080 plan for this finding
                finding_id = proposed.get("id")
                plan_artifact_id: str | None = None
                if finding_id:
                    plan_artifact_id = manifest.get("selected_by_subject", {}).get("080", {}).get(finding_id)

                finding_entry: dict[str, Any] = {
                    "candidate_id": cid,
                    "finding_id": finding_id,
                    "assessment_disposition": disposition,
                    "assessment_rationale": finding_payload.get("assessment_rationale", ""),
                    "proposed_record": _extract_canonical_fields(proposed),
                    "affected_components": finding_payload.get("affected_components", []),
                    "impact": finding_payload.get("impact", ""),
                    "likelihood": finding_payload.get("likelihood", ""),
                    "evidence": finding_payload.get("evidence", []),
                    "unknowns": finding_payload.get("unknowns", []),
                    "blockers": finding_payload.get("blockers", []),
                    "source_artifact": art_070_id,
                    "source_commit": art_070.get("source_commit", ctx["source_commit"]),
                    "remediation_plan_artifact": plan_artifact_id,
                }
                # Explicitly never mark a finding fixed merely because a remediation plan exists
                if plan_artifact_id and finding_entry["proposed_record"].get("status") == "fixed":
                    finding_entry["proposed_record"]["status"] = "open"
                    finding_entry["_note"] = (
                        "status reset from 'fixed' to 'open': a remediation plan does not "
                        "constitute a fix; status must be updated only after verified remediation"
                    )
                findings.append(finding_entry)
                assessed.append(cid)
            else:
                missing_assessments.append(cid)

        if errors:
            for err in errors:
                print(f"error: {err}", file=sys.stderr)

        assessment_complete = (
            len(missing_assessments) == 0
            and len(stale_assessments) == 0
            and not errors
        )
        complete = assessment_complete

        # --- Phase-080 provenance check: detect intel_artifact_id mismatches ---
        sbs_080: dict[str, str] = manifest.get("selected_by_subject", {}).get("080", {})
        sel_040 = manifest.get("selected_by_phase", {}).get("040")
        prov_mismatched_intel: list[str] = []
        prov_limitations: list[str] = []

        for finding_sid, plan_art_id in sbs_080.items():
            plan_art = _find_by_id(manifest, plan_art_id)
            if plan_art is None:
                continue
            plan_payload_rel = plan_art.get("payload_path")
            if not plan_payload_rel:
                continue
            plan_payload_abs = os.path.join(run_root, plan_payload_rel)
            if not os.path.isfile(plan_payload_abs):
                continue
            try:
                with open(plan_payload_abs, encoding="utf-8") as fh:
                    plan_payload = json.load(fh)
            except (json.JSONDecodeError, OSError):
                continue
            plan_intel_id = plan_payload.get("intel_artifact_id")
            if plan_intel_id and sel_040 and plan_intel_id != sel_040:
                prov_mismatched_intel.append(finding_sid)
                prov_limitations.append(
                    f"finding {finding_sid!r}: plan used intel {plan_intel_id!r} "
                    f"but current selected 040 is {sel_040!r}; "
                    "reassessment recommended before declaring plan fully current"
                )

        if prov_limitations:
            for lim in prov_limitations:
                print(f"WARNING: {lim}", file=sys.stderr)

        # --- Build multi-field readiness object ---
        readiness_limitations: list[str] = []
        readiness_limitations.extend(intel_limitations)
        readiness_limitations.extend(coverage_limitations)
        if not assessment_complete:
            if missing_assessments:
                readiness_limitations.append(
                    f"missing assessments for: {', '.join(missing_assessments)}"
                )
            if stale_assessments:
                readiness_limitations.append(
                    f"stale assessments for: {', '.join(stale_assessments)}"
                )
        readiness_limitations.extend(prov_limitations)

        readiness: dict[str, Any] = {
            "intel": intel_readiness,
            "assessment": {
                "complete": assessment_complete,
                "missing_assessments": missing_assessments,
                "stale_assessments": stale_assessments,
            },
            "provenance_080": {
                "findings_with_plans": len(sbs_080),
                "mismatched_intel": prov_mismatched_intel,
                "limitations": prov_limitations,
            },
            "readiness_ok": (
                assessment_complete
                and intel_freshness_ok
                and not prov_mismatched_intel
            ),
            "policy_check_failed": False,  # updated below if --require-fresh-intel
            "limitations": readiness_limitations,
        }

        if not assessment_complete:
            print(
                "WARNING: findings export is PARTIAL:\n"
                f"  missing assessments: {missing_assessments}\n"
                f"  stale assessments:   {stale_assessments}\n"
                "  A partial export is NOT a complete remediation handoff.",
                file=sys.stderr,
            )

        coverage = {
            "total_candidates": len(candidate_ids),
            "assessed": len(assessed),
            "missing_assessments": missing_assessments,
            "stale_assessments": stale_assessments,
            "complete": assessment_complete,
            "intel_collected_at_utc": intel_readiness.get("coverage", {}).get("collected_at_utc"),
            "intel_freshness_ok": intel_freshness_ok,
        }

        version = _next_findings_version(manifest)
        findings_fname = f"findings-v{version}.json"
        findings_path = os.path.join(reports_dir, findings_fname)

        export: dict[str, Any] = {
            "schema_version": 1,
            "generated_at_utc": generated_at,
            "run_id": ctx["run_id"],
            "source_commit": ctx["source_commit"],
            "source_identity": ctx["source_identity"],
            "toolkit_revision": ctx["toolkit_revision"],
            "complete": complete,
            "selected_artifact_ids": {
                "060": sel_060,
                "070": dict(sbs_070),
                "080": dict(sbs_080),
            },
            "coverage": coverage,
            "readiness": readiness,
            "findings": findings,
            "dismissed_candidates": dismissed,
        }

        try:
            write_json_atomic(findings_path, export)
        except OSError as exc:
            die(f"failed to write findings export: {exc}")

        findings_sha = sha256_file(findings_path)
        findings_rel = os.path.relpath(findings_path, run_root)

        # Determine prerequisite artifacts
        prereq_ids: list[str] = [sel_060] + list(sbs_070.values())
        prereq_ids = list(dict.fromkeys(prereq_ids))  # deduplicate, preserve order

        # Apply --require-fresh-intel policy check
        policy_check_failed = require_fresh_intel and not intel_freshness_ok
        if policy_check_failed:
            readiness["policy_check_failed"] = True
            export["readiness"] = readiness
            # Re-write export with updated readiness to reflect policy failure
            try:
                write_json_atomic(findings_path, export)
            except OSError as exc:
                die(f"failed to re-write findings export: {exc}")
            findings_sha = sha256_file(findings_path)

        fe_entry: dict[str, Any] = {
            "id": f"findings-v{version}",
            "kind": "findings_export",
            "version": version,
            "path": findings_rel,
            "sha256": findings_sha,
            "source_commit": ctx["source_commit"],
            "toolkit_revision": ctx["toolkit_revision"],
            "producer": "hermes-vps-artifacts/generate-findings",
            "created_at_utc": _utcnow(),
            "completion_status": "complete" if complete else "partial",
            "prerequisite_artifacts": prereq_ids,
            "complete": complete,
            "intel_freshness_ok": intel_freshness_ok,
            "policy_check_failed": policy_check_failed,
        }

        manifest["artifacts"].append(fe_entry)
        manifest["selected_by_phase"]["findings"] = f"findings-v{version}"

        try:
            write_json_atomic(manifest_path, manifest)
        except OSError as exc:
            die(f"failed to update manifest: {exc}")

    _print_findings_handoff_prompt(
        ctx, findings_path, findings_sha, version, complete, coverage, run_json_path
    )

    if policy_check_failed:
        print(
            "\nPOLICY CHECK FAILED: --require-fresh-intel is set but intelligence is stale.\n"
            f"  Findings export was written and registered: findings-v{version}\n"
            "  The export exists and contains valid findings.\n"
            "  This is a policy gate failure (exit 2), not a JSON write or registration failure.\n"
            "  To remediate: re-run hermes-vps-collect-intel, revise the phase-040 artifact,\n"
            "  then re-run generate-findings.",
            file=sys.stderr,
        )
        return 2  # Policy check failure; distinct from error (1)

    return 0


def _load_registered_payload(
    artifact_entry: dict[str, Any],
    run_root: str,
    phase: str,
    subject_id: str | None,
) -> dict[str, Any]:
    """Load and return the JSON payload for a registered artifact."""
    payload_path_rel = artifact_entry.get("payload_path")
    if not payload_path_rel:
        raise ValidationError(
            f"artifact {artifact_entry.get('id')!r} has no registered payload; "
            f"phase {phase} requires a structured payload registered with --payload-json"
        )
    payload_abs = os.path.join(run_root, payload_path_rel)
    if not os.path.isfile(payload_abs):
        raise ValidationError(
            f"registered payload file not found: {payload_abs}"
        )
    recorded_sha = artifact_entry.get("payload_sha256", "")
    if recorded_sha:
        actual_sha = sha256_file(payload_abs)
        if actual_sha != recorded_sha:
            raise ValidationError(
                f"payload SHA-256 mismatch for {artifact_entry.get('id')!r}: "
                f"recorded={recorded_sha[:16]}… actual={actual_sha[:16]}…"
            )
    try:
        payload = load_json(payload_abs)
    except ValidationError as exc:
        raise ValidationError(f"cannot read payload for {artifact_entry.get('id')!r}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValidationError(f"payload for {artifact_entry.get('id')!r} must be a JSON object")
    return payload


_CANONICAL_FIELDS = {
    "id", "title", "status", "severity", "confidence",
    "firstSeen", "lastReviewed", "source", "files",
    "summary", "exploitPath", "remediation",
    "duplicateOf", "acceptedRiskId", "notes",
}


def _extract_canonical_fields(proposed: dict[str, Any]) -> dict[str, Any]:
    """Extract only canonical schema fields from a proposed finding record."""
    return {k: v for k, v in proposed.items() if k in _CANONICAL_FIELDS}


def _validate_against_schema(data: Any, schema_path: str) -> None:
    """Minimal structural validation against a JSON Schema (stdlib only; no jsonschema dep)."""
    try:
        schema = load_json(schema_path)
    except ValidationError as exc:
        raise ValidationError(f"cannot read schema {schema_path}: {exc}") from exc
    if not isinstance(schema, dict):
        raise ValidationError("schema must be a JSON object")
    # Check required top-level fields
    required = schema.get("required", [])
    if isinstance(required, list) and isinstance(data, dict):
        missing = [f for f in required if f not in data]
        if missing:
            raise ValidationError(f"missing required fields: {missing}")


def _print_findings_handoff_prompt(
    ctx: dict[str, Any],
    findings_path: str,
    findings_sha: str,
    version: int,
    complete: bool,
    coverage: dict[str, Any],
    run_json_path: str,
) -> None:
    completeness = "COMPLETE" if complete else "PARTIAL"
    missing = coverage.get("missing_assessments", [])
    stale = coverage.get("stale_assessments", [])
    coverage_lines = (
        f"  Total candidates:   {coverage.get('total_candidates', '?')}\n"
        f"  Assessed:           {coverage.get('assessed', '?')}\n"
        f"  Missing:            {missing if missing else '(none)'}\n"
        f"  Stale:              {stale if stale else '(none)'}"
    )

    print(f"""\
======== hermesVPS FINDINGS HANDOFF PROMPT (generate-findings) ========
NOTE: Structural/hash checks do not prove factual correctness of findings.
NOTE: A partial export is NOT a complete remediation handoff.

Assessment status:  {completeness}
Findings file:      {findings_path}
Findings SHA-256:   {findings_sha}
Version:            findings-v{version}
Run ID:             {ctx['run_id']}
Source commit:      {ctx['source_commit']}

Coverage:
{coverage_lines}

HANDOFF INSTRUCTIONS:
  1. Verify the source commit and findings SHA-256 above are accurate.
  2. Attach or paste the full contents of the findings file to the remediation agent.
  3. For each open finding, invoke phase 080 separately with the finding_id:
       hermes-vps-review --phase 080 --run-json {run_json_path} --trigger-input <finding_id>
  4. If any assessments are missing or stale, resolve them before treating
     this export as a COMPLETE remediation handoff.

STOP. Do not start remediation without a separate explicit human request.
======== end findings handoff prompt ========
""")


# ---------------------------------------------------------------------------
# Subcommand: validate-findings
# ---------------------------------------------------------------------------

def cmd_validate_findings(args: argparse.Namespace, run_json_path: str) -> int:
    """Read-only: validate a findings export file against the schema."""
    data = load_json(run_json_path)
    try:
        ctx = validate_run(data, expected_policy_prefix=None)
    except ValidationError as exc:
        die(str(exc))

    findings_file = args.findings_file
    if not os.path.isabs(findings_file):
        die("--findings-file must be an absolute path")
    if not os.path.isfile(findings_file):
        die(f"--findings-file not found: {findings_file}")

    try:
        export = load_json(findings_file)
    except ValidationError as exc:
        die(f"cannot read findings file: {exc}")

    schema_path = os.path.join(ctx["policy_prefix"], "templates", "findings-export.schema.json")
    if not os.path.isfile(schema_path):
        die(f"findings-export.schema.json not found at {schema_path}")

    try:
        _validate_against_schema(export, schema_path)
    except ValidationError as exc:
        die(f"findings file failed schema validation: {exc}")

    # Check identity fields
    if isinstance(export, dict):
        stored_commit = export.get("source_commit", "")
        if stored_commit and stored_commit != ctx["source_commit"]:
            print(
                f"warning: findings source_commit {stored_commit!r} != "
                f"run.json commit {ctx['source_commit']!r}",
                file=sys.stderr,
            )
        complete = export.get("complete", False)
        status = "COMPLETE" if complete else "PARTIAL"
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
        help="Subject identifier (required for phases 070/080: candidate_id or finding_id)",
    )
    p_reg.add_argument(
        "--payload-json",
        default=None,
        action=_Once,
        help="Absolute path to structured JSON payload sidecar (required for phases 060/070)",
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
        help="Subject identifier override (inferred from superseded artifact if omitted)",
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
