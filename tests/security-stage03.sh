#!/usr/bin/env bash
# Stage 03: optional finding classification and structured evidence.
# Contract-text checks show instruction consistency, not reviewer compliance.
# Schema checks show record structure, not vulnerability truth.
# Synthetic fixtures only. No network, installs, or target execution.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXT="${ROOT}/extensions/hermesVPS"
SEC="${ROOT}/modules/security/files"
CA="${ROOT}/modules/contre-attaque/files/.cursor/skills/contre-attaque"
SCHEMA="${SEC}/security/findings.schema.json"
CATALOG="${SEC}/security/weakness-classes.md"
INVENTORY="${SEC}/security/surface-inventory.md"

fail=0
ok() { echo "PASS: $*"; }
bad() { echo "FAIL: $*" >&2; fail=1; }

need() {
  command -v "$1" >/dev/null 2>&1 || { echo "FAIL: missing host command $1" >&2; exit 1; }
}
need git
need python3
need cmp
need grep

have() {
  local file="$1" needle="$2" label="$3" flat
  flat="$(tr '\n' ' ' <"${file}")"
  if grep -Fq -- "${needle}" <<<"${flat}"; then
    ok "${label}"
  else
    bad "${label}"
  fi
}

have "${INVENTORY}" \
  "A traceable, unchanged or demonstrably equivalent value may preserve the check." \
  "inventory: equivalent value may preserve a check"
have "${INVENTORY}" \
  "A changed value, or a value whose equivalence is not established, remains \`unresolved\` for that use." \
  "inventory: unestablished equivalence stays unresolved"
have "${INVENTORY}" \
  "authn: unresolved. \`session.User\` at line 44 is the loaded subject" \
  "inventory: session.User is not credential validation"
if grep -Fq "authn: observed, \`session.User\`" "${INVENTORY}"; then
  bad "inventory still treats session.User as credential validation"
else
  ok "inventory dropped the session.User validation claim"
fi

have "${SEC}/.cursor/rules/30-security-reviewer.mdc" \
  "include optional \`weaknessClasses\`" \
  "reviewer proposes optional metadata"
have "${SEC}/.cursor/rules/30-security-reviewer.mdc" \
  "These fields do not lower the valid-finding bar" \
  "reviewer keeps the valid-finding bar"
have "${SEC}/.cursor/rules/40-security-triage.mdc" \
  "shared weakness class as a reason to mark findings" \
  "triage does not dedupe on a class label"
have "${SEC}/security/templates/finding-template.md" \
  "Omit this section when the mapping is uncertain" \
  "finding template marks classification optional"
have "${ROOT}/extensions/hermes/rules/rules_050-source-review.md" \
  "do not write \`security/findings-reviewed.json\`" \
  "local Hermes 050 does not write the reviewed store"
have "${EXT}/rules/rules_050-source-review.md" \
  "do not write \`security/findings-reviewed.json\`" \
  "hermesVPS 050 does not write the reviewed store"
have "${EXT}/rules/rules_070-reviewed-findings.md" \
  "Do not write \`security/findings-reviewed.json\`" \
  "hermesVPS 070 does not write the reviewed store"
have "${CA}/SKILL.md" \
  "an advisory match is not" \
  "contre-attaque does not treat an advisory match as reachability"
have "${SEC}/security/README.md" \
  "Init and sync do not migrate or enrich an existing findings store." \
  "readme documents no automatic migration"

if cmp -s "${SCHEMA}" "${EXT}/security-assets/findings.schema.json"; then
  ok "bundled findings schema matches the canonical file"
else
  bad "bundled findings schema drifted"
fi
if cmp -s "${INVENTORY}" "${EXT}/security-assets/surface-inventory.md"; then
  ok "bundled surface inventory matches the canonical file"
else
  bad "bundled surface inventory drifted"
fi
if cmp -s "${CATALOG}" "${EXT}/security-assets/weakness-classes.md"; then
  ok "bundled weakness catalog matches the canonical file"
