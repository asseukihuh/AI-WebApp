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

from poster_design import (
    CTA_STYLES,
    HEADLINE_SCALES,
    HEADLINE_WEIGHTS,
    LAYOUT_TEMPLATES,
    MAX_CHARS,
    MAX_WORDS,
    TEMPLATES,
    brand_roles,
    clamp_words,
    default_template_for,
    headline_scale_for,
    kit_hero_unsuitable,
    template_hint_from_profile,
)

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
        "layoutTemplate": {"type": "string", "enum": list(LAYOUT_TEMPLATES)},
        "headlineScale": {"type": "string", "enum": list(HEADLINE_SCALES)},
        "headlineWeight": {"type": "string", "enum": list(HEADLINE_WEIGHTS)},
        "eyebrow": {"type": "string"},
        "ctaStyle": {"type": "string", "enum": list(CTA_STYLES)},
        "rationale": {"type": "string"},
    },
    "required": [
        "headline",
        "subhead",
        "cta",
        "layoutRecipe",
        "heroStrategy",
        "heroImagePrompt",
        "accentImagePrompt",
        "ideogramLayers",
        "logoTreatment",
        "emphasis",
        "layoutTemplate",
        "headlineScale",
        "headlineWeight",
        "eyebrow",
        "ctaStyle",
        "rationale",
    ],
}

ART_DIRECTOR_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "score": {"type": "integer"},
        "issues": {"type": "array", "items": {"type": "string"}},
        "headline": {"type": "string"},
        "subhead": {"type": "string"},
        "cta": {"type": "string"},
        "eyebrow": {"type": "string"},
        "headlineScale": {"type": "string", "enum": list(HEADLINE_SCALES)},
        "headlineWeight": {"type": "string", "enum": list(HEADLINE_WEIGHTS)},
        "ctaStyle": {"type": "string", "enum": list(CTA_STYLES)},
    },
    "required": [
        "score",
        "issues",
        "headline",
        "subhead",
        "cta",
        "eyebrow",
        "headlineScale",
        "headlineWeight",
        "ctaStyle",
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
        f"heroImageKind: {kit.get('heroImageKind') or '(unknown)'}",
        f"kitHeroUsableAsBackground: {bool(kit.get('heroImageUrl')) and not kit_hero_unsuitable(kit)}",
        f"headlineFromSite: {kit.get('headline') or '(none)'}",
    ]
    from brand_profile import brand_profile_prompt_lines

    lines.extend(brand_profile_prompt_lines(kit))
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
    """Headline: the crisis message when it fits the headline limit, else the first fact."""
    facts = str(crisis.get("crisisFacts") or crisis.get("facts") or "").strip()
    message = str(crisis.get("crisisMessage") or crisis.get("message") or "").strip()
    message_line = message.splitlines()[0].strip() if message else ""
    if message_line and len(message_line.split()) <= MAX_WORDS["headline"]:
        return _truncate(message_line, 90)
    blob = facts or message
    if not blob:
        return "Important update"
    line = blob.splitlines()[0].strip()
    return _truncate(line or "Important update", 90)


def _fallback_subhead(kit: dict[str, Any] | None, crisis: dict[str, Any]) -> str:
    """Subhead: the first confirmed fact that isn't the headline; the kit tagline only as a last resort."""
    kit = kit or {}
    headline = _first_fact_line(crisis).casefold()
    facts = str(crisis.get("crisisFacts") or crisis.get("facts") or "")
    for line in facts.splitlines():
        line = line.strip()
        if line and len(line) > 12 and line.casefold() != headline:
            return clamp_words(line, MAX_WORDS["subline"], MAX_CHARS["subline"])
    return clamp_words(str(kit.get("tagline") or "").strip(), MAX_WORDS["subline"], MAX_CHARS["subline"])


