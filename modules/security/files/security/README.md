# Security workflow

This directory stores durable, human-reviewed security context rather than raw
scanner output.

## Source of truth

- `threat-model.md` — assets, entry points, and trust boundaries
- `weakness-classes.md` — canonical weakness-class catalog and source-review coverage contract
- `surface-inventory.md` — canonical surface and trust-boundary inventory contract
- `scanner-planning.md` — canonical scanner-planning and result-handoff contract. Rule 030 and a plan that proposes an executable check read it. It does not run scanners or import findings.
- `gitleaks_handoff.py` — offline normalizer for one explicitly selected Gitleaks JSON report. It writes a separate secret-minimized handoff of unreviewed leads. It does not launch Gitleaks or update the findings store.
- `gitleaks_dir_scan.py` — one explicit local directory scan using an already installed Gitleaks executable, then the normalizer above. It is not run by Rule 030. It does not update the findings store.
- `findings-reviewed.json` — reviewed findings and lifecycle status
- `accepted-risks.md` — explicitly accepted or deferred risks
- `findings.schema.json` — findings-store structure. Optional `weaknessClasses`
  and `entrySink` may be omitted. Records without them stay valid. A toolkit
  that still ships the previous schema rejects records that contain the new
  fields. Init and sync do not migrate or enrich an existing findings store.
  An `entrySink` evidence path is a portable repository-relative path using
  `/` separators. The schema only requires a string. `validate_finding_metadata`
  rejects an empty or whitespace-only path, a POSIX absolute path, a Windows
  drive-qualified or drive-relative path, a UNC or backslash path, a URI-like
  reference, a `.` or `..` component, a repeated or trailing separator, a
  leading `./`, and NUL or other control characters. Spaces and Unicode in a
  filename are allowed, including a name that contains the substring `..`.
  The check does not open the path or prove symlink confinement. A reader
  must confine the path to an approved root before opening it. The top-level
  `files` list is unchanged.
- `templates/` — reusable finding templates
- `plans/` — approved hardening and remediation plans

## Workflow

1. Run `/security-plan-hardening` in Plan Mode and review
   `security/plans/security-hardening.md`. Plans for a single finding go in
   `security/plans/<finding-id>.md`.
2. Review one approved priority with `/security-review-priority-1`.
3. Convert validated issues with `/security-generate-finding`.
4. Manually approve records before adding them to the findings store.
5. Use `/security-triage-findings` to deduplicate repeated review output.
6. Use `/security-fix-finding` to remediate one approved finding at a time.

Human review controls updates to `findings-reviewed.json` and
`accepted-risks.md`.

## Commit policy

Commit this README, the threat model, reviewed findings, accepted risks,
plans, schema, and templates. Keep raw scans, temporary reports, and private records
out of Git.

## Statuses

- `open`
- `fixed`
- `accepted-risk`
- `duplicate`
- `rejected`
