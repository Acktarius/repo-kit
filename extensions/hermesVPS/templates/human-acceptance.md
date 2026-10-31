# Human acceptance record (hermesVPS) — optional audit artifact

This file is an **optional** written record of human review. It is not
required for normal phase progression. The artifact index (`manifest.json`)
is updated automatically by `hermes-vps-artifacts`; this document is
supplementary documentation for audit purposes only.

A model must not fill this acceptance attestation as if it were the operator.
Completion of a Hermes report ≠ second-opinion review ≠ human acceptance.

Second-opinion review (Roomote or other) is optional. If skipped, say so.
Missing second-opinion must not block human review of the Hermes report.

Normal progression to the next phase requires only:
- the current phase report registered in the artifact index; and
- a separate explicit human request for the next phase.

---

## Run identity

- **Run ID:** `<!-- matches run.json -->`
- **Source identity:** `<!-- github.example/org/example-repo -->`
- **Full source commit SHA:** `<!-- 40-char hex -->`
- **Working tree at time of accepted reports:** clean

## Exact artifacts reviewed

List each artifact by **id** and path. Do not use "latest".

| Artifact ID | Path | SHA-256 |
|-------------|------|---------|
| `phase-010-hermes-v1` | `reports/phase-010-hermes-v1.md` | `<!-- hex -->` |

## Second-opinion review

- **Conducted:** yes / no / skipped
- **Reviewer identity (declared):** `<!-- if conducted -->`
- **Outcome:** ACCEPT / REVISE / (skipped)
- **Review artifact ID (if conducted):** `<!-- e.g. phase-010-hermes-v2 -->`

## Human reviewer attestation

- **Reviewed by (human operator):**
- **UTC timestamp:**
- **Notes:**

---

### Authorization explicitly **not** granted by this record

Unless listed in a separate written approval, this record does **not**
authorize:

- source code changes, commits, or pull requests;
- dependency updates or lockfile modifications;
- scanner, build, or test execution;
- advancing to the next phase without a separate explicit request.
