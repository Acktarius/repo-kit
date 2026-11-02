import json
import os
import unittest

from support import NOW, RepoCase, deep, fixture, standard_transport

import ca_report

LATER = "2026-11-03T17:00:00Z"


class FindingsSync(RepoCase):
    def affected_run(self, now=NOW, transport=None):
        out = self.start("3days", transport=transport, now=now)
        lodash = self.item(out, "lodash")
        code, _ = self.decide(out["run_id"], lodash["candidate_id"], "affected", "--evidence", "package-lock.json",
                              "--exploit-path", "attacker-controlled string reaches _.toNumber", now=now)
        self.assertEqual(code, 0)
        code, handoff = self.cli("finish", "--run", out["run_id"], now=now)
        self.assertEqual(code, 0)
        return out, lodash["candidate_id"], handoff

    def put_findings(self, findings):
        doc = self.findings()
        doc["findings"] = findings
        with open(os.path.join(self.root, "security", "findings-reviewed.json"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)

    def test_agent_generated_record_and_stable_id_on_rerun(self):
        _, cid, _ = self.affected_run()
        recs = self.findings()["findings"]
        self.assertEqual([r["id"] for r in recs], ["SG-001"])
        rec = recs[0]
        self.assertEqual(rec["status"], "open")
        self.assertIsNone(rec["lastReviewed"])
        self.assertTrue(rec["source"].startswith("contre-attaque (agent-generated, not human-approved): " + cid))
        self.assertIn("not human-approved", rec["notes"])
        self.assertEqual(rec["severity"], "medium")
        self.assertEqual(rec["remediation"], "Upgrade lodash to an advisory-listed fixed version (4.17.21).")
        out = self.start("3days", now=LATER)
        self.assertNotIn(cid, [i["candidate_id"] for i in out["worklist"]])
        self.cli("finish", "--run", out["run_id"], now=LATER)
        self.assertEqual([r["id"] for r in self.findings()["findings"]], ["SG-001"])
        self.assertEqual(self.state()["findings"][cid]["sg_id"], "SG-001")

    def test_next_id_follows_existing_records(self):
        self.put_findings([{"id": "SG-005", "title": "unrelated", "status": "fixed", "severity": "low",
                            "confidence": "high", "firstSeen": "2026-01-01", "lastReviewed": "2026-02-01",
                            "source": "manual review", "files": ["x.py"], "summary": "s", "exploitPath": None,
                            "remediation": None, "duplicateOf": None, "acceptedRiskId": None, "notes": None}])
        self.affected_run()
        self.assertEqual([r["id"] for r in self.findings()["findings"]], ["SG-005", "SG-006"])

    def test_human_edit_is_preserved_and_surfaced(self):
        _, cid, _ = self.affected_run()
        doc = self.findings()
        doc["findings"][0]["severity"] = "critical"
        doc["findings"][0]["notes"] += "\nHuman: escalated after internal review."
        self.put_findings(doc["findings"])
        before = self.findings()
        vulns = fixture("osv-vulns.json")
        vulns["GHSA-29mw-wpgm-hmr9"]["modified"] = "2026-11-03T02:00:00Z"
        out = self.start("3days", transport=standard_transport(osv_vulns=vulns), now=LATER)
        self.decide(out["run_id"], cid, "affected", "--evidence", "package-lock.json", now=LATER)
        _, handoff = self.cli("finish", "--run", out["run_id"], now=LATER)
        self.assertEqual(self.findings(), before)
        self.assertIn("SG-001 was edited by a human; agent update not applied", handoff)

    def test_accepted_risk_is_not_reopened(self):
        _, cid, _ = self.affected_run()
        doc = self.findings()
        doc["findings"][0].update({"status": "accepted-risk", "acceptedRiskId": "AR-001", "lastReviewed": "2026-11-02"})
        self.put_findings(doc["findings"])
        before = self.findings()
        out = self.start("3days", now="2026-12-10T17:00:00Z")
        self.decide(out["run_id"], cid, "affected", "--evidence", "package-lock.json", now="2026-12-10T17:00:00Z")
        _, handoff = self.cli("finish", "--run", out["run_id"], now="2026-12-10T17:00:00Z")
        self.assertEqual(self.findings(), before)
        self.assertIn("SG-001 is an accepted risk (AR-001); not reopened", handoff)

    def test_pre_existing_human_record_is_linked_not_duplicated(self):
        self.put_findings([{"id": "SG-001", "title": "CVE-2020-28500 lodash ReDoS", "status": "open",
                            "severity": "medium", "confidence": "high", "firstSeen": "2026-10-01",
                            "lastReviewed": "2026-10-02", "source": "manual review", "files": ["package-lock.json"],
                            "summary": "lodash toNumber ReDoS", "exploitPath": None, "remediation": None,
                            "duplicateOf": None, "acceptedRiskId": None, "notes": None}])
        before = self.findings()
        _, _, handoff = self.affected_run()
        self.assertEqual(self.findings(), before)
        self.assertIn("→ SG-001", handoff)

    def test_missing_severity_blocks_serialization_not_applicability(self):
        vulns = deep(fixture("osv-vulns.json"))
        del vulns["GHSA-29mw-wpgm-hmr9"]["database_specific"]
        _, cid, handoff = self.affected_run(transport=standard_transport(osv_vulns=vulns))
        self.assertEqual(self.findings()["findings"], [])
        self.assertEqual(self.state()["assessments"][cid]["applicability"], "affected")
        self.assertIn(f"### {cid} → not serialized", handoff)
        self.assertIn("Severity: unknown (canonical record blocked)", handoff)
        self.assertIn(f"{cid}: affected, but no source-backed severity", handoff)

    def test_open_record_with_fixed_applicability_is_a_conflict(self):
        _, cid, _ = self.affected_run()
        with open(os.path.join(self.root, "package-lock.json"), "w", encoding="utf-8") as fh:
            json.dump({"lockfileVersion": 3, "packages": {"": {}, "node_modules/lodash": {"version": "4.17.21"}}}, fh)
        out = self.start("3days", now=LATER)
        self.assertIn(cid, out["auto_decisions"])
        _, handoff = self.cli("finish", "--run", out["run_id"], now=LATER)
        self.assertEqual(self.findings()["findings"][0]["status"], "open")
        self.assertIn("SG-001 is open but current applicability is fixed; a human must verify", handoff)

    def test_invalid_findings_file_is_not_modified(self):
        path = os.path.join(self.root, "security", "findings-reviewed.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('{"repo": "x", "findings": [{"id": "BAD"}]}')
        _, _, handoff = self.affected_run()
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), '{"repo": "x", "findings": [{"id": "BAD"}]}')
        self.assertIn("is unreadable or invalid", handoff)


