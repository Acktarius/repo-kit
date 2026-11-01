#!/usr/bin/env bash
# Focused regression checks for the 75462d8 review (REG-1 .. REG-10).
# Each check builds its own fixtures and runs independently; a failing check
# does not stop the others.  Synthetic repos, fixture/mocked network only.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXT="${ROOT}/extensions/hermesVPS"

command -v git >/dev/null 2>&1 || { echo "FAIL: missing git" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "FAIL: missing python3" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'chmod -R u+rwX "${TMP}" 2>/dev/null; rm -rf "${TMP}"' EXIT

PYTHONDONTWRITEBYTECODE=1 python3 - "${EXT}" "${TMP}" <<'PY'
import contextlib, io, json, os, shlex, shutil, subprocess, sys, traceback

EXT, TMP = sys.argv[1], sys.argv[2]
STAMP = os.path.join(os.path.dirname(os.path.dirname(EXT)), "tests", "hermes_vps_stamp.py")
HDR_PREFIX, HDR_SUFFIX = "<!-- hermes-vps-report: ", " -->"
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
results = []


class Run:
    """Fresh policy copy, git source repo, and run.json under its own directory."""

    def __init__(self, name, run_root_name="run-reg"):
        self.base = os.path.join(TMP, name)
        self.policy = os.path.join(self.base, "policy", "hermes-review")
        self.src = os.path.join(self.base, "repositories", "example-repo")
        self.run_root = os.path.join(self.base, "review-runs", "example-repo", run_root_name)
        self.work = os.path.join(self.base, "work")
        shutil.copytree(EXT, self.policy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for d in (self.src, os.path.join(self.run_root, "reports"), self.work):
            os.makedirs(d, exist_ok=True)
        git = lambda *a: subprocess.run(["git", "-C", self.src, *a], check=True, capture_output=True)
        git("init", "-q")
        git("config", "user.email", "t@example.com")
        git("config", "user.name", "T")
        with open(os.path.join(self.src, "README.md"), "w") as fh:
            fh.write("hello\n")
        git("add", "README.md")
        git("commit", "-q", "-m", "init")
        self.sha = subprocess.run(["git", "-C", self.src, "rev-parse", "HEAD"], check=True,
                                  capture_output=True, text=True).stdout.strip()
        self.run_json = os.path.join(self.run_root, "run.json")
        self.write_json(self.run_json, {
            "schema_version": 1, "run_id": "run-reg", "policy_prefix": self.policy,
            "source": {"path": self.src, "identity": "fixture/example-repo",
                       "commit": self.sha, "require_clean_worktree": True},
            "output": {"run_root": self.run_root},
            "phase_request": {"phase": "010", "phase_name": "inventory", "requested_by": "test",
                              "requested_at_utc": "2026-10-30T00:00:00Z"},
            "prerequisites": {"artifacts": []},
            "boundaries": {"claims_os_readonly_source": False, "allowed_write_roots": [self.run_root]},
            "toolkit": {"toolkit_revision": "testrev01", "toolkit_dirty": False},
        })
        self.n = 0

    # -- files -------------------------------------------------------------
    @staticmethod
    def write_json(path, data):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        return path

    def report(self, title, state="complete"):
        self.n += 1
        path = os.path.join(self.work, f"report-{self.n}.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"# {title}\n\nContent {self.n}.\n\nState: `{state}`\n")
        return path

    def payload(self, data):
        self.n += 1
        return self.write_json(os.path.join(self.work, f"payload-{self.n}.json"), data)

    def manifest(self):
        with open(os.path.join(self.run_root, "manifest.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def art(self, art_id):
        return next(a for a in self.manifest()["artifacts"] if a["id"] == art_id)

    def sel(self, phase, subject=None):
        m = self.manifest()
        if subject is not None:
            return m.get("selected_by_subject", {}).get(phase, {}).get(subject)
        return m.get("selected_by_phase", {}).get(phase)

    # -- payload fixtures ----------------------------------------------------
    def triage(self, cids, commit=None):
        return {"schema_version": 1, "phase": "060", "source_commit": commit or self.sha,
                "candidates": [{"candidate_id": c, "title": f"Finding {c}", "disposition": "validated-new",
                                "severity_estimate": "medium", "confidence": "high"} for c in cids]}

    def finding(self, cid, disposition="confirmed", finding_id=None, commit=None):
        return {"schema_version": 1, "phase": "070", "candidate_id": cid,
                "source_commit": commit or self.sha, "assessment_disposition": disposition,
                "assessment_rationale": f"rationale {cid}", "affected_components": ["auth.py"],
                "impact": "bypass", "likelihood": "medium",
                "evidence": [{"description": "cmp", "file": "auth.py", "line": 1}],
                "unknowns": [], "blockers": [],
                "proposed_finding": {"id": finding_id, "title": f"Finding {cid}", "status": "open",
                                     "severity": "medium", "confidence": "high", "files": ["auth.py"],
                                     "summary": "s", "exploitPath": "e", "remediation": "r"}}

    def intel(self):
        na = lambda ep: {"status": "not_authorized", "endpoint_used": ep, "retrieved_at_utc": None,
                         "response_sha256": None, "note": "not authorized"}
        return {"schema_version": 1, "phase": "040", "source_commit": self.sha,
                "collection_mode": "not_authorized", "collected_at_utc": "2026-10-30T00:00:00Z",
                "freshness_policy_hours": 24.0,
                "providers": {
                    "osv": {**na("https://api.osv.dev/v1/querybatch"), "packages_queried": 0,
                            "advisory_ids_returned": []},
                    "nvd": {**na("https://services.nvd.nist.gov/rest/json/cves/2.0"), "cves_enriched": [],
                            "cves_failed": [], "api_key_used": False},
                    "cisa_kev": {**na("https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"),
                                 "catalog_version": None, "kev_count": 0, "matched_cves": []}},
                "vendor_advisories": [], "matches": [], "no_match_packages": [],
                "unsupported_ecosystems": [], "inventory_gaps": [],
                "coverage": {"total_packages_checked": 0, "total_matches": 0, "kev_matches": 0,
                             "packages_with_gaps": 0, "baseline_or_refresh": "baseline", "notes": "na"}}

    def plan080(self, cid, finding_id=None):
        intel_id, f_id = self.sel("040"), self.sel("070", cid)
        data = {"schema_version": 1, "phase": "080", "candidate_id": cid, "source_commit": self.sha,
                "intel_artifact_id": intel_id,
                "intel_artifact_sha256": self.art(intel_id)["payload_sha256"],
                "assessed_finding_artifact_id": f_id,
                "assessed_finding_sha256": self.art(f_id)["payload_sha256"],
                "intel_freshness_at_plan_time": {
                    "evaluated_at_utc": "2026-10-30T00:00:00Z", "effective_threshold_hours": 24.0,
                    "threshold_source": "default", "freshness_ok": False, "stale_providers": [],
                    "unknown_providers": ["osv", "nvd", "cisa_kev"], "limitations": []}}
        if finding_id is not None:
            data["finding_id"] = finding_id
        return data

    # -- commands ------------------------------------------------------------
    def tool(self, name, *args):
        return subprocess.run([os.path.join(EXT, "bin", name), *args], capture_output=True, text=True, env=ENV)

    def artifacts(self, sub, *args):
        return self.tool("hermes-vps-artifacts", sub, "--run-json", self.run_json, *args)

    def review(self, phase, trigger=None):
        extra = ["--trigger-input", trigger] if trigger else []
        return self.tool("hermes-vps-review", "--phase", phase, "--run-json", self.run_json, *extra)

    def stamp(self, report, phase, subject=None):
        """What the agent does at phase start: take the runner's header (input snapshot)."""
        args = ["register", "--run-json", self.run_json, "--phase", phase, "--source-report", report]
        subprocess.run([sys.executable, STAMP, os.path.join(EXT, "bin", "hermes-vps-review"), *args,
                        *(["--subject-id", subject] if subject else [])], check=True, env=ENV)

    def register(self, phase, report, payload=None, subject=None, must=True):
        self.stamp(report, phase, subject)
        args = ["--phase", phase, "--source-report", report]
        if subject:
            args += ["--subject-id", subject]
        if payload is not None:
            args += ["--payload-json", payload if isinstance(payload, str) else self.payload(payload)]
        r = self.artifacts("register", *args)
        if must:
            assert r.returncode == 0, f"setup register {phase} {subject or ''} failed: {r.stderr.strip()[-400:]}"
        return r

    def revise(self, supersedes, report, payload=None, subject=None):
        prior = next((a for a in self.manifest()["artifacts"] if a["id"] == supersedes), {})
        self.stamp(report, prior.get("phase", "010"), subject or prior.get("subject_id"))
        args = ["--source-report", report, "--supersedes", supersedes, "--reviewer-identity", "reviewer"]
        if subject:
            args += ["--subject-id", subject]
        if payload is not None:
            args += ["--payload-json", payload if isinstance(payload, str) else self.payload(payload)]
        return self.artifacts("revise", *args)

    def chain(self, cids=(), assess=None, priorities=(), intel=True):
        """Register 010..060 (040 and/or 050 branches) and optional 070 assessments."""
        self.register("010", self.report("010"))
        self.register("020", self.report("020"))
        if intel:
            self.register("030", self.report("030"))
            self.register("040", self.report("040"), self.intel())
        for p in priorities:
            self.register("050", self.report(f"050 {p}"), subject=p)
        if cids:
            self.register("060", self.report("060"), self.triage(cids))
        for cid, (disp, fid) in (assess or {}).items():
            self.register("070", self.report(f"070 {cid}"), self.finding(cid, disp, fid), subject=cid)


def check(name, fn):
    try:
        outcome = fn()
        results.append((name, "SKIP" if outcome == "skip" else "PASS", ""))
    except Exception as exc:  # noqa: BLE001
        detail = str(exc) if isinstance(exc, AssertionError) else traceback.format_exc(limit=2)
        results.append((name, "FAIL", detail.strip()))


# ---------------------------------------------------------------------------
def reg1():
    """Runner resolves prerequisites fail-closed before emitting a prompt."""
    r = Run("reg1")
    res = r.review("020")
    assert res.returncode != 0, "runner phase 020 succeeded with no phase-010 artifact"
    assert res.stdout == "", "runner printed a prompt despite missing prerequisites"
    r.register("010", r.report("010", state="incomplete"))
    res = r.review("020")
    assert res.returncode != 0, "runner phase 020 accepted an incomplete phase-010 artifact"
    assert res.stdout == "", "runner printed a prompt for an incomplete prerequisite"


def reg2():
    """revise applies the same payload validation as register."""
    r = Run("reg2")
    r.chain(cids=["C-001"], assess={"C-001": ("confirmed", None)})
    old = r.sel("070", "C-001")
    before = r.manifest()
    res = r.revise(old, r.report("070 revised"), r.finding("C-001", commit="0" * 40), subject="C-001")
    assert res.returncode != 0, "revise accepted a 070 payload with a foreign source_commit"
    bad = r.finding("C-001")
    del bad["proposed_finding"]["title"]
    res = r.revise(old, r.report("070 revised 2"), bad, subject="C-001")
    assert res.returncode != 0, "revise accepted a 070 payload failing the nested schema"
    assert r.manifest() == before, "rejected revise changed manifest.json"


def reg3():
    """Every selected 050 priority is an input to 060; 050 skill passes the priority."""
    r = Run("reg3")
    r.chain(priorities=["auth-module", "network-layer"], intel=False)
    ids = {r.sel("050", "auth-module"), r.sel("050", "network-layer")}
    assert None not in ids, f"050 priorities not both selected: {ids}"
    res = r.review("060")
    assert res.returncode == 0, f"runner 060 failed: {res.stderr.strip()}"
    for art_id in ids:
        assert art_id in res.stdout, f"runner 060 prompt omits selected 050 input {art_id}"
    r.register("060", r.report("060"), r.triage(["C-001"]))
    prereqs = set(r.art(r.sel("060"))["prerequisite_artifacts"])
    assert ids <= prereqs, f"060 prerequisite_artifacts {prereqs} missing 050 inputs {ids - prereqs}"
    skill = open(os.path.join(EXT, "skills", "hermes-vps-050", "SKILL.md")).read()
    assert "--trigger-input <priority_area>" in skill, "050 skill does not pass the priority as trigger input"
    assert "--subject-id <priority_area>" in skill, "050 skill registers without --subject-id"


def reg4():
    """070/080 share candidate_id; 080 requires an actionable 070 and matching finding_id."""
    r = Run("reg4")
    r.chain(cids=["C-001", "C-002"],
            assess={"C-001": ("confirmed", "SG-001"), "C-002": ("dismissed", None)})
    res = r.register("080", r.report("080 C-001"), r.plan080("C-001", "SG-999"), subject="C-001", must=False)
    assert res.returncode != 0, "080 accepted finding_id that differs from the 070 proposed_finding.id"
    res = r.register("080", r.report("080 C-002"), r.plan080("C-002"), subject="C-002", must=False)
    assert res.returncode != 0, "080 accepted a dismissed 070 assessment"
    res = r.review("080", "C-099")
    assert res.returncode != 0, "runner 080 accepted a candidate outside the 060 inventory"
    r.register("080", r.report("080 C-001 ok"), r.plan080("C-001", "SG-001"), subject="C-001")
    assert r.sel("080", "C-001"), "080 plan for C-001 not selected under its candidate_id"


def reg5():
    """Full schemas, mandatory source identity, actual completion states."""
    r = Run("reg5")
    r.chain()
    res = r.register("060", r.report("060"), r.triage(["C-001"], commit="0" * 40), must=False)
    assert res.returncode != 0, "060 accepted a payload for a different source_commit"
    r.register("060", r.report("060 ok"), r.triage(["C-001"]))
    bad = r.finding("C-001")
    del bad["proposed_finding"]["title"]
    res = r.register("070", r.report("070"), bad, subject="C-001", must=False)
    assert res.returncode != 0, "070 accepted a payload missing proposed_finding.title"
    r.register("070", r.report("070 blocked", state="blocked"), r.finding("C-001", "blocked"), subject="C-001")
    status = r.art(r.sel("070", "C-001"))["completion_status"]
    assert status == "blocked", f"report declaring 'blocked' registered as {status!r}"
    res = r.review("080", "C-001")
    assert res.returncode != 0, "runner 080 accepted a blocked 070 prerequisite"
    r.artifacts("generate-findings")
    export_path = os.path.join(r.run_root, r.art(r.sel("findings"))["path"])
    export = json.load(open(export_path))
    export["source_identity"] = "someone/else"
    res = r.artifacts("validate-findings", "--findings-file", r.write_json(os.path.join(r.work, "x.json"), export))
    assert res.returncode != 0, "validate-findings accepted an export with a foreign source_identity"


def reg6():
    """Upstream revisions and report/payload hash changes invalidate downstream artifacts."""
    r = Run("reg6")
    r.chain(cids=["C-001"], assess={"C-001": ("confirmed", None)})
    res = r.revise(r.sel("060"), r.report("060 v2"), r.triage(["C-001"]))
    assert res.returncode == 0, f"setup revise 060 failed: {res.stderr.strip()[-300:]}"
    res = r.artifacts("selected", "--phase", "070")
    assert res.returncode != 0 and "superseded" in res.stdout + res.stderr, \
        "selected reports 070 usable after its 060 input was superseded"
    res = r.review("080", "C-001")
    assert res.returncode != 0, "runner 080 accepted a 070 built on a superseded 060"
    r.artifacts("generate-findings")
    export = json.load(open(os.path.join(r.run_root, r.art(r.sel("findings"))["path"])))
    assert "C-001" in export["coverage"].get("stale_assessments", []), \
        f"export did not mark C-001 stale: {export['coverage']}"
    with open(os.path.join(r.run_root, r.art(r.sel("040"))["payload_path"]), "a") as fh:
        fh.write("\n")
    res = r.review("060")
    assert res.returncode != 0, "runner 060 accepted a 040 whose payload hash changed"


def reg7():
    """OSV collection keeps package+ecosystem+version per advisory, through dedup."""
    r = Run("reg7")
    fx = os.path.join(r.work, "fixtures")
    os.makedirs(fx)
    w = lambda name, data: r.write_json(os.path.join(fx, name), data)
    w("osv-querybatch.json", {"results": [
        {"vulns": [{"id": "GHSA-1"}, {"id": "GHSA-3"}]},     # npm foo 1.0
        {"vulns": [{"id": "GHSA-1"}]},                       # npm foo-core 1.0
        {"vulns": [{"id": "PYSEC-2"}]},                      # PyPI foo 1.0
        {"vulns": [{"id": "GHSA-4"}]},                       # npm bar 2.0 (detail fetch fails)
        {"vulns": [], "next_page_token": "more"},            # npm baz 3.0 (truncated)
        {"vulns": []},                                       # npm qux 4.0 (clean)
    ]})
    aff = lambda eco, name, fixed: {"package": {"ecosystem": eco, "name": name},
                                    "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": fixed}]}]}
    w("osv-vuln-GHSA-1.json", {"id": "GHSA-1", "aliases": ["CVE-2026-1"],
                               "affected": [aff("npm", "foo", "1.1"), aff("npm", "foo-core", "1.2"),
                                            aff("PyPI", "foo", "9.9")]})
    w("osv-vuln-GHSA-3.json", {"id": "GHSA-3", "aliases": ["CVE-2026-2"], "affected": [aff("npm", "foo", "1.3")]})
    w("osv-vuln-PYSEC-2.json", {"id": "PYSEC-2", "aliases": ["CVE-2026-2"], "affected": [aff("PyPI", "foo", "1.4")]})
    pkgs = [{"ecosystem": "npm", "name": "foo", "version": "1.0"},
            {"ecosystem": "npm", "name": "foo-core", "version": "1.0"},
            {"ecosystem": "PyPI", "name": "foo", "version": "1.0"},
            {"ecosystem": "npm", "name": "bar", "version": "2.0"},
            {"ecosystem": "npm", "name": "baz", "version": "3.0"},
            {"ecosystem": "npm", "name": "qux", "version": "4.0"}]
    sys.path.insert(0, r.policy)
    for mod in [m for m in sys.modules if m == "lib" or m.startswith("lib.")]:
        del sys.modules[mod]
    from lib import hermes_vps_intel as hi
    rec = hi.run_collection(r.sha, pkgs, "live", 24.0, fixture_dir=fx)
    key = lambda m: (m["ecosystem"], m["package"], m["version"])
    by = {}
    for m in rec["matches"]:
        by.setdefault(key(m), []).append(m)
    assert ("npm", "foo-core", "1.0") in by, "second package sharing GHSA-1 lost its match"
    assert any("GHSA-1" in m["advisory_ids"] for m in by.get(("npm", "foo", "1.0"), [])), "npm foo lost GHSA-1"
    assert ("PyPI", "foo", "1.0") in by, "PyPI foo merged into npm foo via shared alias"
    npm_foo_fixed = {fv for m in by[("npm", "foo", "1.0")] for fv in m["fixed_versions"]}
    assert "9.9" not in npm_foo_fixed, "npm foo picked up the PyPI affected range of GHSA-1"
    bar = by.get(("npm", "bar", "2.0"), [])
    assert bar and bar[0].get("details_fetch_failed") is True, "failed advisory fetch dropped npm bar's match"
    osv = rec["providers"]["osv"]
    assert osv["status"] == "partial", f"OSV status {osv['status']!r} despite failed fetch / truncation"
    assert "GHSA-4" in osv.get("fetch_failed_ids", []), "fetch_failed_ids missing GHSA-4"
    assert any(p["package"] == "baz" for p in osv.get("incomplete_packages", [])), "truncated baz not recorded"
    nm = {(p["ecosystem"], p["package"], p["version"]) for p in rec["no_match_packages"]}
    assert ("npm", "baz", "3.0") not in nm, "truncated package claimed as no-match"
    assert rec["coverage"]["total_packages_checked"] == 5, \
        f"checked count {rec['coverage']['total_packages_checked']} != 5 fully answered packages"
    from lib.hermes_vps_common import load_schema, validate_schema
    validate_schema(rec, load_schema(r.policy, "vuln-intel-record.schema.json"))
    na = hi.run_collection(r.sha, pkgs, "not-authorized", 24.0)
    assert na["no_match_packages"] == [] and na["coverage"]["total_packages_checked"] == 0, \
        "not-authorized record claims packages were checked / no-match"


def reg8():
    """Destination policy: IPv4/IPv6 classes, credentials, DNS failure, rebinding, redirects."""
    import socket, urllib.request
    from unittest import mock
    r = Run("reg8")
    sys.path.insert(0, r.policy)
    for mod in [m for m in sys.modules if m == "lib" or m.startswith("lib.")]:
        del sys.modules[mod]
    from lib import hermes_vps_intel as hi
    for url in ["https://[fc00::1]/", "https://[::ffff:10.0.0.1]/", "https://100.64.0.1/",
                "https://[2001:db8::1]/", "https://224.0.0.1/", "https://0.0.0.0/",
                "https://[fe80::1]/", "https://169.254.169.254/", "https://user:pw@8.8.8.8/"]:
        try:
            hi.validate_url(url)
        except ValueError:
            continue
        raise AssertionError(f"validate_url accepted {url}")
    hi.validate_url("https://8.8.8.8/")
    with mock.patch("socket.getaddrinfo", side_effect=socket.gaierror("no dns")):
        try:
            hi.validate_url("https://api.osv.dev/")
            raise AssertionError("validate_url accepted an unresolvable host")
        except ValueError:
            pass
    private = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443))]
    public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
    with mock.patch("socket.getaddrinfo", return_value=private), \
         mock.patch("socket.create_connection", side_effect=AssertionError("connected")) as cc, \
         mock.patch("urllib.request.urlopen", side_effect=AssertionError("urlopen")):
        status, _ = hi._http_request("https://api.osv.dev/v1/querybatch", method="POST", body=b"{}")
        assert status == 0 and not cc.called, "request to privately-resolving host was attempted"
    with mock.patch("socket.getaddrinfo", side_effect=[public, private]), \
         mock.patch("socket.create_connection", side_effect=AssertionError("connected")) as cc:
        hi.validate_url("https://api.osv.dev/")
        conn = hi._PinnedHTTPSConnection("api.osv.dev", 443, timeout=1)
        try:
            conn.connect()
            raise AssertionError("connect-time rebinding to a private IP was not rejected")
        except ValueError:
            assert not cc.called, "socket opened to a rebound private address"
    opener = hi._build_opener()
    redir = next(h for h in opener.handlers if isinstance(h, urllib.request.HTTPRedirectHandler))
    req = urllib.request.Request("https://8.8.8.8/x")
    for target in ["https://169.254.169.254/latest/meta-data", "http://8.8.8.8/", "https://[::1]/"]:
        try:
            redir.redirect_request(req, None, 302, "Found", {}, target)
        except ValueError:
            continue
        raise AssertionError(f"redirect to {target} was followed")
    assert not any(isinstance(h, urllib.request.ProxyHandler) and h.proxies for h in opener.handlers), \
        "environment proxies are enabled for intel requests"


