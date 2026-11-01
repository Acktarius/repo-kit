<!-- hermes-vps-report: REPLACE THIS LINE WITH THE REPORT IDENTITY HEADER PRINTED BY hermes-vps-review -->
# Phase 010 — inventory (Hermes report)

- **Artifact ID:** `phase-010-hermes-v{{N}}`
- **UTC creation time:**
- **Run ID:**
- **Completion state:** `complete` | `blocked` | `incomplete`

## 1. Identity and scope

- **Repository identity:** (credentials redacted)
- **Approved source path:**
- **Full source commit SHA:**
- **Working-tree state:** clean / dirty
- **Branch / detached HEAD:**
- **Policy prefix:**
- **Toolkit revision (if known):**
- **Rules consulted:**
  - `rules/rules_000-safety-and-scope.md`
  - `rules/rules_005-report-output.md`
  - `rules/rules_010-inventory.md`
- **Exact prerequisite artifacts used:** none (phase 010)

## 2. Requested work

- **Phase explicitly requested by human:** 010 inventory
- **Actions actually performed:**
- **Actions not performed (and why):**

## 3. Evidence

- Paths examined (with line numbers where relevant)
- Read-only commands run; bound/truncated output noted
- Symlinks encountered and whether followed
- Exclusions and coverage gaps

## 4. Phase results

### 4.1 Repository identity

### 4.2 Scope and exclusions

### 4.3 Structure and technology evidence

### 4.4 Dependency inventory

| Component | Manifest or asset path | Declared range | Resolved or observed version | Evidence | Uncertainty |
|-----------|------------------------|----------------|------------------------------|----------|-------------|
| | | | | | |

### 4.5 CI, deployment, and existing security-record paths

### 4.6 Unknowns and inspection errors

### 4.7 Completion state

## 5. Limitations

- Procedural (not OS-enforced) write/read boundaries unless verified otherwise
- No scanners, builds, tests, network, or dependency installation in this phase
- Schema `security-assets/findings.schema.json` is present for later phases;
  this inventory does **not** generate findings

## 6. Outputs

- **This report path:** `reports/phase-010-hermes-v{{N}}.md`
- **Manifest:** operator must append this artifact to `manifest.json` separately
- Other agent-written files under the run root: none expected

## 7. Next human approval required

1. Review this report.  
2. Optionally prepare a Roomote handoff (`templates/roomote-handoff.md`).  
   If Roomote review is skipped, record that in acceptance.  
3. Record human acceptance of **exact** artifact versions
   (`templates/human-acceptance.md`).  
4. Only after acceptance, issue a **separate** explicit request for phase 020
   (not implemented in Stage 3 payload beyond this gate documentation).  

Do not advance automatically.
