"""contre-attaque intelligence sources, bounded HTTPS client, and normalization.

INTEL_SOURCES is the single place where provider URLs are defined; rules,
skills, and docs refer to this module instead of repeating them.
"""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

INTEL_SOURCES: dict[str, dict[str, str]] = {
    "osv": {
        "query": "https://api.osv.dev/v1/query",
        "querybatch": "https://api.osv.dev/v1/querybatch",
        "vuln": "https://api.osv.dev/v1/vulns/{id}",
        "docs": "https://google.github.io/osv.dev/api/",
    },
    "nvd": {
        "cves": "https://services.nvd.nist.gov/rest/json/cves/2.0",
        "docs": "https://nvd.nist.gov/developers/vulnerabilities",
    },
    "kev": {
        "json_feed": "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
        "catalog": "https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
    },
}

PROVIDER_CAPABILITIES: dict[str, dict[str, str]] = {
    "osv": {
        "scope": "Per-package lookups (ecosystem + name + version). Not a global recent-advisory feed.",
        "window": "Every inventory component is queried; each advisory's published/modified time "
                  "is compared with the window afterwards. Unassessed older matches are baseline.",
        "pagination": "querybatch next_page_token is followed through /v1/query (bounded pages).",
        "transmits": "ecosystem, package name, and resolved version of every queryable component",
    },
    "nvd": {
        "scope": "Global CVE feed filtered by lastModified range (max 120 days per request).",
        "window": "lastModStartDate/lastModEndDate = window; items are then classified as published "
                  "or modified in window and matched locally against runtime/image/OS products by CPE.",
        "pagination": "startIndex/resultsPerPage, bounded page count, rate-limited.",
        "transmits": "the window dates and page index; CVE IDs for severity enrichment",
    },
    "kev": {
        "scope": "Full CISA Known Exploited Vulnerabilities catalog.",
        "window": "dateAdded (day precision) inside the window's inclusive UTC dates; KEV membership "
                  "of every candidate CVE is re-checked regardless of date.",
        "pagination": "single document",
        "transmits": "nothing beyond a plain GET of the public feed",
    },
    "vendor": {
        "scope": "Official vendor/project advisories and incident disclosures fetched by URL.",
        "window": "agent-selected; news is a discovery lead only and never sufficient evidence",
        "pagination": "single document per URL",
        "transmits": "the requested URL",
    },
}

REQUEST_TIMEOUT = 30
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_REDIRECTS = 5
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0
OSV_BATCH_SIZE = 1000
OSV_MAX_PAGES = 10
NVD_PAGE_SIZE = 500
NVD_MAX_PAGES = 40
NVD_MAX_RANGE_DAYS = 120
NVD_DELAY_NO_KEY = 6.1
NVD_DELAY_WITH_KEY = 0.7
NVD_MAX_CVE_LOOKUPS = 20
USER_AGENT = "repo-kit-contre-attaque/1"
DEFAULT_PERIOD_DAYS = 7

SEVERITIES = ("low", "medium", "high", "critical")


class Status:
    SUCCESS = "success"
    NO_MATCH = "no_match"
    PARTIAL = "partial"
    FAILED = "failed"
    NOT_AUTHORIZED = "not_authorized"
    NOT_CHECKED = "not_checked"

    COMPLETE = ("success", "no_match")


# ---------------------------------------------------------------------------
# Time window
# ---------------------------------------------------------------------------

class PeriodError(ValueError):
    pass


_PERIOD_RE = re.compile(r"^(\d+)\s*(d|day|days)?$", re.IGNORECASE)


def parse_period(text: str | None) -> int:
    """Return the lookback in days. Empty means DEFAULT_PERIOD_DAYS."""
    raw = (text or "").strip()
    if not raw:
        return DEFAULT_PERIOD_DAYS
    m = _PERIOD_RE.match(raw)
    if not m:
        raise PeriodError(
            f"invalid period {raw!r}: use a whole number of days such as 7, 3d, 3days, or '3 days'"
        )
    days = int(m.group(1))
    if not 1 <= days <= NVD_MAX_RANGE_DAYS:
        raise PeriodError(f"invalid period {raw!r}: days must be between 1 and {NVD_MAX_RANGE_DAYS}")
    return days


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime
    days: int

    def contains(self, ts: datetime | None) -> bool:
        return ts is not None and self.start <= ts <= self.end

    def contains_date(self, d: date | None) -> bool:
        return d is not None and self.start.date() <= d <= self.end.date()

    def as_dict(self) -> dict[str, Any]:
        return {"days": self.days, "start_utc": iso(self.start), "end_utc": iso(self.end)}


