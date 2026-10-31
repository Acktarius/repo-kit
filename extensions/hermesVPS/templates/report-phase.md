# Phase {{NNN}} — {{phase-name}} (Hermes report)

- **Artifact ID:** `phase-{{NNN}}-hermes-v{{N}}`
- **UTC creation time:**
- **Run ID:**
- **Completion state:** `complete` | `blocked` | `incomplete`

## 1. Identity and scope

- **Repository identity:** (credentials redacted)
- **Approved source path:**
- **Full source commit SHA:**
- **Working-tree state:** clean / dirty (v1 requires clean; if dirty → blocked)
- **Branch / detached HEAD:**
- **Policy prefix:**
- **Toolkit revision:**
- **Rules consulted:** (absolute or policy-relative paths)
- **Exact prerequisite artifacts used:** (ids; none for 010)

## 2. Requested work

- **Phase explicitly requested by human:**
- **Actions actually performed:**
- **Actions not performed (and why):**

## 3. Evidence

- Paths and symbols examined (with line numbers where relevant)
- Commands run (read-only); bound/truncated output noted
- Exclusions and coverage gaps

## 4. Phase results

Use the phase-specific sections required by the phase rule (once implemented).
For inventory (010), expected sections include:

1. Repository identity  
2. Scope and exclusions  
3. Structure and technology evidence  
4. Dependency inventory  
5. CI, deployment, and existing security-record paths  
6. Unknowns and inspection errors  
7. Completion state  

Do not invent findings, CVEs, or severity in phases that produce inventory or
plans only.

When proposing finding-shaped objects (later phases), match
`security-assets/findings.schema.json` and keep proposals out of the
canonical target store until separately authorized. Distinguish:

- unvalidated candidates  
- independently reviewed finding proposals  
- accepted risks  
- remediation proposals  
- retest results  

## 5. Limitations

- Tooling missing or unavailable
- Network/advisory verification not approved
- Procedural (not OS-enforced) write/read boundaries
- Any schema validation that did **not** run

## 6. Outputs

- **This report path:** `reports/phase-{{NNN}}-hermes-v{{N}}.md`
- Other files written under the run root (none expected beyond this report for
  read-only phases)

## 7. After this report

1. Call `hermes-vps-artifacts register` with this report path (see runner
   prompt for the exact command). The helper will assign the final versioned
   filename, compute SHA-256, update the artifact index, and print the
   consultation prompt.
2. If registration fails (saved-but-unregistered): follow the retry command
   from the helper. Do not re-run this phase.
3. After registration: **stop**. Do not start the next phase automatically.

The consultation prompt from the helper includes instructions for optional
second-opinion handoff. Normal progression to the next phase requires only a
separate explicit human request — not a separate acceptance file.
