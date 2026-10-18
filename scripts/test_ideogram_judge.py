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
    retry_prompt,
    review_generated_picture,
)
from render_poster_samples import write_png  # noqa: E402


def _fixture_png(folder: str, name: str = "picture.png") -> str:
    path = os.path.join(folder, name)
    row = b"\x4b\xc8\x00" * 8
    write_png(path, 8, 8, [row] * 8)
    return path


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
