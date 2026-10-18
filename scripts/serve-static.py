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
import time
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
from creative_brief import (  # noqa: E402
    _normalize_api_key,
    art_director_enabled,
    art_director_review,
    build_creative_brief,
    coerce_ideogram_for_unsuitable_kit_hero,
)
from ideogram_client import (  # noqa: E402
    brand_terms_from_kit,
    generate_layer_image,
    ideogram_api_key,
)
from ideogram_judge import (  # noqa: E402
    acquire_poster_picture,
    is_png,
    judge_real_png,
    picture_references,
    poster_status_line,
)
from image_luma import load_rgb_grid  # noqa: E402
from brand_profile import (  # noqa: E402
    analyze_brand_bundle,
    apply_brand_profile_to_kit,
    playwright_available,
)
from communication_kit import ensure_communication_kit  # noqa: E402
from poster_compiler import (  # noqa: E402
    compile_poster_batch,
    hero_cache_basename,
    logo_cache_basename,
    logo_svg_dimensions_oversized,
    logo_svg_variants,
    normalize_logo_fill,
    should_skip_hero_for_brief,
)
from poster_design import (  # noqa: E402
    brand_roles,
    kit_hero_unsuitable,
    resolve_template_name,
)
from photocraft_cli import run_poster_batch, _cli_missing_user_message  # noqa: E402

MAX_HTML_BYTES = 2_000_000
MAX_POSTER_BODY_BYTES = 256_000
MAX_LOGO_BYTES = 4_000_000
FETCH_TIMEOUT_SEC = 20
GENERATED_DIR = os.path.join(ROOT, "generated")
ASSETS_DIR = os.path.join(GENERATED_DIR, "assets")
BRAND_PROFILE_DIR = os.path.join(GENERATED_DIR, "brand-profiles")
COMMUNICATION_KIT_DIR = os.path.join(GENERATED_DIR, "communication-kits")

mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("text/javascript", ".js")


CREATIVE_BRIEF_STACK = "v28-picture-error"


def _request_brand_profile(body: dict, kit: dict) -> dict | None:
    """Explicit ``brandProfile`` in the request, else the one onboarding saves on ``kit.brandProfile``."""
    for candidate in (body.get("brandProfile"), (kit or {}).get("brandProfile")):
        if isinstance(candidate, dict) and candidate:
            return candidate
    return None


def dev_status_payload() -> dict:
    anthropic_key = _normalize_api_key(os.environ.get("ANTHROPIC_API_KEY"))
    ideogram_key = (os.environ.get("IDEOGRAM_API_KEY") or "").strip().lstrip("\ufeff")
    return {
        "anthropicKeyLoaded": bool(anthropic_key),
        "anthropicKeyLen": len(anthropic_key),
        "ideogramKeyLoaded": bool(ideogram_key),
        "playwrightAvailable": playwright_available()[0],
        "creativeBriefStack": CREATIVE_BRIEF_STACK,
    }


def log_anthropic_key_on_startup() -> None:
    key = _normalize_api_key(os.environ.get("ANTHROPIC_API_KEY"))
    if not key:
        return
    prefix = key if len(key) <= 12 else f"{key[:12]}…"
    sys.stderr.write(
        f"CommMaker: ANTHROPIC_API_KEY loaded (len={len(key)}, prefix={prefix})\n"
    )


class CommMakerHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, coop_coep: bool = False, **kwargs):
        self.coop_coep = coop_coep
        super().__init__(*args, directory=ROOT, **kwargs)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/dev-status":
            self._handle_dev_status()
            return
        super().do_GET()

    def _handle_dev_status(self) -> None:
        self._send_json(200, dev_status_payload())

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/scrape-kit":
            self._handle_scrape_kit()
            return
        if path == "/api/creative-brief":
            self._handle_creative_brief()
            return
        if path == "/api/brand-profile":
            self._handle_brand_profile()
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

    def _scrape_kit_for_url(self, url: str) -> dict:
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
            return data[:MAX_STYLESHEET_BYTES]

        return scrape_kit_from_page(html, url, fetcher=_css_fetcher)

    def _handle_brand_profile(self) -> None:
        try:
            body = self._read_json_body()
            url = validate_fetch_url(str(body.get("url", "")))
            result = analyze_brand_bundle(
                url,
                cache_dir=BRAND_PROFILE_DIR,
                scrape_fn=self._scrape_kit_for_url,
                refresh=bool(body.get("refresh")),
                mobile=body.get("mobile", True) is not False,
                repo_root=ROOT,
            )
            kit = result.get("kit") or {}
            shots = (result.get("capture") or {}).get("screenshots") or {}
            if shots and isinstance(kit, dict):
                kit["screenshotPaths"] = shots
                result["kit"] = kit
            self._send_json(200, result)
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

    def _maybe_cache_logo_variants(
        self,
        kit: dict,
        errors: list[dict[str, str]] | None = None,
    ) -> dict[str, str]:
        """Cache the logo; inline SVGs also get ``light`` / ``dark`` recolored variants."""
        if not kit:
            return {}
        logo_svg = kit.get("logoSvg")
        if isinstance(logo_svg, str) and logo_svg.strip().startswith("<svg"):
            payload = logo_svg.strip()
            dims = svg_dimensions_from_text(payload)
            if dims and logo_svg_dimensions_oversized(dims[0], dims[1]):
                fallback = self._maybe_cache_remote_asset(
                    kit.get("logoUrl"), logo_cache_basename, errors, role="logo"
                ) or self._maybe_cache_remote_asset(
                    kit.get("faviconUrl"), logo_cache_basename, errors, role="logo"
                )
                return {"original": fallback} if fallback else {}
            variants: dict[str, str] = {}
            for name, markup in logo_svg_variants(payload).items():
                digest = hashlib.sha256(markup.encode("utf-8")).hexdigest()[:16]
                variants[name] = self._write_cached_asset(
                    f"logo-{digest}.svg", markup.encode("utf-8")
                )
            return variants
        remote = self._maybe_cache_remote_asset(
            kit.get("logoUrl"), logo_cache_basename, errors, role="logo"
        )
        return {"original": remote} if remote else {}

    def _maybe_cache_hero(
        self, kit: dict, errors: list[dict[str, str]] | None = None
    ) -> str | None:
        if kit and kit_hero_unsuitable(kit):
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
            kit = apply_brand_profile_to_kit(body.get("kit") or {})
            brand_profile = _request_brand_profile(body, kit)
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
            result = build_creative_brief(kit, crisis, fmt, brand_profile)
            payload = {
                "brief": result["brief"],
                "source": result["source"],
            }
            if result.get("model"):
                payload["model"] = result["model"]
            if result.get("provider"):
                payload["provider"] = result["provider"]
            if result.get("fallbackReason"):
                payload["fallbackReason"] = result["fallbackReason"]
            if result.get("errorDetail"):
                payload["errorDetail"] = result["errorDetail"]
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
            kit = apply_brand_profile_to_kit(kit)
            brand_profile = _request_brand_profile(body, kit)
            kit = ensure_communication_kit(
                kit,
                cache_dir=COMMUNICATION_KIT_DIR,
                brand_profile=brand_profile,
                allow_llm=not bool(kit.get("communicationKit")),
            )
            if isinstance(kit.get("logoSvg"), str) and kit["logoSvg"].strip().startswith(
                "<svg"
            ):
                kit.pop("logoUrl", None)
            creative_brief = body.get("creativeBrief")
            if isinstance(creative_brief, dict):
                crisis_for_brief = {
                    "crisisMessage": str(session.get("suggestedHeadline") or "").strip(),
                    "crisisFacts": str((session.get("brief") or {}).get("facts") or ""),
                    "tone": (session.get("brief") or {}).get("tone"),
                }
                creative_brief = coerce_ideogram_for_unsuitable_kit_hero(
                    creative_brief,
                    kit,
                    crisis_for_brief,
                )
            asset_errors: list[dict[str, str]] = []
            hero_rel = None
            accent_rel = None
            hero_meta: dict = {}
            generated_assets: list[dict[str, str]] = []
            ideogram_fallback_message: str | None = None
            ideogram_judge: dict | None = None
            ideogram_ms = 0
            ideogram_used = False
            picture_bytes: bytes | None = None
            picture_prompt = ""
            if isinstance(creative_brief, dict):
                roles = brand_roles(kit, brand_profile)
                resolved_template = resolve_template_name(
                    creative_brief,
                    has_image=True,
                    monochrome=roles.monochrome,
                    brand_profile=brand_profile,
                    communication_kit=kit.get("communicationKit") if isinstance(kit, dict) else None,
                )
                ideogram_style = {
                    "template": resolved_template,
                    "palette": [
                        c
                        for c in (roles.dark, roles.brand, roles.accent, roles.light, *roles.palette)
                        if c
                    ],
                    "brand_terms": brand_terms_from_kit(kit),
                    "mood": {
                        "urgent": "serious, steady, reassuring",
                        "celebratory": "optimistic, energetic, bright",
                    }.get(str(creative_brief.get("emphasis") or ""), "calm, confident, premium"),
                    "brand_profile": brand_profile,
                }

                picture_resolution = "1200x627"

                def _generate_picture(scene: str) -> tuple:
                    return generate_layer_image(
                        scene,
                        "background",
                        picture_resolution,
                        assets_dir=ASSETS_DIR,
                        **ideogram_style,
                    )

                acquired = acquire_poster_picture(
                    creative_brief,
                    kit,
                    brand_profile,
                    template=resolved_template,
                    key_set=bool(ideogram_api_key()),
                    generate=_generate_picture,
                )
                creative_brief = acquired["brief"]
                ideogram_ms = int(acquired["ideogramMs"])
                ideogram_used = bool(acquired["ideogramUsed"])
                ideogram_fallback_message = acquired["ideogramError"]
                picture_prompt = str(acquired.get("prompt") or "")
                picture_bytes = acquired.get("image") if isinstance(acquired.get("image"), (bytes, bytearray)) else None
                if ideogram_used and acquired.get("path") and is_png(picture_bytes):
                    hero_rel = str(acquired["path"])
                    bg_meta = acquired.get("meta") or {}
                    generated_assets.append(
                        {"role": "background", "path": hero_rel, "source": "ideogram-4"}
                    )
                    hero_meta = {
                        "heroSource": "ideogram-4",
                        "heroImagePrompt": picture_prompt,
                        "ideogramResolution": bg_meta.get("ideogramResolution"),
                        "ideogramLayers": "background-only",
                        "ideogramStructuredPrompt": bg_meta.get("structuredPrompt"),
                        "layoutTemplate": resolved_template,
                    }
                    if bg_meta.get("resolutionNote"):
                        hero_meta["resolutionNote"] = (
                            f"{bg_meta['resolutionNote']} "
                            "Poster compiler cover-fills the 1200×627 canvas."
                        )
                    kit["heroImageUrl"] = f"/{hero_rel}"
                    picture_path = os.path.join(ROOT, hero_rel)
                    logo_for_judge = self._maybe_cache_logo_variants(kit, asset_errors)
                    logo_rel_for_judge = logo_for_judge.get("original")
                    logo_abs = os.path.join(ROOT, logo_rel_for_judge) if logo_rel_for_judge else None

                    def _regenerate(revised: str) -> tuple:
                        nonlocal ideogram_ms
                        started = time.perf_counter()
                        try:
                            rel, data, meta = _generate_picture(revised)
                        finally:
                            ideogram_ms += int((time.perf_counter() - started) * 1000)
                        if not is_png(data):
                            raise ValueError("Ideogram retry did not return a PNG.")
                        return rel, data, meta

                    judge = judge_real_png(
                        picture_bytes,
                        picture_path,
                        picture_prompt,
                        reference_paths=picture_references(kit, ROOT, logo_path=logo_abs),
                        palette=ideogram_style["palette"],
                        brand_profile=brand_profile,
                        regenerate=_regenerate,
                        region=(0, 0, 1200, 627),
                        repo_root=ROOT,
                    )
                    if judge:
                        ideogram_judge = {
                            "passed": judge.get("passed"),
                            "reason": judge.get("reason") or "",
                            "attempts": int(judge.get("attempts") or 1),
                            "retried": bool(judge.get("retried")),
                        }
                        if judge.get("imagePath"):
                            hero_rel = str(judge["imagePath"])
                            generated_assets[-1]["path"] = hero_rel
                            generated_assets[-1]["source"] = "ideogram-4-retry"
                            kit["heroImageUrl"] = f"/{hero_rel}"
                            hero_meta["retried"] = True
                            picture_path = os.path.join(ROOT, hero_rel)
                            if os.path.isfile(picture_path):
                                with open(picture_path, "rb") as handle:
                                    picture_bytes = handle.read()
                elif acquired.get("called"):
                    asset_errors.append(
                        {
                            "role": "ideogram",
                            "error": ideogram_fallback_message or "Ideogram failed",
                            "url": "",
                        }
                    )
            else:
                ideogram_fallback_message = "No creative brief — Ideogram skipped."
            if not should_skip_hero_for_brief(kit, creative_brief):
                hero_rel = self._maybe_cache_hero(kit, asset_errors)
            logo_variants = self._maybe_cache_logo_variants(kit, asset_errors)
            logo_rel = logo_variants.get("original")
            hero_width: int | None = None
            hero_height: int | None = None
            accent_width: int | None = None
            accent_height: int | None = None
            logo_width: int | None = None
            logo_height: int | None = None
            hero_grid = None
            if hero_rel:
                hero_dims = raster_dimensions(os.path.join(ROOT, hero_rel))
                if hero_dims:
                    hero_width, hero_height = hero_dims
                hero_grid = load_rgb_grid(os.path.join(ROOT, hero_rel))
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
            compile_kwargs = {
                "logo_relative_path": logo_rel,
                "logo_variants": logo_variants or None,
                "logo_fill": normalize_logo_fill(None, kit),
                "hero_relative_path": hero_rel,
                "hero_width": hero_width,
                "hero_height": hero_height,
                "hero_grid": hero_grid,
                "accent_relative_path": accent_rel,
                "accent_width": accent_width,
                "accent_height": accent_height,
                "logo_width": logo_width,
                "logo_height": logo_height,
                "fonts_resolved": fonts_resolved,
                "assets_dir": ASSETS_DIR,
                "brand_profile": brand_profile,
            }
            batch = compile_poster_batch(
                kit, session, creative_brief=creative_brief, **compile_kwargs
            )
            art_director: dict | None = None
            audit_failed = ((batch.get("meta") or {}).get("designAudit") or {}).get("failed") or []
            if isinstance(creative_brief, dict) and art_director_enabled() and audit_failed:
                review = art_director_review(creative_brief, batch.get("meta") or {})
                if review:
                    art_director = {
                        "score": review.get("score"),
                        "issues": review.get("issues"),
                        "auditBefore": (batch.get("meta") or {}).get("designAudit", {}).get("score"),
                        "applied": review["brief"] != creative_brief,
                    }
                    if art_director["applied"]:
                        creative_brief = review["brief"]
                        batch = compile_poster_batch(
                            kit, session, creative_brief=creative_brief, **compile_kwargs
                        )
                    art_director["auditAfter"] = (
                        (batch.get("meta") or {}).get("designAudit", {}).get("score")
                    )
                    batch.setdefault("meta", {})["artDirector"] = art_director
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
                "previewUrl": result.get("previewPath"),
                "layoutTemplate": (batch.get("meta") or {}).get("layoutTemplate"),
                "designAudit": (batch.get("meta") or {}).get("designAudit"),
            }
            if art_director:
                payload["artDirector"] = art_director
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
            if isinstance(creative_brief, dict):
                payload["heroStrategy"] = creative_brief.get("heroStrategy")
                if creative_brief.get("ideogramLayers"):
                    payload["briefIdeogramLayers"] = creative_brief.get("ideogramLayers")
            payload["ideogramUsed"] = bool(ideogram_used) and is_png(picture_bytes)
            payload["ideogramMs"] = int(ideogram_ms)
            payload["ideogramError"] = ideogram_fallback_message
            if ideogram_judge and ideogram_judge.get("passed") is True and not is_png(picture_bytes):
                ideogram_judge = None
            if ideogram_judge:
                payload["ideogramJudge"] = ideogram_judge
            if ideogram_fallback_message:
                payload["ideogramFallback"] = ideogram_fallback_message
            payload["statusLine"] = poster_status_line(
                template=(batch.get("meta") or {}).get("layoutTemplate"),
                ideogram_used=bool(payload["ideogramUsed"]),
                error=ideogram_fallback_message,
                score=((batch.get("meta") or {}).get("designAudit") or {}).get("score"),
                ideogram_ms=int(ideogram_ms),
                judge=ideogram_judge,
            )
            sys.stderr.write(
                "CommMaker poster: template=%s ideogramUsed=%s ideogramMs=%s ideogramError=%s\n"
                % (
                    payload.get("layoutTemplate") or "-",
                    payload["ideogramUsed"],
                    payload["ideogramMs"],
                    ideogram_fallback_message or "-",
                )
            )
            scene = picture_prompt
            if not scene and isinstance(creative_brief, dict):
                scene = str(creative_brief.get("heroImagePrompt") or hero_meta.get("heroImagePrompt") or "")
            payload["promptSnippet"] = " ".join(scene.split())[:90]
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

    log_anthropic_key_on_startup()

    handler = functools.partial(CommMakerHandler, coop_coep=args.coop_coep)
    with http.server.ThreadingHTTPServer(("", args.port), handler) as httpd:
        print(f"Serving {ROOT} at http://localhost:{args.port}/")
        if args.coop_coep:
            print("COOP/COEP enabled (optional; PhotoCraft does not need SharedArrayBuffer)")
        print("PhotoCraft embed: http://localhost:{}/photocraft/".format(args.port))
        print("Brand profile: POST http://localhost:{}/api/brand-profile".format(args.port))
        print("Creative brief: POST http://localhost:{}/api/creative-brief".format(args.port))
        print("Poster API: POST http://localhost:{}/api/generate-poster".format(args.port))
        print("Dev status: GET http://localhost:{}/api/dev-status".format(args.port))
        os.makedirs(GENERATED_DIR, exist_ok=True)
        httpd.serve_forever()


if __name__ == "__main__":
    main()
