#!/usr/bin/env python3
"""Unit tests for creative brief + compiler integration."""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from creative_brief import (  # noqa: E402
    build_creative_brief,
    build_fallback_brief,
    default_model_for_provider,
    resolve_llm_model,
)
from poster_compiler import compile_poster_batch  # noqa: E402


class TestCreativeBriefFallback(unittest.TestCase):
    def test_fallback_busy_hero_uses_gradient(self) -> None:
        kit = {
            "siteName": "Acme",
            "heroBusy": True,
            "heroImageUrl": "https://example.com/hero.jpg",
            "tagline": "We build things",
        }
        crisis = {
            "crisisMessage": "Planned maintenance tonight",
            "crisisFacts": "API may be slow between 22:00–23:00 UTC.",
            "tone": "calm",
        }
        result = build_creative_brief(kit, crisis)
        self.assertEqual(result["source"], "fallback")
        brief = result["brief"]
        self.assertEqual(brief["heroStrategy"], "gradient_from_palette")
        self.assertEqual(brief["layoutRecipe"], "gradient-brand")
        headline = brief["headline"].lower()
        self.assertTrue("maintenance" in headline or "api" in headline)

    def test_fallback_photo_when_hero_available(self) -> None:
        kit = {
            "siteName": "Stripe",
            "heroImageUrl": "https://example.com/og.png",
            "tagline": "Payments",
        }
        crisis = {"crisisFacts": "Investigating elevated errors."}
        brief = build_fallback_brief(kit, crisis)
        self.assertEqual(brief["heroStrategy"], "use_kit_photo")
        self.assertEqual(brief["layoutRecipe"], "photo-hero-type")

    def test_frontier_default_not_mini(self) -> None:
        for provider in ("openai", "anthropic", "openrouter"):
            model = default_model_for_provider(provider)  # type: ignore[arg-type]
            self.assertNotIn("mini", model.lower())
            self.assertNotIn("nano", model.lower())

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}, clear=False)
    def test_default_model_sonnet_when_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("COMMMAKER_LLM_MODEL", None)
            model = resolve_llm_model("anthropic")
        self.assertEqual(model, "claude-sonnet-4-20250514")

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    @patch("creative_brief._call_llm")
    def test_llm_path_returns_model_metadata(self, mock_llm) -> None:
        mock_llm.return_value = {
            "headline": "Update",
            "subhead": "Details inside",
            "layoutRecipe": "minimal-wordmark",
            "heroStrategy": "none",
            "logoTreatment": "wordmark-white",
            "emphasis": "urgent",
            "rationale": "Minimal layout for clarity.",
        }
        result = build_creative_brief({}, {"crisisFacts": "x"})
        self.assertEqual(result["source"], "llm")
        self.assertEqual(result["model"], "gpt-4.1")
        self.assertEqual(result["provider"], "openai")
        mock_llm.assert_called_once()


class TestPosterWithBrief(unittest.TestCase):
    def test_compile_stores_brief_and_overrides_copy(self) -> None:
        fixture_path = os.path.join(SCRIPTS, "fixtures", "sample_creative_brief.json")
        with open(fixture_path, encoding="utf-8") as handle:
            brief = json.load(handle)
        kit = {
            "siteName": "Stripe",
            "colors": ["#635bff", "#0a2540"],
            "heroBusy": False,
            "heroBrandMark": False,
        }
        session = {
            "suggestedHeadline": "Old headline",
            "brief": {"facts": "Old facts line."},
        }
        batch = compile_poster_batch(
            kit,
            session,
            creative_brief=brief,
        )
        meta = batch.get("meta") or {}
        self.assertEqual(meta.get("headline"), brief["headline"])
        self.assertEqual(meta.get("tagline"), brief["subhead"])
        stored = meta.get("creativeBrief") or {}
        self.assertEqual(stored.get("layoutRecipe"), "photo-hero-type")
        self.assertFalse(meta.get("hasHero"))


if __name__ == "__main__":
    unittest.main()
