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
HeroStrategy = Literal[
    "use_kit_photo",
    "ideogram_generate",
    "gradient_from_palette",
    "solid",
    "none",
]
IdeogramLayers = Literal["background-only", "background-plus-accent"]
LogoTreatment = Literal["wordmark-white", "wordmark-dark", "symbol-only"]
Emphasis = Literal["calm", "urgent", "celebratory"]
BriefSource = Literal["llm", "fallback"]
FallbackReason = Literal["no_provider", "no_api_key", "llm_error"]
LlmProvider = Literal["openai", "anthropic", "openrouter"]

# Frontier defaults — never mini/nano (quality for marketing copy + layout decisions).
# Opus override (not a default): COMMMAKER_LLM_MODEL=claude-opus-4-8
FRONTIER_MODEL_BY_PROVIDER: dict[LlmProvider, str] = {
    "anthropic": "claude-sonnet-5-5",
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
            "enum": [
                "use_kit_photo",
                "ideogram_generate",
                "gradient_from_palette",
                "solid",
                "none",
            ],
        },
        "heroImagePrompt": {"type": "string"},
        "accentImagePrompt": {"type": "string"},
        "ideogramLayers": {
            "type": "string",
            "enum": ["background-only", "background-plus-accent"],
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


def _normalize_api_key(raw: str | None) -> str:
    """Strip whitespace and UTF-8 BOM from env-sourced API keys."""
    if not raw:
        return ""
    return raw.strip().lstrip("\ufeff")


_ANTHROPIC_CONSOLE_KEY_PREFIXES = (
    "sk-ant-usr-",
    "sk-ant-svc-",
    "sk-ant-admin-",
    "sk-ant-api",
)


def _anthropic_uses_bearer_auth(api_key: str) -> bool:
    return any(api_key.startswith(prefix) for prefix in _ANTHROPIC_CONSOLE_KEY_PREFIXES)


def _anthropic_request_headers(api_key: str) -> dict[str, str]:
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    if _anthropic_uses_bearer_auth(api_key):
        headers["Authorization"] = f"Bearer {api_key}"
    workspace_id = _normalize_api_key(os.environ.get("ANTHROPIC_WORKSPACE_ID"))
    if workspace_id:
        headers["anthropic-workspace-id"] = workspace_id
    return headers


def resolve_llm_provider() -> LlmProvider | None:
    """Pick provider from ``COMMMAKER_LLM_PROVIDER`` or installed API keys."""
    forced = (os.environ.get("COMMMAKER_LLM_PROVIDER") or "").strip().lower()
    if forced in FRONTIER_MODEL_BY_PROVIDER:
        return forced  # type: ignore[return-value]
    if _normalize_api_key(os.environ.get("ANTHROPIC_API_KEY")):
        return "anthropic"
    if _normalize_api_key(os.environ.get("OPENROUTER_API_KEY")):
        return "openrouter"
    if _normalize_api_key(os.environ.get("OPENAI_API_KEY")):
        return "openai"
    return None


def resolve_llm_model(provider: LlmProvider) -> str:
    override = (os.environ.get("COMMMAKER_LLM_MODEL") or "").strip()
    if override:
        return override
    return default_model_for_provider(provider)


def api_key_for_provider(provider: LlmProvider) -> str:
    if provider == "anthropic":
        return _normalize_api_key(os.environ.get("ANTHROPIC_API_KEY"))
    if provider == "openrouter":
        return _normalize_api_key(os.environ.get("OPENROUTER_API_KEY"))
    return _normalize_api_key(os.environ.get("OPENAI_API_KEY"))


def _http_error_body(exc: urllib.error.HTTPError, limit: int = 240) -> str:
    try:
        if exc.fp is None:
            return ""
        raw = exc.fp.read()
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    except Exception:
        return ""
    return _truncate(text, limit)


def _safe_error_detail(
    exc: BaseException,
    *,
    provider: LlmProvider | None = None,
) -> str:
    """Short, non-secret diagnostic for UI when LLM call fails."""
    if isinstance(exc, urllib.error.HTTPError):
        body = _http_error_body(exc)
        if exc.code == 404 and provider == "anthropic":
            hint = "HTTP 404 — check COMMMAKER_LLM_MODEL (Sonnet 4 IDs retired)"
            return f"{hint}: {body}" if body else hint
        detail = f"HTTP {exc.code}"
        return f"{detail}: {body}" if body else detail
    return type(exc).__name__


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
        if (os.environ.get("IDEOGRAM_API_KEY") or "").strip():
            return "ideogram_generate", "photo-hero-type"
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
    if layout == "photo-hero-type" and hero_strategy in (
        "use_kit_photo",
        "ideogram_generate",
    ):
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
    if hero_strategy == "ideogram_generate":
        brief["heroImagePrompt"] = _fallback_ideogram_prompt(kit, crisis)
        brief["ideogramLayers"] = effective_ideogram_layers(brief)
        if brief["ideogramLayers"] == "background-plus-accent":
            brief["accentImagePrompt"] = _fallback_accent_prompt(kit, crisis)
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
    hero_prompt = raw.get("heroImagePrompt")
    accent_prompt = raw.get("accentImagePrompt")
    if hero == "ideogram_generate":
        if hero_prompt and str(hero_prompt).strip():
            out["heroImagePrompt"] = _truncate(str(hero_prompt), 480)
        else:
            out["heroImagePrompt"] = _truncate(
                str(raw.get("heroImagePrompt") or "Professional brand scene for LinkedIn update."),
                480,
            )
        layers = effective_ideogram_layers(raw)
        out["ideogramLayers"] = layers
        if layers == "background-plus-accent":
            if accent_prompt and str(accent_prompt).strip():
                out["accentImagePrompt"] = _truncate(str(accent_prompt), 480)
            else:
                out["accentImagePrompt"] = _truncate(
                    str(
                        raw.get("accentImagePrompt")
                        or "Isolated brand illustration, no text or logo."
                    ),
                    480,
                )
    elif hero_prompt and str(hero_prompt).strip():
        out["heroImagePrompt"] = _truncate(str(hero_prompt), 480)
    return out


def _kit_color_phrase(kit: dict[str, Any] | None) -> str:
    kit = kit or {}
    colors = kit.get("accentColors") or kit.get("colors") or []
    if not colors:
        return "brand-appropriate colors"
    return ", ".join(str(c) for c in colors[:4])


def effective_ideogram_layers(
    brief: dict[str, Any] | None,
    *,
    ideogram_key_set: bool | None = None,
) -> IdeogramLayers:
    """Layer mode for ``ideogram_generate`` briefs."""
    if not brief or brief.get("heroStrategy") != "ideogram_generate":
        return "background-only"
    raw = brief.get("ideogramLayers")
    if raw in ("background-only", "background-plus-accent"):
        return raw  # type: ignore[return-value]
    if ideogram_key_set is None:
        ideogram_key_set = bool((os.environ.get("IDEOGRAM_API_KEY") or "").strip())
    if ideogram_key_set:
        return "background-plus-accent"
    return "background-only"


def _fallback_ideogram_prompt(
    kit: dict[str, Any] | None,
    crisis: dict[str, Any],
) -> str:
    kit = kit or {}
    site = kit.get("siteName") or "the organization"
    colors = _kit_color_phrase(kit)
    tone = (crisis.get("tone") or "factual").strip()
    facts = str(crisis.get("crisisFacts") or crisis.get("facts") or "").strip()
    context = _truncate(facts.splitlines()[0] if facts else "corporate update", 120)
    return (
        f"Editorial marketing photograph for {site}, calm {tone} corporate communications, "
        f"abstract professional scene (no UI screenshots, no homepage mockups), "
        f"palette accents {colors}, subtle depth, negative space in lower-left for headline text, "
        f"context: {context}"
    )


def _fallback_accent_prompt(
    kit: dict[str, Any] | None,
    crisis: dict[str, Any],
) -> str:
    kit = kit or {}
    site = kit.get("siteName") or "the organization"
    colors = _kit_color_phrase(kit)
    tone = (crisis.get("tone") or "factual").strip()
    return (
        f"Single editorial illustration subject for {site}, calm {tone} corporate tone, "
        f"no text, no logo, no wordmarks, palette accents {colors}, "
        f"isolated focal subject suitable for right side of a poster"
    )


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
Avoid full-bleed competitor OG artwork when heroBrandMark is true or heroBusy is true.
For LinkedIn crisis/update posts when the scraped kit hero is busy UI chrome or a brand-mark OG image, prefer heroStrategy ideogram_generate with layoutRecipe photo-hero-type.
When heroStrategy is ideogram_generate:
- Set ideogramLayers to background-plus-accent when a distinct subject helps the story; background-only for abstract texture-only heroes.
- heroImagePrompt: full-bleed background scene (include siteName and kit color hex values). Always leave the lower-left third clear/uncluttered for headline type. No text in the image.
- When ideogramLayers is background-plus-accent, set accentImagePrompt to a single illustration or photo subject for the right/center (no text, no logo — the scraped SVG logo is added separately).
- The accent must not duplicate the brand logo or wordmark.
Never describe homepage screenshots, browser chrome, or literal OG triangles.
When heroStrategy is not ideogram_generate, omit heroImagePrompt, accentImagePrompt, and ideogramLayers.
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


def _anthropic_submit_tool() -> dict[str, Any]:
    return {
        "name": "submit_creative_brief",
        "description": "Submit the poster creative brief JSON fields.",
        "input_schema": _anthropic_tool_schema(),
        "strict": True,
    }


def _anthropic_messages_body(
    kit: dict[str, Any] | None,
    crisis: dict[str, Any],
    format: str,
    *,
    model: str,
) -> dict[str, Any]:
    return {
        "model": model,
        "max_tokens": 1200,
        "system": (
            "You produce concise marketing creative briefs. "
            "You MUST call submit_creative_brief exactly once with complete structured fields."
        ),
        "messages": [{"role": "user", "content": _llm_prompt(kit, crisis, format)}],
        "tools": [_anthropic_submit_tool()],
        "tool_choice": {"type": "auto"},
    }


def _brief_from_anthropic_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    for block in payload.get("content") or []:
        if block.get("type") == "tool_use" and block.get("name") == "submit_creative_brief":
            tool_input = block.get("input")
            if isinstance(tool_input, dict):
                return _normalize_brief(tool_input)
    return None


def _text_from_anthropic_payload(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for block in payload.get("content") or []:
        if block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    return "\n".join(parts).strip()


def _post_anthropic_messages(body: dict[str, Any], *, api_key: str) -> dict[str, Any]:
    url = f"{ANTHROPIC_API_BASE}/messages"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=_anthropic_request_headers(api_key),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=LLM_TIMEOUT_SEC) as resp:
        return json.loads(resp.read().decode("utf-8"))


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
                    "No markdown, no commentary outside JSON. "
                    "For ideogram_generate heroes, always leave the lower-left clear for type; "
                    "accent illustrations must not include logos or duplicate the wordmark."
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
    body = _anthropic_messages_body(kit, crisis, format, model=model)
    payload: dict[str, Any] = {}
    for _ in range(2):
        payload = _post_anthropic_messages(body, api_key=api_key)
        brief = _brief_from_anthropic_payload(payload)
        if brief is not None:
            return brief
    text = _text_from_anthropic_payload(payload)
    if text:
        return _parse_llm_json(text)
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
            "fallbackReason": "no_provider",
            "errorDetail": "ConfigurationError",
        }
    api_key = api_key_for_provider(provider)
    if not api_key:
        return {
            "brief": build_fallback_brief(kit, crisis, format),
            "source": "fallback",
            "fallbackReason": "no_api_key",
            "errorDetail": "MissingApiKeyError",
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
    ) as exc:
        return {
            "brief": build_fallback_brief(kit, crisis, format),
            "source": "fallback",
            "fallbackReason": "llm_error",
            "errorDetail": _safe_error_detail(exc, provider=provider),
            "provider": provider,
        }