def _fallback_hero_and_layout(
    kit: dict[str, Any] | None,
) -> tuple[HeroStrategy, LayoutRecipe]:
    kit = kit or {}
    if kit.get("heroImageUrl") and kit_hero_unsuitable(kit):
        if (os.environ.get("IDEOGRAM_API_KEY") or "").strip():
            return "ideogram_generate", "photo-hero-type"
        return "gradient_from_palette", "gradient-brand"
    if kit.get("heroImageUrl"):
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


_FALLBACK_EYEBROW: dict[str, str] = {
    "urgent": "Service update",
    "celebratory": "Announcement",
    "calm": "Update",
}
_FALLBACK_CTA: dict[str, str] = {
    "urgent": "Read the update",
    "celebratory": "Learn more",
    "calm": "Read more",
}


def fallback_layout_template(
    kit: dict[str, Any] | None,
    *,
    layout_recipe: str,
    hero_strategy: str,
    emphasis: str,
    brand_profile: dict[str, Any] | None = None,
) -> str:
    has_image = hero_strategy in ("use_kit_photo", "ideogram_generate")
    ck = (kit or {}).get("communicationKit") if isinstance(kit, dict) else None
    if isinstance(ck, dict) and ck.get("thinSite") and not has_image:
        return "device-stage"
    hint = template_hint_from_profile(brand_profile)
    if hint and (has_image or hint == "centered-statement"):
        return hint
    return default_template_for(
        layout_recipe=layout_recipe,
        has_image=has_image,
        emphasis=emphasis,
        monochrome=brand_roles(kit, brand_profile).monochrome,
    )


def build_fallback_brief(
    kit: dict[str, Any] | None,
    crisis: dict[str, Any],
    format: str = "linkedin-1200x627",
    brand_profile: dict[str, Any] | None = None,
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
        "cta": _FALLBACK_CTA[emphasis],
        "layoutRecipe": layout,
        "heroStrategy": hero_strategy,
        "logoTreatment": logo,
        "emphasis": emphasis,
        "layoutTemplate": fallback_layout_template(
            kit,
            layout_recipe=layout,
            hero_strategy=hero_strategy,
            emphasis=emphasis,
            brand_profile=brand_profile,
        ),
        "eyebrow": _FALLBACK_EYEBROW[emphasis],
        "ctaStyle": "pill",
        "rationale": rationale,
    }
    if hero_strategy == "ideogram_generate":
        brief["heroImagePrompt"] = _fallback_ideogram_prompt(kit, crisis)
        brief["ideogramLayers"] = effective_ideogram_layers(brief)
        if brief["ideogramLayers"] == "background-plus-accent":
            brief["accentImagePrompt"] = _fallback_accent_prompt(kit, crisis)
    brief = _normalize_brief(brief)
    return coerce_ideogram_for_unsuitable_kit_hero(brief, kit, crisis)


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
    headline = _truncate(str(raw.get("headline") or "Important update"), 90)
    out: dict[str, Any] = {
        "headline": headline,
        "subhead": clamp_words(str(raw.get("subhead") or ""), MAX_WORDS["subline"], MAX_CHARS["subline"]),
        "layoutRecipe": layout,
        "heroStrategy": hero,
        "logoTreatment": logo,
        "emphasis": emphasis,
        "rationale": _truncate(str(raw.get("rationale") or "Creative brief for this poster."), 220),
    }
    cta = raw.get("cta")
    if cta and str(cta).strip():
        out["cta"] = clamp_words(str(cta), MAX_WORDS["cta"], MAX_CHARS["cta"]).rstrip("…")
    template = raw.get("layoutTemplate")
    if template in TEMPLATES:
        out["layoutTemplate"] = template
    scale = raw.get("headlineScale")
    out["headlineScale"] = scale if scale in HEADLINE_SCALES else headline_scale_for(headline)
    weight = raw.get("headlineWeight")
    out["headlineWeight"] = (
        weight if weight in HEADLINE_WEIGHTS else ("bold" if out["headlineScale"] == "md" else "extrabold")
    )
    eyebrow = clamp_words(str(raw.get("eyebrow") or ""), MAX_WORDS["eyebrow"], MAX_CHARS["eyebrow"])
    if eyebrow:
        out["eyebrow"] = eyebrow.rstrip("…")
    cta_style = raw.get("ctaStyle")
    out["ctaStyle"] = cta_style if cta_style in CTA_STYLES else ("pill" if out.get("cta") else "none")
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


