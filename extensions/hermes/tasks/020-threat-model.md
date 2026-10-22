# Task 020 — Evidence-based threat model

- Phase: 020 — threat-model
- Phase rule: `rules_020-threat-model.md`
- Report: `.repo-kit/hermes/reports/phase-020-threat-model.md`

## 1. Read first
1. `.repo-kit/hermes/review-rules/README.md`
2. `.repo-kit/hermes/review-rules/rules_000-safety-and-scope.md`
3. `.repo-kit/hermes/review-rules/rules_005-report-output.md`
4. `.repo-kit/hermes/review-rules/rules_020-threat-model.md`

If any of these files is missing, report the missing path and stop.

## 2. Target
The approved target is the repository root where Hermes was started.
Do not inspect paths outside it.

## 3. Prior reports
Required, newest matching file in `.repo-kit/hermes/reports/`:
- `phase-010-inventory*.md`

Triggering this task confirms the human reviewed that report.
If it is missing or its completion state is not complete, write the
report with completion state `blocked`, name the gap, and stop.
If the commit hash differs from the inventory, report the difference
and stop.

## 4. Perform
Perform only Rule 020. Read-only inspection only.
Do not execute project code, install anything, or use the network.
Do not update `security/threat-model.md`.

## 5. Write
Write exactly one report to the path above, or to its timestamped
variant if that file already exists (Rule 005).
Include the Rule 005 report contents and the Rule 020 required
response sections.

## 6. Stop
Stop and wait for human approval. Do not start Task 030.
