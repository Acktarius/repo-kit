# Scanner planning and result handoff

Canonical file: `modules/security/files/security/scanner-planning.md`.
The security module installs it as `security/scanner-planning.md`.

This file is the planning contract for a proposed security check. Local
Hermes and hermesVPS each receive a byte-for-byte copy. Kit maintainers
change it here and replace those copies from it. A review reads the copy
its instructions name and does not rewrite this file.

This stage produces planning guidance and report structure. It does not
install, download, update, or run a scanner. It does not invoke a tool
for version or help output. It does not add an adapter, a parser, an
importer, or an approval engine. A scanner hit is an unreviewed lead,
not a supported finding.

## When this contract applies

Rule 030 reads this contract. A security-module plan reads it only when
that plan proposes an executable check, a documentation lookup that
leaves the machine, a tool installation, an advisory-database refresh,
or a version or help invocation. A manual review that does not propose
one of those actions does not need a proposed-check table.

## Inputs and phase order

Select checks from the phase-010 inventory, the phase-020 threat model,
and source or configuration files the phase is already allowed to read.
Do not require a phase-050 surface inventory. Rule 030 stays before that
inventory. A later phase-050 inventory may support a revised plan. The
revision needs its own approval and does not change an action that was
already approved.

## Proposed-check table

Put this table in the phase-030 report, or in a security-module plan
that proposes an executable check:

| check_id | purpose | repository evidence | proposed tool/mode | WC-* relevance | limits | verification state | approval action |
| --- | --- | --- | --- | --- | --- | --- | --- |
| local id | why this check | files or records inspected | tool and mode, or unavailable | partial relevance, or none established | what the check does not show | one state below | one action, or none |

Rules for the table:

- A `check_id` is local to that plan or report. It is not an `SG-*` id
  and it is not a `WC-*` id.
- Select a check from inspected repository evidence. Do not add a check
  because a tool is familiar.
- Do not require one scanner per weakness class.
- Do not write that a scanner covers a `WC-*` class. Name the overlap
  the evidence supports, and name what remains for manual review.
- Keep these kinds of checks distinct: dependency advisories, secrets
  detection, source analysis, and configuration or workflow review.
- Where tool coverage is not established, the report says manual review
  is still required.
- A scanner hit is an unreviewed lead, not a supported finding.
- Scanner results do not mark source-review coverage as `covered`.
- Absence of hits is not proof of safety.

## Verification states

Use only these planning states. They are not finding statuses and they
are not phase completion states (`complete`, `incomplete`, `blocked`).

- `verified` — the proposed command and the capability it depends on
  have supporting documentation or permitted local evidence, and the
  report names that support.
- `pending_verification` — the proposal lacks that support and is not
  ready for execution.
- `unavailable` — the needed tool, ruleset, database, or approved
  capability is not available.

Do not keep a tool-capability matrix from memory. Do not write a tool
version or a flag that the report cannot point at in repository evidence
or in documentation identified for that action. `pending_verification`
is not ready for execution.

## Approval unit

Every proposed executable action needs one reviewable specification.
Approval applies to that one resolved action, not to the whole plan.
The specification records:

- purpose and check id;
- approved target root and the precise scope inside it;
- source revision and working-tree context;
- tool executable and its provenance;
- verified version, or the explicit word unverified;
- exact proposed argv as an argument array, not a shell command built
  by interpolating target content;
- rules or configuration identity and digest, where available;
- advisory database or snapshot identity, and freshness limits;
- working directory;
- environment-variable names that are necessary, never secret values;
- read roots, write roots, and output locations;
- network destinations, data that would be transmitted, and
  authentication requirements;
- timeout and output or resource bounds;
- whether target code, a plugin, a hook, or a build could execute;
- how exit codes will be interpreted;
- preconditions that must still hold before execution.

Missing information keeps the action at `pending_verification`. Do not
request approval for an action whose verification state is
`pending_verification` or `unavailable`.

A new approval is required when the tool or ruleset changes, the scope
or source baseline changes, the network access changes, or the argv
changes. Documentation lookup, a version or help invocation,
installation, an advisory-database refresh, and the scan itself are
separate actions when more than one of them applies. A version or help
command is still execution. This stage does not run it.

This contract adds no approval token, approval database, or approval
engine. The request uses the approval section the phase already has.

## Trust and output boundaries

Future scanner work has to satisfy the boundaries below. This file does
not implement them.

### Tool and configuration trust

