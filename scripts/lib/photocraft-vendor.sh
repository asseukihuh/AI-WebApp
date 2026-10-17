#!/usr/bin/env bash
# Shared helpers for vendoring PhotoCraft web assets into AI-WebApp.
set -euo pipefail

PHOTOCRAFT_FORK_REPO="${PHOTOCRAFT_FORK_REPO:-asseukihuh/photocraft}"
PHOTOCRAFT_UPSTREAM_REPO="${PHOTOCRAFT_UPSTREAM_REPO:-storytold/photocraft}"

photocraft_vendor_root() {
  cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd
}

photocraft_vendor_dest() {
  echo "$(photocraft_vendor_root)/vendor/photocraft-web"
}

write_commmaker_source_json() {
  local dest="$1" repo="$2" ref="$3" method="${4:-release}"
  local built_at
  built_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  python3 -c "
import json, pathlib
path = pathlib.Path('${dest}') / '.commmaker-source.json'
path.write_text(json.dumps({
    'repo': '${repo}',
    'ref': '${ref}',
    'method': '${method}',
    'builtAt': '${built_at}',
}, indent=2) + '\n', encoding='utf-8')
"
}

resolve_latest_release_tag() {
  local repo="$1"
  local url="https://api.github.com/repos/${repo}/releases/latest"
  local tag
  tag="$(curl -fsSL "$url" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('tag_name',''))" 2>/dev/null || true)"
  if [ -z "$tag" ]; then
    return 1
  fi
  tag="${tag#v}"
  echo "$tag"
}

pick_asset_url_for_version() {
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

install_photocraft_zip_to_dest() {
  local asset_url="$1" dest="$2"
  local tmp zip inner
  tmp="$(mktemp -d)"
  zip="$tmp/photocraft-web.zip"
  curl -fsSL -o "$zip" "$asset_url"
  rm -rf "${dest:?}"/*
  mkdir -p "$dest"
  unzip -q "$zip" -d "$tmp/extract"
  inner="$(find "$tmp/extract" -mindepth 1 -maxdepth 1 -type d | head -1)"
  if [ -z "$inner" ]; then
    echo "error: unexpected zip layout" >&2
    rm -rf "$tmp"
    return 1
  fi
  cp -R "$inner/." "$dest/"
  rm -rf "$tmp"
  if [ ! -f "$dest/index.html" ]; then
    echo "error: index.html missing after extract" >&2
    return 1
  fi
}

copy_photocraft_build_dir_to_dest() {
  local src_dir="$1" dest="$2"
  rm -rf "${dest:?}"/*
  mkdir -p "$dest"
  cp -R "$src_dir/." "$dest/"
  if [ ! -f "$dest/index.html" ]; then
    echo "error: index.html missing in build output ($src_dir)" >&2
    return 1
  fi
}
