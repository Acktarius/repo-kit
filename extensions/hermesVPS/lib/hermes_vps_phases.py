"""hermesVPS phase table — centralized phase definitions and prerequisite descriptors.

All phase numbers, titles, prerequisite rules, required policy files, and
subject-identity requirements are defined here.  The runner, artifact helper,
and tests use this module as the single source of truth.

Structural/hash checks do not prove factual correctness of review content.
"""

from __future__ import annotations

import os
from typing import Any, NamedTuple

# ---------------------------------------------------------------------------
# Prerequisite descriptors
# ---------------------------------------------------------------------------

class AllOf:
    """All listed phases must have a valid selected artifact.

    A repeated prerequisite phase that shares the dependent phase's subject key
    (070 -> 080, both keyed by candidate_id) resolves to that subject's selection;
    otherwise every subject-scoped selection of the prerequisite phase is required.
    """

    def __init__(self, phases: list[str]) -> None:
        self.phases = phases

    def __repr__(self) -> str:  # pragma: no cover
        return f"AllOf({self.phases!r})"


class OneOf:
    """At least one of the listed phases must have a selected artifact.

    Every selected branch is resolved and used as input.  A selected branch that
    is stale or invalid fails resolution even if another branch is valid
    (fail closed: downstream work must not silently drop an input).
    """

    def __init__(self, phases: list[str]) -> None:
        self.phases = phases

    def __repr__(self) -> str:  # pragma: no cover
        return f"OneOf({self.phases!r})"


# ---------------------------------------------------------------------------
# Phase info
# ---------------------------------------------------------------------------

class PhaseInfo(NamedTuple):
    title: str               # Short display title
    phase_name: str          # slug (e.g. "inventory", "threat-model")
    prereqs: AllOf | OneOf   # Prerequisite descriptor
    policy_files: list[str]  # Required relative paths under policy_prefix
    subject_id_required: bool = False  # True for repeated phases (050, 070, 080)
    payload_required: bool = False     # True for phases that need a JSON sidecar
    repeated: bool = False             # True for phases that run per subject
    trigger_label: str = ""            # Subject key: --trigger-input / --subject-id / payload field
    payload_schema: str = ""           # templates/<name> enforced for the payload


# ---------------------------------------------------------------------------
# Per-phase required policy files
# ---------------------------------------------------------------------------

_BASE = [
    "BOOTSTRAP.md",
    "rules/rules_000-safety-and-scope.md",
    "rules/rules_005-report-output.md",
]
_SCHEMA = [
    "security-assets/findings.schema.json",
    "security-assets/README.md",
]


def _phase_files(rule: str, task: str, template: str, extra: list[str] | None = None) -> list[str]:
    files = _BASE + [rule, task, template] + _SCHEMA
    if extra:
        files += extra
    return files


# ---------------------------------------------------------------------------
# Phase table
# ---------------------------------------------------------------------------

