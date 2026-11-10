#!/usr/bin/env bash
TOOL_NAME="py-indexer"
TOOL_DESC="Local cross-repo lexical code retrieval (user-wide CLI + read-only stdio MCP)"
TOOL_DEPENDS=()
# Project-local machine config must never be overwritten on reinstall/--force.
# (Seeded separately; listed here for documentation / future generic copy.)
TOOL_PRESERVE=(
  ".repo-kit/tools/py-indexer/repos.json"
)
# Minimum shared application compat_version accepted without upgrade prompt.
TOOL_PY_INDEXER_COMPAT="0.3.3"
