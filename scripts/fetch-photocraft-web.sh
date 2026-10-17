#!/usr/bin/env bash
# Download photocraft-web-<version>.zip into vendor/photocraft-web/ (fork-first).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/photocraft-vendor.sh
source "$ROOT/scripts/lib/photocraft-vendor.sh"

DEST="$(photocraft_vendor_dest)"
VERSION="${PHOTOCRAFT_WEB_VERSION:-}"
FORK_REPO="$PHOTOCRAFT_FORK_REPO"

if [ -z "$VERSION" ]; then
  VERSION="$(resolve_latest_release_tag "$FORK_REPO" 2>/dev/null || true)"
fi
if [ -z "$VERSION" ]; then
  VERSION="$(resolve_latest_release_tag "$PHOTOCRAFT_UPSTREAM_REPO")" || {
    echo "error: could not resolve latest photocraft-web release" >&2
    exit 1
  }
fi

ASSET_URL=""
SOURCE_REPO=""
ASSET_URL="$(pick_asset_url_for_version "$FORK_REPO" "$VERSION")"
if [ -n "$ASSET_URL" ]; then
  SOURCE_REPO="$FORK_REPO"
else
  ASSET_URL="$(pick_asset_url_for_version "$PHOTOCRAFT_UPSTREAM_REPO" "$VERSION")"
  if [ -n "$ASSET_URL" ]; then
    SOURCE_REPO="$PHOTOCRAFT_UPSTREAM_REPO"
    echo "note: no photocraft-web zip on ${FORK_REPO} for v${VERSION}; using upstream ${PHOTOCRAFT_UPSTREAM_REPO}" >&2
  fi
fi

if [ -z "$ASSET_URL" ]; then
  echo "error: no photocraft-web zip for version ${VERSION}" >&2
  exit 1
fi

echo "Fetching photocraft-web ${VERSION} from ${SOURCE_REPO} ..."
install_photocraft_zip_to_dest "$ASSET_URL" "$DEST"
write_commmaker_source_json "$DEST" "$SOURCE_REPO" "v${VERSION}" "release"

echo "Installed to $DEST (version ${VERSION})"
echo "Source: ${SOURCE_REPO} @ v${VERSION} (release zip)"
if [ -f "$DEST/index.html" ]; then
  echo "OK: $DEST/index.html"
else
  echo "error: index.html missing after extract" >&2
  exit 1
fi
