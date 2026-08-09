#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPSTREAM="$ROOT/vendor/opensources/upstream"
ENGINES="$ROOT/data/engines"
BUILD="$ROOT/.runtime/build"
INSTALL_TRELLIS=1
INSTALL_TRIPOSR=1
FORCE=0
for arg in "$@"; do
  [[ "$arg" == "--trellis-only" ]] && INSTALL_TRIPOSR=0
  [[ "$arg" == "--triposr-only" ]] && INSTALL_TRELLIS=0
  [[ "$arg" == "--force" ]] && FORCE=1
done
mkdir -p "$ENGINES" "$BUILD"
[[ -d "$UPSTREAM/trellis.cpp/.git" && -d "$UPSTREAM/TripoSR/.git" ]] || "$ROOT/utilities/bootstrap-opensources.sh"

if [[ $INSTALL_TRELLIS -eq 1 ]]; then
  command -v cmake >/dev/null || { echo 'CMake is required for trellis.cpp.' >&2; exit 1; }
  SRC="$UPSTREAM/trellis.cpp"; B="$BUILD/trellis.cpp"; DEST="$ENGINES/trellis.cpp"
  [[ $FORCE -eq 0 ]] || rm -rf "$B" "$DEST"
  cmake -S "$SRC" -B "$B" -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=89 -DTRELLIS_WEBP=ON -DCMAKE_BUILD_TYPE=Release
  cmake --build "$B" --config Release --parallel
  CLI="$(find "$B" -type f \( -name trellis-cli -o -name trellis-cli.exe \) | head -1)"
  [[ -n "$CLI" ]] || { echo 'trellis-cli was not generated.' >&2; exit 1; }
  mkdir -p "$DEST"; cp -a "$(dirname "$CLI")/." "$DEST/"
  echo "trellis.cpp installed: $DEST"
  echo "Weights are still required under $ROOT/data/models/trellis2; the app preflight blocks generation until they exist."
fi

if [[ $INSTALL_TRIPOSR -eq 1 ]]; then
  SRC="$UPSTREAM/TripoSR"; DEST="$ENGINES/TripoSR"
  [[ $FORCE -eq 0 ]] || rm -rf "$DEST"
  if [[ ! -d "$DEST/.git" ]]; then git clone --shared "$SRC" "$DEST"; fi
  git -C "$DEST" checkout --detach 107cefdc244c39106fa830359024f6a2f1c78871
  python3 -m venv "$DEST/venv"
  "$DEST/venv/bin/python" -m pip install -r "$DEST/requirements.txt"
  "$DEST/venv/bin/python" - <<'PY'
import torch
print({'torch': torch.__version__, 'cuda_available': torch.cuda.is_available()})
PY
  echo "TripoSR installed: $DEST"
fi
