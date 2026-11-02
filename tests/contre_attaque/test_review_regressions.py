"""Regressions for the 880fd0c review findings (one class per finding)."""
import json
import os
import subprocess
import unittest

from support import RepoCase, deep, fixture, standard_transport, write

import ca_intel
import ca_report
import ca_state

LATER = "2026-11-03T17:00:00Z"
LOCK_WITHOUT_LODASH = json.dumps({"lockfileVersion": 3, "packages": {"": {}, "node_modules/other": {"version": "1.0.0"}}})


class Baseline(RepoCase):
    """First run: lodash affected, requests not_affected (code path), python under_investigation."""

    def first_run(self):
        out = self.start("3days")
        rid = out["run_id"]
        ids = {i["component"]["name"]: i["candidate_id"] for i in out["worklist"]}
        self.assertEqual(self.decide(rid, ids["lodash"], "affected", "--evidence", "package-lock.json")[0], 0)
        self.assertEqual(self.decide(rid, ids["requests"], "not_affected", "--justification",
                                     "vulnerable_code_not_in_execute_path", "--evidence", "app/server.py:4")[0], 0)
        self.decide(rid, ids["python"], "under_investigation", "--unknown", "runtime patch level unknown")
        self.assertEqual(self.cli("finish", "--run", rid)[0], 0)
        return ids

    def reasons(self, out):
        return {i["candidate_id"]: i["queue_reasons"] for i in out["worklist"]}


class R1IncompleteInventoryNeverImpliesNotPresent(Baseline):
    def assert_unproven(self, cid, out, fragment):
        self.assertNotIn(cid, out["auto_decisions"])
        self.assertNotIn(cid, self.state()["assessments"])
        self.assertTrue(any("absence is not shown" in r and fragment in r for r in self.reasons(out)[cid]),
                        self.reasons(out).get(cid))

    def test_unparseable_lockfile(self):
        ids = self.first_run()
        write(self.root, "package-lock.json", "{ not json")
        self.assert_unproven(ids["lodash"], self.start("3days", now=LATER), "could not be parsed")

    def test_deleted_lockfile(self):
        ids = self.first_run()
        os.remove(os.path.join(self.root, "package-lock.json"))
        self.assert_unproven(ids["lodash"], self.start("3days", now=LATER), "no longer present")

    def test_unpinned_requirement(self):
        ids = self.first_run()
        write(self.root, "requirements.txt", "requests>=2\n")
        self.assert_unproven(ids["requests"], self.start("3days", now=LATER), "unresolved entries")

    def test_complete_parse_without_component_is_shown_absent(self):
        ids = self.first_run()
        write(self.root, "package-lock.json", LOCK_WITHOUT_LODASH)
        out = self.start("3days", now=LATER)
        self.assertIn(ids["lodash"], out["auto_decisions"])
        a = self.state()["assessments"][ids["lodash"]]
        self.assertEqual((a["applicability"], a["justification"]), ("not_affected", "component_not_present"))
        self.assertEqual(a["evidence"][1]["path"], "package-lock.json")


class R2SourceChangesInvalidateCodeDependentDecisions(Baseline):
    def test_uncited_source_file_change(self):
        ids = self.first_run()
        write(self.root, "app/new_handler.py", "import requests\nrequests.get(u, proxies=p)\n")
        reasons = self.reasons(self.start("3days", now=LATER))
        for name in ("requests", "lodash"):
            self.assertIn("repository source changed since this code-dependent decision", reasons[ids[name]])

    def test_committed_change_also_invalidates(self):
        ids = self.first_run()
        write(self.root, "app/util.py", "x = 1\n")
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "util"], cwd=self.root, check=True, capture_output=True)
        self.assertIn(ids["requests"], self.reasons(self.start("3days", now=LATER)))

    def test_review_records_are_not_source(self):
        self.first_run()
        with open(os.path.join(self.root, "security", "accepted-risks.md"), "a", encoding="utf-8") as fh:
            fh.write("\nreviewed\n")
        out = self.start("3days", now=LATER)
        self.assertEqual(out["reused_decisions"], 2)

    def test_version_only_decisions_ignore_source_changes(self):
        ids = self.first_run()
        write(self.root, "package-lock.json", LOCK_WITHOUT_LODASH)
        out = self.start("3days", now=LATER)
        self.cli("finish", "--run", out["run_id"], now=LATER)
        write(self.root, "app/util.py", "x = 1\n")
        out = self.start("3days", now="2026-11-04T17:00:00Z")
        self.assertNotIn(ids["lodash"], self.reasons(out))