else
  bad "bundled weakness catalog drifted"
fi

python3 - "${ROOT}" "${EXT}" "${SCHEMA}" "${CATALOG}" "${CA}/scripts" <<'PY'
import json, os, sys
root, ext, schema_path, catalog_path, ca_scripts = sys.argv[1:]
sys.path.insert(0, ext)
sys.path.insert(0, ca_scripts)
import ca_state
from lib import hermes_vps_common as hv
from lib.hermes_vps_artifacts import _CANONICAL_FIELDS, _check_proposed_metadata
from lib.hermes_vps_phases import PHASE_TABLE
import ca_report

def die(msg):
    raise SystemExit(msg)

catalog_text = open(catalog_path, encoding="utf-8").read()
ids = hv.catalog_class_ids(catalog_text)
if ca_state.catalog_class_ids(catalog_text) != ids:
    die("hermes and contre-attaque catalog parsers disagree")
if ids[0] != "WC-AUTHZ-OBJECT" or "WC-SECURITY-CONFIG" not in ids or len(ids) != len(set(ids)):
    die(f"catalog headings unusable: {ids}")

schema = json.load(open(schema_path, encoding="utf-8"))
item = schema["properties"]["findings"]["items"]["properties"]["weaknessClasses"]["items"]
if "enum" in item:
    if item["enum"] != ids:
        die("schema weaknessClasses enum drifted from catalog headings")
finding_schema = schema["properties"]["findings"]["items"]
if finding_schema.get("additionalProperties") is not False:
    die("finding additionalProperties is no longer closed")
if finding_schema["properties"]["status"]["enum"] != [
    "open", "fixed", "accepted-risk", "duplicate", "rejected"
]:
    die("finding status enum changed")
for phase in ("050", "070"):
    if "security-assets/weakness-classes.md" not in PHASE_TABLE[phase].policy_files:
        die(f"phase {phase} cannot read the weakness catalog")
if "security-assets/weakness-classes.md" in PHASE_TABLE["060"].policy_files:
    die("phase 060 was given the catalog without a proposal role")

def legacy():
    return {
        "id": "SG-001", "title": "Synthetic legacy", "status": "open",
        "severity": "low", "files": ["pkg/synthetic.go"],
    }

def sink(note="Synthetic note establishing the gap.", start=40, end=44, **extra):
    ref = {"file": "pkg/synthetic.go", "symbol": "GetOrder", "note": note}
    if start is not None:
        ref["startLine"] = start
    if end is not None:
        ref["endLine"] = end
    ref.update(extra)
    return {
        "entryPoint": "Synthetic HTTP handler GetOrder",
        "flow": "Synthetic caller-supplied order id reaches the load",
        "sensitiveOperation": "Synthetic load of one order row",
        "controlGap": "Synthetic owner check uses a different id",
        "evidence": [ref],
    }

def store(finding):
    return {"repo": "synthetic", "lastReviewed": None, "findings": [finding]}

def check(doc, label):
    try:
        hv.validate_findings_document(doc, schema, ids, label)
        ca_state.validate_findings_document(doc, schema, ids, label)
    except (hv.ValidationError, ca_state.StateError) as exc:
        die(f"{label} should validate: {exc}")

def reject(doc, label, needle):
    saw = []
    for mod, err in ((hv, hv.ValidationError), (ca_state, ca_state.StateError)):
        try:
            mod.validate_findings_document(doc, schema, ids, label)
        except err as exc:
            text = str(exc)
            if needle not in text:
                die(f"{label} via {mod.__name__} rejected without {needle!r}: {text}")
            saw.append(mod.__name__)
        else:
            die(f"{label} via {mod.__name__} was accepted")
    if saw != ["lib.hermes_vps_common", "ca_state"] and saw != ["hermes_vps_common", "ca_state"]:
        # Module __name__ is the import name. Either pair is fine if both rejected.
        if len(saw) != 2:
            die(f"{label} did not reject in both validators: {saw}")

