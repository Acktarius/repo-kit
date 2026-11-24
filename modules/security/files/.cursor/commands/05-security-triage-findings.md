# Security triage findings

Compare proposed findings against:

- `security/findings-reviewed.json`
- `security/findings.schema.json`
- `security/accepted-risks.md`
- `.cursor/rules/40-security-triage.mdc`

Classify each proposal as `new`, `duplicate`, `accepted-risk`, `rejected`,
`existing-open`, or `existing-fixed`. Preserve stable IDs, link duplicates and
accepted risks, and propose the next `SG-XXX` ID only for genuinely new issues.

Keep existing `weaknessClasses` and `entrySink` unless the approved change
replaces them. Do not backfill them from titles or advisory text. A missing
optional class is not invalidity. A shared class label is not a duplicate.

Do not modify files or mark findings fixed without current evidence.
