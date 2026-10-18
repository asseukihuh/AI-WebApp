#!/usr/bin/env python3
"""Brand packet for Ideogram: palette, imagery line, clean references, no remix."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from ideogram_client import (  # noqa: E402
    IDEOGRAM_GENERATE_URL,
    IDEOGRAM_REMIX_URL,
    _call_generate_api,
    build_structured_prompt,
    ideogram_conditioning,
)
from ideogram_judge import acquire_poster_picture, picture_references, poster_status_line  # noqa: E402
from ideogram_packet import (  # noqa: E402
    SCREENSHOTS_SKIPPED_STATUS,
    build_ideogram_packet,
    clean_references,
    mostly_page_text,
    prompt_with_packet,
)
from image_luma import load_rgb_grid  # noqa: E402
from render_poster_samples import write_png  # noqa: E402


def _png(path: str, width: int, height: int, pixel) -> None:
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            row.extend(pixel(x, y))
        rows.append(bytes(row))
    write_png(path, width, height, rows)


class TestCleanReferences(unittest.TestCase):
    def test_page_text_is_not_passed_and_a_photo_crop_is(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            text_path = os.path.join(tmp, "page.png")
            photo_path = os.path.join(tmp, "photo.png")
            _png(
                text_path,
                48,
                36,
                lambda x, y: (12, 16, 20) if y % 2 == 0 and x % 2 == 0 else (248, 248, 246),
            )
            _png(photo_path, 48, 32, lambda x, y: (30 + x, 70 + y, 160))
            text_grid = load_rgb_grid(text_path, grid_w=48)
            self.assertTrue(mostly_page_text(text_grid["pixels"], text_grid["w"], text_grid["h"]))
            photo_grid = load_rgb_grid(photo_path, grid_w=48)
            self.assertFalse(mostly_page_text(photo_grid["pixels"], photo_grid["w"], photo_grid["h"]))

            page = os.path.join(tmp, "ui-with-photo.png")

            def page_pixel(x: int, y: int) -> tuple[int, int, int]:
                if x >= 32 and y >= 24:
                    return (40 + (x - 32) * 4, 120, 70)
                if y % 2 == 0 and x % 2 == 0:
                    return (10, 12, 16)
                return (250, 250, 248)

            _png(page, 48, 36, page_pixel)
            found = clean_references([page, text_path, photo_path], os.path.join(tmp, "refs"))
            self.assertLessEqual(len(found), 2)
            self.assertNotIn(text_path, found)
            self.assertNotIn(page, found)
            self.assertTrue(any(path == photo_path or path.endswith(".png") for path in found))
            self.assertTrue(all(os.path.isfile(path) for path in found))


class TestPacketPrompt(unittest.TestCase):
    def test_generic_scene_is_not_sent_alone(self) -> None:
        packet = {
            "palette": [{"role": "primary", "hex": "#635bff"}, {"role": "background", "hex": "#0a2540"}],
            "imagery": "Wide blurple ribbons and soft gradient light.",
            "references": [],
        }
        prompt = prompt_with_packet("A text-free flat illustration, a simple scene, bold flat shapes", packet)
        self.assertIn("Palette:", prompt)
        self.assertIn("primary #635bff", prompt)
        self.assertIn("Wide blurple ribbons", prompt)
        self.assertNotIn("simple scene", prompt)
        with self.assertRaises(ValueError):
            prompt_with_packet("abstract flowing brand-colored shapes", {"palette": [], "imagery": ""})

    def test_structured_prompt_keeps_hexes_that_sanitizing_would_strip(self) -> None:
        packet = {
            "palette": [{"role": "primary", "hex": "#635bff"}],
            "imagery": "Wide blurple ribbons and soft gradient light.",
        }
        structured = build_structured_prompt(
            "abstract flowing brand-colored shapes",
            role="background",
            treatment="full-sheet",
            brand_packet=packet,
        )
        text = json.dumps(structured)
        self.assertIn("#635bff", text)
        self.assertIn("primary #635bff", text)
        self.assertIn("blurple ribbons", text)

    def test_generate_api_has_no_reference_image_field(self) -> None:
        note = ideogram_conditioning()
        self.assertFalse(note["generateAcceptsReferenceImage"])
        self.assertNotEqual(IDEOGRAM_GENERATE_URL, IDEOGRAM_REMIX_URL)
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"data":[]}'
        mock_resp.__enter__ = lambda _self: _self
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp) as opened:
            _call_generate_api("A field", "1280x720", api_key="test-key", rendering_speed="default")
        request = opened.call_args[0][0]
        self.assertEqual(request.full_url, IDEOGRAM_GENERATE_URL)
        self.assertNotIn("remix", request.full_url)
        body = json.loads(request.data.decode("utf-8"))
        self.assertNotIn("image", body)
        self.assertNotIn("images", body)
        self.assertNotIn("style_reference_images", body)
        self.assertEqual(body["prompt"], "A field")


class TestPosterUsesPacket(unittest.TestCase):
    def test_prompt_includes_palette_and_judge_uses_the_same_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            photo = os.path.join(tmp, "photo.png")
            _png(photo, 32, 24, lambda x, y: (20 + x, 90, 140))
            packet = build_ideogram_packet(
                {
                    "imageryStyle": {"ideogramPrompt": "Sunlit interiors and warm timber."},
                    "palette": [{"role": "primary", "hex": "#ff5a5f"}, {"role": "text", "hex": "#484848"}],
                },
                image_paths=[photo],
                screenshots_skipped=False,
                out_dir=tmp,
            )
            self.assertEqual(packet["imagery"], "Sunlit interiors and warm timber.")
            self.assertEqual(packet["references"], [photo])
            self.assertFalse(packet["referenceImageSent"])
            kit = {"siteName": "Airbnb", "colors": ["#ff5a5f"], "ideogramPacket": packet}
            profile = {"ideogramPacket": packet}

            def generate(prompt: str):
                self.assertIn("Palette:", prompt)
                self.assertIn("#ff5a5f", prompt)
                self.assertIn("Sunlit interiors", prompt)
                self.assertNotEqual(prompt.strip(), "A text-free photograph of a simple sunlit interior, warm materials")
                return "generated/assets/photo.png", b"\x89PNG\r\n\x1a\nhello", {}

            result = acquire_poster_picture(
                {"layoutTemplate": "photo-block", "heroStrategy": "solid", "heroImagePrompt": ""},
                kit,
                profile,
                template="photo-block",
                key_set=True,
                generate=generate,
            )
            self.assertTrue(result["ideogramUsed"])
            self.assertEqual(picture_references(kit, tmp, packet=packet), [photo])

    def test_missing_playwright_status_says_colours_only(self) -> None:
        packet = build_ideogram_packet(
            {"imageryStyle": {"ideogramPrompt": "This line must not be used without screenshots."}, "palette": [{"role": "primary", "hex": "#111111"}]},
            screenshots_skipped=True,
        )
        self.assertEqual(packet["imagery"], "")
        self.assertEqual(packet["references"], [])
        self.assertTrue(packet["coloursOnly"])
        self.assertEqual(packet["statusLine"], SCREENSHOTS_SKIPPED_STATUS)
        line = poster_status_line(
            template="full-bleed-scrim",
            ideogram_used=True,
            error=None,
            treatment="full-sheet",
            screenshots_skipped=True,
        )
        self.assertIn(SCREENSHOTS_SKIPPED_STATUS, line)


class TestBrandPassPacket(unittest.TestCase):
    def test_analyze_brand_records_skipped_screenshots(self) -> None:
        import brand_profile as bp

        def no_browser(*_args, **_kwargs):
            return {"available": False, "reason": "playwright not installed", "screenshots": {}}

        env = {k: v for k, v in os.environ.items() if "API_KEY" not in k and k != "COMMMAKER_LLM_PROVIDER"}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, env, clear=True):
            result = bp.analyze_brand(
                "https://example.com",
                cache_dir=tmp,
                kit={"siteName": "Example", "colors": ["#2255aa", "#ffffff"], "fonts": ["Inter"]},
                capture_fn=no_browser,
                refresh=True,
            )
        packet = result["ideogramPacket"]
        self.assertTrue(packet["screenshotsSkipped"])
        self.assertEqual(packet["imagery"], "")
        self.assertEqual(packet["references"], [])
        self.assertTrue(packet["palette"])
        self.assertEqual(result["statusLine"], SCREENSHOTS_SKIPPED_STATUS)
        self.assertIn("role", packet["palette"][0])
        self.assertTrue(packet["palette"][0]["hex"].startswith("#"))