def make_window(days: int, now: datetime) -> Window:
    end = now.astimezone(timezone.utc).replace(microsecond=0)
    return Window(start=end - timedelta(days=days), end=end, days=days)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(value: Any) -> datetime | None:
    """Parse ISO-8601 timestamps; naive values (NVD) are UTC."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?([+-]\d{2}:\d{2})?$", text)
        if not m:
            return None
        dt = datetime.fromisoformat(m.group(1) + (m.group(3) or ""))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_day(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def window_reasons(window: Window, published: Any, modified: Any) -> list[str]:
    reasons = []
    if window.contains(parse_ts(published)):
        reasons.append("published")
    if window.contains(parse_ts(modified)) and "published" not in reasons:
        reasons.append("modified")
    return reasons


# ---------------------------------------------------------------------------
# Destination policy and bounded HTTPS transport
# ---------------------------------------------------------------------------

def _ip_allowed(ip_text: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text.split("%", 1)[0])
    except ValueError:
        return False
    embedded = []
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = [a for a in (ip.ipv4_mapped, ip.sixtofour, ip.teredo and ip.teredo[1]) if a]
    return all(a.is_global and not a.is_multicast for a in [ip, *embedded])


def resolve_allowed(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, OSError) as exc:
        raise ValueError(f"cannot resolve {host!r}: {exc}") from exc
    addrs = list(dict.fromkeys(info[4][0] for info in infos))
    bad = [a for a in addrs if not _ip_allowed(a)]
    if not addrs or bad:
        raise ValueError(f"{host!r} resolves to disallowed address(es) {bad or addrs}")
    return addrs


def check_url_shape(url: str) -> urllib.parse.SplitResult:
    """Static checks: HTTPS, port 443, no credentials, has a host."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        raise ValueError(f"only HTTPS URLs are allowed (got {parsed.scheme or 'none'!r})")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URLs with embedded credentials are not allowed")
    if not parsed.hostname:
        raise ValueError("URL has no hostname")
    if (parsed.port or 443) != 443:
        raise ValueError(f"only port 443 is allowed (got {parsed.port})")
    return parsed


