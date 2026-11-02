"""Regressions for the 4360e32 review blockers."""
import json
import os
import shutil
import tempfile
import unittest

from support import NOW, RepoCase, write

import ca_inventory as inv
import contre_attaque
from test_review_regressions import LATER, Baseline

MALFORMED = {
    "package-lock.json": "{}",
    "npm-shrinkwrap.json": '{"lockfileVersion": 3}',
    "composer.lock": "{}",
    "Pipfile.lock": "{}",
    "go.mod": "",
    "Gemfile.lock": "",
    "yarn.lock": "",
    "pnpm-lock.yaml": "",
    "poetry.lock": "",
    "uv.lock": "",
    "Cargo.lock": "",
    "package.json": "[]",
    "Dockerfile": "# no FROM\n",
    ".github/workflows/ci.yml": "name: ci\n",
    "compose.yaml": "version: '3'\n",
}


class B1StructureValidatedBeforeAbsenceProof(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ca-struct-")
        self.imports = os.path.join(self.root, ".repo-kit", "contre-attaque", "imports")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def inventory(self):
        return inv.build_inventory(self.root, self.imports)

    def test_malformed_documents_never_prove_absence(self):
        for rel, text in MALFORMED.items():
            write(self.root, rel, text)
        data = self.inventory()
        for rel in MALFORMED:
            why = inv.absence_unproven(data, {"source": rel})
            self.assertIsNotNone(why, rel)
            self.assertRegex(why, "unexpected .* document structure|could not be parsed|unsupported|without a packages", rel)

    def test_minimal_valid_documents_prove_absence(self):
        write(self.root, "package-lock.json", json.dumps({"lockfileVersion": 3, "packages": {"": {}}}))
        write(self.root, "go.mod", "module example.com/x\n\ngo 1.22\n")
        data = self.inventory()
        self.assertIsNone(inv.absence_unproven(data, {"source": "package-lock.json"}))
        self.assertIsNone(inv.absence_unproven(data, {"source": "go.mod"}))

    def test_sbom_structure(self):
        meta = {"timestamp": "2026-11-01T00:00:00Z", "component": {"name": "api"}}
        docs = {
            "spdx.json": {"spdxVersion": "SPDX-2.3", "packages": []},
            "nolist.json": {"bomFormat": "CycloneDX", "metadata": meta},
            "badpurl.json": {"bomFormat": "CycloneDX", "metadata": meta,
                             "components": [{"purl": "pkg:npm/a@1.0.0"}, {"name": "no-purl"}]},
        }
        for name, doc in docs.items():
            write(self.imports, name, json.dumps(doc))
        data = self.inventory()
        for name in docs:
            self.assertIsNotNone(inv.absence_unproven(data, {"source": f".repo-kit/contre-attaque/imports/{name}"}), name)
        self.assertEqual([c["name"] for c in data["components"]], ["a"])


class B1EndToEnd(Baseline):
    def assert_kept_queued(self, body):
        ids = self.first_run()
        write(self.root, "package-lock.json", body)
        out = self.start("3days", now=LATER)
        cid = ids["lodash"]
        self.assertNotIn(cid, out["auto_decisions"])
        self.assertNotIn(cid, self.state()["assessments"])
        reasons = next(i["queue_reasons"] for i in out["worklist"] if i["candidate_id"] == cid)
        self.assertTrue(any("absence is not shown: package-lock.json" in r for r in reasons), reasons)
        self.assertEqual(self.state()["stale"][cid]["assessment"]["applicability"], "affected")

    def test_empty_object_lockfile_keeps_affected_package_queued(self):
        self.assert_kept_queued("{}")

    def test_lockfile_without_packages_keeps_affected_package_queued(self):
        self.assert_kept_queued('{"lockfileVersion": 3}')


class B2FailClosedWithoutSourceFingerprint(RepoCase):
    def drop_git(self):
        shutil.rmtree(os.path.join(self.root, ".git"))

    def test_start_refuses_without_git(self):
        self.drop_git()
        code, out = self.cli("start", "3days")
        self.assertEqual((code, out["status"]), (1, "source_snapshot_unavailable"))
        self.assertFalse(os.path.exists(os.path.join(self.root, ".repo-kit", "contre-attaque", "state.json")))

    def test_decide_refuses_when_git_disappears(self):
        out = self.start("3days")
        self.drop_git()
        code, err = self.decide(out["run_id"], self.item(out, "lodash")["candidate_id"], "affected",
                                "--evidence", "package-lock.json")
        self.assertEqual(code, 2)
        self.assertIn("source snapshot is unavailable", err["error"])
        state = self.state()
        self.assertEqual(state["assessments"], {})
        self.assertEqual(state["runs"][-1]["outcome"], "interrupted")

    def test_finish_refuses_and_writes_no_findings(self):
        out = self.start("3days")
        self.decide(out["run_id"], self.item(out, "lodash")["candidate_id"], "affected", "--evidence", "package-lock.json")
        before = self.findings()
        self.drop_git()
        code, err = self.cli("finish", "--run", out["run_id"])
        self.assertEqual(code, 2)
        self.assertIn("source snapshot is unavailable", err["error"])
        self.assertEqual(self.findings(), before)
        self.assertEqual(before["findings"], [])
        self.assertFalse(os.path.isdir(os.path.join(self.root, ".repo-kit", "contre-attaque", "runs", out["run_id"])))

    def test_none_equal_none_is_not_a_match(self):
        state = {"runs": []}
        run = {"run_id": "r", "outcome": "running", "git": {"commit": None, "source_fingerprint": None},
               "inventory": {"fingerprint": "f"}}
        snap = {"commit": None, "source_fingerprint": None, "inventory_fingerprint": "f"}
        saved = []
        orig = contre_attaque.st.save_state
        contre_attaque.st.save_state = lambda root, s: saved.append(s)
        try:
            with self.assertRaises(contre_attaque.UsageError):
                contre_attaque._check_snapshot(self.root, state, run, snap, contre_attaque.intel.parse_ts(NOW))
        finally:
            contre_attaque.st.save_state = orig
        self.assertEqual(run["outcome"], "interrupted")
        self.assertEqual(len(saved), 1)


if __name__ == "__main__":
    unittest.main()
