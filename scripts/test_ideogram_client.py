#!/usr/bin/env python3
"""Tests for Ideogram hero client (mocked HTTP)."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from ideogram_client import (  # noqa: E402
    IDEOGRAM_GENERATE_URL,
    _call_generate_api,
    closest_ideogram_resolution,
    generate_hero_image,
    generate_layer_image,
    hero_cache_basename_for_prompt,
    ideogram_auth_headers,
    ideogram_conditioning,
    resolve_layer_resolution,
)
from creative_brief import CREATIVE_BRIEF_JSON_SCHEMA, _normalize_brief  # noqa: E402


class TestIdeogramConditioning(unittest.TestCase):
    def test_generate_has_no_style_reference(self) -> None:
        note = ideogram_conditioning()
        self.assertFalse(note["generateAcceptsReferenceImage"])
        self.assertTrue(note["remixKeepsSourceText"])
        self.assertIn("no image reference", str(note["note"]).lower())
        self.assertIn("palette", str(note["note"]).lower())


class TestIdeogramResolution(unittest.TestCase):
    def test_linkedin_maps_to_1280x720(self) -> None:
        self.assertEqual(closest_ideogram_resolution("1200x627"), "1280x720")

    def test_role_resolution_background(self) -> None:
        self.assertEqual(resolve_layer_resolution("background", "1200x627"), "1280x720")

    def test_role_resolution_accent_default(self) -> None:
        self.assertEqual(resolve_layer_resolution("accent", ""), "1024x1024")

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
            self.assertTrue(rel.startswith("generated/assets/layer-ideogram-background-"))
            self.assertEqual(data[:4], b"\x89PNG")
            self.assertEqual(meta["heroSource"], "ideogram-4")
            self.assertEqual(meta["ideogramResolution"], "1280x720")
            basename = rel.split("/")[-1]
            self.assertTrue(os.path.isfile(os.path.join(tmp, basename)))
            mock_api.assert_called_once()
            call_resolution = mock_api.call_args[0][1]
            self.assertEqual(call_resolution, "1280x720")

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


class TestIdeogramAuthHeader(unittest.TestCase):
    def test_generate_sends_api_key_not_bearer(self) -> None:
        seen: dict = {}

        def fake_open(req: urllib.request.Request, timeout: float | None = None):
            seen["req"] = req
            seen["timeout"] = timeout
            body = b'{"error":"The API key is invalid.","reject_reason":"invalid_api_key"}'
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", None, io.BytesIO(body))

        headers = ideogram_auth_headers("test-key")
        self.assertEqual(headers["Api-Key"], "test-key")
        self.assertNotIn("Authorization", headers)

        with patch("ideogram_client.urllib.request.urlopen", fake_open):
            with self.assertRaises(ValueError) as caught:
                _call_generate_api(
                    "A text-free illustration",
                    "1280x720",
                    api_key="test-key",
                    rendering_speed="default",
                    magic_prompt="off",
                )

        req = seen["req"]
        self.assertEqual(req.full_url, IDEOGRAM_GENERATE_URL)
        self.assertEqual(req.get_method(), "POST")
        # urllib title-cases header names in do_open before they are written.
        wire = {name.title(): value for name, value in {**req.unredirected_hdrs, **req.headers}.items()}
        self.assertEqual(wire.get("Api-Key"), "test-key")
        self.assertNotIn("Authorization", wire)
        self.assertNotIn("Bearer", " ".join(wire))
        message = str(caught.exception)
        self.assertIn("HTTP 401", message)
        self.assertIn("The API key is invalid.", message)
        self.assertIn("invalid_api_key", message)
        self.assertNotIn("HTTP Error 401: Unauthorized", message)


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
