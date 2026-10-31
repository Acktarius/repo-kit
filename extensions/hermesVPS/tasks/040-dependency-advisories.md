# Task 040 — Dependency identification and advisory matching

- Phase: 040 — dependency-advisories
- Phase rule: `rules/rules_040-dependency-advisories.md`
- Report: `<run_root>/reports/phase-040-hermes-vN.md`
- Payload: `<run_root>/reports/payload-040-all-vN.json` (vuln-intel-record.json)

## 1. Read first

1. `BOOTSTRAP.md`
2. `rules/rules_000-safety-and-scope.md`
3. `rules/rules_005-report-output.md`
4. `rules/rules_040-dependency-advisories.md`

## 2. Target

Approved source path and commit from `run.json`.

## 3. Prior artifacts

Resolve selected phase-010, phase-020, and phase-030 artifacts.
Verify SHA-256. Missing, stale, or blocked → write report with `blocked`, stop.

## 4. Determine collection mode

Check whether the trigger message explicitly authorizes network access.

If authorized:
```
hermes-vps-collect-intel \
  --run-json <run_json_path> \
  --output <run_root>/reports/vuln-intel.json \
  --mode live \
  --packages-json <path-to-packages.json>
```

If NOT authorized:
```
hermes-vps-collect-intel \
  --run-json <run_json_path> \
  --output <run_root>/reports/vuln-intel.json \
  --mode not-authorized
```

If using prior evidence (offline/air-gapped):
```
hermes-vps-collect-intel \
  --run-json <run_json_path> \
  --output <run_root>/reports/vuln-intel.json \
  --mode imported \
  --import-evidence <path-to-prior-record.json>
```

**Do not silently enable live mode just because evidence is stale.**
The `packages.json` file is created from the phase-010 inventory:
`[{"ecosystem": "PyPI", "name": "requests", "version": "2.28.2"}, ...]`

All endpoint URLs are in `lib/hermes_vps_intel.py INTEL_SOURCES`.
Do not hardcode URLs here.

## 5. Perform

Identify dependencies per Rule 040.
Summarize collection results, freshness, and coverage.
Produce candidate issues from matches (candidates, not findings).

## 6. Write

Write exactly one Markdown report to `<run_root>/reports/`.

## 7. Register

```
hermes-vps-artifacts register \
  --run-json <run_json_path> \
  --phase 040 \
  --source-report <absolute-path-to-report.md> \
  --payload-json <absolute-path-to-vuln-intel.json>
```

`--payload-json` is **required** for phase 040.
The payload is the `vuln-intel-record.json` from step 4.

## 8. Stop

Stop and wait for human approval.
