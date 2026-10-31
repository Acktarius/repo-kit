# Second-opinion handoff — manual transport (hermesVPS)

Use the consultation prompt printed by `hermes-vps-artifacts register` as the
basis for this handoff. Fill every section. Paste or attach the Hermes report
body — a local path alone is **not** sufficient unless the second agent has
separately verified filesystem access to that path.

This handoff requests **validation only**. It does not authorize source edits,
dependency changes, scanner execution, commits, pushes, or pull requests.

Structural and hash checks by the artifact helper do not prove factual
correctness of report content.

---

## 1. Artifact identity (from consultation prompt)

- **Artifact ID:** `<!-- e.g. phase-010-hermes-v1 -->`
- **Source commit SHA (full 40-char):** `<!-- from consultation prompt -->`
- **Report SHA-256:** `<!-- from consultation prompt -->`
- **Report path (local):** `<!-- absolute path; informational only if second agent cannot access -->`
- **Artifact index path (local):** `<!-- manifest.json path; informational only -->`
- **Working tree at report time:** clean (required for v1)

## 2. Run and phase

- **Run ID:** `<!-- matches run.json -->`
- **Phase:** `<!-- e.g. 010 inventory -->`
- **Toolkit revision (installed policy):** `<!-- toolkit_revision from consultation prompt -->`

## 3. Artifact delivery (choose one that the second agent can access)

- [ ] Full report pasted below in §6
- [ ] Private repository URL + path + commit (operator-confirmed readable by second agent): `<!-- URL -->`
- [ ] Other operator-mediated channel: `<!-- describe -->`

Do **not** rely on: shared `/opt/data` mount, MCP bridge, or `gh` from Hermes
unless those are separately verified for this session.

## 4. Requested validation scope

The second agent should independently validate against the **same** full
source commit:

- Confirm cited paths/symbols exist at that revision (via GitHub or approved access).
- Check evidence quality and whether claims are supported.
- Flag invented paths, overstated impact, or missing limitations.
- For finding-shaped content (later phases), check compatibility with
  `findings.schema.json` field names and enums (`SG-*`, status, severity).
- Keep reviewer commentary **separate** from the original Hermes report.
- Do not merge reviewer text into the Hermes report file.

Out of scope for this handoff unless the human adds an explicit separate
authorization:

- modifying source or policy
- updating `security/findings-reviewed.json` or `accepted-risks.md`
- creating PRs or pushing branches
- installing dependencies or running scanners/tests

## 5. Outcomes

After review, the operator (or agent) calls one of:

```text
# Record ACCEPT (does not change selection; not required for normal progression)
hermes-vps-artifacts accept \
  --run-json /abs/run.json \
  --artifact-id phase-010-hermes-v1 \
  --reviewer-identity "declared-name-or-id"

# Import corrected report (REVISE — updates selection, preserves original)
hermes-vps-artifacts revise \
  --run-json /abs/run.json \
  --source-report /abs/path/to/revised.md \
  --supersedes phase-010-hermes-v1 \
  --reviewer-identity "declared-name-or-id"
```

Reviewer identity is recorded as declared and unauthenticated.
Model-generated ACCEPT is not human acceptance.

## 6. Explicit prohibitions

The second agent must **not**, for this handoff:

1. Change application source, configuration, lockfiles, or CI.
2. Create, update, or merge a pull request.
3. Treat this message as approval to remediate.
4. Auto-advance Hermes to the next phase.

## 7. Hermes report content

```markdown
<!-- Paste the full contents of phase-NNN-hermes-vN.md here -->
```

## 8. Operator notes

- **Prepared by (human):**
- **UTC timestamp:**
- **Notes:**
