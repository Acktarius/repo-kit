"""hermesVPS vulnerability intelligence collection library.

All external endpoint configuration is centralized in INTEL_SOURCES below.
Do not duplicate endpoint URLs in rules, tasks, or skills — reference
this module by name when endpoint documentation is needed.

Architecture
------------
- This library: fetching, evidence formatting, freshness evaluation.
- bin/hermes-vps-collect-intel: CLI shim (invokes main()).
- hermes-vps-artifacts: artifact registration and selection (reads payload output).
- hermes-vps-review: read-only validation (never calls this library).

Network isolation
-----------------
Pass --fixture-dir to use pre-recorded response files; no live HTTP calls
are made when fixture_dir is set.  Tests MUST use fixture mode.

Pass --mode not-authorized to produce a valid record without any network
access (documents that authorization was not granted).

Privacy note
------------
Package names and versions are transmitted to OSV and NVD APIs.
Use offline/import mode when dependency disclosure is not permitted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

# Prevent __pycache__ writes under the policy tree.
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

# ---------------------------------------------------------------------------
# Centralized endpoint configuration — SINGLE SOURCE OF TRUTH for all URLs.
# Do not copy these URLs into rules, tasks, skills, or templates.
# ---------------------------------------------------------------------------

INTEL_SOURCES: dict[str, Any] = {
    "osv": {
        "query":      "https://api.osv.dev/v1/query",
        "querybatch": "https://api.osv.dev/v1/querybatch",
        "vuln":       "https://api.osv.dev/v1/vulns/{id}",
        "docs":       "https://google.github.io/osv.dev/api/",
    },
    "nvd": {
        "cves":  "https://services.nvd.nist.gov/rest/json/cves/2.0",
        "docs":  "https://nvd.nist.gov/developers/vulnerabilities",
    },
    "cisa_kev": {
        "catalog":   "https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
        "json_feed": "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
    },
}

# ---------------------------------------------------------------------------
# Defaults and limits
# ---------------------------------------------------------------------------

DEFAULT_FRESHNESS_HOURS: float = 24.0
REQUEST_TIMEOUT_SECONDS: int = 30
MAX_BATCH_SIZE: int = 1000          # OSV querybatch max queries per request
NVD_RESULTS_PER_PAGE: int = 2000   # NVD max results per page
# NVD rate limits (documented): 5 req/30s without key, 50/30s with key
NVD_RATE_DELAY_NO_KEY: float = 6.1    # > 30/5
NVD_RATE_DELAY_WITH_KEY: float = 0.61 # > 30/50
MAX_RETRY_ATTEMPTS: int = 3
RETRY_BACKOFF_BASE: float = 2.0

# ---------------------------------------------------------------------------
# Collection status strings
# ---------------------------------------------------------------------------

class Status:
    SUCCESS        = "success"
    NO_MATCH       = "no_match"
    PARTIAL        = "partial"
    UNSUPPORTED    = "unsupported"
    FAILED         = "failed"
    NOT_AUTHORIZED = "not_authorized"
    NOT_CHECKED    = "not_checked"


class FreshnessSource:
    DEFAULT    = "default"
    CLI        = "cli"
    RUN_CONFIG = "run_config"


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_dt(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# URL validation — private network / loopback / link-local rejection
# ---------------------------------------------------------------------------

_PRIVATE_PREFIXES = ("127.", "10.", "192.168.", "169.254.")
_PRIVATE_172_RANGE = tuple(f"172.{i}." for i in range(16, 32))
_BLOCKED_HOSTS = {"localhost", "metadata.google.internal", "169.254.169.254"}


def validate_url(url: str) -> None:
    """Raise ValueError if the URL targets a disallowed destination.

    Rejects: non-HTTPS schemes, loopback, RFC-1918, link-local,
    cloud metadata IPs, and known blocked hostnames.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as exc:
        raise ValueError(f"URL parse error: {exc}") from exc
    if parsed.scheme != "https":
        raise ValueError(f"only HTTPS URLs allowed; got scheme {parsed.scheme!r}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("URL has no hostname")
    if host in _BLOCKED_HOSTS:
        raise ValueError(f"blocked hostname: {host!r}")
    for prefix in _PRIVATE_PREFIXES + _PRIVATE_172_RANGE:
        if host.startswith(prefix):
            raise ValueError(f"private/loopback/link-local target rejected: {host!r}")
    # Best-effort DNS resolution check (offline environments may skip)
    try:
        for _, _, _, _, sockaddr in socket.getaddrinfo(host, None):
            ip = sockaddr[0]
            for prefix in _PRIVATE_PREFIXES + _PRIVATE_172_RANGE:
                if ip.startswith(prefix):
                    raise ValueError(f"resolved IP is private: {ip!r} for host {host!r}")
            if ip.startswith("::1") or ip == "::":
                raise ValueError(f"resolved to IPv6 loopback: {ip!r}")
    except (socket.gaierror, OSError):
        pass  # Cannot resolve — skip; will fail at request time if private


# ---------------------------------------------------------------------------
# Fixture injection
# ---------------------------------------------------------------------------

def _load_fixture(fixture_dir: str | None, name: str) -> dict[str, Any] | None:
    """Return parsed JSON from fixture_dir/name, or None if not found."""
    if fixture_dir is None:
        return None
    p = os.path.join(fixture_dir, name)
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# HTTP helper (with 429 retry/backoff)
# ---------------------------------------------------------------------------

def _http_request(
    url: str,
    method: str = "GET",
    body: bytes | None = None,
    extra_headers: dict[str, str] | None = None,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
    max_retries: int = MAX_RETRY_ATTEMPTS,
) -> tuple[int, bytes]:
    """Return (http_status, response_bytes). Retries on 429 with exponential backoff.

    Raises ValueError via validate_url() before making any network request
    if the URL targets a disallowed destination.
    """
    # URL policy check before any network activity.
    validate_url(url)
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    attempt = 0
    while True:
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < max_retries:
                time.sleep(RETRY_BACKOFF_BASE ** (attempt + 1))
                attempt += 1
                continue
            return exc.code, (exc.read() or b"")
        except (urllib.error.URLError, OSError) as exc:
            return 0, str(exc).encode("utf-8")


# ---------------------------------------------------------------------------
# OSV collection
# ---------------------------------------------------------------------------

def _osv_querybatch(
    queries: list[dict[str, Any]],
    fixture_dir: str | None,
) -> tuple[dict[str, Any], bytes]:
    """POST /v1/querybatch. Returns (parsed_response, raw_bytes) or (_error key, b'')."""
    if fixture_dir is not None:
        data = _load_fixture(fixture_dir, "osv-querybatch.json")
        if data is None:
            return {"_error": "fixture osv-querybatch.json not found", "results": []}, b""
        return data, json.dumps(data, sort_keys=True).encode()

    body = json.dumps({"queries": queries}).encode()
    url = INTEL_SOURCES["osv"]["querybatch"]
    status, resp_bytes = _http_request(url, method="POST", body=body)
    if status != 200:
        err = resp_bytes.decode(errors="replace")[:200]
        return {"_error": f"HTTP {status}: {err}", "results": []}, b""
    try:
        return json.loads(resp_bytes), resp_bytes
    except json.JSONDecodeError as exc:
        return {"_error": f"JSON decode: {exc}", "results": []}, b""


def _osv_fetch_vuln(vuln_id: str, fixture_dir: str | None) -> dict[str, Any] | None:
    """GET /v1/vulns/{id}. Returns advisory dict or None on failure."""
    safe_id = vuln_id.replace("/", "_")
    fixture_name = f"osv-vuln-{safe_id}.json"
    if fixture_dir is not None:
        return _load_fixture(fixture_dir, fixture_name)

    url = INTEL_SOURCES["osv"]["vuln"].format(id=vuln_id)
    status, resp_bytes = _http_request(url)
    if status != 200:
        return None
    try:
        return json.loads(resp_bytes)
    except json.JSONDecodeError:
        return None


def _extract_osv_ranges(affected_entry: dict[str, Any]) -> list[dict[str, Any]]:
    ranges: list[dict[str, Any]] = []
    for r in affected_entry.get("ranges", []):
        rtype = r.get("type", "UNKNOWN")
        introduced: str | None = None
        fixed: str | None = None
        for evt in r.get("events", []):
            if "introduced" in evt:
                introduced = evt["introduced"]
            if "fixed" in evt:
                fixed = evt["fixed"]
        ranges.append({"type": rtype, "introduced": introduced, "fixed": fixed})
    return ranges


def _cvss_base_to_severity(score: float) -> str:
    if score >= 9.0:  return "critical"
    if score >= 7.0:  return "high"
    if score >= 4.0:  return "medium"
    return "low"


def _extract_match_from_advisory(
    adv: dict[str, Any],
    pkg_name: str,
    pkg_version: str,
    pkg_ecosystem: str,
) -> dict[str, Any]:
    """Build a normalized match entry from a full OSV advisory record."""
    adv_id = adv.get("id", "")
    raw_aliases = adv.get("aliases", [])
    all_ids = [adv_id] + [a for a in raw_aliases if a != adv_id]
    cve_aliases = [a for a in all_ids if a.startswith("CVE-")]

    ranges: list[dict[str, Any]] = []
    fixed_versions: list[str] = []
    for affected in adv.get("affected", []):
        affected_name = affected.get("package", {}).get("name", "")
        if affected_name.lower() == pkg_name.lower():
            ranges.extend(_extract_osv_ranges(affected))
            for r in affected.get("ranges", []):
                for evt in r.get("events", []):
                    if "fixed" in evt and evt["fixed"]:
                        fv = str(evt["fixed"])
                        if fv not in fixed_versions:
                            fixed_versions.append(fv)

    # Determine severity from OSV severity array
    severity = "unknown"
    for s_entry in adv.get("severity", []):
        score_str = s_entry.get("score", "")
        # Try to parse CVSS vector base score embedded as float
        try:
            severity = _cvss_base_to_severity(float(score_str))
            break
        except ValueError:
            pass

    return {
        "package": pkg_name,
        "version": pkg_version,
        "ecosystem": pkg_ecosystem,
        "advisory_ids": all_ids,
        "aliases": [a for a in all_ids if a != adv_id],
        "affected_ranges": ranges,
        "fixed_versions": fixed_versions,
        "kev_membership": False,   # updated in run_collection after KEV fetch
        "severity": severity,
        "published": adv.get("published"),
        "modified": adv.get("modified"),
        "summary": (adv.get("summary") or adv.get("details") or "")[:300],
        "candidate_id_suggestion": None,  # assigned later
    }


def collect_osv(
    packages: list[dict[str, Any]],
    fixture_dir: str | None = None,
) -> dict[str, Any]:
    """Query OSV querybatch for a list of packages. Returns provider evidence dict.

    Note: also returns '_matches_raw' (internal); stripped before persisting.
    """
    retrieved_at = _utcnow()
    endpoint = INTEL_SOURCES["osv"]["querybatch"]

    if not packages:
        return {
            "status": Status.NOT_CHECKED,
            "endpoint_used": endpoint,
            "retrieved_at_utc": retrieved_at,
            "response_sha256": None,
            "packages_queried": 0,
            "advisory_ids_returned": [],
            "note": "no packages provided",
            "_matches_raw": [],
        }

    # Build OSV query objects
    queries: list[dict[str, Any]] = []
    valid_pkgs: list[dict[str, Any]] = []
    for pkg in packages:
        name = pkg.get("name", "")
        eco  = pkg.get("ecosystem", "")
        ver  = pkg.get("version", "")
        commit = pkg.get("commit", "")
        if name and eco and ver:
            queries.append({"version": ver, "package": {"name": name, "ecosystem": eco}})
            valid_pkgs.append(pkg)
        elif commit:
            queries.append({"commit": commit})
            valid_pkgs.append(pkg)

    if not queries:
        return {
            "status": Status.NOT_CHECKED,
            "endpoint_used": endpoint,
            "retrieved_at_utc": retrieved_at,
            "response_sha256": None,
            "packages_queried": 0,
            "advisory_ids_returned": [],
            "note": "no queryable packages (missing name/ecosystem/version)",
            "_matches_raw": [],
        }

    advisory_ids: list[str] = []
    matches_raw: list[dict[str, Any]] = []
    raw_hash_acc = b""
    failed = False

    for batch_start in range(0, len(queries), MAX_BATCH_SIZE):
        batch_q = queries[batch_start: batch_start + MAX_BATCH_SIZE]
        batch_p = valid_pkgs[batch_start: batch_start + MAX_BATCH_SIZE]
        resp_data, resp_bytes = _osv_querybatch(batch_q, fixture_dir)
        if "_error" in resp_data:
            failed = True
            break
        raw_hash_acc += resp_bytes
        for j, result in enumerate(resp_data.get("results", [])):
            pkg = batch_p[j] if j < len(batch_p) else {}
            for vuln_stub in result.get("vulns", []):
                vid = vuln_stub.get("id", "")
                if vid and vid not in advisory_ids:
                    advisory_ids.append(vid)
                    matches_raw.append({
                        "advisory_id": vid,
                        "package": pkg.get("name", "unknown"),
                        "version": pkg.get("version", "unknown"),
                        "ecosystem": pkg.get("ecosystem", "unknown"),
                    })

    response_sha = _sha256_bytes(raw_hash_acc) if raw_hash_acc else None

    if failed:
        return {
            "status": Status.FAILED,
            "endpoint_used": endpoint,
            "retrieved_at_utc": retrieved_at,
            "response_sha256": None,
            "packages_queried": len(queries),
            "advisory_ids_returned": [],
            "note": "querybatch request failed",
            "_matches_raw": [],
        }

    return {
        "status": Status.SUCCESS if advisory_ids else Status.NO_MATCH,
        "endpoint_used": endpoint,
        "retrieved_at_utc": retrieved_at,
        "response_sha256": response_sha,
        "packages_queried": len(queries),
        "advisory_ids_returned": advisory_ids,
        "note": None,
        "_matches_raw": matches_raw,   # internal; stripped before persisting
    }


def fetch_osv_advisories(
    advisory_ids: list[str],
    fixture_dir: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch full advisory records for each ID from OSV /v1/vulns/{id}."""
    results = []
    for vid in advisory_ids:
        rec = _osv_fetch_vuln(vid, fixture_dir)
        if rec is None:
            results.append({"id": vid, "_fetch_failed": True})
        else:
            results.append(rec)
    return results


# ---------------------------------------------------------------------------
# NVD enrichment
# ---------------------------------------------------------------------------

def collect_nvd(
    cve_ids: list[str],
    api_key: str | None = None,
    fixture_dir: str | None = None,
) -> dict[str, Any]:
    """Enrich CVE IDs via NVD CVE API 2.0. Returns provider evidence dict."""
    retrieved_at = _utcnow()
    endpoint = INTEL_SOURCES["nvd"]["cves"]
    api_key_used = bool(api_key)
    rate_delay = NVD_RATE_DELAY_WITH_KEY if api_key else NVD_RATE_DELAY_NO_KEY
    extra_headers: dict[str, str] = {}
    if api_key:
        extra_headers["apiKey"] = api_key  # key never logged or stored in output

    if not cve_ids:
        return {
            "status": Status.NOT_CHECKED,
            "endpoint_used": endpoint,
            "retrieved_at_utc": retrieved_at,
            "response_sha256": None,
            "cves_enriched": [],
            "cves_failed": [],
            "api_key_used": api_key_used,
            "note": "no CVE IDs to enrich",
        }

    enriched: list[dict[str, Any]] = []
    failed_ids: list[str] = []
    raw_hash = hashlib.sha256()

    for i, cve_id in enumerate(cve_ids):
        if i > 0 and fixture_dir is None:
            time.sleep(rate_delay)

        fixture_name = f"nvd-cve-{cve_id.replace('/', '_')}.json"
        if fixture_dir is not None:
            data = _load_fixture(fixture_dir, fixture_name)
            if data is None:
                failed_ids.append(cve_id)
                continue
        else:
            url = f"{endpoint}?cveId={urllib.parse.quote(cve_id)}"
            status, resp_bytes = _http_request(url, extra_headers=extra_headers)
            if status != 200:
                failed_ids.append(cve_id)
                continue
            try:
                data = json.loads(resp_bytes)
                raw_hash.update(resp_bytes)
            except json.JSONDecodeError:
                failed_ids.append(cve_id)
                continue

        for v_entry in (data or {}).get("vulnerabilities", []):
            cve = v_entry.get("cve", {})
            entry: dict[str, Any] = {
                "cve_id": cve.get("id", cve_id),
                "descriptions": [
                    d.get("value", "")
                    for d in cve.get("descriptions", [])
                    if d.get("lang") == "en"
                ],
                "base_score_v31": None,
                "base_severity_v31": None,
                "published": cve.get("published"),
                "last_modified": cve.get("lastModified"),
            }
            for metric in cve.get("metrics", {}).get("cvssMetricV31", []):
                entry["base_score_v31"] = metric.get("cvssData", {}).get("baseScore")
                entry["base_severity_v31"] = metric.get("cvssData", {}).get("baseSeverity")
                break
            enriched.append(entry)

    # Status logic
    if enriched and not failed_ids:
        status_val = Status.SUCCESS
    elif enriched and failed_ids:
        status_val = Status.PARTIAL
    elif failed_ids and not enriched:
        status_val = Status.FAILED
    else:
        status_val = Status.NOT_CHECKED

    digest = raw_hash.hexdigest()
    null_digest = hashlib.sha256(b"").hexdigest()

    return {
        "status": status_val,
        "endpoint_used": endpoint,
        "retrieved_at_utc": retrieved_at,
        "response_sha256": None if digest == null_digest else digest,
        "cves_enriched": enriched,
        "cves_failed": failed_ids,
        "api_key_used": api_key_used,
        "note": None,
    }


# ---------------------------------------------------------------------------
# CISA KEV
# ---------------------------------------------------------------------------

def collect_cisa_kev(
    cve_ids: list[str],
    fixture_dir: str | None = None,
) -> dict[str, Any]:
    """Fetch CISA KEV JSON feed once; match locally by CVE ID."""
    retrieved_at = _utcnow()
    endpoint = INTEL_SOURCES["cisa_kev"]["json_feed"]

    if fixture_dir is not None:
        data = _load_fixture(fixture_dir, "kev-feed.json")
        if data is None:
            return {
                "status": Status.FAILED,
                "endpoint_used": endpoint,
                "retrieved_at_utc": retrieved_at,
                "response_sha256": None,
                "catalog_version": None,
                "kev_count": 0,
                "matched_cves": [],
                "note": "fixture kev-feed.json not found",
            }
        resp_bytes = json.dumps(data, sort_keys=True).encode()
    else:
        status, resp_bytes = _http_request(endpoint)
        if status != 200:
            return {
                "status": Status.FAILED,
                "endpoint_used": endpoint,
                "retrieved_at_utc": retrieved_at,
                "response_sha256": None,
                "catalog_version": None,
                "kev_count": 0,
                "matched_cves": [],
                "note": f"HTTP {status}",
            }
        try:
            data = json.loads(resp_bytes)
        except json.JSONDecodeError as exc:
            return {
                "status": Status.FAILED,
                "endpoint_used": endpoint,
                "retrieved_at_utc": retrieved_at,
                "response_sha256": None,
                "catalog_version": None,
                "kev_count": 0,
                "matched_cves": [],
                "note": f"JSON decode: {exc}",
            }

    response_sha = _sha256_bytes(resp_bytes)
    all_vulns = data.get("vulnerabilities", [])
    kev_id_set = {v.get("cveID") for v in all_vulns if v.get("cveID")}
    matched_entries = [v for v in all_vulns if v.get("cveID") in set(cve_ids)]

    return {
        "status": Status.SUCCESS,
        "endpoint_used": endpoint,
        "retrieved_at_utc": retrieved_at,
        "response_sha256": response_sha,
        "catalog_version": data.get("catalogVersion"),
        "kev_count": data.get("count", len(kev_id_set)),
        "matched_cves": [
            {
                "cve_id": e.get("cveID"),
                "vendor_project": e.get("vendorProject"),
                "product": e.get("product"),
                "vulnerability_name": e.get("vulnerabilityName"),
                "date_added": e.get("dateAdded"),
                "known_ransomware": e.get("knownRansomwareCampaignUse"),
                "due_date": e.get("dueDate"),
            }
            for e in matched_entries
        ],
        "note": "Absence from KEV does not establish that exploitation is impossible.",
    }


# ---------------------------------------------------------------------------
# Alias deduplication
# ---------------------------------------------------------------------------

def _deduplicate_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge match entries that share an advisory ID without losing source refs."""
    primary_to_idx: dict[str, int] = {}
    deduped: list[dict[str, Any]] = []
    for m in matches:
        ids = m.get("advisory_ids", [])
        primary = ids[0] if ids else None
        if primary is None:
            deduped.append(m)
            continue
        # Check all IDs of the new entry against known primaries
        merged = False
        for aid in ids:
            if aid in primary_to_idx:
                existing = deduped[primary_to_idx[aid]]
                for new_id in ids:
                    if new_id not in existing["advisory_ids"]:
                        existing["advisory_ids"].append(new_id)
                for new_alias in m.get("aliases", []):
                    if new_alias not in existing["aliases"]:
                        existing["aliases"].append(new_alias)
                merged = True
                break
        if not merged:
            primary_to_idx[primary] = len(deduped)
            for aid in ids:
                primary_to_idx[aid] = len(deduped)
            deduped.append(dict(m))
    return deduped


def _assign_candidate_id_suggestions(matches: list[dict[str, Any]]) -> None:
    for i, m in enumerate(matches, start=1):
        m["candidate_id_suggestion"] = f"C-OSV-{i:03d}"


# ---------------------------------------------------------------------------
# Freshness assessment (per-provider)
# ---------------------------------------------------------------------------

def assess_freshness(
    record: dict[str, Any],
    threshold_hours: float,
    threshold_source: str = FreshnessSource.DEFAULT,
    at_utc: str | None = None,
) -> dict[str, Any]:
    """Evaluate per-provider freshness.

    Freshness is evaluated against providers[*].retrieved_at_utc.
    Importing an old snapshot does not refresh its age.
    Missing or invalid timestamps → reported as unknown, not fresh.
    Freshness and coverage are separate dimensions.
    """
    now_str = at_utc or _utcnow()
    now_dt = _parse_dt(now_str) or datetime.now(timezone.utc)

    providers = record.get("providers", {})
    stale_providers: list[str] = []
    unknown_providers: list[str] = []
    limitations: list[str] = []
    ages: dict[str, float] = {}

    for pname, pdata in providers.items():
        if not isinstance(pdata, dict):
            continue
        pstatus = pdata.get("status", Status.NOT_CHECKED)
        if pstatus in (Status.NOT_AUTHORIZED, Status.NOT_CHECKED, Status.UNSUPPORTED):
            unknown_providers.append(pname)
            limitations.append(f"{pname}: not checked ({pstatus})")
            continue
        if pstatus == Status.FAILED:
            unknown_providers.append(pname)
            limitations.append(f"{pname}: collection failed — no valid timestamp")
            continue
        ts = pdata.get("retrieved_at_utc")
        ts_dt = _parse_dt(ts)
        if ts_dt is None:
            unknown_providers.append(pname)
            limitations.append(f"{pname}: missing or unparseable retrieved_at_utc — reported as unknown, not fresh")
            continue
        age_h = (now_dt - ts_dt).total_seconds() / 3600.0
        ages[pname] = age_h
        if age_h > threshold_hours:
            stale_providers.append(pname)
            limitations.append(
                f"{pname}: {age_h:.1f}h old (threshold {threshold_hours:.0f}h)"
            )

    checked_ages = list(ages.values())
    oldest = max(checked_ages) if checked_ages else None
    freshness_ok = bool(checked_ages and not stale_providers and not unknown_providers)

    return {
        "ok": freshness_ok,
        "evaluated_at_utc": now_str,
        "effective_threshold_hours": threshold_hours,
        "threshold_source": threshold_source,
        "oldest_provider_age_hours": round(oldest, 2) if oldest is not None else None,
        "stale_providers": stale_providers,
        "unknown_providers": unknown_providers,
        "limitations": limitations,
        "note": (
            "Freshness is per-provider retrieved_at_utc. "
            "Import/registration time does not refresh evidence age. "
            "Freshness and coverage are independent."
        ),
    }


# ---------------------------------------------------------------------------
# Evidence import (offline mode)
# ---------------------------------------------------------------------------

def import_evidence(path: str) -> dict[str, Any]:
    """Load a prior vuln-intel-record.json for offline/import mode.

    Re-stamps imported_at_utc; does NOT update provider retrieved_at_utc
    (so freshness age reflects the original collection time).
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"import evidence file not found: {path}")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("import evidence must be a JSON object")
    if data.get("schema_version") != 1:
        raise ValueError(f"unsupported schema_version: {data.get('schema_version')!r}")
    if data.get("phase") != "040":
        raise ValueError(f"import evidence phase must be '040'; got {data.get('phase')!r}")
    if "providers" not in data:
        raise ValueError("import evidence missing 'providers' field")
    data["collection_mode"] = "imported"
    data["imported_at_utc"] = _utcnow()
    # Note: provider retrieved_at_utc values are preserved as-is (not updated)
    return data


# ---------------------------------------------------------------------------
# Collection orchestration
# ---------------------------------------------------------------------------

def run_collection(
    source_commit: str,
    packages: list[dict[str, Any]],
    mode: str,
    freshness_hours: float,
    nvd_api_key: str | None = None,
    fixture_dir: str | None = None,
) -> dict[str, Any]:
    """Orchestrate collection across all providers. Returns vuln-intel-record dict."""

    def _not_authorized_provider(provider_key: str) -> dict[str, Any]:
        endpoint = (
            INTEL_SOURCES.get(provider_key, {}).get("querybatch")
            or INTEL_SOURCES.get(provider_key, {}).get("cves")
            or INTEL_SOURCES.get(provider_key, {}).get("json_feed")
        )
        return {
            "status": Status.NOT_AUTHORIZED,
            "endpoint_used": endpoint,
            "retrieved_at_utc": None,
            "response_sha256": None,
            "note": "network access not authorized for this collection run",
        }

    if mode == "not-authorized":
        return {
            "schema_version": 1,
            "phase": "040",
            "source_commit": source_commit,
            "collection_mode": "not_authorized",
            "collected_at_utc": _utcnow(),
            "freshness_policy_hours": freshness_hours,
            "providers": {
                "osv": {
                    **_not_authorized_provider("osv"),
                    "packages_queried": 0,
                    "advisory_ids_returned": [],
                },
                "nvd": {
                    **_not_authorized_provider("nvd"),
                    "cves_enriched": [],
                    "cves_failed": [],
                    "api_key_used": False,
                },
                "cisa_kev": {
                    **_not_authorized_provider("cisa_kev"),
                    "catalog_version": None,
                    "kev_count": 0,
                    "matched_cves": [],
                },
            },
            "vendor_advisories": [],
            "matches": [],
            "no_match_packages": [
                {"package": p.get("name", ""), "version": p.get("version", "unknown"),
                 "ecosystem": p.get("ecosystem", "unknown")}
                for p in packages
            ],
            "unsupported_ecosystems": [],
            "inventory_gaps": [],
            "coverage": {
                "total_packages_checked": len(packages),
                "total_matches": 0,
                "kev_matches": 0,
                "packages_with_gaps": len(packages),
                "baseline_or_refresh": "baseline",
                "notes": "Network access was not authorized; no advisory data collected.",
            },
        }

    # Live / fixture mode
    osv_result = collect_osv(packages, fixture_dir=fixture_dir)
    advisory_ids = osv_result.get("advisory_ids_returned", [])
    matches_raw: list[dict[str, Any]] = osv_result.pop("_matches_raw", [])

    # Fetch full advisory records and build normalized matches.
    # Each entry in matches_raw carries the exact package/version/ecosystem for
    # that advisory_id; preserve the per-package relationship (one match per
    # package+advisory pair before alias deduplication).
    advisories = fetch_osv_advisories(advisory_ids, fixture_dir=fixture_dir)
    matches: list[dict[str, Any]] = []
    advisory_fetch_failed: list[str] = []

    for adv in advisories:
        if adv.get("_fetch_failed"):
            advisory_fetch_failed.append(adv.get("id", "?"))
            continue
        adv_id = adv.get("id", "")
        # Collect ALL packages that matched this advisory (not just the first).
        pkg_contexts = [mr for mr in matches_raw if mr["advisory_id"] == adv_id]
        if not pkg_contexts:
            pkg_contexts = [{}]
        for pkg_context in pkg_contexts:
            m = _extract_match_from_advisory(
                adv,
                pkg_context.get("package", "unknown"),
                pkg_context.get("version", "unknown"),
                pkg_context.get("ecosystem", "unknown"),
            )
            matches.append(m)

    # Downgrade OSV status if any advisory full-record fetches failed.
    if advisory_fetch_failed:
        if osv_result.get("status") == Status.SUCCESS:
            osv_result["status"] = Status.PARTIAL
        osv_result.setdefault("fetch_failed_ids", []).extend(advisory_fetch_failed)

    # Collect CVE IDs for NVD enrichment (from all advisory IDs and aliases)
    all_cve_ids: list[str] = []
    for m in matches:
        for aid in m["advisory_ids"] + m.get("aliases", []):
            if aid.startswith("CVE-") and aid not in all_cve_ids:
                all_cve_ids.append(aid)

    nvd_result = collect_nvd(all_cve_ids, api_key=nvd_api_key, fixture_dir=fixture_dir)

    # Update severity from NVD base scores when available
    nvd_by_cve: dict[str, dict[str, Any]] = {
        e["cve_id"]: e for e in nvd_result.get("cves_enriched", [])
    }
    for m in matches:
        for aid in m["advisory_ids"] + m.get("aliases", []):
            if aid in nvd_by_cve:
                score = nvd_by_cve[aid].get("base_score_v31")
                if score is not None:
                    m["severity"] = _cvss_base_to_severity(float(score))
                break

    kev_result = collect_cisa_kev(all_cve_ids, fixture_dir=fixture_dir)

    # Mark KEV membership on matches
    kev_cve_set = {e["cve_id"] for e in kev_result.get("matched_cves", [])}
    for m in matches:
        for aid in m["advisory_ids"] + m.get("aliases", []):
            if aid in kev_cve_set:
                m["kev_membership"] = True
                break

    # Deduplicate (alias collisions)
    matches = _deduplicate_matches(matches)
    _assign_candidate_id_suggestions(matches)

    # Clean internal fields from provider results
    osv_clean = {k: v for k, v in osv_result.items() if not k.startswith("_")}

    # Compute coverage.
    # NEVER classify a package as "no-match" when the OSV collection failed or
    # was only partial — we don't know whether it has advisories or not.
    osv_status = osv_result.get("status", Status.NOT_CHECKED)
    osv_collection_complete = osv_status in (Status.SUCCESS, Status.NO_MATCH)

    matched_names_lower = {m["package"].lower() for m in matches}
    no_match_packages: list[dict[str, Any]] = []
    if osv_collection_complete:
        no_match_packages = [
            {"package": p.get("name", ""), "version": p.get("version", "unknown"),
             "ecosystem": p.get("ecosystem", "unknown")}
            for p in packages
            if p.get("name", "").lower() not in matched_names_lower
            and not (not p.get("version") and not p.get("name"))
        ]
    inventory_gaps = [
        {"package": p.get("name", ""), "reason": "version-unknown"}
        for p in packages
        if p.get("name") and not p.get("version") and not p.get("commit")
    ]

    return {
        "schema_version": 1,
        "phase": "040",
        "source_commit": source_commit,
        "collection_mode": mode,
        "collected_at_utc": _utcnow(),
        "freshness_policy_hours": freshness_hours,
        "providers": {
            "osv": osv_clean,
            "nvd": nvd_result,
            "cisa_kev": kev_result,
        },
        "vendor_advisories": [],
        "matches": matches,
        "no_match_packages": no_match_packages,
        "unsupported_ecosystems": [],
        "inventory_gaps": inventory_gaps,
        "coverage": {
            "total_packages_checked": len(packages),
            "total_matches": len(matches),
            "kev_matches": len(kev_result.get("matched_cves", [])),
            "packages_with_gaps": len(inventory_gaps),
            "baseline_or_refresh": "baseline",
            "notes": "",
        },
    }


# ---------------------------------------------------------------------------
# CLI — main()
# ---------------------------------------------------------------------------

def main() -> int:  # noqa: C901
    p = argparse.ArgumentParser(
        prog="hermes-vps-collect-intel",
        description=(
            "Collect vulnerability intelligence for hermesVPS phase 040. "
            "Writes a vuln-intel-record.json for registration via hermes-vps-artifacts. "
            "Do not invoke manually in normal operation; Hermes orchestrates collection. "
            "All endpoint URLs are defined in lib/hermes_vps_intel.py INTEL_SOURCES — "
            "do not duplicate them in rules, tasks, or skills."
        ),
    )
    p.add_argument("--run-json", required=True,
                   help="Absolute path to run.json")
    p.add_argument("--output", required=True,
                   help="Absolute path for output vuln-intel-record.json")
    p.add_argument(
        "--mode",
        choices=["live", "imported", "not-authorized"],
        default="not-authorized",
        help=(
            "Collection mode (default: not-authorized — network collection must be explicit). "
            "'live': perform network requests (requires explicit network authorization in trigger). "
            "'imported': re-use prior evidence file (--import-evidence required); "
            "does not refresh evidence age. "
            "'not-authorized': produce an honest record documenting no network access; "
            "valid for registration."
        ),
    )
    p.add_argument("--packages-json", default=None,
                   help="Absolute path to JSON array: [{ecosystem,name,version}, ...]")
    p.add_argument("--import-evidence", default=None,
                   help="Path to prior vuln-intel-record.json (required for --mode imported)")
    p.add_argument(
        "--freshness-hours",
        type=float,
        default=None,
        help=f"Override freshness threshold in hours (default: {DEFAULT_FRESHNESS_HOURS}). "
             "Records effective value; does not change collected_at_utc.",
    )
    p.add_argument("--nvd-api-key-env", default=None,
                   help="Name of env var holding the NVD API key (key is never logged or stored)")
    p.add_argument("--fixture-dir", default=None,
                   help="Directory of fixture JSON files for tests (no live HTTP calls)")
    args = p.parse_args()

    # Validate paths
    if not os.path.isabs(args.run_json):
        print(f"error: --run-json must be absolute: {args.run_json}", file=sys.stderr)
        return 1
    if not os.path.isfile(args.run_json):
        print(f"error: --run-json not found: {args.run_json}", file=sys.stderr)
        return 1
    if not os.path.isabs(args.output):
        print(f"error: --output must be absolute: {args.output}", file=sys.stderr)
        return 1

    # Load run.json for source_commit
    try:
        with open(args.run_json, encoding="utf-8") as fh:
            run_data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"error reading run.json: {exc}", file=sys.stderr)
        return 1
    source_commit = run_data.get("source", {}).get("commit", "")
    if not source_commit:
        print("error: run.json missing source.commit", file=sys.stderr)
        return 1

    freshness_hours = (
        args.freshness_hours
        if args.freshness_hours is not None
        else DEFAULT_FRESHNESS_HOURS
    )

    # Load packages
    packages: list[dict[str, Any]] = []
    if args.packages_json:
        if not os.path.isfile(args.packages_json):
            print(f"error: --packages-json not found: {args.packages_json}", file=sys.stderr)
            return 1
        try:
            with open(args.packages_json, encoding="utf-8") as fh:
                packages = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"error reading --packages-json: {exc}", file=sys.stderr)
            return 1
        if not isinstance(packages, list):
            print("error: --packages-json must be a JSON array", file=sys.stderr)
            return 1

    # Resolve NVD API key (never logged)
    nvd_api_key: str | None = None
    if args.nvd_api_key_env:
        nvd_api_key = os.environ.get(args.nvd_api_key_env)
        if not nvd_api_key:
            print(
                f"warning: env var {args.nvd_api_key_env!r} not set; "
                "NVD will use unauthenticated rate limit",
                file=sys.stderr,
            )

    # Execute collection
    record: dict[str, Any]
    if args.mode == "imported":
        if not args.import_evidence:
            print("error: --mode imported requires --import-evidence PATH", file=sys.stderr)
            return 1
        try:
            record = import_evidence(args.import_evidence)
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            print(f"error importing evidence: {exc}", file=sys.stderr)
            return 1
        if args.freshness_hours is not None:
            record["freshness_policy_hours"] = freshness_hours
    else:
        record = run_collection(
            source_commit=source_commit,
            packages=packages,
            mode=args.mode,
            freshness_hours=freshness_hours,
            nvd_api_key=nvd_api_key,
            fixture_dir=args.fixture_dir,
        )

    # Atomic write
    tmp_path = args.output + f".tmp.{os.getpid()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2)
            fh.write("\n")
        os.replace(tmp_path, args.output)
    except OSError as exc:
        print(f"error writing output: {exc}", file=sys.stderr)
        return 1

    mode_label = record.get("collection_mode", args.mode)
    matches_count = len(record.get("matches", []))
    total = record.get("coverage", {}).get("total_packages_checked", len(packages))
    print(
        f"vuln-intel-record written: mode={mode_label} "
        f"packages={total} matches={matches_count} "
        f"output={args.output}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
