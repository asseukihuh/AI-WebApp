#!/usr/bin/env python3
"""Tests for Ideogram multi-layer generate + poster compile stack."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from creative_brief import _normalize_brief  # noqa: E402
from poster_compiler import compile_poster_batch  # noqa: E402


class TestIdeogramLayersBrief(unittest.TestCase):
    @patch.dict(os.environ, {"IDEOGRAM_API_KEY": "test-key"})
    def test_default_layers_plus_accent_when_key_set(self) -> None:
        brief = _normalize_brief(
            {
                "headline": "Update",
                "subhead": "",
                "layoutRecipe": "photo-hero-type",
                "heroStrategy": "ideogram_generate",
                "logoTreatment": "wordmark-white",
                "emphasis": "calm",
                "rationale": "AI layers.",
                "heroImagePrompt": "Soft gradient background with lower-left negative space",
            }
        )
        self.assertEqual(brief["ideogramLayers"], "background-plus-accent")
        self.assertIn("accentImagePrompt", brief)

    def test_background_only_respected(self) -> None:
        brief = _normalize_brief(
            {
                "headline": "Update",
                "subhead": "",
                "layoutRecipe": "photo-hero-type",
                "heroStrategy": "ideogram_generate",
                "logoTreatment": "wordmark-white",
                "emphasis": "calm",
                "rationale": "Texture only.",
                "heroImagePrompt": "Abstract texture",
                "ideogramLayers": "background-only",
            }
        )
        self.assertEqual(brief["ideogramLayers"], "background-only")
        self.assertNotIn("accentImagePrompt", brief)


class TestPosterLayerStack(unittest.TestCase):
    def test_ideogram_background_and_accent_placements(self) -> None:
        brief = {
            "headline": "Service update",
            "subhead": "Details",
            "layoutRecipe": "photo-hero-type",
            "heroStrategy": "ideogram_generate",
            "ideogramLayers": "background-plus-accent",
            "logoTreatment": "wordmark-white",
            "emphasis": "calm",
            "rationale": "Layered AI art.",
        }
        kit = {"siteName": "Acme", "colors": ["#112233"]}
        session = {"brief": {"facts": "Maintenance tonight."}}
        batch = compile_poster_batch(
            kit,
            session,
            hero_relative_path="generated/assets/layer-ideogram-background-abc.png",
            hero_width=1280,
            hero_height=720,
            accent_relative_path="generated/assets/layer-ideogram-accent-cutout-def.png",
            accent_width=1024,
            accent_height=1024,
            creative_brief=brief,
        )
        bg = batch.get("backgroundPlacements") or []
        names = [p.get("name") for p in bg]
        self.assertEqual(names, ["Background", "Accent illustration"])
        layer_names = [(st.get("params") or {}).get("name") for st in batch.get("steps") or []]
        self.assertIn("Text scrim", layer_names)
        self.assertNotIn("layer.newFillLayer.solidColor", [st.get("command") for st in batch["steps"]])
        meta = batch.get("meta") or {}
        self.assertTrue(meta.get("hasAccentLayer"))
        self.assertEqual(meta.get("ideogramLayers"), "background-plus-accent")

    def test_background_only_single_raster_layer(self) -> None:
        brief = {
            "headline": "Update",
            "subhead": "",
            "layoutRecipe": "photo-hero-type",
            "heroStrategy": "ideogram_generate",
            "ideogramLayers": "background-only",
            "logoTreatment": "wordmark-white",
            "emphasis": "calm",
            "rationale": "One layer.",
        }
        batch = compile_poster_batch(
            {},
            {"brief": {"facts": "x"}},
            hero_relative_path="generated/assets/layer-ideogram-background-abc.png",
            hero_width=1280,
            hero_height=720,
            creative_brief=brief,
        )
        bg = batch.get("backgroundPlacements") or []
        self.assertEqual(len(bg), 1)
        self.assertEqual(bg[0].get("name"), "Background")
        self.assertFalse((batch.get("meta") or {}).get("hasAccentLayer"))


class TestMultiGenerateMocked(unittest.TestCase):
    @patch("ideogram_client._download_image")
    @patch("ideogram_client._call_generate_api")
    def test_generate_two_roles(self, mock_api: MagicMock, mock_dl: MagicMock) -> None:
        from ideogram_client import generate_layer_image  # noqa: E402

        mock_api.return_value = {
            "data": [{"url": "https://cdn.example/layer.png", "is_image_safe": True}]
        }
        mock_dl.return_value = b"\x89PNG\r\n\x1a\n"

        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"COMMMAKER_IDEOGRAM_ACCENT_CUTOUT": "false"}):
                rel_bg, _, meta_bg = generate_layer_image(
                    "Background scene",
                    "background",
                    "1200x627",
                    assets_dir=tmp,
                    api_key="k",
                )
                rel_ac, _, meta_ac = generate_layer_image(
                    "Accent subject",
                    "accent",
                    "1024x1024",
                    assets_dir=tmp,
                    api_key="k",
                )
        self.assertIn("background", rel_bg)
        self.assertIn("accent", rel_ac)
        self.assertEqual(meta_bg["role"], "background")
        self.assertEqual(meta_ac["role"], "accent")
        self.assertEqual(mock_api.call_count, 2)


if __name__ == "__main__":
    unittest.main()
