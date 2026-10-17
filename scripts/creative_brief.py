"""LLM creative brief for CommMaker posters (Phase B).

One structured marketing decision per generate; ``poster_compiler`` remains the renderer.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Literal

LayoutRecipe = Literal["photo-hero-type", "gradient-brand", "minimal-wordmark"]
HeroStrategy = Literal["use_kit_photo", "gradient_from_palette", "solid", "none"]
LogoTreatment = Literal["wordmark-white", "wordmark-dark", "symbol-only"]
Emphasis = Literal["calm", "urgent", "celebratory"]
BriefSource = Literal["llm", "fallback"]
LlmProvider = Literal["openai", "anthropic", "openrouter"]

# Frontier defaults — never mini/nano (quality for marketing copy + layout decisions).
FRONTIER_MODEL_BY_PROVIDER: dict[LlmProvider, str] = {
    "anthropic": "claude-sonnet-4-20250514",
    "openai": "gpt-4.1",
    "openrouter": "anthropic/claude-sonnet-4",
}

OPENAI_API_BASE = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1").rstrip("/")
ANTHROPIC_API_BASE = os.environ.get(
    "ANTHROPIC_API_BASE", "https://api.anthropic.com/v1"
).rstrip("/")
OPENROUTER_API_BASE = os.environ.get(
    "OPENROUTER_API_BASE", "https://openrouter.ai/api/v1"
).rstrip("/")
LLM_TIMEOUT_SEC = 60

CREATIVE_BRIEF_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "headline": {"type": "string"},
        "subhead": {"type": "string"},
        "cta": {"type": "string"},
        "layoutRecipe": {
            "type": "string",
            "enum": ["photo-hero-type", "gradient-brand", "minimal-wordmark"],
        },
        "heroStrategy": {
            "type": "string",
            "enum": ["use_kit_photo", "gradient_from_palette", "solid", "none"],
        },
        "logoTreatment": {
            "type": "string",
            "enum": ["wordmark-white", "wordmark-dark", "symbol-only"],
        },
        "emphasis": {
            "type": "string",
            "enum": ["calm", "urgent", "celebratory"],
        },
        "rationale": {"type": "string"},
    },
    "required": [
        "headline",
        "subhead",
        "layoutRecipe",
        "heroStrategy",
        "logoTreatment",
        "emphasis",
        "rationale",
    ],
}


def default_model_for_provider(provider: LlmProvider) -> str:
    return FRONTIER_MODEL_BY_PROVIDER[provider]


def resolve_llm_provider() -> LlmProvider | None:
    """Pick provider from ``COMMMAKER_LLM_PROVIDER`` or installed API keys."""
    forced = (os.environ.get("COMMMAKER_LLM_PROVIDER") or "").strip().lower()
    if forced in FRONTIER_MODEL_BY_PROVIDER:
        return forced  # type: ignore[return-value]
    if (os.environ.get("ANTHROPIC_API_KEY") or "").strip():
        return "anthropic"
    if (os.environ.get("OPENROUTER_API_KEY") or "").strip():
        return "openrouter"
    if (os.environ.get("OPENAI_API_KEY") or "").strip():
        return "openai"
    return None


def resolve_llm_model(provider: LlmProvider) -> str:
    override = (os.environ.get("COMMMAKER_LLM_MODEL") or "").strip()
    if override:
        return override
    return default_model_for_provider(provider)


def api_key_for_provider(provider: LlmProvider) -> str:
    if provider == "anthropic":
        return (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if provider == "openrouter":
        return (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    return (os.environ.get("OPENAI_API_KEY") or "").strip()


def _truncate(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def kit_summary_for_prompt(kit: dict[str, Any] | None) -> str:
    kit = kit or {}
    colors = kit.get("accentColors") or kit.get("colors") or []
    color_str = ", ".join(str(c) for c in colors[:6]) if colors else "(none)"
    fonts = kit.get("fonts") or []
    font_str = ", ".join(str(f) for f in fonts[:4]) if fonts else "(none)"
    lines = [
        f"siteName: {kit.get('siteName') or '(unknown)'}",
        f"tagline: {kit.get('tagline') or '(none)'}",
        f"colors: {color_str}",
        f"fonts: {font_str}",
        f"heroBusy: {bool(kit.get('heroBusy'))}",
        f"heroBrandMark: {bool(kit.get('heroBrandMark'))}",
        f"hasHeroImage: {bool(kit.get('heroImageUrl'))}",
        f"headlineFromSite: {kit.get('headline') or '(none)'}",
    ]
    return "\n".join(lines)


def _tone_to_emphasis(tone: str | None) -> Emphasis:
    mapping = {
        "calm": "calm",
        "factual": "calm",
        "empathetic": "calm",
        "urgent": "urgent",
        "celebratory": "celebratory",
    }
    return mapping.get((tone or "").strip().lower(), "calm")


def _first_fact_line(crisis: dict[str, Any]) -> str:
    facts = str(crisis.get("crisisFacts") or crisis.get("facts") or "").strip()
    message = str(crisis.get("crisisMessage") or crisis.get("message") or "").strip()
    blob = facts or message
    if not blob:
        return "Important update"
    line = blob.splitlines()[0].strip()
    return _truncate(line or "Important update", 90)


def _fallback_subhead(kit: dict[str, Any] | None, crisis: dict[str, Any]) -> str:
    kit = kit or {}
    tag = _truncate(str(kit.get("tagline") or ""), 72)
    if tag:
        return tag
    facts = str(crisis.get("crisisFacts") or crisis.get("facts") or "")
    for line in facts.splitlines():
        line = line.strip()
        if line and len(line) > 12:
            return _truncate(line, 72)
    return ""


def _fallback_hero_and_layout(
    kit: dict[str, Any] | None,
) -> tuple[HeroStrategy, LayoutRecipe]:
    kit = kit or {}
    if kit.get("heroBusy") or kit.get("heroBrandMark"):
        return "gradient_from_palette", "gradient-brand"
    if kit.get("heroImageUrl") and not kit.get("heroBrandMark"):
        return "use_kit_photo", "photo-hero-type"
    if kit.get("logoUrl") or kit.get("logoSvg"):
        return "gradient_from_palette", "minimal-wordmark"
    return "gradient_from_palette", "gradient-brand"


def _fallback_logo_treatment(
    kit: dict[str, Any] | None,
    hero_strategy: HeroStrategy,
    layout: LayoutRecipe,
) -> LogoTreatment:
    if layout == "photo-hero-type" and hero_strategy == "use_kit_photo":
        return "wordmark-white"
    if layout in ("gradient-brand", "minimal-wordmark"):
        return "wordmark-white"
    return "wordmark-dark"


def build_fallback_brief(
    kit: dict[str, Any] | None,
    crisis: dict[str, Any],
    format: str = "linkedin-1200x627",
) -> dict[str, Any]:
    """Deterministic brief when LLM is unavailable."""
    kit = kit or {}
    crisis = crisis or {}
    headline = _first_fact_line(crisis)
    subhead = _fallback_subhead(kit, crisis)
    hero_strategy, layout = _fallback_hero_and_layout(kit)
    logo = _fallback_logo_treatment(kit, hero_strategy, layout)
    emphasis = _tone_to_emphasis(crisis.get("tone"))
    site = kit.get("siteName") or "the organization"
    rationale = (
        f"Rule-based brief for {format}: lead with confirmed crisis facts, "
        f"use {layout.replace('-', ' ')} layout aligned with {site} kit signals."
    )
    brief: dict[str, Any] = {
        "headline": headline,
        "subhead": subhead,
        "layoutRecipe": layout,
        "heroStrategy": hero_strategy,
        "logoTreatment": logo,
        "emphasis": emphasis,
        "rationale": rationale,
    }
    return _normalize_brief(brief)


def _normalize_brief(raw: dict[str, Any]) -> dict[str, Any]:
    layout = raw.get("layoutRecipe") or "gradient-brand"
    if layout not in CREATIVE_BRIEF_JSON_SCHEMA["properties"]["layoutRecipe"]["enum"]:
        layout = "gradient-brand"
    hero = raw.get("heroStrategy") or "gradient_from_palette"
    if hero not in CREATIVE_BRIEF_JSON_SCHEMA["properties"]["heroStrategy"]["enum"]:
        hero = "gradient_from_palette"
    logo = raw.get("logoTreatment") or "wordmark-white"
    if logo not in CREATIVE_BRIEF_JSON_SCHEMA["properties"]["logoTreatment"]["enum"]:
        logo = "wordmark-white"
    emphasis = raw.get("emphasis") or "calm"
    if emphasis not in CREATIVE_BRIEF_JSON_SCHEMA["properties"]["emphasis"]["enum"]:
        emphasis = "calm"
    out: dict[str, Any] = {
        "headline": _truncate(str(raw.get("headline") or "Important update"), 90),
        "subhead": _truncate(str(raw.get("subhead") or ""), 72),
        "layoutRecipe": layout,
        "heroStrategy": hero,
        "logoTreatment": logo,
        "emphasis": emphasis,
        "rationale": _truncate(str(raw.get("rationale") or "Creative brief for this poster."), 220),
    }
    cta = raw.get("cta")
    if cta and str(cta).strip():
        out["cta"] = _truncate(str(cta), 48)
    return out


def _llm_prompt(
    kit: dict[str, Any] | None,
    crisis: dict[str, Any],
    format: str,
) -> str:
    crisis = crisis or {}
    facts = crisis.get("crisisFacts") or crisis.get("facts") or ""
    message = crisis.get("crisisMessage") or crisis.get("message") or ""
    tone = crisis.get("tone") or "factual"
    return f"""You are a senior brand marketing strategist drafting a LinkedIn crisis/update poster brief.

