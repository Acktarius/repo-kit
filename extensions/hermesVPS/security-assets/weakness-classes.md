# Defensive weakness-class catalog

Canonical file: `modules/security/files/security/weakness-classes.md`.
The security module installs it as `security/weakness-classes.md`.

This file is the only weakness-class list. Local Hermes and hermesVPS
each receive a byte-for-byte copy. Kit maintainers change classes by
editing this file and replacing those copies from it. A review reads the
copy its instructions name and does not rewrite this catalog. If that
copy cannot be read, report the path and stop. Do not treat any class
as reviewed.

This is source-review guidance and coverage accounting. It is not a
scanner, and a catalog entry is not an automated check. Apply a class
only when the repository shape makes it relevant. Do not force a web or
API model onto a library, CLI, worker, or infrastructure project.
Scanner planning and scanner results do not mark a class `covered`.
Presence of a technology, a missing optional hardening setting, or a
keyword match is not a confirmed vulnerability. A source-supported
finding does not require exploit execution.

## Coverage contract

Put this table in the review's existing narrative:

- security-module review text;
- Hermes phase 050 section "Coverage and completion state";
- hermesVPS phase 050 section "Coverage limitations".

Do not add coverage fields to findings JSON or change finding statuses.

| class_id | status | scope/evidence | limitation or rationale |
| --- | --- | --- | --- |
| `WC-...` | `covered`, `not_applicable`, or `not_reviewed` | files, symbols, controls, or linked findings | why that status |

Include every `WC-` class in this file, once. Use only these statuses:

- `covered` — the class was reviewed inside the declared scope. The
  scope/evidence cell cites files or symbols and explains the relevant
  controls or links the findings. `covered` means the review happened.
  It does not mean the code is secure or free of weaknesses. A class can
  be `covered` and still have findings.
- `not_applicable` — the declared scope has a concrete reason the class
  has no relevant entry point, sink, or security decision. Name that
  reason. An uninspected area is not a reason.
- `not_reviewed` — inspection was incomplete, blocked, or outside the
  review budget. State the limitation. Missing evidence stays
  `not_reviewed`.

Further rules:

- Do not report a coverage percentage or a completeness guarantee.
- This table records source and configuration review. Scanner output,
  dependency-advisory review, and CI results do not mark a class
  `covered`.
- When a class lists variants, the row accounts for each one as reviewed,
  not applicable in this scope, or not reviewed. If any applicable
  variant was not inspected, the class status is `not_reviewed`.
  Reviewing one variant does not cover another. One absent variant does
  not make the class `not_applicable` while another applicable variant
  remains.
- Work outside the approved scope is `not_reviewed`, with that limit
  named. `not_applicable` is for a surface the approved scope does not
  contain.

Source review also follows `surface-inventory.md` (installed beside
this catalog). Coverage rows may cite that inventory's `S-*` and `F-*`
IDs. An inventory does not mark any weakness class `covered`. An
applicable surface inside the declared scope that was not inspected
keeps the class `not_reviewed`.

A supported finding identifies all of the following:

1. a reachable entry point or trust boundary;
2. the flow or security decision that uses the untrusted value;
3. the sensitive operation;
4. the control that is absent or that does not hold.

If any of those is unresolved, leave the case unresolved. Hermes phase
050 keeps the existing candidate and unresolved-question wording and
does not present the case as a supported finding. The security-module
review does not call it a valid finding. This bar adds to each
consumer's existing evidence rules. It does not replace or relax them.

Illustration of the columns only. This row is not a review result:

| class_id | status | scope/evidence | limitation or rationale |
| --- | --- | --- | --- |
| WC-CSRF | not_applicable | State-changing routes in the approved scope (`src/api/router.ts`) authenticate with a caller-supplied bearer header. | Those routes do not accept ambient browser credentials. |

## Classes

### WC-AUTHZ-OBJECT

