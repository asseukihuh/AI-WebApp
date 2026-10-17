#!/usr/bin/env python3
"""Communication kit: strict schema, thin-site design, devices, poster rules."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import communication_kit as kitlib  # noqa: E402
import poster_design as design  # noqa: E402
from creative_brief import resolve_llm_model  # noqa: E402
from poster_compiler import compile_poster_batch  # noqa: E402


def _fixture(name: str) -> dict:
    with open(os.path.join(SCRIPTS, "fixtures", name), encoding="utf-8") as handle:
        return json.load(handle)


def _schema_problems(node: object, path: str = "$") -> list[str]:
    problems = []
    if not isinstance(node, dict):
        return problems
    if node.get("type") == "object":
        if node.get("additionalProperties") is not False:
            problems.append(f"{path} missing additionalProperties: false")
        props = node.get("properties") or {}
        required = set(node.get("required") or [])
        if set(props) != required:
            problems.append(f"{path} required {sorted(required)} != properties {sorted(props)}")
        for key, child in props.items():
            problems.extend(_schema_problems(child, f"{path}.{key}"))
    if node.get("type") == "array":
        problems.extend(_schema_problems(node.get("items"), f"{path}[]"))
    return problems


def _bds() -> dict:
    return {
        "sourceUrl": "https://bds-ig2i.fr/",
        "siteName": "BDS IG2I",
        "tagline": "Bureau des Sports",
        "headline": "BDS",
        "colors": ["#1f7a3a", "#0e3b1c"],
        "fonts": ["Inter"],
        "logoSvg": "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 72'><path fill='#1f7a3a' d='M32 4l24 10v24c0 16-24 30-24 30S8 54 8 38V14z'/></svg>",
    }


class TestSchema(unittest.TestCase):
    def test_every_object_is_strict_and_fully_required(self) -> None:
        self.assertEqual(_schema_problems(kitlib.COMMUNICATION_KIT_JSON_SCHEMA), [])

    def test_anthropic_tool_is_strict(self) -> None:
        body = kitlib.anthropic_kit_body(_bds(), None, model="claude-opus-5-5")
        tool = body["tools"][0]
        self.assertTrue(tool["strict"])
        self.assertEqual(tool["input_schema"]["additionalProperties"], False)
        self.assertEqual(tool["name"], "submit_communication_kit")

    def test_brand_model_defaults_to_opus_and_briefs_stay_on_sonnet(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("COMMMAKER_BRAND_MODEL", None)
            os.environ.pop("COMMMAKER_LLM_MODEL", None)
            self.assertEqual(kitlib.resolve_brand_model("anthropic"), "claude-opus-5-5")
            self.assertEqual(resolve_llm_model("anthropic"), "claude-sonnet-5-5")
            self.assertEqual(kitlib.poster_brief_model("anthropic"), "claude-sonnet-5-5")


class TestThinSites(unittest.TestCase):
    def test_bds_is_thin_and_stripe_vercel_are_not(self) -> None:
        self.assertTrue(kitlib.is_thin_site(_bds()))
        self.assertFalse(kitlib.is_thin_site(_fixture("kit-stripe.json")))
        self.assertFalse(kitlib.is_thin_site(_fixture("kit-vercel.json")))

    def test_neutrals_and_an_app_icon_still_count_as_thin(self) -> None:
        kit = {
            "siteName": "BDS IG2I — Centrale Lille",
            "tagline": "Site officiel du Bureau des Sports, avec entrainements, adhesions et tournois etudiants.",
            "colors": ["#00733a", "#005a2d", "#ffffff", "#000000", "#1a1a1a", "#9e9e9e", "#f5f5f5"],
            "fonts": ["Inter", "Playfair Display", "Roboto"],
            "heroImageUrl": "https://bds-ig2i.fr/icons/icon-512x512.png",
            "heroImageKind": "og-marketing",
        }
        self.assertTrue(kitlib.is_thin_site(kit))
        self.assertEqual(kitlib.chromatic_colors(kit["colors"]), ["#00733a", "#005a2d"])

    def test_each_sector_gets_its_own_devices(self) -> None:
        bds = {d["kind"] for d in kitlib.design_fallback(_bds())["devices"]}
        stripe = {d["kind"] for d in kitlib.design_fallback(_fixture("kit-stripe.json"))["devices"]}
        vercel = {d["kind"] for d in kitlib.design_fallback(_fixture("kit-vercel.json"))["devices"]}
        self.assertIn("climbing-holds", bds)
        self.assertIn("mark-crop", bds)
        self.assertIn("swoosh", stripe)
        self.assertIn("stripe", stripe)
        self.assertTrue("grid-dots" in vercel or "mark-crop" in vercel)
        self.assertNotEqual(bds, stripe)
        self.assertNotEqual(stripe, vercel)
        self.assertNotEqual(bds, vercel)
        for kinds in (bds, stripe, vercel):
            self.assertGreaterEqual(len(kinds), 3)

    def test_fallback_svg_and_bezier_path(self) -> None:
        designed = kitlib.design_fallback(_bds())
        svg = kitlib.device_svg(designed["devices"][0], designed, logo_svg=_bds()["logoSvg"])
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn("fill=", svg)
        shapes = kitlib.poster_vectors(designed, template_name="device-stage", logo_svg=_bds()["logoSvg"])
        self.assertTrue(any(shape["type"] == "path" and shape.get("knots") for shape in shapes))
        steps = kitlib.shape_steps(shapes)
        self.assertTrue(
            any(
                step["params"]["kind"] == "path" and step["params"]["path"]["subpaths"][0]["knots"]
                for step in steps
            )
        )
        self.assertTrue(all(step["params"].get("kind") != "polygon" or "rect" in step["params"] for step in steps))
        self.assertTrue(all("additionalProperties" not in step for step in steps))


class TestCacheAndCost(unittest.TestCase):
    def test_cache_is_per_domain_and_cost_is_estimated(self) -> None:
        costs = kitlib.estimated_unit_costs()
        self.assertGreater(costs["kitAnalysisUsd"], 0.05)
        self.assertLess(costs["kitAnalysisUsd"], 0.25)
        self.assertEqual(costs["posterBriefModel"], "claude-sonnet-5-5")
        self.assertGreater(costs["posterWithIdeogramUsd"], costs["posterBriefUsd"])
        raw = kitlib.design_fallback(_bds())
        raw["devices"] = raw["devices"][:4]

        def llm(_kit, _profile):
            return {"raw": raw, "usage": {"inputTokens": 2000, "outputTokens": 1200}, "model": "claude-opus-5-5", "provider": "anthropic"}

        with tempfile.TemporaryDirectory() as cache:
            first = kitlib.analyze_communication_kit(_bds(), cache_dir=cache, allow_llm=True, llm_fn=llm)
            self.assertEqual(first["source"], "llm")
            self.assertEqual(first["model"], "claude-opus-5-5")
            self.assertFalse(first["cached"])
            self.assertGreater(first["costUsd"], 0)
            self.assertTrue(first["communicationKit"]["devices"][0]["svg"].startswith("<svg"))
            second = kitlib.analyze_communication_kit(_bds(), cache_dir=cache, allow_llm=True, llm_fn=llm)
            self.assertTrue(second["cached"])
            self.assertEqual(second["communicationKit"]["sector"], first["communicationKit"]["sector"])

    def test_no_key_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as cache, patch.dict(os.environ, {"ANTHROPIC_API_KEY": "", "OPENAI_API_KEY": "", "OPENROUTER_API_KEY": ""}, clear=False):
            result = kitlib.analyze_communication_kit(_bds(), cache_dir=cache, allow_llm=True)
        self.assertEqual(result["source"], "fallback")
        self.assertEqual(result["costUsd"], 0)
        self.assertTrue(result["thinSite"])


class TestPosterUsesKit(unittest.TestCase):
    def _session(self) -> dict:
        return {"suggestedHeadline": "Soiree sport", "brief": {"headline": "Soiree sport", "facts": "Vendredi 20 h au gymnase."}}

    def test_thin_kit_compiles_device_stage_and_passes_linearity(self) -> None:
        designed = kitlib.design_fallback(_bds())
        kit = {**_bds(), "communicationKit": designed}
        batch = compile_poster_batch(
            kit,
            self._session(),
            creative_brief={
                "headline": "Soiree sport",
                "subhead": "Vendredi au gymnase.",
                "cta": "Je viens",
                "eyebrow": "BDS",
                "layoutRecipe": "gradient-brand",
                "heroStrategy": "gradient_from_palette",
                "logoTreatment": "wordmark-white",
                "emphasis": "celebratory",
                "headlineScale": "xl",
                "headlineWeight": "extrabold",
                "ctaStyle": "pill",
                "rationale": "test",
            },
            logo_relative_path="generated/assets/logo.svg",
            logo_variants={"original": "generated/assets/logo.svg", "light": "generated/assets/logo-light.svg"},
            logo_width=64,
            logo_height=72,
        )
        meta = batch["meta"]
        self.assertEqual(meta["layoutTemplate"], "device-stage")
        names = [step["params"].get("name") for step in batch["steps"]]
        self.assertTrue(any(str(name).startswith("Device ") for name in names), names)
        self.assertIn("Colour block", names)
        self.assertEqual(meta["designAudit"]["failed"], [])
        self.assertGreaterEqual(meta["designAudit"]["score"], 90)
        self.assertGreaterEqual(meta["logoLayout"]["targetHeightPx"], 48)
        for rule in ("focal-point", "hook", "scale-contrast", "asymmetry", "layered-depth", "colour-blocking", "thumbnail", "logo-size"):
            self.assertIn(rule, {c["rule"] for c in meta["designAudit"]["checks"]})

    def test_tiny_logo_fails_logo_size(self) -> None:
        plan = design.plan_layout("full-bleed-scrim", headline="Big hook here", subline="A short detail line.", cta="Read more", logo_size=(20, 12))
        audit = design.audit_plan(plan, contrast={"headline": 7, "subline": 7, "logo": 5})
        self.assertIn("logo-size", audit["failed"])


if __name__ == "__main__":
    unittest.main()
