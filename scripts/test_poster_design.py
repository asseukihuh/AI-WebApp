#!/usr/bin/env python3
"""Tests for the poster design system (docs/poster-design-system.md)."""

from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
import unittest
import zlib
from unittest.mock import MagicMock, patch

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import poster_design as design  # noqa: E402
from creative_brief import (  # noqa: E402
    _apply_art_director_patch,
    art_director_review,
    build_fallback_brief,
)
from ideogram_client import (  # noqa: E402
    brand_terms_from_kit,
    build_structured_prompt,
    generate_layer_image,
    sanitize_scene_description,
)
from image_luma import _grid_from_png  # noqa: E402
from poster_compiler import compile_poster_batch, logo_svg_variants  # noqa: E402


def _fixture(name: str) -> dict:
    with open(os.path.join(SCRIPTS, "fixtures", name), encoding="utf-8") as handle:
        return json.load(handle)


def _session() -> dict:
    return {
        "suggestedHeadline": "New pricing plan for students",
        "brief": {"headline": "New pricing plan for students", "facts": "Reduced fees.\n"},
    }


def _brief(**overrides) -> dict:
    brief = {
        "headline": "New pricing plan for students",
        "subhead": "Student founders now get reduced fees for their first year.",
        "cta": "See student pricing",
        "eyebrow": "New for students",
        "layoutRecipe": "photo-hero-type",
        "heroStrategy": "ideogram_generate",
        "logoTreatment": "wordmark-white",
        "emphasis": "celebratory",
        "layoutTemplate": "full-bleed-scrim",
        "headlineScale": "lg",
        "headlineWeight": "extrabold",
        "ctaStyle": "pill",
        "rationale": "test",
    }
    brief.update(overrides)
    return brief


def _uniform_grid(rgb: tuple[int, int, int]) -> dict:
    return {"w": 8, "h": 4, "src_w": 1200, "src_h": 627, "pixels": [rgb] * 32}


