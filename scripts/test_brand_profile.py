#!/usr/bin/env python3
"""Offline tests for the hybrid AI + vision Brand Profile (no network, no browser)."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import brand_profile as bp  # noqa: E402
from creative_brief import kit_summary_for_prompt  # noqa: E402

FIXTURES = os.path.join(SCRIPTS, "fixtures", "brand_profile")
LLM_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "COMMMAKER_LLM_PROVIDER",
    "COMMMAKER_LLM_MODEL",
    "COMMMAKER_BRAND_PROFILE_MODEL",
)


def _load(name: str) -> dict:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


def _env_without_llm(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in LLM_ENV_KEYS}
    env.update(extra)
    return env


def _fixture_capture(name: str, shots: dict[str, str] | None = None) -> dict:
    data = _load(name)
    return {
        "available": True,
        "rendered": data["rendered"],
        "screenshots": shots or {},
        "durationSec": 0.0,
    }


def _stripe_signals() -> dict:
    data = _load("stripe_capture.json")
    return bp.build_signals(data["kit"], _fixture_capture("stripe_capture.json"), data["pixels"])


def _vercel_signals() -> dict:
    data = _load("vercel_capture.json")
    return bp.build_signals(data["kit"], _fixture_capture("vercel_capture.json"), data["pixels"])


def _schema_problems(node: object, path: str = "$") -> list[str]:
    problems: list[str] = []
    if isinstance(node, dict):
        if node.get("type") == "object":
            if node.get("additionalProperties") is not False:
                problems.append(f"{path}: additionalProperties")
            props = set((node.get("properties") or {}).keys())
            if set(node.get("required") or []) != props:
                problems.append(f"{path}: required != properties")
        for key, child in node.items():
            problems.extend(_schema_problems(child, f"{path}.{key}"))
    elif isinstance(node, list):
        for i, child in enumerate(node):
            problems.extend(_schema_problems(child, f"{path}[{i}]"))
    return problems


def _anthropic_payload(tool_input: dict) -> dict:
    return {
        "content": [
            {"type": "text", "text": "Here is the profile."},
            {"type": "tool_use", "name": "submit_brand_profile", "input": tool_input},
        ],
        "usage": {"input_tokens": 7400, "output_tokens": 1300},
    }


class TestSchema(unittest.TestCase):
    def test_every_object_is_strict_and_fully_required(self) -> None:
        self.assertEqual(_schema_problems(bp.BRAND_PROFILE_JSON_SCHEMA), [])

    def test_anthropic_body_has_images_and_strict_tool(self) -> None:
        images = [
            {"key": "desktopFold", "label": "Desktop", "data": "AAAA", "mediaType": "image/jpeg", "size": (1280, 800)}
        ]
        body = bp.anthropic_vision_body(_stripe_signals(), images, model="claude-opus-5-5")
        self.assertEqual(body["model"], "claude-opus-5-5")
        self.assertEqual(body["tool_choice"], {"type": "auto"})
        tool = body["tools"][0]
        self.assertTrue(tool["strict"])
        self.assertEqual(tool["name"], "submit_brand_profile")
        blocks = body["messages"][0]["content"]
        self.assertEqual(blocks[1]["type"], "image")
        self.assertEqual(blocks[1]["source"]["media_type"], "image/jpeg")
        self.assertIn("colorCandidates", blocks[-1]["text"])
        self.assertNotIn("<svg", blocks[-1]["text"])


class TestSignals(unittest.TestCase):
    def test_stripe_candidates_from_rendered_dom(self) -> None:
        s = _stripe_signals()
        by_hex = {c["hex"]: c for c in s["colors"]}
        self.assertIn("#533afd", by_hex)
        self.assertIn("computed:cta-background", by_hex["#533afd"]["sources"])
        self.assertEqual(s["fonts"][0]["family"], "sohne-var")
        self.assertIn("display", s["fonts"][0]["roles"])
        logo = s["logos"][0]
        self.assertEqual(logo["id"], "L1")
        self.assertIn("stripe", logo["label"].lower())
        self.assertNotIn("var(", logo["svg"])

    def test_vercel_small_home_mark_is_logo(self) -> None:
        s = _vercel_signals()
        self.assertIn("vercel", s["logos"][0]["label"].lower())
        self.assertFalse(any("emoji" in f["family"].lower() for f in s["fonts"]))

    def test_static_only_signals_without_capture(self) -> None:
        kit = _load("stripe_capture.json")["kit"]
        s = bp.build_signals(kit, {"available": False}, [])
        self.assertFalse(s["rendered"])
        self.assertTrue(s["colors"])
        self.assertTrue(any(lg["source"] == "static-scrape" for lg in s["logos"]))


class TestHeuristicFallback(unittest.TestCase):
    def test_stripe_roles(self) -> None:
        p = bp.heuristic_profile(_stripe_signals())
        roles = {e["role"]: e["hex"] for e in p["palette"]}
        for role in bp.REQUIRED_PALETTE_ROLES:
            self.assertIn(role, roles)
        self.assertEqual(roles["background"], "#ffffff")
        self.assertEqual(roles["primary"], "#533afd")
        self.assertEqual(roles["text"], "#061b31")
        self.assertEqual(p["typography"]["display"]["family"], "sohne-var")
        self.assertTrue(p["tagline"].startswith("Financial infrastructure"))
        self.assertTrue(p["aesthetic"])

    def test_vercel_monochrome_primary_is_cta(self) -> None:
        p = bp.heuristic_profile(_vercel_signals())
        roles = {e["role"]: e["hex"] for e in p["palette"]}
        self.assertEqual(roles["primary"], "#171717")
        self.assertEqual(p["typography"]["display"]["family"], "GeistSans")
        self.assertEqual(p["logo"]["candidateId"], "L1")


class TestReconcile(unittest.TestCase):
    def test_ai_values_snap_to_procedural_ground_truth(self) -> None:
        p = bp.reconcile_profile(_load("stripe_ai_tool_input.json"), _stripe_signals())
        by_role = {e["role"]: e for e in p["palette"]}
        self.assertEqual(by_role["background"]["hex"], "#ffffff")
        self.assertTrue(by_role["background"]["verified"])
        self.assertEqual(by_role["text"]["hex"], "#061b31")
        self.assertEqual(by_role["primary"]["candidateId"], "c2")
        self.assertEqual(by_role["accent"]["source"], "procedural")
        self.assertNotEqual(by_role["accent"]["hex"], "#ff9a44")
        self.assertEqual(by_role["secondary"]["source"], "vision")
        self.assertFalse(by_role["secondary"]["verified"])
        display = p["typography"]["display"]
        self.assertEqual(display["family"], "sohne-var")
        self.assertTrue(display["matched"])
        self.assertIn("Chromatic Fluidity", p["aesthetic"])
        self.assertEqual(p["logo"]["candidateId"], "L1")
        self.assertEqual(p["imageryStyle"]["primaryMedium"], "gradients")

    def test_missing_roles_are_backfilled(self) -> None:
        raw = _load("stripe_ai_tool_input.json")
        raw["palette"] = [{"role": "primary", "hex": "#533afd", "candidateId": "c2", "name": "", "usage": ""}]
        p = bp.reconcile_profile(raw, _stripe_signals())
        roles = {e["role"] for e in p["palette"]}
        self.assertTrue(set(bp.REQUIRED_PALETTE_ROLES) <= roles)

    def test_hex_wins_when_candidate_id_disagrees(self) -> None:
        signals = _stripe_signals()
        light = next(c for c in signals["colors"] if c["hex"] == "#e5edf5")
        raw = _load("stripe_ai_tool_input.json")
        raw["palette"][1] = {"role": "primary", "hex": "#533afd", "candidateId": light["id"], "name": "Blurple", "usage": ""}
        p = bp.reconcile_profile(raw, signals)
        primary = next(e for e in p["palette"] if e["role"] == "primary")
        self.assertEqual(primary["hex"], "#533afd")
        self.assertTrue(primary["verified"])

    def test_duplicate_cta_labels_collapse(self) -> None:
        self.assertEqual(bp._dedupe_label("Sign in Sign in"), "Sign in")
        self.assertEqual(bp._dedupe_label("Get started"), "Get started")

    def test_unknown_candidate_ids_are_safe(self) -> None:
        raw = _load("stripe_ai_tool_input.json")
        raw["logo"]["candidateId"] = "L99"
        raw["typography"]["display"] = {"family": "Unheard Grotesk", "candidateId": "f42", "weights": [500], "usage": ""}
        p = bp.reconcile_profile(raw, _stripe_signals())
        self.assertEqual(p["logo"]["candidateId"], "L1")
        self.assertFalse(p["typography"]["display"]["matched"])
        self.assertEqual(p["typography"]["display"]["weights"], [500])


class TestAnalyzeBrand(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="brand-profile-test-")
        self.kit = _load("stripe_capture.json")["kit"]
        self.shot = None
        try:
            from PIL import Image

            img = Image.new("RGB", (1440, 900), "#ffffff")
            for x in range(900, 1440):
                for y in range(0, 900, 6):
                    img.putpixel((x, y), (253, 150, 67))
            self.shot = os.path.join(self.tmp, "fold.jpg")
            img.save(self.shot)
        except ImportError:
            pass

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _capture_fn(self, url: str, out_dir: str, *, mobile: bool = True) -> dict:
        shots = {"desktopFold": self.shot} if self.shot else {}
        return _fixture_capture("stripe_capture.json", shots)

    def test_llm_path_cost_cache_and_logo(self) -> None:
        payload = _anthropic_payload(_load("stripe_ai_tool_input.json"))
        with patch.dict(os.environ, _env_without_llm(ANTHROPIC_API_KEY="sk-ant-test"), clear=True), patch(
            "brand_profile._post_json", return_value=payload
        ) as post:
            result = bp.analyze_brand(
                "https://www.stripe.com/", cache_dir=self.tmp, kit=self.kit, capture_fn=self._capture_fn
            )
            self.assertEqual(result["source"], "llm")
            self.assertEqual(result["model"], "claude-opus-5-5")
            self.assertEqual(result["usage"], {"inputTokens": 7400, "outputTokens": 1300})
            self.assertAlmostEqual(result["costUsd"], 0.2085, places=4)
            self.assertFalse(result["cached"])
            self.assertIn("Stripe logo", result["kit"]["logoSvg"])
            self.assertEqual(result["kit"]["brandProfile"]["name"], "Stripe")
            body = post.call_args[0][1]
            if self.shot:
                self.assertTrue(any(b["type"] == "image" for b in body["messages"][0]["content"]))
            self.assertTrue(os.path.isfile(os.path.join(self.tmp, "stripe.com", "profile.json")))

            again = bp.analyze_brand("https://stripe.com", cache_dir=self.tmp, kit=self.kit, capture_fn=self._capture_fn)
            self.assertTrue(again["cached"])
            self.assertEqual(post.call_count, 1)

    def test_no_key_falls_back_and_stale_fallback_is_retried(self) -> None:
        with patch.dict(os.environ, _env_without_llm(), clear=True):
            result = bp.analyze_brand("https://stripe.com", cache_dir=self.tmp, kit=self.kit, capture_fn=self._capture_fn)
        self.assertEqual(result["source"], "fallback")
        self.assertEqual(result["fallbackReason"], "no_provider")
        self.assertEqual(result["brandProfile"]["analysis"]["source"], "fallback")
        payload = _anthropic_payload(_load("stripe_ai_tool_input.json"))
        with patch.dict(os.environ, _env_without_llm(ANTHROPIC_API_KEY="sk-ant-test"), clear=True), patch(
            "brand_profile._post_json", return_value=payload
        ):
            upgraded = bp.analyze_brand("https://stripe.com", cache_dir=self.tmp, kit=self.kit, capture_fn=self._capture_fn)
        self.assertEqual(upgraded["source"], "llm")

    def test_llm_http_error_falls_back(self) -> None:
        err = urllib.error.HTTPError("https://api.anthropic.com", 529, "Overloaded", None, None)
        with patch.dict(os.environ, _env_without_llm(ANTHROPIC_API_KEY="sk-ant-test"), clear=True), patch(
            "brand_profile._post_json", side_effect=err
        ):
            result = bp.analyze_brand("https://stripe.com", cache_dir=self.tmp, kit=self.kit, capture_fn=self._capture_fn, refresh=True)
        self.assertEqual(result["source"], "fallback")
        self.assertEqual(result["fallbackReason"], "llm_error")
        self.assertIn("529", result["errorDetail"])

    def test_capture_unavailable_still_profiles(self) -> None:
        def no_browser(url: str, out_dir: str, *, mobile: bool = True) -> dict:
            return {"available": False, "reason": "playwright not installed"}

        with patch.dict(os.environ, _env_without_llm(), clear=True):
            result = bp.analyze_brand("https://stripe.com", cache_dir=self.tmp, kit=self.kit, capture_fn=no_browser, refresh=True)
        self.assertFalse(result["capture"]["available"])
        self.assertEqual(result["capture"]["reason"], "playwright not installed")
        self.assertTrue(result["brandProfile"]["palette"])

    def test_capture_site_reports_missing_playwright(self) -> None:
        with patch("brand_profile.playwright_available", return_value=(False, "playwright not installed")):
            cap = bp.capture_site("https://stripe.com", self.tmp)
        self.assertEqual(cap, {"available": False, "reason": "playwright not installed"})

    def test_domain_key(self) -> None:
        self.assertEqual(bp.domain_key("https://www.Stripe.com/pricing?x=1"), "stripe.com")
        self.assertEqual(bp.domain_key("http://localhost:8000/a"), "localhost")


class TestDownstreamHooks(unittest.TestCase):
    def _kit(self) -> dict:
        profile = bp.reconcile_profile(_load("stripe_ai_tool_input.json"), _stripe_signals())
        kit = dict(_load("stripe_capture.json")["kit"])
        kit["brandProfile"] = profile
        return kit

    def test_apply_profile_to_kit(self) -> None:
        kit = self._kit()
        applied = bp.apply_brand_profile_to_kit(kit)
        self.assertEqual(applied["colors"][0], "#533afd")
        self.assertEqual(applied["accentColors"][0], "#533afd")
        self.assertEqual(applied["fonts"][0], "sohne-var")
        self.assertEqual(applied["tagline"], "Financial infrastructure to grow your revenue.")
        self.assertEqual(bp.apply_brand_profile_to_kit(applied), applied)
        self.assertEqual(bp.apply_brand_profile_to_kit({"siteName": "X"}), {"siteName": "X"})

    def test_user_edits_win(self) -> None:
        kit = self._kit()
        for entry in kit["brandProfile"]["palette"]:
            if entry["role"] == "primary":
                entry["hex"] = "#00d4b2"
        kit["brandProfile"]["typography"]["display"]["family"] = "Playfair Display"
        applied = bp.apply_brand_profile_to_kit(kit)
        self.assertEqual(applied["colors"][0], "#00d4b2")
        self.assertEqual(applied["fonts"][0], "Playfair Display")

    def test_augment_ideogram_prompt(self) -> None:
        kit = self._kit()
        base = "Abstract brand background for Stripe, no text"
        out = bp.augment_ideogram_prompt(base, kit, role="background")
        self.assertTrue(out.startswith(base))
        self.assertIn("Chromatic Fluidity", out)
        self.assertIn("#533afd", out)
        self.assertIn("flowing ribbon gradients", out)
        self.assertLessEqual(len(out), bp.IDEOGRAM_PROMPT_MAX_CHARS)
        accent = bp.augment_ideogram_prompt("Single subject", kit, role="accent")
        self.assertNotIn("Flowing translucent ribbon", accent)
        self.assertEqual(bp.augment_ideogram_prompt(base, {"siteName": "x"}), base)
        twice = bp.augment_ideogram_prompt(out, kit, role="background")
        self.assertEqual(twice.count("Chromatic Fluidity"), 1)

    def test_creative_brief_prompt_includes_profile(self) -> None:
        summary = kit_summary_for_prompt(self._kit())
        self.assertIn("brandProfile (AI + vision", summary)
        self.assertIn("Chromatic Fluidity", summary)
        self.assertIn("display sohne-var", summary)
        self.assertNotIn("brandProfile", kit_summary_for_prompt({"siteName": "Acme"}))


if __name__ == "__main__":
    unittest.main()
