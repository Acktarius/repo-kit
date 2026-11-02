import json
import os
import unittest

from support import FakeTransport, RepoCase, deep, fixture, standard_transport, write

LATER = "2026-11-03T17:00:00Z"


class Applicability(RepoCase):
    def test_affected_justified_not_affected_and_under_investigation(self):
        out = self.start("3days")
        rid = out["run_id"]
        lodash = self.item(out, "lodash")
        requests = self.item(out, "requests")
        python = self.item(out, "python", "CVE-2026-1111")

        code, err = self.decide(rid, requests["candidate_id"], "not_affected", "--evidence", "app/server.py:4")
        self.assertEqual(code, 2)
        self.assertIn("justification", err["error"])
        code, err = self.decide(rid, requests["candidate_id"], "not_affected",
                                "--justification", "vulnerable_code_not_in_execute_path")
        self.assertEqual(code, 2)
        self.assertIn("evidence", err["error"])
        code, _ = self.decide(rid, requests["candidate_id"], "not_affected",
                              "--justification", "vulnerable_code_not_in_execute_path", "--evidence", "app/server.py:4")
        self.assertEqual(code, 0)

        code, _ = self.decide(rid, lodash["candidate_id"], "affected", "--evidence", "package-lock.json")
        self.assertEqual(code, 0)
        code, err = self.decide(rid, python["candidate_id"], "under_investigation")
        self.assertEqual(code, 2)
        code, _ = self.decide(rid, python["candidate_id"], "under_investigation",
                              "--unknown", "deployed interpreter patch level not observable")
        self.assertEqual(code, 0)

        state = self.state()
        a = state["assessments"]
        self.assertEqual(a[requests["candidate_id"]]["applicability"], "not_affected")
        self.assertEqual(a[requests["candidate_id"]]["evidence"][0]["excerpt"], "    return requests.get(url, proxies=None)")
        self.assertEqual(a[lodash["candidate_id"]]["applicability"], "affected")
        queued = {q["candidate_id"] for q in state["queue"]}
        self.assertIn(python["candidate_id"], queued)
        self.assertNotIn(lodash["candidate_id"], queued)

    def test_evidence_paths_cannot_escape_the_repo(self):
        out = self.start("3days")
        cid = self.item(out, "lodash")["candidate_id"]
        code, err = self.decide(out["run_id"], cid, "affected", "--evidence", "../outside.txt")
        self.assertEqual(code, 1)
        self.assertIn("escapes", err["error"])

    def test_news_lead_alone_is_not_sufficient(self):
        url = "https://news.example.com/lodash"
        t = standard_transport(vendor={url: b"<html>lodash exploited</html>"})
        out = self.start("3days", transport=t)
        code, fetched = self.cli("fetch-evidence", "--run", out["run_id"], "--lead", url, transport=t)
        self.assertEqual(code, 0, fetched)
        cid = self.item(out, "lodash")["candidate_id"]
        code, err = self.decide(out["run_id"], cid, "affected", "--evidence", fetched["evidence"])
        self.assertEqual(code, 2)
        self.assertIn("not sufficient", err["error"])
        code, _ = self.decide(out["run_id"], cid, "affected", "--evidence", fetched["evidence"],
                              "--evidence", "package-lock.json")
        self.assertEqual(code, 0)

    def test_runtime_vulnerability_despite_clean_library_scan(self):
        t = standard_transport(osv_index={})
        out = self.start("3days", transport=t)
        self.assertEqual(out["collection"]["providers"]["osv"]["status"], "no_match")
        py = self.item(out, "python", "CVE-2026-1111")
        self.assertEqual(py["component"]["kind"], "image")
        self.assertEqual(py["component"]["tier"], "build")
        self.assertTrue(py["version_match"])
        self.assertEqual(py["severity"], "high")
        self.assertEqual(py["window_reasons"], ["published"])
        self.assertFalse(any(i["advisory"] == "CVE-2026-2222" for i in out["worklist"]))