def reg9():
    """Exclusive creation, bundle-aware retries, operation-preserving shell-safe recovery."""
    r = Run("reg9 it's", run_root_name="run reg it's")
    # Exclusive creation: an existing file / symlink at the destination is never overwritten.
    victim = os.path.join(r.work, "victim.txt")
    open(victim, "w").write("victim\n")
    os.symlink(victim, os.path.join(r.run_root, "reports", "phase-010-hermes-v1.md"))
    res = r.register("010", r.report("010"), must=False)
    assert open(victim).read() == "victim\n", "register wrote through a pre-existing symlink"
    assert res.returncode != 0, "register succeeded although its destination already existed"
    os.unlink(os.path.join(r.run_root, "reports", "phase-010-hermes-v1.md"))
    if os.path.exists(os.path.join(r.run_root, "manifest.json")):
        os.unlink(os.path.join(r.run_root, "manifest.json"))
    r.chain(cids=[])
    # Bundle-aware retry: same report + different payload must not be treated as idempotent.
    rpt = r.report("060")
    r.register("060", rpt, r.triage(["C-001"]))
    count = len(r.manifest()["artifacts"])
    res = r.register("060", rpt, r.triage(["C-001", "C-002"]), must=False)
    assert res.returncode != 0, "re-register with same report but different payload reported success"
    assert len(r.manifest()["artifacts"]) == count, "rejected retry added an artifact"
    # Revise retry with identical bundle is idempotent.
    rpt2, pay2 = r.report("060 v2"), r.payload(r.triage(["C-001", "C-002"]))
    old = r.sel("060")
    assert r.revise(old, rpt2, pay2).returncode == 0, "setup revise failed"
    count = len(r.manifest()["artifacts"])
    res = r.revise(old, rpt2, pay2)
    assert res.returncode == 0 and len(r.manifest()["artifacts"]) == count, "identical revise retry not idempotent"
    res = r.revise(old, rpt2, r.triage(["C-001", "C-003"]))
    assert res.returncode != 0, "revise retry with same report but different payload reported success"
    assert len(r.manifest()["artifacts"]) == count, "rejected revise retry added an artifact"
    # Findings exports are created exclusively too.
    victim2 = os.path.join(r.work, "victim2.txt")
    open(victim2, "w").write("victim\n")
    os.symlink(victim2, os.path.join(r.run_root, "reports", "findings-v1.json"))
    res = r.artifacts("generate-findings")
    assert open(victim2).read() == "victim\n", "generate-findings replaced a pre-existing export path"
    assert res.returncode != 0, "generate-findings succeeded although findings-v1.json already existed"
    os.unlink(os.path.join(r.run_root, "reports", "findings-v1.json"))
    if os.geteuid() == 0:
        return "skip"
    # Recovery: force the manifest write to fail, then run the printed command verbatim.
    for op in ("register", "revise"):
        os.chmod(r.run_root, 0o555)
        try:
            if op == "register":
                res = r.register("070", r.report("070"), r.finding("C-001"), subject="C-001", must=False)
            else:
                res = r.revise(r.sel("070", "C-001"), r.report("070 v2"), r.finding("C-001", "suspected"),
                               subject="C-001")
        finally:
            os.chmod(r.run_root, 0o755)
        assert res.returncode != 0, f"{op}: forced write failure not reported"
        lines = res.stderr.splitlines()
        idx = next((i for i, l in enumerate(lines) if "retry" in l.lower()), None)
        assert idx is not None and idx + 1 < len(lines), f"{op}: no recovery command printed:\n{res.stderr}"
        argv = shlex.split(lines[idx + 1].strip())
        assert os.path.isabs(argv[0]) and argv[0].endswith("hermes-vps-artifacts"), f"{op}: bad binary {argv[0]}"
        assert argv[1] == op, f"{op}: recovery command changed the operation to {argv[1]!r}"
        assert argv[argv.index("--run-json") + 1] == r.run_json, f"{op}: --run-json mangled by quoting"
        assert "--payload-json" in argv and "--subject-id" in argv, f"{op}: recovery dropped arguments: {argv}"
        rerun = subprocess.run(argv, capture_output=True, text=True, env=ENV)
        assert rerun.returncode == 0, f"{op}: recovery command failed: {rerun.stderr.strip()[-300:]}"


