#!/usr/bin/env bash
# CLI checks for the offline Gitleaks JSON normalizer. Synthetic reports only.
# No scanner invocation, network, or target checkout writes.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 - "${ROOT}" <<'PY'
import importlib.util, json, os, stat, subprocess, sys, tempfile

root = sys.argv[1]
util = os.path.join(root, "modules", "security", "files", "security", "gitleaks_handoff.py")
spec = importlib.util.spec_from_file_location("gitleaks_handoff", util)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

sys.path.insert(0, os.path.join(root, "extensions", "hermesVPS"))
from lib.hermes_vps_common import evidence_path_error as hv_path
ca_dir = os.path.join(
    root, "modules", "contre-attaque", "files", ".cursor", "skills",
    "contre-attaque", "scripts")
sys.path.insert(0, ca_dir)
ca_path = os.path.join(ca_dir, "ca_state.py")
ca_spec = importlib.util.spec_from_file_location("ca_state", ca_path)
ca_mod = importlib.util.module_from_spec(ca_spec)
ca_spec.loader.exec_module(ca_mod)

MARKER = "SYNTHETIC_SECRET_MARKER_04B"
fail = 0

def bad(msg):
    global fail
    fail = 1
    print(f"FAIL: {msg}", file=sys.stderr)

def ok(msg):
    print(f"PASS: {msg}")

paths = [
    "auth.py", "pkg/my file.go", "pkg/café.go", "pkg/config..example",
    "/etc/passwd", "C:/Windows/system.ini", "C:relative.ini",
    "\\\\server\\share\\file", "https://example.test/a", "pkg/bad\nname.go",
    "pkg//nested.go", "pkg/nested.go/", "./pkg/nested.go", "pkg/../secret",
    "", "   ",
]
for path in paths:
    left = mod.evidence_path_error(path)
    if left != hv_path(path) or left != ca_mod.evidence_path_error(path):
        bad(f"path policy drift for {path!r}: {left!r}")
        break
else:
    ok("handoff path policy matches both validators")

base = [
    sys.executable, util,
    "--check-id", "P-1",
    "--source-revision", "unknown",
    "--working-tree", "clean",
    "--tool-version", "unknown",
    "--rules-identity", "unknown",
    "--report-provenance", "synthetic-report",
    "--scanner-outcome", "unknown",
]

def run(report, outcome="unknown", check="P-1", out_name="handoff.json",
        input_path=None, output_path=None, extra=None, prewrite=None):
    tmp = tempfile.mkdtemp(prefix="stage04b-")
    findings = os.path.join(tmp, "findings-reviewed.json")
    with open(findings, "w", encoding="utf-8") as fh:
        fh.write('{"findings":[]}\n')
    before = open(findings, "rb").read()
    src = input_path or os.path.join(tmp, "report.json")
    dst = output_path or os.path.join(tmp, out_name)
    if input_path is None:
        mode = "wb" if isinstance(report, bytes) else "w"
        with open(src, mode) as fh:
            fh.write(report)
    report_before = open(src, "rb").read() if os.path.isfile(src) and not os.path.islink(src) else None
    if prewrite:
        prewrite(dst)
    args = base + ["--input", src, "--output", dst, "--scanner-outcome", outcome, "--check-id", check]
    if extra:
        args.extend(extra)
    proc = subprocess.run(args, capture_output=True, timeout=5)
    return proc, src, dst, tmp, before, findings, report_before

def combined(proc):
    return proc.stdout + proc.stderr

def no_marker(proc, dst, label):
    blob = combined(proc)
    if MARKER.encode() in blob:
        bad(f"{label}: marker reached stdout or stderr")
        return False
    if os.path.exists(dst):
        if MARKER.encode() in open(dst, "rb").read():
            bad(f"{label}: marker reached the handoff")
            return False
    return True

def finding(rule="rule-a", path="pkg/a.py", **extra):
    item = {
        "RuleID": rule,
        "Description": MARKER,
        "StartLine": 3,
        "EndLine": 4,
        "Match": MARKER,
        "Secret": MARKER,
        "File": path,
        "Message": MARKER,
        "Tags": [MARKER],
        "Fingerprint": MARKER,
        "Line": MARKER,
        "Mystery": MARKER,
    }
    item.update(extra)
    return item

