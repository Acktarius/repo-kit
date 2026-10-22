# Rule 070 — Propose human-reviewed finding records

## Prerequisites
- Apply rules_000-safety-and-scope.md throughout this phase.
- Require a human-approved candidate from Rule 060.
- Process one explicitly selected candidate at a time.
- Require the current findings schema and existing findings store,
  or explicit confirmation that no store exists yet.
- Read accepted risks and the finding template when available.
- Confirm the target revision and working-tree state.
- Stop if material evidence has changed or prerequisites are missing.

## Permissions
The default action is to propose a record in the response.
Do not create or modify files, allocate an ID in a persistent store,
accept risks, apply fixes, or change existing records automatically.
Saving requires approval of the exact destination and proposed content.
Approval to generate a proposal is not approval to save it.

## Eligibility
- Only validated, human-approved candidates may become new proposals.
- Do not convert pending-evidence candidates into reviewed findings.
- For an existing record, propose an update instead of a duplicate.
- For a duplicate or accepted risk, preserve the existing linkage.
- Risk acceptance requires its own explicit human decision.
- Missing severity or essential evidence must be resolved before
  proposing a record that requires those fields.
- Do not weaken or silently extend the schema to make a candidate fit.

## Schema compatibility
Read and follow the actual security/findings.schema.json.
For the current repo-kit schema:
- preserve the SG-[0-9]{3,} identifier format;
- use only allowed lifecycle statuses;
- use only allowed severity and confidence values;
- do not add undeclared fields;
- record files as repository-relative paths;
- place detailed advisory and reference evidence in notes.

If the schema differs from these expectations, report the difference
and follow the approved current schema rather than assuming compatibility.

## Identifier handling
- Inspect existing identifiers before suggesting a new SG identifier.
- Label a new identifier as proposed, not reserved or saved.
- Do not renumber existing findings.
- Recheck identifier availability immediately before an approved write.
- If the store changed after approval, stop and request fresh approval
  for any revised content.

## Required evidence
The proposal must preserve:
- repository revision and candidate provenance;
- affected paths and relevant functions or line numbers;
- root cause and concise supporting evidence;
- attacker capabilities and necessary preconditions;
- high-level exploit path and supported impact;
- confidence and deployment uncertainty;
- concrete remediation direction and verification criteria;
- duplicate or accepted-risk relationships where applicable.

For dependency findings, also preserve:
- component identity and locally evidenced version;
- advisory identifiers and aliases;
- exact verified source URLs and lookup dates;
- affected ranges and local comparison;
- advisory database or snapshot dates when relevant;
- source severity separately from local risk assessment;
- reachability and exploitability limits.

Do not invent values to fill optional fields.
Use null or omit optional fields where the schema permits.

## Proposal format
Return:
1. A concise explanation of why the candidate qualifies.
2. One proposed finding object matching the approved schema.
3. An explanation of severity, confidence, and remaining limitations.
4. The intended destination and proposed change, without writing it.
5. A request for human approval if saving is requested.

Do not expose secrets in evidence or references.
Do not represent proposed timestamps as past review events.
Use verified timestamps when available; otherwise leave optional dates
unset and state that they will be populated at approved recording time.

## Validation and saving
Before any approved write:
- verify that the current store and schema have not changed;
- validate the complete proposed store, not just the individual object;
- use an approved validator and command;
- do not claim machine validation unless it actually ran successfully.

If validation tooling is unavailable, report that limitation and request
approval for a specific validation action.
Do not silently replace machine validation with an assertion.

An approved write must preserve unrelated records.
Do not create commits, push changes, or publish findings without
separate approval.
Stop after proposing or completing the specifically approved action.