def reg10():
    """Registering the last 070 assessment consolidates findings automatically."""
    r = Run("reg10")
    r.chain(cids=["C-001", "C-002"], assess={"C-001": ("confirmed", None)})
    assert not r.sel("findings"), "findings consolidated before all candidates were assessed"
    res = r.register("070", r.report("070 C-002"), r.finding("C-002", "dismissed"), subject="C-002")
    fid = r.sel("findings")
    assert fid, f"no findings export after the last 070 assessment:\n{res.stderr}"
    export = json.load(open(os.path.join(r.run_root, r.art(fid)["path"])))
    assert export["complete"] and not export["coverage"]["missing_assessments"], "auto export not complete"


def _header(report):
    first = open(report, encoding="utf-8").readline().rstrip("\n")
    return json.loads(first[len(HDR_PREFIX):-len(HDR_SUFFIX)])


def _restamp(report, header):
    body = open(report, encoding="utf-8").read().split("\n", 1)[1]
    with open(report, "w", encoding="utf-8") as fh:
        fh.write(HDR_PREFIX + json.dumps(header, separators=(",", ":")) + HDR_SUFFIX + "\n" + body)


def reg11():
    """Input selection changes between phase start and registration: old output is rejected."""
    r = Run("reg11")
    r.register("010", r.report("010 v1"))
    v1 = r.sel("010")
    rpt = r.report("020 analyzed v1")
    r.stamp(rpt, "020")                                   # phase start: snapshot names 010 v1
    assert [i["id"] for i in _header(rpt)["execution_inputs"]] == [v1], "runner snapshot is not 010 v1"
    res = r.revise(v1, r.report("010 v2"))                # analysis still running; v2 selected
    assert res.returncode == 0, f"setup revise 010 failed: {res.stderr.strip()[-300:]}"
    v2 = r.sel("010")
    before = r.manifest()
    res = r.register("020", rpt, must=False)              # old output
    assert res.returncode != 0, "020 registered although its analyzed input (010 v1) is no longer selected"
    assert "execution inputs changed" in res.stderr, f"unclear rejection: {res.stderr.strip()[-300:]}"
    assert r.manifest() == before, "rejected registration changed manifest.json"
    assert not any(a.get("phase") == "020" for a in r.manifest()["artifacts"]), "an 020 entry was recorded"
    assert not [n for n in os.listdir(os.path.join(r.run_root, "reports")) if "020" in n], \
        "rejected registration left 020 files in reports/"
    rpt2 = r.report("020 analyzed v2")                    # redo the phase from a fresh runner snapshot
    r.register("020", rpt2)
    entry = r.art(r.sel("020"))
    assert entry["prerequisite_artifacts"] == [v2], f"020 recorded {entry['prerequisite_artifacts']}, not [{v2}]"
    # Repeated-phase inputs: a new 050 priority selected mid-analysis also invalidates 060 output.
    r.register("050", r.report("050 a"), subject="auth-module")
    rpt060 = r.report("060")
    r.stamp(rpt060, "060")
    r.register("050", r.report("050 b"), subject="network-layer")
    res = r.register("060", rpt060, r.triage(["C-001"]), must=False)
    assert res.returncode != 0, "060 registered although a 050 priority was added after it started"


