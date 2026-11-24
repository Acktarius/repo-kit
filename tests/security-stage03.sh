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
