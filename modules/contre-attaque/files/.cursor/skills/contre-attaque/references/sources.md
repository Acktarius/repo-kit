# contre-attaque intelligence sources

All endpoint URLs and limits live in `scripts/ca_intel.py` (`INTEL_SOURCES`,
`PROVIDER_CAPABILITIES`). This file explains their behavior; it does not repeat
the URLs.

## How the window is applied

| Provider | Capability | Window implementation |
|---|---|---|
| OSV | Per-package lookups (querybatch, query with page tokens, vulns by ID). **Not** a global recent-advisory feed. | Every queryable component (ecosystem + name + resolved version) is queried each run. Each advisory's `published`/`modified` is then compared with the window. Matches never assessed before are **baseline** items, regardless of age. |
| NVD CVE API 2.0 | Global feed filtered by `lastModStartDate`/`lastModEndDate` (max 120 days), paginated. | One range query equal to the window. New publications are included because publishing sets `lastModified`. Items are classified as `published` or `modified` and matched locally by CPE against runtime, image, and OS components. |
| CISA KEV | Full catalog. | `dateAdded` (day precision) inside the window's inclusive UTC dates marks `kev_added`. Every candidate CVE's KEV membership is re-checked regardless of date, so an old CVE that becomes exploited is reassessed. |
| Vendor / disclosures | Single HTTPS documents chosen by the agent. | Agent-selected. News is a discovery lead only. |

## Baseline behavior

- **First enrollment:** OSV returns every known advisory affecting the current
  component versions. These are queued as baseline items. NVD history before
  the window is not reviewed, and this is reported as a window gap.
- **Changed dependencies:** a new or changed component version is queried in
  full on OSV, so older advisories outside the window still surface.
- **Runtime/image/OS changes:** these are matched only against NVD items in the
  current window and against stored advisory evidence. Older NVD-only CVEs for
  a new runtime version need a longer period.

## Collection rules

- HTTPS on port 443 only. No embedded credentials. Destinations (including
  redirects, re-checked at connect time) must be globally routable. Proxies are
  not used.
- Timeouts, retries on 429/503 with backoff, NVD rate delays, page caps, and
  a 16 MiB response cap.
- Successful responses are stored as content-addressed evidence
  (`evidence/<sha256>.json`) with non-secret request metadata. URL secrets are
  redacted. The NVD API key is read only from `NVD_API_KEY` and is never stored
  or logged.
- Statuses are `success`, `no_match`, `partial`, `failed`, `not_authorized`, and
  `not_checked`. Failed or partial collection is never reported as no match.
  A checkpoint advances only after a complete live collection by that provider.

## Offline / imported evidence

Place files under `.repo-kit/contre-attaque/imports/`:

- `osv/*.json`: OSV vulnerability records (matched locally; non-numeric
  versions are undecided).
- `nvd/*.json`: NVD CVE API 2.0 response documents.
- `kev.json`: the CISA KEV JSON feed.
- `*.json` (top level): CycloneDX SBOMs. Each must set `metadata.timestamp`
  (observation time) and `metadata.component` name/version (the deployment or
  build it describes). Otherwise it is rejected.

Imported evidence never advances checkpoints, and runs that use it report
coverage as incomplete.
