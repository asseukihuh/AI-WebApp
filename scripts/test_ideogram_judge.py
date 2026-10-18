#!/usr/bin/env python3
"""Picture judge: one vision check, at most one regeneration. No live Ideogram."""

from __future__ import annotations

import functools
import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from unittest.mock import patch

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from ideogram_client import treatment_spec  # noqa: E402
from ideogram_judge import (  # noqa: E402
    MAX_IDEOGRAM_ATTEMPTS,
    JUDGE_JSON_SCHEMA,
    acquire_poster_picture,
    fetch_picture_layer,
    frame_fill_report,
    judge_real_png,
    poster_status_line,
    retry_prompt,
    review_generated_picture,
)
from poster_compiler import LINKEDIN_HEIGHT, LINKEDIN_WIDTH, compile_poster_batch, cover_scale_percent  # noqa: E402
from render_poster_samples import write_png  # noqa: E402


def _fixture_png(folder: str, name: str = "picture.png") -> str:
    path = os.path.join(folder, name)
    row = b"\x4b\xc8\x00" * 8
    write_png(path, 8, 8, [row] * 8)
    return path


def _circle_brief() -> dict:
    return {
        "headline": "Learn a language in five minutes daily",
        "subhead": "Free lessons, no textbook required.",
        "cta": "Learn more",
        "layoutRecipe": "photo-hero-type",
        "heroStrategy": "ideogram_generate",
        "logoTreatment": "wordmark-dark",
        "layoutTemplate": "circle-stage",
        "headlineScale": "lg",
        "ctaStyle": "pill",
        "composition": {
            "textRegion": "left",
            "visuals": [],
            "colourBlock": "none",
            "field": "ideogram",
            "showCta": True,
            "offer": "",
            "proof": "",
        },
    }


class TestCircleBitmap(unittest.TestCase):
    def test_key_set_and_bitmap_returned_has_no_solid_ellipse(self) -> None:
        png = b"\x89PNG\r\n\x1a\n" + b"not-empty"

        def generate(_prompt):
            return "generated/assets/duo-illustration.png", png, {"source": "ideogram-4"}

        fetched = fetch_picture_layer(
            "A text-free flat illustration of a simple green character.",
            key_set=True,
            generate=generate,
        )
        self.assertIsNone(fetched["error"])
        self.assertEqual(fetched["path"], "generated/assets/duo-illustration.png")
        grid = {"w": 2, "h": 2, "src_w": 640, "src_h": 640, "pixels": [(120, 200, 0)] * 4}
        batch = compile_poster_batch(
            {"siteName": "Duolingo", "colors": ["#78c800", "#1cb0f6", "#ffffff"]},
            {"suggestedHeadline": "Learn a language in five minutes daily", "brief": {"facts": "Free lessons."}},
            creative_brief=_circle_brief(),
            hero_relative_path=fetched["path"],
            hero_width=640,
            hero_height=640,
            hero_grid=grid,
            logo_relative_path="generated/assets/duo.png",
            logo_variants={"original": "generated/assets/duo.png"},
            logo_width=180,
            logo_height=180,
        )
        names = [step.get("params", {}).get("name") for step in batch["steps"]]
        self.assertNotIn("Illustration plate", names)
        pictures = [item for item in batch.get("backgroundPlacements") or [] if "duo-illustration" in item.get("path", "")]
        self.assertEqual(len(pictures), 1)
        self.assertEqual(pictures[0]["center"], [LINKEDIN_WIDTH / 2, LINKEDIN_HEIGHT / 2])
        self.assertNotIn("Picture", [item.get("name") for item in batch["placements"]])

    def test_key_set_and_api_error_is_on_the_status_line(self) -> None:
        def generate(_prompt):
            raise RuntimeError("HTTP 401 invalid API key")

        fetched = fetch_picture_layer("A flat illustration.", key_set=True, generate=generate)
        self.assertIn("HTTP 401 invalid API key", fetched["error"])
        line = poster_status_line(
            template="circle-stage",
            ideogram_used=False,
            error=fetched["error"],
            score=94,
        )
        self.assertIn("circle-stage", line)
        self.assertIn("HTTP 401 invalid API key", line)
        self.assertIn("Ideogram failed", line)

    def test_key_missing_allows_the_ellipse(self) -> None:
        fetched = fetch_picture_layer("A flat illustration.", key_set=False, generate=lambda _p: ("x", b"y", {}))
        self.assertTrue(fetched["keyMissing"])
        self.assertIsNone(fetched["error"])
        batch = compile_poster_batch(
            {"siteName": "Duolingo", "colors": ["#1cb0f6", "#ffffff"]},
            {"suggestedHeadline": "Learn a language in five minutes daily", "brief": {"facts": "Free lessons."}},
            creative_brief={**_circle_brief(), "heroStrategy": "solid"},
            logo_relative_path="generated/assets/duo.png",
            logo_variants={"original": "generated/assets/duo.png"},
            logo_width=180,
            logo_height=180,
        )
        names = [step.get("params", {}).get("name") for step in batch["steps"]]
        self.assertIn("Illustration plate", names)


