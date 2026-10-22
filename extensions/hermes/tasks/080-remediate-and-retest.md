# Task 080 — Plan remediation and retest for one finding

- Phase: 080 — remediate-and-retest
- Phase rule: `rules_080-remediate-and-retest.md`
- Report: `.repo-kit/hermes/reports/phase-080-remediate-and-retest.md`

## 1. Read first
1. `.repo-kit/hermes/review-rules/README.md`
2. `.repo-kit/hermes/review-rules/rules_000-safety-and-scope.md`
3. `.repo-kit/hermes/review-rules/rules_005-report-output.md`
4. `.repo-kit/hermes/review-rules/rules_080-remediate-and-retest.md`

If any of these files is missing, report the missing path and stop.

## 2. Target
The approved target is the repository root where Hermes was started.
Do not inspect paths outside it.

## 3. Prior reports and inputs
Required, newest matching file in `.repo-kit/hermes/reports/`:
- `phase-070-reviewed-findings*.md`

Also required:
- one open finding ID named in the trigger message;
- that finding in the reviewed findings store.

If any input is missing, write the report with completion state
`blocked`, name the gap, and stop.
If the commit hash or finding evidence changed, report the difference
and stop.

## 4. Perform
Perform only Rule 080 approval gate 1: propose the remediation and
verification plan.
Do not edit source, run tests, or update the finding record.
Each of those actions needs its own explicit human approval.

## 5. Write
Write exactly one report to the path above, or to its timestamped
variant if that file already exists (Rule 005).
Include the Rule 005 report contents and the Rule 080 required
response sections.

## 6. Stop
Stop and wait for human approval. The report is not approval to
change source code.