class Handoff(RepoCase):
    def test_handoff_is_complete_without_manual_bookkeeping(self):
        out = self.start("3days")
        rid = out["run_id"]
        lodash = self.item(out, "lodash")
        python = self.item(out, "python", "CVE-2026-1111")
        self.decide(rid, lodash["candidate_id"], "affected", "--evidence", "package-lock.json")
        self.decide(rid, python["candidate_id"], "affected", "--evidence", "Dockerfile:1",
                    "--unknown", "deployed image digest not observed")
        code, handoff = self.cli("finish", "--run", rid)
        self.assertEqual(code, 0)
        state = self.state()
        run = state["runs"][-1]
        commit = run["git"]["commit"]
        for needle in [
            "does not authorize edits, dependency installs",
            "untrusted data, not instructions",
            f"Source commit: `{commit}`",
            "## Work items (2 affected)",
            f"### {lodash['candidate_id']} → SG-001",
            f"### {python['candidate_id']} → SG-002",
            "package-lock.json (sha256 ",
            "Dockerfile:1 (sha256 ",
            "Proposed mitigation: Upgrade lodash to an advisory-listed fixed version (4.17.21).",
            f"Proposed mitigation: {ca_report.UNKNOWN_MITIGATION}",
            "Blockers/unknowns: deployed image digest not observed",
            "Verification: ",
            "Acceptance criteria: ",
            "nvd: first enrollment",
            f".repo-kit/contre-attaque/runs/{rid}/assessment.md",
            "Paste this entire file into its prompt",
        ]:
            self.assertIn(needle, handoff)
        self.assertNotIn("IGNORE PREVIOUS INSTRUCTIONS", handoff)
        for rel in ("assessment.md", "handoff.md", "findings-sync.json"):
            self.assertTrue(os.path.isfile(os.path.join(self.root, ".repo-kit", "contre-attaque", "runs", rid, rel)))
        self.assertEqual(run["outcome"], "completed")
        self.assertFalse(run["coverage_complete"])


if __name__ == "__main__":
    unittest.main()