class R3StaleDecisionsAreNotCurrent(Baseline):
    def test_invalidated_affected_is_not_synced_or_handed_off_as_current(self):
        ids = self.first_run()
        before = self.findings()
        self.assertEqual([r["id"] for r in before["findings"]], ["SG-001"])
        write(self.root, "app/new_handler.py", "pass\n")
        out = self.start("3days", now=LATER)
        state = self.state()
        self.assertNotIn(ids["lodash"], state["assessments"])
        self.assertEqual(state["stale"][ids["lodash"]]["assessment"]["applicability"], "affected")
        prior = self.item(out, "lodash")["prior_decision"]
        self.assertEqual(prior["note"], "historical only; not a current decision")
        self.assertIn("repository source changed since this code-dependent decision", prior["invalidated_because"])
        code, handoff = self.cli("finish", "--run", out["run_id"], now=LATER)
        self.assertEqual(code, 0)
        self.assertEqual(self.findings(), before)
        self.assertIn("## Work items (0 affected)", handoff)
        self.assertIn(f"- {ids['lodash']} CVE-2020-28500 × lodash (SG-001 not refreshed): was affected", handoff)
        self.assertNotIn("test rationale for affected", handoff)

    def test_new_decision_replaces_stale(self):
        ids = self.first_run()
        write(self.root, "app/new_handler.py", "pass\n")
        out = self.start("3days", now=LATER)
        self.decide(out["run_id"], ids["lodash"], "affected", "--evidence", "package-lock.json", now=LATER)
        state = self.state()
        self.assertNotIn(ids["lodash"], state["stale"])
        self.assertEqual(state["assessments"][ids["lodash"]]["history"][-1]["applicability"], "affected")


class R4SnapshotsVerifiedAtDecideAndFinish(RepoCase):
    def test_source_change_before_decide_interrupts_run(self):
        out = self.start("3days")
        write(self.root, "app/server.py", "changed\n")
        code, err = self.decide(out["run_id"], self.item(out, "lodash")["candidate_id"], "affected",
                                "--evidence", "package-lock.json")
        self.assertEqual(code, 2)
        self.assertIn("repository source files", err["error"])
        run = self.state()["runs"][-1]
        self.assertEqual(run["outcome"], "interrupted")
        self.assertIn("inputs changed during the run", run["interrupted_reason"])
        self.assertEqual(self.state()["assessments"], {})

    def test_inventory_change_before_finish_blocks_sync(self):
        out = self.start("3days")
        self.decide(out["run_id"], self.item(out, "lodash")["candidate_id"], "affected", "--evidence", "package-lock.json")
        imports = os.path.join(self.root, ".repo-kit", "contre-attaque", "imports")
        write(imports, "sbom.json", json.dumps({"bomFormat": "CycloneDX", "metadata": {
            "timestamp": "2026-11-02T00:00:00Z", "component": {"name": "api"}}, "components": []}))
        code, err = self.cli("finish", "--run", out["run_id"])
        self.assertEqual(code, 2)
        self.assertIn("component inventory", err["error"])
        self.assertEqual(self.findings()["findings"], [])
        self.assertFalse(os.path.isdir(os.path.join(self.root, ".repo-kit", "contre-attaque", "runs", out["run_id"])))


class R5RunAndWorklistMembership(Baseline):
    def test_decide_rejects_candidates_outside_the_run_worklist(self):
        ids = self.first_run()
        out = self.start("3days", now=LATER)
        self.assertNotIn(ids["lodash"], [i["candidate_id"] for i in out["worklist"]])
        code, err = self.decide(out["run_id"], ids["lodash"], "not_affected", "--justification",
                                "vulnerable_code_not_present", "--evidence", "package-lock.json", now=LATER)
        self.assertEqual(code, 2)
        self.assertIn("not in run", err["error"])
        self.assertEqual(self.state()["assessments"][ids["lodash"]]["applicability"], "affected")

    def test_completed_run_cannot_take_decisions(self):
        out = self.start("3days")
        self.cli("finish", "--run", out["run_id"])
        code, err = self.decide(out["run_id"], self.item(out, "lodash")["candidate_id"], "affected",
                                "--evidence", "package-lock.json")
        self.assertEqual(code, 2)
        self.assertIn("completed", err["error"])

    def test_second_start_cannot_touch_the_active_run(self):
        out = self.start("3days")
        before = self.state()
        code, busy = self.cli("start", "1day", transport=standard_transport())
        self.assertEqual((code, busy["status"]), (1, "run_in_progress"))
        self.assertEqual(self.state(), before)


class R6InventoryGapsMakeCoverageIncomplete(RepoCase):
    def run_shape(self, gaps):
        live = {"status": "success", "mode": "live"}
        return {"collection": {"providers": {"osv": live, "nvd": live, "kev": live}, "window_gaps": []},
                "inventory": {"gaps": gaps}, "assessment": {"pending_after_run": 0}}

    def test_reasons(self):
        self.assertEqual(ca_report.incomplete_reasons({}, self.run_shape([])), [])
        self.assertEqual(ca_report.incomplete_reasons({}, self.run_shape(["x.lock: could not be parsed"])),
                         ["inventory: x.lock: could not be parsed"])

    def test_handoff_reports_inventory_gap(self):
        write(self.root, "requirements.txt", "requests==2.28.0\nflask>=2\n")
        out = self.start("3days")
        _, handoff = self.cli("finish", "--run", out["run_id"])
        self.assertIn("- inventory: requirements.txt: unpinned requirements (no resolved version): flask", handoff)
        self.assertFalse(self.state()["runs"][-1]["coverage_complete"])


