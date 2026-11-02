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
- The helper refreshes only records it wrote and nobody has edited since. Any
  edit to such a record, including `lastReviewed` or `source`, makes it
  human-owned. It
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
  when the inventory has gaps (unparsed or partially resolved files, vendored
  code, image contents without an SBOM), or when items remain queued.
- A component that disappears is recorded as `component_not_present` only when
  its source file was parsed completely without it. A failed, partial, or
  deleted source leaves the item queued instead.
- Fix versions are proposed only from the affected range that contains the
  installed version. If sources disagree, the mitigation stays unknown.

## Runs

Only one run is active at a time. A run's worklist is fixed at `start`, and
`decide` accepts only those candidates. `decide` and `finish` re-check the
source fingerprint (all tracked and untracked non-ignored files, excluding
`.repo-kit/` and the security review records) and the inventory; any change
interrupts the run, and no findings are synced. To give up on an unfinished
run, use `abandon --run <id>`.

## Reruns and reuse

A decision is reused only when all of these are unchanged: the advisory
revision, KEV status, component version and tier, runtime/image/SBOM/deployment
configuration, and every cited evidence file. Decisions that depend on code
(`affected`, and `not_affected` with a code-based justification) also require
an unchanged repository source fingerprint. A decision must also be at most 30
days old. Any change re-queues the item immediately and moves the old decision
to history: it is shown as invalidated in the handoff and is never used for
findings. `under_investigation` is never reused.

Each run assesses at most 25 queued items. The rest stay queued and are picked
up by the next run, with KEV items, least-attempted items, and in-window items
first. Collection checkpoints advance independently of assessment progress,
and only after a complete live collection.

## Recovery

- If `start` crashes before issuing its worklist, the next `/contre-attaque`
  marks it `interrupted`. An unfinished run with a worklist blocks new runs
  until it is finished, abandoned, or 24 hours old. Queues and completed
  collection checkpoints always survive.
- A lock timeout means another run is writing. Retry after it finishes.
- If `state.json` is corrupt, the helper refuses to continue. Restore it or move
  it aside; the next run then rebuilds a baseline, and existing canonical
  findings are deduplicated rather than duplicated.

Out of scope: scheduled monitoring, Hermes orchestration, live deployment
access, and automatic remediation.
