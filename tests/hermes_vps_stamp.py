#!/usr/bin/env python3
"""Test helper: give a fixture report the identity header an agent would use.

Usage: hermes_vps_stamp.py RUNNER (register|revise) [hermes-vps-artifacts args...]

Runs the real hermes-vps-review for the report's phase/subject and prepends the
header it prints (the execution-input snapshot of the current selection), with
completion_state taken from the report body ('State: ...', default complete).
When the runner refuses (negative tests with missing prerequisites), an
identity-only header with no inputs is used so the intended error still fires.
Reports that already start with a header are left untouched.  Never fails.
"""
import json
import os
import re
import subprocess
import sys

PREFIX, SUFFIX = "<!-- hermes-vps-report: ", " -->"
STATE_RE = re.compile(r"^\s*-?\s*(?:completion\s+state|state)\s*:\s*(complete|incomplete|blocked)\s*$", re.I)


def main() -> int:
    runner, args = sys.argv[1], sys.argv[2:]
    if not args or args[0] not in ("register", "revise"):
        return 0

    def opt(name):
        return args[args.index(name) + 1] if name in args[:-1] else None

    run_json, report = opt("--run-json"), opt("--source-report")
    if not (run_json and report and os.path.isfile(report) and os.path.isfile(run_json)):
        return 0
    text = open(report, encoding="utf-8").read()
    if text.startswith(PREFIX):
        return 0
    run = json.load(open(run_json, encoding="utf-8"))
    phase, subject = opt("--phase"), opt("--subject-id")
    if args[0] == "revise":
        try:
            manifest = json.load(open(os.path.join(run["output"]["run_root"], "manifest.json")))
            prior = next(a for a in manifest["artifacts"] if a.get("id") == opt("--supersedes"))
            phase, subject = prior["phase"], subject or prior.get("subject_id")
        except (OSError, ValueError, KeyError, StopIteration):
            return 0
    if not phase:
        return 0

    cmd = [runner, "--phase", phase, "--run-json", run_json] + (["--trigger-input", subject] if subject else [])
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    line = next((ln for ln in out.splitlines() if ln.startswith(PREFIX)), None)
    if line is None:
        line = PREFIX + json.dumps({
            "schema_version": 1, "run_id": run.get("run_id"), "phase": phase, "subject_id": subject,
            "source_identity": run.get("source", {}).get("identity"),
            "source_commit": run.get("source", {}).get("commit"),
            "completion_state": "<complete|incomplete|blocked>", "execution_inputs": [],
        }, separators=(",", ":")) + SUFFIX
    states = {m.group(1).lower() for ln in text.splitlines()
              if (m := STATE_RE.match(ln.replace("*", "").replace("`", "")))}
    state = states.pop() if len(states) == 1 else "complete"
    with open(report, "w", encoding="utf-8") as fh:
        fh.write(line.replace("<complete|incomplete|blocked>", state) + "\n" + text)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - a helper must never mask the command under test
        sys.exit(0)
