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

from ideogram_client import generate_layer_image  # noqa: E402
from ideogram_client import (  # noqa: E402
    IDEOGRAM_GENERATE_URL,
    IDEOGRAM_REMIX_URL,
    _call_generate_api,
    build_structured_prompt,
    closest_ideogram_resolution,
    ideogram_conditioning,
)
from ideogram_judge import (  # noqa: E402
    acquire_poster_picture,
    picture_references,
    poster_status_line,
    review_generated_picture,
)
from ideogram_packet import (  # noqa: E402
    SCREENSHOTS_SKIPPED_STATUS,
    build_ideogram_packet,
    choose_component_crops,
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

    def test_generate_api_uploads_one_clean_reference(self) -> None:
        note = ideogram_conditioning()
        self.assertTrue(note["generateAcceptsReferenceImage"])
        self.assertIn("ideogram-4-5", IDEOGRAM_GENERATE_URL)
        self.assertNotEqual(IDEOGRAM_GENERATE_URL, IDEOGRAM_REMIX_URL)
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"data":[]}'
        mock_resp.__enter__ = lambda _self: _self
        mock_resp.__exit__ = MagicMock(return_value=False)
        with tempfile.TemporaryDirectory() as tmp:
            photo = os.path.join(tmp, "photo.png")
            _png(photo, 32, 24, lambda x, y: (20 + x, 90, 140))
            peel = os.path.join(tmp, "peel.png")
            _png(peel, 32, 24, lambda x, y: (30, 90, 200) if x > 16 else (12, 12, 14))
            with patch("urllib.request.urlopen", return_value=mock_resp) as opened:
                _call_generate_api(
                    "A field",
                    "1200x627",
                    api_key="test-key",
                    rendering_speed="default",
                    reference_paths=[photo, peel],
                )
        request = opened.call_args[0][0]
        self.assertEqual(request.full_url, IDEOGRAM_GENERATE_URL)
        self.assertNotIn("remix", request.full_url)
        raw = request.data
        self.assertIn(b'name="prompt"', raw)
        self.assertIn(b"A field", raw)
        self.assertIn(b'name="size"', raw)
        self.assertIn(b"1440x720", raw)
        self.assertNotIn(b"1280x720", raw)
        self.assertEqual(raw.count(b'name="images"'), 2)
        self.assertIn(b"photo.png", raw)
        self.assertIn(b"peel.png", raw)
        self.assertIn(b'name="num_images"', raw)
        self.assertNotIn(b"style_reference_images", raw)
        self.assertNotIn(b"remix", request.full_url.encode())

    def test_4_5_request_uses_a_documented_size_and_skips_svg(self) -> None:
        import io
        import urllib.error

        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"data":[]}'
        mock_resp.__enter__ = lambda _self: _self
        mock_resp.__exit__ = MagicMock(return_value=False)
        with tempfile.TemporaryDirectory() as tmp:
            svg = os.path.join(tmp, "logo.svg")
            with open(svg, "w", encoding="utf-8") as handle:
                handle.write('<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0h10v10z"/></svg>')
            with patch("urllib.request.urlopen", return_value=mock_resp) as opened:
                _call_generate_api(
                    "A field",
                    "1280x720",
                    api_key="test-key",
                    rendering_speed="default",
                    reference_paths=[svg],
                )
        raw = opened.call_args[0][0].data
        self.assertIn(b"1440x720", raw)
        self.assertNotIn(b"1280x720", raw)
        self.assertNotIn(b"<svg", raw)
        self.assertNotIn(b"image/svg", raw)
        self.assertIn(b"1024x1024", closest_ideogram_resolution("1024x1024").encode())
        err = urllib.error.HTTPError(
            IDEOGRAM_GENERATE_URL,
            400,
            "Bad Request",
            hdrs=None,
            fp=io.BytesIO(b'{"error":"Invalid input"}'),
        )
        with patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(ValueError) as caught:
                _call_generate_api("A field", "1440x720", api_key="test-key", rendering_speed="default")
        self.assertIn("Invalid input", str(caught.exception))
        self.assertNotIn("HTTP Error 400", str(caught.exception))


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
            self.assertTrue(packet["referenceImageSent"])
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