- **Name:** Object-level authorization and tenant isolation
- **Description:** A caller may access or change only the objects and tenant data their authority allows.
- **CWE:** CWE-639
- **Variants:** object access; tenant isolation
- **Trust boundary:** Object ids, tenant ids, or ownership fields from the caller, from a caller-influenced token claim, or from stored untrusted data.
- **Sensitive operation:** Read, update, delete, or export of a specific object or tenant-scoped record.
- **Defensive control:** On the server, decide with the authenticated subject and a trusted owner or tenant record, then use that same decision in the query or fetch.
- **Evidence:** Entry point, identifier, authorization decision, and the operation that consumes the decision, showing they refer to the same object and tenant.
- **Applicability:** Applies when an id or key selects an object or tenant. Name tenant isolation `not_applicable` only when the reviewed system has a single tenant. A route that accepts an id is a review lead. It becomes a finding only when the check is missing or the checked value differs from the value the operation uses. A client-side check does not satisfy the control.

### WC-AUTHZ-FUNCTION

- **Name:** Function-level authorization
- **Description:** A caller may invoke only the actions their role or scope allows, including administrative actions.
- **CWE:** CWE-285
- **Trust boundary:** Anonymous or authenticated callers reaching a privileged action, including alternate routes and non-browser clients.
- **Sensitive operation:** Admin, staff, billing, role-changing, or other privileged function.
- **Defensive control:** Enforce an explicit server-side check for that action before performing it.
- **Evidence:** Entry point, the authority the decision uses, and the privileged operation that follows.
- **Applicability:** Applies to privileged operations in the approved scope. The existence of an admin route is a review lead, not a finding, until the check is absent or ineffective. Hiding a control in the interface does not satisfy the control.

### WC-AUTHZ-PROPERTY

- **Name:** Property-level authorization and excessive exposure
- **Description:** A caller must not write or receive fields outside the set allowed for that action and audience.
- **CWE:** CWE-915 for mass assignment; CWE-213 for exposure through an incompatible disclosure policy
- **Variants:** mass assignment; excessive exposure
- **Trust boundary:** Request bodies, query parameters, or serialized objects whose property set the caller can influence; responses and exports built from stored records.
- **Sensitive operation:** Binding input onto a privileged field, or returning sensitive or other-users' fields.
- **Defensive control:** Allow-list the fields that action may write, and allow-list the fields that audience may receive.
- **Evidence:** The input or output site, the field that crosses the boundary, and the allow-list or its absence.
- **Applicability:** Applies when the scope writes or returns structured objects. A broad serializer is a review lead. It becomes a finding only when a sensitive or privileged field is writable or visible to a caller who lacks that authority.

### WC-AUTHN

- **Name:** Authentication, session, and token validation
- **Description:** A security decision must use a caller identity the server has validated.
- **CWE:** CWE-287; CWE-613 when session lifetime is the defect; CWE-347 when trust rests on a signature or MAC. No CWE is asserted for PKCE itself.
- **Variants:** session; bearer/JWT; OAuth/PKCE
- **Trust boundary:** Cookies, authorization headers, token parameters, OAuth redirects, and assertions produced outside the service.
- **Sensitive operation:** Accepting a session or token as identity, or issuing a session from an OAuth code exchange.
- **Defensive control:** Validate the credential on the server before use, including signature or MAC, issuer, audience, expiry, and the session store or revocation check the design relies on. For an OAuth authorization-code client that cannot hold a client secret, require PKCE. Feed the validated identity into later authorization.
- **Evidence:** The acceptance site, the checks performed, and the identity value later decisions use.
- **Applicability:** Account for each variant present in the scope. A JWT library or an OAuth dependency is not a finding. A skipped check is a finding only for a credential the service accepts.

### WC-INJECTION

- **Name:** SQL, NoSQL, command, and template injection
- **Description:** Untrusted data must not change the structure of a query, command, or template.
- **CWE:** CWE-89 (SQL), CWE-943 (NoSQL), CWE-78 (OS command), CWE-1336 (server-side template). Cite a CWE only for a variant whose sink is in scope.
- **Variants:** SQL; NoSQL; command; template
- **Trust boundary:** Request data and stored, queued, or file-backed untrusted strings that reach a query, command, or template.
- **Sensitive operation:** Building a SQL or NoSQL query, a process or shell command, or a server-side template.
- **Defensive control:** Keep data out of the control channel: parameterized queries, allow-listed operators and fields, argument arrays that do not invoke a shell, and templates that do not evaluate caller-controlled directives.
- **Evidence:** The source, the construction site, and whether the untrusted value can change query structure, command structure, or template code.
- **Applicability:** Account for each variant that has a sink in scope. A database driver or a template library is not a finding. String concatenation is a finding only when untrusted data can change that structure.