def validate_url(url: str) -> None:
    parsed = check_url_shape(url)
    host = parsed.hostname.lower()
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        resolve_allowed(host, 443)
        return
    if not _ip_allowed(host):
        raise ValueError(f"disallowed IP literal destination {host!r}")


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Re-resolve and validate at connect time to close the DNS-rebinding gap."""

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
    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _build_opener() -> urllib.request.OpenerDirector:
    # Environment proxies are disabled: the pinned connection must reach the validated host.
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _PolicyHTTPSHandler(), _PolicyRedirectHandler()
    )


Transport = Callable[[str, str, "bytes | None", "dict[str, str]"], "tuple[int, bytes, str]"]


def live_transport(method: str, url: str, body: bytes | None, headers: dict[str, str]) -> tuple[int, bytes, str]:
    try:
        validate_url(url)
    except ValueError as exc:
        return 0, b"", f"destination policy: {exc}"
    hdrs = {"Accept": "application/json", "User-Agent": USER_AGENT, **headers}
    if body is not None:
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with _build_opener().open(req, timeout=REQUEST_TIMEOUT) as resp:
            data = resp.read(MAX_RESPONSE_BYTES + 1)
            if len(data) > MAX_RESPONSE_BYTES:
                return 0, b"", f"response exceeds {MAX_RESPONSE_BYTES} bytes"
            return resp.status, data, ""
    except urllib.error.HTTPError as exc:
        return exc.code, b"", f"HTTP {exc.code}"
    except ValueError as exc:
        return 0, b"", f"destination policy: {exc}"
    except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
        return 0, b"", f"network error: {exc}"


_SECRET_PARAM = re.compile(r"(key|token|secret|password|passwd|auth|sig|signature|credential)", re.IGNORECASE)


def redact_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if not parsed.query:
        return url
    pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    safe = [(k, "REDACTED" if _SECRET_PARAM.search(k) else v) for k, v in pairs]
    return urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(safe)))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Fetcher:
    """Retrying, logging wrapper around a transport.

    store(data) persists a successful response body and returns an evidence ID.
    Request headers (which may carry an API key) are never logged.
    """

    def __init__(
        self,
        transport: Transport | None = None,
        store: Callable[[bytes, dict[str, Any]], str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.transport = transport or live_transport
        self.store = store
        self.sleep = sleep
        self.log: list[dict[str, Any]] = []

    def request(
        self,
        provider: str,
        method: str,
        url: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes, dict[str, Any]]:
        attempt = 0
        while True:
            status, data, error = self.transport(method, url, body, dict(headers or {}))
            if status in (429, 503) and attempt < MAX_RETRIES:
                self.sleep(RETRY_BACKOFF ** (attempt + 1))
                attempt += 1
                continue
            break
        if status == 200 and len(data) > MAX_RESPONSE_BYTES:
            status, data, error = 0, b"", f"response exceeds {MAX_RESPONSE_BYTES} bytes"
        meta: dict[str, Any] = {
            "provider": provider,
            "method": method,
            "url": redact_url(url),
            "status": status,
            "at_utc": iso(utcnow()),
            "bytes": len(data),
            "sha256": sha256_bytes(data) if status == 200 else None,
            "request_sha256": sha256_bytes(body) if body else None,
            "error": error or None,
            "evidence": None,
        }
        if status == 200 and self.store is not None:
            meta["evidence"] = self.store(data, meta)
        self.log.append(meta)
        return status, data, meta

    def get_json(self, provider: str, url: str, headers: dict[str, str] | None = None) -> tuple[Any, dict[str, Any]]:
        status, data, meta = self.request(provider, "GET", url, headers=headers)
        return _decode(status, data, meta), meta

    def post_json(self, provider: str, url: str, payload: Any) -> tuple[Any, dict[str, Any]]:
        status, data, meta = self.request(provider, "POST", url, body=json.dumps(payload).encode())
        return _decode(status, data, meta), meta


def _decode(status: int, data: bytes, meta: dict[str, Any]) -> Any:
    if status != 200:
        meta["error"] = meta.get("error") or f"HTTP {status}"
        return None
    try:
        return json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        meta["error"] = f"invalid JSON: {exc}"
        return None


# ---------------------------------------------------------------------------
# Version comparison (numeric dotted versions only; anything else is unknown)
# ---------------------------------------------------------------------------

_NUM_VERSION = re.compile(r"^v?(\d+(?:\.\d+)*)$")


def num_version(text: Any) -> tuple[int, ...] | None:
    if not isinstance(text, str):
        return None
    m = _NUM_VERSION.match(text.strip())
    return tuple(int(p) for p in m.group(1).split(".")) if m else None


def _cmp(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    n = max(len(a), len(b))
    pa, pb = a + (0,) * (n - len(a)), b + (0,) * (n - len(b))
    return (pa > pb) - (pa < pb)


def _next_prefix(v: tuple[int, ...]) -> tuple[int, ...]:
    return v[:-1] + (v[-1] + 1,)


def range_relation(
    version: str,
    start: str | None,
    start_incl: bool,
    end: str | None,
    end_incl: bool,
    precise_parts: int = 3,
) -> bool | None:
    """True if version is inside the range, False if outside, None if unknown.

    Versions with fewer than precise_parts components (e.g. image tag "3.11")
    are treated as the whole prefix family [3.11, 3.12).
    """
    v = num_version(version)
    s = num_version(start) if start else None
    e = num_version(end) if end else None
    if v is None or (start and s is None) or (end and e is None):
        return None
    lo, hi = v, (_next_prefix(v) if len(v) < precise_parts else None)

    def above_start(x: tuple[int, ...]) -> bool:
        return s is None or _cmp(x, s) > 0 or (start_incl and _cmp(x, s) == 0)

    def below_end(x: tuple[int, ...]) -> bool:
        return e is None or _cmp(x, e) < 0 or (end_incl and _cmp(x, e) == 0)

    if hi is None:
        return above_start(lo) and below_end(lo)
    if (e is not None and not below_end(lo)) or (s is not None and _cmp(hi, s) <= 0):
        return False
    if above_start(lo) and (e is None or _cmp(hi, e) <= 0):
        return True
    return None


# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------

_SEV_MAP = {"low": "low", "moderate": "medium", "medium": "medium", "high": "high", "critical": "critical"}


def osv_severity(record: dict[str, Any]) -> str | None:
    db = record.get("database_specific") or {}
    sev = db.get("severity") if isinstance(db, dict) else None
    return _SEV_MAP.get(str(sev).lower()) if sev else None


def nvd_severity(cve: dict[str, Any]) -> str | None:
    metrics = cve.get("metrics") or {}
    for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        entries = metrics.get(key) or []
        entries = sorted(entries, key=lambda m: m.get("type") != "Primary")
        for m in entries:
            sev = (m.get("cvssData") or {}).get("baseSeverity") or m.get("baseSeverity")
            if sev and str(sev).lower() in _SEV_MAP:
                return _SEV_MAP[str(sev).lower()]
    return None


def max_severity(*values: str | None) -> str | None:
    known = [v for v in values if v in SEVERITIES]
    return max(known, key=SEVERITIES.index) if known else None


# ---------------------------------------------------------------------------
# OSV
# ---------------------------------------------------------------------------

def osv_query_for(component: dict[str, Any]) -> dict[str, Any] | None:
    eco, name, version = component.get("ecosystem"), component.get("name"), component.get("version")
    if component.get("kind") not in ("library", "os-package") or not (eco and name and version):
        return None
    return {"package": {"ecosystem": eco, "name": name}, "version": version}


def collect_osv(
    fetcher: Fetcher,
    components: list[dict[str, Any]],
    cached: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Query OSV for every queryable component.

    cached maps advisory ID -> {"modified": ..., "record": ...}; a record is
    re-fetched only when querybatch reports a different modified time.
    """
    queries: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for comp in components:
        q = osv_query_for(comp)
        if q:
            queries.append((comp, q))
    result: dict[str, Any] = {
        "status": Status.NOT_CHECKED, "mode": "live", "queried": len(queries),
        "answered": [], "incomplete": [], "errors": [], "matches": {}, "records": {},
    }
    if not queries:
        result["note"] = "no component has ecosystem, name, and resolved version"
        return result

    stubs: dict[str, str | None] = {}
    batch_failures = 0
    for start in range(0, len(queries), OSV_BATCH_SIZE):
        batch = queries[start:start + OSV_BATCH_SIZE]
        data, meta = fetcher.post_json("osv", INTEL_SOURCES["osv"]["querybatch"], {"queries": [q for _, q in batch]})
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list) or len(results) != len(batch):
            batch_failures += 1
            result["errors"].append(f"querybatch failed: {meta.get('error') or 'malformed result list'}")
            result["incomplete"].extend(c["key"] for c, _ in batch)
            continue
        for (comp, q), res in zip(batch, results):
            vulns = list((res or {}).get("vulns") or [])
            token = (res or {}).get("next_page_token")
            pages = 0
            while token and pages < OSV_MAX_PAGES:
                page, pmeta = fetcher.post_json("osv", INTEL_SOURCES["osv"]["query"], {**q, "page_token": token})
                if not isinstance(page, dict):
                    result["errors"].append(f"query page failed for {comp['key']}: {pmeta.get('error')}")
                    break
                vulns.extend(page.get("vulns") or [])
                token = page.get("next_page_token")
                pages += 1
            if token:
                result["incomplete"].append(comp["key"])
            else:
                result["answered"].append(comp["key"])
            ids = []
            for stub in vulns:
                vid = stub.get("id")
                if vid:
                    ids.append(vid)
                    stubs[vid] = stub.get("modified")
            result["matches"][comp["key"]] = sorted(set(ids))

    for vid, modified in sorted(stubs.items()):
        prior = cached.get(vid)
        if prior and prior.get("record") and modified and prior.get("modified") == modified:
            result["records"][vid] = prior["record"]
            continue
        url = INTEL_SOURCES["osv"]["vuln"].format(id=urllib.parse.quote(vid, safe=""))
        rec, meta = fetcher.get_json("osv", url)
        if isinstance(rec, dict) and rec.get("id"):
            rec["_evidence"] = meta.get("evidence")
            result["records"][vid] = rec
        else:
            result["errors"].append(f"advisory {vid} fetch failed: {meta.get('error')}")

    if batch_failures and not result["answered"]:
        result["status"] = Status.FAILED
    elif result["incomplete"] or result["errors"]:
        result["status"] = Status.PARTIAL
    else:
        result["status"] = Status.SUCCESS if stubs else Status.NO_MATCH
    return result