check(store(legacy()), "legacy")
classified = legacy()
classified["weaknessClasses"] = ["WC-AUTHZ-OBJECT"]
classified["entrySink"] = sink()
check(store(classified), "classified")
multi = legacy()
multi["id"] = "SG-002"
multi["weaknessClasses"] = ["WC-AUTHZ-OBJECT", "WC-AUTHN"]
check(store(multi), "multiple classes")
all_classes = legacy()
all_classes["id"] = "SG-003"
all_classes["weaknessClasses"] = list(ids)
check(store(all_classes), "every catalog heading")

unknown = legacy()
unknown["weaknessClasses"] = ["WC-NOT-A-CLASS"]
try:
    hv.validate_schema(store(unknown), schema, "schema-only")
except hv.ValidationError as exc:
    die(f"JSON Schema alone rejected an unknown WC id; membership must stay in validate_finding_metadata: {exc}")
reject(store(unknown), "unknown class", "not a catalog")

dup = legacy()
dup["weaknessClasses"] = ["WC-AUTHN", "WC-AUTHN"]
reject(store(dup), "duplicate class", "duplicate")

empty = legacy()
empty["weaknessClasses"] = []
reject(store(empty), "empty classes", "at least 1")

incomplete = legacy()
incomplete["entrySink"] = sink()
del incomplete["entrySink"]["controlGap"]
reject(store(incomplete), "incomplete entrySink", "controlGap")

blank = legacy()
blank["entrySink"] = sink(note="   ")
reject(store(blank), "whitespace note", "does not match")
empty_note = legacy()
empty_note["entrySink"] = sink(note="")
reject(store(empty_note), "empty note", "does not match")

zero = legacy()
zero["entrySink"] = sink(start=0, end=1)
reject(store(zero), "non-positive line", "minimum")

one_sided = legacy()
one_sided["entrySink"] = sink(start=10, end=None)
try:
    hv.validate_schema(store(one_sided), schema, "schema-only-lines")
except hv.ValidationError as exc:
    die(f"JSON Schema alone rejected a one-sided line range: {exc}")
reject(store(one_sided), "one-sided lines", "supplied together")

reversed_range = legacy()
reversed_range["entrySink"] = sink(start=12, end=4)
try:
    hv.validate_schema(store(reversed_range), schema, "schema-only-order")
    ca_state.validate_schema(store(reversed_range), schema, "schema-only-order")
except (hv.ValidationError, ca_state.StateError) as exc:
    die(f"JSON Schema alone rejected a reversed line range: {exc}")
reject(store(reversed_range), "reversed range", "before startLine")

bad_status = legacy()
bad_status["status"] = "closed"
reject(store(bad_status), "bad status", "not in")

extra = legacy()
extra["coverage"] = "complete"
reject(store(extra), "extra field", "unexpected field")

ctx = {"policy_prefix": ext}
try:
    _check_proposed_metadata(ctx, {"weaknessClasses": ["WC-NOT-A-CLASS"]}, "payload.proposed_finding")
except hv.ValidationError as exc:
    if "not a catalog" not in str(exc):
        die(f"phase 070 metadata check gave an unexpected error: {exc}")
else:
    die("phase 070 metadata check accepted an unknown class")
_check_proposed_metadata(ctx, {
    "weaknessClasses": ["WC-FILE-ACCESS"],
    "entrySink": sink(),
}, "payload.proposed_finding")

proposed = {
    "title": "Synthetic", "status": "open", "severity": "low", "files": ["pkg/synthetic.go"],
    "weaknessClasses": ["WC-FILE-ACCESS"], "entrySink": sink(),
    "assessment_disposition": "confirmed",
}
copied = {k: v for k, v in proposed.items() if k in _CANONICAL_FIELDS}
if copied.get("weaknessClasses") != ["WC-FILE-ACCESS"] or copied.get("entrySink") != sink():
    die("findings export dropped optional metadata")