class AliasesAndRelationships(RepoCase):
    def test_aliases_merge_per_component_and_components_stay_separate(self):
        write(self.root, "tools/requirements.txt", "requests==2.28.0\n")
        out = self.start("3days")
        req = [i for i in out["worklist"] if i["component"]["name"] == "requests"]
        self.assertEqual(len(req), 2)
        self.assertEqual({i["component"]["source"] for i in req}, {"requirements.txt", "tools/requirements.txt"})
        for i in req:
            self.assertEqual(i["advisory"], "CVE-2023-32681")
            self.assertEqual(set(i["aliases"]), {"CVE-2023-32681", "GHSA-j8r2-6x86-q33q", "PYSEC-2023-74"})
            self.assertEqual(i["window_reasons"], ["baseline"])
        self.assertNotEqual(req[0]["candidate_id"], req[1]["candidate_id"])


class CollectionOutcome(RepoCase):
    def test_failed_collection_is_not_no_match_and_does_not_advance_checkpoints(self):
        out = self.start("3days", transport=standard_transport(fail={"osv", "nvd"}))
        self.assertEqual(out["collection"]["providers"]["osv"]["status"], "failed")
        self.assertEqual(out["collection"]["status"], "partial")
        cp = self.state()["checkpoints"]
        self.assertIsNone(cp["osv"])
        self.assertIsNone(cp["nvd"])
        self.assertIsNotNone(cp["kev"])
        code, handoff = self.cli("finish", "--run", out["run_id"])
        self.assertEqual(code, 0)
        self.assertIn("Coverage: INCOMPLETE", handoff)
        self.assertIn("osv: failed (live)", handoff)

    def test_window_gap_reported_after_prior_checkpoint(self):
        out = self.start("3days")
        self.cli("finish", "--run", out["run_id"])
        out = self.start("1day", now="2026-11-10T17:00:00Z")
        self.assertTrue(any("never collected" in g for g in out["collection"]["window_gaps"]))

    def test_old_cve_newly_added_to_kev_is_flagged_and_reassessed(self):
        out = self.start("3days")
        cid = self.item(out, "requests")["candidate_id"]
        self.decide(out["run_id"], cid, "not_affected", "--justification", "vulnerable_code_not_in_execute_path",
                    "--evidence", "app/server.py:4")
        self.cli("finish", "--run", out["run_id"])
        kev = fixture("kev.json")
        kev["vulnerabilities"].append({"cveID": "CVE-2023-32681", "vendorProject": "Python", "product": "Requests",
                                       "vulnerabilityName": "x", "dateAdded": "2026-11-03"})
        out = self.start("3days", transport=standard_transport(kev=kev), now=LATER)
        item = self.item(out, "requests")
        self.assertIn("kev_added", item["window_reasons"])
        self.assertIn("KEV exploitation status changed", item["queue_reasons"])
        self.assertEqual(out["worklist"][0]["candidate_id"], cid)


