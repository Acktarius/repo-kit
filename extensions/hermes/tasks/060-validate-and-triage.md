# Task 060 — Validate and triage security candidates

- Phase: 060 — validate-and-triage
- Phase rule: `rules_060-validate-and-triage.md`
- Report: `.repo-kit/hermes/reports/phase-060-validate-and-triage.md`

## 1. Read first
1. `.repo-kit/hermes/review-rules/README.md`
2. `.repo-kit/hermes/review-rules/rules_000-safety-and-scope.md`
3. `.repo-kit/hermes/review-rules/rules_005-report-output.md`
4. `.repo-kit/hermes/review-rules/rules_060-validate-and-triage.md`

If any of these files is missing, report the missing path and stop.

## 2. Target
The approved target is the repository root where Hermes was started.
Do not inspect paths outside it.

## 3. Prior reports
Required, newest matching files in `.repo-kit/hermes/reports/`:
- at least one of `phase-040-dependency-advisories*.md` or
  `phase-050-source-review*.md`

Also read existing reviewed findings and accepted risks when present.

Triggering this task confirms the human reviewed those reports.
If no candidate report exists, write the report with completion state
`blocked`, name the gap, and stop.
If candidate evidence describes a different commit, report the
mismatch and stop.

## 4. Perform
Perform only Rule 060. Read-only validation only.
Do not execute exploits, tests, or target code.
Do not allocate SG IDs or modify findings or accepted risks.

## 5. Write
Write exactly one report to the path above, or to its timestamped
variant if that file already exists (Rule 005).
Include the Rule 005 report contents and the Rule 060 required
response sections.

## 6. Stop
Stop and wait for human approval. Do not start Task 070.
