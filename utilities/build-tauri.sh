#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.runtime/venv/bin/python"; TAURI="$ROOT/source/desktop/src-tauri"; BIN="$TAURI/binaries"; INSTALLERS="$ROOT/installers"
[[ -x "$PY" ]] || "$ROOT/utilities/install.sh" --skip-opensources
command -v cargo >/dev/null || { echo "Rust/Cargo is required." >&2; exit 1; }
command -v cargo-tauri >/dev/null || cargo install tauri-cli --version '^2' --locked
"$PY" -m pip install 'pyinstaller>=6,<7'
HOST="$(rustc -vV | awk '/^host:/{print $2}')"
[[ -n "$HOST" ]] || { echo "Rust host target unavailable" >&2; exit 1; }
mkdir -p "$BIN" "$INSTALLERS" "$ROOT/.runtime/pyinstaller"
"$PY" -m PyInstaller --noconfirm --clean --onefile --name cinenode-backend --collect-all cinenode \
  --distpath "$ROOT/.runtime/pyinstaller/dist" --workpath "$ROOT/.runtime/pyinstaller/work" --specpath "$ROOT/.runtime/pyinstaller/spec" \
  "$ROOT/utilities/backend_entry.py"
BUILT="$ROOT/.runtime/pyinstaller/dist/cinenode-backend"
[[ -x "$BUILT" ]] || { echo "Backend sidecar not generated" >&2; exit 1; }
cp "$BUILT" "$BIN/cinenode-backend-$HOST"
CINENODE_HOME="$ROOT/.runtime/sidecar-smoke" "$BUILT" init
(cd "$TAURI" && cargo tauri build)
find "$TAURI/target/release/bundle" -type f \( -name '*.AppImage' -o -name '*.deb' -o -name '*.rpm' -o -name '*.dmg' -o -name '*.msi' -o -name '*.exe' \) -exec cp -f {} "$INSTALLERS/" \;