### WC-XSS

- **Name:** Browser script injection
- **Description:** Untrusted data must not execute as script in a browser.
- **CWE:** CWE-79
- **Trust boundary:** Untrusted strings placed into HTML, script, URLs, or DOM APIs.
- **Sensitive operation:** Writing that data into a browser execution context.
- **Defensive control:** Encode for the destination context, or use a DOM API that does not parse HTML. Apply the control at the sink whose context is known.
- **Evidence:** The source, the output context, and the encoding or API used there.
- **Applicability:** Applies where the scope renders untrusted data to a browser. A template engine is not a finding.

### WC-CSRF

- **Name:** Cross-site request forgery
- **Description:** A state-changing action that trusts ambient browser credentials must require a secret the other site cannot attach.
- **CWE:** CWE-352
- **Trust boundary:** Browser requests that carry cookies or other credentials the browser attaches by itself.
- **Sensitive operation:** The state-changing action accepted on that request.
- **Defensive control:** Require a per-session or per-request secret the attacking origin cannot supply, or a same-site cookie policy that applies to the request, and reject the action when the check fails.
- **Evidence:** The state-changing entry point, how the browser authenticates it, and the anti-forgery check.
- **Applicability:** Applies where ambient browser credentials authorize the action. Requests authenticated only by a header the browser does not attach cross-site are outside this class when that is the only authenticator.

### WC-FILE-ACCESS

- **Name:** Path traversal, unsafe file operations, and file inclusion
- **Description:** Untrusted input must not choose a path, file operation, or included file outside the intended set.
- **CWE:** CWE-22 for traversal; CWE-73 for an externally influenced file name or path; CWE-98 only for include or require of an attacker-influenced path (the CWE name is PHP-specific).
- **Variants:** path traversal; unsafe file operations; file inclusion
- **Trust boundary:** File names, paths, archive entries, and upload metadata from callers or from stored untrusted content.
- **Sensitive operation:** Open, read, write, delete, move, or include a file.
- **Defensive control:** Resolve the path and confine it to an allow-listed root or key before the filesystem operation. Do not include or execute a file selected by the caller.
- **Evidence:** The input, the path computation, the confinement check, and the filesystem or include call.
- **Applicability:** Account for each variant that exists in scope. A file API is not a finding.

### WC-CODE-EXEC

- **Name:** Unsafe deserialization and dynamic code evaluation
- **Description:** Untrusted bytes or text must not become objects with behavior or executable code.
- **CWE:** CWE-502 for deserialization; CWE-95 for eval-style execution
- **Variants:** deserialization; dynamic evaluation
- **Trust boundary:** Request bodies, messages, files, or caches passed to a loader or evaluator.
- **Sensitive operation:** Deserialization or evaluation that can construct privileged objects or run code.
- **Defensive control:** Accept a restricted data format, or an allow-list of types, and do not pass caller-controlled text to a general-purpose evaluator.
- **Evidence:** The payload source and the loader or evaluator, including the type or language restriction.
- **Applicability:** Parsing JSON as data, with no object behavior and no evaluator, is outside this class. A deserializer is a finding only when it accepts untrusted input without a restriction that holds.

### WC-SSRF

- **Name:** Server-side request forgery and outbound destination trust
- **Description:** The server must fetch only destinations it is allowed to fetch.
- **CWE:** CWE-918
- **Trust boundary:** URLs or host names from callers, stored content, or redirects returned by an untrusted server.
- **Sensitive operation:** An outbound request whose target can be influenced, including webhooks and URL preview.
- **Defensive control:** Allow-list the destination, or resolve it and reject untrusted, link-local, and metadata addresses before connecting, and apply the same check to redirects.
- **Evidence:** The URL source, the request site, and the destination check.
- **Applicability:** Applies when an outbound target can be influenced from the approved scope. An HTTP client with a fixed trusted host is outside this class. The client library alone is not a finding.