proc, src, dst, tmp, before, findings, report_before = run(json.dumps([
    finding("rule-a", "pkg/a.py"),
    finding("rule-b", "pkg/my file.go", StartLine=8, EndLine=9, File="pkg/café.go"),
]))
if proc.returncode != 0 or proc.stdout or not no_marker(proc, dst, "multiple"):
    bad(f"multiple leads failed: {proc.returncode} {proc.stderr!r}")
else:
    data = json.loads(open(dst, encoding="utf-8").read())
    if data["parsingOutcome"] != "normalized" or data["declaredScannerOutcome"] != "unknown":
        bad("multiple leads mixed outcomes")
    elif [lead["leadId"] for lead in data["leads"]] != ["L-001", "L-002"]:
        bad("lead ids changed")
    elif data["leads"][1]["location"]["path"] != "pkg/café.go":
        bad("unicode path was not kept")
    elif data["callerSupplied"]["approved"] or data["callerSupplied"]["verified"]:
        bad("caller claims were treated as approved or verified")
    elif "SG-" in open(dst, encoding="utf-8").read() or "entrySink" in data["leads"][0]:
        bad("handoff invented finding fields")
    elif stat.S_IMODE(os.stat(dst).st_mode) != 0o600:
        bad(f"handoff mode is {oct(stat.S_IMODE(os.stat(dst).st_mode))}")
    elif open(findings, "rb").read() != before or open(src, "rb").read() != report_before:
        bad("source report or findings store changed")
    else:
        ok("multiple leads stay secret-minimized and unreviewed")

proc, src, dst, tmp, before, findings, _ = run("[]\n")
if proc.returncode != 0:
    bad(f"empty report failed: {proc.stderr!r}")
else:
    data = json.loads(open(dst, encoding="utf-8").read())
    if data["parsingOutcome"] != "empty" or data["declaredScannerOutcome"] != "unknown" or data["leads"]:
        bad("empty report was treated as a completed scan")
    else:
        ok("empty report keeps an unknown scanner outcome")

proc, src, dst, tmp, *_ = run(json.dumps([{"RuleID": "rule-a", "File": "a.py", "Secret": MARKER}]).encode() + b"\xff")
if proc.returncode != mod.EXIT_MALFORMED or b"invalid UTF-8" not in proc.stderr or os.path.exists(dst):
    bad(f"invalid UTF-8: {proc.returncode} {proc.stderr!r}")
elif not no_marker(proc, dst, "utf8"):
    pass
else:
    ok("invalid UTF-8 fails closed")

proc, src, dst, *_ = run('[{"RuleID":"rule-a","File":"a.py","Secret":"%s","Secret":"x"}]' % MARKER)
if proc.returncode != mod.EXIT_MALFORMED or b"duplicate JSON key" not in proc.stderr or os.path.exists(dst):
    bad(f"duplicate key: {proc.returncode} {proc.stderr!r}")
elif not no_marker(proc, dst, "duplicate"):
    pass
else:
    ok("duplicate keys fail closed")

nested = '[{"RuleID":"rule-a","File":"a.py","Nested":' + ("[" * 40) + '"%s"' % MARKER + ("]" * 40) + "}]"
proc, src, dst, *_ = run(nested)
if proc.returncode != mod.EXIT_MALFORMED or b"excessive nesting" not in proc.stderr or os.path.exists(dst):
    bad(f"nesting: {proc.returncode} {proc.stderr!r}")
elif not no_marker(proc, dst, "nesting"):
    pass
else:
    ok("excessive nesting fails closed")

proc, src, dst, *_ = run('{"Secret":"%s"}' % MARKER)
if proc.returncode != mod.EXIT_UNSUPPORTED or b"unsupported format" not in proc.stderr or os.path.exists(dst):
    bad(f"root object: {proc.returncode} {proc.stderr!r}")
elif not no_marker(proc, dst, "root"):
    pass
else:
    ok("non-array root is an unsupported format")

proc, src, dst, *_ = run('["%s"]' % MARKER)
if proc.returncode != mod.EXIT_MALFORMED or b"malformed record" not in proc.stderr or os.path.exists(dst):
    bad(f"record shape: {proc.returncode} {proc.stderr!r}")
elif not no_marker(proc, dst, "record"):
    pass
else:
    ok("a non-object record is malformed")

proc, src, dst, *_ = run("{")
if proc.returncode != mod.EXIT_MALFORMED or b"malformed JSON" not in proc.stderr or os.path.exists(dst):
    bad(f"malformed JSON: {proc.returncode} {proc.stderr!r}")
else:
    ok("malformed JSON leaves no handoff")

