# Rule 080 — Remediate and retest one approved finding

## Prerequisites
- Apply rules_000-safety-and-scope.md throughout this phase.
- Apply rules_005-report-output.md for report artefact writes.
- Require one explicitly selected, human-approved open finding.
- Read the reviewed finding, supporting evidence, relevant accepted risks,
  and approved remediation scope.
- Confirm the full commit hash and working-tree state.
- Identify existing local changes and preserve them.
- If the baseline or finding evidence changed materially, report the
  difference and stop for approval.

## Separate approval gates
Treat these as separate actions:
1. Propose the remediation and verification plan.
2. Apply the specifically approved patch.
3. Execute specifically approved verification commands.
4. Propose a finding-status update.
5. Save the approved record update.

Approval for one action does not authorize the others.
Do not commit, push, publish, deploy, or restart services without
separate approval.

## 1. Plan the smallest safe remediation
Before editing, return:
- finding ID and root cause;
- exact files and behavior to change;
- proposed fix and why it addresses the root cause;
- compatibility and operational risks;
- dependency changes, if any;
- verification commands and expected evidence;
- permissions, network access, and resource requirements;
- rollback considerations.

Prefer one root cause and a minimal, reviewable patch.
Do not mix unrelated refactoring or formatting into the fix.
Do not weaken security controls or suppress scanner rules merely
to remove a reported result.
Stop for approval before editing.

## 2. Apply only the approved patch
- Stay within the approved files and behavior.
- Preserve unrelated changes.
- Do not use destructive resets, cleans, or broad replacements.
- Do not run project scripts, hooks, or dependency installation implicitly.
- If the approved approach is insufficient, stop and propose a revision.
- Report the resulting diff and any deviations.
- Do not automatically advance to test execution.

## Dependency remediation
- Verify upstream remediation guidance before selecting a version.
- Do not assume latest is the correct or compatible fix.
- Record source URLs, lookup dates, and fixed-version evidence.
- Network access, downloading, installation, and lockfile generation
  each require appropriate approval.
- Do not enable lifecycle scripts implicitly.
- For vendored files, preserve required licensing and attribution.
- Verify the identity and provenance of replacements.
- Do not delete or replace an entire vendor directory without
  explicitly approved scope.

## 3. Execute approved verification
Before running commands, confirm:
- the exact approved commands and execution location;
- whether they execute target code or invoke hooks or plugins;
- required secrets, network, filesystem access, and external services;
- timeout, output bounds, and resource limits.

Do not test against deployed or third-party systems without
explicit authorization.
Do not use discovered credentials.
Keep secrets out of commands, logs, and reports.

Where relevant, verify:
- the vulnerable behavior is addressed;
- legitimate behavior still works;
- a regression check covers the root cause;
- dependency advisory matching no longer reports the affected artifact.

Record exact commands, tool versions, exit codes, and relevant output.
Report skipped, failed, and unavailable checks separately.
A scanner no longer matching does not by itself prove the root cause
was fixed.

## 4. Evaluate the result
Distinguish:
- patch applied;
- verification passed;
- verification incomplete;
- remediation unsuccessful.

Do not claim success from an unexecuted test or an unsupported assumption.
If verification fails, report evidence and stop before expanding scope.
Do not automatically roll back unrelated work or make additional changes.

## 5. Propose a record update
Only propose status fixed when current evidence supports remediation.
Preserve the existing finding ID and unrelated record fields.
Include:
- patched revision or an explicit uncommitted-patch description;
- affected files and root-cause change;
- verification evidence and remaining limitations;
- review timestamp when verified and available;
- relevant advisory references.

Do not mark a finding fixed solely because a patch was written.
Do not convert a failed fix into accepted-risk without human approval.
Saving the record requires approval of the exact proposed update
and validation against the current findings schema.

## Required response
For the currently approved action, report:
1. Finding ID and baseline
2. Approved scope and action performed
3. Proposed or actual changes
4. Verification evidence, if execution was approved
5. Remaining risks, failures, and coverage gaps
6. Proposed record change, if justified
7. Completion state and next approval required

Write the phase report to
`.repo-kit/hermes/reports/phase-080-remediate-and-retest.md`
(or a timestamped variant if that file already exists).
Source edits still require the separate remediation approvals above;
the report itself is not approval to change source code.
Stop after writing the phase report for the specifically approved action.