if "assessment_disposition" in copied:
    die("findings export copied a non-canonical field")

cand = {
    "candidate_id": "CA-0123456789", "canonical_id": "CVE-2026-0001", "aliases": ["CVE-2026-0001"],
    "component": {"name": "synthetic-lib", "version": "1.0.0", "kind": "library", "tier": "direct",
                  "source": "go.mod"},
    "sources": [{"provider": "osv", "id": "CVE-2026-0001"}], "fixed_versions": [], "kev": None,
    "first_seen_utc": "2026-01-01T00:00:00Z", "severity": "medium",
}
assessment = {
    "applicability": "affected", "rationale": "Synthetic advisory assessment.", "confidence": "medium",
    "evidence": [], "unknowns": [], "decided_at_utc": "2026-01-02T00:00:00Z", "decided_by": "agent",
    "exploit_path": None,
}
run = {"run_id": "run-synthetic", "git": {"commit": "a" * 40}}
plain = ca_report.build_record(cand, assessment, run, "SG-100")
if "weaknessClasses" in plain or "entrySink" in plain:
    die("advisory record invented classification or a local source flow")
carried = dict(assessment)
carried["weaknessClasses"] = ["WC-SUPPLY-CHAIN"]
carried["entrySink"] = sink()
rich = ca_report.build_record(cand, carried, run, "SG-100")
if rich.get("weaknessClasses") != ["WC-SUPPLY-CHAIN"] or rich.get("entrySink") != sink():
    die("advisory handoff dropped supported metadata")
kept = dict(rich)
kept["weaknessClasses"] = ["WC-AUTHN"]
refresh = ca_report.build_record(cand, assessment, run, "SG-100")
kept.update(refresh)
if kept.get("weaknessClasses") != ["WC-AUTHN"]:
    die("refresh without a class replaced human classification")
print("PASS: schema, catalog membership, export, and advisory handoff")

# Path policy. JSON Schema accepts these strings; both metadata validators decide.
legacy_abs = legacy()
legacy_abs["files"] = ["/etc/passwd"]
check(store(legacy_abs), "legacy files path is not under the new policy")
traversed = legacy()
traversed["entrySink"] = sink()
traversed["entrySink"]["evidence"][0]["file"] = "../secret"
try:
    hv.validate_schema(store(traversed), schema, "schema-only-path")
    ca_state.validate_schema(store(traversed), schema, "schema-only-path")
except (hv.ValidationError, ca_state.StateError) as exc:
    die(f"JSON Schema alone rejected an evidence path: {exc}")
reject(store(traversed), "traversal path", "component")

path_cases = [
    ("pkg/nested/file.go", None),
    ("pkg/my file.go", None),
    ("pkg/café.go", None),
    ("pkg/config..example", None),
    ("pkg/../secret", "contains a '..' component"),
    ("/etc/passwd", "is absolute"),
    ("C:/Windows/system.ini", "is a URI or drive-qualified path"),
    ("C:relative.ini", "is a URI or drive-qualified path"),
    ("\\\\server\\share\\file", "contains a backslash"),
    ("https://example.test/a", "is a URI or drive-qualified path"),
    ("pkg/bad\nname.go", "contains a control character"),
    ("pkg/bad\x00name.go", "contains a control character"),
    ("pkg//nested.go", "has an empty component"),
    ("pkg/nested.go/", "has an empty component"),
    ("./pkg/nested.go", "contains a '.' component"),
    ("", "empty or whitespace-only"),
    ("   ", "empty or whitespace-only"),
]
for path, expected in path_cases:
    left = hv.evidence_path_error(path)
    right = ca_state.evidence_path_error(path)
    if left != right:
        die(f"path policy drift for {path!r}: {left!r} vs {right!r}")
    if expected is None and left is not None:
        die(f"path {path!r} should be valid, got {left!r}")
    if expected is not None and left != expected:
        die(f"path {path!r} should be {expected!r}, got {left!r}")
