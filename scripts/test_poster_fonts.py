#!/usr/bin/env python3
"""Verify headline vs body font selection in poster batches (Stripe + Meunier fixtures)."""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from font_fetcher import parse_google_font_links, pick_body_font, pick_headline_font  # noqa: E402
from kit_scraper import scrape_kit_from_html  # noqa: E402
from poster_compiler import compile_poster_batch  # noqa: E402


def _type_fonts(batch: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for step in batch.get("steps") or []:
        if step.get("command") != "type.create":
            continue
        params = step.get("params") or {}
        name = params.get("name") or "?"
        out[name] = params.get("font") or ""
    return out


def _stripe_kit() -> dict:
    return {
        "siteName": "Stripe",
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
        assert fonts["Subline"] == fonts["Footer"]
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


def test_logo_placements_with_hero() -> None:
    batch = compile_poster_batch(
        _stripe_kit(),
        _session(),
        hero_relative_path="generated/assets/test-hero.jpg",
        logo_relative_path="generated/assets/test-logo.png",
    )
    placements = batch.get("placements") or []
    assert len(placements) >= 2
    assert placements[0].get("name") == "Logo knockback"
    assert placements[-1].get("name") == "Logo"


def main() -> int:
    test_pick_helpers()
    test_batch_fonts_differ()
    test_google_font_link_parse()
    test_logo_placements_with_hero()
    print("poster font tests OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
