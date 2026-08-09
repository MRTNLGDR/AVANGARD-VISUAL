#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA="$ROOT/data"; ENGINES="$DATA/engines"; UPSTREAM="$ROOT/vendor/opensources/upstream"
PY="$ROOT/.runtime/venv/bin/python"; FORCE=0; WITH_LLM=0; WITH_OPENCODE=0; WITH_COMFYUI=0; WITH_3D=0; ACCEPT_WANGP=0
for arg in "$@"; do
  [[ "$arg" == "--force" ]] && FORCE=1
  [[ "$arg" == "--with-llm" ]] && WITH_LLM=1
  [[ "$arg" == "--with-opencode" ]] && WITH_OPENCODE=1
  [[ "$arg" == "--with-comfyui" ]] && WITH_COMFYUI=1
  [[ "$arg" == "--with-3d" ]] && WITH_3D=1
  [[ "$arg" == "--accept-wangp-license" ]] && ACCEPT_WANGP=1
done
mkdir -p "$ENGINES"
[[ -x "$PY" ]] || "$ROOT/utilities/install.sh" --skip-opensources
command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null || { echo "FFmpeg and ffprobe are required." >&2; exit 1; }
SD_SOURCE="$UPSTREAM/stable-diffusion.cpp"
if [[ ! -d "$SD_SOURCE/.git" ]]; then
  BOOTSTRAP=()
  [[ $ACCEPT_WANGP -eq 0 ]] || BOOTSTRAP+=(--accept-wangp-license)
  "$ROOT/utilities/bootstrap-opensources.sh" "${BOOTSTRAP[@]}"
fi
command -v cmake >/dev/null || { echo "CMake is required." >&2; exit 1; }
BUILD="$ROOT/.runtime/build/stable-diffusion.cpp"; TARGET="$ENGINES/stable-diffusion.cpp/bin"
[[ $FORCE -eq 0 ]] || rm -rf "$BUILD"
mkdir -p "$BUILD" "$TARGET"
cmake -S "$SD_SOURCE" -B "$BUILD" -DSD_CUDA=ON -DSD_BUILD_EXAMPLES=ON -DSD_WEBM=ON -DCMAKE_CUDA_ARCHITECTURES=89 -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD" --parallel
SDCLI="$(find "$BUILD" -type f -name sd-cli -perm -u+x | head -1)"
[[ -n "$SDCLI" ]] || { echo "sd-cli was not generated" >&2; exit 1; }
cp -a "$(dirname "$SDCLI")/." "$TARGET/"
PORTABLE_ARGS=()
[[ $FORCE -eq 0 ]] || PORTABLE_ARGS+=(--force)
"$PY" "$ROOT/utilities/install_portable_engines.py" "${PORTABLE_ARGS[@]}"
if [[ $WITH_LLM -eq 1 ]]; then
  if ! command -v ollama >/dev/null; then curl -fsSL https://ollama.com/install.sh | sh; fi
  ollama pull qwen3:8b-q4_K_M
fi
if [[ $WITH_COMFYUI -eq 1 ]]; then
  if [[ $FORCE -eq 1 ]]; then "$ROOT/utilities/install-comfyui.sh" --force; else "$ROOT/utilities/install-comfyui.sh"; fi
fi
if [[ $WITH_3D -eq 1 ]]; then
  if [[ $FORCE -eq 1 ]]; then "$ROOT/utilities/install-3d-engines.sh" --force; else "$ROOT/utilities/install-3d-engines.sh"; fi
fi
if [[ $WITH_OPENCODE -eq 1 ]] && ! command -v opencode >/dev/null; then
  if command -v npm >/dev/null; then npm install -g opencode-ai@latest
  elif command -v brew >/dev/null; then brew install anomalyco/tap/opencode
  else echo "Install OpenCode with an official package manager." >&2; fi
fi
CINENODE_HOME="$DATA" "$PY" -m cinenode doctor
