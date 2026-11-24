# Surface and trust-boundary inventory

Canonical file: `modules/security/files/security/surface-inventory.md`.
The security module installs it as `security/surface-inventory.md`.

This file is the only inventory contract. Local Hermes and hermesVPS
each receive a byte-for-byte copy. Kit maintainers change it by editing
this file and replacing those copies from it. A review reads the copy
its instructions name and does not rewrite this contract. If that copy
cannot be read, report the path and stop. Do not treat any weakness
class as reviewed.

This is source-reading guidance and report structure. It is not a
scanner, a runtime discovery system, or a claim of complete application
coverage. Build the inventory from files in the approved scope. Do not
send requests, run the application, or execute target code to resolve
uncertainty.

Phase 010 repository inventory and `security/threat-model.md` stay
separate artifacts. Use them only where the active review rules already
permit, as evidence with provenance and limits. They do not prove that
a route is registered or reachable.

An inventory does not mark any weakness class `covered`. Class IDs and
coverage statuses come only from `weakness-classes.md`.

## Where the sections go

Write these four sections in the review narrative:

- security-module review text;
- Hermes phase 050, inside the existing required response: scope in
  section 1, both tables in section 2, linkage in section 7
  ("Coverage and completion state");
- hermesVPS phase 050: scope and both tables as their own sections;
  linkage inside the existing **Coverage limitations** section.

Keep existing report identity headers and completion states
(`complete`, `incomplete`, `blocked`). Do not add coverage fields or
surface IDs to findings JSON.

## 1. Review scope and inspection limits

State:

- the approved repository revision or working-tree context, when known;
- the approved paths, diff, priority, or other scope limit;
- whether the work is diff-scoped, priority-scoped, or broader;
- paths actually inspected, and important exclusions;
- search or output truncation, inaccessible files, and unresolved
  registration or configuration.

Do not widen the scope to make the inventory look complete. Work
outside the approved scope stays outside scope and is named as a
limitation. A missing or partial inventory is a review limitation. It
is not an application vulnerability.

## 2. Entry-point and sensitive-operation inventory

One row per surface in the approved scope. IDs are stable only inside
this report (`S-1`, `S-2`, …). They are not a global database.

| surface_id | kind/entry | evidence | trust boundary/inputs | controls observed | sensitive operation | class IDs | review state/limits |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `S-n` | kind and name | repo-relative path, symbol, line range | untrusted inputs by role | authn and authz, separately | operation or exposure | `WC-*` | state and limit |

Kinds, only when that kind is present: `http-handler`,
`graphql-resolver`, `websocket`, `rpc`, `webhook`, `queue-consumer`,
`scheduled-job`, `cli`, `file-input`, `ci-build`. Name any other kind
in the cell. Do not force an HTTP model onto a library, a command-line
tool, or an infrastructure repository.

Record a route or handler declaration separately from verified
registration or reachability. A declaration does not prove runtime
exposure. Use review state `declared-only` until registration is shown
in source. Do not confirm reachability by calling the service.

Name object IDs, tenant IDs, URL or destination inputs, paths, and
security-relevant writable fields by role. Do not copy secret values,
credentials, private keys, personal records, or live payloads.

Authentication and authorization are separate controls. Mark each
`observed`, `unresolved`, or `outside-scope`, and cite the file and
symbol when observed. An unlocated check is `unresolved`. It is not
automatically an absent check and it is not a finding.

Record a sensitive output or exposure boundary in the sensitive
operation or limits cell when the surface returns or writes data.

Review states:

- `inspected` — the cited source was read in this review;
- `declared-only` — a declaration was seen; registration or reachability was not verified;
- `unresolved` — the relationship or control was not established from the files read;
- `excluded` — in the repository, left out of this inspection, with the reason;
- `outside-scope` — not in the approved scope; record it only as a limitation.

Discovery of a surface is a review lead. It becomes a finding only
under the weakness-class evidence bar.

## 3. Persisted-input and second-order flows

One row per handoff whose writer or reader is in the approved scope.
IDs are stable only inside this report (`F-1`, `F-2`, …).

| flow_id | untrusted source/writer | store or handoff | reader/consumer | sensitive use | controls/evidence | limits |
| --- | --- | --- | --- | --- | --- | --- |
| `F-n` | writer path and symbol, or `unresolved` | database, cache, queue, or file | reader path and symbol, or `unresolved` | later sensitive use | check and whether it binds the same value | proven, suspected, or unresolved |

Include database, cache, queue, and filesystem handoffs that the
approved scope supports. Link `S-*` IDs in the writer or reader cell
when that surface is already in the table.

An evidenced writer-to-reader relationship cites both sides in source.
A shared field or column name is not proof of a flow. Mark that row
suspected or unresolved and keep the missing side. Do not drop
unresolved producer or consumer links.

When a check exists, record whether it binds the same value, identity,
tenant, and scope that the sensitive operation uses. A traceable,
unchanged or demonstrably equivalent value may preserve the check. A
changed value, or a value whose equivalence is not established, remains
`unresolved` for that use.

