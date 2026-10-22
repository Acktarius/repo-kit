# Task 030 — Scanner selection and execution plan

- Phase: 030 — scan-plan
- Phase rule: `rules_030-scan-plan.md`
- Report: `.repo-kit/hermes/reports/phase-030-scan-plan.md`

## 1. Read first
1. `.repo-kit/hermes/review-rules/README.md`
2. `.repo-kit/hermes/review-rules/rules_000-safety-and-scope.md`
3. `.repo-kit/hermes/review-rules/rules_005-report-output.md`
4. `.repo-kit/hermes/review-rules/rules_030-scan-plan.md`

If any of these files is missing, report the missing path and stop.

## 2. Target
The approved target is the repository root where Hermes was started.
Do not inspect paths outside it.

## 3. Prior reports
Required, newest matching files in `.repo-kit/hermes/reports/`:
- `phase-010-inventory*.md`
- `phase-020-threat-model*.md`

Triggering this task confirms the human reviewed those reports.
If any is missing or its completion state is not complete, write the
report with completion state `blocked`, name the gap, and stop.
If the commit hash differs from the reviewed baseline, report the
difference and stop.

## 4. Perform
Perform only Rule 030. This task produces a plan, not a scan.
Do not install, download, authenticate, or run scanners.
Label every command as a proposal.

## 5. Write
Write exactly one report to the path above, or to its timestamped
variant if that file already exists (Rule 005).
Include the Rule 005 report contents and the Rule 030 required
response sections.

## 6. Stop
Stop and wait for human approval. Do not start Task 040 or 050.
