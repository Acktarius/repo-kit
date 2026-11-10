#!/usr/bin/env bash
# Installed-app isolation: source removal, optional offline wheel, spaces in XDG paths.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

fail=0
pass=0
ok() { pass=$((pass + 1)); echo "PASS: $*"; }
bad() { fail=$((fail + 1)); echo "FAIL: $*" >&2; }

# --- install from a temporary kit copy, then make that source unavailable ---
KIT="${TMP}/reloc-kit"
mkdir -p "${KIT}/modules" "${KIT}/tools"
cp -a "${ROOT}/scripts" "${KIT}/scripts"
cp -a "${ROOT}/modules/base" "${KIT}/modules/base"
cp -a "${ROOT}/tools/py-indexer" "${KIT}/tools/py-indexer"
cp "${ROOT}/VERSION" "${KIT}/VERSION"
rm -rf "${KIT}/tools/py-indexer/build" "${KIT}/tools/py-indexer/src/"*.egg-info

RELOC_HOME="${TMP}/reloc-home"
RELOC_DATA="${TMP}/reloc-data"
RELOC_CACHE="${TMP}/reloc-cache"
RELOC_BIN="${TMP}/reloc-bin"
mkdir -p "${RELOC_HOME}" "${RELOC_DATA}" "${RELOC_CACHE}" "${RELOC_BIN}"
RELOC_TARGET="${TMP}/reloc-project"
mkdir -p "${RELOC_TARGET}"
printf 'export const relocatedToken = 1;\n' >"${RELOC_TARGET}/reloc.ts"
git -C "${RELOC_TARGET}" init -q

HOME="${RELOC_HOME}" XDG_DATA_HOME="${RELOC_DATA}" XDG_CACHE_HOME="${RELOC_CACHE}" \
  XDG_BIN_HOME="${RELOC_BIN}" REPO_KIT_TOOL_ASSUME_YES=1 REPO_KIT_TOOL_SKIP_DEPS=1 \
  "${KIT}/scripts/init.sh" "${RELOC_TARGET}" --tool py-indexer >"${TMP}/reloc-init.out"

rm -rf "${KIT}/tools/py-indexer"
env -u PYTHONPATH HOME="${RELOC_HOME}" XDG_DATA_HOME="${RELOC_DATA}" \
  XDG_CACHE_HOME="${RELOC_CACHE}" XDG_BIN_HOME="${RELOC_BIN}" \
  "${RELOC_BIN}/py-indexer" --app-id >"${TMP}/reloc-app.json"
python3 - "${TMP}/reloc-app.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
assert doc["name"] == "py-indexer", doc
assert doc["cli_ready"] is True, doc
assert doc["mcp_ready"] is False, doc
PY
installed="$(find "${RELOC_DATA}/py-indexer/venv" -path '*/site-packages/py_indexer/__init__.py' -print -quit)"
[[ -n "${installed}" ]] || { echo "installed package missing" >&2; exit 1; }
if [[ "${installed}" == "${KIT}"* ]]; then
  bad "installed package still points at the removed kit"
else
  ok "installed CLI runs after the source copy is removed"
fi

# --- wheel install when an offline build backend is already present ---
if python3 -c 'import setuptools' >/dev/null 2>&1 \
  && python3 -m pip wheel --help >/dev/null 2>&1; then
  WHEEL_SRC="${TMP}/wheel-src"
  mkdir -p "${WHEEL_SRC}"
  cp -a "${ROOT}/tools/py-indexer/." "${WHEEL_SRC}/"
  rm -rf "${WHEEL_SRC}/build" "${WHEEL_SRC}/src/"*.egg-info
  WHEEL_DIR="${TMP}/wheels"
  set +e
  PIP_NO_INDEX=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    python3 -m pip wheel --no-deps --no-build-isolation -w "${WHEEL_DIR}" "${WHEEL_SRC}" \
    >"${TMP}/wheel-build.out" 2>&1
  wheel_rc=$?
  set -e
  if [[ "${wheel_rc}" -ne 0 ]]; then
    echo "SKIP: offline wheel build unavailable"
    sed -n '1,40p' "${TMP}/wheel-build.out" >&2 || true
  else
    python3 -m venv "${TMP}/wheel-venv"
    PIP_NO_INDEX=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
      "${TMP}/wheel-venv/bin/python" -m pip install --no-index --no-deps \
      --find-links "${WHEEL_DIR}" py-indexer >"${TMP}/wheel-install.out"
    rm -rf "${WHEEL_SRC}"
    env -u PYTHONPATH "${TMP}/wheel-venv/bin/python" -m py_indexer --app-id >"${TMP}/wheel-app.json"
    python3 - "${TMP}/wheel-app.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
