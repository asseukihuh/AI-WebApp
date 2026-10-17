#!/usr/bin/env python3
"""Static file server for AI-WebApp / CommMaker shell.

Serves the repo root with correct application/wasm MIME type.
Optional COOP/COEP headers for pages that need cross-origin isolation
(PhotoCraft itself does not require them; see packaging/web/README.md).
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
from typing import Callable

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from kit_scraper import (  # noqa: E402
    MAX_STYLESHEET_BYTES,
    scrape_kit_from_page,
    validate_fetch_url,
)
from image_probe import image_dimensions, raster_dimensions, svg_dimensions_from_text  # noqa: E402
from font_fetcher import resolve_poster_fonts  # noqa: E402
from creative_brief import build_creative_brief, effective_ideogram_layers  # noqa: E402
from ideogram_client import generate_layer_image, ideogram_api_key  # noqa: E402
from poster_compiler import (  # noqa: E402
    compile_poster_batch,
    hero_cache_basename,
    logo_cache_basename,
    logo_svg_dimensions_oversized,
    should_recolor_logo_light,
    should_skip_hero_for_brief,
)
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
        if path == "/api/creative-brief":
            self._handle_creative_brief()
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

            def _css_fetcher(css_url: str) -> bytes:
                req = urllib.request.Request(
                    css_url,
                    headers={
                        "User-Agent": "CommMaker-KitScraper/0.2 (+https://github.com/asseukihuh/AI-WebApp)",
                        "Accept": "text/css,*/*",
                    },
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SEC) as resp:
                    data = resp.read(MAX_STYLESHEET_BYTES + 1)
                if len(data) > MAX_STYLESHEET_BYTES:
                    data = data[:MAX_STYLESHEET_BYTES]
                return data

            kit = scrape_kit_from_page(html, url, fetcher=_css_fetcher)
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

    def _write_cached_asset(self, basename: str, data: bytes) -> str:
        os.makedirs(ASSETS_DIR, exist_ok=True)
        rel_path = f"generated/assets/{basename}"
        abs_path = os.path.join(ROOT, rel_path)
        if not os.path.isfile(abs_path):
            with open(abs_path, "wb") as handle:
                handle.write(data)
        return rel_path

    def _maybe_cache_remote_asset(
        self,
        url: str | None,
        basename_fn: Callable[[str], str],
        errors: list[dict[str, str]] | None = None,
        role: str = "asset",
    ) -> str | None:
        if not url or not isinstance(url, str):
            return None
        try:
            url = validate_fetch_url(url)
        except ValueError as exc:
            if errors is not None:
                errors.append({"role": role, "url": url, "error": str(exc)})
            return None
        basename = basename_fn(url)
        rel_path = f"generated/assets/{basename}"
        abs_path = os.path.join(ROOT, rel_path)
        if not os.path.isfile(abs_path):
            try:
                data = self._fetch_binary(url)
            except urllib.error.HTTPError as exc:
                if errors is not None:
                    errors.append(
                        {
                            "role": role,
                            "url": url,
                            "error": f"HTTP {exc.code}",
                        }
                    )
                return None
            except urllib.error.URLError as exc:
                if errors is not None:
                    errors.append(
                        {
                            "role": role,
                            "url": url,
                            "error": f"Fetch failed: {exc.reason}",
                        }
                    )
                return None
            except ValueError as exc:
                if errors is not None:
                    errors.append({"role": role, "url": url, "error": str(exc)})
                return None
            self._write_cached_asset(basename, data)
        return rel_path

    def _maybe_cache_logo(
        self,
        kit: dict,
        errors: list[dict[str, str]] | None = None,
        *,
        recolor_light_mark: bool = False,
    ) -> str | None:
        if not kit:
            return None
        logo_svg = kit.get("logoSvg")
        if isinstance(logo_svg, str) and logo_svg.strip().startswith("<svg"):
            from poster_compiler import recolor_logo_svg_for_light_hero

            payload = logo_svg.strip()
            dims = svg_dimensions_from_text(payload)
            if dims and logo_svg_dimensions_oversized(dims[0], dims[1]):
                fallback = self._maybe_cache_remote_asset(
                    kit.get("logoUrl"), logo_cache_basename, errors, role="logo"
                )
                if fallback:
                    return fallback
                return self._maybe_cache_remote_asset(
                    kit.get("faviconUrl"), logo_cache_basename, errors, role="logo"
                )
            if recolor_light_mark:
                payload = recolor_logo_svg_for_light_hero(payload)
            digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
            return self._write_cached_asset(
                f"logo-{digest}.svg", payload.encode("utf-8")
            )
        return self._maybe_cache_remote_asset(
            kit.get("logoUrl"), logo_cache_basename, errors, role="logo"
        )

    def _maybe_cache_hero(
        self, kit: dict, errors: list[dict[str, str]] | None = None
    ) -> str | None:
        if kit and (kit.get("heroBusy") or kit.get("heroBrandMark")):
            return None
        return self._maybe_cache_remote_asset(
            kit.get("heroImageUrl") if kit else None,
            hero_cache_basename,
            errors,
            role="hero",
        )

    def _handle_creative_brief(self) -> None:
        try:
            body = self._read_json_body(MAX_POSTER_BODY_BYTES)
            kit = body.get("kit") or {}
            crisis_message = str(body.get("crisisMessage") or "").strip()
            crisis_facts = body.get("crisisFacts")
            crisis: dict = {
                "crisisMessage": crisis_message,
                "crisisFacts": crisis_facts if crisis_facts is not None else "",
                "tone": body.get("tone"),
            }
            if body.get("brief") and isinstance(body["brief"], dict):
                brief_form = body["brief"]
                crisis.setdefault("crisisFacts", brief_form.get("facts") or "")
                crisis.setdefault("tone", brief_form.get("tone"))
            fmt = str(body.get("format") or "linkedin-1200x627")
            result = build_creative_brief(kit, crisis, fmt)
            payload = {
                "brief": result["brief"],
                "source": result["source"],
            }
            if result.get("model"):
                payload["model"] = result["model"]
            if result.get("provider"):
                payload["provider"] = result["provider"]
            self._send_json(200, payload)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except json.JSONDecodeError:
            self._send_json(400, {"error": "Invalid JSON body"})
        except Exception as exc:  # noqa: BLE001 — MVP API
            self._send_json(500, {"error": str(exc)})

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
            kit = dict(kit or {})
            if isinstance(kit.get("logoSvg"), str) and kit["logoSvg"].strip().startswith(
                "<svg"
            ):
                kit.pop("logoUrl", None)
            creative_brief = body.get("creativeBrief")
            asset_errors: list[dict[str, str]] = []
            hero_busy = bool(kit.get("heroBusy"))
            hero_brand_mark = bool(kit.get("heroBrandMark"))
            hero_rel = None
            accent_rel = None
            hero_meta: dict = {}
            generated_assets: list[dict[str, str]] = []
            ideogram_fallback_message: str | None = None
            if (
                isinstance(creative_brief, dict)
                and creative_brief.get("heroStrategy") == "ideogram_generate"
            ):
                prompt = str(creative_brief.get("heroImagePrompt") or "").strip()
                layers_mode = effective_ideogram_layers(creative_brief)
                accent_prompt = str(creative_brief.get("accentImagePrompt") or "").strip()
                if ideogram_api_key() and prompt:
                    try:
                        hero_rel, _bytes, bg_meta = generate_layer_image(
                            prompt,
                            "background",
                            "1200x627",
                            assets_dir=ASSETS_DIR,
                        )
                        generated_assets.append(
                            {
                                "role": "background",
                                "path": hero_rel,
                                "source": "ideogram-4",
                            }
                        )
                        hero_meta = {
                            "heroSource": "ideogram-4",
                            "heroImagePrompt": prompt,
                            "ideogramResolution": bg_meta.get("ideogramResolution"),
                            "ideogramLayers": layers_mode,
                        }
                        if bg_meta.get("resolutionNote"):
                            hero_meta["resolutionNote"] = (
                                f"{bg_meta['resolutionNote']} "
                                "Poster compiler cover-fills 1200×627."
                            )
                        kit["heroImageUrl"] = f"/{hero_rel}"
                        if (
                            layers_mode == "background-plus-accent"
                            and accent_prompt
                        ):
                            accent_rel, _accent_bytes, accent_meta = generate_layer_image(
                                accent_prompt,
                                "accent",
                                "1024x1024",
                                assets_dir=ASSETS_DIR,
                                remove_bg=True,
                            )
                            generated_assets.append(
                                {
                                    "role": "accent",
                                    "path": accent_rel,
                                    "source": accent_meta.get("source", "ideogram-4"),
                                }
                            )
                    except (
                        urllib.error.URLError,
                        urllib.error.HTTPError,
                        ValueError,
                        json.JSONDecodeError,
                        OSError,
                    ) as exc:
                        ideogram_fallback_message = (
                            f"Ideogram hero unavailable ({exc}); using kit gradient/photo fallback."
                        )
                        asset_errors.append(
                            {"role": "ideogram", "error": str(exc), "url": ""}
                        )
                        hero_rel = None
                        accent_rel = None
                        generated_assets = []
                        patched = dict(creative_brief)
                        if kit.get("heroImageUrl") and not (
                            kit.get("heroBusy") or kit.get("heroBrandMark")
                        ):
                            patched["heroStrategy"] = "use_kit_photo"
                        else:
                            patched["heroStrategy"] = "gradient_from_palette"
                            patched["layoutRecipe"] = "gradient-brand"
                        creative_brief = patched
                elif not ideogram_api_key():
                    ideogram_fallback_message = (
                        "IDEOGRAM_API_KEY not set — using scraped kit hero or brand gradient."
                    )
                    patched = dict(creative_brief)
                    if kit.get("heroImageUrl") and not (
                        kit.get("heroBusy") or kit.get("heroBrandMark")
                    ):
                        patched["heroStrategy"] = "use_kit_photo"
                    else:
                        patched["heroStrategy"] = "gradient_from_palette"
                        patched["layoutRecipe"] = "gradient-brand"
                    creative_brief = patched
                elif not prompt:
                    ideogram_fallback_message = (
                        "Creative brief missing heroImagePrompt — using gradient fallback."
                    )
                    creative_brief = {
                        **creative_brief,
                        "heroStrategy": "gradient_from_palette",
                        "layoutRecipe": "gradient-brand",
                    }
            if not should_skip_hero_for_brief(kit, creative_brief):
                hero_rel = self._maybe_cache_hero(kit, asset_errors)
            logo_treatment = (creative_brief or {}).get("logoTreatment")
            if logo_treatment == "wordmark-white":
                logo_recolor_light = True
            elif logo_treatment == "wordmark-dark":
                logo_recolor_light = False
            else:
                logo_recolor_light = should_recolor_logo_light(
                    kit,
                    has_photo_hero=bool(hero_rel),
                    hero_busy=hero_busy,
                    hero_brand_mark=hero_brand_mark,
                )
            logo_rel = self._maybe_cache_logo(
                kit,
                asset_errors,
                recolor_light_mark=logo_recolor_light,
            )
            hero_width: int | None = None
            hero_height: int | None = None
            accent_width: int | None = None
            accent_height: int | None = None
            logo_width: int | None = None
            logo_height: int | None = None
            if hero_rel:
                hero_dims = raster_dimensions(os.path.join(ROOT, hero_rel))
                if hero_dims:
                    hero_width, hero_height = hero_dims
            if accent_rel:
                accent_dims = raster_dimensions(os.path.join(ROOT, accent_rel))
                if accent_dims:
                    accent_width, accent_height = accent_dims
            if logo_rel:
                logo_dims = image_dimensions(os.path.join(ROOT, logo_rel))
                if logo_dims:
                    logo_width, logo_height = logo_dims
            elif isinstance((kit or {}).get("logoSvg"), str):
                svg_dims = svg_dimensions_from_text(str(kit["logoSvg"]))
                if svg_dims:
                    logo_width, logo_height = svg_dims

            def _font_fetch(url: str) -> bytes:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "CommMaker-FontFetcher/0.1 (+https://github.com/asseukihuh/AI-WebApp)",
                        "Accept": "text/css,font/woff2,*/*",
                    },
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SEC) as resp:
                    return resp.read()

            fonts_resolved = resolve_poster_fonts(
                kit or {},
                ROOT,
                fetcher=_font_fetch,
            )
            batch = compile_poster_batch(
                kit,
                session,
                logo_relative_path=logo_rel,
                hero_relative_path=hero_rel,
                hero_width=hero_width,
                hero_height=hero_height,
                accent_relative_path=accent_rel,
                accent_width=accent_width,
                accent_height=accent_height,
                logo_width=logo_width,
                logo_height=logo_height,
                fonts_resolved=fonts_resolved,
                creative_brief=creative_brief,
            )
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
            placement_errors = list(result.get("placementErrors") or [])
            if asset_errors:
                for item in asset_errors:
                    placement_errors.append(
                        {
                            "role": item.get("role", "asset"),
                            "error": item.get("error", "asset download failed"),
                            "url": item.get("url"),
                        }
                    )
            payload = {
                "ok": result.get("ok", False),
                "commandBatch": result.get("commandBatch"),
                "documentPath": result.get("documentPath"),
                "openUrl": result.get("openUrl"),
                "cliAvailable": result.get("cliAvailable", False),
                "cliPath": result.get("cliPath"),
                "placementErrors": placement_errors,
                "fontsResolved": fonts_resolved,
            }
            if generated_assets:
                payload["generatedAssets"] = generated_assets
            if hero_meta:
                payload["heroSource"] = hero_meta.get("heroSource")
                payload["heroImagePrompt"] = hero_meta.get("heroImagePrompt")
                payload["ideogramResolution"] = hero_meta.get("ideogramResolution")
                if hero_meta.get("ideogramLayers"):
                    payload["ideogramLayers"] = hero_meta.get("ideogramLayers")
                if hero_meta.get("resolutionNote"):
                    payload["resolutionNote"] = hero_meta["resolutionNote"]
            if ideogram_fallback_message:
                payload["ideogramFallback"] = ideogram_fallback_message
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
        print("Creative brief: POST http://localhost:{}/api/creative-brief".format(args.port))
        print("Poster API: POST http://localhost:{}/api/generate-poster".format(args.port))
        os.makedirs(GENERATED_DIR, exist_ok=True)
        httpd.serve_forever()


if __name__ == "__main__":
    main()
