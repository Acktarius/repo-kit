"""Read-only repository technology inventory for contre-attaque.

Evidence tiers (never merged into a production claim):
  locked         resolved version from a lockfile
  declared       manifest range or version file (requested, not resolved)
  build          container build definition (Dockerfile FROM / package installs)
  deploy_config  deployment configuration (compose, Kubernetes manifests)
  ci             CI workflow versions
  sbom           imported CycloneDX SBOM in imports/; records which deployment/build it
                 describes and when it was observed. Inventory evidence only, not proof
                 of what is running now.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__", ".tox", ".mypy_cache",
    ".pytest_cache", "dist", "build", "target", ".next", ".nuxt", ".cache", ".repo-kit",
    ".cursor", ".idea", ".vscode", "coverage", ".terraform",
}
BUNDLED_DIRS = {"vendor", "third_party", "third-party", "external", "deps", "extern"}
MAX_FILES = 20000
MAX_FILE_BYTES = 8 * 1024 * 1024

# Container image / runtime names -> NVD CPE (vendor, product) pairs.
CPE_PRODUCTS: dict[str, list[tuple[str, str]]] = {
    "python": [("python", "python")],
    "node": [("nodejs", "node.js")],
    "nodejs": [("nodejs", "node.js")],
    "golang": [("golang", "go")],
    "go": [("golang", "go")],
    "ruby": [("ruby-lang", "ruby")],
    "php": [("php", "php")],
    "rust": [("rust-lang", "rust")],
    "nginx": [("f5", "nginx"), ("nginx", "nginx")],
    "httpd": [("apache", "http_server")],
    "postgres": [("postgresql", "postgresql")],
    "postgresql": [("postgresql", "postgresql")],
    "mysql": [("oracle", "mysql")],
    "mariadb": [("mariadb", "mariadb")],
    "redis": [("redis", "redis")],
    "memcached": [("memcached", "memcached")],
    "mongo": [("mongodb", "mongodb")],
    "haproxy": [("haproxy", "haproxy")],
    "traefik": [("traefik", "traefik")],
    "caddy": [("caddyserver", "caddy")],
    "openssl": [("openssl", "openssl")],
    "rabbitmq": [("vmware", "rabbitmq"), ("pivotal_software", "rabbitmq")],
    "elasticsearch": [("elastic", "elasticsearch")],
    "tomcat": [("apache", "tomcat")],
    "jenkins": [("jenkins", "jenkins")],
    "grafana": [("grafana", "grafana")],
    "vault": [("hashicorp", "vault")],
    "consul": [("hashicorp", "consul")],
    "keycloak": [("redhat", "keycloak")],
}

PURL_ECOSYSTEMS = {
    "npm": "npm", "pypi": "PyPI", "cargo": "crates.io", "golang": "Go", "maven": "Maven",
    "nuget": "NuGet", "gem": "RubyGems", "composer": "Packagist", "pub": "Pub", "hex": "Hex",
}
DEBIAN_CODENAMES = {"bookworm": "12", "bullseye": "11", "buster": "10", "trixie": "13"}


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _norm_name(ecosystem: str, name: str) -> str:
    if ecosystem == "PyPI":
        return re.sub(r"[-_.]+", "-", name).lower()
    return name


def component(kind: str, ecosystem: str, name: str, version: str | None, tier: str,
              source: str, line: int | None = None, **extra: Any) -> dict[str, Any]:
    name = _norm_name(ecosystem, name.strip())
    identity = f"{kind}:{ecosystem}:{name}:{source}"
    comp = {
        "identity": identity,
        "key": f"{identity}@{version or '?'}",
        "kind": kind, "ecosystem": ecosystem, "name": name,
        "version": version or None, "tier": tier, "source": source, "line": line,
    }
    comp.update({k: v for k, v in extra.items() if v is not None})
    return comp


# ---------------------------------------------------------------------------
# Lockfile parsers (each returns components; malformed input -> gap)
# ---------------------------------------------------------------------------

def _npm_lock(text: str, src: str) -> list[dict[str, Any]]:
    data = json.loads(text)
    out = []
    packages = data.get("packages")
    if isinstance(packages, dict):
        for path, meta in packages.items():
            if not path or not isinstance(meta, dict) or meta.get("link") or "node_modules/" not in path:
                continue
            name = meta.get("name") or path.rsplit("node_modules/", 1)[1]
            if meta.get("version"):
                out.append(component("library", "npm", name, meta["version"], "locked", src))
        return out

    def walk(deps: dict[str, Any]) -> None:
        for name, meta in (deps or {}).items():
            if isinstance(meta, dict) and meta.get("version"):
                out.append(component("library", "npm", name, meta["version"], "locked", src))
                walk(meta.get("dependencies") or {})

    walk(data.get("dependencies") or {})
    return out


def _split_at_version(spec: str) -> tuple[str, str] | None:
    idx = spec.rfind("@")
    if idx <= 0:
        return None
    return spec[:idx], spec[idx + 1:]


def _pnpm_lock(text: str, src: str) -> list[dict[str, Any]]:
    out, in_packages = [], False
    for line in text.splitlines():
        if re.match(r"^(packages|snapshots):\s*$", line):
            in_packages = line.startswith("packages")
            continue
        if re.match(r"^\S", line):
            in_packages = False
            continue
        if not in_packages:
            continue
        m = re.match(r"^  ['\"]?(/?[^'\"\s][^'\"]*?)['\"]?:\s*$", line)
        if not m:
            continue
        spec = re.sub(r"\(.*$", "", m.group(1)).lstrip("/")
        parsed = _split_at_version(spec)
        if parsed is None and spec.count("/") >= 1:
            name, _, ver = spec.rpartition("/")
            parsed = (name, ver) if name else None
        if parsed and re.match(r"^\d", parsed[1]):
            out.append(component("library", "npm", parsed[0], parsed[1], "locked", src))
    return out


def _yarn_lock(text: str, src: str) -> list[dict[str, Any]]:
    out, current = [], None
    for line in text.splitlines():
        if line and not line.startswith((" ", "#")) and line.rstrip().endswith(":"):
            first = line.rstrip()[:-1].split(",")[0].strip().strip('"')
            parsed = _split_at_version(first)
            current = parsed[0] if parsed else None
            if current == "__metadata":
                current = None
            continue
        m = re.match(r'^\s+version:?\s+"?([^"\s]+)"?\s*$', line)
        if current and m:
            out.append(component("library", "npm", current, m.group(1), "locked", src))
            current = None
    return out


def _toml_packages(text: str, src: str, ecosystem: str, skip_local: bool) -> list[dict[str, Any]]:
    out = []
    for block in re.split(r"^\[\[package\]\]\s*$", text, flags=re.MULTILINE)[1:]:
        block = re.split(r"^\[(?!\[package)", block, maxsplit=1, flags=re.MULTILINE)[0]
        name = re.search(r'^name\s*=\s*"([^"]+)"', block, re.MULTILINE)
        ver = re.search(r'^version\s*=\s*"([^"]+)"', block, re.MULTILINE)
        source = re.search(r"^source\s*=\s*(.+)$", block, re.MULTILINE)
        if not (name and ver):
            continue
        if skip_local and (not source or re.search(r"(virtual|editable|path)\s*=", source.group(1))):
            continue
        out.append(component("library", ecosystem, name.group(1), ver.group(1), "locked", src))
    return out


def _requirements(text: str, src: str) -> tuple[list[dict[str, Any]], list[str]]:
    out, unpinned = [], []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        line = line.split(";", 1)[0].strip()
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*===?\s*([A-Za-z0-9._+!-]+)\s*(\\)?$", line)
        if m:
            out.append(component("library", "PyPI", m.group(1), m.group(3), "locked", src))
        else:
            name = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", line)
            if name:
                unpinned.append(name.group(1))
    return out, unpinned


def _pipfile_lock(text: str, src: str) -> list[dict[str, Any]]:
    data = json.loads(text)
    out = []
    for section in ("default", "develop"):
        for name, meta in (data.get(section) or {}).items():
            ver = str((meta or {}).get("version") or "")
            if ver.startswith("=="):
                out.append(component("library", "PyPI", name, ver[2:], "locked", src))
    return out


def _composer_lock(text: str, src: str) -> list[dict[str, Any]]:
    data = json.loads(text)
    out = []
    for section in ("packages", "packages-dev"):
        for pkg in data.get(section) or []:
            if pkg.get("name") and pkg.get("version"):
                out.append(component("library", "Packagist", pkg["name"], str(pkg["version"]).lstrip("v"), "locked", src))
    return out


def _gemfile_lock(text: str, src: str) -> list[dict[str, Any]]:
    out, in_specs = [], False
    for line in text.splitlines():
        if line.strip() == "specs:":
            in_specs = True
            continue
        if in_specs and line and not line.startswith(" "):
            in_specs = False
        m = re.match(r"^    ([A-Za-z0-9._-]+) \(([^)]+)\)\s*$", line)
        if in_specs and m:
            out.append(component("library", "RubyGems", m.group(1), m.group(2).split("-")[0], "locked", src))
    return out


def _go_mod(text: str, src: str) -> list[dict[str, Any]]:
    out = []
    in_block = False
    for raw in text.splitlines():
        line = raw.split("//", 1)[0].strip()
        if line.startswith("require ("):
            in_block = True
            continue
        if in_block and line == ")":
            in_block = False
            continue
        m = re.match(r"^(?:require\s+)?(\S+)\s+(v\S+)$", line) if (in_block or line.startswith("require ")) else None
        if m:
            out.append(component("library", "Go", m.group(1), m.group(2), "locked", src))
        go = re.match(r"^go\s+(\d+\.\d+(?:\.\d+)?)$", line)
        if go:
            out.append(component("runtime", "Go", "go", go.group(1), "declared", src, cpe=CPE_PRODUCTS["go"]))
            if go.group(1).count(".") == 2:
                out.append(component("library", "Go", "stdlib", go.group(1), "declared", src))
        tc = re.match(r"^toolchain\s+go(\d+\.\d+\.\d+)$", line)
        if tc:
            out.append(component("runtime", "Go", "go-toolchain", tc.group(1), "declared", src, cpe=CPE_PRODUCTS["go"]))
            out.append(component("library", "Go", "stdlib", tc.group(1), "declared", src))
    return out


# ---------------------------------------------------------------------------
# Runtime / image / deployment parsers
# ---------------------------------------------------------------------------

def _runtime(name: str, version: str, tier: str, src: str, line: int | None = None) -> dict[str, Any]:
    return component("runtime", "runtime", name, version, tier, src, line, cpe=CPE_PRODUCTS.get(name))


def parse_image_ref(ref: str) -> dict[str, Any] | None:
    ref = ref.strip().strip("'\"")
    if not ref or "$" in ref or "{{" in ref or ref == "scratch":
        return None
    digest = None
    if "@" in ref:
        ref, digest = ref.split("@", 1)
    last = ref.rsplit("/", 1)[-1]
    tag = None
    if ":" in last:
        ref, tag = ref.rsplit(":", 1)
    repo = ref
    base = repo.rsplit("/", 1)[-1].lower()
    ver = None
    if tag:
        m = re.match(r"^v?(\d+(?:\.\d+)*)", tag)
        ver = m.group(1) if m else None
    os_eco = None
    tag_l = (tag or "").lower()
    for code, num in DEBIAN_CODENAMES.items():
        if code in tag_l:
            os_eco = f"Debian:{num}"
    m = re.search(r"alpine(\d+\.\d+)", tag_l)
    if m:
        os_eco = f"Alpine:v{m.group(1)}"
    if base == "debian" and tag_l in DEBIAN_CODENAMES:
        os_eco = f"Debian:{DEBIAN_CODENAMES[tag_l]}"
    if base == "alpine" and ver:
        os_eco = f"Alpine:v{'.'.join(ver.split('.')[:2])}"
    return {"repo": repo, "base": base, "tag": tag, "digest": digest, "version": ver, "os_ecosystem": os_eco}


def _image_components(ref: str, tier: str, src: str, line: int) -> tuple[list[dict[str, Any]], str | None]:
    img = parse_image_ref(ref)
    if img is None:
        return [], f"{src}:{line}: unresolved image reference {ref.strip()!r}"
    gap = None if img["version"] else f"{src}:{line}: image {img['repo']} has no version tag ({img['tag'] or 'implicit latest'})"
    comp = component("image", "container", img["repo"], img["version"], tier, src, line,
                     tag=img["tag"], digest=img["digest"], cpe=CPE_PRODUCTS.get(img["base"]),
                     os_ecosystem=img["os_ecosystem"])
    return [comp], gap


def _dockerfile(text: str, src: str) -> tuple[list[dict[str, Any]], list[str]]:
    out, gaps, stages = [], [], set()
    os_eco = None
    joined = re.sub(r"\\\n", " ", text)
    for idx, line in enumerate(joined.splitlines(), start=1):
        s = line.strip()
        m = re.match(r"^FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?", s, re.IGNORECASE)
        if m:
            if m.group(1).lower() in stages:
                pass
            else:
                comps, gap = _image_components(m.group(1), "build", src, idx)
                out.extend(comps)
                if gap:
                    gaps.append(gap)
                os_eco = comps[0].get("os_ecosystem") if comps else None
            if m.group(2):
                stages.add(m.group(2).lower())
            continue
        pm = re.search(r"\b(apt-get|apt|apk)\s+(?:install|add)\b(.*)", s)
        if pm:
            for tok in pm.group(2).split():
                if tok.startswith("-") or tok in ("&&", "||", ";") or "$" in tok:
                    if tok in ("&&", "||", ";"):
                        break
                    continue
                name, _, ver = tok.partition("=")
                if not re.match(r"^[a-z0-9][a-z0-9.+-]*$", name):
                    continue
                comp = component("os-package", os_eco or "unknown-os", name, ver or None, "build", src, idx)
                out.append(comp)
                if not ver or not os_eco:
                    gaps.append(f"{src}:{idx}: OS package {name} has no pinned version or known distro release")
    return out, gaps


def _image_lines(text: str, tier: str, src: str) -> tuple[list[dict[str, Any]], list[str]]:
    out, gaps = [], []
    for idx, line in enumerate(text.splitlines(), start=1):
        m = re.match(r"^\s*-?\s*image:\s*(\S+)\s*$", line)
        if m:
            comps, gap = _image_components(m.group(1), tier, src, idx)
            out.extend(comps)
            if gap:
                gaps.append(gap)
    return out, gaps


def _workflow(text: str, src: str) -> tuple[list[dict[str, Any]], list[str]]:
    out, gaps = _image_lines(text, "ci", src)
    for idx, line in enumerate(text.splitlines(), start=1):
        m = re.match(r"^\s*(python|node|go|ruby|java)-version:\s*(.+)$", line)
        if not m:
            continue
        name = {"node": "node", "python": "python", "go": "go", "ruby": "ruby", "java": "java"}[m.group(1)]
        for ver in re.findall(r"v?(\d+(?:\.\d+)*)", m.group(2)):
            out.append(_runtime(name, ver, "ci", src, idx))
    return out, gaps


class SbomError(ValueError):
    pass


def _sbom(text: str, src: str) -> list[dict[str, Any]]:
    data = json.loads(text)
    if data.get("bomFormat") != "CycloneDX":
        return []
    meta = data.get("metadata") or {}
    subject = meta.get("component") or {}
    observed_at = meta.get("timestamp")
    subject_id = " ".join(str(subject.get(k)) for k in ("name", "version") if subject.get(k))
    if not observed_at or not subject.get("name"):
        raise SbomError(
            "CycloneDX import must set metadata.timestamp (observation time) and "
            "metadata.component.name/version (the deployment or build it describes)"
        )
    sbom_meta = {"sbom_subject": subject_id, "sbom_observed_at": observed_at}
    out = []
    for comp in data.get("components") or []:
        purl = comp.get("purl") or ""
        m = re.match(r"^pkg:([^/]+)/(.+?)@([^?#]+)(\?[^#]*)?", purl)
        if not m:
            continue
        ptype, path, version = m.group(1).lower(), m.group(2), m.group(3)
        quals = dict(q.split("=", 1) for q in (m.group(4) or "?")[1:].split("&") if "=" in q)
        name = path.replace("%40", "@")
        if ptype in ("deb", "apk"):
            name = name.split("/", 1)[-1]
            distro = quals.get("distro", "")
            dm = re.match(r"^(debian|alpine)-(\d+(?:\.\d+)?)", distro)
            eco = None
            if dm:
                eco = f"Debian:{dm.group(2).split('.')[0]}" if dm.group(1) == "debian" else f"Alpine:v{dm.group(2)}"
            out.append(component("os-package", eco or "unknown-os", name, version, "sbom", src, **sbom_meta))
        elif ptype in PURL_ECOSYSTEMS:
            if ptype == "maven":
                name = name.replace("/", ":")
            out.append(component("library", PURL_ECOSYSTEMS[ptype], name, version, "sbom", src, **sbom_meta))
    return out


# ---------------------------------------------------------------------------
# Walk
# ---------------------------------------------------------------------------

def _walk(root: str) -> tuple[list[str], list[str], bool]:
    files, bundled, truncated = [], [], False
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = os.path.relpath(dirpath, root)
        keep = []
        for d in sorted(dirnames):
            if d in SKIP_DIRS or os.path.islink(os.path.join(dirpath, d)):
                continue
            if d in BUNDLED_DIRS:
                bundled.append(os.path.normpath(os.path.join(rel_dir, d)))
            keep.append(d)
        dirnames[:] = keep
        for f in sorted(filenames):
            full = os.path.join(dirpath, f)
            if os.path.islink(full) or not os.path.isfile(full):
                continue
            files.append(os.path.normpath(os.path.join(rel_dir, f)))
            if len(files) >= MAX_FILES:
                return files, bundled, True
    return files, bundled, truncated


def _kind(rel: str) -> str | None:
    base = os.path.basename(rel).lower()
    parts = rel.replace(os.sep, "/").split("/")
    if base in ("package-lock.json", "npm-shrinkwrap.json"):
        return "npm-lock"
    if base == "pnpm-lock.yaml":
        return "pnpm-lock"
    if base == "yarn.lock":
        return "yarn-lock"
    if base in ("poetry.lock", "uv.lock", "cargo.lock", "pipfile.lock", "composer.lock", "gemfile.lock", "go.mod"):
        return base
    if re.match(r"^requirements.*\.txt$", base):
        return "requirements"
    if base == "package.json":
        return "package.json"
    if base == "pyproject.toml":
        return "pyproject"
    if base in (".python-version", ".nvmrc", ".node-version", ".tool-versions", "rust-toolchain", "rust-toolchain.toml"):
        return base
    if base.startswith(("dockerfile", "containerfile")) or base.endswith(".dockerfile"):
        return "dockerfile"
    if len(parts) >= 3 and parts[0] == ".github" and parts[1] == "workflows" and base.endswith((".yml", ".yaml")):
        return "workflow"
    if re.match(r"^(docker-)?compose.*\.ya?ml$", base):
        return "compose"
    if base.endswith((".yml", ".yaml")) and parts[0] != ".github":
        return "yaml"
    return None


def _read(root: str, rel: str) -> str | None:
    full = os.path.join(root, rel)
    if os.path.getsize(full) > MAX_FILE_BYTES:
        return None
    with open(full, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def build_inventory(root: str, imports_dir: str | None = None) -> dict[str, Any]:
    root = os.path.realpath(root)
    files, bundled, truncated = _walk(root)
    comps: list[dict[str, Any]] = []
    gaps: list[str] = []
    sources: dict[str, str] = {}
    locked_dirs: set[str] = set()
    declared_manifests: list[tuple[str, str]] = []
    parsed: set[str] = set()
    incomplete: dict[str, str] = {}

    def add_source(rel: str) -> None:
        sources[rel] = sha256_file(os.path.join(root, rel))

    for rel in files:
        kind = _kind(rel)
        if kind is None:
            continue
        text = _read(root, rel)
        if text is None:
            incomplete[rel] = f"larger than {MAX_FILE_BYTES} bytes"
            gaps.append(f"{rel}: larger than {MAX_FILE_BYTES} bytes; not parsed")
            continue
        found: list[dict[str, Any]] = []
        gaps_before = len(gaps)
        try:
            if kind == "npm-lock":
                found = _npm_lock(text, rel)
            elif kind == "pnpm-lock":
                found = _pnpm_lock(text, rel)
            elif kind == "yarn-lock":
                found = _yarn_lock(text, rel)
            elif kind == "poetry.lock":
                found = _toml_packages(text, rel, "PyPI", skip_local=False)
            elif kind == "uv.lock":
                found = _toml_packages(text, rel, "PyPI", skip_local=True)
            elif kind == "cargo.lock":
                found = _toml_packages(text, rel, "crates.io", skip_local=True)
            elif kind == "pipfile.lock":
                found = _pipfile_lock(text, rel)
            elif kind == "composer.lock":
                found = _composer_lock(text, rel)
            elif kind == "gemfile.lock":
                found = _gemfile_lock(text, rel)
            elif kind == "go.mod":
                found = _go_mod(text, rel)
            elif kind == "requirements":
                found, unpinned = _requirements(text, rel)
                if unpinned:
                    gaps.append(f"{rel}: unpinned requirements (no resolved version): {', '.join(sorted(unpinned)[:20])}")
            elif kind == "package.json":
                data = json.loads(text)
                node = (data.get("engines") or {}).get("node")
                if node:
                    m = re.search(r"(\d+(?:\.\d+)*)", str(node))
                    if m:
                        found.append(_runtime("node", m.group(1), "declared", rel))
                if data.get("dependencies") or data.get("devDependencies"):
                    declared_manifests.append((rel, "npm"))
            elif kind == "pyproject":
                m = re.search(r'requires-python\s*=\s*"[^"\d]*(\d+(?:\.\d+)*)', text)
                if m:
                    found.append(_runtime("python", m.group(1), "declared", rel))
                if re.search(r"^\s*dependencies\s*=|^\[tool\.poetry\.dependencies\]", text, re.MULTILINE):
                    declared_manifests.append((rel, "PyPI"))
            elif kind in (".python-version", ".nvmrc", ".node-version"):
                ver = text.strip().splitlines()[0].strip().lstrip("v") if text.strip() else ""
                name = "python" if kind == ".python-version" else "node"
                if re.match(r"^\d+(\.\d+)*$", ver):
                    found.append(_runtime(name, ver, "declared", rel, 1))
                else:
                    gaps.append(f"{rel}: runtime version {ver!r} is not a numeric version")
            elif kind == ".tool-versions":
                for idx, line in enumerate(text.splitlines(), start=1):
                    parts = line.split()
                    if len(parts) >= 2:
                        name = {"nodejs": "node", "golang": "go"}.get(parts[0], parts[0])
                        found.append(_runtime(name, parts[1].lstrip("v"), "declared", rel, idx))
            elif kind in ("rust-toolchain", "rust-toolchain.toml"):
                m = re.search(r"(\d+\.\d+(?:\.\d+)?)", text)
                if m:
                    found.append(_runtime("rust", m.group(1), "declared", rel))
            elif kind == "dockerfile":
                found, g = _dockerfile(text, rel)
                gaps.extend(g)
            elif kind == "workflow":
                found, g = _workflow(text, rel)
                gaps.extend(g)
            elif kind == "compose" or (kind == "yaml" and re.search(r"^\s*apiVersion:", text, re.MULTILINE)):
                found, g = _image_lines(text, "deploy_config", rel)
                gaps.extend(g)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            incomplete[rel] = f"could not be parsed ({type(exc).__name__})"
            gaps.append(f"{rel}: could not be parsed ({type(exc).__name__}); components unknown")
            continue
        parsed.add(rel)
        if len(gaps) > gaps_before:
            incomplete[rel] = f"parsed with unresolved entries ({len(gaps) - gaps_before} inventory gap(s))"
        if found:
            add_source(rel)
            comps.extend(found)
            if kind not in ("package.json", "pyproject", "workflow", "dockerfile", "compose", "yaml"):
                locked_dirs.add(os.path.dirname(rel))
        elif kind in ("package.json", "pyproject"):
            add_source(rel)

    for rel, eco in declared_manifests:
        if os.path.dirname(rel) not in locked_dirs:
            gaps.append(f"{rel}: {eco} dependencies are declared without a lockfile; resolved versions unknown")

    if imports_dir and os.path.isdir(imports_dir):
        for name in sorted(os.listdir(imports_dir)):
            full = os.path.join(imports_dir, name)
            if not name.endswith(".json") or not os.path.isfile(full) or os.path.islink(full):
                continue
            rel = os.path.relpath(full, root)
            try:
                with open(full, encoding="utf-8") as fh:
                    found = _sbom(fh.read(), rel)
            except SbomError as exc:
                incomplete[rel] = f"rejected: {exc}"
                gaps.append(f"{rel}: rejected: {exc}")
                continue
            except (ValueError, OSError) as exc:
                incomplete[rel] = f"not a readable JSON import ({type(exc).__name__})"
                gaps.append(f"{rel}: not a readable JSON import ({type(exc).__name__})")
                continue
            parsed.add(rel)
            if found:
                add_source(rel)
                comps.extend(found)

    for d in bundled:
        gaps.append(f"{d}/: bundled or vendored code present; components not inventoried automatically")
    if truncated:
        gaps.append(f"inventory stopped after {MAX_FILES} files; coverage incomplete")
    limitations = ["current production runtime is not observed; repository, CI, and SBOM evidence "
                   "do not prove what is deployed now"]
    if not any(c["tier"] == "sbom" for c in comps):
        note = "no deployment/build SBOM imported (.repo-kit/contre-attaque/imports/*.json, CycloneDX)"
        if any(c["kind"] == "image" for c in comps):
            gaps.append(f"container image contents (OS packages, bundled runtimes) not inventoried: {note}")
        else:
            limitations.append(note)

    unique: dict[str, dict[str, Any]] = {}
    for c in comps:
        unique.setdefault(c["key"], c)
    comps = sorted(unique.values(), key=lambda c: c["key"])
    for c in comps:
        if not c.get("version") and c["kind"] != "os-package":
            gaps.append(f"{c['source']}: {c['kind']} {c['name']} has no resolved version")
    parsed_hashes = {rel: sha256_file(os.path.join(root, rel)) for rel in parsed}
    fp_material = json.dumps([[[c["key"], c["tier"]] for c in comps], sorted(parsed_hashes.items()),
                              sorted(incomplete.items()), sorted(set(gaps)), truncated], sort_keys=True)
    return {
        "components": comps,
        "gaps": sorted(set(gaps)),
        "limitations": limitations,
        "sources": sources,
        "parsed": sorted(parsed),
        "incomplete": incomplete,
        "truncated": truncated,
        "fingerprint": hashlib.sha256(fp_material.encode()).hexdigest(),
    }


def absence_unproven(inventory: dict[str, Any], comp: dict[str, Any]) -> str | None:
    """Why a component missing from this inventory may still be present; None if absence is shown.

    Absence is shown only when the walk completed and the component's own source
    file was read and parsed successfully without it.
    """
    src = comp["source"]
    if inventory.get("truncated"):
        return f"inventory stopped after {MAX_FILES} files"
    if src in (inventory.get("incomplete") or {}):
        return f"{src}: {inventory['incomplete'][src]}"
    if src not in (inventory.get("parsed") or []):
        return f"{src} is no longer present or readable; removal of the component itself is not shown"
    return None


def component_fingerprint(comp: dict[str, Any]) -> str:
    return hashlib.sha256(f"{comp['key']}|{comp['tier']}".encode()).hexdigest()


def deployment_fingerprint(inventory: dict[str, Any]) -> str:
    """Runtime/image/OS/deployed components plus build and deployment config hashes."""
    keys = sorted(
        (c["key"], c.get("sbom_observed_at"))
        for c in inventory["components"] if c["kind"] != "library" or c["tier"] == "sbom"
    )
    deploy_kinds = ("dockerfile", "compose", "yaml", "workflow")
    srcs = sorted((p, h) for p, h in inventory["sources"].items() if _kind(p) in deploy_kinds)
    return hashlib.sha256(json.dumps([keys, srcs]).encode()).hexdigest()