Output JSON only matching the schema. Copy must be factual, non-sensational, and appropriate for corporate communications.

Format: {format}
Tone from user: {tone}

Communication kit (scraped brand signals):
{kit_summary_for_prompt(kit)}

Crisis message (primary):
{message or "(use facts below)"}

Confirmed crisis facts:
{facts or "(none provided)"}

Choose layoutRecipe, heroStrategy, and logoTreatment so the poster feels on-brand and readable at 1200×627.
Avoid full-bleed competitor OG artwork when heroBrandMark is true; prefer gradient or minimal wordmark layouts.
Headline should state the update clearly; subhead supports with brand context or next step."""


def _parse_llm_json(content: str) -> dict[str, Any]:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("LLM response was not a JSON object")
    return _normalize_brief(data)


def _anthropic_tool_schema() -> dict[str, Any]:
    schema = dict(CREATIVE_BRIEF_JSON_SCHEMA)
    schema.pop("additionalProperties", None)
    return schema


def _call_openai_compatible(
    kit: dict[str, Any] | None,
    crisis: dict[str, Any],
    format: str,
    *,
    api_key: str,
    model: str,
    base_url: str,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    url = f"{base_url}/chat/completions"
    body = {
        "model": model,
        "temperature": 0.35,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You produce concise marketing creative briefs as strict JSON. "
                    "No markdown, no commentary outside JSON."
                ),
            },
            {"role": "user", "content": _llm_prompt(kit, crisis, format)},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "creative_brief",
                "strict": True,
                "schema": CREATIVE_BRIEF_JSON_SCHEMA,
            },
        },
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=LLM_TIMEOUT_SEC) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    choices = payload.get("choices") or []
    if not choices:
        raise ValueError("LLM returned no choices")
    message = choices[0].get("message") or {}
    content = message.get("content") or ""
    return _parse_llm_json(content)


def _call_anthropic(
    kit: dict[str, Any] | None,
    crisis: dict[str, Any],
    format: str,
    *,
    api_key: str,
    model: str,
) -> dict[str, Any]:
    url = f"{ANTHROPIC_API_BASE}/messages"
    body = {
        "model": model,
        "max_tokens": 1200,
        "system": (
            "You produce concise marketing creative briefs. "
            "Use the submit_creative_brief tool with complete structured fields."
        ),
        "messages": [{"role": "user", "content": _llm_prompt(kit, crisis, format)}],
        "tools": [
            {
                "name": "submit_creative_brief",
                "description": "Submit the poster creative brief JSON fields.",
                "input_schema": _anthropic_tool_schema(),
            }
        ],
        "tool_choice": {"type": "tool", "name": "submit_creative_brief"},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=LLM_TIMEOUT_SEC) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    for block in payload.get("content") or []:
        if block.get("type") == "tool_use" and block.get("name") == "submit_creative_brief":
            tool_input = block.get("input")
            if isinstance(tool_input, dict):
                return _normalize_brief(tool_input)
    raise ValueError("Anthropic response missing creative brief tool output")


def _call_llm(
    provider: LlmProvider,
    kit: dict[str, Any] | None,
    crisis: dict[str, Any],
    format: str,
    *,
    api_key: str,
    model: str,
) -> dict[str, Any]:
    if provider == "anthropic":
        return _call_anthropic(kit, crisis, format, api_key=api_key, model=model)
    if provider == "openrouter":
        referer = os.environ.get("OPENROUTER_HTTP_REFERER", "https://github.com/asseukihuh/AI-WebApp")
        title = os.environ.get("OPENROUTER_APP_TITLE", "CommMaker")
        return _call_openai_compatible(
            kit,
            crisis,
            format,
            api_key=api_key,
            model=model,
            base_url=OPENROUTER_API_BASE,
            extra_headers={
                "HTTP-Referer": referer,
                "X-Title": title,
            },
        )
    return _call_openai_compatible(
        kit,
        crisis,
        format,
        api_key=api_key,
        model=model,
        base_url=OPENAI_API_BASE,
    )


def build_creative_brief(
    kit: dict[str, Any] | None,
    crisis: dict[str, Any],
    format: str = "linkedin-1200x627",
) -> dict[str, Any]:
    """Build brief. Returns ``brief``, ``source`` (`llm`|`fallback`), optional ``model`` / ``provider``."""
    provider = resolve_llm_provider()
    if not provider:
        return {
            "brief": build_fallback_brief(kit, crisis, format),
            "source": "fallback",
        }
    api_key = api_key_for_provider(provider)
    if not api_key:
        return {
            "brief": build_fallback_brief(kit, crisis, format),
            "source": "fallback",
        }
    model = resolve_llm_model(provider)
    try:
        brief = _call_llm(
            provider,
            kit,
            crisis,
            format,
            api_key=api_key,
            model=model,
        )
        return {
            "brief": brief,
            "source": "llm",
            "model": model,
            "provider": provider,
        }
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        json.JSONDecodeError,
        ValueError,
        TimeoutError,
        OSError,
    ):
        return {
            "brief": build_fallback_brief(kit, crisis, format),
            "source": "fallback",
        }