fat_rule = "R" * (mod.MAX_COPIED_STRING + 1)
proc, src, dst, *_ = run(json.dumps([{"RuleID": MARKER + fat_rule, "File": "a.py"}]))
if proc.returncode != mod.EXIT_LIMIT or b"limit exceeded: copied string" not in proc.stderr or os.path.exists(dst):
    bad(f"copied string: {proc.returncode} {proc.stderr!r}")
elif not no_marker(proc, dst, "copied"):
    pass
else:
    ok("an oversized copied field fails closed")

proc, src, dst, *_ = run(json.dumps([
    {"RuleID": "r", "File": "a.py", "Secret": MARKER} for _ in range(mod.MAX_RECORDS + 1)
]))
if proc.returncode != mod.EXIT_LIMIT or b"limit exceeded: records" not in proc.stderr or os.path.exists(dst):
    bad(f"record limit: {proc.returncode} {proc.stderr!r}")
elif not no_marker(proc, dst, "records"):
    pass
else:
    ok("too many records fails closed")

long_path = "dir/" + ("n" * 240) + ".py"
proc, src, dst, *_ = run(json.dumps([
    {"RuleID": "R" * mod.MAX_COPIED_STRING, "File": long_path, "Secret": MARKER,
     "StartLine": 1, "EndLine": 1}
    for _ in range(100)
]))
if proc.returncode != mod.EXIT_LIMIT or b"limit exceeded: output" not in proc.stderr or os.path.exists(dst):
    bad(f"output limit: {proc.returncode} {proc.stderr!r}")
elif not no_marker(proc, dst, "output limit"):
    pass
else:
    ok("oversized output fails closed")

blob = b"[" + MARKER.encode() + (b"x" * (mod.MAX_INPUT_BYTES + 1))
proc, src, dst, *_ = run(blob)
if proc.returncode != mod.EXIT_LIMIT or b"limit exceeded: input bytes" not in proc.stderr or os.path.exists(dst):
    bad(f"input limit: {proc.returncode} {proc.stderr!r}")
elif not no_marker(proc, dst, "input limit"):
    pass
else:
    ok("oversized input fails closed")

locations = [
    ("/etc/passwd", True),
    ("pkg/../" + MARKER, True),
    ("https://example.test/" + MARKER, True),
    ("pkg/my file.go", False),
    ("pkg/café.go", False),
]
report = []
for path, _omitted in locations:
    report.append({"RuleID": "rule-a", "Secret": MARKER, "File": path, "StartLine": 4, "EndLine": 2})
report.append({"RuleID": "rule-a", "Secret": MARKER, "StartLine": 1, "EndLine": 1})
report.append({"Secret": MARKER, "File": "pkg/a.py"})
proc, src, dst, *_ = run(json.dumps(report))
if proc.returncode != 0 or not no_marker(proc, dst, "locations"):
    bad(f"locations: {proc.returncode} {proc.stderr!r}")
else:
    data = json.loads(open(dst, encoding="utf-8").read())
    omitted = [lead["location"]["status"] == "unavailable" for lead in data["leads"]]
    if omitted != [True, True, True, False, False, True, False]:
        bad(f"location decisions changed: {omitted}")
    elif any("lineRange" in lead for lead in data["leads"][:5]):
        bad("reversed or unsafe records kept a line range")
    elif data["counts"]["leads"] != 7 or data["counts"]["locationsOmitted"] != 4:
        bad(f"omitted locations dropped a lead: {data['counts']}")
    elif data["leads"][3]["location"]["path"] != "pkg/my file.go":
        bad("spaced path was not kept")
    else:
        ok("unsafe locations stay on the lead without the raw path")

# Symlink, fifo, existing output, alias, missing parent.
tmp = tempfile.mkdtemp(prefix="stage04b-fs-")
report_path = os.path.join(tmp, "report.json")
with open(report_path, "w", encoding="utf-8") as fh:
    fh.write("[]\n")
link = os.path.join(tmp, "linked.json")
os.symlink(report_path, link)
proc = subprocess.run(base + ["--input", link, "--output", os.path.join(tmp, "out.json")],
                      capture_output=True, timeout=5)
if proc.returncode != mod.EXIT_IO or b"input is a symlink" not in proc.stderr:
    bad(f"symlink input: {proc.returncode} {proc.stderr!r}")
else:
    ok("symlink input is rejected")

