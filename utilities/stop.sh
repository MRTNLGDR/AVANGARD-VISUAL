#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIDFILE="$ROOT/data/cinenode.pid"
if [[ -f "$PIDFILE" ]]; then PID="$(cat "$PIDFILE")"; kill "$PID" 2>/dev/null || true; rm -f "$PIDFILE"; echo "Stopped $PID"; else echo "CineNode is not running."; fi