def _png_bytes(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


class TestColorMath(unittest.TestCase):
    def test_contrast_extremes(self) -> None:
        self.assertAlmostEqual(design.contrast_ratio((0, 0, 0), (255, 255, 255)), 21.0, places=1)
        self.assertAlmostEqual(design.contrast_ratio((10, 10, 10), (10, 10, 10)), 1.0)

    def test_scrim_alpha_reaches_target(self) -> None:
        samples = [(240, 200, 170)]
        alpha = design.required_scrim_alpha(samples, (10, 18, 32), (255, 255, 255))
        self.assertIsNotNone(alpha)
        assert alpha is not None
        blended = design.blend(samples[0], (10, 18, 32), alpha)
        self.assertGreaterEqual(design.contrast_ratio((255, 255, 255), blended), design.TEXT_CONTRAST_MIN)
        self.assertLessEqual(alpha, design.SCRIM_MAX_ALPHA)

    def test_scrim_alpha_none_when_impossible(self) -> None:
        self.assertIsNone(
            design.required_scrim_alpha([(255, 255, 255)], (250, 250, 250), (255, 255, 255))
        )


class TestTemplatesAndCopy(unittest.TestCase):
    def test_grid_columns(self) -> None:
        self.assertEqual(design.col_x(0), design.MARGIN_X)
        self.assertEqual(design.col_x(11) + design.COLUMN_W, design.CANVAS_W - design.MARGIN_X)

    def test_profile_layout_traits_hint(self) -> None:
        name = design.resolve_template_name(
            {}, has_image=True, monochrome=False, brand_profile=_fixture("brand-profile-stripe.json")
        )
        self.assertEqual(name, "split-text-left")

    def test_brief_template_wins(self) -> None:
        name = design.resolve_template_name(
            {"layoutTemplate": "text-panel"}, has_image=True, monochrome=False
        )
        self.assertEqual(name, "text-panel")

    def test_no_image_is_centered(self) -> None:
        self.assertEqual(
            design.resolve_template_name(None, has_image=False, monochrome=True), "centered-statement"
        )

    def test_profile_palette_drives_brand_role(self) -> None:
        roles = design.brand_roles(_fixture("kit-stripe.json"), _fixture("brand-profile-stripe.json"))
        self.assertEqual(roles.brand, "#635bff")
        self.assertEqual(roles.dark, "#0a2540")
        self.assertFalse(roles.monochrome)

    def test_clamp_words(self) -> None:
        out = design.clamp_words("one two three four five six", 3, 100)
        self.assertEqual(out, "one two three…")

    def test_balanced_lines_avoid_orphans(self) -> None:
        lines = design.balance_lines("New pricing plan for students", 64, 620, design.HEADLINE_EM)
        self.assertEqual(len(lines), 2)
        self.assertGreater(len(lines[-1].split()), 1)

    def test_plan_stacks_on_grid_and_audits_clean(self) -> None:
        plan = design.plan_layout(
            "full-bleed-scrim",
            headline="New pricing plan for students",
            subline="Student founders now get reduced fees.",
            eyebrow="New",
            cta="Learn more",
            logo_size=(86, 36),
        )
        els = plan.elements
        self.assertEqual(els["headline"]["box"][0], design.MARGIN_X)
        self.assertLess(els["eyebrow"]["box"][1], els["headline"]["box"][1])
        self.assertLess(els["headline"]["box"][1], els["subline"]["box"][1])
        self.assertLess(els["subline"]["box"][1], els["cta"]["box"][1])
        bottom = els["cta"]["box"][1] + els["cta"]["box"][3]
        self.assertLessEqual(bottom, design.CANVAS_H - design.MARGIN_Y + 0.5)
        audit = design.audit_plan(plan, contrast={"headline": 7.0, "subline": 7.0, "logo": 5.0})
        self.assertEqual(audit["failed"], [])

    def test_audit_flags_low_contrast(self) -> None:
        plan = design.plan_layout("full-bleed-scrim", headline="Update", logo_size=(86, 36))
        audit = design.audit_plan(plan, contrast={"headline": 2.0})
        self.assertIn("contrast", audit["failed"])


class TestCompilerRules(unittest.TestCase):
    def _compile(self, grid: dict, **kwargs) -> dict:
        return compile_poster_batch(
            _fixture("kit-stripe.json"),
            _session(),
            hero_relative_path="generated/assets/test-hero.png",
            hero_width=1200,
            hero_height=627,
            hero_grid=grid,
            logo_relative_path="generated/assets/logo.svg",
            logo_variants={
                "original": "generated/assets/logo.svg",
                "light": "generated/assets/logo-light.svg",
                "dark": "generated/assets/logo-dark.svg",
            },
            logo_width=60,
            logo_height=25,
            creative_brief=kwargs.pop("brief", _brief()),
            **kwargs,
        )

    def test_bright_background_gets_gradient_scrim_not_flat_band(self) -> None:
        batch = self._compile(_uniform_grid((235, 190, 160)))
        commands = [s["command"] for s in batch["steps"]]
        self.assertNotIn("fill.solidColor", commands)
        meta = batch["meta"]
        self.assertGreaterEqual(meta["contrast"]["headline"], design.TEXT_CONTRAST_MIN)
        if meta["scrim"]["kind"] != "none":
            scrim = next(
                s for s in batch["steps"] if s["command"] == "gradient.fill.create"
            )["params"]
            self.assertEqual(scrim["transparency"][-1][1], 0)

    def test_mid_grey_background_needs_scrim(self) -> None:
        batch = self._compile(_uniform_grid((128, 128, 128)))
        meta = batch["meta"]
        self.assertGreaterEqual(meta["contrast"]["headline"], design.TEXT_CONTRAST_MIN)
        names = [s["params"].get("name") for s in batch["steps"]]
        self.assertTrue(
            meta["scrim"]["kind"] != "none" or meta["layoutTemplate"] == "text-panel",
            msg=f"no scrim and no panel: {names}",
        )

    def test_cta_chip_and_bold_headline(self) -> None:
        batch = self._compile(_uniform_grid((20, 24, 40)))
        names = [s["params"].get("name") for s in batch["steps"]]
        self.assertIn("CTA chip", names)
        self.assertIn("CTA label", names)
        headline = next(s for s in batch["steps"] if s["params"].get("name") == "Headline")
        self.assertGreaterEqual(headline["params"]["weight"], 700)
        self.assertGreaterEqual(headline["params"]["size"], design.HEADLINE_MIN_SIZE)

    def test_dark_background_picks_light_logo(self) -> None:
        batch = self._compile(_uniform_grid((12, 16, 30)))
        self.assertEqual(batch["meta"]["logoVariant"], "light")
        self.assertEqual(batch["placements"][-1]["path"], "generated/assets/logo-light.svg")
        self.assertGreaterEqual(batch["meta"]["contrast"]["logo"], design.GRAPHIC_CONTRAST_MIN)

    def test_light_background_keeps_dark_logo(self) -> None:
        batch = self._compile(_uniform_grid((246, 246, 250)), brief=_brief(logoTreatment="wordmark-dark"))
        self.assertIn(batch["meta"]["logoVariant"], ("original", "dark"))

    def test_split_template_places_hero_in_right_half(self) -> None:
        batch = self._compile(_uniform_grid((20, 24, 40)), brief=_brief(layoutTemplate="split-text-left"))
        self.assertEqual(batch["meta"]["layoutTemplate"], "split-text-left")
        hero = batch["backgroundPlacements"][0]
        right_edge = hero["center"][0] + 1200 * hero["scale"] / 100 / 2
        self.assertAlmostEqual(right_edge, design.CANVAS_W, delta=1)
        names = [s["params"].get("name") for s in batch["steps"]]
        self.assertIn("Brand panel", names)

    def test_design_audit_in_meta(self) -> None:
        batch = self._compile(_uniform_grid((20, 24, 40)))
        audit = batch["meta"]["designAudit"]
        self.assertGreaterEqual(audit["score"], 90)
        self.assertEqual(audit["failed"], [])


class TestLogoVariants(unittest.TestCase):
    def test_variants_recolor_current_color(self) -> None:
        svg = '<svg viewBox="0 0 10 10"><path fill="currentColor" d="M0 0h10v10z"/></svg>'
        variants = logo_svg_variants(svg)
        self.assertIn('xmlns="http://www.w3.org/2000/svg"', variants["original"])
        self.assertIn(design.WHITE, variants["light"].lower())
        self.assertIn(design.INK, variants["dark"].lower())


class TestIdeogramPrompt(unittest.TestCase):
    def test_sanitizer_removes_brand_and_text_words(self) -> None:
        kit = _fixture("kit-stripe.json")
        out = sanitize_scene_description(
            'Stripe logo wordmark with headline "Students" over violet waves #635bff',
            brand_terms_from_kit(kit),
        )
        lowered = out.lower()
        for banned in ("stripe", "logo", "wordmark", "headline", "students", "#635bff"):
            self.assertNotIn(banned, lowered)
        self.assertIn("violet waves", lowered)

    def test_structured_prompt_has_no_text_elements(self) -> None:
        kit = _fixture("kit-stripe.json")
        prompt = build_structured_prompt(
            "Stripe ribbons of light",
            role="background",
            template="split-text-left",
            palette=["#635bff"],
            brand_terms=brand_terms_from_kit(kit),
            brand_profile=_fixture("brand-profile-stripe.json"),
        )
        payload = json.dumps(prompt).lower()
        self.assertNotIn("stripe", payload)
        elements = prompt["compositional_deconstruction"]["elements"]
        self.assertTrue(elements)
        self.assertTrue(all(e["type"] == "obj" for e in elements))
        for element in elements:
            self.assertGreaterEqual(element["bbox"][1], 500)
        self.assertEqual(prompt["style_description"]["color_palette"][0], "#635bff")
        self.assertIn("minimal", prompt["style_description"]["aesthetics"])

    @patch("ideogram_client._download_image")
    @patch("ideogram_client._call_generate_api")
    def test_generate_sends_json_prompt_with_magic_off(
        self, mock_api: MagicMock, mock_dl: MagicMock
    ) -> None:
        mock_api.return_value = {"data": [{"url": "https://cdn.example/x.png", "is_image_safe": True}]}
        mock_dl.return_value = b"\x89PNG\r\n\x1a\n"
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=False):
            os.environ.pop("COMMMAKER_IDEOGRAM_MAGIC_PROMPT", None)
            _rel, _data, meta = generate_layer_image(
                "Acme abstract waves",
                "background",
                "1200x627",
                assets_dir=tmp,
                api_key="test-key",
                template="full-bleed-scrim",
                brand_terms=["Acme"],
            )
        sent_prompt = mock_api.call_args.args[0]
        self.assertEqual(mock_api.call_args.kwargs["magic_prompt"], "off")
        parsed = json.loads(sent_prompt)
        self.assertNotIn("acme", sent_prompt.lower())
        self.assertIn("compositional_deconstruction", parsed)
        self.assertEqual(meta["template"], "full-bleed-scrim")


