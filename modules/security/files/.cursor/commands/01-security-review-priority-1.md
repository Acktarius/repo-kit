# Security review: Priority 1

Read:

- `security/plans/security-hardening.md`
- `.cursor/rules/30-security-reviewer.mdc`
- `.cursor/rules/40-security-triage.mdc`
- `security/threat-model.md`
- `security/findings-reviewed.json`
- `security/accepted-risks.md`

Review only the first priority area in the approved plan. Identify real
medium, high, or critical issues supported by evidence. For each valid issue,
propose an object matching `security/findings.schema.json`. When the
evidence establishes them, include optional `weaknessClasses` and
`entrySink`. Omit the class when the mapping is uncertain and say why.
Do not invent a class. That metadata does not lower the valid-issue bar.

Do not modify code or security records. If that priority was inspected and
nothing valid is found, say exactly: `no valid findings for Priority 1`.
That line is only the findings summary. It does not mean the priority is
secure. If `.cursor/rules/30-security-reviewer.mdc` stops the review as
blocked or incomplete, report that condition and do not use this line.