### WC-REDIRECT

- **Name:** Open redirects
- **Description:** A redirect must send the browser only to a target the application allows.
- **CWE:** CWE-601
- **Trust boundary:** Redirect targets from query parameters, form fields, or stored content.
- **Sensitive operation:** Sending the browser to that URL, including after login or with a token in the request.
- **Defensive control:** Allow-list a relative path or a known host before redirecting.
- **Evidence:** The parameter, the redirect call, and the allow-list.
- **Applicability:** Applies when untrusted data can choose the target. A redirect to a fixed path is outside this class.

### WC-SENSITIVE-DATA

- **Name:** Embedded secrets and sensitive information exposure
- **Description:** Secrets and sensitive data must stay out of source, logs, responses, and generated artifacts unless that location is an intended, authorized disclosure.
- **CWE:** CWE-798 for hard-coded credentials; CWE-532 for logs; CWE-200 for exposure to an unauthorized actor
- **Variants:** embedded secrets; logs; responses; generated artifacts
- **Trust boundary:** Committed source and config, logs, API responses, error output, client bundles, and review reports.
- **Sensitive operation:** Embedding a secret, or writing a secret, token, or sensitive record into a log, response, or artifact.
- **Defensive control:** Load secrets from a store that is not committed. Redact logs and errors. Return only fields that caller may see. Keep review artifacts free of secret values.
- **Evidence:** The committed location or the write site, and the missing redaction or exclusion. Do not copy secret values into the review.
- **Applicability:** A limited review does not establish that secrets are absent; record that limit as `not_reviewed`. A name that contains "secret" is not a finding. Use `not_applicable` only when the approved scope has neither secret material nor sensitive output.

### WC-CRYPTO

- **Name:** Cryptographic misuse and unsafe transport
- **Description:** Cryptography and transport must provide the protection the product claims.
- **CWE:** CWE-327 for a broken or risky cryptographic construction; CWE-295 for certificate validation; CWE-319 for cleartext transmission of sensitive information
- **Variants:** cryptographic misuse; transport configuration
- **Trust boundary:** Keys, plaintext, ciphertext, tokens, and connections that are supposed to provide confidentiality or integrity.
- **Sensitive operation:** Encryption, signing, password verification, TLS setup, or certificate checks.
- **Defensive control:** Use a construction suited to the data and verify the remote certificate. Keep private keys out of the repository and out of client bundles.
- **Evidence:** The call and parameters that select the algorithm, mode, or verification behavior, and the data that depends on them.
- **Applicability:** Account for both variants when each exists. A hash library or a TLS library is not a finding. An optional header is a finding only when the reviewed configuration turns off a control a sensitive operation requires.

### WC-RESOURCE-LIMITS

- **Name:** Unbounded resource consumption
- **Description:** Untrusted input must not be able to force unbounded work, memory, storage, or concurrency.
- **CWE:** CWE-770; CWE-400
- **Trust boundary:** Sizes, counts, nesting, and rates a caller or a fetched document can influence.
- **Sensitive operation:** Allocation, parsing, queries, decompression, or fan-out.
- **Defensive control:** Enforce a limit on size, depth, time, or concurrency before the expensive work.
- **Evidence:** The dimension the caller controls, the work it triggers, and the limit. A deployment quota that was not verified remains unknown.
- **Applicability:** Applies where the approved scope lets a caller influence cost. A missing process-wide rate limit is not a finding for an operation that already bounds the caller-controlled dimension.

### WC-SUPPLY-CHAIN

