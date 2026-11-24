<!-- hermes-vps-report: REPLACE THIS LINE WITH THE REPORT IDENTITY HEADER PRINTED BY hermes-vps-review -->
# Phase 050 — Source and Configuration Review

## Run identity

- Run ID / source commit / prior artifact IDs
- Review priority: `<priority_name>`
- One priority for this invocation. Do not import coverage from another priority or revision.

## Prior artifacts

- Selected phase 010 and 020 IDs and SHA-256 status
- Phase 030 only when this review is scanner-assisted

## Review priority

Priority name and the boundary of this invocation.

## Review scope and inspection limits

- Diff-scoped, priority-scoped, or broader
- Inspected paths, exclusions, truncation, and inaccessible files
- Do not widen the priority to fill the inventory

## Entry-point and sensitive-operation inventory

| surface_id | kind/entry | evidence | trust boundary/inputs | controls observed | sensitive operation | class IDs | review state/limits |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S-n | | repo-relative path and symbol | roles, not secret values | authn and authz separately | | WC-* | |

## Persisted-input and second-order flows

| flow_id | untrusted source/writer | store or handoff | reader/consumer | sensitive use | controls/evidence | limits |
| --- | --- | --- | --- | --- | --- | --- |
| F-n | | database, cache, queue, or file | unresolved if unseen | | same value, identity, tenant, and scope | suspected or unresolved stays labeled |

## Candidate issues

For each candidate:

### `<CANDIDATE_TITLE>`

- **File**: `path/to/file.ext`
- **Lines**: NNN–MMM
- **Evidence**: (code excerpt or configuration value)
- **Severity estimate**: low | medium | high | critical
- **Confidence**: low | medium | high
- **Attack path**: (describe how this could be exploited)
- **Notes**: (uncertainties; mark speculative items)

An inventory row is not a candidate. Discovery alone is not a finding.

## Unexecuted checks

## Coverage limitations

Include every weakness class and "Coverage linkage and gaps".
An inventory does not mark any weakness class `covered`.
Cite S-* and F-* IDs where useful. No percentages or completeness claims.

## Completion state

State: `complete` | `incomplete` | `blocked`

Next human gate: separate explicit request required before phase 060.
A separate invocation is required for each additional review priority.
