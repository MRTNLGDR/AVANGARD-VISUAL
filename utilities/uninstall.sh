#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"$ROOT/utilities/stop.sh" || true
rm -rf "$ROOT/.runtime"
if [[ "${1:-}" == "--purge-data" ]]; then rm -rf "$ROOT/data"; fi
echo "Runtime removed. Source and data were preserved unless --purge-data was supplied."
