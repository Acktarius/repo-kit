#!/usr/bin/env bash
# py-indexer: offline-by-default suite.
#
# Default: stdlib unit tests + installer regressions (no networked pip).
# MCP e2e: supply PY_INDEXER_MCP_PYTHON (interpreter that already has mcp==1.30.x).
# Strict:  PY_INDEXER_MCP_STRICT=1 fails if MCP env is missing/unusable.
# Opt-in bootstrap (network): PY_INDEXER_MCP_BOOTSTRAP=1 creates a temp venv
# and pip-installs mcp==1.30.0 once for local/CI convenience.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1
export REPO_KIT_TOOL_SKIP_DEPS="${REPO_KIT_TOOL_SKIP_DEPS:-1}"
# Installer fixtures that need a shared app set ASSUME_YES themselves.
unset REPO_KIT_TOOL_ASSUME_YES || true

echo "== unit tests (stdlib, offline) =="
(
  cd "${ROOT}/tests/py_indexer"
  PYTHONPATH="${ROOT}/tools/py-indexer/src" python3 -m unittest \
    test_core test_cli_discovery -v
)

echo
echo "== tools-cli installer regressions (offline; SKIP_DEPS) =="
bash "${ROOT}/tests/tools-cli.sh"

echo
echo "== MCP integration =="
MCP_PY="${PY_INDEXER_MCP_PYTHON:-}"
STRICT="${PY_INDEXER_MCP_STRICT:-0}"
BOOTSTRAP="${PY_INDEXER_MCP_BOOTSTRAP:-0}"
BOOTSTRAP_ROOT=""

cleanup_bootstrap() {
  if [[ -n "${BOOTSTRAP_ROOT}" && -d "${BOOTSTRAP_ROOT}" ]]; then
    rm -rf "${BOOTSTRAP_ROOT}"
  fi
}
trap cleanup_bootstrap EXIT

if [[ -z "${MCP_PY}" && "${BOOTSTRAP}" == "1" ]]; then
  echo "opt-in: PY_INDEXER_MCP_BOOTSTRAP=1 — creating temp venv and installing mcp (network)"
  BOOTSTRAP_ROOT="$(mktemp -d)"
  python3 -m venv "${BOOTSTRAP_ROOT}/venv"
  "${BOOTSTRAP_ROOT}/venv/bin/pip" install 'mcp==1.30.0'
  MCP_PY="${BOOTSTRAP_ROOT}/venv/bin/python"
  export PY_INDEXER_MCP_PYTHON="${MCP_PY}"
fi

if [[ -n "${MCP_PY}" ]]; then
  if ! "${MCP_PY}" -c 'import mcp' 2>/dev/null; then
    echo "error: PY_INDEXER_MCP_PYTHON cannot import mcp: ${MCP_PY}" >&2
    exit 1
  fi
  echo "using PY_INDEXER_MCP_PYTHON=${MCP_PY}"
  (
    cd "${ROOT}/tests/py_indexer"
    PYTHONPATH="${ROOT}/tools/py-indexer/src" \
      "${MCP_PY}" -m unittest test_mcp_generated_config test_mcp_integration -v
  )
elif [[ "${STRICT}" == "1" ]]; then
  echo "error: PY_INDEXER_MCP_STRICT=1 but PY_INDEXER_MCP_PYTHON is unset/unusable" >&2
  echo "supply an interpreter with mcp==1.30.x, or set PY_INDEXER_MCP_BOOTSTRAP=1" >&2
  exit 1
else
  echo "SKIP: MCP integration (set PY_INDEXER_MCP_PYTHON to a python with mcp==1.30.x)"
  echo "      optional: PY_INDEXER_MCP_BOOTSTRAP=1 to pip-install into a temp venv (network)"
  echo "      optional: PY_INDEXER_MCP_STRICT=1 to fail instead of skipping"
fi

echo "py-indexer suite ok"