- **Name:** CI, build, and supply-chain trust boundaries
- **Description:** Build and automation must keep untrusted code, artifacts, and parameters away from secrets and publish rights.
- **CWE:** CWE-494 when code or tools are downloaded without an integrity check; CWE-829 when the workflow includes functionality from an untrusted control sphere. Cite only the pattern present.
- **Variants:** CI and workflow permissions; build inputs; downloaded tools and artifacts
- **Trust boundary:** Pull requests, untrusted branches, third-party automation, downloaded tools, and build parameters.
- **Sensitive operation:** Running with secrets, publishing artifacts, or granting a token to a workflow an outsider can influence.
- **Defensive control:** Keep untrusted execution separate from secrets, check integrity of downloaded tools, and limit the token to the job that needs it.
- **Evidence:** The workflow or build step, the untrusted input, and the secret or permission it can reach.
- **Applicability:** This class is source review of build and automation files in the approved scope. It is not a dependency-advisory scan and it does not mark advisory coverage. A third-party action is a review lead until its inputs and privileges show a broken boundary. Files that exist outside the approved scope stay `not_reviewed`.

### WC-WEBSOCKET

- **Name:** WebSocket origin, authentication, and per-message authorization
- **Description:** A WebSocket handshake must establish who is calling, and each message must be authorized for its action.
- **CWE:** CWE-1385 for a missing WebSocket origin check. Handshake identity uses the same expectation as WC-AUTHN (CWE-287). Message actions still need WC-AUTHZ-OBJECT and WC-AUTHZ-FUNCTION where those decisions apply.
- **Variants:** origin; handshake authentication; per-message authorization
- **Trust boundary:** The handshake (origin and credentials) and each later message.
- **Sensitive operation:** Accepting the socket, and performing the read or write a message requests.
- **Defensive control:** Check origin when the socket relies on ambient browser credentials. Authenticate before accepting application traffic. Authorize every message that reads or changes state.
- **Evidence:** The handshake handler, the origin and credential checks, and a message path through its authorization decision.
- **Applicability:** Applies when the approved scope has a WebSocket endpoint. A non-browser client that does not use ambient cookies can record origin as `not_applicable` with that reason. Tracing only the HTTP routes does not cover per-message authorization.

### WC-SECURITY-CONFIG

- **Name:** Security-relevant configuration
- **Description:** The configuration under review must keep the protective controls and security audit logging that the sensitive operations rely on.
- **CWE:** CWE-778 where security audit logging is disabled or insufficient. Other weakened controls are in this class without an additional CWE.
- **Variants:** protective controls; audit logging
- **Trust boundary:** Config files, environment defaults, feature flags, and profile overrides that select the running settings.
- **Sensitive operation:** The branch that skips authentication, authorization, transport checks, or an audit record because of that setting.
- **Defensive control:** The reviewed profile keeps those controls and the security-relevant audit log enabled. Record which profile was inspected.
- **Evidence:** The setting, the branch it changes, and whether that setting is the one in the reviewed configuration.
- **Applicability:** Inspect the configuration the review was given. A sample file is evidence only for that sample. An optional hardening toggle is a finding only when the reviewed profile turns off a control a sensitive operation requires. Unknown deployment settings stay unknown: record `not_reviewed`, and do not treat them as either a vulnerability or proof of safety.

## Cross-cutting review notes

These notes are not extra classes and they do not add coverage rows.
Apply them while reviewing the classes they affect. If an applicable note
was not followed, the affected class is `not_reviewed`.

### Batch endpoints and alternate content types

When two handlers perform the same sensitive operation, including batch
routes and alternate body types, require the same authentication,
authorization, and input controls on each. A control on one handler does
not cover the other.

### GraphQL

Review resolver authorization, which fields are returned, and query
cost or depth limits when GraphQL is in scope. Introspection by itself
is not a vulnerability. Record field exposure on WC-AUTHZ-PROPERTY and
resource limits on WC-RESOURCE-LIMITS.

### Second-order flows

Follow untrusted values that are stored in a database, cache, queue, or
file and later used by a sensitive operation. Review the class at the
later use, not only at the first write.

### Validation and use mismatches

The value, identity, scope, or tenant that was checked must be the value
used at the sensitive operation. A check on a different field, copy, or
request does not satisfy the control.

### Undocumented routes and exposed functionality

An undocumented or newly discovered route is a review lead. It becomes
a finding only after the same entry-point, flow, operation, and control
evidence required above. Discovery alone is not proof of a weakness.
