# Task 070 — Propose a human-reviewed finding record

- Phase: 070 — reviewed-findings
- Phase rule: `rules_070-reviewed-findings.md`
- Report: `.repo-kit/hermes/reports/phase-070-reviewed-findings.md`

## 1. Read first
1. `.repo-kit/hermes/review-rules/README.md`
2. `.repo-kit/hermes/review-rules/rules_000-safety-and-scope.md`
3. `.repo-kit/hermes/review-rules/rules_005-report-output.md`
4. `.repo-kit/hermes/review-rules/rules_070-reviewed-findings.md`

If any of these files is missing, report the missing path and stop.

## 2. Target
The approved target is the repository root where Hermes was started.
Do not inspect paths outside it.

## 3. Prior reports and inputs
Required, newest matching file in `.repo-kit/hermes/reports/`:
- `phase-060-validate-and-triage*.md`

Also required:
- one candidate ID named in the trigger message;
- the findings schema and findings store, or the human's confirmation
  that no store exists yet.

If any input is missing, write the report with completion state
`blocked`, name the gap, and stop.

## 4. Perform
Perform only Rule 070, for the one named candidate.
Put the proposed record in the report only.
Do not write the findings store, allocate a persistent ID, or accept
risks.

## 5. Write
Write exactly one report to the path above, or to its timestamped
variant if that file already exists (Rule 005).
Include the Rule 005 report contents and the proposed record.

## 6. Stop
Stop and wait for human approval. Saving the record is a separate
approved action.
