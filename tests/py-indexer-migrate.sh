#!/usr/bin/env bash
# Direct migrate.sh cleanup gates. Isolated HOME / XDG. No network.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

fail=0
pass=0
ok() { pass=$((pass + 1)); echo "PASS: $*"; }
bad() { fail=$((fail + 1)); echo "FAIL: $*" >&2; }

export HOME="${TMP}/home"
export XDG_DATA_HOME="${TMP}/xdg-data"
export XDG_CACHE_HOME="${TMP}/xdg-cache"
export XDG_BIN_HOME="${TMP}/xdg-bin"
mkdir -p "${HOME}" "${XDG_DATA_HOME}" "${XDG_CACHE_HOME}" "${XDG_BIN_HOME}"
KIT_VER="$(tr -d '[:space:]' < "${ROOT}/VERSION")"

REQ_TEXT='# Optional MCP dependency. Indexing and CLI search work without it.
# Pin matched to FastMCP stdio API used by py_indexer.mcp_server.
mcp==1.30.0
'

pty_run() {
  local answer="$1"
  shift
  python3 - "${answer}" "$@" <<'PY'
import os, pty, select, subprocess, sys, time
answer = sys.argv[1]
cmd = sys.argv[2:]
master, slave = pty.openpty()
proc = subprocess.Popen(cmd, stdin=slave, stdout=slave, stderr=subprocess.STDOUT, close_fds=True)
os.close(slave)
buf = b""
sent = False
deadline = time.time() + 90
while time.time() < deadline:
    ready, _, _ = select.select([master], [], [], 0.2)
    if ready:
        try:
            chunk = os.read(master, 4096)
        except OSError:
            break
        if not chunk:
            break
        buf += chunk
        if not sent and b"[y/N]" in buf:
            os.write(master, (answer + "\n").encode())
            sent = True
    elif proc.poll() is not None:
        break
rc = proc.wait(timeout=20)
while True:
    ready, _, _ = select.select([master], [], [], 0.1)
    if not ready:
        break
    try:
        chunk = os.read(master, 4096)
    except OSError:
        break
    if not chunk:
        break
    buf += chunk
os.close(master)
sys.stdout.buffer.write(buf)
raise SystemExit(rc)
PY
}

write_version() {
  mkdir -p "$1/.repo-kit"
  printf '%s\n' "${KIT_VER}" >"$1/.repo-kit/version"
}

seed_bin() {
  local tool="$1"
  mkdir -p "${tool}/bin"
  printf '#!/bin/sh\nexit 0\n' >"${tool}/bin/py-indexer"
  chmod +x "${tool}/bin/py-indexer"
}

seed_venv() {
  local tool="$1"
  mkdir -p "${tool}/.venv/bin"
  printf 'home = /tmp\n' >"${tool}/.venv/pyvenv.cfg"
  printf '#!/bin/sh\nexit 0\n' >"${tool}/.venv/bin/python"
  chmod +x "${tool}/.venv/bin/python"
}

# --- missing shared app: a yes must not delete the only install ---
MISSING="${TMP}/missing-app"
write_version "${MISSING}"
seed_bin "${MISSING}/.repo-kit/tools/py-indexer"
(
  export HOME="${TMP}/home-missing"
  export XDG_DATA_HOME="${TMP}/xdg-missing"
  export XDG_CACHE_HOME="${TMP}/cache-missing"
  export XDG_BIN_HOME="${TMP}/bin-missing"
  mkdir -p "${HOME}" "${XDG_DATA_HOME}" "${XDG_CACHE_HOME}" "${XDG_BIN_HOME}"
  export REPO_KIT_TOOL_ASSUME_YES=1
  out="$(pty_run y "${ROOT}/scripts/migrate.sh" "${MISSING}")"
  printf '%s\n' "${out}"
) >"${TMP}/missing.out"
if [[ -f "${MISSING}/.repo-kit/tools/py-indexer/bin/py-indexer" ]] \
  && grep -q 'no verified shared py-indexer' "${TMP}/missing.out"; then
  ok "missing shared app keeps project-local runtime"
else
  bad "missing shared app deleted or did not explain: $(cat "${TMP}/missing.out")"
fi

# Shared CLI for the remaining cases.
DONOR="${TMP}/donor"
mkdir -p "${DONOR}"
REPO_KIT_TOOL_ASSUME_YES=1 REPO_KIT_TOOL_SKIP_DEPS=1 \
  "${ROOT}/scripts/init.sh" "${DONOR}" --tool py-indexer >/dev/null

