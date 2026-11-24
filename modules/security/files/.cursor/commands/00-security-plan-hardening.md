# Security plan hardening

Use this command in **Plan Mode**.

Read the security rules, skill, repository architecture, dependency manifests,
deployment configuration, and `security/` records.

Create a repository-specific security hardening plan that:

1. identifies assets, entry points, trust boundaries, secrets, and external services;
2. states assumptions and unknowns;
3. orders review areas by risk;
4. lists the files and functions to inspect and why they matter;
5. ends with a short implementation checklist.

Do not change code or record findings. Do not invent issues. If this plan
proposes an executable scanner check, follow `security/scanner-planning.md`
and do not run the check. A manual plan does not need that table. Save the result to
`security/plans/security-hardening.md`, then stop for review.
