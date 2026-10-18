#!/usr/bin/env python3
"""Verify headline vs body font selection in poster batches (Stripe + Meunier fixtures)."""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from font_fetcher import (  # noqa: E402
    parse_font_faces,
    parse_google_font_links,
    pick_body_font,
    pick_headline_font,
    resolve_poster_fonts,
)
from kit_scraper import scrape_kit_from_html  # noqa: E402
from image_probe import svg_dimensions_from_text  # noqa: E402
from poster_compiler import (  # noqa: E402
    compile_poster_batch,
    count_logo_placements,
)
from poster_design import HEADLINE_MIN_SIZE, MARGIN_X, SUBLINE_MIN_SIZE, span_w  # noqa: E402


def _type_fonts(batch: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for step in batch.get("steps") or []:
        if step.get("command") != "type.create":
            continue
        params = step.get("params") or {}
        name = params.get("name") or "?"
        out[name] = params.get("font") or ""
    return out


_STRIPE_LOGO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 120" width="512" height="120">'
    '<path fill="#635BFF" d="M0 0h512v120H0z"/></svg>'
)


def _stripe_kit() -> dict:
    return {
        "siteName": "Stripe",
        "logoSvg": _STRIPE_LOGO_SVG,
        "fonts": ["sohne-var", "Inter", "Helvetica"],
        "googleFonts": [
            {
                "family": "Inter",
                "weights": ["400", "600"],
                "cssUrl": "https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap",
            }
        ],
        "heroImageUrl": "https://example.com/hero.jpg",
        "heroWidth": 1200,
        "heroHeight": 630,
        "colors": ["#635bff"],
        "tagline": "Financial infrastructure for the internet",
    }


def _meunier_kit() -> dict:
    return {
        "siteName": "Meunier",
        "fonts": ["Cormorant Garamond", "Source Sans Pro"],
        "googleFonts": [
            {
                "family": "Cormorant Garamond",
                "weights": ["400", "700"],
                "cssUrl": "https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;700&display=swap",
            },
            {
                "family": "Source Sans Pro",
                "weights": ["400"],
                "cssUrl": "https://fonts.googleapis.com/css2?family=Source+Sans+Pro:wght@400&display=swap",
            },
        ],
        "heroImageUrl": "https://example.com/project.jpg",
        "heroWidth": 1600,
        "heroHeight": 900,
        "colors": ["#1c1c1c"],
        "tagline": "Architecture contemporaine",
    }


def _session() -> dict:
    return {
        "suggestedHeadline": "Project update",
        "brief": {"headline": "Project update", "facts": "Timeline adjusted.\n"},
    }


def test_pick_helpers() -> None:
    kit = _meunier_kit()
    assert pick_headline_font(kit) == "Cormorant Garamond"
    assert pick_body_font(kit) == "Source Sans Pro"


def test_batch_fonts_differ() -> None:
    for kit in (_stripe_kit(), _meunier_kit()):
        batch = compile_poster_batch(
            kit,
            _session(),
            hero_relative_path="generated/assets/test-hero.jpg",
            hero_width=kit.get("heroWidth"),
            hero_height=kit.get("heroHeight"),
            logo_relative_path="generated/assets/test-logo.png",
            logo_width=200,
        )
        fonts = _type_fonts(batch)
        assert fonts["Headline"] != fonts["Subline"], (kit.get("siteName"), fonts)
        assert "Footer" not in fonts
        meta = (batch.get("meta") or {}).get("fonts") or {}
        assert meta.get("headline") == fonts["Headline"]
        assert meta.get("body") == fonts["Subline"]


def test_google_font_link_parse() -> None:
    html = (
        '<link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;700&display=swap" '
        'rel="stylesheet">'
    )
    kit = scrape_kit_from_html(html, "https://example.com/")
    assert kit.get("googleFonts")
    assert kit["googleFonts"][0]["family"] == "Roboto"
    assert "700" in kit["googleFonts"][0]["weights"]
    parsed = parse_google_font_links(html)
    assert parsed[0]["cssUrl"].startswith("https://fonts.googleapis.com/")


