#!/usr/bin/env bash
# Download photocraft-web-<version>.zip into vendor/photocraft-web/
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/vendor/photocraft-web"
VERSION="${PHOTOCRAFT_WEB_VERSION:-}"

FORK_REPO="${PHOTOCRAFT_FORK_REPO:-asseukihuh/photocraft}"
UPSTREAM_REPO="${PHOTOCRAFT_UPSTREAM_REPO:-storytold/photocraft}"
FALLBACK_VERSION="${PHOTOCRAFT_WEB_FALLBACK_VERSION:-0.9.0}"
FALLBACK_ASSET_URL="https://github.com/storytold/photocraft/releases/download/v${FALLBACK_VERSION}/photocraft-web-${FALLBACK_VERSION}.zip"

tmpdir() {
  local base="${TMPDIR:-${TEMP:-}}"
  if [ -n "$base" ]; then
    mkdir -p "$base"
    mktemp -d "${base%/}/commmaker-pc.XXXXXX"
  else
    mktemp -d
  fi
}

curl_to_file() {
  local url="$1" out="$2"
  curl -fsSL --retry 2 --retry-delay 1 -o "$out" "$url"
}

resolve_latest() {
  local repo="$1"
  local url="https://api.github.com/repos/${repo}/releases/latest"
  local body_file tag
  body_file="$(mktemp)"
  if ! curl_to_file "$url" "$body_file"; then
    rm -f "$body_file"
    return 1
  fi
  tag="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('tag_name',''))" "$body_file" 2>/dev/null || true)"
  rm -f "$body_file"
  if [ -z "$tag" ]; then
    return 1
  fi
  tag="${tag#v}"
  echo "$tag"
}

pick_asset_url() {
  local repo="$1" ver="$2"
  local body_file url
  body_file="$(mktemp)"
  if ! curl_to_file "https://api.github.com/repos/${repo}/releases/tags/v${ver}" "$body_file"; then
    rm -f "$body_file"
    return 0
  fi
  url="$(python3 -c "
import json, sys
try:
    with open(sys.argv[1], encoding='utf-8') as f:
        data = json.load(f)
except (json.JSONDecodeError, OSError):
    raise SystemExit(0)
for a in data.get('assets', []):
    n = a.get('name', '')
    if n.startswith('photocraft-web-') and n.endswith('.zip'):
        print(a['browser_download_url'])
        break
" "$body_file" 2>/dev/null || true)"
  rm -f "$body_file"
  if [ -n "$url" ]; then
    echo "$url"
  fi
}

SOURCE_REPO=""

if [ -z "$VERSION" ]; then
  VERSION="$(resolve_latest "$FORK_REPO")" || VERSION="$(resolve_latest "$UPSTREAM_REPO")" || VERSION="$FALLBACK_VERSION"
fi

ASSET_URL="$(pick_asset_url "$FORK_REPO" "$VERSION")"
if [ -n "$ASSET_URL" ]; then
  SOURCE_REPO="$FORK_REPO"
fi
if [ -z "$ASSET_URL" ]; then
  ASSET_URL="$(pick_asset_url "$UPSTREAM_REPO" "$VERSION")"
  if [ -n "$ASSET_URL" ]; then
    SOURCE_REPO="$UPSTREAM_REPO"
  fi
fi
if [ -z "$ASSET_URL" ]; then
  if [ "$VERSION" = "$FALLBACK_VERSION" ]; then
    ASSET_URL="$FALLBACK_ASSET_URL"
    SOURCE_REPO="$UPSTREAM_REPO"
    echo "note: using upstream fallback release zip (v${FALLBACK_VERSION})" >&2
  else
    echo "error: no photocraft-web zip for version ${VERSION}" >&2
    exit 1
  fi
fi

TMP="$(tmpdir)"
ZIP="$TMP/photocraft-web.zip"
STAGE="$TMP/stage"
echo "Fetching photocraft-web ${VERSION} ..."
curl_to_file "$ASSET_URL" "$ZIP"

mkdir -p "$STAGE"
unzip -q "$ZIP" -d "$TMP/extract"
INNER="$(find "$TMP/extract" -mindepth 1 -maxdepth 1 -type d | head -1)"
if [ -z "$INNER" ]; then
  echo "error: unexpected zip layout" >&2
  exit 1
fi
cp -R "$INNER/." "$STAGE/"

if [ ! -f "$STAGE/index.html" ]; then
  echo "error: index.html missing after extract" >&2
  exit 1
fi

mkdir -p "$(dirname "$DEST")"
rm -rf "$DEST"
mv "$STAGE" "$DEST"
rm -rf "$TMP"

if [ -n "$SOURCE_REPO" ]; then
  BUILT_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || python3 -c "from datetime import datetime,timezone; print(datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))")"
  printf '%s\n' "{\"repo\":\"${SOURCE_REPO}\",\"ref\":\"v${VERSION}\",\"method\":\"release\",\"builtAt\":\"${BUILT_AT}\"}" >"$DEST/.commmaker-source.json"
fi

echo "Installed to $DEST (version ${VERSION})"
echo "OK: $DEST/index.html"