def osv_record_affects(record: dict[str, Any], component: dict[str, Any]) -> bool | None:
    """Local match used for imported OSV records (no server-side evaluation)."""
    name = str(component.get("name") or "").lower()
    eco = str(component.get("ecosystem") or "")
    version = str(component.get("version") or "")
    verdict: bool | None = False
    for aff in record.get("affected") or []:
        pkg = aff.get("package") or {}
        if str(pkg.get("name", "")).lower() != name or str(pkg.get("ecosystem", "")) != eco:
            continue
        if version in (aff.get("versions") or []):
            return True
        for rng in aff.get("ranges") or []:
            if rng.get("type") not in ("SEMVER", "ECOSYSTEM"):
                verdict = None
                continue
            for start, end, end_incl in _osv_intervals(rng.get("events") or []):
                rel = range_relation(version, start, True, end, end_incl, precise_parts=1)
                if rel is True:
                    return True
                if rel is None:
                    verdict = None
    return verdict


def _osv_intervals(events: list[dict[str, Any]]) -> list[tuple[str | None, str | None, bool]]:
    intervals: list[tuple[str | None, str | None, bool]] = []
    start: str | None = None
    is_open = False
    for evt in events:
        if "introduced" in evt:
            start = None if evt["introduced"] == "0" else evt["introduced"]
            is_open = True
        elif is_open and "fixed" in evt:
            intervals.append((start, evt["fixed"], False))
            is_open = False
        elif is_open and "last_affected" in evt:
            intervals.append((start, evt["last_affected"], True))
            is_open = False
    if is_open:
        intervals.append((start, None, False))
    return intervals


