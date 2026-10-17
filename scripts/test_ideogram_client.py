#!/usr/bin/env python3
"""Tests for Ideogram hero client (mocked HTTP)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from ideogram_client import (  # noqa: E402
    closest_ideogram_resolution,
    generate_hero_image,
    hero_cache_basename_for_prompt,
)
from creative_brief import CREATIVE_BRIEF_JSON_SCHEMA, _normalize_brief  # noqa: E402


class TestIdeogramResolution(unittest.TestCase):
    def test_linkedin_maps_to_1280x720(self) -> None:
        self.assertEqual(closest_ideogram_resolution("1200x627"), "1280x720")

    def test_preset_passthrough(self) -> None:
        self.assertEqual(closest_ideogram_resolution("1280x720"), "1280x720")


class TestIdeogramGenerateMocked(unittest.TestCase):
    @patch("ideogram_client._download_image")
    @patch("ideogram_client._call_generate_api")
    def test_generate_caches_png(self, mock_api: MagicMock, mock_dl: MagicMock) -> None:
        mock_api.return_value = {
            "data": [
                {
                    "url": "https://cdn.example/hero.png",
                    "is_image_safe": True,
                    "resolution": "1280x720",
                }
            ]
        }
        mock_dl.return_value = b"\x89PNG\r\n\x1a\n"

        with tempfile.TemporaryDirectory() as tmp:
            rel, data, meta = generate_hero_image(
                "Calm abstract scene for Acme",
                "1200x627",
                assets_dir=tmp,
                api_key="test-key",
            )
            self.assertTrue(rel.startswith("generated/assets/hero-ideogram-"))
            self.assertEqual(data[:4], b"\x89PNG")
            self.assertEqual(meta["heroSource"], "ideogram-4")
            self.assertEqual(meta["ideogramResolution"], "1280x720")
            basename = rel.split("/")[-1]
            self.assertTrue(os.path.isfile(os.path.join(tmp, basename)))
            mock_api.assert_called_once()
            call_resolution = mock_api.call_args[0][1]
            self.assertEqual(call_resolution, "1280x720")


class TestCreativeBriefSchema(unittest.TestCase):
    def test_ideogram_strategy_in_schema(self) -> None:
        enums = CREATIVE_BRIEF_JSON_SCHEMA["properties"]["heroStrategy"]["enum"]
        self.assertIn("ideogram_generate", enums)

    def test_normalize_ideogram_requires_prompt(self) -> None:
        brief = _normalize_brief(
            {
                "headline": "Update",
                "subhead": "Details",
                "layoutRecipe": "photo-hero-type",
                "heroStrategy": "ideogram_generate",
                "logoTreatment": "wordmark-white",
                "emphasis": "calm",
                "rationale": "AI hero for busy scrape.",
                "heroImagePrompt": "Abstract blue gradient office scene for Stripe",
            }
        )
        self.assertEqual(brief["heroStrategy"], "ideogram_generate")
        self.assertIn("Stripe", brief["heroImagePrompt"])


if __name__ == "__main__":
    unittest.main()
