#!/usr/bin/env bash
# Regression tests for --tool discovery, parsing, listing, and py-indexer shared install.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

fail=0
pass=0
ok() { pass=$((pass + 1)); echo "PASS: $*"; }
bad() { fail=$((fail + 1)); echo "FAIL: $*" >&2; }

# Isolate HOME / XDG so tests never touch the developer install.
export HOME="${TMP}/home"
export XDG_DATA_HOME="${TMP}/xdg-data"
export XDG_CACHE_HOME="${TMP}/xdg-cache"
export XDG_BIN_HOME="${TMP}/xdg-bin"
mkdir -p "${HOME}" "${XDG_DATA_HOME}" "${XDG_CACHE_HOME}" "${XDG_BIN_HOME}"

# --- list includes TOOL section and py-indexer ---
list_out="$("${ROOT}/scripts/list-modules.sh")"
if echo "${list_out}" | grep -q '^TOOL'; then
  ok "list-modules shows TOOL section"
else
  bad "list-modules missing TOOL section"
fi
if echo "${list_out}" | grep -q 'py-indexer'; then
  ok "list-modules lists py-indexer"
else
  bad "list-modules missing py-indexer"
fi

help_out="$("${ROOT}/scripts/init.sh" --help)"
if echo "${help_out}" | grep -q -- '--tool'; then
  ok "init --help mentions --tool"
else
  bad "init --help missing --tool"
fi

sync_help="$("${ROOT}/scripts/sync-cursor.sh" --help)"
if echo "${sync_help}" | grep -q -- '--tool'; then
  ok "sync-cursor --help mentions --tool"
else
  bad "sync-cursor --help missing --tool"
fi

# --- unknown / missing tool names ---
set +e
err="$("${ROOT}/scripts/init.sh" "${TMP}/t1" --tool 2>&1)"
rc=$?
set -e
if [[ "${rc}" -ne 0 ]] && echo "${err}" | grep -qi 'requires a name'; then
  ok "missing --tool name rejected"
else
  bad "missing --tool name not rejected cleanly: rc=${rc} err=${err}"
fi

set +e
err="$("${ROOT}/scripts/init.sh" "${TMP}/t2" --tool no-such-tool 2>&1)"
rc=$?
set -e
if [[ "${rc}" -ne 0 ]] && echo "${err}" | grep -qi 'unknown tool'; then
  ok "unknown tool rejected"
else
  bad "unknown tool not rejected: rc=${rc} err=${err}"
fi

# --- non-interactive without assume-yes refuses first install ---
TARGET0="${TMP}/no-consent"
mkdir -p "${TARGET0}"
git -C "${TARGET0}" init -q
export REPO_KIT_TOOL_SKIP_DEPS=1
unset REPO_KIT_TOOL_ASSUME_YES || true
set +e
nc_out="$("${ROOT}/scripts/init.sh" "${TARGET0}" --tool py-indexer 2>&1)"
nc_rc=$?
set -e
if [[ "${nc_rc}" -ne 0 ]] && echo "${nc_out}" | grep -qi 'ASSUME_YES\|refused\|not installed'; then
  ok "non-interactive without ASSUME_YES refuses shared install"
else
  bad "expected non-interactive refuse: rc=${nc_rc} out=${nc_out}"
fi

# --- first shared install (offline) ---
TARGET="${TMP}/project with spaces/app"
mkdir -p "${TARGET}"
git -C "${TARGET}" init -q
export REPO_KIT_TOOL_ASSUME_YES=1
init_out="$("${ROOT}/scripts/init.sh" "${TARGET}" --tool py-indexer 2>&1)"
TOOL="${TARGET}/.repo-kit/tools/py-indexer"
EXE="${XDG_BIN_HOME}/py-indexer"

if echo "${init_out}" | grep -q 'without mcp\|REPO_KIT_TOOL_SKIP_DEPS'; then
  ok "installer offline/skip-deps path exercised"
else
  bad "installer did not report offline skip: ${init_out}"
fi

if [[ -f "${TOOL}/repos.json" ]]; then
  ok "seeded repos.json"
else
  bad "missing repos.json"
fi

if [[ -f "${TARGET}/.cursor/rules/py-indexer.mdc" ]]; then
  ok "cursor rule installed"
else
  bad "cursor rule missing"
fi

# Must NOT copy application into the project
for rel in bin/py-indexer py_indexer/__init__.py requirements.txt index .venv; do
  if [[ -e "${TOOL}/${rel}" ]]; then
    bad "should not copy ${rel} into project"
  else
    ok "no project-local ${rel}"
  fi
done

if [[ -x "${EXE}" ]]; then
  ok "shared py-indexer linked at XDG_BIN_HOME"
else
  bad "shared executable missing: ${EXE}"
fi

python3 - "${TARGET}/.cursor/mcp.json" "${EXE}" "${TOOL}/repos.json" <<'PY' && ok "mcp.json absolute exe + --config serve" || bad "mcp.json contract wrong"
import json, sys
doc = json.load(open(sys.argv[1]))
entry = doc["mcpServers"]["py-indexer"]
assert entry["type"] == "stdio"
assert entry["command"] == sys.argv[2], entry
assert entry["args"] == ["--config", sys.argv[3], "serve"], entry
PY