def reg12():
    """Report identity header: run, phase, subject, source identity/commit, completion state."""
    r = Run("reg12")
    plain = os.path.join(r.work, "plain.md")
    open(plain, "w").write("# 010\n\nState: `complete`\n")
    res = r.artifacts("register", "--phase", "010", "--source-report", plain)
    assert res.returncode != 0, "report without an identity header was registered"
    good = r.report("010")
    r.stamp(good, "010")
    base = _header(good)
    for key, value in [("run_id", "other-run"), ("phase", "020"), ("subject_id", "x"),
                       ("source_identity", "someone/else"), ("source_commit", "0" * 40),
                       ("completion_state", "<complete|incomplete|blocked>"), ("completion_state", "done")]:
        bad = r.report(f"010 bad {key}")
        _restamp(bad, {**base, key: value})
        res = r.artifacts("register", "--phase", "010", "--source-report", bad)
        assert res.returncode != 0, f"header with {key}={value!r} was accepted"
    contradict = r.report("010 contradict", state="incomplete")
    _restamp(contradict, {**base, "completion_state": "complete"})
    res = r.artifacts("register", "--phase", "010", "--source-report", contradict)
    assert res.returncode != 0, "body 'State: incomplete' contradicting a 'complete' header was accepted"
    assert not os.path.exists(os.path.join(r.run_root, "manifest.json")) or not r.manifest()["artifacts"], \
        "an invalid report was recorded"
    blocked = r.report("010 blocked", state="blocked")
    r.register("010", blocked)
    assert r.art(r.sel("010"))["completion_status"] == "blocked", "header completion_state not recorded"


