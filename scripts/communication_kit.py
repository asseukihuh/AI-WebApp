"""Website → communication kit.

When a scraped site is visually thin, an AI pass (``COMMMAKER_BRAND_MODEL``, default
``claude-opus-5-5``) designs a coherent kit: graphic devices from the logo and sector,
colour proportions and tints, a type pairing, imagery direction and layout motifs.
Rich sites are formalised from the colours and type already on the page. Results are
cached per domain. Poster briefs stay on ``COMMMAKER_LLM_MODEL``.

Reusable assets are SVG. Posters place the same geometry as PhotoCraft ``shape.create``
vectors (path beziers, ellipses, polygons, rects, lines).
"""

from __future__ import annotations

import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from creative_brief import (
    ANTHROPIC_API_BASE,
    OPENAI_API_BASE,
    OPENROUTER_API_BASE,
    _anthropic_request_headers,
    api_key_for_provider,
    resolve_llm_model,
    resolve_llm_provider,
)
from poster_design import (
    CANVAS_H,
    CANVAS_W,
    brand_roles,
    chroma,
    hex_to_rgb,
    kit_hero_unsuitable,
    mix_hex,
    normalize_hex,
    relative_luminance,
)

KIT_VERSION = 2
CACHE_TTL_SEC = 7 * 24 * 3600
KIT_TIMEOUT_SEC = 90
KIT_MAX_TOKENS = 2200

# Opus-class list price (USD / million tokens) for kit-analysis accounting.
# Override with COMMMAKER_BRAND_PRICE_IN_PER_MTOK / COMMMAKER_BRAND_PRICE_OUT_PER_MTOK.
DEFAULT_BRAND_PRICE_IN = 15.0
DEFAULT_BRAND_PRICE_OUT = 75.0
DEFAULT_BRAND_MODEL = "claude-opus-5-5"

# Typical call sizes used by estimated_unit_costs().
TYPICAL_KIT_INPUT_TOKENS = 2000
TYPICAL_KIT_OUTPUT_TOKENS = 1200
TYPICAL_BRIEF_INPUT_TOKENS = 1800
TYPICAL_BRIEF_OUTPUT_TOKENS = 600
IDEOGRAM_IMAGE_USD = 0.06

DEVICE_KINDS: tuple[str, ...] = (
    "block",
    "crop",
    "corner-pin",
    "swoosh",
    "confetti",
    "climbing-holds",
    "mark-crop",
    "arc",
    "stripe",
    "blob",
    "grid-dots",
    "chevron",
    "shield",
    "wave",
    "bar",
    "ring",
    "slash",
    "burst",
    "ribbon",
)
DEVICE_ROLES = ("focal", "support", "texture", "frame")
COLOR_ROLES = ("primary", "secondary", "accent", "ink", "surface", "tint")
ANCHORS = (
    "top-left",
    "top-right",
    "bottom-left",
    "bottom-right",
    "center-right",
    "edge-top",
    "edge-bottom",
)
BACKDROPS = ("light", "dark", "brand")
FOCUS = ("headline", "device", "image")
WHITESPACE = ("generous", "moderate", "tight")
DEPTHS = ("layered", "flat")
BLOCKING = ("left-panel", "diagonal-crop", "corner-block", "full-field")

_SECTOR_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sport", ("sport", "bds", "escalade", "climb", "football", "rugby", "athlet", "fitness", "stade", "ig2i")),
    ("payments", ("stripe", "payment", "billing", "finance", "bank", "checkout", "invoice")),
    ("developer", ("vercel", "deploy", "developer", "infra", "cloud", "software", "api", "github")),
)

_PAIRINGS: dict[str, tuple[str, int, str, int, str]] = {
    "sport": (
        "Noto Sans Display",
        800,
        "Inter",
        400,
        "Heavy display sans for the hook, Inter for the one detail line.",
    ),
    "payments": (
        "Liberation Serif",
        700,
        "Inter",
        400,
        "A masthead serif against a neutral grotesque.",
    ),
    "developer": (
        "JetBrains Mono",
        700,
        "Inter",
        400,
        "Mono for the hook, Inter for the detail line.",
    ),
    "general": (
        "Noto Sans Display",
        700,
        "Inter",
        400,
        "Display sans plus a quiet body face.",
    ),
}


def _str() -> dict[str, Any]:
    return {"type": "string"}


def _str_list() -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}}


def _strict_object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties.keys()),
    }


COMMUNICATION_KIT_JSON_SCHEMA: dict[str, Any] = _strict_object(
    {
        "thinSite": {"type": "boolean"},
        "sector": _str(),
        "logoSystem": _strict_object(
            {
                "clearSpace": _str(),
                "minHeightPx": {"type": "integer"},
                "backdrop": {"type": "string", "enum": list(BACKDROPS)},
                "notes": _str(),
            }
        ),
        "proportions": _strict_object(
            {
                "primary": {"type": "integer"},
                "secondary": {"type": "integer"},
                "accent": {"type": "integer"},
            }
        ),
        "colours": {
            "type": "array",
            "items": _strict_object(
                {
                    "role": {"type": "string", "enum": list(COLOR_ROLES)},
                    "hex": _str(),
                    "name": _str(),
                    "usage": _str(),
                }
            ),
        },
        "tints": {
            "type": "array",
            "items": _strict_object(
                {
                    "name": _str(),
                    "hex": _str(),
                    "mixedFrom": _str(),
                    "amount": {"type": "number"},
                    "usage": _str(),
                }
            ),
        },
        "typePairing": _strict_object(
            {
                "displayFamily": _str(),
                "displayWeight": {"type": "integer"},
                "bodyFamily": _str(),
                "bodyWeight": {"type": "integer"},
                "pairingNote": _str(),
            }
        ),
        "devices": {
            "type": "array",
            "items": _strict_object(
                {
                    "id": _str(),
                    "kind": {"type": "string", "enum": list(DEVICE_KINDS)},
                    "role": {"type": "string", "enum": list(DEVICE_ROLES)},
                    "colorRole": {"type": "string", "enum": list(COLOR_ROLES)},
                    "scale": {"type": "number"},
                    "rotation": {"type": "number"},
                    "anchor": {"type": "string", "enum": list(ANCHORS)},
                    "opacity": {"type": "number"},
                    "count": {"type": "integer"},
                }
            ),
        },
        "imagery": _strict_object(
            {
                "primaryMedium": _str(),
                "motifs": _str_list(),
                "colorTreatment": _str(),
                "direction": _str(),
            }
        ),
        "layoutMotif": _strict_object(
            {
                "composition": _str(),
                "focal": {"type": "string", "enum": list(FOCUS)},
                "whitespace": {"type": "string", "enum": list(WHITESPACE)},
                "depth": {"type": "string", "enum": list(DEPTHS)},
                "blocking": {"type": "string", "enum": list(BLOCKING)},
            }
        ),
        "tone": _str_list(),
        "dos": _str_list(),
        "donts": _str_list(),
    }
)


