"""Shared fail-closed prerequisite resolver and upstream-staleness checks (read-only).

Single implementation used by bin/hermes-vps-review before prompt emission and
by hermes-vps-artifacts register, revise, and generate-findings.

Identity contract (phases 060-080):
  - phase-060 payload candidates[].candidate_id defines the subject inventory.
  - phase-070 and phase-080 are keyed by that candidate_id (--trigger-input,
    --subject-id, and the payload's candidate_id field must all be equal).
  - phase-080 requires the selected, complete phase-070 for the same candidate
    with an actionable disposition.  finding_id (SG-NNN) is optional metadata
    and, when present in a plan, must equal the 070 proposed_finding.id.

Structural/hash checks do not prove factual correctness of report content.
"""

from __future__ import annotations

import os
from typing import Any

from lib.hermes_vps_common import ValidationError, load_json, sha256_file
from lib.hermes_vps_phases import PHASE_TABLE, REPEATED_PHASES, AllOf, OneOf

ACTIONABLE_070 = frozenset({"confirmed", "suspected", "needs-investigation"})


def find_artifact(manifest: dict[str, Any], art_id: str | None) -> dict[str, Any] | None:
    for art in manifest.get("artifacts", []):
        if isinstance(art, dict) and art.get("id") == art_id:
            return art
    return None


def current_selection(manifest: dict[str, Any], phase: str, subject_id: str | None) -> str | None:
    if phase in REPEATED_PHASES:
        return manifest.get("selected_by_subject", {}).get(phase, {}).get(subject_id or "")
    return manifest.get("selected_by_phase", {}).get(phase)


def _run_path(run_root: str, rel: str) -> str:
    if not isinstance(rel, str) or not rel or os.path.isabs(rel) or ".." in rel.split(os.sep):
        raise ValidationError(f"manifest path {rel!r} must be relative and inside the run root")
    return os.path.join(run_root, rel)


def file_problems(run_root: str, entry: dict[str, Any]) -> list[str]:
    """Report and payload integrity against the hashes recorded in the manifest."""
    problems: list[str] = []
    for path_key, sha_key, label in (
        ("path", "sha256", "report"),
        ("payload_path", "payload_sha256", "payload"),
    ):
        if path_key not in entry:
            if label == "report":
                problems.append("no report path recorded")
            continue
        try:
            abs_path = _run_path(run_root, entry[path_key])
        except ValidationError as exc:
            problems.append(str(exc))
            continue
        if os.path.islink(abs_path) or not os.path.isfile(abs_path):
            problems.append(f"{label} file missing or not a regular file: {abs_path}")
            continue
        recorded = entry.get(sha_key)
        if not recorded:
            problems.append(f"no {label} SHA-256 recorded")
        elif sha256_file(abs_path) != recorded:
            problems.append(f"{label} SHA-256 mismatch for {abs_path}")
    return problems


def artifact_problems(
    manifest: dict[str, Any],
    run_root: str,
    art_id: str,
    _memo: dict[str, list[str]] | None = None,
) -> list[str]:
    """Reasons art_id cannot serve as current, complete input (empty list = usable).

    Covers: presence, declared completion, report/payload hashes, whether it is
    still the current selection for its phase/subject, the prerequisite hashes
    recorded at registration, and (recursively) the same checks for every
    upstream prerequisite.  An upstream revision therefore invalidates every
    downstream artifact built on the superseded input.
    """
    memo = {} if _memo is None else _memo
    if art_id in memo:
        return memo[art_id]
    memo[art_id] = ["prerequisite cycle"]

    entry = find_artifact(manifest, art_id)
    if entry is None:
        memo[art_id] = ["not found in manifest"]
        return memo[art_id]

    problems: list[str] = []
    status = entry.get("completion_status")
    if status != "complete":
        problems.append(f"completion_status is {status!r}, not 'complete'")
    problems.extend(file_problems(run_root, entry))
    if entry.get("kind") == "hermes_phase_report":
        sel = current_selection(manifest, entry.get("phase", ""), entry.get("subject_id"))
        if sel != art_id:
            problems.append(f"superseded: current selection is {sel!r}")

    recorded_hashes = entry.get("prerequisite_hashes", {})
    for pid in entry.get("prerequisite_artifacts", []):
        upstream = find_artifact(manifest, pid)
        rec = recorded_hashes.get(pid)
        if upstream is not None and isinstance(rec, dict):
            for key in ("sha256", "payload_sha256"):
                if rec.get(key) != upstream.get(key):
                    problems.append(f"upstream {pid}: {key} differs from value recorded at registration")
        for reason in artifact_problems(manifest, run_root, pid, memo):
            problems.append(f"upstream {pid}: {reason}")

    memo[art_id] = problems
    return problems