fifo = os.path.join(tmp, "pipe.json")
os.mkfifo(fifo)
proc = subprocess.run(base + ["--input", fifo, "--output", os.path.join(tmp, "out.json")],
                      capture_output=True, timeout=5)
if proc.returncode != mod.EXIT_IO or b"input is not a regular file" not in proc.stderr:
    bad(f"fifo input: {proc.returncode} {proc.stderr!r}")
else:
    ok("fifo input is rejected")

proc = subprocess.run(base + ["--input", "/dev/null", "--output", os.path.join(tmp, "out.json")],
                      capture_output=True, timeout=5)
if proc.returncode != mod.EXIT_IO or b"input is not a regular file" not in proc.stderr:
    bad(f"device input: {proc.returncode} {proc.stderr!r}")
else:
    ok("device input is rejected")

existing = os.path.join(tmp, "exists.json")
with open(existing, "w", encoding="utf-8") as fh:
    fh.write("keep\n")
proc = subprocess.run(base + ["--input", report_path, "--output", existing],
                      capture_output=True, timeout=5)
if proc.returncode != mod.EXIT_IO or open(existing, encoding="utf-8").read() != "keep\n":
    bad(f"existing output: {proc.returncode} {proc.stderr!r}")
else:
    ok("an existing handoff is not overwritten")

proc = subprocess.run(base + ["--input", report_path, "--output", report_path],
                      capture_output=True, timeout=5)
if proc.returncode != mod.EXIT_IO or b"alias" not in proc.stderr or open(report_path, encoding="utf-8").read() != "[]\n":
    bad(f"alias: {proc.returncode} {proc.stderr!r}")
else:
    ok("input and output alias is rejected")

missing_parent = os.path.join(tmp, "missing-dir", "handoff.json")
proc = subprocess.run(base + ["--input", report_path, "--output", missing_parent],
                      capture_output=True, timeout=5)
if proc.returncode != mod.EXIT_IO or os.path.exists(missing_parent):
    bad(f"missing parent: {proc.returncode} {proc.stderr!r}")
else:
    ok("a missing output parent fails closed")

if hasattr(os, "geteuid") and os.geteuid() == 0:
    print("SKIP: unreadable report omitted while running as root")
else:
    hidden = os.path.join(tmp, "hidden.json")
    with open(hidden, "w", encoding="utf-8") as fh:
        fh.write("[]\n")
    os.chmod(hidden, 0)
    try:
        proc = subprocess.run(base + ["--input", hidden, "--output", os.path.join(tmp, "hidden-out.json")],
                              capture_output=True, timeout=5)
        if proc.returncode != mod.EXIT_IO or os.path.exists(os.path.join(tmp, "hidden-out.json")):
            bad(f"unreadable input: {proc.returncode} {proc.stderr!r}")
        else:
            ok("unreadable input fails closed")
    finally:
        os.chmod(hidden, 0o644)

proc, src, dst, *_ = run(b"")
if proc.returncode != mod.EXIT_MALFORMED or os.path.exists(dst):
    bad(f"empty file: {proc.returncode} {proc.stderr!r}")
else:
    ok("a zero-byte file is malformed rather than an empty report")

partial = os.path.join(tmp, "partial.json")
info = os.stat(report_path)
original_write = os.write
def fail_write(fd, data):
    raise OSError("write failed")
os.write = fail_write
try:
    try:
        mod._write_output(partial, b"{}\n", info, report_path)
        bad("partial write returned")
    except OSError:
        if os.path.exists(partial):
            bad("partial handoff remained after a failed write")
        else:
            ok("a failed write removes the partial handoff")
finally:
    os.write = original_write

plan = open(os.path.join(root, "modules", "security", "files", "security", "scanner-planning.md"), encoding="utf-8").read()
copy = open(os.path.join(root, "extensions", "hermesVPS", "security-assets", "scanner-planning.md"), encoding="utf-8").read()
flat = " ".join(plan.split())
if plan != copy:
    bad("bundled scanner-planning.md drifted")
elif "Approval of the probe does not approve scanning." not in flat:
    bad("probe approval clarification is missing")
elif "python3 security/gitleaks_handoff.py" not in plan:
    bad("normalizer usage is missing from the contract")
else:
    ok("planning contract documents the probe and the normalizer")

if fail:
    raise SystemExit(1)
print("OK")
PY

cmp -s "${ROOT}/modules/security/files/security/scanner-planning.md" \
  "${ROOT}/extensions/hermesVPS/security-assets/scanner-planning.md"
