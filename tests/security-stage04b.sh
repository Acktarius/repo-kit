#!/usr/bin/env bash
# CLI checks for the offline Gitleaks JSON normalizer. Synthetic reports only.
# No scanner invocation, network, or target checkout writes.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 - "${ROOT}" <<'PY'
import atexit, contextlib, importlib.util, io, json, os, stat, subprocess, sys, tempfile

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

temps = []
atexit.register(lambda: [holder.cleanup() for holder in temps])

def run(report, outcome="unknown", check="P-1", out_name="handoff.json",
        input_path=None, output_path=None, extra=None, prewrite=None):
    holder = tempfile.TemporaryDirectory(prefix="stage04b-")
    temps.append(holder)
    tmp = holder.name
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
fs_holder = tempfile.TemporaryDirectory(prefix="stage04b-fs-")
temps.append(fs_holder)
tmp = fs_holder.name
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

def expect_malformed(doc, label):
    proc, _src, dst, *_ = run(doc)
    err = proc.stderr.decode("utf-8", "replace")
    if (proc.returncode != mod.EXIT_MALFORMED or "malformed JSON" not in err
            or "Traceback" in err or os.path.exists(dst) or MARKER.encode() in proc.stdout + proc.stderr):
        bad(f"{label}: {proc.returncode} {proc.stderr!r}")
    else:
        ok(label)

indic = "\u0661"
super_two = "\u00b2"
expect_malformed('[{"RuleID":"rule-a","File":"a.py","StartLine":%s,"Secret":"%s"}]' % (indic, MARKER),
                  "Arabic-Indic digit in a retained number is malformed")
expect_malformed('[{"RuleID":"rule-a","File":"a.py","StartLine":%s,"Secret":"%s"}]' % (super_two, MARKER),
                  "superscript digit in a retained number is malformed")
expect_malformed('[{"RuleID":"rule-a","File":"a.py","Entropy":%s,"Secret":"%s"}]' % (indic, MARKER),
                  "Arabic-Indic digit in a discarded number is malformed")
expect_malformed('[{"RuleID":"rule-a","File":"a.py","Entropy":%s,"Secret":"%s"}]' % (super_two, MARKER),
                  "superscript digit in a discarded number is malformed")
expect_malformed('[{"RuleID":"rule-a","File":"a.py","Entropy":1.%s,"Secret":"%s"}]' % (indic, MARKER),
                  "non-ASCII fraction digit is malformed")
expect_malformed('[{"RuleID":"rule-a","File":"a.py","Entropy":1e%s,"Secret":"%s"}]' % (super_two, MARKER),
                  "non-ASCII exponent digit is malformed")
for doc, label in (
    ('[{"RuleID":"rule-a","File":"a.py","Entropy":01,"Secret":"%s"}]' % MARKER, "leading zero is malformed"),
    ('[{"RuleID":"rule-a","File":"a.py","Entropy":1.,"Secret":"%s"}]' % MARKER, "missing fraction digit is malformed"),
    ('[{"RuleID":"rule-a","File":"a.py","Entropy":1e,"Secret":"%s"}]' % MARKER, "missing exponent digit is malformed"),
    ('[{"RuleID":"rule-a","File":"a.py","Entropy":1e+,"Secret":"%s"}]' % MARKER, "missing signed exponent digit is malformed"),
):
    expect_malformed(doc, label)

proc, _src, dst, *_ = run(
    '[{"RuleID":"rule-a","File":"pkg/a.py","StartLine":12,"EndLine":12,"Entropy":1.5,"Scale":1e2,"Neg":-3}]')
if proc.returncode != 0 or "Traceback" in proc.stderr.decode():
    bad(f"ASCII numbers: {proc.returncode} {proc.stderr!r}")
else:
    data = json.loads(open(dst, encoding="utf-8").read())
    if data["leads"][0].get("lineRange") != {"startLine": 12, "endLine": 12}:
        bad("ASCII integer line range was not kept")
    else:
        ok("ASCII integer, fraction, and exponent syntax is accepted")

proc, _src, dst, *_ = run('[{"RuleID":"rule-a","File":"pkg/a.py","StartLine":-1,"EndLine":2}]')
if proc.returncode != 0 or "lineRange" in json.loads(open(dst, encoding="utf-8").read())["leads"][0]:
    bad("negative line was not omitted")
else:
    ok("a negative line number is omitted")