def osv_fixed_versions(record: dict[str, Any], component: dict[str, Any]) -> list[str]:
    """Fixed versions of the affected interval that contains the component's version.

    Fixes for other maintenance branches are never returned; if the version
    cannot be placed in an interval, nothing is returned.
    """
    name = str(component.get("name") or "").lower()
    eco = str(component.get("ecosystem") or "")
    version = str(component.get("version") or "")
    out: list[str] = []
    for aff in record.get("affected") or []:
        pkg = aff.get("package") or {}
        if str(pkg.get("name", "")).lower() != name or str(pkg.get("ecosystem", "")) != eco:
            continue
        for rng in aff.get("ranges") or []:
            if rng.get("type") not in ("SEMVER", "ECOSYSTEM"):
                continue
            for start, end, end_incl in _osv_intervals(rng.get("events") or []):
                if end and not end_incl and range_relation(version, start, True, end, False, precise_parts=1) is True:
                    if end not in out:
                        out.append(str(end))
    return out


# ---------------------------------------------------------------------------
# NVD
# ---------------------------------------------------------------------------

def _nvd_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000+00:00")


def collect_nvd(fetcher: Fetcher, window: Window, api_key: str | None = None) -> dict[str, Any]:
    headers = {"apiKey": api_key} if api_key else {}
    delay = NVD_DELAY_WITH_KEY if api_key else NVD_DELAY_NO_KEY
    result: dict[str, Any] = {"status": Status.NOT_CHECKED, "mode": "live", "items": [], "total": None,
                              "pages": 0, "errors": [], "api_key_used": bool(api_key)}
    start_index = 0
    while True:
        if result["pages"] >= NVD_MAX_PAGES:
            result["errors"].append(f"page cap {NVD_MAX_PAGES} reached; remaining results not collected")
            break
        if result["pages"]:
            fetcher.sleep(delay)
        params = urllib.parse.urlencode({
            "lastModStartDate": _nvd_ts(window.start),
            "lastModEndDate": _nvd_ts(window.end),
            "resultsPerPage": NVD_PAGE_SIZE,
            "startIndex": start_index,
        })
        data, meta = fetcher.get_json("nvd", f"{INTEL_SOURCES['nvd']['cves']}?{params}", headers)
        if not isinstance(data, dict) or not isinstance(data.get("vulnerabilities"), list):
            result["errors"].append(f"page startIndex={start_index} failed: {meta.get('error') or 'malformed'}")
            break
        result["pages"] += 1
        result["total"] = int(data.get("totalResults") or 0)
        for v in data["vulnerabilities"]:
            cve = v.get("cve") or {}
            if cve.get("id"):
                cve["_evidence"] = meta.get("evidence")
                result["items"].append(cve)
        start_index += len(data["vulnerabilities"])
        if not data["vulnerabilities"] or start_index >= result["total"]:
            break
    if result["pages"] == 0:
        result["status"] = Status.FAILED
    elif result["errors"]:
        result["status"] = Status.PARTIAL
    else:
        result["status"] = Status.SUCCESS if result["items"] else Status.NO_MATCH
    return result