class TestBriefDecisions(unittest.TestCase):
    def test_fallback_brief_has_design_fields(self) -> None:
        brief = build_fallback_brief(
            _fixture("kit-stripe.json"),
            {"crisisMessage": "New pricing plan for students", "crisisFacts": "", "tone": "celebratory"},
        )
        self.assertIn(brief["layoutTemplate"], design.LAYOUT_TEMPLATES)
        self.assertIn(brief["headlineScale"], design.HEADLINE_SCALES)
        self.assertIn(brief["headlineWeight"], design.HEADLINE_WEIGHTS)
        self.assertEqual(brief["ctaStyle"], "pill")
        self.assertTrue(brief["cta"])
        self.assertLessEqual(design.word_count(brief["subhead"]), design.MAX_WORDS["subline"])

    def test_fallback_copy_uses_message_and_facts_not_tagline(self) -> None:
        brief = build_fallback_brief(
            _fixture("kit-stripe.json"),
            {
                "crisisMessage": "New pricing plan for students",
                "crisisFacts": "Student founders get reduced fees for their first year.",
                "tone": "celebratory",
            },
        )
        self.assertEqual(brief["headline"], "New pricing plan for students")
        self.assertEqual(brief["subhead"], "Student founders get reduced fees for their first year.")

    def test_og_social_card_is_not_a_poster_background(self) -> None:
        kit = _fixture("kit-stripe.json")
        self.assertTrue(design.kit_hero_unsuitable(kit))
        with patch.dict(os.environ, {"COMMMAKER_ALLOW_OG_HERO": "1"}):
            self.assertFalse(design.kit_hero_unsuitable(kit))
        with patch.dict(os.environ, {"IDEOGRAM_API_KEY": ""}):
            brief = build_fallback_brief(kit, {"crisisMessage": "Update", "crisisFacts": ""})
        self.assertNotEqual(brief["heroStrategy"], "use_kit_photo")
        photo_kit = {**kit, "heroImageKind": "marketing"}
        self.assertFalse(design.kit_hero_unsuitable(photo_kit))

    def test_art_director_patch_keeps_imagery_and_template(self) -> None:
        brief = _brief(heroImagePrompt="violet ribbons", ideogramLayers="background-only")
        patched = _apply_art_director_patch(
            brief,
            {
                "headline": "Student pricing is here",
                "subhead": "Reduced fees for student founders.",
                "cta": "",
                "eyebrow": "New",
                "headlineScale": "xl",
                "headlineWeight": "bold",
                "ctaStyle": "outline",
            },
        )
        self.assertEqual(patched["headline"], "Student pricing is here")
        self.assertEqual(patched["headlineScale"], "xl")
        self.assertEqual(patched["heroImagePrompt"], "violet ribbons")
        self.assertEqual(patched["layoutTemplate"], "full-bleed-scrim")
        self.assertEqual(patched["ctaStyle"], "none")

    @patch("creative_brief._post_anthropic_messages")
    def test_art_director_review_mocked(self, mock_post: MagicMock) -> None:
        mock_post.return_value = {
            "content": [
                {
                    "type": "tool_use",
                    "name": "submit_art_direction",
                    "input": {
                        "score": 72,
                        "issues": ["Headline too long for xl"],
                        "headline": "Student pricing is here",
                        "subhead": "Reduced fees for student founders.",
                        "cta": "See pricing",
                        "eyebrow": "New",
                        "headlineScale": "lg",
                        "headlineWeight": "extrabold",
                        "ctaStyle": "pill",
                    },
                }
            ]
        }
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test", "COMMMAKER_LLM_PROVIDER": ""}):
            review = art_director_review(_brief(), {"designAudit": {"score": 80, "failed": []}})
        self.assertIsNotNone(review)
        assert review is not None
        self.assertEqual(review["score"], 72)
        self.assertEqual(review["brief"]["headline"], "Student pricing is here")
        prompt = mock_post.call_args.args[0]["messages"][0]["content"]
        self.assertIn("full-bleed-scrim", prompt)


class TestImageLuma(unittest.TestCase):
    def test_pure_png_decoder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.png")
            with open(path, "wb") as handle:
                handle.write(_png_bytes(40, 20, (200, 100, 50)))
            grid = _grid_from_png(path, 8)
        self.assertIsNotNone(grid)
        assert grid is not None
        self.assertEqual((grid["src_w"], grid["src_h"]), (40, 20))
        self.assertEqual(grid["w"], 8)
        self.assertTrue(all(tuple(p) == (200, 100, 50) for p in grid["pixels"]))


if __name__ == "__main__":
    unittest.main()