proc, _src, dst, *_ = run('[{"RuleID":"rule-a","File":"pkg/a.py","StartLine":1000001,"EndLine":1000001}]')
if proc.returncode != 0 or "lineRange" in json.loads(open(dst, encoding="utf-8").read())["leads"][0]:
    bad("out-of-range line was not omitted")
else:
    ok("an out-of-range line number is omitted")

proc, _src, dst, *_ = run('[{"RuleID":"rule%s%s","File":"pkg/a.py"}]' % (super_two, indic))
if proc.returncode != 0:
    bad(f"digits in a string: {proc.returncode} {proc.stderr!r}")
else:
    rule = json.loads(open(dst, encoding="utf-8").read())["leads"][0]["ruleId"]
    if rule != "rule" + super_two + indic:
        bad(f"string digits were not kept: {rule!r}")
    else:
        ok("digit characters inside a string stay string content")

def reject_const(_name):
    raise ValueError("nonstandard number")

accepted_docs = [
    "[]",
    '[{"RuleID":"a","File":"a.py"}]',
    '[{"RuleID":"say \\"hi\\"","File":"a.py","Note":"back\\\\slash"}]',
    '[{"RuleID":"caf\\u00e9","File":"a.py"}]',
    '[{"RuleID":"\\uD83D\\uDE00","File":"a.py"}]',
    '[{"RuleID":"a","File":"a.py","Entropy":1.5e+2,"Flag":true,"Empty":null,"No":false}]',
    '[{"RuleID":"a","File":"a.py","StartLine":10,"EndLine":12,"Entropy":0}]',
    " [ ] ",
]
oracle_ok = True
for doc in accepted_docs:
    try:
        json.loads(doc, parse_constant=reject_const)
    except (json.JSONDecodeError, ValueError) as exc:
        bad(f"strict JSON oracle rejected a fixture: {exc}")
        oracle_ok = False
        break
    try:
        mod._Parser(doc).report()
    except mod.HandoffError as exc:
        bad(f"normalizer rejected strict JSON: {exc.message}")
        oracle_ok = False
        break
if oracle_ok:
    ok("documents the normalizer accepts are strict JSON")

for doc in (
    "[]x",
    '[{"Entropy":01}]',
    '[{"Entropy":1.}]',
    '[{"Entropy":1e}]',
    '[{"Entropy":1e+}]',
    '[{"Entropy":NaN}]',
    '[{"Entropy":Infinity}]',
    '[{"Entropy":-}]',
    '[{"A":١}]',
):
    try:
        mod._Parser(doc).report()
        bad(f"parser accepted {doc!r}")
        break
    except mod.HandoffError as exc:
        if exc.code != mod.EXIT_MALFORMED or exc.message != "malformed JSON":
            bad(f"parser diagnostic for {doc!r}: {exc.code} {exc.message}")
            break
else:
    ok("syntax corpus rejects malformed and nonstandard numbers")

def capture_main(argv):
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = mod.main(argv)
    return code, stdout.getvalue(), stderr.getvalue()

def fault_case(name, patches, message, output_remains=False, dest_bytes=None):
    holder = tempfile.TemporaryDirectory(prefix="stage04b-fault-")
    temps.append(holder)
    src = os.path.join(holder.name, "report.json")
    dst = os.path.join(holder.name, "handoff.json")
    report = ('[{"RuleID":"rule-a","File":"pkg/a.py","Secret":"%s"}]\n' % MARKER).encode()
    with open(src, "wb") as fh:
        fh.write(report)
    if dest_bytes is not None:
        with open(dst, "wb") as fh:
            fh.write(dest_bytes)
    argv = [
        "--input", src, "--output", dst, "--check-id", "P-1",
        "--source-revision", "unknown", "--working-tree", "clean",
        "--tool-version", "unknown", "--rules-identity", "unknown",
        "--report-provenance", MARKER, "--scanner-outcome", "unknown",
    ]
    saved = {key: getattr(os, key) for key in patches}
    try:
        for key, fn in patches.items():
            setattr(os, key, fn)
        code, out, err = capture_main(argv)
    finally:
        for key, fn in saved.items():
            setattr(os, key, fn)
    noisy = MARKER in out or MARKER in err or "Traceback" in err
    existed = dest_bytes is not None
    if code != mod.EXIT_IO or message not in err or noisy:
        bad(f"{name}: {code} {err!r}")
    elif open(src, "rb").read() != report:
        bad(f"{name}: report bytes changed")
    elif existed and open(dst, "rb").read() != dest_bytes:
        bad(f"{name}: existing destination changed")
    elif (not existed) and output_remains != os.path.exists(dst):
        bad(f"{name}: partial file state is {os.path.exists(dst)}")
    else:
        ok(name)

