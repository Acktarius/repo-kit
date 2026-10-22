# Rule 030 — Scanner selection and execution plan

## Prerequisites
- Apply rules_000-safety-and-scope.md throughout this phase.
- Require an approved target path, reviewed inventory from Rule 010,
  and reviewed threat model from Rule 020.
- Confirm the full commit hash and working-tree state.
- If the target differs from the approved baseline, report the difference
  and stop for approval.

## Permissions
This phase produces a plan, not a scan.
- Do not install, update, download, authenticate, or run scanners.
- Do not execute target code, scripts, builds, or dependency installers.
- Do not access the network, modify files, or delegate work.
- Read-only inspection may locate existing tool executables and inspect
  relevant configuration.
- Propose version/help checks as explicit actions for approval; do not
  assume arbitrary executables are safe to invoke.
- Return the plan in the response. Saving it requires separate approval.

## Select checks from repository evidence
Consider only checks relevant to the approved inventory and threat model:
- dependency advisory matching, including vendored components;
- static analysis of application code;
- secrets detection with mandatory output redaction;
- CI, deployment, and configuration review;
- manual investigation of application-specific trust boundaries.

Do not assume a package-manager audit covers vendored libraries.
Do not assume one scanner covers every language or vulnerability class.
Do not select tools merely because they are popular.
Separate dependency advisory checks from original-code analysis.

## Tool and advisory evidence
For each proposed tool:
- explain its purpose and applicable repository evidence;
- identify the executable or proposed installation source;
- record a verified version, or mark version unverified;
- propose a pinned version rather than an unqualified latest install;
- identify advisory database or ruleset sources and freshness needs;
- identify authoritative documentation needed to verify commands;
- do not invent flags, supported ecosystems, or offline capabilities;
- mark unverified capabilities and commands as pending verification.

If current documentation or advisory data is unavailable, request narrowly
scoped lookup permission or an approved local snapshot.
Do not substitute model memory for current verification.

## Permission and isolation plan
For every proposed action, state:
- where it runs: host, existing sandbox, or separate scanner environment;
- exact target paths and required read/write access;
- whether source code or metadata leaves the machine;
- required network destinations and their purpose;
- authentication requirements and approved secret-handling method;
- installation steps and whether elevated privileges are needed;
- output destinations outside the target checkout;
- execution timeout, output bounds, and resource limits;
- whether target code, plugins, hooks, or dependency scripts could execute.

Prefer read-only target access and the least privileges needed.
Do not propose privileged containers or mounting the Docker socket into
the agent sandbox.
Do not enable general sandbox networking just to refresh advisory data.
An online data-preparation step and an offline scan may be planned
separately, but verify tool support before claiming that workflow works.

## Snyk and other external services
Consider Snyk when it offers relevant coverage.
Before proposing its use, document:
- the specific product or scan mode;
- applicability to the repository's dependency layout;
- authentication and account requirements;
- source or metadata transmission;
- local versus remote analysis;
- licensing or usage constraints, if verified;
- user approval needed for external processing.

Do not assume a CLI invocation means analysis stays local.
Never request that tokens be pasted into chat or reports.

## Output and reproducibility
Plan separate locations for:
- raw scanner output;
- normalized, unreviewed candidates;
- reviewed finding proposals;
- run metadata and checkpoints.

Do not write raw output directly into the canonical findings store.
Record proposed tool versions, ruleset/database dates, commands,
target revision, exclusions, and expected exit-code interpretation.
Do not treat a nonzero exit code as a clean scan.
Document failures and incomplete coverage explicitly.

## Required response
Use these sections:
1. Baseline and approved scope
2. Proposed checks and coverage
3. Tool selection and unresolved verification
4. Permissions, connectivity, and data exposure
5. Exact proposed actions and output destinations
6. Resource limits and failure handling
7. Coverage gaps and exclusions
8. Approval request

Clearly label commands as proposals, not executed actions.
If a command cannot yet be verified, do not present it as ready to run.
Ask approval for one concrete next action.
Approval of one action does not authorize the whole plan.
Stop without installing tools or running scans.
