# Task 050 — Evidence-based source and configuration review

- Phase: 050 — source-review
- Phase rule: `rules_050-source-review.md`
- Report: `.repo-kit/hermes/reports/phase-050-source-review.md`

## 1. Read first
1. `.repo-kit/hermes/review-rules/README.md`
2. `.repo-kit/hermes/review-rules/rules_000-safety-and-scope.md`
3. `.repo-kit/hermes/review-rules/rules_005-report-output.md`
4. `.repo-kit/hermes/review-rules/rules_050-source-review.md`

If any of these files is missing, report the missing path and stop.

## 2. Target
The approved target is the repository root where Hermes was started.
Do not inspect paths outside it.

## 3. Prior reports
Required, newest matching files in `.repo-kit/hermes/reports/`:
- `phase-010-inventory*.md`
- `phase-020-threat-model*.md`
- `phase-030-scan-plan*.md` (required for scanner-assisted review)

Triggering this task confirms the human reviewed those reports.
If a required report is missing or its completion state is not
complete, write the report with completion state `blocked`, name the
gap, and stop.
If the commit hash differs from the reviewed baseline, report the
difference and stop.

## 4. Perform
Perform only Rule 050, for one review priority:
- the priority named in the trigger message; otherwise
- the first prioritized review area in the threat-model report.

Read-only inspection by default. Run a scanner only if the human
approved that exact action in the trigger message.
Do not execute target code or apply fixes.

## 5. Write
Write exactly one report to the path above, or to its timestamped
variant if that file already exists (Rule 005).
Include the Rule 005 report contents and the Rule 050 required
response sections.

## 6. Stop
Stop and wait for human approval. Do not review another priority.