real_write = os.write
real_close = os.close
def fail_read(_fd, _n):
    raise OSError(MARKER)
def fail_lstat(_path):
    raise OSError(MARKER)
def fail_fchmod(_fd, _mode):
    raise OSError(MARKER)
def fail_write(fd, data):
    if data:
        real_write(fd, bytes(data[:1]))
    raise OSError(MARKER)
def fail_fsync(_fd):
    raise OSError(MARKER)
closes = {"n": 0}
def fail_output_close(fd):
    closes["n"] += 1
    if closes["n"] >= 2:
        raise OSError(MARKER)
    return real_close(fd)
def fail_unlink(_path):
    raise OSError(MARKER)

fault_case("input read failure stays on the CLI boundary", {"read": fail_read},
           "input could not be read")
fault_case("destination inspection failure stays on the CLI boundary", {"lstat": fail_lstat},
           "output could not be created", dest_bytes=b"keep\n")
fault_case("permission failure stays on the CLI boundary", {"fchmod": fail_fchmod},
           "output could not be finalized")
fault_case("partial write is removed", {"write": fail_write},
           "output could not be finalized")
fault_case("fsync failure stays on the CLI boundary", {"fsync": fail_fsync},
           "output could not be finalized")
fault_case("output close failure stays on the CLI boundary", {"close": fail_output_close},
           "output could not be finalized")
fault_case("cleanup failure is not success", {"write": fail_write, "unlink": fail_unlink},
           "output cleanup failed", output_remains=True)

saved_flag = os.O_NOFOLLOW
try:
    del os.O_NOFOLLOW
    holder = tempfile.TemporaryDirectory(prefix="stage04b-prim-")
    temps.append(holder)
    src = os.path.join(holder.name, "report.json")
    dst = os.path.join(holder.name, "handoff.json")
    report = b"[]\n"
    with open(src, "wb") as fh:
        fh.write(report)
    code, out, err = capture_main([
        "--input", src, "--output", dst, "--check-id", "P-1",
        "--source-revision", "unknown", "--working-tree", "clean",
        "--tool-version", "unknown", "--rules-identity", "unknown",
        "--report-provenance", "synthetic-report", "--scanner-outcome", "unknown",
    ])
    if (code != mod.EXIT_IO or "required file primitives are unavailable" not in err
            or os.path.exists(dst) or open(src, "rb").read() != report or "Traceback" in err):
        bad(f"missing primitive: {code} {err!r}")
    else:
        ok("missing file primitives fail before opening input")
finally:
    os.O_NOFOLLOW = saved_flag

install = tempfile.TemporaryDirectory(prefix="stage04b-install-")
temps.append(install)
home = os.path.join(install.name, "home")
target = os.path.join(install.name, "target")
os.makedirs(home)
env = os.environ.copy()
env["HOME"] = home
installed = subprocess.run(
    [os.path.join(root, "scripts", "init.sh"), target, "--security"],
    cwd=root, env=env, capture_output=True, text=True, timeout=60)
installed_util = os.path.join(target, "security", "gitleaks_handoff.py")
findings = os.path.join(target, "security", "findings-reviewed.json")
if installed.returncode != 0 or not os.path.isfile(installed_util):
    bad(f"security install failed: {installed.stderr[-400:]}")
elif open(installed_util, "rb").read() != open(util, "rb").read():
    bad("installed normalizer differs from the canonical source")
else:
    before = open(findings, "rb").read()
    src = os.path.join(install.name, "report.json")
    dst = os.path.join(install.name, "handoff.json")
    with open(src, "w", encoding="utf-8") as fh:
        fh.write('[{"RuleID":"rule-a","File":"pkg/a.py","Secret":"%s"}]\n' % MARKER)
    ran = subprocess.run(
        [sys.executable, installed_util, "--input", src, "--output", dst,
         "--check-id", "P-1", "--source-revision", "unknown", "--working-tree", "clean",
         "--tool-version", "unknown", "--rules-identity", "unknown",
         "--report-provenance", "synthetic-report", "--scanner-outcome", "unknown"],
        capture_output=True, timeout=10)
    if ran.returncode != 0 or MARKER.encode() in ran.stdout + ran.stderr:
        bad(f"installed utility failed: {ran.returncode} {ran.stderr!r}")
    elif open(findings, "rb").read() != before:
        bad("installed run changed the findings store")
    else:
        ok("installed utility matches the source and leaves findings unchanged")

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
