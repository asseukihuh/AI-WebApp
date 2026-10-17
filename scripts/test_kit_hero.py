#!/usr/bin/env python3
"""Kit hero selection + poster busy-hero / logo-on-dark behavior."""

from __future__ import annotations

import os
import sys

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from image_probe import classify_hero_candidate  # noqa: E402
from kit_scraper import scrape_kit_from_html  # noqa: E402
from image_probe import hero_url_looks_brand_mark  # noqa: E402
from poster_compiler import (  # noqa: E402
    LOGO_ICON_MAX_HEIGHT,
    compile_poster_batch,
    count_logo_placements,
    recolor_logo_svg_for_light_hero,
    should_recolor_logo_light,
)

VERCEL_META_SNIPPET = """
<!DOCTYPE html><html><head>
<meta charSet="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<meta property="og:image" content="https://cdn.example/og-home-not-x.png"/>
<meta property="og:title" content="Agentic Infrastructure - Vercel"/>
<meta name="description" content="The autonomous stack for every app and agent."/>
<meta name="twitter:image" content="https://cdn.example/zapier-desktop-dark.webp"/>
</head><body>
<img src="https://cdn.example/zapier-desktop-dark.webp" width="2784" height="1560"/>
</body></html>
"""

_STRIPE_LOGO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 120">'
    '<path fill="#0a2540" d="M0 0h512v120H0z"/></svg>'
)


def test_self_closing_meta_parsed() -> None:
    kit = scrape_kit_from_html(
        '<head><meta property="og:site_name" content="Vercel"/></head>',
        "https://vercel.com/",
    )
    assert kit.get("siteName") == "Vercel"


def test_vercel_fixture_prefers_clean_og() -> None:
    kit = scrape_kit_from_html(VERCEL_META_SNIPPET, "https://vercel.com/")
    assert kit.get("heroImageUrl") == "https://cdn.example/og-home-not-x.png"
    assert kit.get("heroBusy") is False
    assert kit.get("heroImageKind") == "og-marketing"
    assert kit.get("heroBrandMark") is True


_VERCEL_LOGO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 76 65">'
    '<path fill="#000000" d="M37.5 0L75 65H0z"/></svg>'
)


def test_vercel_poster_skips_og_uses_gradient_and_light_logo() -> None:
    kit = scrape_kit_from_html(VERCEL_META_SNIPPET, "https://vercel.com/")
    kit["logoSvg"] = _VERCEL_LOGO_SVG
    kit["colors"] = ["#000000", "#50e3c2", "#ffffff"]
    session = {
        "suggestedHeadline": "Platform incident",
        "brief": {"facts": "Elevated errors in EU."},
    }
    batch = compile_poster_batch(
        kit,
        session,
        hero_relative_path="generated/assets/should-be-ignored.jpg",
        hero_width=1200,
        hero_height=1200,
        logo_relative_path="generated/assets/vercel-logo.svg",
        logo_width=76,
        logo_height=65,
    )
    meta = batch.get("meta") or {}
    assert meta.get("heroBrandMark") is True
    assert meta.get("hasHero") is False
    assert meta.get("logoOnDark") is True
    assert count_logo_placements(batch) == 1
    bg = batch.get("backgroundPlacements") or []
    assert not any(p.get("name") == "Hero image" for p in bg)
    layout = meta.get("logoLayout") or {}
    assert layout.get("targetHeightPx", 99) <= LOGO_ICON_MAX_HEIGHT


def test_busy_url_classified() -> None:
    busy, kind = classify_hero_candidate(
        "https://cdn.example/zapier-desktop-dark.webp",
        width=2784,
        height=1560,
        source="page",
    )
    assert busy is True
    assert kind == "ui-screenshot"


def test_stripe_poster_no_knockback_logo_on_dark() -> None:
    kit = {
        "siteName": "Stripe",
        "logoSvg": _STRIPE_LOGO_SVG,
        "colors": ["#635bff", "#0a2540"],
        "fonts": ["Inter"],
        "tagline": "Financial infrastructure for the internet",
    }
    session = {
        "suggestedHeadline": "Service update",
        "brief": {"facts": "Investigating API errors."},
    }
    batch = compile_poster_batch(
        kit,
        session,
        hero_relative_path="generated/assets/test-hero.jpg",
        hero_width=1200,
        hero_height=630,
        logo_relative_path="generated/assets/logo.svg",
        logo_width=512,
        logo_height=120,
    )
    meta = batch.get("meta") or {}
    assert meta.get("logoOnDark") is True
    assert meta.get("logoKnockback") is False
    assert count_logo_placements(batch) == 1
    names = [p.get("name") for p in batch.get("placements") or []]
    assert "Logo knockback" not in names
    assert names[-1] == "Logo"


def test_og_home_url_classified_brand_mark() -> None:
    assert hero_url_looks_brand_mark(
        "https://cdn.example/og-home-not-x.png",
        width=1200,
        height=1200,
        kind="og-marketing",
    )


def test_busy_hero_skips_image_uses_gradient() -> None:
    kit = {
        "siteName": "Example",
        "heroBusy": True,
        "heroImageUrl": "https://cdn.example/ui.webp",
        "colors": ["#1a365d", "#2c5282", "#4a5568"],
    }
    batch = compile_poster_batch(
        kit,
        {"suggestedHeadline": "Update", "brief": {"facts": "Details."}},
        hero_relative_path="generated/assets/ui.webp",
    )
    assert not batch.get("backgroundPlacements")
    assert (batch.get("meta") or {}).get("hasHero") is False
    step_names = [
        (s.get("params") or {}).get("name")
        for s in batch.get("steps") or []
        if s.get("command") == "layer.newFillLayer.solidColor"
    ]
    assert "Brand base" in step_names


def test_svg_recolor_dark_paths() -> None:
    out = recolor_logo_svg_for_light_hero(_STRIPE_LOGO_SVG)
    assert 'fill="#ffffff"' in out or "fill='#ffffff'" in out
    assert "#0a2540" not in out


def main() -> int:
    test_self_closing_meta_parsed()
    test_vercel_fixture_prefers_clean_og()
    test_og_home_url_classified_brand_mark()
    test_vercel_poster_skips_og_uses_gradient_and_light_logo()
    test_busy_url_classified()
    test_stripe_poster_no_knockback_logo_on_dark()
    test_busy_hero_skips_image_uses_gradient()
    test_svg_recolor_dark_paths()
    print("kit hero tests OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