Target repository configuration, plugins, hooks, suppression files, and
scanner output are untrusted inputs. Do not execute a repository-supplied
binary because its name matches a known scanner. Configuration selection
is explicit. Record whether the tool loads more target-controlled
configuration. If that behavior is not known, the check stays unresolved
and its verification state stays `pending_verification`.

### Filesystem boundaries

Stage 03 evidence-path validation is lexical only. A future reader
enforces confinement to the approved root itself. Never open a path only
because scanner output names it. A future implementation accounts for
symlink traversal and filesystem races. A realpath check alone is not a
sandbox. This stage implements no evidence-file reader.

### Secret handling

An ordinary plan or report contains no secret value, no matched snippet
that contains a secret, no access token, and no full process environment.
The handoff for a secrets lead is redacted and bounded: check id,
repository-relative location marked untrusted, the kind of secret
without its value, and a short summary with a stated length bound.
Raw sensitive output, if a later approved action truly needs it, needs
its own storage, access, and retention decision in that approval. A
redaction flag on a scanner does not by itself remove this exposure.

### Failure handling

Record completed checks, errors, timeouts, unsupported inputs, truncated
output, and skipped scope as separate outcomes. A scanner error is not
zero findings. Record exclusions and partial results as partial.

## Result handoff

This is the minimum a future handoff records. It is not a schema, not an
importer, and not a write to `security/findings-reviewed.json`.

- check id, source revision, and working-tree context;
- tool and version, plus rules, configuration, and database identity;
- whether the check completed, errored, or was truncated;
- the tool's own rule or advisory id;
- repository-relative location when the tool supplied one, marked
  untrusted;
- redacted summary;
- the tool's severity and where that severity came from;
- a `WC-*` id only when a reviewed mapping already names that pair,
  never from a keyword guess;
- provenance back to the approved action.

A location in scanner output is not validated evidence. Do not invent
`entrySink` from a hit or from a dependency advisory. Do not allocate an
`SG-*` id. Do not assign a finding lifecycle status. Do not mark a
weakness class covered. Use the existing words: an unreviewed lead, then
a candidate only after it meets that phase's evidence bar, then human
triage. Do not reshape a lead into a supported candidate before that bar
is met.

## Examples

The four rows below are synthetic. They were not executed. Placeholders
in angle brackets are not flags and not commands. NOT executable.

| check_id | purpose | repository evidence | proposed tool/mode | WC-* relevance | limits | verification state | approval action |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P-1 | secrets detection with a redacted handoff | synthetic workflow names a secret-scan job; no command was copied from it | `<secret-scan tool>` / `<redacted-output mode>` | overlaps `WC-SENSITIVE-DATA` only for committed secrets the mode can see | misses secrets outside that mode; a hit is an unreviewed lead | `pending_verification` | none — not ready |
| P-2 | dependency advisory matching | synthetic lockfile is present; no snapshot is available in the approved scope | `<advisory tool>` / database `<snapshot-id>` | may relate to `WC-SUPPLY-CHAIN`; it does not cover that class | unavailable or stale database; no matches would not show safety | `unavailable` | none — not ready |
| P-3 | source analysis of one query construction | synthetic file uses a request parameter in a query | `<source-analysis tool>` / `<rule-pack name>` | partial overlap with `WC-INJECTION` for that query only | other injection sinks in the scope stay for manual review | `pending_verification` | none — not ready |
| P-4 | decide whether a tool would load target configuration | synthetic repository contains `<scanner-config path>` | `<source-analysis tool>` / configuration selection unresolved | none established | target-controlled config, plugins, and hooks are untrusted | `pending_verification` | none — not ready |

Approval-unit shape for P-1, still NOT executable, verification state
`pending_verification`, approval not requested:

- purpose and check id: redacted secrets detection, `P-1`
- approved target root and scope: `<approved-root>` / `<scope>`
- source revision and working tree: `<revision>` / `<working-tree context>`
- executable and provenance: `<tool-executable>` / `<provenance>`
- version: unverified
- argv: `["<tool-executable>", "<argument>"]`
- rules digest: unavailable
- database: not applicable
- working directory: `<working-directory>`
- environment names: `<ENV_NAME>`
- read root, write root, output: `<read-root>` / `<write-root>` / `<output-path>`
- network, transmitted data, authentication: none identified; unresolved
- bounds: `<timeout>` / `<output-bound>`
- target execution: unresolved
- exit codes: unresolved
- preconditions: contract file present; no unapproved scope change