def resolve_brand_model(provider: str | None = None) -> str:
    """Kit-analysis model. Poster briefs keep ``resolve_llm_model`` / ``COMMMAKER_LLM_MODEL``."""
    override = (os.environ.get("COMMMAKER_BRAND_MODEL") or "").strip()
    if override:
        return override
    provider = provider or resolve_llm_provider() or "anthropic"
    if provider == "openrouter":
        return "anthropic/claude-opus-5-5"
    if provider == "openai":
        return "gpt-4.1"
    return DEFAULT_BRAND_MODEL


def poster_brief_model(provider: str | None = None) -> str:
    """Per-poster creative brief model (unchanged Sonnet-class default)."""
    return resolve_llm_model(provider or resolve_llm_provider() or "anthropic")


def _price(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


def cost_usd(usage: dict[str, int] | None, *, kind: str = "kit") -> float:
    usage = usage or {}
    if kind == "brief":
        price_in = _price("COMMMAKER_LLM_PRICE_IN_PER_MTOK", 3.0)
        price_out = _price("COMMMAKER_LLM_PRICE_OUT_PER_MTOK", 15.0)
    else:
        price_in = _price("COMMMAKER_BRAND_PRICE_IN_PER_MTOK", DEFAULT_BRAND_PRICE_IN)
        price_out = _price("COMMMAKER_BRAND_PRICE_OUT_PER_MTOK", DEFAULT_BRAND_PRICE_OUT)
    return round(
        usage.get("inputTokens", 0) * price_in / 1e6 + usage.get("outputTokens", 0) * price_out / 1e6,
        4,
    )


def estimated_unit_costs() -> dict[str, Any]:
    """Order-of-magnitude USD. Kit analysis is cached per domain; a cache hit is 0."""
    kit = cost_usd({"inputTokens": TYPICAL_KIT_INPUT_TOKENS, "outputTokens": TYPICAL_KIT_OUTPUT_TOKENS})
    brief = cost_usd(
        {"inputTokens": TYPICAL_BRIEF_INPUT_TOKENS, "outputTokens": TYPICAL_BRIEF_OUTPUT_TOKENS},
        kind="brief",
    )
    return {
        "kitAnalysisUsd": kit,
        "kitAnalysisModel": resolve_brand_model("anthropic"),
        "kitAnalysisNote": (
            f"~{TYPICAL_KIT_INPUT_TOKENS} in / {TYPICAL_KIT_OUTPUT_TOKENS} out at "
            f"${DEFAULT_BRAND_PRICE_IN:.0f}/${DEFAULT_BRAND_PRICE_OUT:.0f} per MTok; cached 7 days per domain"
        ),
        "posterBriefUsd": brief,
        "posterBriefModel": "claude-sonnet-5-5",
        "posterWithIdeogramUsd": round(brief + IDEOGRAM_IMAGE_USD, 4),
        "ideogramImageUsd": IDEOGRAM_IMAGE_USD,
    }


# --------------------------------------------------------------------------- signals


def domain_key(url: str | None) -> str:
    host = urlparse(str(url or "")).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    host = re.sub(r"[^a-z0-9.-]", "", host)
    return host or "unknown"


def _blob(kit: dict[str, Any], profile: dict[str, Any] | None) -> str:
    parts = [
        kit.get("siteName"),
        kit.get("tagline"),
        kit.get("headline"),
        kit.get("sourceUrl"),
        (profile or {}).get("businessOverview"),
        " ".join((profile or {}).get("keywords") or []),
    ]
    return " ".join(str(p or "") for p in parts).casefold()


def infer_sector(kit: dict[str, Any] | None, profile: dict[str, Any] | None = None) -> str:
    text = _blob(kit or {}, profile)
    for name, words in _SECTOR_WORDS:
        if any(word in text for word in words):
            return name
    return "general"


def chromatic_colors(colors: list[Any] | None) -> list[str]:
    """Drop near-black, near-white and grey. A green crest plus neutrals is still one colour."""
    out: list[str] = []
    for raw in colors or []:
        hex6 = normalize_hex(str(raw or ""))
        if not hex6 or hex6 in out:
            continue
        rgb = hex_to_rgb(hex6)
        lum = relative_luminance(rgb)
        if lum > 0.92 or lum < 0.04 or chroma(rgb) < 0.12:
            continue
        out.append(hex6)
    return out


def is_thin_site(kit: dict[str, Any] | None, profile: dict[str, Any] | None = None) -> bool:
    """A site with too little visual system for a poster to borrow.

    Usable photography, a real chromatic palette and real copy each count. Two or more
    gaps (the score reaches 3) means the kit has to be designed, not just extracted.
    Neutral CSS colours (black, white, grey) do not count as a palette.
    """
    kit = kit or {}
    colors = chromatic_colors(kit.get("colors"))
    text = " ".join(str(kit.get(key) or "") for key in ("headline", "tagline", "siteName"))
    hero_ok = bool(kit.get("heroImageUrl")) and not kit_hero_unsuitable(kit)
    fonts = [f for f in (kit.get("fonts") or []) if str(f).strip() and "emoji" not in str(f).casefold()]
    score = 0
    if not hero_ok:
        score += 2
    if len(colors) <= 2:
        score += 1
    if len(text.strip()) < 48:
        score += 1
    if len(fonts) <= 1:
        score += 1
    if profile and hero_ok and len(profile.get("aesthetic") or []) >= 3 and len(colors) >= 4:
        return False
    return score >= 3


def _triangular_logo(svg: str) -> bool:
    compact = re.sub(r"\s+", "", svg or "")
    return "H0z" in compact or "h0z" in compact or "L0," in compact


def _device_plan(sector: str, logo_svg: str, thin: bool) -> list[tuple[str, str, str, float, str, int, float, float]]:
    """Catalog kinds are not stamped onto a brand.

    Poster imagery comes from the captured palette, the real logo geometry, or a
    usable photograph (see creative_brief.default_composition). A fixed ribbon,
    bar, or dot grid does not become a Stripe device just because the sector is payments.
    """
    del sector, logo_svg, thin
    return []


def _colours_from_roles(roles: Any) -> list[dict[str, str]]:
    tint = mix_hex(roles.brand, "#ffffff", 0.4)
    pairs = (
        ("primary", roles.brand, "Brand", "60% field and the focal device"),
        ("secondary", roles.dark, "Depth", "30% colour block and type ink on light"),
        ("accent", roles.accent, "Signal", "10% — CTA, eyebrow, one support device"),
        ("ink", roles.dark, "Ink", "Text and the logo on light fields"),
        ("surface", roles.light, "Paper", "Quiet ground and fine frames"),
        ("tint", tint, "Tint", "Secondary device, mixed toward paper"),
    )
    return [{"role": role, "hex": hex6, "name": name, "usage": usage} for role, hex6, name, usage in pairs]


def _tints(roles: Any) -> list[dict[str, Any]]:
    return [
        {
            "name": "Field",
            "hex": mix_hex(roles.brand, "#ffffff", 0.82),
            "mixedFrom": "primary",
            "amount": 0.82,
            "usage": "Large quiet ground",
        },
        {
            "name": "Deep",
            "hex": mix_hex(roles.brand, "#000000", 0.55),
            "mixedFrom": "primary",
            "amount": 0.55,
            "usage": "Colour block shadow",
        },
        {
            "name": "Signal tint",
            "hex": mix_hex(roles.accent, "#ffffff", 0.35),
            "mixedFrom": "accent",
            "amount": 0.35,
            "usage": "Support device",
        },
    ]


def _pairing_for(kit: dict[str, Any], sector: str, thin: bool) -> dict[str, Any]:
    display, d_weight, body, b_weight, note = _PAIRINGS[sector]
    fonts = [str(f).strip() for f in (kit.get("fonts") or []) if str(f).strip()]
    if not thin and fonts:
        display = fonts[0]
        body = fonts[1] if len(fonts) > 1 else fonts[0]
        note = "Pairing taken from the families already used on the site."
    return {
        "displayFamily": display,
        "displayWeight": d_weight,
        "bodyFamily": body,
        "bodyWeight": b_weight,
        "pairingNote": note,
    }


def _imagery_for(sector: str, thin: bool) -> dict[str, Any]:
    table = {
        "sport": (
            "abstract-shapes",
            ["crest crop", "climbing holds", "diagonal swoosh"],
            "one saturated green against a deep field",
            "Flat vector athletic marks. No photographs of people, no type inside the artwork.",
        ),
        "payments": (
            "gradients",
            ["ribbon", "soft stripe", "single arc"],
            "brand colour as a thin signal on a deep ground",
            "Smooth abstract ribbons, generous empty field, no UI and no currency symbols.",
        ),
        "developer": (
            "abstract-shapes",
            ["triangle crop", "dot grid", "hairline pins"],
            "near-monochrome with one accent",
            "Precise geometric marks, lots of empty ground, no product screenshots.",
        ),
        "general": (
            "abstract-shapes",
            ["colour block", "wave", "corner pin"],
            "60/30/10 brand field",
            "Simple geometric devices and one empty region for the hook.",
        ),
    }
    medium, motifs, treatment, direction = table[sector]
    if not thin:
        direction = "Echo the site's existing imagery. Devices stay quiet and off the text."
    return {
        "primaryMedium": medium,
        "motifs": motifs,
        "colorTreatment": treatment,
        "direction": direction,
    }


def _motif_for(thin: bool, sector: str) -> dict[str, str]:
    if thin:
        return {
            "composition": "Asymmetric: hook on a colour block, one large device opposite.",
            "focal": "device",
            "whitespace": "generous",
            "depth": "layered",
            "blocking": "diagonal-crop" if sector == "sport" else "left-panel",
        }
    return {
        "composition": "Existing layout, with devices only in the open field.",
        "focal": "headline",
        "whitespace": "moderate",
        "depth": "layered",
        "blocking": "full-field",
    }


def design_fallback(
    kit: dict[str, Any] | None,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministic kit when the brand model is unavailable. Still sector-specific."""
    kit = kit or {}
    thin = is_thin_site(kit, profile)
    sector = infer_sector(kit, profile)
    roles = brand_roles(kit, profile)
    devices = []
    for index, row in enumerate(_device_plan(sector, str(kit.get("logoSvg") or ""), thin), 1):
        kind, role, color, scale, anchor, count, opacity, rotation = row
        devices.append(
            {
                "id": f"d{index}",
                "kind": kind,
                "role": role,
                "colorRole": color,
                "scale": scale,
                "rotation": rotation,
                "anchor": anchor,
                "opacity": opacity,
                "count": count,
            }
        )
    backdrop = "dark" if roles.monochrome or thin else "brand"
    return {
        "thinSite": thin,
        "sector": sector,
        "logoSystem": {
            "clearSpace": "0.5× logo height, never inside a box",
            "minHeightPx": 48 if thin else 36,
            "backdrop": backdrop,
            "notes": "One real logo. Size it so it reads in a phone thumbnail.",
        },
        "proportions": {"primary": 60, "secondary": 30, "accent": 10},
        "colours": _colours_from_roles(roles),
        "tints": _tints(roles),
        "typePairing": _pairing_for(kit, sector, thin),
        "devices": devices,
        "imagery": _imagery_for(sector, thin),
        "layoutMotif": _motif_for(thin, sector),
        "tone": ["direct", "confident"] if thin else ["on-brand"],
        "dos": [
            "One focal point",
            "Hook in four to seven words",
            "Logo at clear-space size",
            "Leave a quiet field",
        ],
        "donts": [
            "Don't box the logo",
            "Don't add a second logo",
            "Don't fill the negative space",
            "Don't introduce colours outside the kit",
        ],
    }


def _clamp(value: Any, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _colour_map(colours: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for entry in colours:
        hex6 = normalize_hex(str(entry.get("hex") or ""))
        role = str(entry.get("role") or "")
        if hex6 and role:
            out[role] = hex6
    return out


def reconcile_kit(raw: dict[str, Any] | None, kit: dict[str, Any] | None, profile: dict[str, Any] | None) -> dict[str, Any]:
    """Snap a model payload onto the strict kit. Procedural colour and sector fill gaps."""
    base = design_fallback(kit, profile)
    raw = raw or {}
    # Thinness stays with the scraper heuristic so a rich site is never relabelled empty.
    thin = base["thinSite"]
    sector = str(raw.get("sector") or base["sector"]).strip() or base["sector"]
    colours = []
    for entry in raw.get("colours") or []:
        if not isinstance(entry, dict):
            continue
        role = entry.get("role")
        hex6 = normalize_hex(str(entry.get("hex") or ""))
        if role not in COLOR_ROLES or not hex6:
            continue
        colours.append(
            {
                "role": role,
                "hex": hex6,
                "name": str(entry.get("name") or role)[:32],
                "usage": str(entry.get("usage") or "")[:80],
            }
        )
    if len(colours) < 4:
        colours = base["colours"]
    devices = []
    for index, entry in enumerate(raw.get("devices") or [], 1):
        if not isinstance(entry, dict):
            continue
        kind = entry.get("kind")
        if kind not in DEVICE_KINDS:
            continue
        role = entry.get("role") if entry.get("role") in DEVICE_ROLES else "support"
        color = entry.get("colorRole") if entry.get("colorRole") in COLOR_ROLES else "primary"
        anchor = entry.get("anchor") if entry.get("anchor") in ANCHORS else "center-right"
        devices.append(
            {
                "id": str(entry.get("id") or f"d{index}")[:16],
                "kind": kind,
                "role": role,
                "colorRole": color,
                "scale": round(_clamp(entry.get("scale"), 0.3, 1.4, 0.8), 2),
                "rotation": round(_clamp(entry.get("rotation"), -40, 40, 0), 1),
                "anchor": anchor,
                "opacity": round(_clamp(entry.get("opacity"), 0.15, 1, 0.8), 2),
                "count": int(_clamp(entry.get("count"), 1, 16, 1)),
            }
        )
    if len(devices) < 3 and len(base["devices"]) >= 3:
        devices = base["devices"]
    focals = [d for d in devices if d["role"] == "focal"]
    if devices and not focals:
        devices[0]["role"] = "focal"
    elif len(focals) > 1:
        seen = False
        for device in devices:
            if device["role"] != "focal":
                continue
            if seen:
                device["role"] = "support"
            seen = True
    devices = devices[:5]
    pairing = raw.get("typePairing") if isinstance(raw.get("typePairing"), dict) else {}
    base_pair = base["typePairing"]
    logo = raw.get("logoSystem") if isinstance(raw.get("logoSystem"), dict) else {}
    motif = raw.get("layoutMotif") if isinstance(raw.get("layoutMotif"), dict) else {}
    imagery = raw.get("imagery") if isinstance(raw.get("imagery"), dict) else {}
    proportions = raw.get("proportions") if isinstance(raw.get("proportions"), dict) else {}
    primary = int(_clamp(proportions.get("primary"), 40, 80, 60))
    accent = int(_clamp(proportions.get("accent"), 5, 20, 10))
    secondary = 100 - primary - accent
    if not 15 <= secondary <= 45:
        primary, secondary, accent = 60, 30, 10
    tints = []
    for entry in raw.get("tints") or []:
        if not isinstance(entry, dict):
            continue
        hex6 = normalize_hex(str(entry.get("hex") or ""))
        if not hex6:
            continue
        tints.append(
            {
                "name": str(entry.get("name") or "Tint")[:32],
                "hex": hex6,
                "mixedFrom": str(entry.get("mixedFrom") or "primary")[:24],
                "amount": round(_clamp(entry.get("amount"), 0, 1, 0.4), 2),
                "usage": str(entry.get("usage") or "")[:80],
            }
        )
    if len(tints) < 2:
        tints = base["tints"]

    def _list(key: str, fallback: list[str], limit: int) -> list[str]:
        values = raw.get(key)
        if not isinstance(values, list):
            return fallback
        out = []
        for value in values:
            text = str(value or "").strip()
            if text:
                out.append(text[:80])
            if len(out) >= limit:
                break
        return out or fallback

    backdrop = logo.get("backdrop") if logo.get("backdrop") in BACKDROPS else base["logoSystem"]["backdrop"]
    motifs = [str(item).strip()[:48] for item in (imagery.get("motifs") or []) if str(item).strip()][:6]
    return {
        "thinSite": thin,
        "sector": sector[:32],
        "logoSystem": {
            "clearSpace": str(logo.get("clearSpace") or base["logoSystem"]["clearSpace"])[:80],
            "minHeightPx": int(_clamp(logo.get("minHeightPx"), 32, 72, base["logoSystem"]["minHeightPx"])),
            "backdrop": backdrop,
            "notes": str(logo.get("notes") or base["logoSystem"]["notes"])[:160],
        },
        "proportions": {"primary": primary, "secondary": secondary, "accent": accent},
        "colours": colours,
        "tints": tints[:6],
        "typePairing": {
            "displayFamily": str(pairing.get("displayFamily") or base_pair["displayFamily"])[:48],
            "displayWeight": int(_clamp(pairing.get("displayWeight"), 400, 900, base_pair["displayWeight"])),
            "bodyFamily": str(pairing.get("bodyFamily") or base_pair["bodyFamily"])[:48],
            "bodyWeight": int(_clamp(pairing.get("bodyWeight"), 300, 700, base_pair["bodyWeight"])),
            "pairingNote": str(pairing.get("pairingNote") or base_pair["pairingNote"])[:160],
        },
        "devices": devices,
        "imagery": {
            "primaryMedium": str(imagery.get("primaryMedium") or base["imagery"]["primaryMedium"])[:40],
            "motifs": motifs or base["imagery"]["motifs"],
            "colorTreatment": str(imagery.get("colorTreatment") or base["imagery"]["colorTreatment"])[:80],
            "direction": str(imagery.get("direction") or base["imagery"]["direction"])[:240],
        },
        "layoutMotif": {
            "composition": str(motif.get("composition") or base["layoutMotif"]["composition"])[:160],
            "focal": motif.get("focal") if motif.get("focal") in FOCUS else ("device" if thin else "headline"),
            "whitespace": motif.get("whitespace") if motif.get("whitespace") in WHITESPACE else "generous",
            "depth": motif.get("depth") if motif.get("depth") in DEPTHS else "layered",
            "blocking": motif.get("blocking") if motif.get("blocking") in BLOCKING else base["layoutMotif"]["blocking"],
        },
        "tone": _list("tone", base["tone"], 5),
        "dos": _list("dos", base["dos"], 6),
        "donts": _list("donts", base["donts"], 6),
    }


# --------------------------------------------------------------------------- model


def _kit_instructions(kit: dict[str, Any], profile: dict[str, Any] | None, thin: bool) -> str:
    roles = brand_roles(kit, profile)
    return f"""Design a communication kit for this organisation. thinSite signal from the scraper: {str(thin).lower()}.
Sector hint: {infer_sector(kit, profile)}.

When thinSite is true, invent a coherent system the website does not have: devices derived from the logo shape and the sector, a 60/30/10 colour proportion, tints mixed from the brand colour, a type pairing, imagery direction, and one layout motif. When thinSite is false, formalise what is already there and keep devices quiet.

Pick 3 or 4 devices from the kind enum. Do not use the same set for every sector. Sport clubs want crest-like mark-crop, climbing-holds or swooshes. Payments brands want ribbons and stripes. Developer brands want grids, pins and slashes. Exactly one device has role focal.

Colour hexes must come from the live palette when one exists (primary {roles.brand}, dark {roles.dark}, accent {roles.accent}, light {roles.light}). Proportions are integers that sum to 100, near 60/30/10.

Logo: clear space about half the logo height, minHeightPx 36 for a wordmark and 48 for an icon, never a box behind the mark.

Site:
name: {kit.get("siteName") or ""}
url: {kit.get("sourceUrl") or ""}
tagline: {kit.get("tagline") or ""}
headline: {kit.get("headline") or ""}
colors: {", ".join(str(c) for c in (kit.get("colors") or [])[:8])}
fonts: {", ".join(str(f) for f in (kit.get("fonts") or [])[:6])}
logo: {"inline svg" if kit.get("logoSvg") else "none"}

Call submit_communication_kit exactly once with every field filled."""


_KIT_SYSTEM = (
    "You are a brand designer building a communication kit in the tradition of a studio brand book: "
    "logo clear space, colour proportions, type pairing, a small set of graphic devices, imagery direction, "
    "layout motifs, and do/don't. You MUST call submit_communication_kit exactly once."
)


def anthropic_kit_body(kit: dict[str, Any], profile: dict[str, Any] | None, *, model: str) -> dict[str, Any]:
    thin = is_thin_site(kit, profile)
    return {
        "model": model,
        "max_tokens": KIT_MAX_TOKENS,
        "system": _KIT_SYSTEM,
        "messages": [{"role": "user", "content": _kit_instructions(kit, profile, thin)}],
        "tools": [
            {
                "name": "submit_communication_kit",
                "description": "Submit the communication kit.",
                "input_schema": COMMUNICATION_KIT_JSON_SCHEMA,
                "strict": True,
            }
        ],
        "tool_choice": {"type": "auto"},
    }


def _post_json(url: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=KIT_TIMEOUT_SEC) as resp:
        return json.loads(resp.read().decode("utf-8"))


def call_kit_llm(kit: dict[str, Any], profile: dict[str, Any] | None) -> dict[str, Any]:
    provider = resolve_llm_provider()
    if not provider:
        raise LookupError("no_provider")
    api_key = api_key_for_provider(provider)
    if not api_key:
        raise LookupError("no_api_key")
    model = resolve_brand_model(provider)
    usage = {"inputTokens": 0, "outputTokens": 0}
    if provider == "anthropic":
        body = anthropic_kit_body(kit, profile, model=model)
        for _ in range(2):
            payload = _post_json(f"{ANTHROPIC_API_BASE}/messages", body, _anthropic_request_headers(api_key))
            u = payload.get("usage") or {}
            usage["inputTokens"] += int(u.get("input_tokens") or 0)
            usage["outputTokens"] += int(u.get("output_tokens") or 0)
            for block in payload.get("content") or []:
                if block.get("type") == "tool_use" and block.get("name") == "submit_communication_kit":
                    if isinstance(block.get("input"), dict):
                        return {"raw": block["input"], "usage": usage, "model": model, "provider": provider}
        raise ValueError("Anthropic response missing submit_communication_kit")
    content = _kit_instructions(kit, profile, is_thin_site(kit, profile))
    body = {
        "model": model,
        "temperature": 0.4,
        "max_tokens": KIT_MAX_TOKENS,
        "messages": [
            {"role": "system", "content": _KIT_SYSTEM},
            {"role": "user", "content": content},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "communication_kit",
                "strict": True,
                "schema": COMMUNICATION_KIT_JSON_SCHEMA,
            },
        },
    }
    base = OPENROUTER_API_BASE if provider == "openrouter" else OPENAI_API_BASE
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if provider == "openrouter":
        headers["HTTP-Referer"] = os.environ.get("OPENROUTER_HTTP_REFERER", "https://github.com/asseukihuh/AI-WebApp")
        headers["X-Title"] = os.environ.get("OPENROUTER_APP_TITLE", "CommMaker")
    payload = _post_json(f"{base}/chat/completions", body, headers)
    u = payload.get("usage") or {}
    usage = {
        "inputTokens": int(u.get("prompt_tokens") or 0),
        "outputTokens": int(u.get("completion_tokens") or 0),
    }
    text = str(((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("LLM response was not a JSON object")
    return {"raw": data, "usage": usage, "model": model, "provider": provider}


def _cache_path(url: str, cache_dir: str) -> str:
    folder = os.path.join(cache_dir, domain_key(url))
    return os.path.join(folder, "kit.json")


def load_cached_kit(url: str, cache_dir: str) -> dict[str, Any] | None:
    path = _cache_path(url, cache_dir)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("version") != KIT_VERSION:
        return None
    if time.time() - float(payload.get("createdAtEpoch") or 0) > CACHE_TTL_SEC:
        return None
    result = payload.get("result")
    return result if isinstance(result, dict) else None


def _write_cache(url: str, cache_dir: str, result: dict[str, Any]) -> None:
    path = _cache_path(url, cache_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(
            {"version": KIT_VERSION, "createdAtEpoch": time.time(), "domain": domain_key(url), "result": result},
            handle,
        )


def analyze_communication_kit(
    kit: dict[str, Any] | None,
    *,
    cache_dir: str,
    brand_profile: dict[str, Any] | None = None,
    allow_llm: bool = True,
    refresh: bool = False,
    llm_fn: Any = None,
) -> dict[str, Any]:
    """Return ``{communicationKit, source, model, costUsd, cached, usage}``."""
    kit = dict(kit or {})
    profile = brand_profile if isinstance(brand_profile, dict) else kit.get("brandProfile")
    if not isinstance(profile, dict):
        profile = None
    url = str(kit.get("sourceUrl") or "")
    if not refresh and url:
        cached = load_cached_kit(url, cache_dir)
        if cached:
            stale = (
                cached.get("source") == "fallback"
                and allow_llm
                and llm_fn is None
                and resolve_llm_provider() is not None
                and api_key_for_provider(resolve_llm_provider() or "anthropic")
            )
            if not stale:
                return {**cached, "cached": True}
    designed: dict[str, Any]
    source = "fallback"
    model = ""
    usage: dict[str, int] = {}
    provider = ""
    if allow_llm:
        try:
            llm = (llm_fn or call_kit_llm)(kit, profile)
            designed = reconcile_kit(llm.get("raw"), kit, profile)
            source = "llm"
            model = str(llm.get("model") or resolve_brand_model())
            usage = llm.get("usage") or {}
            provider = str(llm.get("provider") or "")
        except LookupError:
            designed = design_fallback(kit, profile)
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, ValueError, TimeoutError, OSError):
            designed = design_fallback(kit, profile)
    else:
        designed = design_fallback(kit, profile)
    designed["version"] = KIT_VERSION
    designed["domain"] = domain_key(url)
    designed["designed"] = bool(designed.get("thinSite"))
    for device in designed["devices"]:
        device["svg"] = device_svg(device, designed, logo_svg=str(kit.get("logoSvg") or ""))
    result = {
        "communicationKit": designed,
        "source": source,
        "model": model,
        "provider": provider,
        "usage": usage,
        "costUsd": cost_usd(usage) if source == "llm" else 0.0,
        "thinSite": bool(designed.get("thinSite")),
    }
    if url:
        _write_cache(url, cache_dir, result)
    result["cached"] = False
    return result


def ensure_communication_kit(
    kit: dict[str, Any] | None,
    *,
    cache_dir: str,
    brand_profile: dict[str, Any] | None = None,
    allow_llm: bool = True,
    refresh: bool = False,
) -> dict[str, Any]:
    """Attach ``communicationKit``. Thin sites also receive the designed type and palette."""
    kit = dict(kit or {})
    existing = kit.get("communicationKit")
    if isinstance(existing, dict) and existing.get("devices") and not refresh:
        return kit
    result = analyze_communication_kit(
        kit,
        cache_dir=cache_dir,
        brand_profile=brand_profile,
        allow_llm=allow_llm,
        refresh=refresh,
    )
    designed = result["communicationKit"]
    kit["communicationKit"] = designed
    if designed.get("thinSite"):
        pairing = designed.get("typePairing") or {}
        families = [pairing.get("displayFamily"), pairing.get("bodyFamily")]
        families = [str(f) for f in families if f]
        if families:
            kit["fonts"] = families
        colours = [c.get("hex") for c in designed.get("colours") or [] if c.get("hex")]
        if colours:
            kit["colors"] = colours[:8]
            kit["accentColors"] = colours[:4]
    return kit


def kit_type_pairing(communication_kit: dict[str, Any] | None) -> dict[str, Any]:
    pairing = (communication_kit or {}).get("typePairing") or {}
    return pairing if isinstance(pairing, dict) else {}


# --------------------------------------------------------------------------- vectors


def _knot(ax: float, ay: float, ix: float, iy: float, ox: float, oy: float) -> dict[str, tuple[float, float]]:
    return {"anchor": (ax, ay), "in": (ix, iy), "out": (ox, oy)}


def _rotate(x: float, y: float, cx: float, cy: float, deg: float) -> tuple[float, float]:
    r = math.radians(deg)
    dx, dy = x - cx, y - cy
    return (cx + dx * math.cos(r) - dy * math.sin(r), cy + dx * math.sin(r) + dy * math.cos(r))


def _local_shapes(kind: str, count: int, *, sector: str, logo_svg: str) -> list[dict[str, Any]]:
    """Geometry in a 0–100 box. Bezier devices carry knots; others are primitive."""
    n = max(1, count)
    if kind == "shield" or (kind == "mark-crop" and sector == "sport"):
        return [
            {
                "type": "path",
                "closed": True,
                "knots": [
                    _knot(50, 6, 50, 6, 70, 8),
                    _knot(86, 18, 76, 10, 90, 32),
                    _knot(78, 58, 86, 46, 70, 74),
                    _knot(50, 94, 64, 86, 36, 86),
                    _knot(22, 58, 30, 74, 14, 46),
                    _knot(14, 18, 10, 32, 24, 10),
                ],
            }
        ]
    if kind == "mark-crop" and _triangular_logo(logo_svg):
        return [{"type": "polygon", "points": [(50, 6), (94, 90), (6, 90)]}]
    if kind == "mark-crop":
        return _local_shapes("swoosh", 1, sector=sector, logo_svg=logo_svg)
    if kind == "swoosh":
        return [
            {
                "type": "path",
                "closed": True,
                "knots": [
                    _knot(6, 68, 6, 68, 28, 86),
                    _knot(78, 36, 52, 78, 90, 18),
                    _knot(96, 22, 92, 16, 98, 30),
                    _knot(74, 46, 90, 36, 52, 64),
                    _knot(16, 78, 36, 84, 8, 70),
                ],
            }
        ]
    if kind == "blob":
        return [
            {
                "type": "path",
                "closed": True,
                "knots": [
                    _knot(28, 18, 18, 8, 42, 12),
                    _knot(78, 22, 62, 8, 90, 30),
                    _knot(84, 70, 98, 48, 70, 86),
                    _knot(30, 84, 48, 98, 14, 70),
                    _knot(16, 40, 8, 58, 14, 24),
                ],
            }
        ]
    if kind == "wave":
        return [
            {
                "type": "path",
                "closed": True,
                "knots": [
                    _knot(0, 62, 0, 62, 16, 40),
                    _knot(36, 48, 24, 28, 48, 62),
                    _knot(68, 40, 56, 28, 80, 52),
                    _knot(100, 36, 90, 28, 100, 36),
                    _knot(100, 70, 100, 70, 80, 78),
                    _knot(50, 74, 70, 86, 30, 70),
                    _knot(0, 80, 14, 86, 0, 80),
                ],
            }
        ]
    if kind == "ribbon":
        return [
            {
                "type": "polygon",
                "points": [(4, 28), (70, 16), (96, 36), (78, 48), (96, 62), (62, 78), (8, 58), (22, 42)],
            }
        ]
    if kind == "climbing-holds":
        spots = [(16, 20, 24, 18), (52, 12, 16, 14), (72, 38, 26, 18), (28, 58, 20, 24), (64, 72, 14, 12)]
        return [{"type": "ellipse", "rect": rect} for rect in spots[:n]]
    if kind == "confetti":
        spots = [(8, 12, 10, 6), (30, 8, 6, 12), (58, 18, 12, 5), (78, 6, 7, 7), (18, 40, 8, 5), (46, 48, 5, 11), (70, 36, 9, 6)]
        return [{"type": "rect", "rect": rect} for rect in spots[:n]]
    if kind == "grid-dots":
        dots = []
        for i in range(n):
            col, row = i % 4, i // 4
            dots.append({"type": "ellipse", "rect": (12 + col * 22, 16 + row * 22, 7, 7)})
        return dots
    if kind == "corner-pin":
        return [
            {"type": "polygon", "points": [(6, 6), (6, 36), (12, 36), (12, 12), (36, 12), (36, 6)]},
            {"type": "polygon", "points": [(94, 94), (94, 64), (88, 64), (88, 88), (64, 88), (64, 94)]},
        ]
    if kind == "stripe":
        return [
            {"type": "polygon", "points": [(10, 0), (28, 0), (8, 100), (-10, 100)]},
            {"type": "polygon", "points": [(40, 0), (52, 0), (32, 100), (20, 100)]},
            {"type": "polygon", "points": [(70, 0), (78, 0), (58, 100), (50, 100)]},
        ][:n]
    if kind == "slash":
        return [{"type": "polygon", "points": [(58, 4), (92, 4), (42, 96), (8, 96)]}]
    if kind == "chevron":
        return [
            {"type": "polygon", "points": [(10, 20), (50, 8), (90, 20), (78, 32), (50, 22), (22, 32)]},
            {"type": "polygon", "points": [(10, 48), (50, 36), (90, 48), (78, 60), (50, 50), (22, 60)]},
        ]
    if kind == "block":
        return [{"type": "rect", "rect": (8, 18, 84, 64)}]
    if kind == "crop":
        return [{"type": "polygon", "points": [(0, 0), (100, 0), (100, 46), (0, 100)]}]
    if kind == "bar":
        return [{"type": "rect", "rect": (0, 42, 100, 16)}]
    if kind == "ring":
        return [{"type": "ellipse", "rect": (12, 12, 76, 76), "stroke": 6}]
    if kind == "arc":
        return [
            {
                "type": "path",
                "closed": False,
                "knots": [
                    _knot(14, 62, 14, 62, 30, 18),
                    _knot(50, 14, 36, 10, 64, 10),
                    _knot(86, 62, 70, 18, 86, 62),
                ],
            }
        ]
    if kind == "burst":
        lines = []
        for i in range(max(6, n)):
            ang = math.radians(i * (360 / max(6, n)))
            lines.append(
                {
                    "type": "line",
                    "a": (50 + math.cos(ang) * 18, 50 + math.sin(ang) * 18),
                    "b": (50 + math.cos(ang) * 46, 50 + math.sin(ang) * 46),
                    "width": 3,
                }
            )
        return lines
    return [{"type": "ellipse", "rect": (20, 20, 60, 60)}]


def _map_point(pt: tuple[float, float], origin: tuple[float, float], size: float, rotation: float) -> tuple[float, float]:
    ox, oy = origin
    x = ox + pt[0] / 100 * size
    y = oy + pt[1] / 100 * size
    if rotation:
        cx, cy = ox + size / 2, oy + size / 2
        x, y = _rotate(x, y, cx, cy, rotation)
    return (round(x, 1), round(y, 1))


def _rgba(hex6: str, opacity: float) -> list[float]:
    r, g, b = hex_to_rgb(hex6)
    return [r, g, b, round(max(0.0, min(1.0, opacity)), 3)]


def materialize_device(
    device: dict[str, Any],
    communication_kit: dict[str, Any],
    *,
    origin: tuple[float, float],
    size: float,
    logo_svg: str = "",
) -> list[dict[str, Any]]:
    colours = _colour_map(communication_kit.get("colours") or [])
    hex6 = colours.get(device.get("colorRole") or "") or colours.get("primary") or "#111111"
    opacity = float(device.get("opacity") or 1)
    rotation = float(device.get("rotation") or 0)
    sector = str(communication_kit.get("sector") or "")
    shapes = _local_shapes(str(device.get("kind") or "block"), int(device.get("count") or 1), sector=sector, logo_svg=logo_svg)
    out = []
    name = f"Device {device.get('kind')}"
    for index, shape in enumerate(shapes):
        mapped: dict[str, Any] = {
            "type": shape["type"],
            "name": name if len(shapes) == 1 else f"{name} {index + 1}",
            "fill": _rgba(hex6, opacity),
            "role": device.get("role"),
            "kind": device.get("kind"),
        }
        if shape["type"] in ("polygon",):
            mapped["points"] = [_map_point(p, origin, size, rotation) for p in shape["points"]]
        elif shape["type"] in ("rect", "ellipse"):
            x, y, w, h = shape["rect"]
            p = _map_point((x, y), origin, size, 0)
            mapped["rect"] = [p[0], p[1], round(w / 100 * size, 1), round(h / 100 * size, 1)]
            mapped["rotation"] = rotation
            if shape.get("stroke"):
                mapped["stroke"] = {"width": max(2, shape["stroke"] * size / 100), "color": _rgba(hex6, opacity), "cap": "round"}
                mapped["fill"] = [0, 0, 0, 0]
        elif shape["type"] == "line":
            mapped["a"] = list(_map_point(shape["a"], origin, size, rotation))
            mapped["b"] = list(_map_point(shape["b"], origin, size, rotation))
            mapped["stroke"] = {"width": max(2, shape.get("width", 3) * size / 100), "color": _rgba(hex6, opacity), "cap": "round"}
            mapped["fill"] = None
        elif shape["type"] == "path":
            knots = []
            for knot in shape["knots"]:
                knots.append(
                    {
                        "anchor": list(_map_point(knot["anchor"], origin, size, rotation)),
                        "in": list(_map_point(knot["in"], origin, size, rotation)),
                        "out": list(_map_point(knot["out"], origin, size, rotation)),
                    }
                )
            mapped["knots"] = knots
            mapped["closed"] = bool(shape.get("closed", True))
            if not mapped["closed"]:
                mapped["stroke"] = {
                    "width": max(3, round(size * 0.035, 1)),
                    "color": _rgba(hex6, opacity),
                    "cap": "round",
                }
                mapped["fill"] = [0, 0, 0, 0]
        out.append(mapped)
    return out


def _anchor_origin(anchor: str, size: float, *, text_on_left: bool, index: int) -> tuple[float, float]:
    """Place devices in the open field, away from a left-hand text column."""
    if text_on_left:
        table = {
            "center-right": (CANVAS_W - size - 36, (CANVAS_H - size) / 2 - 10),
            "top-right": (CANVAS_W - size - 24, 28),
            "bottom-right": (CANVAS_W - size - 48, CANVAS_H - size - 24),
            "bottom-left": (640, CANVAS_H - size - 16),
            "top-left": (640, 24),
            "edge-top": (700, -size * 0.25),
            "edge-bottom": (680, CANVAS_H - size * 0.72),
        }
    else:
        table = {
            "center-right": (CANVAS_W - size * 0.72, CANVAS_H * 0.18),
            "top-right": (CANVAS_W - size * 0.55, -size * 0.2),
            "bottom-right": (CANVAS_W - size * 0.7, CANVAS_H - size * 0.55),
            "bottom-left": (-size * 0.35, CANVAS_H - size * 0.45),
            "top-left": (-size * 0.3, -size * 0.15),
            "edge-top": (CANVAS_W * 0.5 - size / 2, -size * 0.45),
            "edge-bottom": (80, CANVAS_H - size * 0.4),
        }
    origin = table.get(anchor, table["center-right"])
    nudge = (index % 3) * 12
    return (round(origin[0] + nudge, 1), round(origin[1], 1))


def poster_vectors(
    communication_kit: dict[str, Any] | None,
    *,
    template_name: str,
    logo_svg: str = "",
) -> list[dict[str, Any]]:
    """Canvas-space shapes for one poster. Empty when the kit has no devices."""
    kit = communication_kit or {}
    devices = kit.get("devices") or []
    if not devices:
        return []
    text_on_left = template_name != "centered-statement"
    shapes: list[dict[str, Any]] = []
    for index, device in enumerate(devices):
        if not isinstance(device, dict):
            continue
        scale = float(device.get("scale") or 0.8)
        role = device.get("role")
        base = 300 if role == "focal" else 180 if role == "support" else 150
        size = max(80.0, min(420.0, base * scale))
        origin = _anchor_origin(str(device.get("anchor") or "center-right"), size, text_on_left=text_on_left, index=index)
        shapes.extend(materialize_device(device, kit, origin=origin, size=size, logo_svg=logo_svg))
    return shapes


def _path_params(
    name: str,
    knots: list[Any],
    *,
    closed: bool,
    fill: Any,
    stroke: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """PhotoCraft path: knots are ``{anchor,in,out}`` or bare ``[x,y]`` corners."""
    encoded = []
    for knot in knots:
        if isinstance(knot, dict) and "anchor" in knot:
            encoded.append(
                {
                    "anchor": list(knot["anchor"]),
                    "in": list(knot.get("in") or knot["anchor"]),
                    "out": list(knot.get("out") or knot["anchor"]),
                }
            )
        else:
            encoded.append({"anchor": list(knot), "in": list(knot), "out": list(knot)})
    params: dict[str, Any] = {
        "kind": "path",
        "name": name,
        "fill": _fill_value(fill),
        "path": {"subpaths": [{"closed": closed, "knots": encoded}], "fillRule": "nonzero"},
    }
    if stroke:
        params["stroke"] = stroke
    return params


def shape_steps(shapes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """PhotoCraft 0.9 ``shape.create``. Custom outlines are paths; ``polygon`` is a regular n-gon."""
    steps = []
    for shape in shapes:
        kind = shape["type"]
        fill = shape.get("fill")
        stroke = shape.get("stroke")
        if kind == "polygon":
            params = _path_params(shape["name"], shape["points"], closed=True, fill=fill, stroke=stroke)
        elif kind == "rect":
            params = {"kind": "rect", "name": shape["name"], "rect": shape["rect"], "fill": _fill_value(fill)}
        elif kind == "ellipse":
            params = {"kind": "ellipse", "name": shape["name"], "rect": shape["rect"], "fill": _fill_value(fill)}
            if stroke:
                params["stroke"] = _stroke_params(stroke)
                if fill == [0, 0, 0, 0]:
                    params["fill"] = None
        elif kind == "line":
            width = (stroke or {}).get("width") or 4
            params = {
                "kind": "line",
                "name": shape["name"],
                "from": shape["a"],
                "to": shape["b"],
                "weight": width,
                "fill": _fill_value((stroke or {}).get("color") or fill),
            }
        elif kind == "path":
            params = _path_params(
                shape["name"],
                shape["knots"],
                closed=bool(shape.get("closed", True)),
                fill=None if stroke and not shape.get("closed", True) else fill,
                stroke=_stroke_params(stroke) if stroke else None,
            )
            if shape.get("closed", True) and shape.get("kind") in ("swoosh", "blob", "wave") and isinstance(fill, list):
                params["fill"] = {
                    "gradient": {
                        "stops": [[0, _rgb_hex(fill)], [1, _rgb_hex(fill, lighten=0.35)]],
                        "angle": 18,
                        "style": "linear",
                    }
                }
        else:
            continue
        steps.append({"command": "shape.create", "params": params})
    return steps


def _fill_value(fill: Any) -> Any:
    """PhotoCraft treats a numeric fill as 0–1 floats, so opaque brand colours go out as hex."""
    if not isinstance(fill, list) or len(fill) < 3:
        return fill
    r, g, b = (max(0, min(255, int(channel))) for channel in fill[:3])
    alpha = float(fill[3]) if len(fill) > 3 else 1.0
    if alpha >= 0.999:
        return f"#{r:02x}{g:02x}{b:02x}"
    return f"#{r:02x}{g:02x}{b:02x}{max(0, min(255, int(round(alpha * 255)))):02x}"


def _stroke_params(stroke: dict[str, Any]) -> dict[str, Any]:
    color = stroke.get("color")
    if isinstance(color, list):
        color = _rgb_hex(color)
    return {
        "width": stroke.get("width") or 4,
        "color": color,
        "cap": stroke.get("cap") or "round",
        "align": "center",
    }


def _rgb_hex(rgba: list[float], lighten: float = 0) -> str:
    r, g, b = (int(channel) for channel in rgba[:3])
    if lighten:
        r = int(r + (255 - r) * lighten)
        g = int(g + (255 - g) * lighten)
        b = int(b + (255 - b) * lighten)
    return f"#{r:02x}{g:02x}{b:02x}"


def colour_block_step(communication_kit: dict[str, Any] | None, *, surface: str) -> dict[str, Any] | None:
    """Diagonal crop used by sport (and any kit that asks for diagonal-crop)."""
    motif = (communication_kit or {}).get("layoutMotif") or {}
    if motif.get("blocking") != "diagonal-crop":
        return None
    r, g, b = hex_to_rgb(surface)
    return {
        "command": "shape.create",
        "params": _path_params(
            "Colour block",
            [[0, 0], [760, 0], [500, CANVAS_H], [0, CANVAS_H]],
            closed=True,
            fill=[r, g, b, 1],
        ),
    }


def _svg_number(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _svg_path(knots: list[dict[str, Any]], closed: bool) -> str:
    if not knots:
        return ""
    start = knots[0]["anchor"]
    parts = [f"M {_svg_number(start[0])} {_svg_number(start[1])}"]
    pairs = [(knots[i], knots[i + 1]) for i in range(len(knots) - 1)]
    if closed:
        pairs.append((knots[-1], knots[0]))
    for prev, cur in pairs:
        parts.append(
            "C "
            + " ".join(
                _svg_number(v)
                for v in (*prev["out"], *cur["in"], *cur["anchor"])
            )
        )
    if closed:
        parts.append("Z")
    return " ".join(parts)


def device_svg(device: dict[str, Any], communication_kit: dict[str, Any], *, logo_svg: str = "") -> str:
    """Standalone reusable SVG for one device (400×400)."""
    shapes = materialize_device(device, communication_kit, origin=(0, 0), size=400, logo_svg=logo_svg)
    body = []
    for shape in shapes:
        fill = shape.get("fill") or [0, 0, 0, 0]
        colour = f"rgb({int(fill[0])},{int(fill[1])},{int(fill[2])})"
        opacity = fill[3] if len(fill) > 3 else 1
        if shape["type"] == "path":
            d = _svg_path(shape["knots"], bool(shape.get("closed", True)))
            stroke = shape.get("stroke")
            if stroke:
                sc = stroke["color"]
                body.append(
                    f'<path d="{d}" fill="none" stroke="rgb({int(sc[0])},{int(sc[1])},{int(sc[2])})" '
                    f'stroke-width="{stroke["width"]:.1f}" stroke-linecap="round"/>'
                )
            else:
                body.append(f'<path d="{d}" fill="{colour}" fill-opacity="{opacity}"/>')
        elif shape["type"] == "polygon":
            points = " ".join(f"{p[0]},{p[1]}" for p in shape["points"])
            body.append(f'<polygon points="{points}" fill="{colour}" fill-opacity="{opacity}"/>')
        elif shape["type"] == "rect":
            x, y, w, h = shape["rect"]
            body.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{colour}" fill-opacity="{opacity}"/>')
        elif shape["type"] == "ellipse":
            x, y, w, h = shape["rect"]
            stroke = shape.get("stroke")
            extra = ""
            if stroke:
                sc = stroke["color"]
                extra = f' fill="none" stroke="rgb({int(sc[0])},{int(sc[1])},{int(sc[2])})" stroke-width="{stroke["width"]:.1f}"'
                body.append(
                    f'<ellipse cx="{x + w / 2:.1f}" cy="{y + h / 2:.1f}" rx="{w / 2:.1f}" ry="{h / 2:.1f}"{extra}/>'
                )
            else:
                body.append(
                    f'<ellipse cx="{x + w / 2:.1f}" cy="{y + h / 2:.1f}" rx="{w / 2:.1f}" ry="{h / 2:.1f}" fill="{colour}" fill-opacity="{opacity}"/>'
                )
        elif shape["type"] == "line":
            stroke = shape["stroke"]
            sc = stroke["color"]
            ax, ay = shape["a"]
            bx, by = shape["b"]
            body.append(
                f'<line x1="{ax}" y1="{ay}" x2="{bx}" y2="{by}" stroke="rgb({int(sc[0])},{int(sc[1])},{int(sc[2])})" stroke-width="{stroke["width"]:.1f}" stroke-linecap="round"/>'
            )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400" width="400" height="400">'
        + "".join(body)
        + "</svg>"
    )


def render_kit_assets(communication_kit: dict[str, Any], out_dir: str, *, logo_svg: str = "") -> list[str]:
    """Write one SVG per device plus a board. Returns absolute paths."""
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for device in communication_kit.get("devices") or []:
        svg = device.get("svg") or device_svg(device, communication_kit, logo_svg=logo_svg)
        path = os.path.join(out_dir, f"device-{device.get('id') or device.get('kind')}.svg")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(svg)
        paths.append(path)
    return paths