print("PASS: evidence-path policy matches on both validators")

import tempfile
catalog_dir = tempfile.mkdtemp(prefix="stage03-catalog-")
try:
    missing = os.path.join(catalog_dir, "missing.md")
    for loader, err in ((hv.load_catalog_ids, hv.ValidationError), (ca_state.catalog_ids_for_document, ca_state.StateError)):
        try:
            if loader is hv.load_catalog_ids:
                loader(missing)
            else:
                loader(catalog_dir, [{"weaknessClasses": ["WC-AUTHN"]}])
        except err as exc:
            if "missing" not in str(exc):
                die(f"missing catalog error was {exc}")
        else:
            die("missing catalog was accepted")
    empty = os.path.join(catalog_dir, "empty.md")
    with open(empty, "w", encoding="utf-8") as fh:
        fh.write("no headings\n")
    dup = os.path.join(catalog_dir, "dup.md")
    with open(dup, "w", encoding="utf-8") as fh:
        fh.write("### WC-AUTHN\n\n### WC-AUTHN\n")
    bad = os.path.join(catalog_dir, "bad.md")
    with open(bad, "wb") as fh:
        fh.write(b"### WC-AUTHN\n\xff\n")
    for path, needle in ((empty, "no ### WC-"), (dup, "duplicate"), (bad, "not valid UTF-8")):
        for loader, err in ((hv.load_catalog_ids, hv.ValidationError),):
            try:
                loader(path)
            except err as exc:
                if needle not in str(exc):
                    die(f"{path} via hermes: {exc}")
            else:
                die(f"{path} was accepted by hermes")
        try:
            saved = os.path.join(catalog_dir, "security")
            os.makedirs(saved, exist_ok=True)
            os.replace(path, os.path.join(saved, "weakness-classes.md"))
            ca_state.catalog_ids_for_document(catalog_dir, [{"weaknessClasses": ["WC-AUTHN"]}])
        except ca_state.StateError as exc:
            if needle not in str(exc):
                die(f"{path} via contre-attaque: {exc}")
        else:
            die(f"{path} was accepted by contre-attaque")
        os.replace(os.path.join(saved, "weakness-classes.md"), path)
    unread = os.path.join(catalog_dir, "unread.md")
    with open(unread, "w", encoding="utf-8") as fh:
        fh.write("### WC-AUTHN\n")
    ca_root = os.path.join(catalog_dir, "ca-root")
    ca_unread = os.path.join(ca_root, "security", "weakness-classes.md")
    os.makedirs(os.path.dirname(ca_unread), exist_ok=True)
    with open(ca_unread, "w", encoding="utf-8") as fh:
        fh.write("### WC-AUTHN\n")
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        print("SKIP: unreadable catalog omitted while running as root")
    else:
        os.chmod(unread, 0)
        os.chmod(ca_unread, 0)
        try:
            checks = (
                ("hermes", hv.ValidationError, lambda: hv.load_catalog_ids(unread)),
                ("contre-attaque", ca_state.StateError, lambda: ca_state.catalog_ids_for_document(
                    ca_root, [{"weaknessClasses": ["WC-AUTHN"]}])),
            )
            for label, err, fn in checks:
                try:
                    fn()
                except err as exc:
                    if "unreadable" not in str(exc):
                        die(f"unreadable catalog via {label}: {exc}")
                else:
                    die(f"unreadable catalog was accepted by {label}")
            print("PASS: unreadable catalog rejected by both loaders")
        finally:
            os.chmod(unread, 0o644)
            os.chmod(ca_unread, 0o644)
    only_sink = legacy()
    only_sink["entrySink"] = sink()
    if ca_state.catalog_ids_for_document(catalog_dir, [only_sink]) != []:
        die("entrySink-only record required a catalog")
    check({"repo": "synthetic", "lastReviewed": None, "findings": [only_sink]}, "entrySink without a class")
