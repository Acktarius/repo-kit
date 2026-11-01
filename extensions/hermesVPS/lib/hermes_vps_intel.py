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
import http.client
import ipaddress
import json
import os
import socket
import ssl
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
# Destination policy — HTTPS only, globally routable unicast IPv4/IPv6 only
# ---------------------------------------------------------------------------

def _ip_allowed(ip_text: str) -> bool:
    """True only for globally routable unicast addresses (IPv4 and IPv6).

    Rejects loopback, RFC 1918, CGNAT, link-local (incl. cloud metadata),
    unique-local, multicast, reserved, documentation, unspecified, and
    IPv4-mapped / 6to4 / Teredo IPv6 forms that embed a disallowed IPv4.
    """
    try:
        ip = ipaddress.ip_address(ip_text.split("%", 1)[0])
    except ValueError:
        return False
    embedded = []
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = [a for a in (ip.ipv4_mapped, ip.sixtofour, ip.teredo and ip.teredo[1]) if a]
    return all(a.is_global and not a.is_multicast for a in [ip, *embedded])


def resolve_allowed(host: str, port: int) -> list[str]:
    """Resolve host and return its addresses; raise ValueError if any is disallowed.

    Fails closed: an unresolvable host is rejected rather than skipped.
    """
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, OSError) as exc:
        raise ValueError(f"cannot resolve {host!r}; refusing request: {exc}") from exc
    addrs = list(dict.fromkeys(info[4][0] for info in infos))
    bad = [a for a in addrs if not _ip_allowed(a)]
    if not addrs or bad:
        raise ValueError(f"{host!r} resolves to disallowed address(es) {bad or addrs}")
    return addrs


def validate_url(url: str) -> None:
    """Raise ValueError if the URL targets a disallowed destination."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        raise ValueError(f"only HTTPS URLs allowed; got scheme {parsed.scheme!r}")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URLs with embedded credentials are not allowed")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("URL has no hostname")
    port = parsed.port or 443
    if port != 443:
        raise ValueError(f"only port 443 allowed; got {port}")
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        is_literal = True
    except ValueError:
        is_literal = False
    if is_literal:
        if not _ip_allowed(host):
            raise ValueError(f"disallowed IP literal destination: {host!r}")
    else:
        resolve_allowed(host, port)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Re-resolve and validate at connect time, then connect to the validated IP.

    Closes the DNS-rebinding gap between validate_url() and the socket connect;
    TLS still verifies the certificate against the original hostname.
    """

    def connect(self) -> None:
        last_exc: OSError | None = None
        for ip in resolve_allowed(self.host, self.port):
            try:
                sock = socket.create_connection((ip, self.port), self.timeout)
                break
            except OSError as exc:
                last_exc = exc
        else:
            raise last_exc or OSError(f"cannot connect to {self.host!r}")
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _PolicyHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req: urllib.request.Request) -> Any:
        return self.do_open(_PinnedHTTPSConnection, req, context=ssl.create_default_context())