def reg13():
    """Automatic consolidation runs inside the registering lock without re-acquiring it."""
    r = Run("reg13")
    r.chain(cids=["C-001", "C-002"], assess={"C-001": ("confirmed", None)})
    rpt, pay = r.report("070 C-002"), r.payload(r.finding("C-002", "dismissed"))
    argv = ["register", "--run-json", r.run_json, "--phase", "070", "--subject-id", "C-002",
            "--source-report", rpt, "--payload-json", pay]
    r.stamp(rpt, "070", "C-002")
    sys.path.insert(0, r.policy)
    for mod in [m for m in sys.modules if m == "lib" or m.startswith("lib.")]:
        del sys.modules[mod]
    from lib import hermes_vps_artifacts as ha
    depth, peak, entered = [0], [0], [0]
    real_enter, real_exit = ha.RunLock.__enter__, ha.RunLock.__exit__

    def enter(self):
        depth[0] += 1
        entered[0] += 1
        peak[0] = max(peak[0], depth[0])
        return real_enter(self)

    def exit_(self, *a):
        depth[0] -= 1
        return real_exit(self, *a)

    ha.RunLock.__enter__, ha.RunLock.__exit__ = enter, exit_
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = ha.main(argv)
    finally:
        ha.RunLock.__enter__, ha.RunLock.__exit__ = real_enter, real_exit
    assert rc == 0, f"register returned {rc}"
    assert r.sel("findings"), "automatic consolidation did not run"
    assert entered[0] == 1 and peak[0] == 1, f"RunLock entered {entered[0]}x, max depth {peak[0]}"
    with ha.RunLock(r.run_root):
        try:
            with ha.RunLock(r.run_root):
                raise AssertionError("nested RunLock acquisition was allowed")
        except RuntimeError:
            pass


