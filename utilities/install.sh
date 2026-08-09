#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME="$ROOT/.runtime"; VENV="$RUNTIME/venv"; DATA="$ROOT/data"
mkdir -p "$RUNTIME" "$DATA"
PYTHON=""
for p in python3.13 python3.12 python3.11 python3; do
  if command -v "$p" >/dev/null && "$p" -c 'import sys; raise SystemExit(sys.version_info < (3,11))'; then PYTHON="$p"; break; fi
done
[[ -n "$PYTHON" ]] || { echo "Python 3.11+ is required." >&2; exit 1; }
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  SUDO=""; [[ $(id -u) -eq 0 ]] || { command -v sudo >/dev/null 2>&1 && SUDO="sudo"; }
  if command -v apt-get >/dev/null 2>&1; then $SUDO apt-get update && $SUDO apt-get install -y ffmpeg
  elif command -v dnf >/dev/null 2>&1; then $SUDO dnf install -y ffmpeg
  elif command -v pacman >/dev/null 2>&1; then $SUDO pacman -Sy --noconfirm ffmpeg
  elif command -v brew >/dev/null 2>&1; then brew install ffmpeg
  else echo "Warning: FFmpeg/ffprobe are missing and no supported package manager was found." >&2
  fi
fi
[[ -x "$VENV/bin/python" ]] || "$PYTHON" -m venv "$VENV"
VENV_PYTHON="$VENV/bin/python"
if ! "$VENV_PYTHON" -m pip --version >/dev/null 2>&1; then
  "$VENV_PYTHON" -m ensurepip --upgrade
fi
WHEEL="$(find "$ROOT/utilities/installers/python" -maxdepth 1 -type f -name 'avangard_visual-*.whl' -print 2>/dev/null | sort | tail -n 1)"

validate_runtime() {
  "$VENV_PYTHON" - <<'PY'
import fastapi, httpx, multipart, pydantic, uvicorn
from importlib.metadata import version
print("Runtime dependencies validated:", {
    "fastapi": version("fastapi"),
    "uvicorn": version("uvicorn"),
    "pydantic": version("pydantic"),
    "httpx": version("httpx"),
    "python-multipart": version("python-multipart"),
})
PY
}

install_host_runtime_fallback() {
  echo "Package index unavailable; trying compatible packages already installed for $PYTHON." >&2
  HOST_PATHS="$($PYTHON - <<'PY'
import os, sys
for item in sys.path:
    if item and os.path.isdir(item) and ("site-packages" in item or "dist-packages" in item):
        print(os.path.abspath(item))
PY
)"
  [[ -n "$HOST_PATHS" ]] || { echo "No compatible host site-packages were found." >&2; return 1; }
  VENV_SITE="$($VENV_PYTHON - <<'PY'
import site
print(site.getsitepackages()[0])
PY
)"
  printf '%s\n' "$HOST_PATHS" > "$VENV_SITE/cinenode-host-runtime.pth"
  "$VENV_PYTHON" -m pip install --disable-pip-version-check --no-deps --force-reinstall "$WHEEL"
  validate_runtime
}

if [[ -n "$WHEEL" ]]; then
  echo "Installing bundled wheel: $(basename "$WHEEL")"
  if ! "$VENV_PYTHON" -m pip install --disable-pip-version-check --prefer-binary "$WHEEL"; then
    install_host_runtime_fallback || {
      echo "CineNode runtime dependencies could not be downloaded or reused from the host Python." >&2
      echo "Reconnect to a Python package index and rerun install.sh; the installer is resumable." >&2
      exit 1
    }
  else
    validate_runtime
  fi
else
  echo "Bundled wheel not found; installing from source."
  "$VENV_PYTHON" -m pip install --disable-pip-version-check --no-build-isolation -e "$ROOT/source/backend"
  validate_runtime
fi
CINENODE_HOME="$DATA" "$VENV_PYTHON" -m cinenode init
if [[ "${1:-}" != "--skip-opensources" ]]; then "$ROOT/utilities/bootstrap-opensources.sh" || echo "Warning: upstream sync failed; retry when online." >&2; fi
printf 'Installed. Run %s/utilities/run.sh\n' "$ROOT"
