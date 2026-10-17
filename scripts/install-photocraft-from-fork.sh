#!/usr/bin/env bash
# Install PhotoCraft web assets from asseukihuh/photocraft (release zip or local build).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/photocraft-vendor.sh
source "$ROOT/scripts/lib/photocraft-vendor.sh"

DEST="$(photocraft_vendor_dest)"
VERSION="${PHOTOCRAFT_WEB_VERSION:-}"
FORK_REPO="$PHOTOCRAFT_FORK_REPO"
FORK_GIT_URL="${PHOTOCRAFT_FORK_GIT_URL:-https://github.com/${FORK_REPO}.git}"

resolve_fork_dir() {
  if [ -n "${PHOTOCRAFT_FORK_DIR:-}" ]; then
    if [ -d "$PHOTOCRAFT_FORK_DIR/.git" ]; then
      echo "$(cd "$PHOTOCRAFT_FORK_DIR" && pwd)"
      return 0
    fi
    echo "error: PHOTOCRAFT_FORK_DIR is set but not a git repo: $PHOTOCRAFT_FORK_DIR" >&2
    exit 1
  fi
  local sibling="$ROOT/../photocraft"
  if [ -d "$sibling/.git" ]; then
    echo "$(cd "$sibling" && pwd)"
    return 0
  fi
  local hidden="$ROOT/.photocraft-fork"
  if [ -d "$hidden/.git" ]; then
    echo "$(cd "$hidden" && pwd)"
    return 0
  fi
  echo "$hidden"
}

clone_fork_if_needed() {
  local dir="$1"
  if [ -d "$dir/.git" ]; then
    return 0
  fi
  echo "Cloning ${FORK_REPO} into $(basename "$dir") ..."
  if ! git clone "$FORK_GIT_URL" "$dir" 2>/dev/null; then
    echo "warning: could not clone ${FORK_REPO} (private repo or network). Continuing with GitHub releases only." >&2
    return 1
  fi
  return 0
}

fork_git_ref() {
  local dir="$1"
  if [ ! -d "$dir/.git" ]; then
    echo "unknown"
    return 0
  fi
  git -C "$dir" rev-parse --short HEAD 2>/dev/null || echo "unknown"
}

try_release_install() {
  local ver="$1"
  local asset_url="" source_repo=""
  asset_url="$(pick_asset_url_for_version "$FORK_REPO" "$ver")"
  if [ -n "$asset_url" ]; then
    source_repo="$FORK_REPO"
  else
    asset_url="$(pick_asset_url_for_version "$PHOTOCRAFT_UPSTREAM_REPO" "$ver")"
    if [ -n "$asset_url" ]; then
      source_repo="$PHOTOCRAFT_UPSTREAM_REPO"
    fi
  fi
  if [ -z "$asset_url" ]; then
    return 1
  fi
  echo "Installing photocraft-web ${ver} from GitHub release (${source_repo}) ..."
  install_photocraft_zip_to_dest "$asset_url" "$DEST"
  write_commmaker_source_json "$DEST" "$source_repo" "v${ver}" "release"
  echo "Installed to $DEST"
  echo "Source: ${source_repo} @ v${ver} (release zip)"
  return 0
}

build_from_fork() {
  local fork_dir="$1"
  local ref
  ref="$(fork_git_ref "$fork_dir")"
  echo "Building web package from fork at ${fork_dir} (ref ${ref}) ..."
  echo "Prerequisites: Rust 1.95+, wasm32-unknown-unknown, Trunk (cargo install trunk --locked)"
  if [ ! -x "$fork_dir/packaging/web/package.sh" ]; then
    echo "error: packaging/web/package.sh not found in fork" >&2
    exit 1
  fi
  (cd "$fork_dir" && ./packaging/web/package.sh)
  local pkg_dir
  pkg_dir="$(find "$fork_dir" -path '*/web-package/photocraft-web-*' -type d 2>/dev/null | head -1)"
  if [ -z "$pkg_dir" ]; then
    pkg_dir="$(find "$fork_dir/target" -path '*/web-package/photocraft-web-*' -type d 2>/dev/null | head -1)"
  fi
  if [ -z "$pkg_dir" ]; then
    echo "error: could not find web-package/photocraft-web-* after build" >&2
    exit 1
  fi
  copy_photocraft_build_dir_to_dest "$pkg_dir" "$DEST"
  write_commmaker_source_json "$DEST" "$FORK_REPO" "$ref" "source-build"
  echo "Installed to $DEST"
  echo "Source: ${FORK_REPO} @ ${ref} (built from source)"
}

main() {
  mkdir -p "$DEST"
  local fork_path
  fork_path="$(resolve_fork_dir)"
  local have_fork=0
  if clone_fork_if_needed "$fork_path"; then
    have_fork=1
  fi

  if [ -z "$VERSION" ]; then
    VERSION="$(resolve_latest_release_tag "$FORK_REPO" 2>/dev/null || true)"
  fi
  if [ -n "$VERSION" ] && try_release_install "$VERSION"; then
    exit 0
  fi

  if [ "$have_fork" -eq 1 ]; then
    build_from_fork "$fork_path"
    exit 0
  fi

  if [ -z "$VERSION" ]; then
    VERSION="$(resolve_latest_release_tag "$PHOTOCRAFT_UPSTREAM_REPO" 2>/dev/null || true)"
  fi
  if [ -n "$VERSION" ] && try_release_install "$VERSION"; then
    exit 0
  fi

  echo "error: no photocraft-web release found and fork clone/build unavailable." >&2
  echo "Set PHOTOCRAFT_FORK_DIR to a local clone of ${FORK_REPO}, or publish a release zip on the fork." >&2
  exit 1
}

main "$@"