def nvd_lookup(fetcher: Fetcher, cve_ids: list[str], api_key: str | None = None) -> dict[str, Any]:
    headers = {"apiKey": api_key} if api_key else {}
    delay = NVD_DELAY_WITH_KEY if api_key else NVD_DELAY_NO_KEY
    found: dict[str, Any] = {}
    failed: list[str] = []
    for i, cve_id in enumerate(cve_ids[:NVD_MAX_CVE_LOOKUPS]):
        if i:
            fetcher.sleep(delay)
        url = f"{INTEL_SOURCES['nvd']['cves']}?{urllib.parse.urlencode({'cveId': cve_id})}"
        data, meta = fetcher.get_json("nvd", url, headers)
        vulns = data.get("vulnerabilities") if isinstance(data, dict) else None
        if not isinstance(vulns, list):
            failed.append(cve_id)
            continue
        for v in vulns:
            cve = v.get("cve") or {}
            if cve.get("id"):
                cve["_evidence"] = meta.get("evidence")
                found[cve["id"]] = cve
    return {"found": found, "failed": failed, "skipped": cve_ids[NVD_MAX_CVE_LOOKUPS:]}


def _cpe_parts(criteria: str) -> tuple[str, str, str] | None:
    parts = criteria.split(":")
    if len(parts) < 6 or parts[0] != "cpe" or parts[1] != "2.3":
        return None
    return parts[3].lower(), parts[4].lower(), parts[5]


def nvd_cpe_relation(cve: dict[str, Any], component: dict[str, Any]) -> bool | None:
    """Match one NVD CVE against a component that carries CPE vendor/product pairs.

    Returns True (version in a vulnerable range), None (product matches but the
    version cannot be decided), or False (no product match or version outside).
    """
    targets = {(v.lower(), p.lower()) for v, p in component.get("cpe") or []}
    version = component.get("version")
    if not targets:
        return False
    verdict: bool | None = False
    for conf in cve.get("configurations") or []:
        for node in conf.get("nodes") or []:
            for match in node.get("cpeMatch") or []:
                if not match.get("vulnerable"):
                    continue
                parts = _cpe_parts(match.get("criteria", ""))
                if not parts or (parts[0], parts[1]) not in targets:
                    continue
                if not version:
                    verdict = None
                    continue
                cpe_ver = parts[2]
                if cpe_ver not in ("*", "-", ""):
                    v, c = num_version(version), num_version(cpe_ver)
                    if v is None or c is None:
                        verdict = None
                    elif len(v) >= 3 and _cmp(v, c) == 0:
                        return True
                    elif len(v) < 3 and c[:len(v)] == v:
                        verdict = None
                    continue
                start = match.get("versionStartIncluding") or match.get("versionStartExcluding")
                end = match.get("versionEndIncluding") or match.get("versionEndExcluding")
                rel = range_relation(
                    version, start, "versionStartIncluding" in match,
                    end, "versionEndIncluding" in match,
                )
                if rel is True:
                    return True
                if rel is None:
                    verdict = None
    return verdict