class _PolicyRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Every redirect target must pass the same destination policy."""

    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _build_opener() -> urllib.request.OpenerDirector:
    # ProxyHandler({}) disables environment proxies: the pinned connection must
    # reach the validated destination directly.
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _PolicyHTTPSHandler(), _PolicyRedirectHandler()
    )


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

    Destination policy violations (initial URL, redirect target, or connect-time
    resolution) return status 0 without contacting the disallowed destination.
    """
    try:
        validate_url(url)
    except ValueError as exc:
        return 0, f"destination policy: {exc}".encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    opener = _build_opener()
    attempt = 0
    while True:
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            with opener.open(req, timeout=timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < max_retries:
                time.sleep(RETRY_BACKOFF_BASE ** (attempt + 1))
                attempt += 1
                continue
            return exc.code, (exc.read() or b"")
        except ValueError as exc:
            return 0, f"destination policy: {exc}".encode("utf-8")
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
        affected_pkg = affected.get("package", {})
        if (
            affected_pkg.get("name", "").lower() == pkg_name.lower()
            and affected_pkg.get("ecosystem", "") == pkg_ecosystem
        ):
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
        "details_fetch_failed": False,
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
    answered: list[dict[str, str]] = []
    incomplete: list[dict[str, str]] = []
    raw_hash_acc = b""
    failed = False

    for batch_start in range(0, len(queries), MAX_BATCH_SIZE):
        batch_q = queries[batch_start: batch_start + MAX_BATCH_SIZE]
        batch_p = valid_pkgs[batch_start: batch_start + MAX_BATCH_SIZE]
        resp_data, resp_bytes = _osv_querybatch(batch_q, fixture_dir)
        results = resp_data.get("results")
        if "_error" in resp_data or not isinstance(results, list) or len(results) != len(batch_q):
            failed = True
            break
        raw_hash_acc += resp_bytes
        for pkg, result in zip(batch_p, results):
            key = _pkg_key(pkg)
            if result.get("next_page_token"):
                incomplete.append({**key, "reason": "next_page_token not followed; results truncated"})
            else:
                answered.append(key)
            for vuln_stub in result.get("vulns", []):
                vid = vuln_stub.get("id", "")
                if not vid:
                    continue
                if vid not in advisory_ids:
                    advisory_ids.append(vid)
                matches_raw.append({"advisory_id": vid, **key})

    response_sha = _sha256_bytes(raw_hash_acc) if raw_hash_acc else None

    if failed:
        return {
            "status": Status.FAILED,
            "endpoint_used": endpoint,
            "retrieved_at_utc": None,
            "response_sha256": None,
            "packages_queried": len(queries),
            "advisory_ids_returned": [],
            "note": "querybatch request failed or returned a malformed result list",
            "_matches_raw": [],
            "_answered": [],
        }

    status = Status.SUCCESS if advisory_ids else Status.NO_MATCH
    if incomplete:
        status = Status.PARTIAL
    return {
        "status": status,
        "endpoint_used": endpoint,
        "retrieved_at_utc": retrieved_at,
        "response_sha256": response_sha,
        "packages_queried": len(queries),
        "advisory_ids_returned": advisory_ids,
        "incomplete_packages": incomplete,
        "note": None,
        "_matches_raw": matches_raw,   # internal; stripped before persisting
        "_answered": answered,         # internal; packages with complete results
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

def _pkg_key(pkg: dict[str, Any]) -> dict[str, str]:
    """Package identity used throughout collection: ecosystem + name + version."""
    return {
        "package": str(pkg.get("name") or pkg.get("package") or "unknown"),
        "version": str(pkg.get("version") or pkg.get("commit") or "unknown"),
        "ecosystem": str(pkg.get("ecosystem") or "unknown"),
    }


def _key_tuple(m: dict[str, Any]) -> tuple[str, str, str]:
    return (m["ecosystem"], m["package"].lower(), m["version"])


def _deduplicate_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge entries for the SAME package+ecosystem+version that share any advisory
    ID or alias.  Entries for different packages or versions are never merged, so
    each package/version/advisory relationship survives deduplication.
    """
    deduped: list[dict[str, Any]] = []
    for m in matches:
        ids = set(m.get("advisory_ids", [])) | set(m.get("aliases", []))
        target = next(
            (
                d for d in deduped
                if _key_tuple(d) == _key_tuple(m)
                and ids & (set(d["advisory_ids"]) | set(d.get("aliases", [])))
            ),
            None,
        )
        if target is None:
            deduped.append({**m, "advisory_ids": list(m["advisory_ids"]), "aliases": list(m.get("aliases", []))})
            continue
        for aid in m["advisory_ids"]:
            if aid not in target["advisory_ids"]:
                target["advisory_ids"].append(aid)
        for alias in m.get("aliases", []):
            if alias not in target["aliases"] and alias not in target["advisory_ids"]:
                target["aliases"].append(alias)
        for rng in m.get("affected_ranges", []):
            if rng not in target["affected_ranges"]:
                target["affected_ranges"].append(rng)
        for fv in m.get("fixed_versions", []):
            if fv not in target["fixed_versions"]:
                target["fixed_versions"].append(fv)
        target["kev_membership"] = target["kev_membership"] or m["kev_membership"]
        target["details_fetch_failed"] = target["details_fetch_failed"] and m["details_fetch_failed"]
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
            "no_match_packages": [],
            "unsupported_ecosystems": [],
            "inventory_gaps": [
                {"package": _pkg_key(p)["package"], "reason": "not-checked: network not authorized"}
                for p in packages
            ],
            "coverage": {
                "total_packages_checked": 0,
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
    answered: list[dict[str, str]] = osv_result.pop("_answered", [])

    # Fetch full advisory records and build normalized matches.
    # Each entry in matches_raw carries the exact package/version/ecosystem for
    # that advisory_id; preserve the per-package relationship (one match per
    # package+advisory pair before alias deduplication).
    advisories = fetch_osv_advisories(advisory_ids, fixture_dir=fixture_dir)
    matches: list[dict[str, Any]] = []
    advisory_fetch_failed: list[str] = []

    for adv in advisories:
        adv_id = adv.get("id", "")
        fetch_failed = bool(adv.get("_fetch_failed"))
        if fetch_failed:
            advisory_fetch_failed.append(adv_id or "?")
        # One match per package+version+ecosystem that querybatch tied to this advisory.
        for pkg_context in (mr for mr in matches_raw if mr["advisory_id"] == adv_id):
            m = _extract_match_from_advisory(
                {"id": adv_id} if fetch_failed else adv,
                pkg_context["package"],
                pkg_context["version"],
                pkg_context["ecosystem"],
            )
            m["details_fetch_failed"] = fetch_failed
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

    matched_keys = {_key_tuple(m) for m in matches}
    no_match_packages: list[dict[str, Any]] = []
    if osv_collection_complete:
        no_match_packages = [k for k in answered if _key_tuple(k) not in matched_keys]
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
            "total_packages_checked": len(answered),
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
