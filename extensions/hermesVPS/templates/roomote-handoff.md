# Roomote handoff — manual transport (hermesVPS)

Fill every section. Paste or attach the Hermes report body (or a reference
Roomote can actually open). An `/opt/data/...` path alone is **not** sufficient
unless Roomote filesystem access has been separately verified.

This handoff requests **validation only**. It does not authorize source edits,
dependency changes, scanner execution, commits, pushes, or pull requests.

---

## 1. Repository identity

- **Identity:** `<!-- e.g. github.example/org/example-repo -->`
- **Approved source path (Hermes side only):** `<!-- absolute path; informational -->`
- **Full source commit SHA:** `<!-- 40-char hex -->`
- **Working tree at Hermes report time:** clean / dirty (must be clean for v1)

## 2. Run and phase

- **Run ID:** `<!-- matches run.json -->`
- **Phase:** `<!-- e.g. 010 inventory -->`
- **Hermes report artifact ID:** `<!-- e.g. phase-010-hermes-v1 -->`
- **Hermes report relative path:** `reports/phase-010-hermes-v1.md`
- **Toolkit revision (installed policy):** `<!-- repo-kit SHA recorded at install -->`

## 3. Artifact delivery (choose one that Roomote can access)

- [ ] Full report pasted below in §6
- [ ] Private reports repository URL + path + commit (operator-confirmed readable by Roomote): `<!-- URL -->`
- [ ] Other operator-mediated channel: `<!-- describe -->`

Do **not** rely on: shared `/opt/data` mount, MCP bridge, or `gh` from Hermes
unless those are separately verified for this session.

## 4. Requested validation scope

Roomote should independently validate against the **same** full source commit:

- Confirm cited paths/symbols exist at that revision (via GitHub or approved access).
- Check evidence quality and whether claims are supported.
- Flag invented paths, overstated impact, or missing limitations.
- For finding-shaped content (later phases), check compatibility with
  `findings.schema.json` field names and enums (`SG-*`, status, severity).
- Keep reviewer commentary **separate** from the original Hermes report.
- Do not merge Roomote text into the Hermes report file; write a new
  `phase-NNN-roomote-vN.md` (operator pastes or records it into the run tree).

Out of scope for this handoff unless the human adds an explicit separate
authorization:

- modifying source or policy
- updating `security/findings-reviewed.json` or `accepted-risks.md`
- creating PRs or pushing branches
- installing dependencies or running scanners/tests

## 5. Explicit prohibitions

Roomote (and any delegated agent) must **not**, for this handoff:

1. Change application source, configuration, lockfiles, or CI.
2. Create, update, or merge a pull request.
3. Treat this message as approval to remediate.
4. Treat a model “accepted” statement as human acceptance.
5. Auto-advance Hermes to the next phase.

## 6. Hermes report content

```markdown
<!-- Paste the full contents of phase-NNN-hermes-vN.md here -->
```

## 7. Operator signature

- **Prepared by (human):**
- **UTC timestamp:**
- **Notes:**
