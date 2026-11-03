#!/usr/bin/env bash
# Regression tests for --tool discovery, parsing, listing, and install entry points.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

fail=0
pass=0
ok() { pass=$((pass + 1)); echo "PASS: $*"; }
bad() { fail=$((fail + 1)); echo "FAIL: $*" >&2; }

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

# --- tool-only install (with assume-yes for deps) ---
TARGET="${TMP}/project with spaces/app"
mkdir -p "${TARGET}"
git -C "${TARGET}" init -q
export REPO_KIT_TOOL_ASSUME_YES=1
init_out="$("${ROOT}/scripts/init.sh" "${TARGET}" --tool py-indexer)"
TOOL="${TARGET}/.repo-kit/tools/py-indexer"

for rel in \
  bin/py-indexer \
  py_indexer/__init__.py \
  excludes.txt \
  repos.example.json \
  repos.json \
  mcp.example.json \
  requirements.txt \
  README.md; do
  if [[ -f "${TOOL}/${rel}" ]]; then
    ok "installed ${rel}"
  else
    bad "missing ${rel}"
  fi
done

if [[ -x "${TOOL}/bin/py-indexer" ]]; then
  ok "bin/py-indexer executable"
else
  bad "bin/py-indexer not executable"
fi

if [[ -d "${TOOL}/index" ]]; then
  ok "index/ directory present"
else
  bad "index/ missing"
fi

if [[ -f "${TARGET}/.cursor/rules/py-indexer.mdc" ]]; then
  ok "cursor rule installed"
else
  bad "cursor rule missing"
fi

if [[ -f "${TARGET}/.cursor/mcp.json" ]] && grep -q 'py-indexer' "${TARGET}/.cursor/mcp.json"; then
  ok "mcp.json contains py-indexer"
else
  bad "mcp.json missing py-indexer"
fi

# Contract: Cursor runs .venv/bin/python with bin/py-indexer as a *Python* script + serve.
python3 - "${TARGET}/.cursor/mcp.json" <<'PY' && ok "mcp.json uses venv python + bin/py-indexer serve" || bad "mcp.json launch contract wrong"
import json, pathlib, sys
doc = json.loads(pathlib.Path(sys.argv[1]).read_text())
entry = doc["mcpServers"]["py-indexer"]
cmd = entry.get("command", "")
args = entry.get("args") or []
assert cmd.endswith("/.repo-kit/tools/py-indexer/.venv/bin/python"), cmd
assert len(args) == 2 and args[1] == "serve", args
assert args[0].endswith("/.repo-kit/tools/py-indexer/bin/py-indexer"), args
print("ok")
PY

if head -n 1 "${TOOL}/bin/py-indexer" | grep -Eq 'python(3)?[[:space:]]*$'; then
  ok "bin/py-indexer shebang is Python"
else
  bad "bin/py-indexer shebang is not Python"
fi

python3 -m py_compile "${TOOL}/bin/py-indexer" \
  && ok "bin/py-indexer compiles as Python" \
  || bad "bin/py-indexer is not valid Python"

if grep -Fq '.repo-kit/tools/py-indexer/index/' "${TARGET}/.gitignore" \
  && grep -Fq '.repo-kit/tools/py-indexer/repos.json' "${TARGET}/.gitignore"; then
  ok "gitignore entries present"
else
  bad "gitignore entries missing"
fi

# --- preserve repos.json + excludes.txt + index on --force reinstall ---
printf '{"schema_version":1,"active_repo":"custom","defaults":{"max_results":3,"max_snippet_chars":100,"max_total_chars":1000,"chunk_lines":40,"chunk_overlap_lines":5,"max_file_bytes":10000},"repositories":[{"id":"custom","root":".","role":"working","related":[],"include":[],"exclude":[]}]}\n' >"${TOOL}/repos.json"
printf '# local exclude edit\n*.secret\n' >"${TOOL}/excludes.txt"
mkdir -p "${TOOL}/index"
echo 'keep-me' >"${TOOL}/index/marker.txt"
sum_before="$(sha256sum "${TOOL}/repos.json" "${TOOL}/excludes.txt" "${TOOL}/index/marker.txt")"

"${ROOT}/scripts/init.sh" "${TARGET}" --tool py-indexer --force >/dev/null
sum_after="$(sha256sum "${TOOL}/repos.json" "${TOOL}/excludes.txt" "${TOOL}/index/marker.txt")"
if [[ "${sum_before}" == "${sum_after}" ]]; then
  ok "force reinstall preserved repos.json, excludes.txt, and index marker"
else
  bad "force reinstall mutated user config/excludes/index"
fi

