#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPSTREAM="$ROOT/vendor/opensources/upstream/ComfyUI"
DEST="$ROOT/data/engines/ComfyUI"
FORCE=0; [[ " ${*:-} " == *' --force '* ]] && FORCE=1
[[ -d "$UPSTREAM/.git" ]] || "$ROOT/utilities/bootstrap-opensources.sh"
[[ $FORCE -eq 0 ]] || rm -rf "$DEST"
if [[ ! -d "$DEST/.git" ]]; then git clone --shared "$UPSTREAM" "$DEST"; fi
git -C "$DEST" checkout --detach 2eb609766a749e3104485979615e062e401bab97
python3 -m venv "$DEST/venv"
"$DEST/venv/bin/python" -m pip install -r "$DEST/requirements.txt"
cat > "$DEST/run-cinenode.sh" <<RUN
#!/usr/bin/env bash
exec "$DEST/venv/bin/python" "$DEST/main.py" --listen 127.0.0.1 --port 8188
RUN
chmod +x "$DEST/run-cinenode.sh"
echo "ComfyUI installed. Start: $DEST/run-cinenode.sh"
