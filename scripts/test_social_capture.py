#!/usr/bin/env python3
"""Public social capture and the single brand-bundle call."""

from __future__ import annotations

import os
import sys
import unittest

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from creative_brief import brand_layout_energy, build_fallback_brief  # noqa: E402
from poster_design import template_needs_raster, template_skips_ideogram  # noqa: E402
from social_capture import (  # noqa: E402
    page_status,
    public_social_targets,
    strategy_from_capture,
)


class TestPublicSocial(unittest.TestCase):
    def test_targets_are_public_profile_urls(self) -> None:
        targets = public_social_targets(
            "https://www.stripe.com/",
            ["https://www.instagram.com/stripe/", "https://twitter.com/stripe"],
            "Stripe",
        )
        urls = [item["url"] for item in targets]
        self.assertIn("https://www.instagram.com/stripe/", urls)
        self.assertTrue(any("linkedin.com/company/stripe" in url for url in urls))
        self.assertFalse(any("twitter.com" in url for url in urls))
        self.assertFalse(any("login" in url for url in urls))

    def test_login_wall_is_recorded_not_treated_as_posts(self) -> None:
        self.assertEqual(
            page_status("https://www.instagram.com/accounts/login/", "Login • Instagram", "Log in to Instagram"),
            "login-wall",
        )
        self.assertEqual(page_status("https://example.com/posts", "Stripe", "A public post about billing " * 40), "loaded")
        strategy = strategy_from_capture(
            {
                "visits": [
                    {"platform": "instagram", "url": "https://www.instagram.com/stripe/", "status": "login-wall"},
                    {"platform": "linkedin", "url": "https://www.linkedin.com/company/stripe/posts/", "status": "partial"},
                ]
            }
        )
        self.assertEqual(strategy["formats"], [])
        self.assertIn("Login wall", strategy["notes"])
        self.assertIn("prices", strategy["doNotInvent"])

    def test_social_format_picks_the_frame_and_skips_ideogram_for_type(self) -> None:
        profile = {"socialStrategy": {"formats": ["type-only", "photo-card"], "voice": "warm", "doNotInvent": ["statistics"]}}
        self.assertEqual(brand_layout_energy({"siteName": "Airbnb", "colors": ["#e61e4d"]}, profile), "photo-card")
        self.assertFalse(template_skips_ideogram("type-only"))
        self.assertFalse(template_skips_ideogram("communique"))
        self.assertFalse(template_skips_ideogram("mark-stage"))
        self.assertFalse(template_needs_raster("type-only"))
        self.assertTrue(template_needs_raster("photo-card"))
        self.assertTrue(template_needs_raster("character-scene"))
        self.assertTrue(template_needs_raster("full-bleed-scrim"))
        brief = build_fallback_brief(
            {"siteName": "Airbnb", "colors": ["#e61e4d", "#ffffff"]},
            {"crisisMessage": "Stay somewhere new", "crisisFacts": "Homes with a kitchen."},
            brand_profile={"socialStrategy": {"formats": ["type-only"], "voice": "plain", "doNotInvent": []}},
        )
        self.assertEqual(brief["layoutTemplate"], "type-only")
        self.assertNotEqual(brief["heroStrategy"], "ideogram_generate")


if __name__ == "__main__":
    unittest.main()