def reg14():
    """070 registered + consolidation failure: 070 stays, failure is explicit, retry is export-only."""
    r = Run("reg14")
    r.chain(cids=["C-001", "C-002"], assess={"C-001": ("confirmed", None)})
    blocker = os.path.join(r.run_root, "reports", "findings-v1.json")
    open(blocker, "w").write("not an export\n")
    res = r.register("070", r.report("070 C-002"), r.finding("C-002", "dismissed"), subject="C-002", must=False)
    assert res.returncode == 3, f"expected exit 3 (registered, consolidation failed); got {res.returncode}"
    art_070 = r.sel("070", "C-002")
    assert art_070, "phase-070 C-002 is not registered after consolidation failed"
    assert "IS registered" in res.stderr and "consolidation FAILED" in res.stderr, \
        f"failure not explicit:\n{res.stderr}"
    assert not r.sel("findings"), "a findings export was recorded despite the failure"
    lines = res.stderr.splitlines()
    idx = next(i for i, l in enumerate(lines) if "Export-only retry" in l)
    retry = shlex.split(lines[idx + 1].strip())
    assert retry[1] == "generate-findings", f"retry is not export-only: {retry}"
    before = r.manifest()["artifacts"]
    os.unlink(blocker)
    rerun = subprocess.run(retry, capture_output=True, text=True, env=ENV)
    assert rerun.returncode == 0, f"export retry failed: {rerun.stderr.strip()[-300:]}"
    after = r.manifest()["artifacts"]
    added = after[len(before):]
    assert after[:len(before)] == before, "retry modified existing artifacts"
    assert [a["kind"] for a in added] == ["findings_export"], f"retry added {[a['kind'] for a in added]}"
    assert r.sel("070", "C-002") == art_070, "retry changed the phase-070 selection"


