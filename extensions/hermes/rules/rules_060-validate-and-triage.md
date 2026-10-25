# Rule 060 — Validate and triage security candidates

## Prerequisites
- Apply rules_000-safety-and-scope.md throughout this phase.
- Apply rules_005-report-output.md for report artefact writes.
- Require an approved target, review scope, and candidate evidence
  from Rule 040 or Rule 050.
- Read existing reviewed findings and accepted risks when present.
- Confirm the full commit hash and working-tree state.
- If candidate evidence describes a different checkout, report the
  mismatch and stop for approval.
- Missing findings stores are context gaps, not permission to create them.

## Permissions
Read-only validation is the default.
Do not:
- execute target code, exploits, tests, builds, or scripts;
- probe deployed services or validate discovered credentials;
- install tools or access the network;
- modify findings, accepted risks, or security settings;
- modify files outside `.repo-kit/hermes/reports/` per Rule 005;
- delegate work.
Write the phase report to
`.repo-kit/hermes/reports/phase-060-validate-and-triage.md`
(or a timestamped variant if that file already exists).
Any additional validation action requires specific approval.
Describe proposed tests without executing them.

## 1. Normalize evidence
For each candidate, collect:
- temporary candidate ID and originating phase;
- repository revision and affected paths;
- component and version evidence, when relevant;
- code or configuration evidence;
- advisory aliases and verified references;
- tool versions and advisory-data dates, when applicable;
- preconditions, controls, impact, and unresolved assumptions.

Do not treat an earlier agent summary as primary evidence.
Revisit relevant source or raw scanner evidence within the approved scope.
Preserve source provenance and redact sensitive values.

## 2. Validate the claim
For dependency candidates:
- confirm component identity and local version evidence;
- confirm affected-range matching and relevant advisory exceptions;
- distinguish affected-version presence from demonstrated exploitability;
- record reachability and deployment preconditions separately;
- retain uncertainty for modified or ambiguously identified vendored code.

For source candidates:
- trace attacker-controlled input to the sensitive operation;
- inspect relevant validation, encoding, and authorization controls;
- distinguish actual behavior from deployment assumptions;
- confirm that the proposed impact follows from the evidence;
- require additional evidence rather than inventing a missing link.

For all candidates:
- verify references or mark verification pending;
- record conflicting evidence explicitly;
- do not require exploit execution to establish every valid finding;
- do not claim exploitability was demonstrated when it was not.

## 3. Deduplicate
Compare candidates against:
- other candidates in this review;
- security/findings-reviewed.json;
- security/accepted-risks.md;
- referenced evidence records when available.

Deduplicate by root cause, affected component, and remediation boundary,
not merely by similar titles.
Treat multiple advisory aliases as one issue when evidence supports that.
Do not merge distinct vulnerabilities merely because they share a file.
Preserve existing SG identifiers.
Do not reopen an accepted risk without identifying a material change
and obtaining human approval.

Do not reopen an accepted risk without identifying a material change
and obtaining human approval.


## Mandatory evidence gate before disposition
Treat prior candidate reports as claims to verify, not established facts.
Do not inherit their confidence, exploitability, or classification.

Before assigning validated-new:

1. Verify cited files and symbols against the current reviewed revision.
   If a cited symbol is missing, identify the incorrect citation and
   reassess the claim using actual evidence. Do not invent a replacement.

2. For source candidates, trace the relevant value from its actual source
   to the security-sensitive operation. Quote short source values or
   representative examples, with file paths and line numbers where
   available. A dangerous API or sink alone is not a vulnerability.

3. For source candidates, identify the attacker, their evidenced
   capabilities, and the trust boundary crossed. Distinguish selecting
   a trusted resource from controlling its contents.

4. Establish the material preconditions of the claimed weakness with
   evidence. List unsupported preconditions explicitly. Do not treat
   hypothetical server compromise or arbitrary repository modification
   as established attacker control.

5. Check evidence that could disprove the claim, including allowlists,
   fixed resource mappings, validation, encoding, sanitization, and
   authorization controls. Explain whether relevant controls break
   the claimed exploit chain.

6. If a remediation is proposed, check it against actual values and
   intended behavior. Do not endorse replacing HTML rendering with
   plain-text rendering without checking for intentional markup.
   Describe unverified compatibility assumptions explicitly.

Apply these decision boundaries:
- Use validated-new only when evidence supports the specific weakness
  and impact claimed.
- For dependency candidates, verified affected-component presence may
  support validated-new without demonstrated application reachability.
  State that limitation and do not claim demonstrated exploitability.
- Use pending-evidence when a material link needed to establish the
  claimed weakness remains unproven.
- Use rejected when evidence disproves the claim or the claimed attack
  crosses no additional security boundary.
- Describe defense-in-depth suggestions separately as hardening notes,
  not as validated vulnerabilities.

An unresolved material precondition blocks validation of any claim
that depends on it, regardless of confidence in an earlier report.
A high-confidence sink observation is not high-confidence exploitability.
Exploit execution is not required when source or advisory evidence
already establishes the claimed weakness.

If a CWE is proposed, verify that its definition matches the actual
weakness. If verification is unavailable, mark classification unverified;
do not guess an identifier or let classification substitute for evidence.

## 4. Assign a proposed disposition
Use one of these triage dispositions:
- validated-new;
- existing-record;
- duplicate;
- covered-by-accepted-risk;
- rejected;
- pending-evidence.

These are triage labels, not additions to the canonical status enum.
Explain the evidence supporting each disposition.
Link existing SG or accepted-risk identifiers where applicable.
A missing reference or unknown version may require pending-evidence,
not automatic rejection.
Do not turn pending-evidence into an open reviewed finding merely
to satisfy the schema.

## 5. Assess severity and confidence
- Separate source advisory severity from deployment-specific assessment.
- Explain the basis of proposed severity and confidence.
- Do not invent CVSS scores.
- Keep unknown severity explicit rather than defaulting to low.
- If the reviewed schema cannot represent the current uncertainty,
  leave the candidate pending and state what evidence is needed.
- A verified affected component can remain a valid dependency concern
  even when application reachability is unknown; describe the limit.

## 6. Prepare the human decision
For each candidate, report:
- candidate ID and proposed disposition;
- supporting and contradicting evidence;
- existing-record or accepted-risk linkage;
- proposed severity and confidence, with rationale;
- unresolved questions and validation limits;
- recommended next action.

Do not allocate permanent SG IDs during this phase.
Do not write to canonical stores or accept risks.
Do not apply fixes or mark existing records fixed.

## Required response
Use these sections:
1. Baseline and reviewed evidence
2. Candidate triage table
3. Validation details and reference provenance
4. Duplicate and accepted-risk relationships
5. Pending evidence and proposed validation actions
6. Completion state and human decisions required

A candidate remains unresolved when required evidence is missing.
Report completed triage separately from completed security coverage.
Stop after writing the phase report and wait for approval before
proposing canonical finding records.
