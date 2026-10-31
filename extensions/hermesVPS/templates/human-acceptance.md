# Human acceptance record (hermesVPS)

This record is authored by a **human**. It is an audit trail, not a
cryptographic or OS security boundary. A model must not fill the acceptance
attestation as if it were the operator.

Completion of a Hermes report ≠ Roomote validation ≠ human acceptance.
Roomote review is **optional** in the initial manual workflow; if skipped,
say so below. Missing Roomote must not block human review of the Hermes report.
Advancing to a dependent next phase (including 010 → 020) still requires
human acceptance of exact artifact versions **and** a **separate explicit**
human request to run that phase.

Suggested path:

```text
<run-root>/approvals/phase-NNN-human-vN.md
```

Never overwrite; bump `vN` for a revised acceptance decision.

---

## Acceptance

- **Run ID:**
- **Phase:**
- **Source identity:**
- **Full source commit SHA accepted for this phase:**
- **UTC timestamp:**
- **Human name / handle:**

### Exact artifacts accepted

List each artifact by **id** and path. Do not use “latest”.

| Artifact ID | Kind | Path |
|-------------|------|------|
| phase-NNN-hermes-vN | hermes_phase_report | reports/… |
| phase-NNN-roomote-vN or `skipped` | roomote_review | reviews/… or n/a |

### Decision

- [ ] Accept Hermes report as sufficient for this phase gate
- [ ] Accept with documented caveats (below)
- [ ] Reject — rework required (name blocking issues)

### Caveats / blocking issues

```text
<!-- human text -->
```

### Authorization explicitly **not** granted by this acceptance

Unless listed in a separate written approval, this acceptance does **not**
authorize:

- source modifications or PRs
- scanner/network/install actions
- updating findings stores or accepted-risk files
- starting the next Hermes phase (request that separately)

### Next phase request (optional pointer only)

If the human intends to request another phase later, record intent here without
treating this as the request itself:

- **Next phase contemplated:** `<!-- e.g. 020 -->`
- **Exact prerequisites that will be named:** `<!-- artifact ids -->`
- **Actual request will be issued:** separately in the Hermes session