# --- declined and noninteractive ---
DECLINED="${TMP}/declined"
write_version "${DECLINED}"
seed_bin "${DECLINED}/.repo-kit/tools/py-indexer"
pty_run n "${ROOT}/scripts/migrate.sh" "${DECLINED}" >"${TMP}/declined.out"
if [[ -f "${DECLINED}/.repo-kit/tools/py-indexer/bin/py-indexer" ]] \
  && grep -q 'left in place' "${TMP}/declined.out"; then
  ok "declined cleanup leaves files"
else
  bad "declined cleanup removed files: $(cat "${TMP}/declined.out")"
fi

NONINT="${TMP}/nonint"
write_version "${NONINT}"
seed_bin "${NONINT}/.repo-kit/tools/py-indexer"
REPO_KIT_TOOL_ASSUME_YES=1 "${ROOT}/scripts/migrate.sh" "${NONINT}" </dev/null >"${TMP}/nonint.out"
if [[ -f "${NONINT}/.repo-kit/tools/py-indexer/bin/py-indexer" ]] \
  && grep -q 'skip' "${TMP}/nonint.out"; then
  ok "noninteractive ASSUME_YES does not delete"
else
  bad "noninteractive cleanup deleted files: $(cat "${TMP}/nonint.out")"
fi

# --- unknown file inside a legacy directory ---
UNKNOWN="${TMP}/unknown"
write_version "${UNKNOWN}"
TOOL_U="${UNKNOWN}/.repo-kit/tools/py-indexer"
seed_bin "${TOOL_U}"
printf 'keep me\n' >"${TOOL_U}/bin/notes.txt"
pty_run y "${ROOT}/scripts/migrate.sh" "${UNKNOWN}" >"${TMP}/unknown.out"
if [[ -f "${TOOL_U}/bin/py-indexer" && -f "${TOOL_U}/bin/notes.txt" ]] \
  && grep -q 'other than the legacy launcher' "${TMP}/unknown.out"; then
  ok "unknown file keeps the legacy directory"
else
  bad "unknown legacy contents were removed: $(cat "${TMP}/unknown.out")"
fi

# --- unrelated cache directory and a positively identified file ---
CACHE_CASE="${TMP}/cache-case"
write_version "${CACHE_CASE}"
TOOL_C="${CACHE_CASE}/.repo-kit/tools/py-indexer"
mkdir -p "${TOOL_C}" "${XDG_CACHE_HOME}/py-indexer/indexes/not-ours"
printf 'leave\n' >"${XDG_CACHE_HOME}/py-indexer/indexes/not-ours/keep.txt"
printf 'leave\n' >"${XDG_CACHE_HOME}/py-indexer/indexes/canonical.sqlite3"
printf '%s' "${REQ_TEXT}" >"${TOOL_C}/requirements.txt"
printf '{"schema_version":1}\n' >"${TOOL_C}/repos.json"
printf '*.keep\n' >"${TOOL_C}/excludes.txt"
pty_run y "${ROOT}/scripts/migrate.sh" "${CACHE_CASE}" >"${TMP}/cache.out"
if [[ -f "${XDG_CACHE_HOME}/py-indexer/indexes/not-ours/keep.txt" ]] \
  && [[ -f "${XDG_CACHE_HOME}/py-indexer/indexes/canonical.sqlite3" ]] \
  && [[ ! -f "${TOOL_C}/requirements.txt" ]] \
  && [[ -f "${TOOL_C}/repos.json" && -f "${TOOL_C}/excludes.txt" ]] \
  && grep -q 'not a legacy project index' "${TMP}/cache.out"; then
  ok "cache directories stay; exact legacy requirements.txt is removed"
else
  bad "cache/requirements cleanup wrong: $(cat "${TMP}/cache.out")"
fi