assert doc["cli_ready"] is True, doc
PY
    ok "wheel install runs with PYTHONPATH unset after source removal"
  fi
else
  echo "SKIP: wheel install (setuptools or pip wheel unavailable)"
fi

# --- launcher when HOME / XDG paths contain spaces ---
SPACE_HOME="${TMP}/home with spaces"
SPACE_DATA="${TMP}/xdg data"
SPACE_CACHE="${TMP}/xdg cache"
SPACE_BIN="${TMP}/xdg bin"
mkdir -p "${SPACE_HOME}" "${SPACE_DATA}" "${SPACE_CACHE}" "${SPACE_BIN}"
SPACE_TARGET="${TMP}/space project"
mkdir -p "${SPACE_TARGET}"
HOME="${SPACE_HOME}" XDG_DATA_HOME="${SPACE_DATA}" XDG_CACHE_HOME="${SPACE_CACHE}" \
  XDG_BIN_HOME="${SPACE_BIN}" REPO_KIT_TOOL_ASSUME_YES=1 REPO_KIT_TOOL_SKIP_DEPS=1 \
  "${ROOT}/scripts/init.sh" "${SPACE_TARGET}" --tool py-indexer >"${TMP}/space-init.out"
launcher="$(find "${SPACE_DATA}/py-indexer/venv/bin/py-indexer" -type f -print -quit)"
[[ -n "${launcher}" ]]
head -1 "${launcher}" | grep -qx '#!/bin/sh'
grep -q 'exec ' "${launcher}"
HOME="${SPACE_HOME}" XDG_DATA_HOME="${SPACE_DATA}" XDG_CACHE_HOME="${SPACE_CACHE}" \
  XDG_BIN_HOME="${SPACE_BIN}" \
  "${SPACE_BIN}/py-indexer" --app-id >"${TMP}/space-app.json"
python3 - "${TMP}/space-app.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
assert doc["name"] == "py-indexer" and doc["cli_ready"] is True, doc
PY
ok "offline launcher runs when XDG paths contain spaces"

# --- a 0.2.1 probe is not reused; upgrade is consented ---
OLD_HOME="${TMP}/old-home"
OLD_DATA="${TMP}/old-data"
OLD_CACHE="${TMP}/old-cache"
OLD_BIN="${TMP}/old-bin"
mkdir -p "${OLD_HOME}" "${OLD_DATA}" "${OLD_CACHE}" "${OLD_BIN}"
cat >"${OLD_BIN}/py-indexer" <<'EOF'
#!/bin/sh
cat <<'JSON'
{
  "name": "py-indexer",
  "version": "0.2.1",
  "compat_version": "0.2.1",
  "schema_version": 1,
  "fts5": true
}
JSON
EOF
chmod +x "${OLD_BIN}/py-indexer"
OLD_TARGET="${TMP}/old-project"
mkdir -p "${OLD_TARGET}"
git -C "${OLD_TARGET}" init -q
HOME="${OLD_HOME}" XDG_DATA_HOME="${OLD_DATA}" XDG_CACHE_HOME="${OLD_CACHE}" \
  XDG_BIN_HOME="${OLD_BIN}" REPO_KIT_TOOL_ASSUME_YES=1 REPO_KIT_TOOL_SKIP_DEPS=1 \
  "${ROOT}/scripts/init.sh" "${OLD_TARGET}" --tool py-indexer >"${TMP}/old-init.out"
if grep -q 'reuse     shared py-indexer' "${TMP}/old-init.out"; then
  bad "0.2.1 probe was reused: $(cat "${TMP}/old-init.out")"
elif grep -q 'incompatible py-indexer' "${TMP}/old-init.out" \
  && grep -q 'Upgrade shared py-indexer' "${TMP}/old-init.out"; then
  ok "0.2.1 probe requires a consented upgrade"
else
  bad "0.2.1 upgrade path missing: $(cat "${TMP}/old-init.out")"
fi
env -u PYTHONPATH HOME="${OLD_HOME}" XDG_DATA_HOME="${OLD_DATA}" \
  XDG_CACHE_HOME="${OLD_CACHE}" XDG_BIN_HOME="${OLD_BIN}" \
  "${OLD_BIN}/py-indexer" --app-id >"${TMP}/old-app.json"
python3 - "${TMP}/old-app.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
assert doc["compat_version"] == "0.2.2", doc
assert doc["capability"] == "staging-publish", doc
assert doc["cli_ready"] is True, doc
PY
ok "consented upgrade replaces the 0.2.1 probe"

echo
echo "py-indexer install: ${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]
