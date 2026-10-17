#!/usr/bin/env python3
"""Unit tests for creative brief + compiler integration."""

from __future__ import annotations

import io
import json
import os
import sys
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from creative_brief import (  # noqa: E402
    CREATIVE_BRIEF_JSON_SCHEMA,
    _anthropic_messages_body,
    _anthropic_request_headers,
    _anthropic_tool_schema,
    _call_anthropic,
    _post_anthropic_messages,
    _safe_error_detail,
    api_key_for_provider,
    build_creative_brief,
    build_fallback_brief,
    default_model_for_provider,
    resolve_llm_model,
)


def _object_nodes_without_additional_properties_false(node: object) -> list[str]:
    """Return JSON paths of object schemas missing additionalProperties: false."""
    missing: list[str] = []

    def walk(value: object, path: str) -> None:
        if not isinstance(value, dict):
            return
        if value.get("type") == "object":
            if value.get("additionalProperties") is not False:
                missing.append(path or "$")
        for key, child in value.items():
            walk(child, f"{path}.{key}" if path else key)

    walk(node, "")
    return missing
from poster_compiler import compile_poster_batch  # noqa: E402


class TestCreativeBriefFallback(unittest.TestCase):
    @patch.dict(os.environ, {"IDEOGRAM_API_KEY": "test-key"})
    def test_fallback_busy_hero_prefers_ideogram_when_key_set(self) -> None:
        kit = {
            "siteName": "Acme",
            "heroBusy": True,
            "heroImageUrl": "https://example.com/hero.jpg",
            "tagline": "We build things",
            "colors": ["#112233"],
        }
        crisis = {
            "crisisMessage": "Planned maintenance tonight",
            "crisisFacts": "API may be slow between 22:00–23:00 UTC.",
            "tone": "calm",
        }
        brief = build_fallback_brief(kit, crisis)
        self.assertEqual(brief["heroStrategy"], "ideogram_generate")
        self.assertIn("Acme", brief.get("heroImagePrompt", ""))

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
        self.assertEqual(result["fallbackReason"], "no_provider")
        self.assertEqual(result["errorDetail"], "ConfigurationError")
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
        self.assertEqual(model, "claude-sonnet-5-5")

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

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    @patch("creative_brief._call_llm")
    def test_llm_error_fallback_metadata(self, mock_llm) -> None:
        mock_llm.side_effect = urllib.error.HTTPError(
            url="https://api.openai.com/v1/chat/completions",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=None,
        )
        result = build_creative_brief({}, {"crisisFacts": "x"})
        self.assertEqual(result["source"], "fallback")
        self.assertEqual(result["fallbackReason"], "llm_error")
        self.assertEqual(result["errorDetail"], "HTTP 401")
        self.assertEqual(result["provider"], "openai")

    def test_safe_error_detail_uses_exception_class(self) -> None:
        self.assertEqual(_safe_error_detail(TimeoutError()), "TimeoutError")

    def test_safe_error_detail_anthropic_404_hint(self) -> None:
        err = urllib.error.HTTPError(
            url="https://api.anthropic.com/v1/messages",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=None,
        )
        detail = _safe_error_detail(err, provider="anthropic")
        self.assertIn("COMMMAKER_LLM_MODEL", detail)
        self.assertIn("Sonnet 4 IDs retired", detail)

    def test_safe_error_detail_includes_truncated_body(self) -> None:
        err = urllib.error.HTTPError(
            url="https://api.anthropic.com/v1/messages",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=io.BytesIO(
                b'{"error":{"message":"tool_choice type tool is not supported on this model"}}'
            ),
        )
        detail = _safe_error_detail(err, provider="anthropic")
        self.assertTrue(detail.startswith("HTTP 400:"))
        self.assertIn("tool_choice", detail)

    def test_anthropic_request_uses_auto_tool_choice_and_strict(self) -> None:
        body = _anthropic_messages_body({}, {"crisisFacts": "x"}, "linkedin-1200x627", model="claude-sonnet-5-5")
        self.assertEqual(body["tool_choice"], {"type": "auto"})
        tool = body["tools"][0]
        self.assertTrue(tool.get("strict"))
        self.assertEqual(tool["name"], "submit_creative_brief")
        self.assertIn("MUST call submit_creative_brief", body["system"])
        schema = tool["input_schema"]
        self.assertEqual(schema.get("additionalProperties"), False)
        props = schema.get("properties") or {}
        self.assertEqual(set(schema.get("required") or []), set(props.keys()))

    def test_creative_brief_schema_strict_object_nodes(self) -> None:
        for schema in (CREATIVE_BRIEF_JSON_SCHEMA, _anthropic_tool_schema()):
            missing = _object_nodes_without_additional_properties_false(schema)
            self.assertEqual(missing, [], msg=f"missing additionalProperties: false at {missing}")

    def test_anthropic_console_usr_key_sends_bearer_and_x_api_key(self) -> None:
        key = "sk-ant-usr-test-key"
        headers = _anthropic_request_headers(key)
        self.assertEqual(headers["x-api-key"], key)
        self.assertEqual(headers["Authorization"], f"Bearer {key}")

    @patch.dict(os.environ, {"ANTHROPIC_WORKSPACE_ID": "ws_abc123"})
    def test_anthropic_workspace_id_header(self) -> None:
        headers = _anthropic_request_headers("sk-ant-usr-test-key")
        self.assertEqual(headers["anthropic-workspace-id"], "ws_abc123")

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "\ufeffsk-ant-usr-secret\n"})
    def test_api_key_for_provider_strips_bom_and_whitespace(self) -> None:
        self.assertEqual(api_key_for_provider("anthropic"), "sk-ant-usr-secret")

    @patch("urllib.request.urlopen")
    def test_post_anthropic_messages_console_key_headers(self, mock_urlopen: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"content": []}).encode("utf-8")
        mock_resp.__enter__ = lambda self: self
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        usr_key = "sk-ant-usr-mock-key"
        _post_anthropic_messages({"model": "claude-sonnet-5-5"}, api_key=usr_key)

        req = mock_urlopen.call_args[0][0]
        header_map = {k.lower(): v for k, v in req.header_items()}
        self.assertEqual(header_map["x-api-key"], usr_key)
        self.assertEqual(header_map["authorization"], f"Bearer {usr_key}")

    @patch("creative_brief._post_anthropic_messages")
    def test_anthropic_retries_once_without_tool_use(self, mock_post: MagicMock) -> None:
        tool_brief = {
            "headline": "Update",
            "subhead": "More",
            "layoutRecipe": "gradient-brand",
            "heroStrategy": "gradient_from_palette",
            "logoTreatment": "wordmark-white",
            "emphasis": "calm",
            "rationale": "Clear gradient layout.",
        }
        mock_post.side_effect = [
            {"content": [{"type": "text", "text": "thinking…"}]},
            {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "submit_creative_brief",
                        "input": tool_brief,
                    }
                ]
            },
        ]
        brief = _call_anthropic(
            {},
            {"crisisFacts": "x"},
            "linkedin-1200x627",
            api_key="key",
            model="claude-sonnet-5-5",
        )
        self.assertEqual(brief["headline"], "Update")
        self.assertEqual(mock_post.call_count, 2)

    @patch("creative_brief._post_anthropic_messages")
    def test_anthropic_text_json_fallback(self, mock_post: MagicMock) -> None:
        mock_post.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "headline": "From text",
                            "subhead": "",
                            "layoutRecipe": "minimal-wordmark",
                            "heroStrategy": "none",
                            "logoTreatment": "wordmark-dark",
                            "emphasis": "calm",
                            "rationale": "Parsed from assistant text.",
                        }
                    ),
                }
            ]
        }
        brief = _call_anthropic(
            {},
            {"crisisFacts": "x"},
            "linkedin-1200x627",
            api_key="key",
            model="claude-sonnet-5-5",
        )
        self.assertEqual(brief["headline"], "From text")
        self.assertEqual(mock_post.call_count, 2)

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("creative_brief._call_llm")
    def test_anthropic_404_fallback_metadata(self, mock_llm) -> None:
        mock_llm.side_effect = urllib.error.HTTPError(
            url="https://api.anthropic.com/v1/messages",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=None,
        )
        result = build_creative_brief({}, {"crisisFacts": "x"})
        self.assertEqual(result["fallbackReason"], "llm_error")
        self.assertIn("Sonnet 4 IDs retired", result["errorDetail"])
        self.assertEqual(result["provider"], "anthropic")


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