finally:
    import shutil
    for rel in ("unread.md", "ca-root/security/weakness-classes.md"):
        path = os.path.join(catalog_dir, rel)
        if os.path.exists(path):
            os.chmod(path, 0o644)
    shutil.rmtree(catalog_dir, ignore_errors=True)
print("PASS: catalog errors stay on the validation path")
PY

python3 - "${ROOT}" "${EXT}" <<'PY'
import json, os, shutil, subprocess, sys, tempfile
root, ext = sys.argv[1:]
stamp = os.path.join(root, "tests", "hermes_vps_stamp.py")
artifacts = os.path.join(ext, "bin", "hermes-vps-artifacts")
review = os.path.join(ext, "bin", "hermes-vps-review")
env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

def die(msg):
    raise SystemExit(msg)

class Run:
    def __init__(self, name):
        self.base = tempfile.mkdtemp(prefix=f"stage03-{name}-")
        self.policy = os.path.join(self.base, "policy")
        self.src = os.path.join(self.base, "src")
        self.run_root = os.path.join(self.base, "run")
        self.work = os.path.join(self.base, "work")
        shutil.copytree(ext, self.policy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        os.makedirs(os.path.join(self.run_root, "reports"))
        os.makedirs(self.work)
        os.makedirs(self.src)
        subprocess.run(["git", "-C", self.src, "init", "-q"], check=True)
        subprocess.run(["git", "-C", self.src, "config", "user.email", "t@example.com"], check=True)
        subprocess.run(["git", "-C", self.src, "config", "user.name", "T"], check=True)
        with open(os.path.join(self.src, "README.md"), "w", encoding="utf-8") as fh:
            fh.write("synthetic\n")
        subprocess.run(["git", "-C", self.src, "add", "README.md"], check=True)
        subprocess.run(["git", "-C", self.src, "commit", "-q", "-m", "init"], check=True)
        self.sha = subprocess.run(["git", "-C", self.src, "rev-parse", "HEAD"], check=True,
                                  capture_output=True, text=True).stdout.strip()
        self.run_json = os.path.join(self.run_root, "run.json")
        self._write(self.run_json, {
            "schema_version": 1, "run_id": "run-stage03", "policy_prefix": self.policy,
            "source": {"path": self.src, "identity": "fixture/stage03", "commit": self.sha,
                       "require_clean_worktree": True},
            "output": {"run_root": self.run_root},
            "phase_request": {"phase": "010", "phase_name": "inventory", "requested_by": "test",
                              "requested_at_utc": "2026-11-23T00:00:00Z"},
            "prerequisites": {"artifacts": []},
            "boundaries": {"claims_os_readonly_source": False, "allowed_write_roots": [self.run_root]},
            "toolkit": {"toolkit_revision": "stage03", "toolkit_dirty": False},
        })
        self.n = 0

    def close(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def _write(self, path, data):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
            fh.write("\n")
        return path

    def report(self, title, state="complete"):
        self.n += 1
        path = os.path.join(self.work, f"report-{self.n}.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"# {title}\n\nSynthetic.\n\nState: `{state}`\n")
        return path

    def payload(self, data):
        self.n += 1
        return self._write(os.path.join(self.work, f"payload-{self.n}.json"), data)

    def manifest(self):
        path = os.path.join(self.run_root, "manifest.json")
        if not os.path.isfile(path):
            return {"artifacts": []}
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def reports(self):
        return sorted(os.listdir(os.path.join(self.run_root, "reports")))

    def stamp(self, report, phase, subject=None):
        args = [sys.executable, stamp, review, "register", "--run-json", self.run_json,
                "--phase", phase, "--source-report", report]
        if subject:
            args += ["--subject-id", subject]
        subprocess.run(args, check=True, env=env)

    def register(self, phase, report, payload=None, subject=None):
        self.stamp(report, phase, subject)
        args = [artifacts, "register", "--run-json", self.run_json, "--phase", phase, "--source-report", report]
        if subject:
            args += ["--subject-id", subject]
        if payload is not None:
            args += ["--payload-json", payload if isinstance(payload, str) else self.payload(payload)]
        return subprocess.run(args, capture_output=True, text=True, env=env)

    def prepare(self):
        for phase in ("010", "020"):
            res = self.register(phase, self.report(phase))
            if res.returncode != 0:
                die(f"setup {phase} failed: {res.stderr}")
        res = self.register("050", self.report("050"), subject="synthetic-priority")
        if res.returncode != 0:
            die(f"setup 050 failed: {res.stderr}")
        triage = {"schema_version": 1, "phase": "060", "source_commit": self.sha,
                  "candidates": [{"candidate_id": "C-001", "title": "Synthetic", "disposition": "validated-new"}]}
        res = self.register("060", self.report("060"), triage)
        if res.returncode != 0:
            die(f"setup 060 failed: {res.stderr}")

    def finding(self, **extra):
        proposed = {"title": "Synthetic finding", "status": "open", "severity": "medium",
                    "files": ["pkg/synthetic.go"]}
        proposed.update(extra)
        return {"schema_version": 1, "phase": "070", "candidate_id": "C-001", "source_commit": self.sha,
                "assessment_disposition": "confirmed", "assessment_rationale": "Synthetic rationale",
                "proposed_finding": proposed}

sink = {
    "entryPoint": "Synthetic handler",
    "flow": "Synthetic caller-supplied id reaches the load",
    "sensitiveOperation": "Synthetic load of one row",
    "controlGap": "Synthetic owner check uses a different id",
    "evidence": [{
        "file": "pkg/café.go", "symbol": "GetOrder", "startLine": 40, "endLine": 44,
        "note": "Synthetic reference. Not a real repository.",
    }],
}

def attempt(name, proposed_extra, commit=None, expect_ok=False):
    run = Run(name)
    try:
        run.prepare()
        before_arts = [a["id"] for a in run.manifest()["artifacts"]]
        before_reports = run.reports()
        payload = run.finding(**proposed_extra)
        if commit is not None:
            payload["source_commit"] = commit
        res = run.register("070", run.report("070"), payload, subject="C-001")
        after_arts = [a["id"] for a in run.manifest()["artifacts"]]
        target_store = os.path.join(run.src, "security", "findings-reviewed.json")
        if os.path.exists(target_store):
            die(f"{name} wrote a target findings store")
        if expect_ok:
            if res.returncode != 0:
                die(f"{name} register failed: {res.stderr}")
            arts = [a for a in run.manifest()["artifacts"] if a.get("phase") == "070"]
            if len(arts) != 1:
                die(f"{name} did not register exactly one phase 070 artifact")
            payload_path = os.path.join(run.run_root, arts[0]["payload_path"])
            saved = json.load(open(payload_path, encoding="utf-8"))
            if saved["proposed_finding"].get("weaknessClasses") != proposed_extra.get("weaknessClasses"):
                die(f"{name} registered payload dropped weaknessClasses")
            if saved["proposed_finding"].get("entrySink") != proposed_extra.get("entrySink"):
                die(f"{name} registered payload dropped entrySink")
            exports = [a for a in run.manifest()["artifacts"] if a.get("kind") == "findings_export"]
            if len(exports) != 1:
                die(f"{name} did not register one findings export")
            export = json.load(open(os.path.join(run.run_root, exports[0]["path"]), encoding="utf-8"))
            record = export["findings"][0]["proposed_record"]
            if record.get("weaknessClasses") != ["WC-SUPPLY-CHAIN"] or record.get("entrySink", {}).get("evidence", [{}])[0].get("file") != "pkg/café.go":
                die(f"{name} export dropped metadata: {record}")
            return
        if res.returncode == 0:
            die(f"{name} register succeeded")
        if after_arts != before_arts:
            die(f"{name} left a registered artifact behind: {after_arts}")
        if run.reports() != before_reports:
            die(f"{name} left report files behind")
        if any(name.startswith("findings-") for name in run.reports()):
            die(f"{name} left a findings export behind")
    finally:
        run.close()

attempt("ok", {"weaknessClasses": ["WC-SUPPLY-CHAIN"], "entrySink": sink}, expect_ok=True)
attempt("unknown-class", {"weaknessClasses": ["WC-NOT-A-CLASS"]})
attempt("bad-path", {"entrySink": {**sink, "evidence": [{**sink["evidence"][0], "file": "../secret"}]}})
attempt("bad-range", {"entrySink": {**sink, "evidence": [{**sink["evidence"][0], "startLine": 12, "endLine": 4}]}})
attempt("wrong-commit", {"weaknessClasses": ["WC-SUPPLY-CHAIN"]}, commit="0" * 40)

run = Run("broken-catalog")
try:
    catalog = os.path.join(run.policy, "security-assets", "weakness-classes.md")
    with open(catalog, "wb") as fh:
        fh.write(b"\xff")
    run.prepare()
    before = [a["id"] for a in run.manifest()["artifacts"]]
    res = run.register("070", run.report("070"), run.finding(weaknessClasses=["WC-SUPPLY-CHAIN"]), subject="C-001")
    if res.returncode == 0 or [a["id"] for a in run.manifest()["artifacts"]] != before:
        die(f"broken catalog registered a classified payload: {res.stderr}")
    if "UTF-8" not in res.stderr and "not valid UTF-8" not in res.stderr:
        die(f"broken catalog error was not explicit: {res.stderr}")
    plain = run.register("070", run.report("070 plain"), run.finding(), subject="C-001")
    if plain.returncode != 0:
        die(f"unclassified payload required a readable catalog: {plain.stderr}")
finally:
    run.close()
print("PASS: phase 070 registration and findings export keep or reject metadata")
PY

TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT
TARGET="${TMP}/target"
mkdir -p "${TARGET}"
git -C "${TARGET}" init -q
"${ROOT}/scripts/init.sh" "${TARGET}" --security >/dev/null
FINDINGS="${TARGET}/security/findings-reviewed.json"
python3 - "${FINDINGS}" <<'PY'
import json, sys
doc = {
    "repo": "synthetic-user",
    "lastReviewed": "2026-01-01T00:00:00Z",
    "findings": [{
        "id": "SG-007",
        "title": "Synthetic user finding",
        "status": "open",
        "severity": "low",
        "files": ["pkg/user.go"],
    }],
}
with open(sys.argv[1], "w", encoding="utf-8") as fh:
    json.dump(doc, fh, indent=2)
    fh.write("\n")
PY
before="$(sha256sum "${FINDINGS}")"
init_out="$("${ROOT}/scripts/init.sh" "${TARGET}" --security --force)"
sync_out="$("${ROOT}/scripts/sync-cursor.sh" "${TARGET}" --security --force)"
after="$(sha256sum "${FINDINGS}")"
if [[ "${before}" != "${after}" ]]; then
  bad "init/sync changed a user findings store"
else
  ok "init/sync preserved the user findings store"
fi
if ! grep -Fq "preserve   security/findings-reviewed.json" <<<"${init_out}${sync_out}"; then
  bad "init/sync did not report the findings store as preserved"
else
  ok "init/sync reported the findings store as preserved"
fi
if ! python3 - "${FINDINGS}" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
finding = doc["findings"][0]
raise SystemExit(0 if finding["id"] == "SG-007" and "weaknessClasses" not in finding else 1)
PY
then
  bad "preserved finding was rewritten or enriched"
else
  ok "preserved finding was not enriched"
fi

if [[ "${fail}" -ne 0 ]]; then
  echo "security-stage03: FAILED" >&2
  exit 1
fi
echo "security-stage03: OK"
