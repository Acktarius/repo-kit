"""Regressions for the 1f89f7f review: listed-but-unresolved entries and unsupported lockfile versions."""
import json
import os
import shutil
import tempfile
import unittest

from support import RepoCase, write

import ca_inventory as inv
from test_review_regressions import LATER, Baseline

REGISTRY = 'source = { registry = "https://pypi.org/simple" }'

UNRESOLVED = {
    "package-lock.json": json.dumps({"lockfileVersion": 3, "packages": {"": {}, "node_modules/lodash": {}}}),
    "npm-shrinkwrap.json": json.dumps({"lockfileVersion": 1, "dependencies": {"lodash": {"resolved": "x"}}}),
    "pnpm-lock.yaml": "lockfileVersion: '9.0'\npackages:\n  lodash@github.com/x/y:\n    resolution: {}\n",
    "yarn.lock": '# yarn lockfile v1\n\nlodash@^4.0.0:\n  resolved "https://x"\n',
    "poetry.lock": '[[package]]\nname = "django"\n\n[metadata]\nlock-version = "2.0"\n',
    "uv.lock": f'version = 1\n\n[[package]]\nname = "flask"\n{REGISTRY}\n',
    "Cargo.lock": 'version = 4\n\n[[package]]\nname = "serde"\nsource = "registry+https://github.com/rust-lang/crates.io-index"\n',
    "Pipfile.lock": json.dumps({"_meta": {"pipfile-spec": 6}, "default": {"requests": {"git": "https://x"}}}),
    "composer.lock": json.dumps({"packages": [{"name": "monolog/monolog"}]}),
    "Gemfile.lock": "GEM\n  remote: https://rubygems.org/\n  specs:\n    rack\n\nPLATFORMS\n  ruby\n",
    "go.mod": "module example.com/x\n\nrequire (\n\tgithub.com/a/b\n)\n",
    "requirements.txt": "-e git+https://example.com/x.git#egg=foo\n",
    "Dockerfile": "FROM debian:bookworm\nRUN apt-get install -y $PKGS\n",
}

UNSUPPORTED = {
    "package-lock.json": json.dumps({"lockfileVersion": 4, "packages": {"": {}}}),
    "pnpm-lock.yaml": "lockfileVersion: '10.0'\npackages: {}\n",
    "yarn.lock": "# yarn lockfile v2\n",
    "berry/yarn.lock": "__metadata:\n  version: 99\n",
    "poetry.lock": '[metadata]\nlock-version = "3.0"\n',
    "uv.lock": "version = 2\n\n[[package]]\nname = \"app\"\n",
    "Cargo.lock": "version = 5\n\n[[package]]\nname = \"app\"\n",
    "Pipfile.lock": json.dumps({"_meta": {"pipfile-spec": 7}, "default": {}}),
}


