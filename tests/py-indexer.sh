#!/usr/bin/env bash
# py-indexer: stdlib unit tests + optional MCP integration + install smoke.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1

echo "== unit tests (stdlib) =="
(cd "${ROOT}/tests/py_indexer" && python3 -m unittest test_core -v)

echo
echo "== MCP integration (optional) =="
MCP_RC=0
if python3 -c 'import mcp' 2>/dev/null; then
  (cd "${ROOT}/tests/py_indexer" && python3 -m unittest test_mcp_integration -v) || MCP_RC=$?
else
  # Temporary venv with pinned mcp (not stored in the repo tree).
  VENV_ROOT="$(mktemp -d)"
  VENV="${VENV_ROOT}/venv"
  cleanup_venv() { rm -rf "${VENV_ROOT}"; }
  trap cleanup_venv EXIT
  python3 -m venv "${VENV}"
  if "${VENV}/bin/pip" install -q -r \
    "${ROOT}/tools/py-indexer/files/.repo-kit/tools/py-indexer/requirements.txt" \
    && "${VENV}/bin/python" -c 'import mcp' 2>/dev/null; then
    (cd "${ROOT}/tests/py_indexer" && "${VENV}/bin/python" -m unittest test_mcp_integration -v) || MCP_RC=$?
  else
    echo "SKIP: could not import mcp after venv install (offline or pip failure)"
    MCP_RC=0
  fi
  cleanup_venv
  trap - EXIT
fi

echo
echo "== tools-cli installer regressions =="
bash "${ROOT}/tests/tools-cli.sh"

if [[ "${MCP_RC}" -ne 0 ]]; then
  echo "MCP integration failed (exit ${MCP_RC})" >&2
  exit "${MCP_RC}"
fi

echo "py-indexer suite ok"