class TestPictureJudge(unittest.TestCase):
    def test_schema_is_strict(self) -> None:
        self.assertFalse(JUDGE_JSON_SCHEMA["additionalProperties"])
        self.assertEqual(
            set(JUDGE_JSON_SCHEMA["required"]),
            set(JUDGE_JSON_SCHEMA["properties"]),
        )

    def test_pass_does_not_regenerate(self) -> None:
        calls = {"llm": 0, "regen": 0}

        def llm(_path, _refs, _palette, _note):
            calls["llm"] += 1
            return {"passed": True, "reason": "One green character in a simple scene.", "critique": ""}

        def regen(_prompt):
            calls["regen"] += 1
            return "generated/assets/second.png", b"", {}

        with tempfile.TemporaryDirectory() as folder:
            picture = _fixture_png(folder)
            result = review_generated_picture(
                picture,
                "A text-free flat illustration of a simple green character.",
                llm_fn=llm,
                regenerate=regen,
            )
        self.assertTrue(result["passed"])
        self.assertFalse(result["retried"])
        self.assertIsNone(result["imagePath"])
        self.assertEqual(calls, {"llm": 1, "regen": 0})

    def test_fail_regenerates_twice_then_places_the_last(self) -> None:
        seen = {"calls": 0, "regen": 0}

        def llm(_path, refs, palette, note):
            seen["refs"] = refs
            seen["palette"] = palette
            seen["calls"] += 1
            return {
                "passed": False,
                "reason": "Flat empty disc, no subject.",
                "critique": "Show a green character in a simple scene instead of a disc.",
            }

        def regen(prompt):
            seen["regen"] += 1
            seen["prompt"] = prompt
            return f"generated/assets/retry-{seen['regen']}.png", b"png", {"source": "ideogram-4"}

        with tempfile.TemporaryDirectory() as folder:
            picture = _fixture_png(folder)
            logo = _fixture_png(folder, "logo.png")
            result = review_generated_picture(
                picture,
                "A text-free flat illustration.",
                reference_paths=[logo, logo, logo],
                palette=["#78c800", "#ffffff"],
                llm_fn=llm,
                regenerate=regen,
            )
        self.assertFalse(result["passed"])
        self.assertTrue(result["retried"])
        self.assertEqual(result["attempts"], 3)
        self.assertEqual(result["imagePath"], "generated/assets/retry-2.png")
        self.assertEqual(result["reason"], "Flat empty disc, no subject.")
        self.assertEqual(seen["calls"], 3)
        self.assertEqual(seen["regen"], 2)
        self.assertEqual(len(seen["refs"]), 2)
        self.assertIn("green character", seen["prompt"])
        self.assertIn("Flat empty disc", seen["prompt"])
        self.assertIn("Fill the frame", seen["prompt"])
        self.assertNotIn("circle", retry_prompt("scene", "disc", "show a character").casefold())

    @patch("ideogram_judge.resolve_llm_provider", return_value=None)
    def test_no_key_skips_without_a_retry(self, _provider) -> None:
        def regen(_prompt):
            raise AssertionError("regenerate should not run")

        with tempfile.TemporaryDirectory() as folder:
            picture = _fixture_png(folder)
            result = review_generated_picture(picture, "scene", regenerate=regen)
        self.assertTrue(result["skipped"])
        self.assertIsNone(result["passed"])
        self.assertFalse(result["retried"])
        self.assertIn("no model key", result["reason"])