class CacheReuse(RepoCase):
    def first_run(self):
        out = self.start("3days")
        rid = out["run_id"]
        ids = {i["component"]["name"]: i["candidate_id"] for i in out["worklist"]}
        self.decide(rid, ids["requests"], "not_affected", "--justification", "vulnerable_code_not_in_execute_path",
                    "--evidence", "app/server.py:4")
        self.decide(rid, ids["lodash"], "affected", "--evidence", "package-lock.json")
        self.decide(rid, ids["python"], "under_investigation", "--unknown", "runtime patch level unknown")
        self.cli("finish", "--run", rid)
        return ids

    def test_safe_reuse_when_nothing_changed(self):
        ids = self.first_run()
        out = self.start("3days", now=LATER)
        names = {i["component"]["name"] for i in out["worklist"]}
        self.assertEqual(names, {"python"}, "only under_investigation is re-queued")
        self.assertEqual(out["reused_decisions"], 2)
        self.assertNotIn(ids["requests"], [i["candidate_id"] for i in out["worklist"]])

    def test_code_change_invalidates(self):
        ids = self.first_run()
        write(self.root, "app/server.py", "import requests\n\ndef fetch(url, p):\n    return requests.get(url, proxies=p)\n")
        out = self.start("3days", now=LATER)
        item = next(i for i in out["worklist"] if i["candidate_id"] == ids["requests"])
        self.assertIn("cited evidence changed: app/server.py", item["queue_reasons"])
        self.assertEqual(item["prior_decision"]["applicability"], "not_affected")

    def test_advisory_revision_invalidates(self):
        ids = self.first_run()
        vulns = fixture("osv-vulns.json")
        vulns["GHSA-j8r2-6x86-q33q"]["modified"] = "2026-11-03T01:00:00Z"
        vulns["GHSA-j8r2-6x86-q33q"]["affected"][0]["ranges"][0]["events"][1]["fixed"] = "2.32.0"
        out = self.start("3days", transport=standard_transport(osv_vulns=vulns), now=LATER)
        item = next(i for i in out["worklist"] if i["candidate_id"] == ids["requests"])
        self.assertIn("advisory revision changed", item["queue_reasons"])
        self.assertEqual(item["window_reasons"], ["modified"])

    def test_deployment_change_invalidates(self):
        ids = self.first_run()
        write(self.root, "Dockerfile", "FROM python:3.11.4-slim\nENV HTTPS_PROXY=http://proxy\n")
        out = self.start("3days", now=LATER)
        reasons = {i["candidate_id"]: i["queue_reasons"] for i in out["worklist"]}
        self.assertIn("runtime, image, SBOM, or deployment configuration changed", reasons[ids["requests"]])

    def test_max_cache_age(self):
        ids = self.first_run()
        out = self.start("3days", now="2026-12-10T17:00:00Z")
        reasons = {i["candidate_id"]: i["queue_reasons"] for i in out["worklist"]}
        self.assertTrue(any("30-day" in r for r in reasons[ids["requests"]]))

    def test_kev_unknown_prevents_reuse(self):
        ids = self.first_run()
        out = self.start("3days", transport=standard_transport(fail={"kev"}), now=LATER)
        reasons = {i["candidate_id"]: i["queue_reasons"] for i in out["worklist"]}
        self.assertIn("exploitation status unknown this run (KEV not collected)", reasons[ids["requests"]])

    def test_version_bump_auto_fixed_by_provider_evidence(self):
        ids = self.first_run()
        write(self.root, "package-lock.json", json.dumps({"lockfileVersion": 3, "packages": {
            "": {}, "node_modules/lodash": {"version": "4.17.21"}}}))
        out = self.start("3days", now=LATER)
        self.assertIn(ids["lodash"], out["auto_decisions"])
        a = self.state()["assessments"][ids["lodash"]]
        self.assertEqual(a["applicability"], "fixed")
        self.assertEqual(a["decided_by"], "helper")
        self.assertEqual(a["history"][-1]["applicability"], "affected")


class PersistentQueue(RepoCase):
    def test_cap_persists_and_resumes_remaining_items(self):
        vulns = deep(fixture("osv-vulns.json"))
        index = {}
        lock = {"": {}}
        for n in range(30):
            vid = f"GHSA-test-{n:04d}"
            vulns[vid] = {"id": vid, "aliases": [f"CVE-2026-{5000 + n}"], "published": "2024-01-01T00:00:00Z",
                          "modified": "2024-01-01T00:00:00Z", "database_specific": {"severity": "LOW"},
                          "affected": [{"package": {"ecosystem": "npm", "name": f"pkg{n}"}}]}
            index[("npm", f"pkg{n}", "1.0.0")] = [vid]
            lock[f"node_modules/pkg{n}"] = {"version": "1.0.0"}
        write(self.root, "package-lock.json", json.dumps({"lockfileVersion": 3, "packages": lock}))
        t = FakeTransport(osv_index=index, osv_vulns=vulns, nvd_items=[])
        out = self.start("3days", transport=t)
        self.assertEqual(len(out["worklist"]), 25)
        self.assertEqual(out["queued_beyond_this_run"], 5)
        first = {i["candidate_id"] for i in out["worklist"]}
        code, handoff = self.cli("finish", "--run", out["run_id"])
        self.assertIn("30 candidate(s) still queued", handoff)
        out2 = self.start("3days", transport=t, now=LATER)
        second = [i["candidate_id"] for i in out2["worklist"]]
        self.assertEqual(len(set(second[:5]) - first), 5, "never-attempted items are served first")
        self.assertEqual(out2["queued_total"], 30)


if __name__ == "__main__":
    unittest.main()