def _ideogram_api_key_set() -> bool:
    return bool((os.environ.get("IDEOGRAM_API_KEY") or "").strip())


def _crisis_context_present(crisis: dict[str, Any] | None) -> bool:
    crisis = crisis or {}
    facts = str(crisis.get("crisisFacts") or crisis.get("facts") or "").strip()
    message = str(crisis.get("crisisMessage") or crisis.get("message") or "").strip()
    return bool(facts or message)


def prefer_ideogram_for_crisis_post(crisis: dict[str, Any] | None) -> bool:
    """When Ideogram is configured, upgrade flat gradient heroes for crisis/update flows."""
    if not _ideogram_api_key_set():
        return False
    pref = (os.environ.get("COMMMAKER_PREFER_IDEOGRAM") or "").strip().lower()
    if pref in ("1", "true", "yes", "on"):
        return True
    return _crisis_context_present(crisis)


def coerce_ideogram_for_unsuitable_kit_hero(
    brief: dict[str, Any],
    kit: dict[str, Any] | None,
    crisis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Prefer Ideogram when scraped heroes are busy UI or OG brand marks, or when a
    crisis brief would otherwise render as a flat palette gradient.

    The LLM often picks ``gradient_from_palette`` for crisis posts (including when
    the kit hero is neither busy nor a brand mark); without coercion that yields a
    flat lavender + logo + type poster instead of a Pomelli-style abstract hero.
    """
    kit = kit or {}
    crisis = crisis or {}
    if not _ideogram_api_key_set():
        return brief
    hero = brief.get("heroStrategy") or ""
    if hero == "ideogram_generate":
        return brief
    unsuitable_kit = bool(kit.get("heroImageUrl")) and kit_hero_unsuitable(kit)
    crisis_gradient = prefer_ideogram_for_crisis_post(crisis) and hero == "gradient_from_palette"
    if not unsuitable_kit and not crisis_gradient:
        return brief
    if hero not in ("use_kit_photo", "gradient_from_palette", "solid", "none"):
        return brief
    upgraded: dict[str, Any] = dict(brief)
    upgraded["heroStrategy"] = "ideogram_generate"
    upgraded["layoutRecipe"] = "photo-hero-type"
    if not str(upgraded.get("heroImagePrompt") or "").strip():
        if crisis_gradient and not unsuitable_kit:
            upgraded["heroImagePrompt"] = _fallback_ideogram_abstract_prompt(kit, crisis)
        else:
            upgraded["heroImagePrompt"] = _fallback_ideogram_prompt(kit, crisis)
    if crisis_gradient and not unsuitable_kit:
        upgraded["ideogramLayers"] = "background-only"
    else:
        upgraded["ideogramLayers"] = effective_ideogram_layers(upgraded)
    if upgraded["ideogramLayers"] == "background-plus-accent":
        if not str(upgraded.get("accentImagePrompt") or "").strip():
            upgraded["accentImagePrompt"] = _fallback_accent_prompt(kit, crisis)
    return _normalize_brief(upgraded)


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


def _fallback_ideogram_abstract_prompt(
    kit: dict[str, Any] | None,
    crisis: dict[str, Any],
) -> str:
    tone = (crisis.get("tone") or "factual").strip()
    return (
        "Abstract flowing ribbons of translucent colour over a soft diagonal gradient with "
        f"subtle grain, {tone} corporate mood, smooth glass-like layered planes"
    )


def _fallback_ideogram_prompt(
    kit: dict[str, Any] | None,
    crisis: dict[str, Any],
) -> str:
    tone = (crisis.get("tone") or "factual").strip()
    return (
        f"Editorial still life of soft geometric glass and paper forms, {tone} corporate "
        "mood, shallow depth of field, gentle shadows, premium minimal set design"
    )


def _fallback_accent_prompt(
    kit: dict[str, Any] | None,
    crisis: dict[str, Any],
) -> str:
    tone = (crisis.get("tone") or "factual").strip()
    return (
        f"A single sculptural abstract object made of smooth layered glass planes, {tone} mood"
    )


def brand_profile_summary_for_prompt(brand_profile: dict[str, Any] | None) -> str:
    """Optional AI-vision brand profile (aesthetic, imageryStyle, toneOfVoice, layoutTraits …)."""
    if not isinstance(brand_profile, dict) or not brand_profile:
        return ""
    lines: list[str] = []
    for key in ("aesthetic", "imageryStyle", "toneOfVoice", "layoutTraits", "palette", "typography"):
        value = brand_profile.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, (list, dict)):
            value = json.dumps(value, ensure_ascii=False)
        lines.append(f"{key}: {_truncate(str(value), 240)}")
    return "\n".join(lines)


def _design_system_prompt() -> str:
    templates = "\n".join(
        f"- {name}: {tpl.ideogram_layout_note}; text {tpl.align}-aligned"
        + (" on a solid brand panel" if tpl.surface == "panel" else "")
        + (" on a rounded card" if tpl.surface == "card" else "")
        for name, tpl in TEMPLATES.items()
    )
    return f"""Design system (Adobe fundamentals: hierarchy, contrast, alignment, balance, whitespace, repetition, emphasis):
layoutTemplate options:
{templates}
- full-bleed-scrim / split-text-left / text-panel need an image (use_kit_photo or ideogram_generate); centered-statement works on brand gradients.
- device-stage is for a thin communication kit: colour block, one focal graphic device, no photograph required.
- Linearity: one focal point, a short hook (≤ 8 words), scale contrast, asymmetry, layered depth, colour blocking, deliberate whitespace, type that survives a phone thumbnail, logo at clear-space size.
- Copy limits: eyebrow ≤ {MAX_WORDS["eyebrow"]} words (short label, e.g. "New plan"), headline ≤ {MAX_WORDS["headline"]} words (ideal 4–8, one idea), subhead ≤ {MAX_WORDS["subline"]} words and one sentence, cta ≤ {MAX_WORDS["cta"]} words (verb first, e.g. "See pricing"). No hashtags, no URLs.
- headlineScale: xl for ≤ 4 words, lg for 5–7, md for 8–10. headlineWeight: extrabold for xl/lg, bold for md.
- ctaStyle: pill (default), outline (when the brand is minimal/monochrome), none (only for somber crisis notices).
- One focal point: the headline (statement) or the image subject (split / full-bleed). The real logo is placed by the compiler; never ask for a logo in imagery."""


def _llm_prompt(
    kit: dict[str, Any] | None,
    crisis: dict[str, Any],
    format: str,
    brand_profile: dict[str, Any] | None = None,
) -> str:
    crisis = crisis or {}
    facts = crisis.get("crisisFacts") or crisis.get("facts") or ""
    message = crisis.get("crisisMessage") or crisis.get("message") or ""
    tone = crisis.get("tone") or "factual"
    kit_profile = (kit or {}).get("brandProfile") if isinstance(kit, dict) else None
    # kit_summary_for_prompt already renders kit.brandProfile (brand_profile_prompt_lines).
    profile = "" if brand_profile == kit_profile else brand_profile_summary_for_prompt(brand_profile)
    profile_block = f"\nBrand profile (AI vision analysis; prefer over scraped signals):\n{profile}\n" if profile else ""
    ck = (kit or {}).get("communicationKit") if isinstance(kit, dict) else None
    ck_block = ""
    if isinstance(ck, dict) and ck.get("devices"):
        kinds = ", ".join(str(d.get("kind") or "") for d in ck["devices"][:4] if isinstance(d, dict))
        motif = ck.get("layoutMotif") or {}
        ck_block = (
            f"\nDesigned communication kit: sector {ck.get('sector')}, devices {kinds}, "
            f"blocking {motif.get('blocking')}. Use this palette and these devices; do not invent another.\n"
        )
    return f"""You are a senior brand marketing strategist and art director drafting a LinkedIn crisis/update poster brief.

Output JSON only matching the schema. Copy must be factual, non-sensational, and appropriate for corporate communications.

Format: {format}
Tone from user: {tone}

Communication kit (scraped brand signals):
{kit_summary_for_prompt(kit)}
{profile_block}{ck_block}
Crisis message (primary):
{message or "(use facts below)"}

Confirmed crisis facts:
{facts or "(none provided)"}

{_design_system_prompt()}

Choose layoutRecipe, layoutTemplate, heroStrategy, and logoTreatment so the poster feels on-brand and readable at 1200×627.
Only choose heroStrategy use_kit_photo when kitHeroUsableAsBackground is true; og:image social cards usually contain the logo and headline text.
For LinkedIn crisis/update posts when the scraped kit hero is busy UI chrome or a brand-mark OG image, prefer heroStrategy ideogram_generate with layoutRecipe photo-hero-type.
For crisis/update posts when a flat gradient would feel empty, prefer ideogram_generate with abstract brand gradients, soft textures, or calm editorial backgrounds (no people, no crowds, no unverified news imagery, no fake event photos). Use background-only ideogramLayers for texture-only heroes.
When heroStrategy is ideogram_generate:
- heroImagePrompt: describe only the visual scene (subject, materials, shapes, lighting, mood) in one or two sentences. Do NOT mention the company name, products, logos, wordmarks, letters, words, signs, screens or UI — the image model paints any name it reads. Composition, palette and the empty text zone are added automatically from layoutTemplate.
- Set ideogramLayers to background-plus-accent only when a distinct subject helps the story; background-only for abstract texture-only heroes and always for centered-statement.
- accentImagePrompt (background-plus-accent only): one isolated object, same rules as heroImagePrompt.
Never describe homepage screenshots, browser chrome, or literal OG triangles.
When heroStrategy is not ideogram_generate, set heroImagePrompt and accentImagePrompt to empty strings and ideogramLayers to background-only.
When cta is not needed, set cta to an empty string and ctaStyle to none.
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
    """Anthropic ``strict`` tools require ``additionalProperties: false`` on every object."""
    return CREATIVE_BRIEF_JSON_SCHEMA


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
    brand_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "model": model,
        "max_tokens": 1400,
        "system": (
            "You produce concise marketing creative briefs. "
            "You MUST call submit_creative_brief exactly once with complete structured fields."
        ),
        "messages": [
            {"role": "user", "content": _llm_prompt(kit, crisis, format, brand_profile)}
        ],
        "tools": [_anthropic_submit_tool()],
        "tool_choice": {"type": "auto"},
    }


