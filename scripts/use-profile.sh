#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${PYTHON_BIN:-python3}"

exec "$python_bin" "$repo_root/scripts/use_profile.py" --repo-root "$repo_root" "$@"