class UnresolvedEntriesAreGaps(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ca-unres-")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def check(self, docs, pattern):
        for i, (rel, text) in enumerate(docs.items()):
            write(self.root, f"case{i}/{rel}", text)
        data = inv.build_inventory(self.root)
        for i, rel in enumerate(docs):
            src = os.path.normpath(f"case{i}/{rel}")
            why = inv.absence_unproven(data, {"source": src})
            self.assertIsNotNone(why, src)
            self.assertRegex(why, pattern, src)
            self.assertTrue(any(g.startswith(src) for g in data["gaps"]), src)
        return data

    def test_listed_entries_without_resolution_never_prove_absence(self):
        data = self.check(UNRESOLVED, "unresolved entries")
        self.assertTrue(any("node_modules/lodash" in g for g in data["gaps"]))
        self.assertNotIn("lodash", {c["name"] for c in data["components"]})

    def test_unsupported_lockfile_versions_are_rejected(self):
        data = self.check(UNSUPPORTED, "unsupported")
        self.assertEqual([c for c in data["components"] if c["kind"] == "library"], [])


class ListedEntryLosesVersionEndToEnd(Baseline):
    def test_previously_affected_lodash_stays_queued(self):
        ids = self.first_run()
        cid = ids["lodash"]
        for body in ({"node_modules/lodash": {}},
                     {"node_modules/lodash": {"version": ""}},
                     {"node_modules/lodash": {"resolved": "https://registry.npmjs.org/lodash/-/lodash.tgz"}}):
            write(self.root, "package-lock.json", json.dumps({"lockfileVersion": 3, "packages": {"": {}, **body}}))
            out = self.start("3days", now=LATER)
            self.assertNotIn(cid, out["auto_decisions"], body)
            item = next(i for i in out["worklist"] if i["candidate_id"] == cid)
            self.assertTrue(any("absence is not shown: package-lock.json: parsed with unresolved entries" in r
                                for r in item["queue_reasons"]), item["queue_reasons"])
            state = self.state()
            self.assertNotIn(cid, state["assessments"])
            self.assertEqual(state["stale"][cid]["assessment"]["applicability"], "affected")
            code, handoff = self.cli("finish", "--run", out["run_id"], now=LATER)
            self.assertEqual(code, 0)
            self.assertIn("listed package entry without a resolved name and version: node_modules/lodash", handoff)
            self.assertNotIn("component_not_present", json.dumps(self.state()["assessments"].get(cid)))


UV_APP = 'version = 1\nrequires-python = ">=3.11"\n\n[[package]]\nname = "app"\nversion = "0.1.0"\nsource = { editable = "." }\n'
UV_REQUESTS = '\n[[package]]\nname = "requests"\nversion = "2.28.0"\n'


class TomlSourceRules(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ca-toml-")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_uv_missing_or_unknown_source_is_a_gap(self):
        write(self.root, "a/uv.lock", UV_APP + UV_REQUESTS)
        write(self.root, "b/uv.lock", UV_APP + UV_REQUESTS + 'source = { mystery = "x" }\n')
        data = inv.build_inventory(self.root)
        for src in ("a/uv.lock", "b/uv.lock"):
            self.assertRegex(inv.absence_unproven(data, {"source": src}) or "", "unresolved entries", src)
            self.assertTrue(any(g.startswith(src) and "requests (source unresolved)" in g for g in data["gaps"]))
        self.assertNotIn("app", {c["name"] for c in data["components"]})

    def test_uv_local_sources_are_skipped_without_a_gap(self):
        local = "".join(f'\n[[package]]\nname = "l{k}"\nversion = "0.1.0"\nsource = {{ {k} = "." }}\n'
                        for k in inv.UV_LOCAL_SOURCES)
        write(self.root, "uv.lock", UV_APP + local + UV_REQUESTS + REGISTRY + "\n")
        data = inv.build_inventory(self.root)
        self.assertIsNone(inv.absence_unproven(data, {"source": "uv.lock"}), data["gaps"])
        self.assertEqual({c["name"] for c in data["components"] if c["kind"] == "library"}, {"requests"})

    def test_cargo_sourceless_workspace_member_is_skipped(self):
        write(self.root, "Cargo.lock", 'version = 4\n\n[[package]]\nname = "app"\nversion = "0.1.0"\n\n'
              '[[package]]\nname = "serde"\nversion = "1.0.0"\n'
              'source = "registry+https://github.com/rust-lang/crates.io-index"\n')
        data = inv.build_inventory(self.root)
        self.assertIsNone(inv.absence_unproven(data, {"source": "Cargo.lock"}), data["gaps"])
        self.assertEqual({c["name"] for c in data["components"] if c["kind"] == "library"}, {"serde"})

    def test_cargo_unknown_source_is_a_gap(self):
        write(self.root, "Cargo.lock", 'version = 4\n\n[[package]]\nname = "serde"\nversion = "1.0.0"\nsource = "mystery+x"\n')
        data = inv.build_inventory(self.root)
        self.assertRegex(inv.absence_unproven(data, {"source": "Cargo.lock"}) or "", "unresolved entries")


class UvEntryLosesSourceEndToEnd(RepoCase):
    def setUp(self):
        super().setUp()
        os.remove(os.path.join(self.root, "requirements.txt"))
        write(self.root, "uv.lock", UV_APP + UV_REQUESTS + REGISTRY + "\n")

    def first_run(self):
        out = self.start("3days")
        cids = [i["candidate_id"] for i in out["worklist"] if i["component"]["name"] == "requests"]
        self.assertTrue(cids)
        for cid in cids:
            self.assertEqual(self.decide(out["run_id"], cid, "affected", "--evidence", "uv.lock")[0], 0)
        self.assertEqual(self.cli("finish", "--run", out["run_id"])[0], 0)
        return cids

    def test_previously_affected_uv_package_stays_queued(self):
        cids = self.first_run()
        write(self.root, "uv.lock", UV_APP + UV_REQUESTS)
        out = self.start("3days", now=LATER)
        state = self.state()
        for cid in cids:
            self.assertNotIn(cid, out["auto_decisions"])
            item = next(i for i in out["worklist"] if i["candidate_id"] == cid)
            self.assertTrue(any("absence is not shown: uv.lock: parsed with unresolved entries" in r
                                for r in item["queue_reasons"]), item["queue_reasons"])
            self.assertNotIn(cid, state["assessments"])
            self.assertEqual(state["stale"][cid]["assessment"]["applicability"], "affected")
        code, handoff = self.cli("finish", "--run", out["run_id"], now=LATER)
        self.assertEqual(code, 0)
        self.assertIn("requests (source unresolved)", handoff)
        self.assertNotIn("component_not_present", json.dumps(self.state()["assessments"]))

    def test_control_removed_uv_entry_is_shown_absent(self):
        cids = self.first_run()
        write(self.root, "uv.lock", UV_APP)
        out = self.start("3days", now=LATER)
        for cid in cids:
            self.assertIn(cid, out["auto_decisions"])
            self.assertEqual(self.state()["assessments"][cid]["justification"], "component_not_present")


if __name__ == "__main__":
    unittest.main()
