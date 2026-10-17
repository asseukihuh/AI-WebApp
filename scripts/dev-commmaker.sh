#!/usr/bin/env bash
# One-command CommMaker pre-MVP dev server (fork-first PhotoCraft vendor).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/vendor/photocraft-web"
PORT="${COMMMAKER_PORT:-8000}"

if [ ! -f "$DEST/index.html" ]; then
  echo "PhotoCraft web assets missing; installing (fork-first) ..."
  "$ROOT/scripts/install-photocraft-from-fork.sh"
elif [ ! -f "$DEST/.commmaker-source.json" ]; then
  echo "Refreshing PhotoCraft vendor metadata ..."
  "$ROOT/scripts/fetch-photocraft-web.sh"
fi

echo "Starting CommMaker dev server on http://localhost:${PORT}/home.html"
exec python3 "$ROOT/scripts/serve-static.py" --port "$PORT" "$@"
