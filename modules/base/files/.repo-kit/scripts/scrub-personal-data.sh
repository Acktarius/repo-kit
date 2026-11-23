#!/usr/bin/env bash
# Scan git-tracked files for personal data; optionally replace hits with placeholders.
# Stdlib-only Python: no venv, no pip. See scrub-personal-data.py --help.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
py_script="${script_dir}/scrub-personal-data.py"

if [[ ! -f "${py_script}" ]]; then
  echo "scrub-personal-data: missing ${py_script}" >&2
  exit 2
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "scrub-personal-data: python3 is required (install python3, e.g. sudo apt install python3)" >&2
  exit 127
fi

exec python3 "${py_script}" "$@"