PHASE_TABLE: dict[str, PhaseInfo] = {
    "010": PhaseInfo(
        title="Inventory",
        phase_name="inventory",
        prereqs=AllOf([]),
        policy_files=_phase_files(
            "rules/rules_010-inventory.md",
            "tasks/010-inventory.md",
            "templates/phase-010-report.md",
        ),
    ),
    "020": PhaseInfo(
        title="Threat model",
        phase_name="threat-model",
        prereqs=AllOf(["010"]),
        policy_files=_phase_files(
            "rules/rules_020-threat-model.md",
            "tasks/020-threat-model.md",
            "templates/phase-020-report.md",
        ),
    ),
    "030": PhaseInfo(
        title="Scanner selection and execution plan",
        phase_name="scan-plan",
        prereqs=AllOf(["010", "020"]),
        policy_files=_phase_files(
            "rules/rules_030-scan-plan.md",
            "tasks/030-scan-plan.md",
            "templates/phase-030-report.md",
        ),
    ),
    "040": PhaseInfo(
        title="Dependency identification and advisory matching",
        phase_name="dependency-advisories",
        prereqs=AllOf(["010", "020", "030"]),
        policy_files=_phase_files(
            "rules/rules_040-dependency-advisories.md",
            "tasks/040-dependency-advisories.md",
            "templates/phase-040-report.md",
            extra=["templates/vuln-intel-record.schema.json"],
        ),
        payload_required=True,
        payload_schema="vuln-intel-record.schema.json",
    ),
    "050": PhaseInfo(
        title="Source and configuration review",
        phase_name="source-review",
        # 010 + 020 required; 030 checked if present (scanner-assisted).
        # Repeated because multiple priority areas may be reviewed independently;
        # earlier inputs are preserved per subject_id (priority label).
        prereqs=AllOf(["010", "020"]),
        policy_files=_phase_files(
            "rules/rules_050-source-review.md",
            "tasks/050-source-review.md",
            "templates/phase-050-report.md",
        ),
        subject_id_required=True,
        repeated=True,
        trigger_label="priority_area",
    ),
    "060": PhaseInfo(
        title="Validate and triage",
        phase_name="validate-and-triage",
        # at least one of 040 or 050 must be selected; every selected 050
        # priority and the selected 040 are all inputs
        prereqs=OneOf(["040", "050"]),
        policy_files=_phase_files(
            "rules/rules_060-validate-and-triage.md",
            "tasks/060-validate-and-triage.md",
            "templates/phase-060-report.md",
            extra=["templates/triage-payload.schema.json"],
        ),
        payload_required=True,
        payload_schema="triage-payload.schema.json",
    ),
    "070": PhaseInfo(
        title="Reviewed findings",
        phase_name="reviewed-findings",
        prereqs=AllOf(["060"]),
        policy_files=_phase_files(
            "rules/rules_070-reviewed-findings.md",
            "tasks/070-reviewed-findings.md",
            "templates/phase-070-report.md",
            extra=["templates/finding-record.schema.json"],
        ),
        subject_id_required=True,
        payload_required=True,
        repeated=True,
        trigger_label="candidate_id",
        payload_schema="finding-record.schema.json",
    ),
    "080": PhaseInfo(
        title="Remediate and retest (gate 1: plan only)",
        phase_name="remediate-and-retest",
        # subject-scoped: requires the selected 070 for the same candidate_id
        prereqs=AllOf(["060", "070"]),
        policy_files=_phase_files(
            "rules/rules_080-remediate-and-retest.md",
            "tasks/080-remediate-and-retest.md",
            "templates/phase-080-report.md",
            extra=["templates/phase-080-plan.schema.json"],
        ),
        subject_id_required=True,
        payload_required=True,
        repeated=True,
        trigger_label="candidate_id",
        payload_schema="phase-080-plan.schema.json",
    ),
}

VALID_PHASES: frozenset[str] = frozenset(PHASE_TABLE.keys())
REPEATED_PHASES: frozenset[str] = frozenset(p for p, i in PHASE_TABLE.items() if i.repeated)
PAYLOAD_PHASES: frozenset[str] = frozenset(p for p, i in PHASE_TABLE.items() if i.payload_required)


# ---------------------------------------------------------------------------
# Helpers for validate_policy_files
# ---------------------------------------------------------------------------

def validate_phase_policy_files(
    policy_prefix: str,
    phase: str,
) -> list[str]:
    """Return list of missing required policy files for phase.

    Returns an empty list if all required files are present.
    Raises KeyError if phase is not in PHASE_TABLE.
    """
    info = PHASE_TABLE[phase]
    missing = []
    for rel in info.policy_files:
        p = os.path.join(policy_prefix, rel)
        if not os.path.isfile(p):
            missing.append(p)
    return missing


def abs_policy_files_for_phase(policy_prefix: str, phase: str) -> dict[str, str]:
    """Return {relative_path: absolute_path} mapping for a phase's required policy files."""
    info = PHASE_TABLE[phase]
    return {rel: os.path.join(policy_prefix, rel) for rel in info.policy_files}
