"""Locate or download photocraft-cli and run command batches via ``serve``."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from typing import Any

PHOTOCRAFT_VERSION = "0.9.0"
PHOTOCRAFT_RELEASE_TAG = f"v{PHOTOCRAFT_VERSION}"
PHOTOCRAFT_TARBALL = {
    "x86_64": f"photocraft-{PHOTOCRAFT_VERSION}-linux-x86_64.tar.gz",
    "aarch64": f"photocraft-{PHOTOCRAFT_VERSION}-linux-aarch64.tar.gz",
    "arm64": f"photocraft-{PHOTOCRAFT_VERSION}-linux-aarch64.tar.gz",
}
DOWNLOAD_BASE = (
    f"https://github.com/storytold/photocraft/releases/download/{PHOTOCRAFT_RELEASE_TAG}"
)


def _machine() -> str:
    return platform.machine().lower()


def vendor_cli_path(repo_root: str) -> str:
    machine = _machine()
    name = "photocraft-cli"
    if os.name == "nt":
        return os.path.join(repo_root, "vendor", "photocraft-cli", f"{name}.exe")
    return os.path.join(
        repo_root,
        "vendor",
        "photocraft-cli",
        f"photocraft-{PHOTOCRAFT_VERSION}-linux-{machine}",
        "bin",
        name,
    )


def find_cli(repo_root: str) -> str | None:
    for candidate in (
        shutil.which("photocraft-cli"),
        vendor_cli_path(repo_root),
    ):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def ensure_linux_cli(repo_root: str) -> str | None:
    existing = find_cli(repo_root)
    if existing:
        return existing
    if os.name != "posix" or platform.system() != "Linux":
        return None

    machine = _machine()
    tarball = PHOTOCRAFT_TARBALL.get(machine)
    if not tarball:
        return None

    dest_root = os.path.join(repo_root, "vendor", "photocraft-cli")
    cli = vendor_cli_path(repo_root)
    if os.path.isfile(cli):
        return cli

    os.makedirs(dest_root, exist_ok=True)
    url = f"{DOWNLOAD_BASE}/{tarball}"
    with tempfile.TemporaryDirectory() as tmp:
        archive_path = os.path.join(tmp, tarball)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "CommMaker-PhotoCraft-CLI/0.1 (+https://github.com/asseukihuh/AI-WebApp)",
                "Accept": "application/octet-stream",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        with open(archive_path, "wb") as handle:
            handle.write(data)
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(path=dest_root)

    if os.path.isfile(cli):
        os.chmod(cli, 0o755)
        return cli
    return None


def run_poster_batch(
    repo_root: str,
    batch: dict[str, Any],
    *,
    cli_path: str | None = None,
) -> dict[str, Any]:
    """Execute batch via photocraft-cli serve; returns status dict."""
    out_rel = batch["output"]["relativePath"].replace("\\", "/")
    out_abs = os.path.join(repo_root, out_rel)
    os.makedirs(os.path.dirname(out_abs), exist_ok=True)

    cli = cli_path or find_cli(repo_root)
    if not cli:
        try:
            cli = ensure_linux_cli(repo_root)
        except Exception as exc:  # noqa: BLE001 — surface download errors
            return {
                "ok": False,
                "cliAvailable": False,
                "error": (
                    f"photocraft-cli not found and download failed: {exc}. "
                    f"Install from storytold/photocraft release {PHOTOCRAFT_RELEASE_TAG} "
                    "or add photocraft-cli to PATH."
                ),
                "commandBatch": batch,
                "documentPath": f"/{out_rel}",
                "openUrl": f"/{out_rel}",
            }

    if not cli:
        return {
            "ok": False,
            "cliAvailable": False,
            "error": (
                "photocraft-cli not found in PATH and automatic Linux download failed "
                f"(expected release {PHOTOCRAFT_RELEASE_TAG} tarball from storytold/photocraft)."
            ),
            "commandBatch": batch,
            "documentPath": f"/{out_rel}",
            "openUrl": f"/{out_rel}",
        }

    lines = [
        {
            "id": 1,
            "method": "doc.new",
            "params": batch["document"],
        },
        {
            "id": 2,
            "method": "batch",
            "params": {
                "steps": batch["steps"],
                "stopOnError": batch.get("stop_on_error", True),
            },
        },
    ]
    place_id = 3
    for placement in batch.get("placements") or []:
        lines.append(
            {
                "id": place_id,
                "method": "doc.place",
                "params": placement,
            }
        )
        place_id += 1
    lines.append(
        {
            "id": place_id,
            "method": "doc.save",
            "params": {"path": out_rel},
        }
    )

    payload = "\n".join(json.dumps(line, separators=(",", ":")) for line in lines) + "\n"
    proc = subprocess.run(
        [
            cli,
            "serve",
            "--automation-read-root",
            repo_root,
            "--automation-write-root",
            repo_root,
        ],
        input=payload,
        capture_output=True,
        text=True,
        timeout=120,
        cwd=repo_root,
    )

    replies: list[dict[str, Any]] = []
    for raw in proc.stdout.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            replies.append(json.loads(raw))
        except json.JSONDecodeError:
            replies.append({"ok": False, "parseError": raw})

    save_reply = next((r for r in reversed(replies) if r.get("id") == place_id), None)
    ok = proc.returncode == 0 and save_reply and save_reply.get("ok")

    result: dict[str, Any] = {
        "ok": bool(ok),
        "cliAvailable": True,
        "cliPath": cli,
        "commandBatch": batch,
        "documentPath": f"/{out_rel}",
        "openUrl": f"/{out_rel}",
        "serveExitCode": proc.returncode,
        "serveReplies": replies,
    }
    if not ok:
        result["error"] = (
            proc.stderr.strip()
            or (save_reply or {}).get("error")
            or "PhotoCraft CLI did not save the document"
        )
    return result
