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
printf '%s' "${REQ_TEXT}" >"${NONINT}/.repo-kit/tools/py-indexer/requirements.txt"
REPO_KIT_TOOL_ASSUME_YES=1 "${ROOT}/scripts/migrate.sh" "${NONINT}" </dev/null >"${TMP}/nonint.out"
if [[ -f "${NONINT}/.repo-kit/tools/py-indexer/bin/py-indexer" ]] \
  && [[ -f "${NONINT}/.repo-kit/tools/py-indexer/requirements.txt" ]] \
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
  && [[ -f "${OURS}/.repo-kit/tools/py-indexer/bin/py-indexer" ]] \
  && grep -q 'does not match the shipped legacy launcher' "${TMP}/other.out"; then
  ok "other checkout registration stays; unverified launcher stays"
else
  bad "other checkout registration was rewritten: $(cat "${TMP}/other.out")"
fi

# --- CLI-only donor does not take over a working legacy MCP registration ---
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
happy_before="$(cat "${HAPPY}/.cursor/mcp.json")"
pty_run y "${ROOT}/scripts/migrate.sh" "${HAPPY}" >"${TMP}/happy.out"
python3 - "${HAPPY}/.cursor/mcp.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
entry = doc["mcpServers"]["py-indexer"]
assert entry["command"].endswith(".venv/bin/python"), entry
assert entry["args"][1] == "serve", entry
assert "--config" not in entry["args"], entry
assert doc["mcpServers"]["keep"]["command"] == "true"
PY
if [[ "$(cat "${HAPPY}/.cursor/mcp.json")" == "${happy_before}" ]] \
  && [[ -e "${TOOL_H}/bin/py-indexer" && -e "${TOOL_H}/.venv" && -e "${TOOL_H}/py_indexer" ]] \
  && [[ ! -e "${TOOL_H}/index" && ! -e "${TOOL_H}/requirements.txt" ]] \
  && [[ -f "${TOOL_H}/repos.json" && -f "${TOOL_H}/excludes.txt" ]] \
  && grep -q 'legacy MCP remains active' "${TMP}/happy.out"; then
  ok "CLI-only migration keeps the legacy registration, launcher, package, and venv"
else
  bad "CLI-only migration rewrote MCP or deleted its runtime: $(cat "${TMP}/happy.out")"
fi

# --- unknown file inside a virtualenv, and a modified shipped module ---
VENV_UNKNOWN="${TMP}/venv-unknown"
write_version "${VENV_UNKNOWN}"
TOOL_V="${VENV_UNKNOWN}/.repo-kit/tools/py-indexer"
seed_venv "${TOOL_V}"
printf 'user note\n' >"${TOOL_V}/.venv/user-note.txt"
pty_run y "${ROOT}/scripts/migrate.sh" "${VENV_UNKNOWN}" >"${TMP}/venv-unknown.out"
if [[ -f "${TOOL_V}/.venv/user-note.txt" && -f "${TOOL_V}/.venv/pyvenv.cfg" ]] \
  && grep -q 'ownership cannot be verified' "${TMP}/venv-unknown.out"; then
  ok "unknown virtualenv file keeps the virtualenv"
else
  bad "virtualenv with an unknown file was removed: $(cat "${TMP}/venv-unknown.out")"
fi

MOD="${TMP}/modified-pkg"
write_version "${MOD}"
TOOL_P="${MOD}/.repo-kit/tools/py-indexer"
mkdir -p "${TOOL_P}/py_indexer"
while IFS= read -r rel; do
  git -C "${ROOT}" show "063b9df^:${rel}" >"${TOOL_P}/py_indexer/$(basename "${rel}")"
done < <(git -C "${ROOT}" ls-tree -r --name-only 063b9df^ -- tools/py-indexer/files/.repo-kit/tools/py-indexer/py_indexer)
printf '\n# local edit\n' >>"${TOOL_P}/py_indexer/__init__.py"
pty_run y "${ROOT}/scripts/migrate.sh" "${MOD}" >"${TMP}/modified.out"
if [[ -f "${TOOL_P}/py_indexer/__init__.py" ]] \
  && grep -q 'modified or could not be verified' "${TMP}/modified.out"; then
  ok "modified legacy module keeps the package directory"