def _save_rgb(path: str, width: int, height: int, color_at) -> str:
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            row.extend(color_at(x, y))
        rows.append(bytes(row))
    write_png(path, width, height, rows)
    return path


class TestPictureFill(unittest.TestCase):
    def test_worst_case_is_three_ideogram_calls(self) -> None:
        self.assertEqual(MAX_IDEOGRAM_ATTEMPTS, 3)

    def test_too_small_fixture_fails_and_a_full_frame_passes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            small = _save_rgb(
                os.path.join(folder, "small.png"),
                80,
                80,
                lambda x, y: (88, 204, 2) if 36 <= x < 44 and 36 <= y < 44 else (255, 255, 255),
            )
            full = _save_rgb(
                os.path.join(folder, "full.png"),
                80,
                80,
                lambda x, y: (28, 176, 246) if y < 40 else (88, 204, 2),
            )
            inset = frame_fill_report(small)
            filled = frame_fill_report(full)
        self.assertIsNotNone(inset)
        self.assertIsNotNone(filled)
        self.assertFalse(inset["passed"])
        self.assertTrue("inset" in inset["reason"] or "cramped" in inset["reason"])
        self.assertTrue(filled["passed"])

    def test_tiny_image_is_not_returned_as_a_pass(self) -> None:
        seen = {"regen": 0}

        def llm(_path, _refs, _palette, _note):
            return {"passed": True, "reason": "Looks fine.", "critique": ""}

        with tempfile.TemporaryDirectory() as folder:
            small = _save_rgb(
                os.path.join(folder, "small.png"),
                80,
                80,
                lambda x, y: (88, 204, 2) if 36 <= x < 44 and 36 <= y < 44 else (255, 255, 255),
            )
            full = _save_rgb(
                os.path.join(folder, "full.png"),
                80,
                80,
                lambda x, y: (28, 176, 246) if y < 40 else (88, 204, 2),
            )

            def regen(_prompt):
                seen["regen"] += 1
                return full, b"png", {}

            result = review_generated_picture(
                small,
                "A text-free character.",
                llm_fn=llm,
                regenerate=regen,
                region=(0, 0, 1200, 627),
                repo_root=folder,
            )
        self.assertTrue(result["passed"])
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(result["imagePath"], full)
        self.assertEqual(seen["regen"], 1)
        self.assertNotEqual(result["imagePath"], small)

    def test_circle_stage_bitmap_covers_the_canvas_not_a_well(self) -> None:
        sheet = treatment_spec("illustration-cluster")
        self.assertEqual(sheet["resolution"], "1280x720")
        self.assertEqual(sheet["aspect"], "16:9")
        self.assertEqual(sheet["zone"], "center")
        self.assertIn("centre", sheet["quiet"].casefold())
        self.assertNotIn("circle", sheet["fill"].casefold())
        batch = compile_poster_batch(
            {"siteName": "Duolingo", "colors": ["#58cc02", "#1cb0f6", "#ffffff"]},
            {"suggestedHeadline": "Learn a language in five minutes daily", "brief": {"facts": "Free lessons."}},
            creative_brief=_circle_brief(),
            hero_relative_path="generated/assets/duo-illustration.png",
            hero_width=180,
            hero_height=180,
            hero_grid={"w": 2, "h": 2, "src_w": 180, "src_h": 180, "pixels": [(88, 204, 2)] * 4},
            logo_relative_path="generated/assets/duo.png",
            logo_variants={"original": "generated/assets/duo.png"},
            logo_width=180,
            logo_height=180,
        )
        picture = next(
            item for item in batch["backgroundPlacements"] if item.get("path", "").endswith("duo-illustration.png")
        )
        self.assertFalse(picture["fit"])
        self.assertEqual(picture["center"], [LINKEDIN_WIDTH / 2, LINKEDIN_HEIGHT / 2])
        self.assertEqual(picture["scale"], round(cover_scale_percent(180, 180), 2))
        self.assertGreaterEqual(180 * picture["scale"] / 100, LINKEDIN_WIDTH)
        headline = next(step for step in batch["steps"] if step.get("params", {}).get("name") == "Headline")
        box = headline["params"]["box"]
        self.assertAlmostEqual(box[0] + box[2] / 2, LINKEDIN_WIDTH / 2, delta=30)
        self.assertEqual(headline["params"]["align"], "center")
        self.assertGreaterEqual(headline["params"]["size"], 54)
        self.assertNotIn("Illustration plate", [step.get("params", {}).get("name") for step in batch["steps"]])
        line = poster_status_line(
            template="circle-stage",
            ideogram_used=True,
            error=None,
            ideogram_ms=212,
            judge={"passed": False, "reason": "The picture is a small inset on an empty field.", "attempts": 3},
        )
        self.assertIn("judge fail", line)
        self.assertIn("small inset", line)
        self.assertIn("3 attempts", line)

    def test_quiet_type_is_sent_to_ideogram(self) -> None:
        kit, profile = _duo()
        seen: list[str] = []

        def generate(prompt: str):
            seen.append(prompt)
            return "generated/assets/quiet-field.png", PNG, {"source": "ideogram-4.5"}

        result = acquire_poster_picture(
            {"layoutTemplate": "centered-statement", "heroStrategy": "solid", "treatment": "quiet-type"},
            kit,
            profile,
            template="centered-statement",
            key_set=True,
            generate=generate,
        )
        self.assertTrue(result["called"])
        self.assertTrue(result["ideogramUsed"])
        self.assertIn("text-free asset in this visual language", seen[0])
        self.assertIn("Do not copy the words in the crop", seen[0])
        line = poster_status_line(
            template="centered-statement",
            ideogram_used=True,
            error=None,
            treatment="quiet-type",
            ideogram_ms=result["ideogramMs"],
            judge={"passed": True, "reason": "Matches the crop.", "attempts": 1},
        )
        self.assertIn("quiet-type", line)
        self.assertIn("judge pass", line)

    def test_photo_band_does_not_cover_the_whole_canvas(self) -> None:
        band = treatment_spec("photo-band")
        self.assertNotEqual(band["resolution"], "1280x720")
        batch = compile_poster_batch(
            {"siteName": "Airbnb", "colors": ["#e61e4d", "#ffffff"]},
            {"suggestedHeadline": "Stay somewhere new", "brief": {"facts": "Homes with a kitchen."}},
            creative_brief={
                **_circle_brief(),
                "layoutTemplate": "photo-block",
                "treatment": "photo-band",
                "headline": "Stay somewhere new",
            },
            hero_relative_path="generated/assets/photo.png",
            hero_width=1536,
            hero_height=512,
            hero_grid={"w": 2, "h": 2, "src_w": 1536, "src_h": 512, "pixels": [(230, 180, 140)] * 4},
        )
        picture = next(item for item in batch["backgroundPlacements"] if item.get("path", "").endswith("photo.png"))
        self.assertLess(picture["center"][1], 250)
        self.assertNotEqual(picture["center"][1], LINKEDIN_HEIGHT / 2)
        displayed_h = 512 * picture["scale"] / 100
        self.assertLess(displayed_h, LINKEDIN_HEIGHT - 40)

    def test_failed_treatment_retries_quiet_type_with_the_crop(self) -> None:
        calls = {"n": 0}

        def llm(_path, _refs, _palette, _note):
            calls["n"] += 1
            if calls["n"] == 1:
                return {
                    "passed": False,
                    "reason": "full-bleed was wrong for this brand.",
                    "critique": "Use a quiet type poster.",
                    "suggestedTreatment": "quiet-type",
                }
            return {"passed": True, "reason": "Matches the crop.", "critique": "", "suggestedTreatment": "same"}

        seen: list[str] = []

        def regen(prompt: str):
            seen.append(prompt)
            return picture, b"\x89PNG\r\n\x1a\n", {}

        with tempfile.TemporaryDirectory() as folder:
            picture = _save_rgb(
                os.path.join(folder, "full.png"),
                80,
                80,
                lambda x, y: (28, 176, 246) if y < 40 else (88, 204, 2),
            )
            result = review_generated_picture(
                picture,
                "A full-bleed scene.",
                reference_paths=[picture],
                llm_fn=llm,
                regenerate=regen,
                treatment="full-sheet",
            )
        self.assertTrue(result["passed"])
        self.assertFalse(result["dropImage"])
        self.assertEqual(result["treatment"], "quiet-type")
        self.assertTrue(seen)
        self.assertIn("Do not copy the words in the crop", seen[0])
        self.assertIn("quiet-type", seen[0])


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24