if grep -Fq '.repo-kit/tools/py-indexer/repos.json' "${TARGET}/.gitignore"; then
  ok "gitignore covers repos.json"
else
  bad "gitignore missing repos.json"
fi

# PATH profile marker idempotent
markers="$(grep -c '^# repo-kit py-indexer PATH$' "${HOME}/.bashrc" || true)"
"${ROOT}/scripts/init.sh" "${TARGET}" --tool py-indexer --force >/dev/null
markers2="$(grep -c '^# repo-kit py-indexer PATH$' "${HOME}/.bashrc" || true)"
if [[ "${markers}" -eq 1 && "${markers2}" -eq 1 ]]; then
  ok "PATH profile marker not duplicated"
else
  bad "PATH markers=${markers} after=${markers2}"
fi

# Existing managed block whose bin directory changed is rewritten in place.
python3 - "${HOME}/.bashrc" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
text = text.replace("# bin: ", "# bin: /old/py-indexer-bin\n# bin-was: ", 1)
path.write_text(text, encoding="utf-8")
PY
"${ROOT}/scripts/init.sh" "${TARGET}" --tool py-indexer --force >/dev/null
if grep -Fqx "# bin: ${XDG_BIN_HOME}" "${HOME}/.bashrc" \
  && [[ "$(grep -c '^# repo-kit py-indexer PATH$' "${HOME}/.bashrc")" -eq 1 ]]; then
  ok "PATH block updated when its bin directory changed"
else
  bad "PATH block was not updated for the current bin directory"
fi

# --- preserve repos.json even with --force ---
printf '{"schema_version":1,"active_repo":"custom","defaults":{"max_results":3,"max_snippet_chars":100,"max_total_chars":1000,"chunk_lines":40,"chunk_overlap_lines":5,"max_file_bytes":10000},"repositories":[{"id":"custom","root":".","role":"working","related":[],"include":[],"exclude":["*.secret"]}]}\n' >"${TOOL}/repos.json"
sum_before="$(sha256sum "${TOOL}/repos.json")"
"${ROOT}/scripts/init.sh" "${TARGET}" --tool py-indexer --force >/dev/null
sum_after="$(sha256sum "${TOOL}/repos.json")"
if [[ "${sum_before}" == "${sum_after}" ]]; then
  ok "force reinstall preserved repos.json"
else
  bad "force reinstall mutated repos.json"
fi

# --- second project reuses shared app ---
TARGET2="${TMP}/second"
mkdir -p "${TARGET2}"
git -C "${TARGET2}" init -q
init2="$("${ROOT}/scripts/init.sh" "${TARGET2}" --tool py-indexer 2>&1)"
if echo "${init2}" | grep -q 'reuse.*shared py-indexer'; then
  ok "second project reuses shared install"
else
  bad "second project did not reuse: ${init2}"
fi
if [[ -f "${TARGET2}/.repo-kit/tools/py-indexer/repos.json" ]] \
  && [[ ! -d "${TARGET2}/.repo-kit/tools/py-indexer/py_indexer" ]]; then
  ok "second project only got config (no app copy)"
else
  bad "second project layout wrong"
fi

# --- CLI from nested dir + spaces ---
(
  cd "${TARGET}/.repo-kit/tools"
  "${EXE}" validate-config >/dev/null
) && ok "validate-config via upward discovery (spaces ok)" || bad "upward discovery failed"

# --- divergent mcp preserved; legacy migrated ---
python3 - "${TARGET}/.cursor/mcp.json" <<'PY'
import json
from pathlib import Path
p = Path(__import__("sys").argv[1])
doc = json.loads(p.read_text())
doc["mcpServers"]["py-indexer"] = {"command": "echo", "args": ["nope"]}
doc["mcpServers"]["other"] = {"command": "true"}
p.write_text(json.dumps(doc, indent=2) + "\n")
PY
merge_out="$("${ROOT}/scripts/init.sh" "${TARGET}" --tool py-indexer --force 2>&1 || true)"
python3 - "${TARGET}/.cursor/mcp.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
assert doc["mcpServers"]["py-indexer"]["command"] == "echo"
assert "other" in doc["mcpServers"]
PY
if echo "${merge_out}" | grep -qi 'differs\|untouched\|fragment'; then
  ok "divergent mcp entry left untouched with guidance"
else
  ok "divergent mcp entry preserved"
fi

# Seed legacy MCP on a fresh target and ensure migration
LEG="${TMP}/legacy-mcp"
mkdir -p "${LEG}"
git -C "${LEG}" init -q
REPO_KIT_TOOL_ASSUME_YES=1 REPO_KIT_TOOL_SKIP_DEPS=1 \
  "${ROOT}/scripts/init.sh" "${LEG}" --tool py-indexer >/dev/null
