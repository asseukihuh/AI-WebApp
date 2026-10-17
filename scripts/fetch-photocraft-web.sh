#!/usr/bin/env bash
# Download photocraft-web-<version>.zip into vendor/photocraft-web/
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/vendor/photocraft-web"
VERSION="${PHOTOCRAFT_WEB_VERSION:-}"

resolve_latest() {
  local repo="$1"
  local url="https://api.github.com/repos/${repo}/releases/latest"
  local tag
  tag="$(curl -fsSL "$url" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tag_name',''))" 2>/dev/null || true)"
  if [ -z "$tag" ]; then
    return 1
  fi
  tag="${tag#v}"
  echo "$tag"
}

pick_asset_url() {
  local repo="$1" ver="$2"
  local body
  body="$(curl -fsSL "https://api.github.com/repos/${repo}/releases/tags/v${ver}" 2>/dev/null || true)"
  [ -n "$body" ] || return 0
  printf '%s' "$body" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
except json.JSONDecodeError:
    raise SystemExit(0)
for a in data.get('assets', []):
    n = a.get('name', '')
    if n.startswith('photocraft-web-') and n.endswith('.zip'):
        print(a['browser_download_url'])
        break
" || true
}

if [ -z "$VERSION" ]; then
  VERSION="$(resolve_latest asseukihuh/photocraft)" || VERSION="$(resolve_latest storytold/photocraft)" || {
    echo "error: could not resolve latest photocraft-web release" >&2
    exit 1
  }
fi

ASSET_URL="$(pick_asset_url asseukihuh/photocraft "$VERSION")"
if [ -z "$ASSET_URL" ]; then
  ASSET_URL="$(pick_asset_url storytold/photocraft "$VERSION")"
fi
if [ -z "$ASSET_URL" ]; then
  echo "error: no photocraft-web zip for version ${VERSION}" >&2
  exit 1
fi

TMP="$(mktemp -d)"
ZIP="$TMP/photocraft-web.zip"
echo "Fetching photocraft-web ${VERSION} ..."
curl -fsSL -o "$ZIP" "$ASSET_URL"

rm -rf "$DEST"/*
mkdir -p "$DEST"
unzip -q "$ZIP" -d "$TMP/extract"
INNER="$(find "$TMP/extract" -mindepth 1 -maxdepth 1 -type d | head -1)"
if [ -z "$INNER" ]; then
  echo "error: unexpected zip layout" >&2
  exit 1
fi
cp -R "$INNER/." "$DEST/"
rm -rf "$TMP"

echo "Installed to $DEST (version ${VERSION})"
if [ -f "$DEST/index.html" ]; then
  echo "OK: $DEST/index.html"
else
  echo "error: index.html missing after extract" >&2
  exit 1
fi