def reg15():
    """Instructions agree on 080 identity, payload hashes, repeated 050, stale inputs, headers."""
    docs = {}
    for sub in ("rules", "tasks", "templates", "skills"):
        for dirpath, _, files in os.walk(os.path.join(EXT, sub)):
            for name in files:
                if name.endswith(".md"):
                    docs[os.path.relpath(os.path.join(dirpath, name), EXT)] = open(os.path.join(dirpath, name)).read()
    for name in ("BOOTSTRAP.md", "README.md"):
        docs[name] = open(os.path.join(EXT, name)).read()
    stale = ['["080"][finding_id]', '["070"][finding_id]', "<finding_id>", "--subject-id SG-", "080 repoX SG-",
             '"ok": <true|false>', "If none is named"]
    hits = [f"{n}: {p}" for n, t in docs.items() for p in stale if p in t]
    assert not hits, "stale instructions: " + "; ".join(hits)
    r080 = docs["rules/rules_080-remediate-and-retest.md"]
    for need in ("candidate_id", "payload_sha256", "finding_id"):
        assert need in r080, f"rules_080 does not mention {need}"
    for n in ("rules/rules_005-report-output.md", "README.md", "BOOTSTRAP.md"):
        assert HDR_PREFIX.strip() in docs[n], f"{n} does not document the report identity header"
    assert "selected_by_subject[\"050\"]" in docs["README.md"], "README omits repeated 050 selection"
    for need in ("OSV pagination is **not implemented**", "are **not retained**"):
        assert need in docs["README.md"], f"README does not state the intelligence limitation {need!r}"
    for need in ("OSV pagination is **not implemented**", "are **not retained**"):
        assert need in docs["README.md"], f"README does not state the intelligence limitation {need!r}"