class R7ProviderEvidenceUsableByDecide(RepoCase):
    def test_worklist_evidence_refs_are_accepted(self):
        out = self.start("3days")
        for name in ("lodash", "python"):
            item = self.item(out, name)
            self.assertTrue(item["evidence_refs"])
            code, res = self.decide(out["run_id"], item["candidate_id"], "affected", "--evidence", item["evidence_refs"][0])
            self.assertEqual(code, 0, res)
        a = self.state()["assessments"]
        self.assertEqual(a[self.item(out, "lodash")["candidate_id"]]["evidence"][0]["provider"], "osv")
        self.assertEqual(a[self.item(out, "python")["candidate_id"]]["evidence"][0]["provider"], "nvd")

    def test_unknown_evidence_is_rejected(self):
        out = self.start("3days")
        code, err = self.decide(out["run_id"], self.item(out, "lodash")["candidate_id"], "affected",
                                "--evidence", "evidence:" + "0" * 64)
        self.assertEqual(code, 2)
        self.assertIn("not stored evidence", err["error"])


class R8HumanOwnershipIncludesLastReviewedAndSource(RepoCase):
    def edit_then_rerun(self, field, value):
        out = self.start("3days")
        cid = self.item(out, "lodash")["candidate_id"]
        self.decide(out["run_id"], cid, "affected", "--evidence", "package-lock.json")
        self.cli("finish", "--run", out["run_id"])
        doc = self.findings()
        doc["findings"][0][field] = value
        with open(os.path.join(self.root, "security", "findings-reviewed.json"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        vulns = fixture("osv-vulns.json")
        vulns["GHSA-29mw-wpgm-hmr9"]["modified"] = "2026-11-03T02:00:00Z"
        out = self.start("3days", transport=standard_transport(osv_vulns=vulns), now=LATER)
        self.decide(out["run_id"], cid, "affected", "--evidence", "package-lock.json", now=LATER)
        _, handoff = self.cli("finish", "--run", out["run_id"], now=LATER)
        self.assertEqual(self.findings(), doc)
        self.assertIn("SG-001 was edited by a human; agent update not applied", handoff)

    def test_last_reviewed(self):
        self.edit_then_rerun("lastReviewed", "2026-11-02")

    def test_source(self):
        self.edit_then_rerun("source", "manual review (took over from contre-attaque)")


class R9NoFixVersionsFromOtherBranches(RepoCase):
    RECORD = {"affected": [{"package": {"ecosystem": "npm", "name": "lib"}, "ranges": [{"type": "SEMVER", "events": [
        {"introduced": "2.0.0"}, {"fixed": "2.5.3"}, {"introduced": "3.0.0"}, {"fixed": "3.1.2"}]}]}]}

    def test_only_the_containing_interval(self):
        comp = {"name": "lib", "ecosystem": "npm"}
        self.assertEqual(ca_intel.osv_fixed_versions(self.RECORD, {**comp, "version": "2.4.0"}), ["2.5.3"])
        self.assertEqual(ca_intel.osv_fixed_versions(self.RECORD, {**comp, "version": "3.0.5"}), ["3.1.2"])
        self.assertEqual(ca_intel.osv_fixed_versions(self.RECORD, {**comp, "version": "not-a-version"}), [])
        self.assertEqual(ca_intel.osv_fixed_versions(self.RECORD, {**comp, "version": "2.4.0", "ecosystem": "PyPI"}), [])

    def test_maintenance_branch_fix_is_not_recommended(self):
        vulns = deep(fixture("osv-vulns.json"))
        vulns["GHSA-29mw-wpgm-hmr9"]["affected"][0]["ranges"][0]["events"] = [
            {"introduced": "0"}, {"fixed": "3.10.2"}, {"introduced": "4.0.0"}, {"fixed": "4.17.21"}]
        out = self.start("3days", transport=standard_transport(osv_vulns=vulns))
        item = self.item(out, "lodash")
        self.assertEqual(item["fixed_versions"], ["4.17.21"])

    def test_disagreeing_sources_leave_mitigation_unknown(self):
        vulns = deep(fixture("osv-vulns.json"))
        vulns["PYSEC-2023-74"]["affected"][0]["ranges"][0]["events"][1]["fixed"] = "2.31.1"
        out = self.start("3days", transport=standard_transport(osv_vulns=vulns))
        cid = self.item(out, "requests")["candidate_id"]
        self.decide(out["run_id"], cid, "affected", "--evidence", "requirements.txt")
        _, handoff = self.cli("finish", "--run", out["run_id"])
        self.assertIn(f"Proposed mitigation: {ca_report.UNKNOWN_MITIGATION}", handoff)
        self.assertIn("different fixed versions for the range containing 2.28.0: 2.31.0, 2.31.1", handoff)
        rec = self.findings()["findings"][0]
        self.assertIsNone(rec["remediation"])


class GitStatusParsing(RepoCase):
    def test_first_dirty_path_is_not_truncated(self):
        write(self.root, "Dockerfile", "FROM python:3.11.4-slim\n")
        self.assertEqual(ca_state.git_info(self.root)["dirty_paths"], ["Dockerfile"])


if __name__ == "__main__":
    unittest.main()