Do not copy credentials, private keys, personal records, or live
payloads into the row.

## 4. Coverage linkage and gaps

The weakness-class coverage table stays the coverage record. A row may
cite `S-*` and `F-*` IDs. Creating those IDs does not mark the class
`covered`.

Preserve grouped-variant rules in `weakness-classes.md`. If any
applicable variant was not inspected, the class is `not_reviewed`.

An applicable surface inside the declared review scope that was not
inspected keeps that class `not_reviewed`. Name the surface or the
gap. Out-of-scope work stays a limitation. It does not become
`not_applicable` merely because it was not opened.

"Not observed in inspected files" does not mean "does not exist".
Record that limit on the class and on the inventory row.

Do not report a coverage percentage, a completeness guarantee, or a
security score.

## Review order

1. Read this contract and `weakness-classes.md`.
2. Write an initial inventory bounded to the approved scope.
3. Review those surfaces and flows for weaknesses.
4. Add in-scope relationships that reading reveals.
5. Leave unresolved routes and flows unresolved.

Do not invent a route, a registration, or a consumer to fill a cell.
Do not carry coverage from another review, priority, or revision.
Another invocation's inventory is evidence only when the active rules
already select that artifact. Name its id, revision, and limits.

hermesVPS phase 050 inventories one approved priority and the
supporting context that priority's rules already allow. It does not
require a whole-repository inventory.

## Examples

These rows are documentation examples. They are not review findings,
not coverage results, and not evidence about any repository.

### Example 1 — object-scoped handler

Priority-scoped review of order reads. The route line is a declaration.
The mux that registers it was not in the approved paths, so exposure
stays `declared-only`.

| surface_id | kind/entry | evidence | trust boundary/inputs | controls observed | sensitive operation | class IDs | review state/limits |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S-1 | http-handler `GetOrder` | `pkg/orders/get.go` `GetOrder` lines 40-88. Declaration `GET /orders/{id}` in `pkg/orders/routes.go` lines 12-14. | Caller-supplied order id. Session subject `session.User`. | authn: unresolved. `session.User` at line 44 is the loaded subject; this synthetic example does not show the credential check. authz: observed, owner comparison at lines 61-66 before the load at line 70. | Load one order row for that owner. Response returns that row's fields. | WC-AUTHZ-OBJECT | handler inspected; route registration outside the approved paths (`declared-only`) |

### Example 2 — stored input, consumer unresolved

| flow_id | untrusted source/writer | store or handoff | reader/consumer | sensitive use | controls/evidence | limits |
| --- | --- | --- | --- | --- | --- | --- |
| F-1 | `pkg/profile/save.go` `SaveDisplayName` writes the submitted display name. Link the surface ID when that handler is already a row. | database column `profiles.display_name` | unresolved | suspected later render. Column name alone does not prove a reader. | Writer stores the string. No output control at the write. | suspected; consumer not found in inspected files. Do not treat the column name as a flow. |

### Example 3 — CLI and queue inputs, not an HTTP service

| surface_id | kind/entry | evidence | trust boundary/inputs | controls observed | sensitive operation | class IDs | review state/limits |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S-3 | cli `runImport` | `cmd/import/main.go` `runImport` lines 20-55. Flag `-file`. | Operator-supplied file path. | authn: outside-scope (the OS user runs the process). authz: unresolved for which paths the process may read. | Read the named file and insert rows. | WC-FILE-ACCESS | inspected in the CLI package. No HTTP handlers in this scope. |
| S-5 | queue-consumer `OnUpload` | `internal/worker/upload.go` `OnUpload` lines 12-40. Queue name `uploads`. | Message field `object_key` from the queue. | authn: unresolved (worker identity not in the inspected file). authz: unresolved. | Read the named object and store metadata. | WC-FILE-ACCESS | inspected. Kind is `queue-consumer`, not an HTTP handler. |

### Example 4 — diff-scoped review with gaps

Scope: diff of `internal/api/invoice.go` only. Diff-scoped. Middleware
and route registration are not in the diff.

| surface_id | kind/entry | evidence | trust boundary/inputs | controls observed | sensitive operation | class IDs | review state/limits |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S-4 | http-handler `PostInvoice` | `internal/api/invoice.go` `PostInvoice` lines 15-40, the added function. | Caller-supplied `tenant_id` field. | authn: unresolved (middleware not in the diff). authz: unresolved. | Insert an invoice for `tenant_id`. | WC-AUTHZ-OBJECT | diff-scoped. Uninspected middleware keeps WC-AUTHZ-OBJECT `not_reviewed` for this scope. Gap is a review limit, not a finding. |

Coverage sketch for example 4, still not a review result: `WC-AUTHZ-OBJECT`
is `not_reviewed` because the applicable authorization surface was not
in the diff. The inventory row does not flip that status to `covered`.
