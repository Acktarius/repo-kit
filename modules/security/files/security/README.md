# Security workflow

This directory stores durable, human-reviewed security context rather than raw
scanner output.

## Source of truth

- `threat-model.md` — assets, entry points, and trust boundaries
- `findings-reviewed.json` — reviewed findings and lifecycle status
- `accepted-risks.md` — explicitly accepted or deferred risks
- `findings.schema.json` — findings-store structure
- `templates/` — reusable finding templates

## Workflow

1. Run `/security-plan-hardening` in Plan Mode and review
   `.cursor/plans/security-hardening.md`.
2. Review one approved priority with `/security-review-priority-1`.
3. Convert validated issues with `/security-generate-finding`.
4. Manually approve records before adding them to the findings store.
5. Use `/security-triage-findings` to deduplicate repeated review output.
6. Use `/security-fix-finding` to remediate one approved finding at a time.

Human review controls updates to `findings-reviewed.json` and
`accepted-risks.md`.

## Commit policy

Commit this README, the threat model, reviewed findings, accepted risks,
schema, and templates. Keep raw scans, temporary reports, and private records
out of Git.

## Statuses

- `open`
- `fixed`
- `accepted-risk`
- `duplicate`
- `rejected`