PICTURE_FRAMES = (
    "circle-stage",
    "photo-block",
    "photo-card",
    "character-scene",
    "product-card",
    "product-ui",
    "full-bleed-scrim",
    "split-text-left",
    "text-panel",
)


def _duo():
    return (
        {"siteName": "Duolingo", "colors": ["#58cc02", "#1cb0f6", "#ffffff"]},
        {"imageryStyle": {"primaryMedium": "illustration", "motifs": ["mascot"]}},
    )


class TestPictureFrameMustPost(unittest.TestCase):
    def test_solid_brief_with_empty_prompt_still_invokes_the_client(self) -> None:
        """Old skip: heroStrategy == ideogram_generate and a non-empty prompt."""
        kit, profile = _duo()
        invoked: list[str] = []

        def generate(prompt: str):
            invoked.append(prompt)
            return "generated/assets/duo-illustration.png", PNG, {"source": "ideogram-4"}

        result = acquire_poster_picture(
            {"layoutTemplate": "circle-stage", "heroStrategy": "solid", "heroImagePrompt": ""},
            kit,
            profile,
            template="circle-stage",
            key_set=True,
            generate=generate,
        )
        self.assertTrue(invoked, "picture frame returned without invoking the Ideogram client")
        self.assertTrue(result["ideogramUsed"])
        self.assertIsNone(result["ideogramError"])
        self.assertIsInstance(result["ideogramMs"], int)
        self.assertNotIn("circle", invoked[0].casefold())
        grid = {"w": 2, "h": 2, "src_w": 640, "src_h": 640, "pixels": [(88, 204, 2)] * 4}
        batch = compile_poster_batch(
            kit,
            {"suggestedHeadline": "Learn a language in five minutes a day", "brief": {"facts": "Free lessons."}},
            creative_brief=result["brief"],
            hero_relative_path=result["path"],
            hero_width=640,
            hero_height=640,
            hero_grid=grid,
            logo_relative_path="generated/assets/duo.png",
            logo_variants={"original": "generated/assets/duo.png"},
            logo_width=180,
            logo_height=180,
        )
        names = [step.get("params", {}).get("name") for step in batch["steps"]]
        self.assertNotIn("Illustration plate", names)
        pictures = [
            item for item in batch.get("backgroundPlacements") or [] if item.get("path", "").endswith("duo-illustration.png")
        ]
        self.assertEqual(len(pictures), 1)
        self.assertEqual(pictures[0]["center"], [LINKEDIN_WIDTH / 2, LINKEDIN_HEIGHT / 2])
        self.assertNotIn("circle", invoked[0].casefold())
        self.assertIn("illustration cluster", invoked[0].casefold())

    def test_every_picture_frame_invokes_a_stubbed_client(self) -> None:
        kit, profile = _duo()
        for template in PICTURE_FRAMES:
            invoked: list[str] = []

            def generate(prompt: str, _invoked: list[str] = invoked, _template: str = template):
                _invoked.append(prompt)
                return f"generated/assets/{_template}.png", PNG, {"source": "ideogram-4"}

            result = acquire_poster_picture(
                {"layoutTemplate": template, "heroStrategy": "gradient_from_palette", "heroImagePrompt": ""},
                kit,
                profile,
                template=template,
                key_set=True,
                generate=generate,
            )
            self.assertTrue(invoked, f"{template} returned without invoking the Ideogram client")
            self.assertTrue(result["ideogramUsed"], template)
            self.assertIsNone(result["ideogramError"], template)

    def test_skip_without_a_key_says_why_and_costs_zero_ms(self) -> None:
        kit, profile = _duo()

        def generate(_prompt: str):
            raise AssertionError("Ideogram client must not be called")

        result = acquire_poster_picture(
            {"layoutTemplate": "circle-stage", "heroStrategy": "ideogram_generate", "heroImagePrompt": "A character"},
            kit,
            profile,
            template="circle-stage",
            key_set=False,
            generate=generate,
        )
        self.assertFalse(result["called"])
        self.assertFalse(result["ideogramUsed"])
        self.assertEqual(result["ideogramMs"], 0)
        self.assertIn("IDEOGRAM_API_KEY not set", result["ideogramError"])
        line = poster_status_line(
            template="circle-stage",
            ideogram_used=False,
            error=result["ideogramError"],
            ideogram_ms=result["ideogramMs"],
            score=94,
        )
        self.assertIn("IDEOGRAM_API_KEY not set", line)
        self.assertIn("0 ms", line)
        self.assertNotIn("Ideogram ·", line)

    def test_quiet_type_still_calls_ideogram(self) -> None:
        kit, profile = _duo()
        seen: list[str] = []

        def generate(prompt: str):
            seen.append(prompt)
            return "generated/assets/vercel-field.png", PNG, {"source": "ideogram-4.5"}

        result = acquire_poster_picture(
            {"layoutTemplate": "mark-stage", "heroStrategy": "solid", "heroImagePrompt": ""},
            kit,
            profile,
            template="mark-stage",
            key_set=True,
            generate=generate,
        )
        self.assertTrue(result["called"])
        self.assertTrue(result["ideogramUsed"])
        self.assertEqual(result["brief"]["heroStrategy"], "ideogram_generate")
        self.assertEqual(result["brief"]["layoutRecipe"], "photo-hero-type")
        self.assertIn("text-free asset in this visual language", seen[0])
        self.assertIn("Do not copy the words in the crop", seen[0])

    def test_empty_image_is_not_a_judge_pass(self) -> None:
        kit, profile = _duo()

        def generate(_prompt: str):
            return "generated/assets/empty.png", b"", {"source": "ideogram-4"}

        result = acquire_poster_picture(
            {"layoutTemplate": "circle-stage", "heroStrategy": "solid"},
            kit,
            profile,
            template="circle-stage",
            key_set=True,
            generate=generate,
        )
        self.assertTrue(result["called"])
        self.assertFalse(result["ideogramUsed"])
        self.assertIn("did not return a PNG", result["ideogramError"])

        def llm(*_args):
            raise AssertionError("judge must not run without a PNG")

        judged = judge_real_png(b"", "", "scene", llm_fn=llm, regenerate=lambda _p: ("x", PNG, {}))
        self.assertIsNone(judged)


