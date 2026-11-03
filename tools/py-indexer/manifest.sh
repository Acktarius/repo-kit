#!/usr/bin/env bash
TOOL_NAME="py-indexer"
TOOL_DESC="Local cross-repo lexical code retrieval (CLI + read-only stdio MCP)"
TOOL_DEPENDS=()
# User may edit excludes.txt after install; never overwrite on reinstall/--force.
TOOL_PRESERVE=(
  ".repo-kit/tools/py-indexer/excludes.txt"
)
