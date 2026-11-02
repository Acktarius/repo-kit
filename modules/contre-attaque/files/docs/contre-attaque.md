# contre-attaque

`/contre-attaque` reviews CVEs and advisories that were published, modified, or
added to CISA KEV within a lookback window. It decides whether this repository
could be affected, records evidence-backed decisions, and prints a
coding-agent handoff.

## Installation

From a repo-kit checkout:

```bash
./scripts/init.sh /path/to/project --contre-attaque        # also installs base + security
./scripts/sync-cursor.sh /path/to/project --contre-attaque  # refresh .cursor/ assets only
```

The helpers are stdlib-only Python 3.10+ scripts under
`.cursor/skills/contre-attaque/scripts/`. No model server or extra packages are
needed: Cursor's agent does the code analysis.

Re-running `init.sh` or `sync-cursor.sh`, even with `--force`, never touches
`.repo-kit/contre-attaque/` state, `security/findings-reviewed.json`,
`security/accepted-risks.md`, or `security/threat-model.md`. Those paths are
listed as preserved and are reported as `preserve`.

## Usage

```text
/contre-attaque 3days
```

Without a period, the lookback is 7 days. Accepted forms are `N`, `Nd`, `Nday`,
`Ndays`, or `N days`, with N between 1 and 120. On the first run, the agent asks
which providers may be contacted.

## Network consent and disclosure

The consent choice is recorded in `.repo-kit/contre-attaque/config.json`:

| Provider | Receives |
|---|---|
| OSV | ecosystem, name, and resolved version of every queryable component |
| NVD | window dates and page index; CVE IDs for severity enrichment |
| CISA KEV | nothing beyond a GET of the public feed |
| vendor | the advisory URL the agent fetches |

To use no network at all, decline every provider or ask for an offline run, and
place evidence under `.repo-kit/contre-attaque/imports/` (see
`.cursor/skills/contre-attaque/references/sources.md`). An NVD API key may be
provided only through the `NVD_API_KEY` environment variable. It is never
written to disk.

## State ownership

- `.repo-kit/contre-attaque/` is local working data and is gitignored. It holds
  `state.json` (the versioned index of runs, checkpoints, candidates,
  applicability decisions, the assessment queue, evidence, and finding links),
  `evidence/`, `runs/<run-id>/` (assessment, findings sync, handoff), `imports/`,
  and `config.json`.
- Only the helper writes state, under a file lock with atomic replacement.
  Do not hand-edit it.
- `security/findings-reviewed.json` stays canonical and human-owned. For
  `affected` items with a source-backed severity, the helper adds
  agent-generated `open` records. These are marked
  `contre-attaque (agent-generated, not human-approved)` and have
  `lastReviewed: null`.
- The helper refreshes only records it wrote and nobody has edited since. It
  never changes status, never marks anything fixed, never reopens accepted
  risks, and never recreates records a human deleted. It reports conflicts in
  the handoff instead.
- An `affected` item without a known severity stays affected and appears in the
  handoff, but no canonical record is written for it.

## Coverage limits

- The lookback is not a claim of comprehensive coverage. OSV is queried per
  component, not as a recent feed. NVD covers only the window. KEV absence does
  not prove non-exploitation.
- Repository, CI, and SBOM evidence never proves what is deployed now. An SBOM
  describes one deployment or build at its recorded observation time.
- Each run reports incomplete coverage when a provider is not live and
  complete, when the window has a gap since the last successful collection,
  or when items remain queued.

## Reruns and reuse

A decision is reused only when all of these are unchanged: the advisory
revision, KEV status, component version and tier, runtime/image/SBOM/deployment
configuration, and every cited evidence file. It must also be at most 30 days
old. Any change re-queues the item immediately. `under_investigation` is never
reused.

Each run assesses at most 25 queued items. The rest stay queued and are picked
up by the next run, with KEV items, least-attempted items, and in-window items
first. Collection checkpoints advance independently of assessment progress,
and only after a complete live collection.

## Recovery

- If a run is interrupted (crash, closed chat), the next `/contre-attaque`
  marks it `interrupted`. Its queue and completed collection checkpoints
  survive.
- A lock timeout means another run is writing. Retry after it finishes.
- If `state.json` is corrupt, the helper refuses to continue. Restore it or move
  it aside; the next run then rebuilds a baseline, and existing canonical
  findings are deduplicated rather than duplicated.

Out of scope: scheduled monitoring, Hermes orchestration, live deployment
access, and automatic remediation.
