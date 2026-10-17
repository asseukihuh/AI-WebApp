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
import mimetypes
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("text/javascript", ".js")


class CommMakerHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, coop_coep: bool = False, **kwargs):
        self.coop_coep = coop_coep
        super().__init__(*args, directory=ROOT, **kwargs)

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
        httpd.serve_forever()


if __name__ == "__main__":
    main()
