#!/usr/bin/env python3
"""Picture judge: one vision check, at most one regeneration. No live Ideogram."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from ideogram_judge import (  # noqa: E402
    JUDGE_JSON_SCHEMA,
    fetch_picture_layer,
    poster_status_line,
    retry_prompt,
    review_generated_picture,
)
from poster_compiler import compile_poster_batch  # noqa: E402
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
        pictures = [item for item in batch["placements"] if item.get("name") == "Picture"]
        self.assertEqual(len(pictures), 1)
        self.assertTrue(pictures[0]["path"].endswith("duo-illustration.png"))

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

    def test_fail_regenerates_once_with_the_critique(self) -> None:
        seen = {}

        def llm(_path, refs, palette, note):
            seen["refs"] = refs
            seen["palette"] = palette
            seen["calls"] = seen.get("calls", 0) + 1
            return {
                "passed": False,
                "reason": "Flat empty disc, no subject.",
                "critique": "Show a green character in a simple scene instead of a disc.",
            }

        def regen(prompt):
            seen["prompt"] = prompt
            return "generated/assets/layer-ideogram-background-retry.png", b"png", {"source": "ideogram-4"}

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
        self.assertEqual(result["imagePath"], "generated/assets/layer-ideogram-background-retry.png")
        self.assertEqual(result["reason"], "Flat empty disc, no subject.")
        self.assertEqual(seen["calls"], 1)
        self.assertEqual(len(seen["refs"]), 2)
        self.assertIn("green character", seen["prompt"])
        self.assertIn("Flat empty disc", seen["prompt"])
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


if __name__ == "__main__":
    unittest.main()