def load_artifact_payload(run_root: str, entry: dict[str, Any]) -> dict[str, Any]:
    """Load a registered payload after verifying its recorded SHA-256."""
    rel = entry.get("payload_path")
    if not rel:
        raise ValidationError(f"artifact {entry.get('id')!r} has no registered payload")
    abs_path = _run_path(run_root, rel)
    if not os.path.isfile(abs_path):
        raise ValidationError(f"payload for {entry.get('id')!r} missing: {abs_path}")
    if sha256_file(abs_path) != entry.get("payload_sha256"):
        raise ValidationError(f"payload SHA-256 mismatch for {entry.get('id')!r}")
    data = load_json(abs_path)
    if not isinstance(data, dict):
        raise ValidationError(f"payload for {entry.get('id')!r} must be a JSON object")
    return data


def prerequisite_hashes(manifest: dict[str, Any], ids: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for pid in ids:
        entry = find_artifact(manifest, pid) or {}
        out[pid] = {"sha256": entry.get("sha256"), "payload_sha256": entry.get("payload_sha256")}
    return out


def triage_candidate_ids(manifest: dict[str, Any], run_root: str) -> tuple[str, list[str]]:
    """Return (selected 060 artifact id, candidate ids) from the verified 060 payload."""
    sel_060 = current_selection(manifest, "060", None)
    entry = find_artifact(manifest, sel_060)
    if entry is None:
        raise ValidationError("no selected phase-060 triage artifact")
    payload = load_artifact_payload(run_root, entry)
    return sel_060, [c["candidate_id"] for c in payload.get("candidates", [])]


def _selections(
    manifest: dict[str, Any], phase: str, req: str, subject_id: str | None
) -> list[tuple[str, str]]:
    """(label, artifact_id) pairs that satisfy prerequisite phase req for phase."""
    info = PHASE_TABLE[phase]
    if req in REPEATED_PHASES:
        by_subject = manifest.get("selected_by_subject", {}).get(req, {})
        if info.repeated and PHASE_TABLE[req].trigger_label == info.trigger_label:
            art = by_subject.get(subject_id or "")
            return [(f"phase-{req}[{subject_id}]", art)] if art else []
        return [(f"phase-{req}[{s}]", a) for s, a in sorted(by_subject.items())]
    art = manifest.get("selected_by_phase", {}).get(req)
    return [(f"phase-{req}", art)] if art else []


def resolve_prerequisites(
    manifest: dict[str, Any],
    run_root: str,
    phase: str,
    subject_id: str | None = None,
) -> list[str]:
    """Return the exact prerequisite artifact IDs for phase/subject, or raise.

    Fail closed: every selected input must be complete, intact, current, and
    free of upstream staleness.  AllOf needs every listed phase; OneOf needs at
    least one, and every selected branch is used (a broken branch is an error).
    """
    info = PHASE_TABLE.get(phase)
    if info is None:
        raise ValidationError(f"unknown phase {phase!r}")
    if info.subject_id_required and not subject_id:
        raise ValidationError(f"phase {phase} requires a subject ({info.trigger_label})")

    memo: dict[str, list[str]] = {}
    resolved: list[str] = []

    def _use(label: str, art_id: str) -> None:
        problems = artifact_problems(manifest, run_root, art_id, memo)
        if problems:
            raise ValidationError(
                f"phase {phase} prerequisite {label} ({art_id}) is not usable: "
                + "; ".join(problems)
            )
        if art_id not in resolved:
            resolved.append(art_id)

    desc = info.prereqs
    if isinstance(desc, AllOf):
        for req in desc.phases:
            sels = _selections(manifest, phase, req, subject_id)
            if not sels:
                scope = f" for {info.trigger_label} {subject_id!r}" if req in REPEATED_PHASES else ""
                raise ValidationError(
                    f"phase {phase} requires a complete phase-{req} artifact{scope}; none selected"
                )
            for label, art in sels:
                _use(label, art)
    elif isinstance(desc, OneOf):
        any_selected = False
        for req in desc.phases:
            for label, art in _selections(manifest, phase, req, subject_id):
                any_selected = True
                _use(label, art)
        if not any_selected:
            raise ValidationError(
                f"phase {phase} requires at least one of phases {desc.phases}; none selected"
            )

    if phase in ("070", "080"):
        _, candidates = triage_candidate_ids(manifest, run_root)
        if subject_id not in candidates:
            raise ValidationError(
                f"candidate_id {subject_id!r} is not in the selected phase-060 triage "
                f"inventory {candidates}"
            )
    if phase == "080":
        entry_070 = find_artifact(manifest, current_selection(manifest, "070", subject_id))
        disposition = load_artifact_payload(run_root, entry_070).get("assessment_disposition")
        if disposition not in ACTIONABLE_070:
            raise ValidationError(
                f"phase 080 for {subject_id!r} requires an actionable phase-070 "
                f"assessment {sorted(ACTIONABLE_070)}; selected assessment is {disposition!r}"
            )
    return resolved