def _tool_input_from_anthropic_payload(payload: dict[str, Any], tool_name: str) -> dict[str, Any] | None:
    for block in payload.get("content") or []:
        if block.get("type") == "tool_use" and block.get("name") == tool_name:
            tool_input = block.get("input")
            if isinstance(tool_input, dict):
                return tool_input
    return None


def _brief_from_anthropic_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    tool_input = _tool_input_from_anthropic_payload(payload, "submit_creative_brief")
    return _normalize_brief(tool_input) if tool_input is not None else None


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


def _openai_compatible_endpoint(provider: LlmProvider) -> tuple[str, dict[str, str]]:
    if provider == "openrouter":
        referer = os.environ.get("OPENROUTER_HTTP_REFERER", "https://github.com/asseukihuh/AI-WebApp")
        title = os.environ.get("OPENROUTER_APP_TITLE", "CommMaker")
        return OPENROUTER_API_BASE, {"HTTP-Referer": referer, "X-Title": title}
    return OPENAI_API_BASE, {}


def _post_openai_json_schema(
    *,
    system: str,
    user: str,
    schema_name: str,
    schema: dict[str, Any],
    api_key: str,
    model: str,
    base_url: str,
    extra_headers: dict[str, str] | None = None,
) -> str:
    body = {
        "model": model,
        "temperature": 0.35,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "strict": True, "schema": schema},
        },
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
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
    return message.get("content") or ""


