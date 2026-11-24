#!/usr/bin/env bash
# Fake-process checks for the directory-scan launcher.
# These checks do not run Gitleaks and do not establish tool compatibility
# or OS sandboxing. The deferred real-tool smoke procedure is not executed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 - "${ROOT}" <<'PY'
import atexit, contextlib, hashlib, importlib.util, io, json, os, signal, stat, subprocess, sys, tempfile, time

root = sys.argv[1]
util = os.path.join(root, "modules", "security", "files", "security", "gitleaks_dir_scan.py")
spec = importlib.util.spec_from_file_location("gitleaks_dir_scan", util)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

MARKER = "SYNTHETIC_SECRET_MARKER_04C"
fail = False
temps = []

def cleanup():
    for holder in temps:
        holder.cleanup()

atexit.register(cleanup)

def ok(name):
    print("PASS:", name)

def bad(name):
    global fail
    fail = True
    print("FAIL:", name)

def capture(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = mod.main(argv)
    return code, out.getvalue(), err.getvalue()

fake_root = tempfile.TemporaryDirectory(prefix="stage04c-fake-")
temps.append(fake_root)
body = r'''
import json, os, sys, time
mode = os.path.basename(sys.argv[0])
here = os.path.dirname(os.path.abspath(sys.argv[0]))
marker = "SYNTHETIC_SECRET_MARKER_04C"
observe = os.path.join(here, mode + ".observe.json")
with open(observe, "w", encoding="utf-8") as fh:
    json.dump({"argv": sys.argv, "env": dict(os.environ)}, fh)
report = None
if "--report-path" in sys.argv:
    report = sys.argv[sys.argv.index("--report-path") + 1]

def write_report(data):
    with open(report, "wb") as handle:
        handle.write(data)

finding = json.dumps([{
    "RuleID": "rule-a",
    "File": "pkg/a.txt",
    "Secret": marker,
    "Match": marker,
    "Fingerprint": "fp-" + marker,
}]).encode() + b"\n"

if mode == "fake-none":
    write_report(b"[]\n")
    raise SystemExit(0)
if mode == "fake-findings":
    write_report(finding)
    raise SystemExit(2)
if mode == "fake-fail":
    write_report(finding)
    raise SystemExit(1)
if mode == "fake-missing":
    raise SystemExit(0)
if mode == "fake-malformed":
    write_report(b"{")
    raise SystemExit(2)
if mode == "fake-oversize":
    write_report(marker.encode() + b"\n" + (b"x" * 180))
    raise SystemExit(0)
if mode == "fake-limit":
    write_report(marker.encode() * 200000)
    raise SystemExit(0)
if mode == "fake-flood":
    write_report(b"[]\n")
    blob = (marker + "\n").encode() * 8000
    sys.stdout.buffer.write(blob)
    sys.stderr.buffer.write(blob)
    sys.stdout.buffer.flush()
    sys.stderr.buffer.flush()
    raise SystemExit(0)
if mode == "fake-empty2":
    write_report(b"[]\n")
    raise SystemExit(2)
if mode == "fake-hit0":
    write_report(finding)
    raise SystemExit(0)
if mode == "fake-timeout":
    pid_path = os.path.join(here, "grandchild.pid")
    alive = os.path.join(here, "grandchild-alive")
    pid = os.fork()
    if pid == 0:
        time.sleep(4)
        with open(alive, "w", encoding="utf-8") as handle:
            handle.write("alive\n")
        os._exit(0)
    with open(pid_path, "w", encoding="utf-8") as handle:
        handle.write(str(pid))
    time.sleep(30)
    raise SystemExit(0)
raise SystemExit(9)
'''
script = "#!" + sys.executable + "\n" + body
digest = hashlib.sha256(script.encode()).hexdigest()
modes = [
    "fake-none", "fake-findings", "fake-fail", "fake-missing", "fake-malformed",
    "fake-oversize", "fake-limit", "fake-flood", "fake-empty2", "fake-hit0",
    "fake-timeout", "fake-digest", "fake-preserve",
]
for mode in modes:
    path = os.path.join(fake_root.name, mode)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(script)
    os.chmod(path, 0o755)

def observe(mode):
    path = os.path.join(fake_root.name, mode + ".observe.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)

def fresh(prefix):
    holder = tempfile.TemporaryDirectory(prefix=prefix)
    temps.append(holder)
    snap = os.path.join(holder.name, "snap")
    out = os.path.join(holder.name, "out")
    os.mkdir(snap)
    os.mkdir(out)
    with open(os.path.join(snap, "note.txt"), "w", encoding="utf-8") as handle:
        handle.write("plain\n")
    return snap, out

def argv_for(mode, snap, out, **over):
    values = {
        "executable": os.path.join(fake_root.name, mode),
        "digest": digest,
        "snapshot": snap,
        "output": out,
        "name": "handoff.json",
        "timeout": 30,
        "files": 100,
        "bytes": 100000,
        "report": 100000,
        "stream": 8192,
        "provenance": "synthetic-report",
    }
    values.update(over)
    return [
        "--executable", values["executable"],
        "--executable-sha256", values["digest"],
        "--snapshot", values["snapshot"],
        "--output-parent", values["output"],
        "--handoff-name", values["name"],
        "--check-id", "P-1",
        "--source-revision", "unknown",
        "--working-tree", "prepared-snapshot",
        "--tool-version", "claim-v8.30.1",
        "--rules-identity", "claim-default",
        "--report-provenance", values["provenance"],
        "--timeout-seconds", str(values["timeout"]),
        "--max-snapshot-files", str(values["files"]),
        "--max-snapshot-bytes", str(values["bytes"]),
        "--max-report-bytes", str(values["report"]),
        "--max-stream-bytes", str(values["stream"]),
    ]

def leaked(text):
    return MARKER in text or "Traceback" in text

source = open(util, encoding="utf-8").read()
if "shell=False" not in source or "shell=True" in source or "os.system" in source:
    bad("launcher constructs a fixed argument vector")
else:
    ok("launcher constructs a fixed argument vector")

snap, out = fresh("stage04c-argv-")
code, stdout, stderr = capture(argv_for("fake-none", snap, out))
seen = observe("fake-none")
handoff = os.path.join(out, "handoff.json")
if code != 0 or seen is None or leaked(stdout + stderr):
    bad(f"fixed argv launch: {code} {stderr!r}")
else:
    report = seen["argv"][seen["argv"].index("--report-path") + 1]
    ignore = seen["argv"][seen["argv"].index("--gitleaks-ignore-path") + 1]
    expected = mod.fixed_argv(os.path.join(fake_root.name, "fake-none"), snap, report, ignore)
    env = seen["env"]
    private = os.path.dirname(report)
    leftovers = [name for name in os.listdir(out) if name.startswith(".gitleaks-dir-scan-")]
    document = json.loads(open(handoff, encoding="utf-8").read())
    status = json.loads(stdout)
    if seen["argv"] != expected or set(env) != {"TMPDIR", "LANG", "LC_ALL"}:
        bad(f"argv or environment mismatch: {seen['argv']} {sorted(env)}")
    elif env["TMPDIR"] != private or "--config" in seen["argv"] or "--follow-symlinks" in seen["argv"]:
        bad("target configuration or symlink following was enabled")
    elif not report.startswith(out + "/") or report.startswith(snap + "/"):
        bad("report path is not outside the snapshot")
    elif leftovers or status["toolDetection"] != "none" or status["toolExit"] != 0:
        bad(f"no-detection status: {status} leftovers={leftovers}")
    elif status["approvalVerified"] or status["callerClaimsVerified"] or status["networkConfined"]:
        bad("status treats claims, approval, or network confinement as verified")
    elif status["observed"]["executableSha256"] != digest or status["profile"] != mod.PROFILE:
        bad("observed digest or profile was replaced by a claim")
    elif document["callerSupplied"]["toolVersion"] != "claim-v8.30.1":
        bad("caller version claim was not kept distinct")
    elif document["callerSupplied"]["verified"] or document["callerSupplied"]["approved"]:
        bad("handoff marked a claim verified")
    elif document["parsingOutcome"] != "empty" or MARKER in open(handoff, encoding="utf-8").read():
        bad("empty report was treated as findings or leaked")
    else:
        ok("fixed argv, allowlisted environment, and no-detection handoff")

snap, out = fresh("stage04c-digest-")
code, stdout, stderr = capture(argv_for("fake-digest", snap, out, digest="0" * 64))
if code != mod.EXIT_IO or "executable digest mismatch" not in stderr or observe("fake-digest") is not None:
    bad(f"digest rejection: {code} {stderr!r}")
elif leaked(stdout + stderr) or os.path.exists(os.path.join(out, "handoff.json")):
    bad("digest rejection leaked or published")
else:
    ok("wrong executable digest is rejected before launch")

snap, out = fresh("stage04c-findings-")
code, stdout, stderr = capture(argv_for("fake-findings", snap, out))
handoff = os.path.join(out, "handoff.json")
if code != 0 or leaked(stdout + stderr) or not os.path.exists(handoff):
    bad(f"detection launch: {code} {stderr!r}")
else:
    text = open(handoff, encoding="utf-8").read()
    status = json.loads(stdout)
    document = json.loads(text)
    if MARKER in text or status["toolDetection"] != "findings" or status["toolExit"] != 2:
        bad("detection handoff leaked or lost the tool exit")
    elif document["counts"]["records"] != 1 or document["leads"][0]["ruleId"] != "rule-a":
        bad("detection handoff did not keep the minimized lead")
    elif "Secret" in text or "Fingerprint" in text:
        bad("raw finding fields were copied")
    else:
        ok("detection publishes a minimized handoff")

def expect_failure(mode, phrase, code_set, label, **over):
    snap, out = fresh("stage04c-" + mode + "-")
    code, stdout, stderr = capture(argv_for(mode, snap, out, **over))
    handoff = os.path.join(out, "handoff.json")
    if code not in code_set or phrase not in stderr or stdout or os.path.exists(handoff) or leaked(stdout + stderr):
        bad(f"{label}: {code} {stderr!r} {stdout[:120]!r}")
    else:
        ok(label)

expect_failure("fake-fail", "tool failure", {mod.EXIT_TOOL}, "tool execution failure does not publish")
expect_failure("fake-missing", "report missing", {mod.EXIT_REPORT}, "missing report does not publish")
expect_failure("fake-malformed", "report malformed", {mod.EXIT_REPORT}, "malformed report does not publish")
expect_failure("fake-oversize", "report oversized", {mod.EXIT_LIMIT}, "oversized report does not publish", report=64)
expect_failure("fake-empty2", "outcome mismatch", {mod.EXIT_TOOL}, "empty array with detection exit does not publish")
expect_failure("fake-hit0", "outcome mismatch", {mod.EXIT_TOOL}, "findings with a zero exit do not publish")

snap, out = fresh("stage04c-limit-")
code, stdout, stderr = capture(argv_for("fake-limit", snap, out, report=1048576))
if code != mod.EXIT_LIMIT or "file size limit" not in stderr or os.path.exists(os.path.join(out, "handoff.json")):
    bad(f"file size limit: {code} {stderr!r}")
elif leaked(stdout + stderr):
    bad("file size limit relayed raw output")
else:
    ok("file size ceiling does not publish")

snap, out = fresh("stage04c-flood-")
code, stdout, stderr = capture(argv_for("fake-flood", snap, out, stream=1024))
if code != mod.EXIT_LIMIT or "stream limit" not in stderr or os.path.exists(os.path.join(out, "handoff.json")):
    bad(f"stream flood: {code} {stderr!r}")
elif leaked(stdout + stderr):
    bad("stream flood relayed raw output")
else:
    ok("flooded stdout and stderr are not relayed")

snap, out = fresh("stage04c-timeout-")
started = time.monotonic()
code, stdout, stderr = capture(argv_for("fake-timeout", snap, out, timeout=2))
elapsed = time.monotonic() - started
time.sleep(3)
pid_path = os.path.join(fake_root.name, "grandchild.pid")
alive = os.path.join(fake_root.name, "grandchild-alive")
pid = int(open(pid_path, encoding="utf-8").read()) if os.path.exists(pid_path) else 0
still = False
if pid:
    try:
        os.kill(pid, 0)
        still = True
    except OSError:
        still = False
if code != mod.EXIT_LIMIT or "timeout" not in stderr or elapsed > 8 or still or os.path.exists(alive):
    bad(f"timeout cleanup: code={code} elapsed={elapsed:.2f} still={still} alive={os.path.exists(alive)} {stderr!r}")
elif leaked(stdout + stderr) or os.path.exists(os.path.join(out, "handoff.json")):
    bad("timeout published or relayed output")
else:
    ok("timeout kills the process group and reaps the child")

saved = os.environ.copy()
try:
    os.environ["GITHUB_TOKEN"] = MARKER
    os.environ["GITLEAKS_CONFIG"] = "/tmp/not-used.toml"
    os.environ["GITLEAKS_CONFIG_TOML"] = MARKER
    os.environ["PATH"] = "/not-a-target-path"
    snap, out = fresh("stage04c-env-")
    # A prior fake-none observation must not be reused.
    prior = os.path.join(fake_root.name, "fake-none.observe.json")
    if os.path.exists(prior):
        os.remove(prior)
    code, stdout, stderr = capture(argv_for("fake-none", snap, out, name="env.json"))
    seen = observe("fake-none")
    if code != 0 or seen is None or leaked(stdout + stderr):
        bad(f"environment override: {code} {stderr!r}")
    elif any(name in seen["env"] for name in ("GITHUB_TOKEN", "GITLEAKS_CONFIG", "GITLEAKS_CONFIG_TOML", "PATH")):
        bad(f"host environment was inherited: {sorted(seen['env'])}")
    elif MARKER in json.dumps(seen["env"]) or "--config" in seen["argv"]:
        bad("target configuration environment was visible to the child")
    else:
        ok("target configuration and host environment are not used")
finally:
    os.environ.clear()
    os.environ.update(saved)

snap, out = fresh("stage04c-link-")
os.symlink("/etc/passwd", os.path.join(snap, "linked"))
code, stdout, stderr = capture(argv_for("fake-preserve", snap, out))
if code != mod.EXIT_IO or "snapshot rejected" not in stderr or observe("fake-preserve") is not None:
    bad(f"symlink rejection: {code} {stderr!r}")
elif leaked(stdout + stderr):
    bad("symlink rejection leaked")
else:
    ok("symlink snapshot is rejected before launch")

snap, out = fresh("stage04c-fifo-")
os.mkfifo(os.path.join(snap, "pipe"))
code, stdout, stderr = capture(argv_for("fake-preserve", snap, out))
if code != mod.EXIT_IO or "snapshot rejected" not in stderr or observe("fake-preserve") is not None:
    bad(f"special file rejection: {code} {stderr!r}")
else:
    ok("special-file snapshot is rejected before launch")

snap, out = fresh("stage04c-config-")
with open(os.path.join(snap, ".gitleaks.toml"), "w", encoding="utf-8") as handle:
    handle.write("title = \"target\"\n")
code, stdout, stderr = capture(argv_for("fake-preserve", snap, out))
if code != mod.EXIT_IO or "snapshot rejected" not in stderr or observe("fake-preserve") is not None:
    bad(f"target config rejection: {code} {stderr!r}")
else:
    ok("target gitleaks config in the snapshot is rejected")

snap, out = fresh("stage04c-ignore-")
with open(os.path.join(snap, ".gitleaksignore"), "w", encoding="utf-8") as handle:
    handle.write("fp\n")
code, stdout, stderr = capture(argv_for("fake-preserve", snap, out))
if code != mod.EXIT_IO or "snapshot rejected" not in stderr or observe("fake-preserve") is not None:
    bad(f"ignore rejection: {code} {stderr!r}")
else:
    ok("target ignore file in the snapshot is rejected")

snap, out = fresh("stage04c-overlap-")
nested = os.path.join(snap, "nested-out")
os.mkdir(nested)
code, stdout, stderr = capture(argv_for("fake-preserve", snap, nested))
if code != mod.EXIT_IO or "output rejected" not in stderr or observe("fake-preserve") is not None:
    bad(f"overlap rejection: {code} {stderr!r}")
else:
    ok("snapshot and output overlap is rejected")

snap, out = fresh("stage04c-keep-")
dest = os.path.join(out, "handoff.json")
with open(dest, "wb") as handle:
    handle.write(b"keep\n")
before = open(dest, "rb").read()
code, stdout, stderr = capture(argv_for("fake-preserve", snap, out))
if code != mod.EXIT_IO or "output rejected" not in stderr or open(dest, "rb").read() != before:
    bad(f"existing output: {code} {stderr!r}")
elif observe("fake-preserve") is not None:
    bad("existing output still launched")
else:
    ok("existing handoff is preserved")

snap, out = fresh("stage04c-cleanfail-")
store = os.path.join(out, "findings-reviewed.json")
with open(store, "wb") as handle:
    handle.write(b'{"findings":[]}\n')
store_bytes = open(store, "rb").read()
real_rmtree = mod.shutil.rmtree
def fail_rmtree(*_args, **_kwargs):
    raise OSError(MARKER)
mod.shutil.rmtree = fail_rmtree
try:
    code, stdout, stderr = capture(argv_for("fake-findings", snap, out, name="clean.json"))
finally:
    mod.shutil.rmtree = real_rmtree
private_left = [name for name in os.listdir(out) if name.startswith(".gitleaks-dir-scan-")]
raw_has_marker = False
if private_left:
    report = os.path.join(out, private_left[0], "report.json")
    if os.path.exists(report):
        raw_has_marker = MARKER.encode() in open(report, "rb").read()
if code == 0 or "cleanup failed" not in stderr or leaked(stdout + stderr):
    bad(f"cleanup failure: {code} {stderr!r}")
elif os.path.exists(os.path.join(out, "clean.json")) or not raw_has_marker:
    bad("cleanup failure published a handoff or dropped the raw failure state")
elif open(store, "rb").read() != store_bytes:
    bad("cleanup failure changed the findings file")
else:
    ok("cleanup failure is not success and leaves raw material")

snap, out = fresh("stage04c-store-")
store = os.path.join(out, "findings-reviewed.json")
with open(store, "wb") as handle:
    handle.write(b'{"findings":[]}\n')
store_bytes = open(store, "rb").read()
code, stdout, stderr = capture(argv_for("fake-findings", snap, out, name="store.json"))
if code != 0 or open(store, "rb").read() != store_bytes or MARKER.encode() in open(os.path.join(out, "store.json"), "rb").read():
    bad("findings file changed or the handoff leaked")
else:
    ok("launcher leaves an adjacent findings file unchanged")

install = tempfile.TemporaryDirectory(prefix="stage04c-install-")
temps.append(install)
home = os.path.join(install.name, "home")
target = os.path.join(install.name, "target")
os.makedirs(home)
env = os.environ.copy()
env["HOME"] = home
installed_run = subprocess.run(
    [os.path.join(root, "scripts", "init.sh"), target, "--security"],
    cwd=root, env=env, capture_output=True, text=True, timeout=60)
installed_util = os.path.join(target, "security", "gitleaks_dir_scan.py")
installed_norm = os.path.join(target, "security", "gitleaks_handoff.py")
findings = os.path.join(target, "security", "findings-reviewed.json")
canonical_norm = os.path.join(root, "modules", "security", "files", "security", "gitleaks_handoff.py")
if installed_run.returncode != 0 or not os.path.isfile(installed_util):
    bad(f"security install failed: {installed_run.stderr[-400:]}")
elif open(installed_util, "rb").read() != open(util, "rb").read():
    bad("installed launcher differs from the canonical source")
elif open(installed_norm, "rb").read() != open(canonical_norm, "rb").read():
    bad("installed normalizer differs from the canonical source")
else:
    before = open(findings, "rb").read()
    snap, out = fresh("stage04c-installed-")
    inst_spec = importlib.util.spec_from_file_location("installed_gitleaks_dir_scan", installed_util)
    inst = importlib.util.module_from_spec(inst_spec)
    inst_spec.loader.exec_module(inst)
    out_buf, err_buf = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
        inst_code = inst.main(argv_for("fake-findings", snap, out, name="installed.json"))
    produced = os.path.join(out, "installed.json")
    if inst_code != 0 or MARKER in out_buf.getvalue() + err_buf.getvalue():
        bad(f"installed launcher failed: {inst_code} {err_buf.getvalue()!r}")
    elif not os.path.exists(produced) or MARKER.encode() in open(produced, "rb").read():
        bad("installed launcher leaked the marker into the handoff")
    elif open(findings, "rb").read() != before:
        bad("installed launcher changed the findings store")
    else:
        ok("security-module install matches the source and leaves findings unchanged")

plan = open(os.path.join(root, "modules", "security", "files", "security", "scanner-planning.md"), encoding="utf-8").read()
copy = open(os.path.join(root, "extensions", "hermesVPS", "security-assets", "scanner-planning.md"), encoding="utf-8").read()
flat = " ".join(plan.split())
local_rule = open(os.path.join(root, "extensions", "hermes", "rules", "rules_030-scan-plan.md"), encoding="utf-8").read()
vps_rule = open(os.path.join(root, "extensions", "hermesVPS", "rules", "rules_030-scan-plan.md"), encoding="utf-8").read()
if plan != copy:
    bad("bundled scanner-planning.md drifted")
elif "security/gitleaks_dir_scan.py" not in local_rule or "security/gitleaks_dir_scan.py" not in vps_rule:
    bad("Rule 030 does not keep the launcher out of the phase")
elif "This procedure was not executed." not in flat or "does not enforce OS network confinement" not in flat:
    bad("deferred smoke procedure is missing")
elif "Preflight is not a sandbox." not in flat or "Cleanup is not secure erasure." not in flat:
    bad("launcher limitations are missing from the contract")
else:
    ok("planning contract documents the launcher and the deferred smoke procedure")
    ok("real-tool smoke procedure was not executed")

if fail:
    raise SystemExit(1)
print("OK")
PY