for name, fn in [("REG-1 runner fail-closed resolver", reg1),
                 ("REG-2 revise validates like register", reg2),
                 ("REG-3 all 050 priorities feed 060", reg3),
                 ("REG-4 candidate/finding/080 identity", reg4),
                 ("REG-5 schemas, source identity, completion", reg5),
                 ("REG-6 semantic upstream staleness", reg6),
                 ("REG-7 OSV package relationships", reg7),
                 ("REG-8 redirect and IPv4/IPv6 policy", reg8),
                 ("REG-9 exclusive create, retries, recovery", reg9),
                 ("REG-10 automatic consolidation", reg10),
                 ("REG-11 input change during analysis", reg11),
                 ("REG-12 machine-enforced report identity", reg12),
                 ("REG-13 consolidation does not re-acquire RunLock", reg13),
                 ("REG-14 consolidation failure: export-only recovery", reg14),
                 ("REG-15 instruction consistency", reg15)]:
    check(name, fn)

failed = 0
for name, status, detail in results:
    print(f"{status}: {name}")
    if detail:
        print("      " + detail.replace("\n", "\n      "))
    failed += status == "FAIL"
print(f"\nSummary: {sum(s == 'PASS' for _, s, _ in results)} passed, {failed} failed, "
      f"{sum(s == 'SKIP' for _, s, _ in results)} skipped")
sys.exit(1 if failed else 0)
PY
