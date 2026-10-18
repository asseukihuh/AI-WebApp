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
    ideogram_conditioning,
    closest_ideogram_resolution,
    generate_hero_image,
    generate_layer_image,
    hero_cache_basename_for_prompt,
    resolve_layer_resolution,
)
from creative_brief import CREATIVE_BRIEF_JSON_SCHEMA, _normalize_brief  # noqa: E402


class TestIdeogramConditioning(unittest.TestCase):
    def test_generate_accepts_one_reference_image(self) -> None:
        note = ideogram_conditioning()
        self.assertTrue(note["generateAcceptsReferenceImage"])
        self.assertEqual(note["imageField"], "images")
        self.assertIn("ideogram-4-5", note["generateUrl"])
        self.assertTrue(note["remixKeepsSourceText"])
        self.assertIn("images field", str(note["note"]).lower())
        self.assertIn("palette", str(note["note"]).lower())


class TestIdeogramResolution(unittest.TestCase):
    def test_linkedin_maps_to_a_4_5_preset(self) -> None:
        self.assertEqual(closest_ideogram_resolution("1200x627"), "2880x1440")
        self.assertNotEqual(closest_ideogram_resolution("1200x627"), "1280x720")
        self.assertNotEqual(closest_ideogram_resolution("1200x627"), "1440x720")
        self.assertNotEqual(closest_ideogram_resolution("1200x627"), "1200x627")

    def test_role_resolution_background(self) -> None:
        self.assertEqual(resolve_layer_resolution("background", "1200x627"), "2880x1440")

    def test_role_resolution_accent_default(self) -> None:
        self.assertEqual(resolve_layer_resolution("accent", ""), "1024x1024")

    def test_preset_passthrough(self) -> None:
        self.assertEqual(closest_ideogram_resolution("1024x1024"), "1024x1024")
        self.assertEqual(closest_ideogram_resolution("1440x2880"), "1440x2880")
        self.assertNotIn("1280x720", [closest_ideogram_resolution("1280x720")])


class TestIdeogramGenerateMocked(unittest.TestCase):
    @patch("ideogram_client._download_image")
    @patch("ideogram_client._call_generate_api")
    def test_generate_caches_png(self, mock_api: MagicMock, mock_dl: MagicMock) -> None:
        mock_api.return_value = {
            "data": [
                {
                    "url": "https://cdn.example/hero.png",
                    "is_image_safe": True,
                    "resolution": "2880x1440",
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
            self.assertTrue(rel.startswith("generated/assets/layer-ideogram-background-"))
            self.assertEqual(data[:4], b"\x89PNG")
            self.assertEqual(meta["heroSource"], "ideogram-4.5")
            self.assertEqual(meta["ideogramResolution"], "2880x1440")
            basename = rel.split("/")[-1]
            self.assertTrue(os.path.isfile(os.path.join(tmp, basename)))
            mock_api.assert_called_once()
            call_resolution = mock_api.call_args[0][1]
            self.assertEqual(call_resolution, "2880x1440")

    @patch("ideogram_client._download_image")
    @patch("ideogram_client._call_generate_api")
    def test_layer_generate_naming(self, mock_api: MagicMock, mock_dl: MagicMock) -> None:
        mock_api.return_value = {
            "data": [{"url": "https://cdn.example/layer.png", "is_image_safe": True}]
        }
        mock_dl.return_value = b"\x89PNG\r\n\x1a\n"
        with tempfile.TemporaryDirectory() as tmp:
            rel, _, meta = generate_layer_image(
                "Accent only",
                "accent",
                "1024x1024",
                assets_dir=tmp,
                api_key="test-key",
                remove_bg=False,
            )
        self.assertIn("layer-ideogram-accent-", rel)
        self.assertEqual(meta["role"], "accent")


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
