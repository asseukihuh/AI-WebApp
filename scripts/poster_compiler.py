"""Compile Communication Kit + crisis session → PhotoCraft command batch (v1).

Command ids and param shapes match PhotoCraft v0.9 engine registry (`photocraft-cli commands --json`).

Document (``doc.new`` / ``file.new`` params):
  width, height: pixel counts (1..300000)
  mode: "rgb" | "gray" | "grayscale" | "cmyk" | "lab"
  depth: 8 | 16 | 32
  background: "white" | "black" | "backgroundColor" | "transparent" | "#rrggbb"
  resolution: ppi (default 72)
  name: str

Engine steps (``batch`` / ``command_batch``):
  type.create — point or paragraph text:
    x, y (baseline for point text); optional box [x,y,w,h] for paragraph text
    text: str; name: str?; align: left|center|right|...
    font: str; size: pt; color: "#rrggbb" or [r,g,b,a]
  type.setStyle — optional follow-up for layer id (when needed)
  layer.newFillLayer.solidColor — {"color": "#rrggbb"} (full-canvas fill layer)
  layer.setProps — {"layer": id?, "name": str?, "opacity": 0..1?, ...}

Placements (headless ``doc.place`` only — not engine.execute file.placeEmbedded):
  path: str relative to automation read root
  center: [x, y]? — anchor point (canvas center for full-bleed hero)
  scale: number? — placement size as % of native pixels (cover uses max(canvas/img)×100)
  fit: bool? — when true, shrink large images to fit inside canvas (do not use for hero)
  smartObject: bool?; name: str?
  cover: bool? — CommMaker-only hint; ``photocraft_cli`` resolves to ``fit: false`` + ``scale``

Hero **cover** (1200×627): ``fit: false``, ``center: [600, 313.5]``, ``scale`` so both
dimensions meet or exceed the canvas (center crop). PhotoCraft does not letterbox when
``fit`` is false and scale is large enough.

``backgroundPlacements`` are applied after ``doc.new`` and before the engine ``batch``
so hero imagery sits under type layers. Foreground ``placements`` run after the batch.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any

LINKEDIN_WIDTH = 1200
LINKEDIN_HEIGHT = 627
SAFE_PAD = 48
TEXT_BLOCK_MAX_WIDTH = 900
LOGO_MARGIN = 56
LOGO_TARGET_WIDTH = 280
LOGO_TARGET_WIDTH_MIN = 220
LOGO_TARGET_WIDTH_MAX = 320
LOGO_MAX_HEIGHT = 80
LOGO_KNOCKBACK_PAD = 14
LOGO_KNOCKBACK_BASE_WIDTH = 168
LOGO_KNOCKBACK_BASE_HEIGHT = 88
LOGO_KNOCKBACK_REL = "assets/commmaker/logo-knockback.svg"
HEADLINE_SIZE_SOLO = 56
HEADLINE_SIZE_WITH_SUB = 52
SUBLINE_SIZE = 24
SUBLINE_OPACITY = 0.9
SUBLINE_CHAR_LIMIT = 72
BATCH_FORMAT = "photocraft-command-batch-v1"

_NEUTRAL_HEX = frozenset(
    {
        "#000000",
        "#ffffff",
        "#fff",
        "#000",
        "#abb8c3",
        "#e2e8f0",
        "#f8fafc",
        "#1a202c",
    }
)


def _normalize_hex(value: str, default: str) -> str:
    if not value:
        return default
    v = value.strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", v):
        return v.lower()
    if re.fullmatch(r"#[0-9a-fA-F]{3}", v):
        return "#" + "".join(c * 2 for c in v[1:]).lower()
    return default


def _is_neutral(hex_color: str) -> bool:
    hex6 = _normalize_hex(hex_color, "")
    if hex6 in _NEUTRAL_HEX:
        return True
    if not hex6.startswith("#") or len(hex6) != 7:
        return True
    body = hex6[1:]
    r, g, b = (int(body[i : i + 2], 16) for i in (0, 2, 4))
    spread = max(r, g, b) - min(r, g, b)
    avg = (r + g + b) / 3
    return spread < 18 and (avg < 40 or avg > 230)


def _palette_from_kit(kit: dict[str, Any] | None) -> list[str]:
    kit = kit or {}
    ordered: list[str] = []
    for key in ("accentColors", "colors"):
        raw = kit.get(key) or []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str):
                    ordered.append(_normalize_hex(item, ""))
    seen: set[str] = set()
    palette: list[str] = []
    for color in ordered:
        if not color or not color.startswith("#") or color in seen:
            continue
        seen.add(color)
        palette.append(color)
    return palette


def _pick_color(
    kit: dict[str, Any] | None,
    index: int = 0,
    default: str = "#1a365d",
) -> str:
    palette = _palette_from_kit(kit)
    vivid = [c for c in palette if not _is_neutral(c)]
    pool = vivid if vivid else palette
    if index < len(pool):
        return pool[index]
    if index < len(palette):
        return palette[index]
    return default


def _hex_luminance(hex_color: str) -> float:
    hex6 = _normalize_hex(hex_color, "#000000").lstrip("#")
    if len(hex6) != 6:
        return 0.0
    r, g, b = (int(hex6[i : i + 2], 16) for i in (0, 2, 4))
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def _contrast_text_color(bg_hex: str) -> str:
    return "#0f172a" if _hex_luminance(bg_hex) > 0.6 else "#ffffff"


_BRIGHT_HERO_CORNER_LUMINANCE = 0.55
_LOGO_MARK_DARK_LUMINANCE = 0.45

_SVG_FILL_ATTR_RE = re.compile(
    r"fill\s*=\s*([\"'])(#[0-9a-fA-F]{3,8}|[a-zA-Z]+)\1",
    re.I,
)
_SVG_STYLE_FILL_RE = re.compile(
    r"fill\s*:\s*(#[0-9a-fA-F]{3,8})",
    re.I,
)


def _normalize_compare(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).casefold()


def _body_lines(
    session: dict[str, Any],
    *,
    skip_headline: str = "",
    max_lines: int = 3,
) -> str:
    facts = (session.get("brief") or {}).get("facts") or ""
    lines = [ln.strip() for ln in facts.splitlines() if ln.strip()]
    if not lines and session.get("captionDraft"):
        lines = [
            ln.strip()
            for ln in str(session["captionDraft"]).splitlines()
            if ln.strip()
        ][1:4]
    skip = _normalize_compare(skip_headline)
    if skip and lines and _normalize_compare(lines[0]) == skip:
        lines = lines[1:]
    elif skip:
        lines = [ln for ln in lines if _normalize_compare(ln) != skip]
    return "\n".join(lines[:max_lines])


_GENERIC_FONT_NAMES = frozenset(
    {
        "inherit",
        "sans-serif",
        "serif",
        "monospace",
        "system-ui",
        "ui-sans-serif",
        "ui-serif",
        "inter",
    }
)

_DISPLAY_FONT_HINT = re.compile(
    r"\b(display|condensed|slab|garamond|playfair|merriweather|"
    r"cormorant|fraunces|bebas|oswald|anton)\b",
    re.I,
)


def _kit_font_names(kit: dict[str, Any] | None) -> list[str]:
    names: list[str] = []
    for raw in (kit or {}).get("fonts") or []:
        cleaned = str(raw).strip()
        if cleaned and cleaned.lower() not in _GENERIC_FONT_NAMES and cleaned not in names:
            names.append(cleaned)
    for entry in (kit or {}).get("googleFonts") or []:
        if isinstance(entry, dict):
            family = str(entry.get("family") or "").strip()
            if family and family.lower() not in _GENERIC_FONT_NAMES and family not in names:
                names.append(family)
    return names


def _pick_headline_font(kit: dict[str, Any] | None) -> str:
    fonts = _kit_font_names(kit)
    if not fonts:
        return "Inter"
    if len(fonts) == 1:
        return fonts[0]
    for name in fonts:
        if _DISPLAY_FONT_HINT.search(name):
            return name
    return fonts[0]


def _pick_body_font(kit: dict[str, Any] | None, headline_font: str) -> str:
    fonts = _kit_font_names(kit)
    for name in fonts:
        if name.casefold() != headline_font.casefold():
            return name
    return fonts[0] if fonts else "Inter"


def _headline_font_style(
    kit: dict[str, Any] | None,
    headline_font: str,
) -> str | None:
    for entry in (kit or {}).get("googleFonts") or []:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("family") or "").casefold() != headline_font.casefold():
            continue
        weights = {str(w) for w in entry.get("weights") or []}
        if weights & {"700", "800", "900"}:
            return "bold"
    return None


def _truncate(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _pick_site_name(kit: dict[str, Any] | None) -> str:
    kit = kit or {}
    raw = kit.get("siteName") or "Learn more"
    name = re.sub(r"\s+", " ", str(raw)).strip()
    if re.match(r"^accueil\s*[-–|]\s*", name, re.I):
        name = re.sub(r"^accueil\s*[-–|]\s*", "", name, flags=re.I).strip()
    generic = name.casefold() in {"accueil", "home", "welcome", "untitled site", "learn more"}
    if generic or len(name) < 3:
        for src in (kit.get("headline"), kit.get("tagline")):
            if not src:
                continue
            parts = [p.strip() for p in re.split(r"[\-–|]", str(src)) if p.strip()]
            if len(parts) >= 2:
                candidate = parts[-1]
                if candidate.casefold() not in {"accueil", "home"}:
                    name = candidate
                    break
    return _truncate(name or "Learn more", 48)


def _resolve_headline_hierarchy(
    kit: dict[str, Any] | None,
    session: dict[str, Any],
) -> tuple[str, str]:
    """Crisis headline (large) + optional subhead (smaller), without duplicating copy."""
    kit = kit or {}
    brief = session.get("brief") or {}
    site_raw = re.sub(r"\s+", " ", str(kit.get("siteName") or "")).strip()
    crisis = _truncate(
        session.get("suggestedHeadline")
        or brief.get("headline")
        or "",
        90,
    )
    kit_head = _truncate(kit.get("headline") or "", SUBLINE_CHAR_LIMIT)
    kit_tag = _truncate(
        kit.get("tagline") or brief.get("tagline") or "",
        SUBLINE_CHAR_LIMIT,
    )

    if not crisis:
        crisis = _truncate(kit_head or "Important update", 90)

    crisis_norm = _normalize_compare(crisis)

    def _distinct_from_headline(candidate: str) -> bool:
        if not candidate:
            return False
        cand = _normalize_compare(candidate)
        if cand == crisis_norm:
            return False
        if site_raw and cand == _normalize_compare(site_raw):
            return False
        if kit_head and cand == _normalize_compare(kit_head) and cand == crisis_norm:
            return False
        return True

    subhead = ""
    if kit_tag and _distinct_from_headline(kit_tag):
        subhead = kit_tag
    elif kit_head and _distinct_from_headline(kit_head):
        subhead = kit_head
    subhead = _truncate(subhead, SUBLINE_CHAR_LIMIT)

    return crisis, subhead


def _logo_mark_luminance(kit: dict[str, Any] | None) -> float:
    palette = _palette_from_kit(kit)
    if not palette:
        return 0.2
    return min(_hex_luminance(c) for c in palette[:4])


def _estimated_hero_corner_luminance(kit: dict[str, Any] | None) -> float:
    """Heuristic: marketing heroes (e.g. Stripe OG) are often bright top-right."""
    palette = _palette_from_kit(kit)
    if not palette:
        return 0.72
    samples = [_hex_luminance(c) for c in palette[:3]]
    avg = sum(samples) / len(samples)
    return max(0.55, min(0.92, avg + 0.22))


def should_logo_on_dark(
    kit: dict[str, Any] | None,
    *,
    has_hero: bool,
    hero_busy: bool = False,
) -> bool:
    if not has_hero or hero_busy:
        return False
    corner = _estimated_hero_corner_luminance(kit)
    mark = _logo_mark_luminance(kit)
    return (
        corner >= _BRIGHT_HERO_CORNER_LUMINANCE
        and mark < _LOGO_MARK_DARK_LUMINANCE
    )


def recolor_logo_svg_for_light_hero(svg: str, light_fill: str = "#ffffff") -> str:
    """Replace dark SVG path fills with a light fill for bright photo heroes."""

    def _maybe_swap(color: str) -> str:
        lower = (color or "").lower()
        if lower in ("none", "transparent", "currentcolor"):
            return color
        if not lower.startswith("#"):
            return color
        if _hex_luminance(color) < _LOGO_MARK_DARK_LUMINANCE:
            return light_fill
        return color

    def _attr_repl(match: re.Match[str]) -> str:
        quote, raw = match.group(1), match.group(2)
        swapped = _maybe_swap(raw)
        if swapped == raw:
            return match.group(0)
        return f"fill={quote}{swapped}{quote}"

    out = _SVG_FILL_ATTR_RE.sub(_attr_repl, svg)

    def _style_repl(match: re.Match[str]) -> str:
        raw = match.group(1)
        swapped = _maybe_swap(raw)
        if swapped == raw:
            return match.group(0)
        return f"fill:{swapped}"

    return _SVG_STYLE_FILL_RE.sub(_style_repl, out)


def _use_logo_knockback(
    kit: dict[str, Any] | None,
    *,
    has_hero: bool,
    hero_busy: bool,
    logo_on_dark: bool,
) -> bool:
    if has_hero or hero_busy or logo_on_dark:
        return False
    primary = _pick_color(kit, 0, "#1a365d")
    if _hex_luminance(primary) > 0.62 and _logo_mark_luminance(kit) < _LOGO_MARK_DARK_LUMINANCE:
        return True
    return False


def _brand_gradient_steps(
    primary: str,
    secondary: str,
    accent: str,
) -> list[dict[str, Any]]:
    """Simulate a 2–3 stop brand gradient without a native gradient layer."""
    return [
        {
            "command": "layer.newFillLayer.solidColor",
            "params": {"color": primary, "name": "Brand base"},
        },
        {
            "command": "layer.newFillLayer.solidColor",
            "params": {"color": secondary, "name": "Brand mid"},
        },
        {
            "command": "layer.setProps",
            "params": {"name": "Brand mid", "opacity": 0.48},
        },
        {
            "command": "layer.newFillLayer.solidColor",
            "params": {"color": accent, "name": "Brand accent"},
        },
        {
            "command": "layer.setProps",
            "params": {"name": "Brand accent", "opacity": 0.28},
        },
    ]


def asset_cache_basename(url: str, prefix: str = "asset") -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    ext = ".png"
    lower = url.lower().split("?", 1)[0]
    for candidate in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"):
        if lower.endswith(candidate):
            ext = candidate if candidate != ".jpeg" else ".jpg"
            break
    return f"{prefix}-{digest}{ext}"


def logo_cache_basename(logo_url: str) -> str:
    return asset_cache_basename(logo_url, "logo")


def hero_cache_basename(hero_url: str) -> str:
    return asset_cache_basename(hero_url, "hero")


def cover_scale_percent(
    img_width: int,
    img_height: int,
    canvas_width: int = LINKEDIN_WIDTH,
    canvas_height: int = LINKEDIN_HEIGHT,
) -> float:
    """Scale % so the image covers the canvas (both sides meet or exceed)."""
    if img_width <= 0 or img_height <= 0:
        return 100.0
    return max(canvas_width / img_width, canvas_height / img_height) * 100.0


def _logo_target_width(img_width: int) -> int:
    if img_width <= 0:
        return LOGO_TARGET_WIDTH
    if img_width >= LOGO_TARGET_WIDTH_MAX:
        return LOGO_TARGET_WIDTH_MAX
    if img_width <= LOGO_TARGET_WIDTH_MIN:
        return LOGO_TARGET_WIDTH_MIN
    return min(LOGO_TARGET_WIDTH_MAX, max(LOGO_TARGET_WIDTH_MIN, LOGO_TARGET_WIDTH))


def logo_scale_percent(
    img_width: int,
    *,
    target_width: int | None = None,
) -> float:
    target = target_width if target_width is not None else _logo_target_width(img_width)
    if img_width <= 0:
        return max(12.0, (target / 480.0) * 100.0)
    return max(8.0, (target / img_width) * 100.0)


def _logo_layout(
    img_width: int = 0,
    img_height: int = 0,
) -> dict[str, float]:
    target_w = _logo_target_width(img_width)
    if img_width > 0 and img_height > 0:
        target_h = max(1.0, target_w * (img_height / img_width))
    else:
        target_h = target_w * (LOGO_KNOCKBACK_BASE_HEIGHT / LOGO_KNOCKBACK_BASE_WIDTH)
    if target_h > LOGO_MAX_HEIGHT:
        target_h = float(LOGO_MAX_HEIGHT)
        if img_width > 0 and img_height > 0:
            target_w = max(
                LOGO_TARGET_WIDTH_MIN,
                min(LOGO_TARGET_WIDTH_MAX, target_h * (img_width / img_height)),
            )
    knock_w = target_w + 2 * LOGO_KNOCKBACK_PAD
    center_x = LINKEDIN_WIDTH - LOGO_MARGIN - target_w / 2
    center_y = LOGO_MARGIN + target_h / 2
    return {
        "target_width": target_w,
        "target_height": target_h,
        "center_x": center_x,
        "center_y": center_y,
        "logo_scale": logo_scale_percent(img_width, target_width=int(round(target_w))),
        "knockback_scale": (knock_w / LOGO_KNOCKBACK_BASE_WIDTH) * 100.0,
    }


def _hero_background_placement(
    hero_relative_path: str,
    *,
    img_width: int | None = None,
    img_height: int | None = None,
) -> dict[str, Any]:
    placement: dict[str, Any] = {
        "path": hero_relative_path.replace("\\", "/"),
        "center": [LINKEDIN_WIDTH / 2, LINKEDIN_HEIGHT / 2],
        "fit": False,
        "smartObject": True,
        "name": "Hero image",
        "cover": True,
    }
    if img_width and img_height:
        placement["scale"] = round(
            cover_scale_percent(img_width, img_height), 2
        )
    return placement


def _logo_knockback_placement(
    *,
    img_width: int = 0,
    img_height: int = 0,
) -> dict[str, Any]:
    layout = _logo_layout(img_width, img_height)
    return {
        "path": LOGO_KNOCKBACK_REL,
        "center": [layout["center_x"], layout["center_y"]],
        "scale": round(layout["knockback_scale"], 2),
        "smartObject": False,
        "name": "Logo knockback",
    }


def _logo_foreground_placement(
    logo_relative_path: str,
    *,
    img_width: int | None = None,
    img_height: int | None = None,
) -> dict[str, Any]:
    layout = _logo_layout(img_width or 0, img_height or 0)
    return {
        "path": logo_relative_path.replace("\\", "/"),
        "center": [layout["center_x"], layout["center_y"]],
        "scale": round(layout["logo_scale"], 2),
        "smartObject": True,
        "name": "Logo",
    }


def _color_with_alpha(hex_color: str, alpha: float) -> list[float]:
    hex6 = _normalize_hex(hex_color, "#ffffff").lstrip("#")
    r, g, b = (int(hex6[i : i + 2], 16) for i in (0, 2, 4))
    return [r, g, b, alpha]


def _show_footer(site_name: str, *, has_logo: bool) -> bool:
    if not has_logo:
        return True
    cleaned = re.sub(r"\s+", " ", site_name or "").strip()
    if not cleaned or cleaned.casefold() in {"learn more", "home", "accueil"}:
        return False
    return False


def _first_fact_sentence(session: dict[str, Any], skip: str) -> str:
    facts = (session.get("brief") or {}).get("facts") or ""
    for line in facts.splitlines():
        line = line.strip()
        if not line:
            continue
        if _normalize_compare(line) == _normalize_compare(skip):
            continue
        sentence = re.split(r"(?<=[.!?])\s+", line, maxsplit=1)[0].strip()
        return _truncate(sentence or line, 140)
    return ""


def compile_poster_batch(
    kit: dict[str, Any] | None,
    session: dict[str, Any],
    *,
    logo_relative_path: str | None = None,
    hero_relative_path: str | None = None,
    hero_width: int | None = None,
    hero_height: int | None = None,
    logo_width: int | None = None,
    logo_height: int | None = None,
    fonts_resolved: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a PhotoCraft command batch for a LinkedIn 1200×627 poster."""
    kit = kit or session.get("kitSnapshot") or {}
    headline, kit_subline = _resolve_headline_hierarchy(kit, session)
    fact_subline = _first_fact_sentence(session, headline)
    subline = kit_subline
    if not subline and fact_subline and _normalize_compare(fact_subline) != _normalize_compare(
        headline
    ):
        subline = fact_subline
    body = _truncate(
        _body_lines(session, skip_headline=headline),
        200,
    )
    if subline and body and _normalize_compare(body.splitlines()[0]) == _normalize_compare(
        subline
    ):
        body_lines = body.splitlines()[1:]
        body = "\n".join(body_lines).strip()
        body = _truncate(body, 200)
    site_name = _pick_site_name(kit)
    if subline and _normalize_compare(subline) == _normalize_compare(site_name):
        subline = ""

    hero_busy = bool(kit.get("heroBusy"))
    if hero_busy:
        hero_relative_path = None

    if not hero_width or not hero_height:
        kit_w = (kit or {}).get("heroWidth")
        kit_h = (kit or {}).get("heroHeight")
        try:
            hero_width = int(kit_w) if kit_w else hero_width
            hero_height = int(kit_h) if kit_h else hero_height
        except (TypeError, ValueError):
            pass

    primary = _pick_color(kit, 0, "#1a365d")
    secondary = _pick_color(kit, 1, "#2c5282")
    accent = _pick_color(kit, 2, secondary)
    text_on_dark = "#ffffff"
    text_on_light = _contrast_text_color(primary)
    resolved = fonts_resolved or {}
    headline_font = str(resolved.get("headline") or _pick_headline_font(kit))
    body_font = str(resolved.get("body") or _pick_body_font(kit, headline_font))
    headline_style = resolved.get("headlineStyle") or _headline_font_style(
        kit, headline_font
    )

    has_hero = bool(hero_relative_path)
    logo_on_dark = should_logo_on_dark(kit, has_hero=has_hero, hero_busy=hero_busy)
    use_knockback = _use_logo_knockback(
        kit,
        has_hero=has_hero,
        hero_busy=hero_busy,
        logo_on_dark=logo_on_dark,
    )
    scrim_opacity = 0.48 if kit.get("heroImageKind") == "ui-screenshot" else 0.42
    bg_color = secondary if has_hero else primary

    document = {
        "width": LINKEDIN_WIDTH,
        "height": LINKEDIN_HEIGHT,
        "mode": "rgb",
        "depth": 8,
        "background": bg_color,
        "resolution": 72,
        "name": f"CommMaker LinkedIn — {site_name}",
    }

    steps: list[dict[str, Any]] = []

    if has_hero:
        steps.append(
            {
                "command": "layer.newFillLayer.solidColor",
                "params": {"color": primary, "name": "Hero scrim"},
            }
        )
        steps.append(
            {
                "command": "layer.setProps",
                "params": {"name": "Hero scrim", "opacity": scrim_opacity},
            }
        )
    else:
        steps.extend(_brand_gradient_steps(primary, secondary, accent))

    text_color = text_on_dark if has_hero else text_on_light
    text_right = SAFE_PAD + TEXT_BLOCK_MAX_WIDTH
    has_logo = bool(logo_relative_path)
    show_footer = _show_footer(site_name, has_logo=has_logo)
    footer_top = LINKEDIN_HEIGHT - SAFE_PAD - 28
    subline_bottom = footer_top - 8 if show_footer else LINKEDIN_HEIGHT - SAFE_PAD - 4
    subline_top = subline_bottom - 56 if subline else subline_bottom
    headline_bottom = subline_top - 12
    headline_top = headline_bottom - 108
    headline_size = HEADLINE_SIZE_SOLO if not subline else HEADLINE_SIZE_WITH_SUB
    headline_params: dict[str, Any] = {
        "name": "Headline",
        "box": [SAFE_PAD, headline_top, text_right, headline_bottom],
        "text": headline,
        "font": headline_font,
        "size": headline_size,
        "color": text_color,
        "align": "left",
    }
    if headline_style:
        headline_params["fontStyle"] = headline_style
    steps.append({"command": "type.create", "params": headline_params})

    if subline:
        steps.append(
            {
                "command": "type.create",
                "params": {
                    "name": "Subline",
                    "box": [SAFE_PAD, subline_top, text_right, subline_bottom],
                    "text": subline,
                    "font": body_font,
                    "size": SUBLINE_SIZE,
                    "color": _color_with_alpha(text_color, SUBLINE_OPACITY),
                    "align": "left",
                },
            }
        )

    if body:
        body_bottom = headline_top - 8
        body_top = max(SAFE_PAD, body_bottom - 100)
        steps.append(
            {
                "command": "type.create",
                "params": {
                    "name": "Body",
                    "box": [SAFE_PAD, body_top, text_right, body_bottom],
                    "text": body,
                    "font": body_font,
                    "size": 20,
                    "color": text_color,
                    "align": "left",
                },
            }
        )

    if show_footer:
        footer_color = "#cbd5e1" if has_hero else text_on_light
        steps.append(
            {
                "command": "type.create",
                "params": {
                    "name": "Footer",
                    "box": [
                        SAFE_PAD,
                        footer_top,
                        text_right,
                        LINKEDIN_HEIGHT - SAFE_PAD,
                    ],
                    "text": site_name,
                    "font": body_font,
                    "size": 18,
                    "color": footer_color,
                    "align": "left",
                },
            }
        )

    background_placements: list[dict[str, Any]] = []
    if hero_relative_path:
        background_placements.append(
            _hero_background_placement(
                hero_relative_path,
                img_width=hero_width,
                img_height=hero_height,
            )
        )

    logo_layout = _logo_layout(logo_width or 0, logo_height or 0)
    foreground_placements: list[dict[str, Any]] = []
    if logo_relative_path:
        if use_knockback:
            foreground_placements.append(
                _logo_knockback_placement(
                    img_width=logo_width or 0,
                    img_height=logo_height or 0,
                )
            )
        foreground_placements.append(
            _logo_foreground_placement(
                logo_relative_path,
                img_width=logo_width,
                img_height=logo_height,
            )
        )

    poster_id = uuid.uuid4().hex[:12]
    filename = f"commmaker-poster-{poster_id}.pcraft"

    return {
        "format": BATCH_FORMAT,
        "photocraftVersion": "0.9.x",
        "canvas": {"width": LINKEDIN_WIDTH, "height": LINKEDIN_HEIGHT},
        "document": document,
        "stop_on_error": True,
        "steps": steps,
        "backgroundPlacements": background_placements,
        "placements": foreground_placements,
        "output": {"relativePath": f"generated/{filename}"},
        "meta": {
            "headline": headline,
            "tagline": subline,
            "siteName": site_name,
            "primaryColor": primary,
            "accentColor": accent,
            "hasHero": has_hero,
            "heroBusy": hero_busy,
            "logoOnDark": logo_on_dark,
            "logoKnockback": use_knockback,
            "hasLogo": has_logo,
            "logoLayout": {
                "targetWidthPx": int(round(logo_layout["target_width"])),
                "targetHeightPx": int(round(logo_layout["target_height"])),
                "logoScalePercent": round(logo_layout["logo_scale"], 2),
                "knockbackScalePercent": round(logo_layout["knockback_scale"], 2),
            },
            "typography": {
                "headlineSize": headline_size,
                "sublineSize": SUBLINE_SIZE if subline else None,
            },
            "fonts": {
                "headline": headline_font,
                "body": body_font,
            },
        },
    }