def test_airbnb_lockup_keeps_the_symbol_and_the_variable_font() -> None:
    import tempfile

    from poster_compiler import crop_lockup_svg

    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 32" width="120" height="32">'
        '<path d="M4 4h24v24H4z"/>'
        '<path d="M48 8h60v16H48z"/>'
        "</svg>"
    )
    cropped = crop_lockup_svg(svg)
    assert "M4 4h24v24H4z" in cropped
    assert "M48 8h60v16H48z" not in cropped
    assert "viewBox=\"0 0" in cropped
    css = (
        '@font-face { font-family: "Airbnb Cereal VF"; '
        'src: url(https://a0.muscache.com/airbnb/static/fonts/cereal.woff2) format("woff2"); '
        "font-weight: 300 900; }"
    )
    faces = parse_font_faces(css, "https://www.airbnb.com/")
    assert faces[0]["family"] == "Airbnb Cereal VF"
    assert faces[0]["url"].endswith("cereal.woff2")
    kit = scrape_kit_from_html(f"<style>{css}</style><h1>Stay somewhere new</h1>", "https://www.airbnb.com/")
    assert any(item["url"].endswith("cereal.woff2") for item in kit.get("fontFiles") or [])
    font_kit = {
        "siteName": "Airbnb",
        "fonts": ["Airbnb Cereal VF", "Circular"],
        "colors": ["#ff5a5f"],
        "fontFiles": faces,
        "logoSvg": cropped,
    }
    profile = {"typography": {"display": {"family": "Airbnb Cereal VF", "weights": [700]}}}

    def fetch_ok(url: str) -> bytes:
        if url.endswith(".woff2"):
            return b"wOF2" + b"\x00" * 40
        raise OSError(url)

    def fetch_fail(url: str) -> bytes:
        raise OSError(url)

    with tempfile.TemporaryDirectory() as tmp:
        loaded = resolve_poster_fonts(font_kit, tmp, fetcher=fetch_ok)
        assert "Airbnb Cereal VF" in loaded["woff2"]
        assert "fontFailure" not in loaded
        assets = os.path.join(tmp, "generated", "assets")
        os.makedirs(assets)
        logo_path = os.path.join(assets, "logo.svg")
        with open(logo_path, "w", encoding="utf-8") as handle:
            handle.write(svg)
        batch = compile_poster_batch(
            font_kit,
            _session(),
            creative_brief={
                "headline": "Stay somewhere new",
                "subhead": "Homes with a kitchen",
                "layoutTemplate": "photo-block",
                "treatment": "photo-band",
                "heroStrategy": "ideogram_generate",
            },
            hero_relative_path="generated/assets/home.png",
            hero_width=1440,
            hero_height=720,
            logo_relative_path="generated/assets/logo.svg",
            logo_width=120,
            logo_height=32,
            assets_dir=assets,
            fonts_resolved=loaded,
            brand_profile=profile,
        )
        assert batch["meta"]["brandFontFailed"] is False
        logo = next(item for item in batch["placements"] if item.get("name") == "Logo")
        assert "logo-symbol-" in logo["path"]
        headline = next(step for step in batch["steps"] if step["params"].get("name") == "Headline")
        assert headline["params"]["font"] == "Airbnb Cereal VF"
        assert headline["params"]["box"][0] > 80
        assert any(step["params"].get("name") == "Type band" for step in batch["steps"])
    with tempfile.TemporaryDirectory() as failed_dir:
        failed = resolve_poster_fonts(font_kit, failed_dir, fetcher=fetch_fail)
        assert "cereal.woff2" in failed["fontFailure"]


def test_logo_placements_with_hero() -> None:
    svg_dims = svg_dimensions_from_text(_STRIPE_LOGO_SVG)
    assert svg_dims == (512, 120)
    batch = compile_poster_batch(
        _stripe_kit(),
        _session(),
        hero_relative_path="generated/assets/test-hero.jpg",
        logo_relative_path="generated/assets/test-logo.png",
        logo_width=svg_dims[0],
        logo_height=svg_dims[1],
    )
    placements = batch.get("placements") or []
    assert count_logo_placements(batch) == 1
    assert len(placements) == 1
    logo_place = placements[0]
    assert logo_place.get("name") == "Logo"
    meta = batch.get("meta") or {}
    assert meta.get("logoKnockback") is False
    assert (meta.get("contrast") or {}).get("logo", 0) >= 3.0
    layout = (batch.get("meta") or {}).get("logoLayout") or {}
    assert layout.get("targetHeightPx") == 36
    assert layout.get("targetWidthPx", 999) <= span_w(3)
    assert abs(logo_place["center"][0] - layout["targetWidthPx"] / 2 - MARGIN_X) <= 1
    steps = batch.get("steps") or []
    type_steps = [s for s in steps if s.get("command") == "type.create"]
    headline = next(s for s in type_steps if s["params"]["name"] == "Headline")
    subline = next(s for s in type_steps if s["params"]["name"] == "Subline")
    assert headline["params"]["size"] >= HEADLINE_MIN_SIZE
    assert headline["params"]["weight"] >= 700
    assert subline["params"]["size"] >= SUBLINE_MIN_SIZE
    assert headline["params"]["box"][0] == subline["params"]["box"][0] == MARGIN_X
    assert not any(p.get("name") == "Type scrim" for p in batch.get("backgroundPlacements") or [])
    assert any(s.get("command") == "gradient.fill.create" for s in steps)


def main() -> int:
    test_pick_helpers()
    test_batch_fonts_differ()
    test_google_font_link_parse()
    test_airbnb_lockup_keeps_the_symbol_and_the_variable_font()
    test_logo_placements_with_hero()
    print("poster font tests OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