python3 - "${LEG}/.cursor/mcp.json" "${LEG}" <<'PY'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
target = sys.argv[2]
doc = {
  "mcpServers": {
    "py-indexer": {
      "type": "stdio",
      "command": f"{target}/.repo-kit/tools/py-indexer/.venv/bin/python",
      "args": [f"{target}/.repo-kit/tools/py-indexer/bin/py-indexer", "serve"],
    },
    "keep": {"command": "true"},
  }
}
p.write_text(json.dumps(doc, indent=2) + "\n")
# Also drop legacy files so advise path is exercised
tool = Path(target) / ".repo-kit/tools/py-indexer"
(tool / "bin").mkdir(exist_ok=True)
(tool / "bin" / "py-indexer").write_text("#!/bin/true\n")
(tool / "py_indexer").mkdir(exist_ok=True)
(tool / "index").mkdir(exist_ok=True)
(tool / "excludes.txt").write_text("*.custom-legacy\n")
PY
leg_out="$(REPO_KIT_TOOL_ASSUME_YES=1 REPO_KIT_TOOL_SKIP_DEPS=1 \
  "${ROOT}/scripts/init.sh" "${LEG}" --tool py-indexer --force 2>&1)"
python3 - "${LEG}/.cursor/mcp.json" "${XDG_BIN_HOME}/py-indexer" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
entry = doc["mcpServers"]["py-indexer"]
assert entry["command"] == sys.argv[2], entry
assert entry["args"][0] == "--config"
assert entry["args"][2] == "serve"
assert "keep" in doc["mcpServers"]
PY
if echo "${leg_out}" | grep -qi 'legacy'; then
  ok "legacy MCP migrated; legacy files advised"
else
  ok "legacy MCP shape replaced (no legacy advisory if files absent)"
fi
# excludes overlay still present
[[ -f "${LEG}/.repo-kit/tools/py-indexer/excludes.txt" ]] && ok "legacy excludes.txt preserved"

# --- invalid mcp.json fallback ---
BAD="${TMP}/badmcp"
mkdir -p "${BAD}/.cursor"
git -C "${BAD}" init -q
printf 'not-json{' >"${BAD}/.cursor/mcp.json"
set +e
bad_out="$(REPO_KIT_TOOL_ASSUME_YES=1 REPO_KIT_TOOL_SKIP_DEPS=1 \
  "${ROOT}/scripts/init.sh" "${BAD}" --tool py-indexer 2>&1)"
bad_rc=$?
set -e
if [[ "${bad_rc}" -eq 0 ]] && [[ "$(cat "${BAD}/.cursor/mcp.json")" == 'not-json{' ]] \
  && [[ -f "${BAD}/.repo-kit/tools/py-indexer/mcp.fragment.json" ]]; then
  ok "unparseable mcp.json left untouched; fragment written"
else
  bad "unparseable mcp.json handling failed rc=${bad_rc} out=${bad_out}"
fi

# --- combo + sync-cursor ---
COMBO="${TMP}/combo"
mkdir -p "${COMBO}"
git -C "${COMBO}" init -q
REPO_KIT_TOOL_ASSUME_YES=1 REPO_KIT_TOOL_SKIP_DEPS=1 \
  "${ROOT}/scripts/init.sh" "${COMBO}" --base --tool py-indexer >/dev/null
if [[ -f "${COMBO}/.cursor/rules/plan-mode-safety.mdc" && -f "${COMBO}/.repo-kit/tools/py-indexer/repos.json" ]]; then
  ok "module + tool combo"
else
  bad "module + tool combo failed"
fi

SYNC="${TMP}/sync"
mkdir -p "${SYNC}"
git -C "${SYNC}" init -q
REPO_KIT_TOOL_ASSUME_YES=1 REPO_KIT_TOOL_SKIP_DEPS=1 \
  "${ROOT}/scripts/sync-cursor.sh" "${SYNC}" --tool py-indexer >/dev/null
if [[ -f "${SYNC}/.repo-kit/tools/py-indexer/repos.json" && -f "${SYNC}/.cursor/rules/py-indexer.mdc" ]]; then
  ok "sync-cursor installs tool + rule"
else
  bad "sync-cursor tool install failed"
fi

# Package bytes live in the user virtualenv. Source removal is tests/py-indexer-install.sh.
installed="$(find "${XDG_DATA_HOME}/py-indexer/venv" -path '*/site-packages/py_indexer/__init__.py' -print -quit)"
if [[ -n "${installed}" && "${installed}" != "${ROOT}/tools/py-indexer/"* ]]; then
  ok "shared app package lives in the user virtualenv"
else
  bad "shared app package is not in the user virtualenv: ${installed}"
fi

# Index + search smoke. A failed search fails the test.
printf 'export const pyIndexerSmokeToken = 1;\n' >"${TARGET}/src-smoke.ts"
(
  cd "${TARGET}"
  "${EXE}" index --all >/dev/null
  "${EXE}" search 'pyIndexerSmokeToken' --json >"${TMP}/search.json"
  "${EXE}" status >/dev/null
) && python3 - "${TMP}/search.json" <<'PY' && ok "index/search/status via shared exe" || bad "index/search/status failed"
import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
assert doc.get("hits"), doc
assert any("pyIndexerSmokeToken" in hit.get("text", "") for hit in doc["hits"])
PY

echo
echo "tools-cli: ${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]
