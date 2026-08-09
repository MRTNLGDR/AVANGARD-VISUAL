#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUNDLE="${1:-recommended}"
MODELS_DIR="${2:-}"
PY="$ROOT/.runtime/venv/bin/python"
[[ -x "$PY" ]] || "$ROOT/utilities/install.sh" --skip-opensources
"$PY" -m pip install 'huggingface-hub>=0.27,<2'
ARGS=("$ROOT/models/manager.py")
[[ -z "$MODELS_DIR" ]] || ARGS+=(--models-dir "$MODELS_DIR")
ARGS+=(install "$BUNDLE")
"$PY" "${ARGS[@]}"
