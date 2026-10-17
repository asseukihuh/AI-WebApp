"""Locate or download photocraft-cli and run command batches via ``serve``."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from typing import Any

PHOTOCRAFT_VERSION = "0.9.0"
PHOTOCRAFT_RELEASE_TAG = f"v{PHOTOCRAFT_VERSION}"
DOWNLOAD_BASE = (
    f"https://github.com/storytold/photocraft/releases/download/{PHOTOCRAFT_RELEASE_TAG}"
)

PHOTOCRAFT_TARBALL = {
    "x86_64": f"photocraft-{PHOTOCRAFT_VERSION}-linux-x86_64.tar.gz",
    "amd64": f"photocraft-{PHOTOCRAFT_VERSION}-linux-x86_64.tar.gz",
    "aarch64": f"photocraft-{PHOTOCRAFT_VERSION}-linux-aarch64.tar.gz",
    "arm64": f"photocraft-{PHOTOCRAFT_VERSION}-linux-aarch64.tar.gz",
}

MACOS_CLI_ZIP = f"photocraft-cli-{PHOTOCRAFT_VERSION}-macos-universal.zip"
MACOS_CLI_DIR = f"photocraft-cli-{PHOTOCRAFT_VERSION}-macos-universal"

WINDOWS_PORTABLE = {
    "amd64": f"photocraft-{PHOTOCRAFT_VERSION}-windows-x64-portable.zip",
    "x86_64": f"photocraft-{PHOTOCRAFT_VERSION}-windows-x64-portable.zip",
    "arm64": f"photocraft-{PHOTOCRAFT_VERSION}-windows-arm64-portable.zip",
    "aarch64": f"photocraft-{PHOTOCRAFT_VERSION}-windows-arm64-portable.zip",
}

WINDOWS_PORTABLE_DIR = {
    "amd64": f"photocraft-{PHOTOCRAFT_VERSION}-windows-x64-portable",
    "x86_64": f"photocraft-{PHOTOCRAFT_VERSION}-windows-x64-portable",
    "arm64": f"photocraft-{PHOTOCRAFT_VERSION}-windows-arm64-portable",
    "aarch64": f"photocraft-{PHOTOCRAFT_VERSION}-windows-arm64-portable",
}

USER_AGENT = (
    "CommMaker-PhotoCraft-CLI/0.2 (+https://github.com/asseukihuh/AI-WebApp)"
)


def _machine() -> str:
    return platform.machine().lower()


def _linux_archive_machine() -> str:
    machine = _machine()
    if machine in ("arm64", "aarch64"):
        return "aarch64"
    if machine in ("amd64", "x86_64"):
        return "x86_64"
    return machine


def _download(url: str, dest_path: str) -> None:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/octet-stream",
        },
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = resp.read()
    with open(dest_path, "wb") as handle:
        handle.write(data)


def vendor_cli_path(repo_root: str) -> str:
    system = platform.system()
    if os.name == "nt" or system == "Windows":
        machine = _machine()
        folder = WINDOWS_PORTABLE_DIR.get(machine, WINDOWS_PORTABLE_DIR["amd64"])
        return os.path.join(
            repo_root,
            "vendor",
            "photocraft-cli",
            folder,
            "photocraft-cli.exe",
        )
    if system == "Darwin":
        return os.path.join(
            repo_root,
            "vendor",
            "photocraft-cli",
            MACOS_CLI_DIR,
            "photocraft-cli",
        )
    machine = _linux_archive_machine()
    return os.path.join(
        repo_root,
        "vendor",
        "photocraft-cli",
        f"photocraft-{PHOTOCRAFT_VERSION}-linux-{machine}",
        "bin",
        "photocraft-cli",
    )


def find_cli(repo_root: str) -> str | None:
    for candidate in (
        shutil.which("photocraft-cli"),
        vendor_cli_path(repo_root),
    ):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _cli_missing_user_message(repo_root: str) -> str:
    system = platform.system()
    if system == "Darwin":
        return (
            "PhotoCraft CLI was not found. On first poster generation CommMaker downloads "
            f"{MACOS_CLI_ZIP} from storytold/photocraft {PHOTOCRAFT_RELEASE_TAG} into "
            f"{os.path.join(repo_root, 'vendor', 'photocraft-cli')}. "
            "If download failed, extract the zip manually or install photocraft-cli on PATH."
        )
    if os.name == "nt" or system == "Windows":
        return (
            "PhotoCraft CLI was not found. CommMaker can download the Windows portable zip "
            f"from storytold/photocraft {PHOTOCRAFT_RELEASE_TAG}, or add photocraft-cli.exe to PATH."
        )
    return (
        "PhotoCraft CLI was not found. On Linux, CommMaker downloads the release tarball on first "
        f"use ({PHOTOCRAFT_RELEASE_TAG}), or add photocraft-cli to PATH."
    )


def ensure_linux_cli(repo_root: str) -> str | None:
    """Backward-compatible alias for :func:`ensure_cli` on Linux only."""
    if platform.system() != "Linux":
        return None
    return ensure_cli(repo_root)


def ensure_cli(repo_root: str) -> str | None:
    existing = find_cli(repo_root)
    if existing:
        return existing

    system = platform.system()
    dest_root = os.path.join(repo_root, "vendor", "photocraft-cli")
    cli = vendor_cli_path(repo_root)
    if os.path.isfile(cli):
        if os.name != "nt":
            os.chmod(cli, 0o755)
        return cli

    os.makedirs(dest_root, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        if system == "Linux":
            machine = _linux_archive_machine()
            tarball = PHOTOCRAFT_TARBALL.get(machine) or PHOTOCRAFT_TARBALL.get(_machine())
            if not tarball:
                return None
            archive_path = os.path.join(tmp, tarball)
            _download(f"{DOWNLOAD_BASE}/{tarball}", archive_path)
            with tarfile.open(archive_path, "r:gz") as tar:
                tar.extractall(path=dest_root)
        elif system == "Darwin":
            archive_path = os.path.join(tmp, MACOS_CLI_ZIP)
            _download(f"{DOWNLOAD_BASE}/{MACOS_CLI_ZIP}", archive_path)
            with zipfile.ZipFile(archive_path) as zf:
                zf.extractall(path=dest_root)
        elif os.name == "nt" or system == "Windows":
            machine = _machine()
            zip_name = WINDOWS_PORTABLE.get(machine) or WINDOWS_PORTABLE["amd64"]
            archive_path = os.path.join(tmp, zip_name)
            _download(f"{DOWNLOAD_BASE}/{zip_name}", archive_path)
            with zipfile.ZipFile(archive_path) as zf:
                zf.extractall(path=dest_root)
        else:
            return None

    if os.path.isfile(cli):
        if os.name != "nt":
            os.chmod(cli, 0o755)
        return cli
    return None


def cli_self_test(repo_root: str) -> dict[str, Any]:
    """Verify photocraft-cli responds to a minimal serve session (for smoke tests)."""
    cli = ensure_cli(repo_root)
    if not cli:
        return {
            "ok": False,
            "platform": platform.system(),
            "machine": _machine(),
            "error": "CLI not available",
            "userMessage": _cli_missing_user_message(repo_root),
        }
    proc = subprocess.run(
        [cli, "--version"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    version_ok = proc.returncode == 0
    return {
        "ok": version_ok,
        "cliPath": cli,
        "platform": platform.system(),
        "machine": _machine(),
        "versionStdout": (proc.stdout or "").strip(),
        "versionStderr": (proc.stderr or "").strip(),
        "exitCode": proc.returncode,
    }


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
    download_error: str | None = None
    if not cli:
        try:
            cli = ensure_cli(repo_root)
        except Exception as exc:  # noqa: BLE001 — surface download errors
            download_error = str(exc)

    if not cli:
        base_error = download_error or (
            f"photocraft-cli not found (expected storytold/photocraft {PHOTOCRAFT_RELEASE_TAG})."
        )
        return {
            "ok": False,
            "cliAvailable": False,
            "error": base_error,
            "cliError": base_error,
            "userMessage": _cli_missing_user_message(repo_root),
            "commandBatch": batch,
            "documentPath": f"/{out_rel}",
            "openUrl": f"/{out_rel}",
        }

    placement_errors: list[dict[str, Any]] = []

    def _check_placement_path(placement: dict[str, Any], role: str) -> None:
        rel = str(placement.get("path") or "").replace("\\", "/")
        if not rel:
            placement_errors.append(
                {"role": role, "path": rel, "error": "Missing placement path"}
            )
            return
        abs_path = os.path.join(repo_root, rel)
        if not os.path.isfile(abs_path):
            placement_errors.append(
                {
                    "role": role,
                    "path": rel,
                    "error": f"Asset not found on disk: {rel}",
                }
            )

    lines = [
        {
            "id": 1,
            "method": "doc.new",
            "params": batch["document"],
        },
    ]
    place_id = 2
    for placement in batch.get("backgroundPlacements") or []:
        _check_placement_path(placement, "background")
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
            "method": "batch",
            "params": {
                "steps": batch["steps"],
                "stopOnError": batch.get("stop_on_error", True),
            },
        }
    )
    place_id += 1
    for placement in batch.get("placements") or []:
        _check_placement_path(placement, "foreground")
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

    place_reply_ids = {
        line["id"]
        for line in lines
        if line.get("method") == "doc.place"
    }
    for reply in replies:
        if reply.get("id") in place_reply_ids and not reply.get("ok"):
            placement_errors.append(
                {
                    "id": reply.get("id"),
                    "error": reply.get("error") or reply.get("parseError") or "doc.place failed",
                    "reply": reply,
                }
            )

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
        "placementErrors": placement_errors,
    }
    if ok:
        result["userMessage"] = "Poster saved successfully."
    else:
        err = (
            proc.stderr.strip()
            or (save_reply or {}).get("error")
            or "PhotoCraft CLI did not save the document"
        )
        result["error"] = err
        result["cliError"] = err
        result["userMessage"] = (
            "PhotoCraft CLI ran but could not save your poster. "
            "See cliError in this response or server logs for details."
        )
    return result


def main() -> None:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        report = cli_self_test(repo_root)
        print(json.dumps(report, indent=2))
        sys.exit(0 if report.get("ok") else 1)
    print("Usage: python3 scripts/photocraft_cli.py --self-test", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