def nvd_reference_urls(cve: dict[str, Any]) -> list[str]:
    return sorted({r.get("url") for r in cve.get("references") or [] if r.get("url")})


def nvd_description(cve: dict[str, Any]) -> str:
    for d in cve.get("descriptions") or []:
        if d.get("lang") == "en":
            return str(d.get("value") or "")
    return ""


# ---------------------------------------------------------------------------
# CISA KEV
# ---------------------------------------------------------------------------

def parse_kev(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict) or not isinstance(data.get("vulnerabilities"), list):
        return None
    entries = {}
    for v in data["vulnerabilities"]:
        cve = v.get("cveID")
        if cve:
            entries[cve] = {
                "cve_id": cve,
                "vendor_project": v.get("vendorProject"),
                "product": v.get("product"),
                "name": v.get("vulnerabilityName"),
                "date_added": v.get("dateAdded"),
                "due_date": v.get("dueDate"),
                "required_action": v.get("requiredAction"),
                "known_ransomware": v.get("knownRansomwareCampaignUse"),
            }
    return {"catalog_version": data.get("catalogVersion"), "date_released": data.get("dateReleased"),
            "entries": entries}


def collect_kev(fetcher: Fetcher) -> dict[str, Any]:
    data, meta = fetcher.get_json("kev", INTEL_SOURCES["kev"]["json_feed"])
    parsed = parse_kev(data)
    if parsed is None:
        return {"status": Status.FAILED, "mode": "live", "entries": {},
                "errors": [f"feed failed: {meta.get('error') or 'malformed'}"]}
    return {"status": Status.SUCCESS, "mode": "live", "errors": [], "evidence": meta.get("evidence"), **parsed}


# ---------------------------------------------------------------------------
# Alias grouping and advisory revision hashing
# ---------------------------------------------------------------------------

def alias_groups(records: dict[str, list[str]]) -> dict[str, str]:
    """Union-find over advisory IDs. records maps id -> aliases. Returns id -> canonical."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for rid, aliases in records.items():
        for alias in aliases:
            ra, rb = find(rid), find(alias)
            if ra != rb:
                parent[ra] = rb
        find(rid)
    members: dict[str, list[str]] = {}
    for x in list(parent):
        members.setdefault(find(x), []).append(x)
    canonical: dict[str, str] = {}
    for group in members.values():
        cves = sorted(g for g in group if g.startswith("CVE-"))
        name = cves[0] if cves else sorted(group)[0]
        for g in group:
            canonical[g] = name
    return canonical


def revision_hash(parts: list[dict[str, Any]]) -> str:
    """Stable hash over the assessment-relevant content of advisory records."""
    norm = json.dumps(sorted(parts, key=lambda p: json.dumps(p, sort_keys=True)), sort_keys=True)
    return sha256_bytes(norm.encode())


def osv_revision_part(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "osv", "id": rec.get("id"), "modified": rec.get("modified"),
        "withdrawn": rec.get("withdrawn"), "aliases": sorted(rec.get("aliases") or []),
        "affected": rec.get("affected"), "severity": rec.get("severity"),
        "db_severity": osv_severity(rec),
    }


def nvd_revision_part(cve: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "nvd", "id": cve.get("id"), "lastModified": cve.get("lastModified"),
        "status": cve.get("vulnStatus"), "configurations": cve.get("configurations"),
        "severity": nvd_severity(cve), "references": nvd_reference_urls(cve),
    }


def clean_text(text: Any, limit: int = 300) -> str:
    """Advisory text is untrusted: collapse whitespace, drop control characters, truncate."""
    s = re.sub(r"[\x00-\x1f\x7f]+", " ", str(text or ""))
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= limit else s[: limit - 1] + "…"