else
  bad "modified legacy package was removed: $(cat "${TMP}/modified.out")"
fi

EXACT="${TMP}/exact-bytes"
write_version "${EXACT}"
TOOL_E="${EXACT}/.repo-kit/tools/py-indexer"
mkdir -p "${TOOL_E}/bin" "${TOOL_E}/py_indexer"
git -C "${ROOT}" show "063b9df^:tools/py-indexer/files/.repo-kit/tools/py-indexer/bin/py-indexer" \
  >"${TOOL_E}/bin/py-indexer"
chmod +x "${TOOL_E}/bin/py-indexer"
while IFS= read -r rel; do
  git -C "${ROOT}" show "063b9df^:${rel}" >"${TOOL_E}/py_indexer/$(basename "${rel}")"
done < <(git -C "${ROOT}" ls-tree -r --name-only 063b9df^ -- tools/py-indexer/files/.repo-kit/tools/py-indexer/py_indexer)
pty_run y "${ROOT}/scripts/migrate.sh" "${EXACT}" >"${TMP}/exact.out"
if [[ ! -e "${TOOL_E}/bin" && ! -e "${TOOL_E}/py_indexer" ]]; then
  ok "byte-matched launcher and package are removed when no MCP registration uses them"
else
  bad "byte-matched legacy runtime was kept: $(cat "${TMP}/exact.out")"
fi

# A registration already pointed at the CLI-only shared executable is restored.
RESTORE="${TMP}/restore"
write_version "${RESTORE}"
TOOL_S="${RESTORE}/.repo-kit/tools/py-indexer"
seed_bin "${TOOL_S}"
seed_venv "${TOOL_S}"
mkdir -p "${RESTORE}/.cursor"
python3 - "${RESTORE}/.cursor/mcp.json" "${XDG_BIN_HOME}/py-indexer" <<'PY'
import json, sys
from pathlib import Path
path, exe = Path(sys.argv[1]), sys.argv[2]
doc = {
    "mcpServers": {
        "py-indexer": {
            "type": "stdio",
            "command": exe,
            "args": ["--config", "/tmp/repos.json", "serve"],
        }
    }
}
path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
PY
pty_run y "${ROOT}/scripts/migrate.sh" "${RESTORE}" >"${TMP}/restore.out"
python3 - "${RESTORE}/.cursor/mcp.json" <<'PY'
import json, sys
entry = json.load(open(sys.argv[1], encoding="utf-8"))["mcpServers"]["py-indexer"]
assert entry["command"].endswith(".venv/bin/python"), entry
assert entry["args"][1] == "serve", entry
assert "--config" not in entry["args"], entry
PY
if [[ -e "${TOOL_S}/bin/py-indexer" && -d "${TOOL_S}/.venv" ]] \
  && grep -q 'restored the legacy MCP registration' "${TMP}/restore.out"; then
  ok "CLI-only registration is restored to the legacy runtime"
else
  bad "broken registration was left pointing at the CLI-only app: $(cat "${TMP}/restore.out")"
fi

if [[ -n "${PY_INDEXER_MCP_PYTHON:-}" ]] \
  && "${PY_INDEXER_MCP_PYTHON}" -c 'from mcp.server.fastmcp import FastMCP' >/dev/null 2>&1; then
  MCP_HOME="${TMP}/mcp-home"
  MCP_DATA="${TMP}/mcp-data"
  MCP_CACHE="${TMP}/mcp-cache"
  MCP_BIN="${TMP}/mcp-bin"
  MCP_PKG="${TMP}/mcp-pkg"
  mkdir -p "${MCP_HOME}" "${MCP_DATA}" "${MCP_CACHE}" "${MCP_BIN}" "${MCP_PKG}"
  cp -a "${ROOT}/tools/py-indexer/src/py_indexer" "${MCP_PKG}/py_indexer"
  # A venv created from another venv does not see that venv's site-packages.
  # Point the shared launcher at the already provisioned interpreter.
  cat >"${MCP_BIN}/py-indexer" <<EOF
