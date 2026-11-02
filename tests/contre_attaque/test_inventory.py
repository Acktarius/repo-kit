import json
import os
import shutil
import tempfile
import unittest

from support import write

import ca_inventory as inv


def sbom(observed="2026-10-31T00:00:00Z", subject=True):
    meta = {"timestamp": observed} if observed else {}
    if subject:
        meta["component"] = {"name": "api-image", "version": "build-417"}
    return json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.5", "metadata": meta, "components": [
        {"purl": "pkg:deb/debian/openssl@3.0.11-1~deb12u2?distro=debian-12"},
        {"purl": "pkg:npm/%40scope/pkg@1.2.3"},
    ]})


class Inventory(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ca-inv-")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def comps(self, **filters):
        data = inv.build_inventory(self.root, os.path.join(self.root, ".repo-kit", "contre-attaque", "imports"))
        out = [c for c in data["components"] if all(c.get(k) == v for k, v in filters.items())]
        return data, out

    def test_lockfiles(self):
        write(self.root, "web/package-lock.json", json.dumps({"lockfileVersion": 3, "packages": {
            "": {}, "node_modules/a": {"version": "1.0.0"}, "node_modules/b/node_modules/c": {"version": "2.0.0"},
            "node_modules/linked": {"link": True}}}))
        write(self.root, "pnpm-lock.yaml", "lockfileVersion: '9.0'\npackages:\n  '@scope/x@1.2.3':\n    resolution: {}\n  y@4.5.6(peer@1.0.0):\n    resolution: {}\n")
        write(self.root, "yarn.lock", '# yarn lockfile v1\n\n"z@^1.0.0", z@~1.0.0:\n  version "1.0.4"\n')
        write(self.root, "poetry.lock", '[[package]]\nname = "Django"\nversion = "4.2.1"\n\n[metadata]\nlock-version = "2.0"\n')
        write(self.root, "uv.lock", 'version = 1\n\n[[package]]\nname = "app"\nversion = "0.1.0"\nsource = { editable = "." }\n\n[[package]]\nname = "flask"\nversion = "3.0.0"\nsource = { registry = "https://pypi.org/simple" }\n')
        write(self.root, "Cargo.lock", '[[package]]\nname = "serde"\nversion = "1.0.0"\nsource = "registry+https://github.com/rust-lang/crates.io-index"\n\n[[package]]\nname = "local"\nversion = "0.1.0"\n')
        write(self.root, "go.mod", "module x\n\ngo 1.22.1\n\nrequire (\n\tgithub.com/a/b v1.2.3 // indirect\n)\nrequire golang.org/x/net v0.20.0\n")
        write(self.root, "Gemfile.lock", "GEM\n  specs:\n    rack (3.0.8)\n\nPLATFORMS\n  ruby\n")
        write(self.root, "composer.lock", json.dumps({"packages": [{"name": "monolog/monolog", "version": "v3.5.0"}]}))
        write(self.root, "requirements-dev.txt", "Pytest_Mock==3.12.0  # pinned\nblack>=23\n")
        _, comps = self.comps(tier="locked")
        got = {(c["ecosystem"], c["name"], c["version"]) for c in comps}
        for want in [("npm", "a", "1.0.0"), ("npm", "c", "2.0.0"), ("npm", "@scope/x", "1.2.3"), ("npm", "y", "4.5.6"),
                     ("npm", "z", "1.0.4"), ("PyPI", "django", "4.2.1"), ("PyPI", "flask", "3.0.0"),
                     ("crates.io", "serde", "1.0.0"), ("Go", "github.com/a/b", "v1.2.3"), ("Go", "golang.org/x/net", "v0.20.0"),
                     ("RubyGems", "rack", "3.0.8"), ("Packagist", "monolog/monolog", "3.5.0"), ("PyPI", "pytest-mock", "3.12.0")]:
            self.assertIn(want, got)
        self.assertNotIn(("PyPI", "app", "0.1.0"), got)
        self.assertNotIn(("crates.io", "local", "0.1.0"), got)
        data, _ = self.comps()
        self.assertTrue(any("unpinned requirements" in g and "black" in g for g in data["gaps"]))
        self.assertTrue(any(c["name"] == "stdlib" and c["version"] == "1.22.1" for c in data["components"]))

    def test_runtimes_images_ci_and_os_packages(self):
        write(self.root, ".python-version", "3.11.4\n")
        write(self.root, ".nvmrc", "v20.11.1\n")
        write(self.root, "Dockerfile", "FROM --platform=linux/amd64 python:3.11.4-slim-bookworm AS base\n"
                                       "RUN apt-get update && apt-get install -y curl=7.88.1-10 libpq5 \\\n    && rm -rf /var/lib/apt\n"
                                       "FROM base\nFROM nginx\n")
        write(self.root, "deploy/compose.yaml", "services:\n  db:\n    image: postgres:16.2\n")
        write(self.root, "k8s/app.yaml", "apiVersion: apps/v1\nkind: Deployment\nspec:\n  containers:\n    - image: redis:7.2.4@sha256:abc\n")
        write(self.root, ".github/workflows/ci.yml", "jobs:\n  t:\n    steps:\n      - uses: actions/setup-python@v5\n        with:\n          python-version: ['3.10', '3.12']\n")
        data, comps = self.comps()
        by = {(c["kind"], c["name"], c["version"], c["tier"]) for c in comps}
        self.assertIn(("runtime", "python", "3.11.4", "declared"), by)
        self.assertIn(("runtime", "node", "20.11.1", "declared"), by)
        self.assertIn(("image", "python", "3.11.4", "build"), by)
        self.assertIn(("image", "postgres", "16.2", "deploy_config"), by)
        self.assertIn(("image", "redis", "7.2.4", "deploy_config"), by)
        self.assertIn(("runtime", "python", "3.10", "ci"), by)
        self.assertIn(("os-package", "curl", "7.88.1-10", "build"), by)
        img = next(c for c in comps if c["kind"] == "image" and c["name"] == "python")
        self.assertEqual([tuple(x) for x in img["cpe"]], [("python", "python")])
        self.assertEqual(img["os_ecosystem"], "Debian:12")
        self.assertEqual(next(c for c in comps if c["name"] == "curl")["ecosystem"], "Debian:12")
        self.assertFalse(any(c["name"] == "base" for c in comps))
        self.assertTrue(any("nginx" in g and "no version tag" in g for g in data["gaps"]))
        self.assertTrue(any("libpq5" in g for g in data["gaps"]))
        self.assertTrue(any("production runtime is not observed" in g for g in data["limitations"]))
        self.assertTrue(any("container image contents" in g for g in data["gaps"]))

    def test_sbom_requires_subject_and_observation_time(self):
        imports = os.path.join(self.root, ".repo-kit", "contre-attaque", "imports")
        write(imports, "bad.json", sbom(observed=None))
        data, comps = self.comps(tier="sbom")
        self.assertEqual(comps, [])
        self.assertTrue(any("bad.json: rejected" in g for g in data["gaps"]))
        write(imports, "good.json", sbom())
        data, comps = self.comps(tier="sbom")
        names = {(c["ecosystem"], c["name"]) for c in comps}
        self.assertEqual(names, {("Debian:12", "openssl"), ("npm", "@scope/pkg")})
        self.assertTrue(all(c["sbom_subject"] == "api-image build-417" for c in comps))
        self.assertTrue(all(c["sbom_observed_at"] == "2026-10-31T00:00:00Z" for c in comps))
        fp1 = inv.deployment_fingerprint(data)
        write(imports, "good.json", sbom(observed="2026-11-01T00:00:00Z"))
        data2, _ = self.comps()
        self.assertNotEqual(fp1, inv.deployment_fingerprint(data2))

    def test_declared_without_lockfile_and_bundled_dirs_are_gaps(self):
        write(self.root, "package.json", json.dumps({"dependencies": {"express": "^4"}, "engines": {"node": ">=18.17.0"}}))
        write(self.root, "vendor/lib/x.c", "int x;\n")
        data, comps = self.comps()
        self.assertTrue(any("declared without a lockfile" in g for g in data["gaps"]))
        self.assertTrue(any(g.startswith("vendor/") for g in data["gaps"]))
        self.assertIn(("runtime", "node", "18.17.0"), {(c["kind"], c["name"], c["version"]) for c in comps})

    def test_symlinks_are_not_followed(self):
        outside = tempfile.mkdtemp(prefix="ca-out-")
        try:
            write(outside, "requirements.txt", "evil==1.0\n")
            os.symlink(outside, os.path.join(self.root, "linked"))
            os.symlink(os.path.join(outside, "requirements.txt"), os.path.join(self.root, "requirements.txt"))
            _, comps = self.comps()
            self.assertEqual(comps, [])
        finally:
            shutil.rmtree(outside)


if __name__ == "__main__":
    unittest.main()