def _call_openai_compatible(
    kit: dict[str, Any] | None,
    crisis: dict[str, Any],
    format: str,
    *,
    api_key: str,
    model: str,
    base_url: str,
    extra_headers: dict[str, str] | None = None,
    brand_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    content = _post_openai_json_schema(
        system=(
            "You produce concise marketing creative briefs as strict JSON. "
            "No markdown, no commentary outside JSON. "
            "Image prompts describe scenes only: never company names, logos, letters or words."
        ),
        user=_llm_prompt(kit, crisis, format, brand_profile),
        schema_name="creative_brief",
        schema=CREATIVE_BRIEF_JSON_SCHEMA,
        api_key=api_key,
        model=model,
        base_url=base_url,
        extra_headers=extra_headers,
    )
    return _parse_llm_json(content)


def _call_anthropic(
    kit: dict[str, Any] | None,
    crisis: dict[str, Any],
    format: str,
    *,
    api_key: str,
    model: str,
    brand_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = _anthropic_messages_body(kit, crisis, format, model=model, brand_profile=brand_profile)
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
    brand_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if provider == "anthropic":
        return _call_anthropic(
            kit, crisis, format, api_key=api_key, model=model, brand_profile=brand_profile
        )
    base_url, extra_headers = _openai_compatible_endpoint(provider)
    return _call_openai_compatible(
        kit,
        crisis,
        format,
        api_key=api_key,
        model=model,
        base_url=base_url,
        extra_headers=extra_headers or None,
        brand_profile=brand_profile,
    )


def build_creative_brief(
    kit: dict[str, Any] | None,
    crisis: dict[str, Any],
    format: str = "linkedin-1200x627",
    brand_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build brief. Returns ``brief``, ``source`` (`llm`|`fallback`), optional ``model`` / ``provider``.

    ``brand_profile`` (optional AI-vision profile) enriches the prompt and template choice.
    """
    provider = resolve_llm_provider()
    if not provider:
        return {
            "brief": build_fallback_brief(kit, crisis, format, brand_profile),
            "source": "fallback",
            "fallbackReason": "no_provider",
            "errorDetail": "ConfigurationError",
        }
    api_key = api_key_for_provider(provider)
    if not api_key:
        return {
            "brief": build_fallback_brief(kit, crisis, format, brand_profile),
            "source": "fallback",
            "fallbackReason": "no_api_key",
            "errorDetail": "MissingApiKeyError",
        }
    model = resolve_llm_model(provider)
    try:
        llm_kwargs: dict[str, Any] = {"api_key": api_key, "model": model}
        if brand_profile:
            llm_kwargs["brand_profile"] = brand_profile
        brief = _call_llm(provider, kit, crisis, format, **llm_kwargs)
        brief = coerce_ideogram_for_unsuitable_kit_hero(brief, kit, crisis)
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
            "brief": build_fallback_brief(kit, crisis, format, brand_profile),
            "source": "fallback",
            "fallbackReason": "llm_error",
            "errorDetail": _safe_error_detail(exc, provider=provider),
            "provider": provider,
        }


# --------------------------------------------------------------------------- art director pass


def art_director_enabled() -> bool:
    raw = (os.environ.get("COMMMAKER_ART_DIRECTOR") or "on").strip().lower()
    return raw not in ("0", "false", "no", "off") and resolve_llm_provider() is not None


def _art_director_prompt(brief: dict[str, Any], layout_meta: dict[str, Any]) -> str:
    audit = layout_meta.get("designAudit") or {}
    summary = {
        "brief": {
            k: brief.get(k)
            for k in (
                "headline",
                "subhead",
                "cta",
                "eyebrow",
                "layoutTemplate",
                "headlineScale",
                "headlineWeight",
                "ctaStyle",
                "emphasis",
            )
        },
        "layout": layout_meta.get("layout"),
        "contrast": layout_meta.get("contrast"),
        "audit": {"score": audit.get("score"), "failed": audit.get("failed"), "checks": audit.get("checks")},
    }
    return f"""You are an art director reviewing a composed LinkedIn poster (1200×627) from its layer metadata.

{_design_system_prompt()}

Composed poster (layer boxes are [x, y, w, h] in px; contrast values are WCAG ratios measured on the real background):
{json.dumps(summary, ensure_ascii=False)}

Score the composition 0–100 against the design system, list the concrete issues, then return the corrected fields.
Only change copy when it breaks a limit or weakens hierarchy; keep facts identical, never invent claims.
Return the current value for any field you keep. The layout template and imagery cannot change."""


def _apply_art_director_patch(brief: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    patched = dict(brief)
    for key in ("headline", "subhead", "cta", "eyebrow"):
        value = str(review.get(key) or "").strip()
        if key == "headline" and not value:
            continue
        patched[key] = value
    for key, allowed in (
        ("headlineScale", HEADLINE_SCALES),
        ("headlineWeight", HEADLINE_WEIGHTS),
        ("ctaStyle", CTA_STYLES),
    ):
        if review.get(key) in allowed:
            patched[key] = review[key]
    normalized = _normalize_brief(patched)
    for key in ("heroImagePrompt", "accentImagePrompt", "ideogramLayers", "layoutTemplate"):
        if key in brief:
            normalized[key] = brief[key]
        elif key in normalized and key not in brief:
            normalized.pop(key)
    if not normalized.get("cta"):
        normalized["ctaStyle"] = "none"
    return normalized


def art_director_review(
    brief: dict[str, Any],
    layout_meta: dict[str, Any],
) -> dict[str, Any] | None:
    """One text-only critique of the composed layout. Returns ``{brief, score, issues}`` or ``None``."""
    provider = resolve_llm_provider()
    if not provider:
        return None
    api_key = api_key_for_provider(provider)
    if not api_key:
        return None
    model = resolve_llm_model(provider)
    user = _art_director_prompt(brief, layout_meta)
    try:
        if provider == "anthropic":
            body = {
                "model": model,
                "max_tokens": 900,
                "system": (
                    "You are a meticulous art director. "
                    "You MUST call submit_art_direction exactly once."
                ),
                "messages": [{"role": "user", "content": user}],
                "tools": [
                    {
                        "name": "submit_art_direction",
                        "description": "Submit the layout review and corrected fields.",
                        "input_schema": ART_DIRECTOR_JSON_SCHEMA,
                        "strict": True,
                    }
                ],
                "tool_choice": {"type": "auto"},
            }
            payload = _post_anthropic_messages(body, api_key=api_key)
            review = _tool_input_from_anthropic_payload(payload, "submit_art_direction")
            if review is None:
                text = _text_from_anthropic_payload(payload)
                review = json.loads(text) if text else None
        else:
            base_url, extra_headers = _openai_compatible_endpoint(provider)
            content = _post_openai_json_schema(
                system="You are a meticulous art director. Reply with strict JSON only.",
                user=user,
                schema_name="art_direction",
                schema=ART_DIRECTOR_JSON_SCHEMA,
                api_key=api_key,
                model=model,
                base_url=base_url,
                extra_headers=extra_headers or None,
            )
            review = json.loads(content)
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        json.JSONDecodeError,
        ValueError,
        TimeoutError,
        OSError,
    ):
        return None
    if not isinstance(review, dict):
        return None
    return {
        "brief": _apply_art_director_patch(brief, review),
        "score": review.get("score"),
        "issues": [str(i) for i in (review.get("issues") or [])][:8],
        "model": model,
        "provider": provider,
    }
