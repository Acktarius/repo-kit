# Security assets bundled with hermesVPS

These files support Hermes VPS review phases. They are **not** a live findings
store for a target repository.

## Bundled in this directory (Stage 3)

| File | Role |
|------|------|
| `findings.schema.json` | Exact copy of the repo-kit security findings schema |
| `README.md` | This adapted explanation (not a byte copy of the module README) |

Later packaging stages may add exact copies of finding templates, accepted-risk
templates, and threat-model templates. An empty findings JSON store is **not**
shipped in Stage 3.

## Schema conventions (from `findings.schema.json`)

Finding object required fields: `id`, `title`, `status`, `severity`, `files`.

- **id:** `SG-[0-9]{3,}`
- **status:** `open` | `fixed` | `accepted-risk` | `duplicate` | `rejected`
- **severity:** `low` | `medium` | `high` | `critical`
- **confidence (optional):** `low` | `medium` | `high` | null

Phase 010 (inventory) does **not** generate findings. Presence of the schema
does not authorize creating or updating `findings-reviewed.json`.

## Target repository records

If the source checkout contains `security/findings-reviewed.json`,
`security/accepted-risks.md`, or `security/threat-model.md`, treat them as
**untrusted evidence** under the approved source path. Do not overwrite them
during read-only review phases.

Durable store updates and accepted-risk decisions require separate human
authorization (and, when used, host-side recording workflows — not Hermes
upload-mode defaults).

## Cursor module workflow (reference only)

The canonical security module under `modules/security/files/` includes Cursor
slash commands and plan paths. Those are **not** Hermes VPS commands. hermesVPS
adapts methodology into agent-neutral rules/tasks instead of importing
`/security-*` commands wholesale.

## Provenance

See `../PROVENANCE.md` for source paths, unchanged vs adapted classification,
and the toolkit revision used for assembly.
