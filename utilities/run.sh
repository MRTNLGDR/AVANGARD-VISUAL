#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -x "$ROOT/.runtime/venv/bin/python" ]] || "$ROOT/utilities/install.sh" --skip-opensources
export CINENODE_HOME="$ROOT/data"
export CINENODE_HOST="127.0.0.1"
export CINENODE_PORT="8787"
exec "$ROOT/.runtime/venv/bin/python" -m cinenode run "$@"
