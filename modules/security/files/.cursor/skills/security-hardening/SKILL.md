---
name: security-hardening
description: Repo-aware security review, finding triage, accepted-risk tracking, and focused remediation workflow.
---

# Security hardening

Use this skill to plan a security review, validate a suspected vulnerability,
record or triage findings, and implement a focused remediation.

## Load repository context

Read these files when present:

- `.cursor/rules/20-security-planner.mdc`
- `.cursor/rules/30-security-reviewer.mdc`
- `.cursor/rules/40-security-triage.mdc`
- `.cursor/plans/security-hardening.md`
- `security/README.md`
- `security/threat-model.md`
- `security/findings-reviewed.json`
- `security/findings.schema.json`
- `security/accepted-risks.md`
- dependency manifests, lockfiles, entrypoints, deployment configuration, and
  files in the requested review scope

If context is missing, continue with what is available and state the gap.

## Principles

- Be repository-specific and evidence-based.
- Review only the requested diff, branch, files, or approved plan scope.
- Do not invent findings or overstate uncertain impact.
- Check reviewed findings and accepted risks before proposing a new record.
- Prefer small fixes that address one root cause.
- Keep durable, human-reviewed security memory in `security/`.
- Do not update findings or accepted risks without explicit approval.

## Workflow

1. **Plan:** map assets, entry points, trust boundaries, secrets, and sensitive
   data flows; save a repo-specific plan for approval.
2. **Review:** inspect the approved scope and report only supported findings.
3. **Propose:** express each validated issue using `findings.schema.json`.
4. **Triage:** classify it as new, duplicate, accepted-risk, rejected, or an
   existing record.
5. **Fix:** implement one approved open finding with the smallest safe patch.
6. **Verify:** run focused validation and document evidence for status changes.

## Review priority

Use repository evidence to order the work. Common high-signal areas are:

1. dependency and supply-chain controls;
2. externally exposed services and authorization boundaries;
3. secrets and sensitive configuration;
4. command execution, deserialization, and filesystem access;
5. outbound network flows and third-party trust;
6. logging, error handling, and denial-of-service paths.

## Finding output

For each valid finding provide:

- stable or proposed ID;
- title, severity, and confidence;
- affected files and relevant function or configuration;
- evidence and high-level exploit path;
- concrete remediation;
- duplicate or accepted-risk linkage when applicable.

If there are no supported findings, say `no valid findings`.