# --- refused / custom MCP registration ---
CUSTOM="${TMP}/custom-mcp"
write_version "${CUSTOM}"
TOOL_M="${CUSTOM}/.repo-kit/tools/py-indexer"
seed_venv "${TOOL_M}"
seed_bin "${TOOL_M}"
mkdir -p "${CUSTOM}/.cursor"
python3 - "${CUSTOM}" <<'PY'
import json, sys
from pathlib import Path
target = Path(sys.argv[1])
tool = target / ".repo-kit/tools/py-indexer"
doc = {
    "mcpServers": {
        "py-indexer": {
            "type": "stdio",
            "command": str(tool / ".venv/bin/python"),
            "args": [str(tool / "bin/py-indexer"), "serve"],
            "env": {"PY_INDEXER_CUSTOM": "1"},
        }
    }
}
(target / ".cursor/mcp.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
PY
pty_run y "${ROOT}/scripts/migrate.sh" "${CUSTOM}" >"${TMP}/custom.out"
python3 - "${CUSTOM}/.cursor/mcp.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
entry = doc["mcpServers"]["py-indexer"]
assert entry["env"]["PY_INDEXER_CUSTOM"] == "1", entry
assert entry["command"].endswith("/.venv/bin/python"), entry
PY
if [[ -d "${TOOL_M}/.venv" && -f "${TOOL_M}/bin/py-indexer" ]] \
  && [[ -f "${TOOL_M}/mcp.fragment.json" ]] \
  && grep -q 'differs' "${TMP}/custom.out"; then
  ok "custom MCP registration and its files stay"
else
  bad "custom MCP cleanup failed: $(cat "${TMP}/custom.out")"
fi

# --- another checkout's registration is not rewritten ---
OTHER="${TMP}/other-checkout"
mkdir -p "${OTHER}/.repo-kit/tools/py-indexer/.venv/bin"
printf 'other\n' >"${OTHER}/.repo-kit/tools/py-indexer/.venv/bin/python"
OURS="${TMP}/ours-checkout"
write_version "${OURS}"
seed_bin "${OURS}/.repo-kit/tools/py-indexer"
mkdir -p "${OURS}/.cursor"
python3 - "${OURS}/.cursor/mcp.json" "${OTHER}" <<'PY'
import json, sys
from pathlib import Path
path, other = Path(sys.argv[1]), Path(sys.argv[2])
tool = other / ".repo-kit/tools/py-indexer"
doc = {
    "mcpServers": {
        "py-indexer": {
            "type": "stdio",
            "command": str(tool / ".venv/bin/python"),
            "args": [str(tool / "bin/py-indexer"), "serve"],
        }
    }
}
path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
PY
pty_run y "${ROOT}/scripts/migrate.sh" "${OURS}" >"${TMP}/other.out"
python3 - "${OURS}/.cursor/mcp.json" "${OTHER}" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
other = sys.argv[2]
assert other in doc["mcpServers"]["py-indexer"]["command"], doc
PY
if [[ -f "${OTHER}/.repo-kit/tools/py-indexer/.venv/bin/python" ]] \
  && [[ ! -e "${OURS}/.repo-kit/tools/py-indexer/bin/py-indexer" ]]; then
  ok "other checkout registration stays; this project's unreferenced launcher can go"
else
  bad "other checkout registration was rewritten: $(cat "${TMP}/other.out")"
fi

# --- exact legacy entry migrates, known files go, config stays ---
HAPPY="${TMP}/happy"
write_version "${HAPPY}"
TOOL_H="${HAPPY}/.repo-kit/tools/py-indexer"
seed_bin "${TOOL_H}"
seed_venv "${TOOL_H}"
mkdir -p "${TOOL_H}/py_indexer" "${TOOL_H}/index" "${HAPPY}/.cursor"
printf 'x = 1\n' >"${TOOL_H}/py_indexer/__init__.py"
printf 'x' >"${TOOL_H}/index/app.sqlite3"
printf '%s' "${REQ_TEXT}" >"${TOOL_H}/requirements.txt"
printf '{"schema_version":1,"keep":true}\n' >"${TOOL_H}/repos.json"
printf '*.custom\n' >"${TOOL_H}/excludes.txt"
python3 - "${HAPPY}" <<'PY'
import json, sys
from pathlib import Path
target = Path(sys.argv[1])
tool = target / ".repo-kit/tools/py-indexer"
doc = {
    "mcpServers": {
        "py-indexer": {
            "type": "stdio",
            "command": "${workspaceFolder}/.repo-kit/tools/py-indexer/.venv/bin/python",
            "args": ["${workspaceFolder}/.repo-kit/tools/py-indexer/bin/py-indexer", "serve"],
        },
        "keep": {"command": "true"},
    }
}
(target / ".cursor/mcp.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
PY
pty_run y "${ROOT}/scripts/migrate.sh" "${HAPPY}" >"${TMP}/happy.out"
python3 - "${HAPPY}/.cursor/mcp.json" "${XDG_BIN_HOME}/py-indexer" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
entry = doc["mcpServers"]["py-indexer"]
assert entry["command"] == sys.argv[2], entry
assert entry["args"][0] == "--config" and entry["args"][2] == "serve"
assert doc["mcpServers"]["keep"]["command"] == "true"
PY
if [[ ! -e "${TOOL_H}/bin" && ! -e "${TOOL_H}/.venv" && ! -e "${TOOL_H}/py_indexer" \
  && ! -e "${TOOL_H}/index" && ! -e "${TOOL_H}/requirements.txt" \
  && -f "${TOOL_H}/repos.json" && -f "${TOOL_H}/excludes.txt" ]]; then
  ok "exact legacy MCP migrated and only known runtime files removed"
else
  bad "happy-path cleanup mismatch: $(cat "${TMP}/happy.out")"
fi

echo
echo "py-indexer migrate: ${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]