# --- ignore idempotency ---
gi_before="$(sha256sum "${TARGET}/.gitignore")"
"${ROOT}/scripts/init.sh" "${TARGET}" --tool py-indexer >/dev/null
gi_after="$(sha256sum "${TARGET}/.gitignore")"
# May append nothing; marker block already present — file should be unchanged or only additive without duplicate marker
markers="$(grep -c '^# repo-kit py-indexer$' "${TARGET}/.gitignore" || true)"
if [[ "${markers}" -eq 1 ]]; then
  ok "gitignore marker idempotent (${markers})"
else
  bad "gitignore marker duplicated (${markers})"
fi

# --- divergent mcp entry preserved ---
python3 - "${TARGET}/.cursor/mcp.json" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
doc = json.loads(p.read_text())
doc["mcpServers"]["py-indexer"] = {"command": "echo", "args": ["nope"]}
doc["mcpServers"]["other"] = {"command": "true"}
doc["extraTop"] = True
p.write_text(json.dumps(doc, indent=2) + "\n")
PY
merge_out="$("${ROOT}/scripts/init.sh" "${TARGET}" --tool py-indexer --force 2>&1 || true)"
python3 - "${TARGET}/.cursor/mcp.json" <<'PY'
import json, pathlib, sys
doc = json.loads(pathlib.Path(sys.argv[1]).read_text())
assert doc["mcpServers"]["py-indexer"]["command"] == "echo", doc
assert "other" in doc["mcpServers"]
assert doc.get("extraTop") is True
print("ok")
PY
if echo "${merge_out}" | grep -qi 'differs\|untouched\|reconcile'; then
  ok "divergent mcp entry left untouched with guidance"
else
  # still ok if entry preserved even without warning text
  if python3 -c "import json; d=json.load(open('${TARGET}/.cursor/mcp.json')); assert d['mcpServers']['py-indexer']['command']=='echo'"; then
    ok "divergent mcp entry preserved"
  else
    bad "divergent mcp entry not preserved"
  fi
fi

# --- invalid mcp.json fallback ---
BAD="${TMP}/badmcp"
mkdir -p "${BAD}/.cursor"
printf 'not-json{' >"${BAD}/.cursor/mcp.json"
set +e
bad_out="$(REPO_KIT_TOOL_ASSUME_YES=1 "${ROOT}/scripts/init.sh" "${BAD}" --tool py-indexer 2>&1)"
bad_rc=$?
set -e
if [[ "${bad_rc}" -eq 0 ]] && [[ "$(cat "${BAD}/.cursor/mcp.json")" == 'not-json{' ]] \
  && [[ -f "${BAD}/.repo-kit/tools/py-indexer/mcp.fragment.json" ]]; then
  ok "unparseable mcp.json left untouched; fragment written"
else
  bad "unparseable mcp.json handling failed rc=${bad_rc}"
fi

# --- combine with module ---
COMBO="${TMP}/combo"
mkdir -p "${COMBO}"
REPO_KIT_TOOL_ASSUME_YES=1 "${ROOT}/scripts/init.sh" "${COMBO}" --base --tool py-indexer >/dev/null
if [[ -f "${COMBO}/.cursor/rules/plan-mode-safety.mdc" && -f "${COMBO}/.repo-kit/tools/py-indexer/bin/py-indexer" ]]; then
  ok "module + tool combination works"
else
  bad "module + tool combination failed"
fi

# --- sync-cursor installs tool fully ---
SYNC="${TMP}/sync only"
mkdir -p "${SYNC}"
REPO_KIT_TOOL_ASSUME_YES=1 "${ROOT}/scripts/sync-cursor.sh" "${SYNC}" --tool py-indexer >/dev/null
if [[ -f "${SYNC}/.repo-kit/tools/py-indexer/bin/py-indexer" && -f "${SYNC}/.cursor/rules/py-indexer.mdc" ]]; then
  ok "sync-cursor --tool installs fully"
else
  bad "sync-cursor --tool did not install fully"
fi

# --- cwd independence / spaces: run CLI from another directory ---
(
  cd "${TMP}"
  "${TOOL}/bin/py-indexer" validate-config >/dev/null
) && ok "validate-config works from other cwd with spaces in path" || bad "validate-config cwd/spaces failed"

# --- MCP startup contract: venv python must execute bin/py-indexer (regression for Bash launcher) ---
if [[ ! -x "${TOOL}/.venv/bin/python" ]]; then
  bad "expected installer to create .venv/bin/python"
else
  (
    cd "${TMP}"
    # Same argv shape as .cursor/mcp.json (minus serve; validate-config needs no mcp SDK).
    "${TOOL}/.venv/bin/python" "${TOOL}/bin/py-indexer" validate-config >/dev/null
  ) && ok "venv python executes bin/py-indexer (MCP argv shape)" \
    || bad "venv python cannot execute bin/py-indexer — MCP would fail to start"
fi

echo
echo "tools-cli: ${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]