def _load_server():
    path = os.path.join(SCRIPTS, "serve-static.py")
    spec = importlib.util.spec_from_file_location("serve_static_force_ideogram", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load serve-static.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _poster_body() -> dict:
    return {
        "kit": {
            "siteName": "Duolingo",
            "colors": ["#58cc02", "#1cb0f6", "#ffffff"],
            "communicationKit": {"devices": [{"kind": "mascot"}], "bundled": True},
        },
        "session": {
            "suggestedHeadline": "Learn a language",
            "brief": {"facts": "Free lessons, no textbook.", "tone": "factual"},
        },
        "creativeBrief": {
            "headline": "Learn a language",
            "subhead": "The most fun way to learn languages, chess, and more.",
            "cta": "Learn more",
            "layoutTemplate": "circle-stage",
            "heroStrategy": "solid",
            "heroImagePrompt": "",
            "layoutRecipe": "minimal-wordmark",
            "logoTreatment": "wordmark-dark",
            "ctaStyle": "pill",
            "composition": {
                "textRegion": "left",
                "visuals": [],
                "colourBlock": "none",
                "field": "ideogram",
                "showCta": True,
                "offer": "",
                "proof": "",
            },
        },
    }


class TestGeneratePosterPosts(unittest.TestCase):
    def _post(self, module, port: int) -> dict:
        raw = json.dumps(_poster_body()).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/generate-poster",
            data=raw,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def test_circle_stage_posts_before_compile_even_when_the_brief_says_solid(self) -> None:
        module = _load_server()
        order: list[str] = []

        def fake_generate(prompt, role, resolution, **_kwargs):
            order.append("ideogram")
            self.assertTrue(str(prompt).strip())
            self.assertEqual(role, "background")
            return "generated/assets/duo-illustration.png", PNG, {"source": "ideogram-4"}

        def fake_batch(*_args, **_kwargs):
            order.append("compile")
            return {"ok": True, "cliAvailable": True, "userMessage": "Poster saved.", "commandBatch": {}}

        handler = functools.partial(module.CommMakerHandler, coop_coep=False)
        httpd = module.http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        with (
            patch.object(module, "generate_layer_image", fake_generate),
            patch.object(module, "run_poster_batch", fake_batch),
            patch.object(
                module,
                "judge_real_png",
                lambda *_a, **_k: {"passed": True, "reason": "One character in a scene.", "retried": False},
            ),
            patch.dict(os.environ, {"IDEOGRAM_API_KEY": "test-key"}),
        ):
            thread.start()
            try:
                payload = self._post(module, httpd.server_address[1])
            finally:
                httpd.shutdown()
                thread.join(timeout=5)
                httpd.server_close()
        self.assertTrue(order, "picture frame returned without invoking the Ideogram client")
        self.assertEqual(order[0], "ideogram")
        self.assertIn("compile", order)
        self.assertLess(order.index("ideogram"), order.index("compile"))
        self.assertTrue(payload["ideogramUsed"])
        self.assertIsNone(payload["ideogramError"])
        self.assertIsInstance(payload["ideogramMs"], int)
        self.assertIn("ms", payload["statusLine"])
        self.assertIsNotNone(payload.get("ideogramJudge"))
        self.assertTrue(payload["ideogramJudge"]["passed"])

    def test_missing_key_skips_with_zero_ms_and_does_not_claim_a_judge_pass(self) -> None:
        module = _load_server()
        calls: list[str] = []

        def fake_generate(*_args, **_kwargs):
            calls.append("ideogram")
            raise AssertionError("Ideogram client must not be called")

        def fake_batch(*_args, **_kwargs):
            return {"ok": True, "cliAvailable": True, "userMessage": "Poster saved.", "commandBatch": {}}

        handler = functools.partial(module.CommMakerHandler, coop_coep=False)
        httpd = module.http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        with (
            patch.object(module, "generate_layer_image", fake_generate),
            patch.object(module, "run_poster_batch", fake_batch),
            patch.dict(os.environ, {"IDEOGRAM_API_KEY": ""}, clear=False),
        ):
            thread.start()
            try:
                payload = self._post(module, httpd.server_address[1])
            finally:
                httpd.shutdown()
                thread.join(timeout=5)
                httpd.server_close()
        self.assertEqual(calls, [])
        self.assertFalse(payload["ideogramUsed"])
        self.assertEqual(payload["ideogramMs"], 0)
        self.assertIn("IDEOGRAM_API_KEY not set", payload["ideogramError"])
        self.assertIn("0 ms", payload["statusLine"])
        self.assertNotIn("ideogramJudge", payload)


if __name__ == "__main__":
    unittest.main()