#!/bin/sh
export PYTHONPATH='${MCP_PKG}'
exec '${PY_INDEXER_MCP_PYTHON}' -m py_indexer "\$@"
EOF
  chmod +x "${MCP_BIN}/py-indexer"
  HOME="${MCP_HOME}" XDG_DATA_HOME="${MCP_DATA}" XDG_CACHE_HOME="${MCP_CACHE}" \
    XDG_BIN_HOME="${MCP_BIN}" "${MCP_BIN}/py-indexer" --app-id >"${TMP}/mcp-ready-app.json"
  python3 - "${TMP}/mcp-ready-app.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
assert doc.get("mcp_ready") is True, doc
assert doc.get("capability") == "staging-publish", doc
PY
  READY="${TMP}/mcp-ready"
  write_version "${READY}"
  TOOL_R="${READY}/.repo-kit/tools/py-indexer"
  mkdir -p "${TOOL_R}/bin" "${TOOL_R}/py_indexer" "${TOOL_R}/.venv/bin" "${READY}/.cursor"
  git -C "${ROOT}" show "063b9df^:tools/py-indexer/files/.repo-kit/tools/py-indexer/bin/py-indexer" \
    >"${TOOL_R}/bin/py-indexer"
  chmod +x "${TOOL_R}/bin/py-indexer"
  while IFS= read -r rel; do
    git -C "${ROOT}" show "063b9df^:${rel}" >"${TOOL_R}/py_indexer/$(basename "${rel}")"
  done < <(git -C "${ROOT}" ls-tree -r --name-only 063b9df^ -- tools/py-indexer/files/.repo-kit/tools/py-indexer/py_indexer)
  printf 'home = /tmp\n' >"${TOOL_R}/.venv/pyvenv.cfg"
  printf '#!/bin/sh\nexit 0\n' >"${TOOL_R}/.venv/bin/python"
  chmod +x "${TOOL_R}/.venv/bin/python"
  python3 - "${READY}" <<'PY'
import json, sys
from pathlib import Path
target = Path(sys.argv[1])
doc = {
    "mcpServers": {
        "py-indexer": {
            "type": "stdio",
            "command": "${workspaceFolder}/.repo-kit/tools/py-indexer/.venv/bin/python",
            "args": ["${workspaceFolder}/.repo-kit/tools/py-indexer/bin/py-indexer", "serve"],
        }
    }
}
(target / ".cursor/mcp.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
PY
  (
    export HOME="${MCP_HOME}" XDG_DATA_HOME="${MCP_DATA}" XDG_CACHE_HOME="${MCP_CACHE}" XDG_BIN_HOME="${MCP_BIN}"
    pty_run y "${ROOT}/scripts/migrate.sh" "${READY}"
  ) >"${TMP}/mcp-ready.out"
  if ! python3 - "${READY}/.cursor/mcp.json" "${MCP_BIN}/py-indexer" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
entry = doc["mcpServers"]["py-indexer"]
if entry.get("command") != sys.argv[2] or entry.get("args", [None, None, None])[2] != "serve":
    raise SystemExit(1)
PY
  then
    bad "MCP-ready migration did not switch registration: $(cat "${TMP}/mcp-ready.out")"
  elif [[ ! -e "${TOOL_R}/bin" && ! -e "${TOOL_R}/py_indexer" && -d "${TOOL_R}/.venv" ]] \
    && grep -q 'ownership cannot be verified' "${TMP}/mcp-ready.out"; then
    ok "MCP-ready migration switches registration and keeps the unverified virtualenv"
  else
    bad "MCP-ready migration mismatch: $(cat "${TMP}/mcp-ready.out")"
  fi
else
  echo "NOT RUN: MCP-ready legacy migration (no provisioned interpreter with mcp.server.fastmcp.FastMCP)"
fi

echo
echo "py-indexer migrate: ${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]
