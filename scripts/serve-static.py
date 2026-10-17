#!/usr/bin/env python3
"""Static file server for AI-WebApp / CommMaker shell.

Serves the repo root with correct application/wasm MIME type.
Optional COOP/COEP headers for pages that need cross-origin isolation
(PhotoCraft itself does not require them; see packaging/web/README.md).
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from kit_scraper import scrape_kit_from_html, validate_fetch_url  # noqa: E402
from poster_compiler import compile_poster_batch, logo_cache_basename  # noqa: E402
from photocraft_cli import run_poster_batch, _cli_missing_user_message  # noqa: E402

MAX_HTML_BYTES = 2_000_000
MAX_POSTER_BODY_BYTES = 256_000
MAX_LOGO_BYTES = 4_000_000
FETCH_TIMEOUT_SEC = 20
GENERATED_DIR = os.path.join(ROOT, "generated")
ASSETS_DIR = os.path.join(GENERATED_DIR, "assets")

mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("text/javascript", ".js")


class CommMakerHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, coop_coep: bool = False, **kwargs):
        self.coop_coep = coop_coep
        super().__init__(*args, directory=ROOT, **kwargs)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/scrape-kit":
            self._handle_scrape_kit()
            return
        if path == "/api/generate-poster":
            self._handle_generate_poster()
            return
        self.send_error(404, "Not found")

    def _read_json_body(self, max_bytes: int = 8192) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > max_bytes:
            raise ValueError("Invalid request body size")
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _fetch_html(self, url: str) -> str:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "CommMaker-KitScraper/0.1 (+https://github.com/asseukihuh/AI-WebApp)",
                "Accept": "text/html,application/xhtml+xml",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SEC) as resp:
            data = resp.read(MAX_HTML_BYTES + 1)
        if len(data) > MAX_HTML_BYTES:
            raise ValueError("Page too large to scrape")
        charset = "utf-8"
        return data.decode(charset, errors="replace")

    def _handle_scrape_kit(self) -> None:
        try:
            body = self._read_json_body()
            url = validate_fetch_url(str(body.get("url", "")))
            html = self._fetch_html(url)
            kit = scrape_kit_from_html(html, url)
            self._send_json(200, {"kit": kit})
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except urllib.error.HTTPError as exc:
            self._send_json(502, {"error": f"Upstream HTTP {exc.code}"})
        except urllib.error.URLError as exc:
            self._send_json(502, {"error": f"Could not fetch URL: {exc.reason}"})
        except json.JSONDecodeError:
            self._send_json(400, {"error": "Invalid JSON body"})
        except Exception as exc:  # noqa: BLE001 — MVP API
            self._send_json(500, {"error": str(exc)})

    def _fetch_binary(self, url: str) -> bytes:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "CommMaker-PosterCompiler/0.1 (+https://github.com/asseukihuh/AI-WebApp)",
                "Accept": "image/*,*/*",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SEC) as resp:
            data = resp.read(MAX_LOGO_BYTES + 1)
        if len(data) > MAX_LOGO_BYTES:
            raise ValueError("Logo image too large")
        return data

    def _maybe_cache_logo(self, kit: dict) -> str | None:
        logo_url = kit.get("logoUrl") if kit else None
        if not logo_url or not isinstance(logo_url, str):
            return None
        try:
            logo_url = validate_fetch_url(logo_url)
        except ValueError:
            return None
        os.makedirs(ASSETS_DIR, exist_ok=True)
        basename = logo_cache_basename(logo_url)
        rel_path = f"generated/assets/{basename}"
        abs_path = os.path.join(ROOT, rel_path)
        if not os.path.isfile(abs_path):
            try:
                data = self._fetch_binary(logo_url)
            except (urllib.error.HTTPError, urllib.error.URLError, ValueError):
                return None
            with open(abs_path, "wb") as handle:
                handle.write(data)
        return rel_path

    def _handle_generate_poster(self) -> None:
        try:
            body = self._read_json_body(MAX_POSTER_BODY_BYTES)
            kit = body.get("kit") or body.get("kitSnapshot")
            session = body.get("session")
            if not session and body.get("brief"):
                session = {"brief": body["brief"]}
            if not session:
                raise ValueError("Request must include session (or brief) JSON")
            if not kit:
                kit = session.get("kitSnapshot")
            logo_rel = self._maybe_cache_logo(kit or {})
            batch = compile_poster_batch(kit, session, logo_relative_path=logo_rel)
            os.makedirs(GENERATED_DIR, exist_ok=True)
            try:
                result = run_poster_batch(ROOT, batch)
            except urllib.error.HTTPError as exc:
                self._send_json(
                    502,
                    {"error": f"PhotoCraft CLI download HTTP {exc.code}"},
                )
                return
            except urllib.error.URLError as exc:
                self._send_json(
                    502,
                    {"error": f"PhotoCraft CLI download failed: {exc.reason}"},
                )
                return
            payload = {
                "ok": result.get("ok", False),
                "commandBatch": result.get("commandBatch"),
                "documentPath": result.get("documentPath"),
                "openUrl": result.get("openUrl"),
                "cliAvailable": result.get("cliAvailable", False),
                "cliPath": result.get("cliPath"),
            }
            if result.get("error"):
                payload["cliError"] = result["error"]
            if result.get("cliError"):
                payload["cliError"] = result["cliError"]
            payload["userMessage"] = result.get("userMessage") or (
                _cli_missing_user_message(ROOT)
                if not result.get("cliAvailable")
                else (result.get("cliError") or "Poster generation failed.")
            )
            self._send_json(200, payload)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except urllib.error.HTTPError as exc:
            self._send_json(502, {"error": f"Logo fetch HTTP {exc.code}"})
        except urllib.error.URLError as exc:
            self._send_json(502, {"error": f"Could not fetch logo: {exc.reason}"})
        except json.JSONDecodeError:
            self._send_json(400, {"error": "Invalid JSON body"})
        except Exception as exc:  # noqa: BLE001 — MVP API
            self._send_json(500, {"error": str(exc)})

    def end_headers(self) -> None:
        if self.coop_coep:
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
            path = self.path.split("?", 1)[0]
            if path.startswith("/vendor/photocraft-web"):
                self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve AI-WebApp static files")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--coop-coep",
        action="store_true",
        help="Send COOP/COEP (and CORP on PhotoCraft assets). Not required for PhotoCraft alone.",
    )
    args = parser.parse_args()

    handler = functools.partial(CommMakerHandler, coop_coep=args.coop_coep)
    with http.server.ThreadingHTTPServer(("", args.port), handler) as httpd:
        print(f"Serving {ROOT} at http://localhost:{args.port}/")
        if args.coop_coep:
            print("COOP/COEP enabled (optional; PhotoCraft does not need SharedArrayBuffer)")
        print("PhotoCraft embed: http://localhost:{}/photocraft/".format(args.port))
        print("Poster API: POST http://localhost:{}/api/generate-poster".format(args.port))
        os.makedirs(GENERATED_DIR, exist_ok=True)
        httpd.serve_forever()


if __name__ == "__main__":
    main()