class TestComponentCrops(unittest.TestCase):
    def test_vision_picks_graphic_crops_and_skips_page_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            text_path = os.path.join(tmp, "ui.png")
            ship = os.path.join(tmp, "ship.png")
            peel = os.path.join(tmp, "peel.png")
            _png(
                text_path,
                48,
                36,
                lambda x, y: (16, 16, 16) if y % 2 == 0 and x % 2 == 0 else (248, 248, 246),
            )
            _png(ship, 48, 36, lambda x, y: (18, 18, 20) if y < 14 or y > 28 else (210, 210, 214))
            _png(peel, 48, 36, lambda x, y: (24, 92, 214) if x > 24 and y > 16 else (12, 12, 14))

            def vision(paths: list[str]) -> list[str]:
                self.assertNotIn(text_path, paths)
                return [ship, peel]

            chosen = choose_component_crops([text_path, ship, peel], vision_fn=vision)
            self.assertEqual(chosen, [ship, peel])

    def test_crop_is_uploaded_again_when_a_black_triangle_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            crop = os.path.join(tmp, "ship.png")
            peel = os.path.join(tmp, "peel.png")
            poster = os.path.join(tmp, "poster.png")
            _png(crop, 32, 24, lambda x, y: (20, 20, 22))
            _png(peel, 32, 24, lambda x, y: (24, 90, 210) if x > 16 else (10, 10, 12))
            _png(poster, 32, 24, lambda _x, _y: (0, 0, 0))
            packet = {
                "palette": [{"role": "primary", "hex": "#111111"}],
                "imagery": "A hanging corrugated container on a black field.",
                "references": [crop, peel],
            }
            calls: list[list[str]] = []

            def fake_api(prompt: str, _size: str, **kwargs):
                calls.append(list(kwargs.get("reference_paths") or []))
                self.assertIn("how this brand's components are built", prompt)
                self.assertIn("one coherent text-free asset", prompt)
                self.assertIn("Do not paste the examples together", prompt)
                self.assertIn("Do not copy the words in the examples", prompt)
                return {"data": [{"url": "https://cdn.example/x.png", "is_image_safe": True}]}

            with patch("ideogram_client._download_image", return_value=b"\x89PNG\r\n\x1a\n"), patch(
                "ideogram_client._call_generate_api", side_effect=fake_api
            ):
                generate_layer_image(
                    "A black triangle",
                    "background",
                    "1200x627",
                    assets_dir=tmp,
                    api_key="test-key",
                    treatment="quiet-type",
                    brand_packet=packet,
                )
                generate_layer_image(
                    "A black triangle. The previous image failed: generic black triangle.",
                    "background",
                    "1200x627",
                    assets_dir=tmp,
                    api_key="test-key",
                    treatment="quiet-type",
                    brand_packet=packet,
                )
            self.assertEqual(calls, [[crop, peel], [crop, peel]])

            seen: list[str] = []

            def llm(_image, refs, _palette, _note):
                self.assertEqual(refs, [crop, peel])
                if not seen:
                    return {
                        "passed": False,
                        "reason": "generic black triangle",
                        "critique": "Use the shipping container, not a triangle.",
                        "suggestedTreatment": "same",
                    }
                return {"passed": True, "reason": "matches the crop", "critique": "", "suggestedTreatment": "same"}

            def regenerate(prompt: str):
                seen.append(prompt)
                return poster, b"\x89PNG\r\n\x1a\n", {}

            judged = review_generated_picture(
                poster,
                "Make a new text-free asset in this visual language. Do not copy the words in the examples.",
                reference_paths=[crop, peel],
                llm_fn=llm,
                regenerate=regenerate,
                palette=["primary #111111"],
            )
            self.assertTrue(judged["retried"])
            self.assertTrue(judged["passed"])
            self.assertIn("Do not copy the words in the examples", seen[0])
            self.assertIn("black triangle", seen[0])
