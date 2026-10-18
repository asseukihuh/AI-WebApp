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
import os
import re
import uuid
from typing import Any

import communication_kit as kit_design
import poster_design as design
from creative_brief import brand_layout_energy, clean_composition, default_composition, sharper_subline

LINKEDIN_WIDTH = 1200
LINKEDIN_HEIGHT = 627
ACCENT_MAX_WIDTH_FRACTION = 0.45
ACCENT_CENTER_X = LINKEDIN_WIDTH * 0.72
ACCENT_CENTER_Y = LINKEDIN_HEIGHT * 0.48
LOGO_TARGET_WIDTH = 280
LOGO_TARGET_WIDTH_MIN = 220
LOGO_TARGET_WIDTH_MAX = 320
LOGO_ICON_MAX_HEIGHT = 64
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


def _hex_luminance(hex_color: str) -> float:
    hex6 = _normalize_hex(hex_color, "#000000").lstrip("#")
    if len(hex6) != 6:
        return 0.0
    r, g, b = (int(hex6[i : i + 2], 16) for i in (0, 2, 4))
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


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


def should_recolor_logo_light(
    kit: dict[str, Any] | None,
    *,
    has_photo_hero: bool,
    hero_busy: bool = False,
    hero_brand_mark: bool = False,
) -> bool:
    """Use a light (#fff) logo mark on bright photo heroes or dark gradient backgrounds."""
    if should_logo_on_dark(kit, has_hero=has_photo_hero, hero_busy=hero_busy):
        return True
    if hero_busy:
        return False
    if hero_brand_mark:
        return True
    if not has_photo_hero:
        palette = _palette_from_kit(kit)
        if palette:
            bg_lum = min(_hex_luminance(c) for c in palette[:3])
            if bg_lum < 0.42:
                return True
    return False


def logo_svg_dimensions_oversized(width: int, height: int) -> bool:
    """Inline SVGs sized like a poster card should not be placed as the logo mark."""
    return width >= 900 and height >= 400


def count_logo_placements(batch: dict[str, Any]) -> int:
    """Count foreground logo asset placements (excludes knockback plate)."""
    total = 0
    for placement in batch.get("placements") or []:
        name = str(placement.get("name") or "")
        if name == "Logo":
            total += 1
    return total


def recolor_logo_svg(svg: str, fill: str, *, mode: str) -> str:
    """Recolor a logo SVG for a light (``mode="light"``) or dark (``mode="dark"``) variant.

    Light swaps dark fills to ``fill``; dark swaps light fills. ``currentColor`` and SVGs
    without any fill (black by default) are recolored in both modes.
    """

    def _maybe_swap(color: str) -> str:
        lower = (color or "").lower()
        if lower == "currentcolor":
            return fill
        if lower in ("none", "transparent") or not lower.startswith("#"):
            return color
        lum = _hex_luminance(color)
        if mode == "light" and lum < _LOGO_MARK_DARK_LUMINANCE:
            return fill
        if mode == "dark" and lum > 0.6:
            return fill
        return color

    def _attr_repl(match: re.Match[str]) -> str:
        quote, raw = match.group(1), match.group(2)
        swapped = _maybe_swap(raw)
        if swapped == raw:
            return match.group(0)
        return f"fill={quote}{swapped}{quote}"

    def _style_repl(match: re.Match[str]) -> str:
        raw = match.group(1)
        swapped = _maybe_swap(raw)
        if swapped == raw:
            return match.group(0)
        return f"fill:{swapped}"

    has_fill = bool(_SVG_FILL_ATTR_RE.search(svg) or _SVG_STYLE_FILL_RE.search(svg))
    out = _SVG_STYLE_FILL_RE.sub(_style_repl, _SVG_FILL_ATTR_RE.sub(_attr_repl, svg))
    if not has_fill and mode == "light":
        out = re.sub(r"<svg\b", f'<svg fill="{fill}"', out, count=1)
    return out


def recolor_logo_svg_for_light_hero(svg: str, light_fill: str = "#ffffff") -> str:
    """Replace dark SVG path fills with a light fill for bright photo heroes."""
    return recolor_logo_svg(svg, light_fill, mode="light")


def standalone_logo_svg(svg: str) -> str:
    """Make an inline page SVG renderable on its own (xmlns, no unresolved CSS-variable fills)."""
    out = re.sub(r'\sfill\s*=\s*(["\'])var\([^)]*\)\1', "", svg)
    if not re.search(r"<svg\b[^>]*\bxmlns=", out):
        out = re.sub(r"<svg\b", '<svg xmlns="http://www.w3.org/2000/svg"', out, count=1)
    return out


def logo_svg_variants(svg: str) -> dict[str, str]:
    """``original`` / ``light`` / ``dark`` SVG payloads for luminance-based logo choice."""
    svg = standalone_logo_svg(svg)
    return {
        "original": svg,
        "light": recolor_logo_svg(svg, design.WHITE, mode="light"),
        "dark": recolor_logo_svg(svg, design.INK, mode="dark"),
    }


def ensure_brand_gradient_svg_stops(
    assets_dir: str,
    stops: list[tuple[float, str]],
) -> str:
    """Write (or reuse) a diagonal brand gradient SVG matching ``poster_design`` stops."""
    normalized = [(round(t, 3), _normalize_hex(c, "#1a365d")) for t, c in stops]
    key = "|".join(f"{t}:{c}" for t, c in normalized)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    filename = f"brand-gradient-{digest}.svg"
    abs_path = os.path.join(assets_dir, filename)
    os.makedirs(assets_dir, exist_ok=True)
    if not os.path.isfile(abs_path):
        stop_tags = "".join(
            f'<stop offset="{t * 100:g}%" stop-color="{c}"/>' for t, c in normalized
        )
        markup = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {LINKEDIN_WIDTH} {LINKEDIN_HEIGHT}" '
            f'preserveAspectRatio="none">'
            f'<defs><linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">{stop_tags}'
            f"</linearGradient></defs>"
            f'<rect width="{LINKEDIN_WIDTH}" height="{LINKEDIN_HEIGHT}" fill="url(#bg)"/>'
            f"</svg>"
        )
        with open(abs_path, "w", encoding="utf-8") as handle:
            handle.write(markup)
    return f"generated/assets/{filename}"


def _brand_gradient_background_placement(relative_path: str) -> dict[str, Any]:
    return {
        "path": relative_path.replace("\\", "/"),
        "center": [LINKEDIN_WIDTH / 2, LINKEDIN_HEIGHT / 2],
        "scale": 100.0,
        "fit": True,
        "smartObject": False,
        "name": "Brand gradient",
    }


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


def region_cover_scale_percent(
    img_width: int,
    img_height: int,
    region_width: float,
    region_height: float,
) -> float:
    """Scale % of native pixels so the bitmap covers the picture well.

    Contain (the shorter side) leaves a tiny inset. Native 100% leaves a small
    file small. Cover enlarges or crops until both sides of the well are filled.
    """
    if img_width <= 0 or img_height <= 0 or region_width <= 0 or region_height <= 0:
        return 100.0
    return max(region_width / img_width, region_height / img_height) * 100.0


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


def _hero_background_placement(
    hero_relative_path: str,
    *,
    img_width: int | None = None,
    img_height: int | None = None,
    layer_name: str = "Hero image",
) -> dict[str, Any]:
    placement: dict[str, Any] = {
        "path": hero_relative_path.replace("\\", "/"),
        "center": [LINKEDIN_WIDTH / 2, LINKEDIN_HEIGHT / 2],
        "fit": False,
        "smartObject": True,
        "name": layer_name,
        "cover": True,
    }
    if img_width and img_height:
        placement["scale"] = round(
            cover_scale_percent(img_width, img_height), 2
        )
    return placement


def _accent_background_placement(
    accent_relative_path: str,
    *,
    img_width: int | None = None,
    img_height: int | None = None,
) -> dict[str, Any]:
    max_w = LINKEDIN_WIDTH * ACCENT_MAX_WIDTH_FRACTION
    max_h = LINKEDIN_HEIGHT * 0.58
    scale = 45.0
    if img_width and img_height and img_width > 0 and img_height > 0:
        scale = min((max_w / img_width) * 100.0, (max_h / img_height) * 100.0)
    return {
        "path": accent_relative_path.replace("\\", "/"),
        "center": [ACCENT_CENTER_X, ACCENT_CENTER_Y],
        "scale": round(scale, 2),
        "fit": True,
        "smartObject": True,
        "name": "Accent illustration",
    }


def _brief_wants_photo_hero(creative_brief: dict[str, Any] | None) -> bool:
    if not creative_brief:
        return True
    layout = creative_brief.get("layoutRecipe")
    hero = creative_brief.get("heroStrategy")
    if layout in ("gradient-brand", "minimal-wordmark"):
        return False
    if hero in ("gradient_from_palette", "solid", "none"):
        return False
    return hero in ("use_kit_photo", "ideogram_generate") or layout == "photo-hero-type"


def _apply_creative_brief_to_compile(
    kit: dict[str, Any],
    *,
    headline: str,
    subline: str,
    creative_brief: dict[str, Any] | None,
    hero_relative_path: str | None,
) -> tuple[str, str, str | None, bool, bool, bool, bool | None]:
    """Return headline, subline, hero path, brand_mark_grad, solid_bg, skip_std_gradient, logo_recolor_override."""
    hero_brand_mark = bool(kit.get("heroBrandMark"))
    force_solid = False
    skip_std_gradient = False
    logo_recolor: bool | None = None
    if not creative_brief:
        return headline, subline, hero_relative_path, hero_brand_mark, force_solid, skip_std_gradient, logo_recolor

    if creative_brief.get("headline"):
        headline = _truncate(str(creative_brief["headline"]), 90)
    if creative_brief.get("subhead"):
        subline = str(creative_brief["subhead"]).strip()

    layout = creative_brief.get("layoutRecipe") or ""
    hero = creative_brief.get("heroStrategy") or ""
    logo = creative_brief.get("logoTreatment") or ""

    if not _brief_wants_photo_hero(creative_brief):
        hero_relative_path = None

    if layout == "minimal-wordmark":
        hero_brand_mark = True
        hero_relative_path = None
    elif layout == "gradient-brand":
        hero_brand_mark = False
        hero_relative_path = None
    elif layout == "photo-hero-type" and hero in ("use_kit_photo", "ideogram_generate"):
        hero_brand_mark = False

    if hero == "solid":
        hero_relative_path = None
        hero_brand_mark = False
        force_solid = True
        skip_std_gradient = True
    elif hero == "gradient_from_palette":
        hero_relative_path = None
    elif hero == "none":
        hero_relative_path = None
        hero_brand_mark = False

    if logo == "wordmark-white":
        logo_recolor = True
    elif logo == "wordmark-dark":
        logo_recolor = False
    elif logo == "symbol-only":
        logo_recolor = True

    return (
        headline,
        subline,
        hero_relative_path,
        hero_brand_mark,
        force_solid,
        skip_std_gradient,
        logo_recolor,
    )


def should_skip_hero_for_brief(
    kit: dict[str, Any] | None,
    creative_brief: dict[str, Any] | None,
) -> bool:
    """Whether asset download should skip kit hero image for this brief."""
    if not creative_brief:
        return design.kit_hero_unsuitable(kit)
    if not _brief_wants_photo_hero(creative_brief):
        return True
    if creative_brief.get("heroStrategy") == "ideogram_generate":
        return True
    return design.kit_hero_unsuitable(kit)


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


def _scrim_geometry(
    kind: str,
    text_zone: tuple[float, float, float, float],
    alpha: float,
) -> dict[str, Any] | None:
    """Gradient Fill params: hold ``alpha`` across the text zone, fade to 0 within SCRIM_FADE_PX."""
    x, y, w, h = text_zone
    pad = 24.0
    x0, y0, x1, y1 = x - pad, y - pad, x + w + pad, y + h + pad
    opacity = round(alpha * 100, 1)
    if kind == "diagonal":
        dx, dy = 0.33, -0.944
        ax, ay = 0.0, float(LINKEDIN_HEIGHT)
        reach = max((cx - ax) * dx + (cy - ay) * dy for cx, cy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)))
        length = reach + design.SCRIM_FADE_PX
        return {
            "from": [ax, ay],
            "to": [round(ax + dx * length, 1), round(ay + dy * length, 1)],
            "style": "linear",
            "hold": round(reach / length, 3),
            "opacity": opacity,
        }
    if kind == "radial":
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        reach = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 / 2
        length = reach + design.SCRIM_FADE_PX
        return {
            "from": [round(cx, 1), round(cy, 1)],
            "to": [round(cx + length, 1), round(cy, 1)],
            "style": "radial",
            "hold": round(reach / length, 3),
            "opacity": opacity,
        }
    if kind == "horizontal":
        reach = x1
        length = reach + design.SCRIM_FADE_PX
        return {
            "from": [0.0, LINKEDIN_HEIGHT / 2],
            "to": [round(length, 1), LINKEDIN_HEIGHT / 2],
            "style": "linear",
            "hold": round(reach / length, 3),
            "opacity": opacity,
        }
    return None


def _gradient_steps(
    name: str,
    color: str,
    geometry: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        {
            "command": "gradient.fill.create",
            "params": {
                "from": geometry["from"],
                "to": geometry["to"],
                "style": geometry["style"],
                "stops": [[0, color], [1, color]],
                "transparency": [
                    [0, geometry["opacity"]],
                    [geometry["hold"], geometry["opacity"]],
                    [1, 0],
                ],
            },
        },
        {"command": "layer.setProps", "params": {"name": name}},
    ]


def _native_brand_gradient_steps(stops: list[tuple[float, str]]) -> list[dict[str, Any]]:
    return [
        {
            "command": "gradient.fill.create",
            "params": {
                "from": [0, 0],
                "to": [LINKEDIN_WIDTH, LINKEDIN_HEIGHT],
                "style": "linear",
                "stops": [[round(t, 3), c] for t, c in stops],
            },
        },
        {"command": "layer.setProps", "params": {"name": "Brand gradient"}},
    ]


def _shape_step(kind: str, name: str, rect: list[float], fill: str, radii: float | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {
        "kind": kind,
        "name": name,
        "rect": [round(v, 1) for v in rect],
        "fill": fill,
    }
    if kind == "roundedRect":
        params["radii"] = 28 if radii is None else radii
    return {"command": "shape.create", "params": params}


def _dark_neutral(kit: dict[str, Any] | None, roles: design.BrandRoles) -> str:
    """Near-black from the captured palette, so a stark mark is not painted in a CSS accent."""
    for color in list(design.kit_palette(kit)) + [roles.dark, roles.brand]:
        rgb = design.hex_to_rgb(color)
        if design.relative_luminance(rgb) < 0.08 and design.chroma(rgb) < 0.12:
            return color
    return "#111111"


def _ground_color(
    template_name: str,
    energy: str,
    kit: dict[str, Any] | None,
    roles: design.BrandRoles,
) -> str | None:
    """Flat field for layouts that are not a diagonal gradient. None keeps the gradient path."""
    if template_name == "mark-stage":
        return _dark_neutral(kit, roles)
    if template_name == "circle-stage" or (template_name == "centered-statement" and energy == "quiet-type"):
        light = roles.light
        if design.relative_luminance(design.hex_to_rgb(light)) > 0.75:
            return light
        return "#f6f3ee"
    if template_name == "product-card":
        return roles.brand
    if template_name == "device-stage":
        return design.mix_hex(roles.brand, "#ffffff", 0.78)
    if template_name == "photo-block":
        return "#f3eadf"
    if template_name == "type-only":
        return roles.brand
    if template_name in ("communique", "product-ui"):
        return "#ffffff"
    if template_name == "photo-card":
        return "#efeae4"
    if template_name == "character-scene":
        return "#f7f4ef"
    return None


def _photo_standin_steps(region: tuple[float, float, float, float], accent: str) -> list[dict[str, Any]]:
    """A text-free interior crop used when Ideogram is not available."""
    x, y, w, h = region
    return [
        _shape_step("rect", "Photo wall", [x, y, w, h], "#f3eadf"),
        _shape_step("ellipse", "Photo window", [x + w * 0.52, y + 36, w * 0.4, h * 0.46], "#fffaf4"),
        _shape_step("roundedRect", "Photo furniture", [x + 40, y + h * 0.62, w * 0.7, h * 0.26], "#d7c0a4"),
        _shape_step("ellipse", "Photo accent", [x + w * 0.58, y + h * 0.55, 150, 110], accent),
    ]


def _scene_standin_steps(accent: str) -> list[dict[str, Any]]:
    """A simple backdrop so a character poster is not a flat field."""
    return [
        _shape_step("rect", "Scene sky", [0, 0, LINKEDIN_WIDTH, 430], "#f4efe6"),
        _shape_step("rect", "Scene ground", [0, 430, LINKEDIN_WIDTH, 197], "#e7efe4"),
        _shape_step("roundedRect", "Scene block", [760, 160, 220, 250], accent),
    ]


def _figure_standin_steps() -> list[dict[str, Any]]:
    """A stand-in character holding a card. Not a claim about a real mascot."""
    return [
        _shape_step("ellipse", "Character body", [500, 70, 220, 250], "#f3e0c8"),
        _shape_step("ellipse", "Character head", [545, 16, 130, 120], "#f7e7d6"),
        _shape_step("roundedRect", "Wordmark card", [250, 150, 280, 120], "#ffffff"),
    ]


def _lesson_standin_steps(accent: str) -> list[dict[str, Any]]:
    return [
        _shape_step("roundedRect", "Lesson card", [80, 48, 1040, 530], "#ffffff"),
        _shape_step("roundedRect", "Lesson progress", [140, 90, 620, 18], "#ececec", radii=9),
        _shape_step("roundedRect", "Lesson progress fill", [140, 90, 180, 18], accent, radii=9),
        _shape_step("roundedRect", "Answer chip", [140, 400, 160, 64], "#d8f5a2", radii=32),
        _shape_step("roundedRect", "Answer chip 2", [320, 400, 180, 64], "#d8f5a2", radii=32),
        _shape_step("roundedRect", "Answer chip 3", [520, 400, 200, 64], "#d8f5a2", radii=32),
        _shape_step("roundedRect", "Continue bar", [140, 490, 760, 56], accent, radii=16),
    ]


def _photo_card_steps(region: tuple[float, float, float, float], accent: str) -> list[dict[str, Any]]:
    x, y, w, h = region
    return [
        _shape_step("roundedRect", "Photo card", [x - 28, y - 24, w + 56, 500], "#ffffff"),
        *_photo_standin_steps((x, y, w, h), accent),
    ]


def _product_standin_steps(region: tuple[float, float, float, float], accent: str) -> list[dict[str, Any]]:
    x, y, w, h = region
    return [
        _shape_step("roundedRect", "Product card", [x, y, w, h], "#fffdf8"),
        _shape_step("roundedRect", "Product pack", [x + w * 0.18, y + h * 0.16, w * 0.64, h * 0.62], accent),
    ]


def _brand_glow_steps(color: str) -> list[dict[str, Any]]:
    return [
        {
            "command": "gradient.fill.create",
            "params": {
                "from": [LINKEDIN_WIDTH * 0.86, LINKEDIN_HEIGHT * 0.12],
                "to": [LINKEDIN_WIDTH * 0.86 + 520, LINKEDIN_HEIGHT * 0.12],
                "style": "radial",
                "stops": [[0, color], [1, color]],
                "transparency": [[0, 38], [1, 0]],
            },
        },
        {"command": "layer.setProps", "params": {"name": "Brand glow"}},
    ]


def _type_step(
    name: str,
    text: str,
    box: tuple[float, float, float, float] | list[float],
    *,
    font: str,
    size: float,
    color: str | list[float],
    weight: int,
    align: str,
    leading: float | None = None,
    tracking: int | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "name": name,
        "box": [round(v, 1) for v in box],
        "text": text,
        "font": font,
        "size": size,
        "color": color,
        "weight": weight,
        "align": align,
    }
    if leading:
        params["leading"] = leading
    if tracking:
        params["tracking"] = tracking
    return {"command": "type.create", "params": params}


def _pick_text_and_scrim(
    samples: list[design.RGB],
    roles: design.BrandRoles,
) -> tuple[str, float | None, str]:
    """Return (text colour, scrim alpha or None if impossible, scrim colour)."""
    ink = roles.dark if design.contrast_ratio(design.hex_to_rgb(roles.dark), (255, 255, 255)) >= 12 else design.INK
    options = []
    for text, scrim in ((design.WHITE, roles.dark), (ink, "#ffffff")):
        worst = design.worst_samples(samples, for_light_text=text == design.WHITE)
        alpha = design.required_scrim_alpha(worst, design.hex_to_rgb(scrim), design.hex_to_rgb(text))
        options.append((text, alpha, scrim))
    white, dark = options
    if white[1] is None and dark[1] is None:
        return white
    if white[1] is None:
        return dark
    if dark[1] is None:
        return white
    # Prefer white type (stronger editorial look) unless dark type needs clearly less scrim.
    return dark if dark[1] + 0.25 < white[1] else white


def _pick_logo_variant(
    available: dict[str, str],
    colors: dict[str, str],
    samples: list[design.RGB],
    preference: str | None,
) -> tuple[str, float]:
    order = ["original", "light", "dark"]
    if preference == "wordmark-white" or preference == "symbol-only":
        order = ["light", "original", "dark"]
    elif preference == "wordmark-dark":
        order = ["dark", "original", "light"]
    scored = []
    for name in order:
        if name not in available:
            continue
        ratio = design.min_contrast(design.hex_to_rgb(colors[name]), samples)
        scored.append((name, ratio))
        if ratio >= design.GRAPHIC_CONTRAST_MIN:
            return name, ratio
    if not scored:
        return "original", 0.0
    return max(scored, key=lambda item: item[1])


def _cta_colors(
    roles: design.BrandRoles,
    style: str,
    text_color: str,
    behind: list[design.RGB],
) -> dict[str, Any]:
    white = (255, 255, 255)
    ink = design.hex_to_rgb(design.INK)
    if style == "outline":
        return {"fill": None, "stroke": text_color, "label": text_color, "chipContrast": design.min_contrast(design.hex_to_rgb(text_color), behind)}
    candidates: list[str] = []
    if roles.accent:
        candidates.append(roles.accent)
    bg_dark = sum(design.relative_luminance(c) for c in behind) / max(1, len(behind)) < 0.3
    candidates.append(design.WHITE if bg_dark else roles.dark if not roles.monochrome else design.INK)
    for fill in candidates:
        rgb = design.hex_to_rgb(fill)
        label = design.WHITE if design.contrast_ratio(rgb, white) >= design.contrast_ratio(rgb, ink) else design.INK
        label_ratio = design.contrast_ratio(rgb, design.hex_to_rgb(label))
        chip_ratio = design.min_contrast(rgb, behind)
        if label_ratio >= design.TEXT_CONTRAST_MIN and chip_ratio >= design.GRAPHIC_CONTRAST_MIN:
            return {"fill": fill, "stroke": None, "label": label, "labelContrast": label_ratio, "chipContrast": chip_ratio}
    fill = candidates[-1]
    rgb = design.hex_to_rgb(fill)
    label = design.WHITE if design.contrast_ratio(rgb, white) >= design.contrast_ratio(rgb, ink) else design.INK
    return {
        "fill": fill,
        "stroke": None,
        "label": label,
        "labelContrast": design.contrast_ratio(rgb, design.hex_to_rgb(label)),
        "chipContrast": design.min_contrast(rgb, behind),
    }


def compile_poster_batch(
    kit: dict[str, Any] | None,
    session: dict[str, Any],
    *,
    logo_relative_path: str | None = None,
    hero_relative_path: str | None = None,
    hero_width: int | None = None,
    hero_height: int | None = None,
    accent_relative_path: str | None = None,
    accent_width: int | None = None,
    accent_height: int | None = None,
    logo_width: int | None = None,
    logo_height: int | None = None,
    fonts_resolved: dict[str, Any] | None = None,
    creative_brief: dict[str, Any] | None = None,
    assets_dir: str | None = None,
    hero_grid: dict[str, Any] | None = None,
    logo_variants: dict[str, str] | None = None,
    logo_fill: str | None = None,
    brand_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a PhotoCraft command batch for a LinkedIn 1200×627 poster.

    Layout follows ``docs/poster-design-system.md``: template grid, type scale, contrast checked
    against ``hero_grid`` (see ``image_luma.load_rgb_grid``), localized gradient scrims, CTA chip,
    and a logo variant (``logo_variants``: ``original`` / ``light`` / ``dark`` paths) picked by
    background luminance. ``brand_profile`` is optional (palette roles, typography, layoutTraits).
    """
    kit = kit or session.get("kitSnapshot") or {}
    headline, kit_subline = _resolve_headline_hierarchy(kit, session)
    fact_subline = _first_fact_sentence(session, headline)
    subline = kit_subline
    if not subline and fact_subline and _normalize_compare(fact_subline) != _normalize_compare(
        headline
    ):
        subline = fact_subline
    site_name = _pick_site_name(kit)
    if subline and _normalize_compare(subline) == _normalize_compare(site_name):
        subline = ""

    hero_busy = bool(kit.get("heroBusy"))
    (
        headline,
        subline,
        hero_relative_path,
        hero_brand_mark,
        force_solid_bg,
        skip_std_gradient,
        brief_logo_recolor,
    ) = _apply_creative_brief_to_compile(
        kit,
        headline=headline,
        subline=subline,
        creative_brief=creative_brief,
        hero_relative_path=hero_relative_path,
    )
    if design.kit_hero_unsuitable(kit) and (
        not creative_brief or creative_brief.get("heroStrategy") == "use_kit_photo"
    ):
        hero_relative_path = None

    if not hero_width or not hero_height:
        try:
            hero_width = int(kit.get("heroWidth")) if kit.get("heroWidth") else hero_width
            hero_height = int(kit.get("heroHeight")) if kit.get("heroHeight") else hero_height
        except (TypeError, ValueError):
            pass

    brief = creative_brief or {}
    roles = design.brand_roles(kit, brand_profile)
    has_photo_hero = bool(hero_relative_path)
    profile_font = design.profile_fonts(brand_profile)
    comm_kit = kit.get("communicationKit") if isinstance(kit.get("communicationKit"), dict) else {}
    pairing = kit_design.kit_type_pairing(comm_kit)
    resolved = fonts_resolved or {}
    headline_font = str(
        resolved.get("headline") or profile_font.get("headline") or pairing.get("displayFamily") or _pick_headline_font(kit)
    )
    body_font = str(
        resolved.get("body") or profile_font.get("body") or pairing.get("bodyFamily") or _pick_body_font(kit, headline_font)
    )

    composition = clean_composition(brief.get("composition")) or default_composition(kit, brand_profile)
    template_name = design.resolve_template_name(
        creative_brief,
        has_image=has_photo_hero,
        monochrome=roles.monochrome,
        brand_profile=brand_profile,
        communication_kit=comm_kit or None,
    )
    # Centred statement ignores a left-hand composition and parks a dark wordmark
    # on a light purple disc. An explicit split or panel template is left alone.
    if composition.get("textRegion") in ("left", "bottom-left") and template_name == "centered-statement":
        template_name = "full-bleed-scrim"

    subline = sharper_subline(
        kit,
        {
            "crisisMessage": headline,
            "crisisFacts": str((session.get("brief") or {}).get("facts") or ""),
        },
        brand_profile,
        subline,
    )
    subline = design.clamp_words(subline, design.MAX_WORDS["subline"], design.MAX_CHARS["subline"])
    eyebrow = str(brief.get("eyebrow") or "").strip()
    cta = str(brief.get("cta") or "").strip()
    cta_style = brief.get("ctaStyle") if brief.get("ctaStyle") in design.CTA_STYLES else "pill"
    if composition.get("showCta") and not cta:
        cta = "Learn more"
        cta_style = "pill"
    if composition.get("showCta") and cta_style == "none":
        cta_style = "pill"
    if not cta:
        cta_style = "none"
    headline_scale = brief.get("headlineScale")
    headline_weight = brief.get("headlineWeight") or profile_font.get("headlineWeight")

    logo_paths: dict[str, str] = dict(logo_variants or {})
    if logo_relative_path and "original" not in logo_paths:
        logo_paths["original"] = logo_relative_path
    has_logo = bool(logo_paths)
    logo_size = design.logo_target_size(logo_width, logo_height) if has_logo else None
    min_logo = float((comm_kit.get("logoSystem") or {}).get("minHeightPx") or 0)
    if logo_size and min_logo and logo_size[1] < min_logo and logo_size[1] > 0:
        aspect = logo_size[0] / logo_size[1]
        logo_h = min_logo
        logo_w = logo_h * aspect
        max_w = design.span_w(3)
        if logo_w > max_w:
            logo_w = max_w
            logo_h = logo_w / aspect
        logo_size = (logo_w, logo_h)

    def _plan(name: str) -> design.LayoutPlan:
        return design.plan_layout(
            name,
            headline=headline,
            subline=subline,
            eyebrow=eyebrow,
            cta=cta,
            cta_style=cta_style,
            headline_scale=headline_scale,
            headline_weight=headline_weight,
            logo_size=logo_size,
        )

    identity_stops = design.identity_gradient_stops(brand_profile, roles)
    wants_gradient = any(
        item.get("source") == "palette-gradient" for item in composition.get("visuals") or []
    ) or composition.get("field") in ("ideogram", "palette-gradient")
    gradient_stops = identity_stops if wants_gradient and identity_stops else design.brand_gradient_stops(roles)
    identity_field = bool(identity_stops) and gradient_stops is identity_stops
    if has_photo_hero and hero_grid:
        def _sampler_for(tpl: design.LayoutTemplate) -> design.Sampler:
            return design.raster_sampler(hero_grid, region=tpl.image_region, align=tpl.image_align)
    elif has_photo_hero:
        _sampler_for = None  # type: ignore[assignment]
    elif force_solid_bg:
        def _sampler_for(tpl: design.LayoutTemplate) -> design.Sampler:
            return design.solid_sampler(roles.brand)
    else:
        def _sampler_for(tpl: design.LayoutTemplate) -> design.Sampler:
            return design.diagonal_gradient_sampler(gradient_stops)

    def _surface_color(tpl: design.LayoutTemplate) -> str | None:
        if tpl.surface == "panel":
            if not roles.monochrome and design.contrast_ratio(design.hex_to_rgb(roles.brand), (255, 255, 255)) >= design.TEXT_CONTRAST_MIN:
                return roles.brand
            return roles.dark
        if tpl.surface == "card":
            return "#ffffff"
        return None

    def _zone_samples(tpl: design.LayoutTemplate, box: tuple[float, float, float, float]) -> list[design.RGB]:
        if _sampler_for is None:
            return design.assumed_photo_samples()
        return design.sample_box(_sampler_for(tpl), box)

    tpl = design.get_template(template_name)
    plan = _plan(tpl.name)
    energy = brand_layout_energy(kit, brand_profile)
    ground = _ground_color(tpl.name, energy, kit, roles)
    if ground:
        identity_field = False

        def _sampler_for(tpl: design.LayoutTemplate) -> design.Sampler:
            return design.solid_sampler(ground)

    surface = _surface_color(tpl)
    scrim_alpha: float | None = 0.0
    scrim_color = roles.dark
    if surface:
        surface_rgb = design.hex_to_rgb(surface)
        ink = roles.dark if design.contrast_ratio(design.hex_to_rgb(roles.dark), (255, 255, 255)) >= 12 else design.INK
        text_color = max((design.WHITE, ink), key=lambda c: design.contrast_ratio(design.hex_to_rgb(c), surface_rgb))
        text_samples = [surface_rgb]
    else:
        zone = plan.text_zone or (design.MARGIN_X, design.MARGIN_Y, 600, 300)
        raw_samples = _zone_samples(tpl, zone)
        text_color, scrim_alpha, scrim_color = _pick_text_and_scrim(raw_samples, roles)
        if scrim_alpha is None or (tpl.scrim == "none" and scrim_alpha > 0):
            tpl = design.get_template("text-panel")
            plan = _plan(tpl.name)
            surface = _surface_color(tpl)
            surface_rgb = design.hex_to_rgb(surface or "#ffffff")
            text_color = design.INK if roles.monochrome else (
                roles.dark if design.contrast_ratio(design.hex_to_rgb(roles.dark), surface_rgb) >= 7 else design.INK
            )
            text_samples = [surface_rgb]
            scrim_alpha = 0.0
        else:
            if scrim_alpha > 0:
                scrim_alpha = round(min(design.SCRIM_MAX_ALPHA, scrim_alpha + 0.05), 3)
            scrim_rgb = design.hex_to_rgb(scrim_color)
            text_samples = [design.blend(s, scrim_rgb, scrim_alpha) for s in raw_samples]

    steps: list[dict[str, Any]] = []
    background_placements: list[dict[str, Any]] = []

    brand_gradient_rel: str | None = None
    if ground:
        steps.append(
            {"command": "layer.newFillLayer.solidColor", "params": {"color": ground, "name": "Field"}}
        )
        picture_accent = roles.accent or roles.brand
        if design.relative_luminance(design.hex_to_rgb(picture_accent)) > 0.85:
            picture_accent = roles.brand
        if tpl.name == "photo-block" and not has_photo_hero:
            steps.extend(_photo_standin_steps(tpl.image_region, picture_accent))
        elif tpl.name == "product-card" and not has_photo_hero:
            steps.extend(_product_standin_steps(tpl.image_region, picture_accent))
        elif tpl.name == "circle-stage" and not has_photo_hero:
            rx, ry, rw, rh = tpl.image_region
            steps.append(_shape_step("ellipse", "Illustration plate", [rx, ry, rw, rh], picture_accent))
        elif tpl.name == "photo-card" and not has_photo_hero:
            steps.extend(_photo_card_steps(tpl.image_region, picture_accent))
        elif tpl.name == "character-scene" and not has_photo_hero:
            wordmark = bool(logo_width and logo_height and logo_width / max(1, logo_height) >= 2.2)
            steps.extend(_figure_standin_steps() if wordmark else _scene_standin_steps(picture_accent))
        elif tpl.name == "product-ui" and not has_photo_hero:
            steps.extend(_lesson_standin_steps(picture_accent))
        elif tpl.name == "communique":
            steps.append(
                _type_step(
                    "Wordmark",
                    site_name or " ",
                    [200, 48, 800, 64],
                    font=headline_font,
                    size=42,
                    color=roles.brand if design.relative_luminance(design.hex_to_rgb(roles.brand)) < 0.85 else roles.dark,
                    weight=800,
                    align="center",
                )
            )
    elif not has_photo_hero:
        if force_solid_bg:
            steps.append(
                {"command": "layer.newFillLayer.solidColor", "params": {"color": roles.brand, "name": "Brand solid"}}
            )
        elif assets_dir:
            brand_gradient_rel = ensure_brand_gradient_svg_stops(assets_dir, gradient_stops)
            background_placements.append(_brand_gradient_background_placement(brand_gradient_rel))
        else:
            steps.extend(_native_brand_gradient_steps(gradient_stops))
        if not force_solid_bg and not identity_field:
            steps.extend(_brand_glow_steps(design.glow_color(kit, roles)))

    ideogram_layers = None
    if brief.get("heroStrategy") == "ideogram_generate":
        ideogram_layers = brief.get("ideogramLayers") or "background-only"
    # A fitted picture must be placed after the Field step. Background placements are
    # painted first, and the solid field would cover the bitmap.
    picture_on_top: dict[str, Any] | None = None
    if hero_relative_path:
        placement = _hero_background_placement(
            hero_relative_path,
            img_width=hero_width,
            img_height=hero_height,
            layer_name="Background" if ideogram_layers else "Hero image",
        )
        rx, ry, rw, rh = tpl.image_region
        fitted = (rx, ry, rw, rh) != (0, 0, LINKEDIN_WIDTH, LINKEDIN_HEIGHT)
        if fitted:
            # fit:true letterboxes into the canvas. Scale is % of native pixels,
            # so a contain scale (or 100) leaves the Duolingo picture as a sticker.
            known_w = hero_width or 1024
            known_h = hero_height or 1024
            placement["cover"] = False
            placement["fit"] = False
            placement["name"] = "Picture"
            placement["center"] = [round(rx + rw / 2, 1), round(ry + rh / 2, 1)]
            placement["scale"] = round(region_cover_scale_percent(known_w, known_h, rw, rh), 2)
            picture_on_top = placement
        else:
            background_placements.append(placement)
    if accent_relative_path:
        accent = _accent_background_placement(
            accent_relative_path, img_width=accent_width, img_height=accent_height
        )
        accent["center"] = list(tpl.accent_center or (LINKEDIN_WIDTH * 0.84, LINKEDIN_HEIGHT * 0.5))
        background_placements.append(accent)

    scrim_meta: dict[str, Any] = {"kind": "none", "alpha": 0.0, "color": None}
    if not surface and scrim_alpha and plan.text_zone:
        kind = tpl.scrim if tpl.scrim != "none" else "diagonal"
        geometry = _scrim_geometry(kind, plan.text_zone, scrim_alpha)
        if geometry:
            steps.extend(_gradient_steps("Text scrim", scrim_color, geometry))
            scrim_meta = {"kind": kind, "alpha": scrim_alpha, "color": scrim_color, "hold": geometry["hold"]}

    if plan.panel and surface:
        block = None
        diagonal = composition.get("colourBlock") == "diagonal-crop" or (
            tpl.name == "device-stage" and (comm_kit.get("layoutMotif") or {}).get("blocking") == "diagonal-crop"
        )
        skip_panel = tpl.name == "device-stage" and composition.get("colourBlock") == "none"
        if diagonal and not skip_panel:
            block = kit_design.colour_block_step(
                {"layoutMotif": {"blocking": "diagonal-crop"}},
                surface=surface,
            )
        if block:
            steps.append(block)
        elif not skip_panel:
            steps.append(
                {
                    "command": "shape.create",
                    "params": {"kind": "rect", "rect": [round(v, 1) for v in plan.panel], "fill": surface, "name": "Brand panel"},
                }
            )
    if plan.card and surface:
        r, g, b = design.hex_to_rgb(surface)
        steps.append(
            {
                "command": "shape.create",
                "params": {
                    "kind": "roundedRect",
                    "rect": [round(v, 1) for v in plan.card],
                    "radii": design.CARD_RADIUS,
                    "fill": [r, g, b, 0.96],
                    "name": "Text card",
                },
            }
        )

    contrast: dict[str, float] = {}
    text_rgb = design.hex_to_rgb(text_color)
    els = plan.elements
    if "eyebrow" in els:
        eyebrow_color = text_color
        if roles.accent and design.min_contrast(design.hex_to_rgb(roles.accent), text_samples) >= design.TEXT_CONTRAST_MIN:
            eyebrow_color = roles.accent
        contrast["eyebrow"] = design.min_contrast(design.hex_to_rgb(eyebrow_color), text_samples)
        e = els["eyebrow"]
        steps.append(
            _type_step(
                "Eyebrow", e["text"], e["box"], font=body_font, size=e["size"], color=eyebrow_color,
                weight=design.EYEBROW_WEIGHT, align=plan.align, tracking=design.EYEBROW_TRACKING,
            )
        )
    h = els["headline"]
    contrast["headline"] = design.min_contrast(text_rgb, text_samples)
    steps.append(
        _type_step(
            "Headline", h["text"], h["box"], font=headline_font, size=h["size"], color=text_color,
            weight=h["weight"], align=plan.align, leading=h["leading"], tracking=design.HEADLINE_TRACKING,
        )
    )
    if "subline" in els:
        sub = els["subline"]
        contrast["subline"] = contrast["headline"]
        steps.append(
            _type_step(
                "Subline", sub["text"], sub["box"], font=body_font, size=sub["size"], color=text_color,
                weight=design.SUBLINE_WEIGHT, align=plan.align, leading=sub["leading"],
            )
        )
    cta_meta: dict[str, Any] | None = None
    if "cta" in els:
        chip = els["cta"]
        colors = _cta_colors(roles, cta_style, text_color, text_samples)
        cx, cy, cw, ch = chip["box"]
        shape: dict[str, Any] = {
            "kind": "roundedRect",
            "rect": [cx, cy, cw, ch],
            "radii": ch / 2,
            "fill": colors["fill"],
            "name": "CTA chip",
        }
        if colors.get("stroke"):
            shape["stroke"] = {"width": 2, "color": colors["stroke"], "align": "inside"}
        steps.append({"command": "shape.create", "params": shape})
        label_h = design.CTA_LABEL_SIZE * 1.3
        # PhotoCraft puts cap tops ~1px below the type box top; centre the cap height optically.
        cap_h = design.CTA_LABEL_SIZE * 0.73
        steps.append(
            _type_step(
                "CTA label", chip["label"], (cx, cy + (ch - cap_h) / 2 + 1, cw, label_h + 4),
                font=body_font, size=design.CTA_LABEL_SIZE, color=colors["label"],
                weight=design.CTA_LABEL_WEIGHT, align="center", tracking=10,
            )
        )
        if colors.get("labelContrast") is not None:
            contrast["ctaLabel"] = colors["labelContrast"]
        contrast["ctaChip"] = colors["chipContrast"]
        cta_meta = {"label": chip["label"], "style": cta_style, **{k: v for k, v in colors.items() if k in ("fill", "label", "stroke")}}

    foreground_placements: list[dict[str, Any]] = []
    if picture_on_top:
        foreground_placements.append(picture_on_top)
    logo_variant = None
    logo_on_dark = False
    mark_share = 0.0
    if has_logo and "logo" in els:
        lx, ly, lw, lh = els["logo"]["box"]
        if plan.panel and lx + lw <= plan.panel[0] + plan.panel[2]:
            logo_samples = [design.hex_to_rgb(surface or roles.dark)]
        else:
            logo_samples = _zone_samples(tpl, (lx - 8, ly - 8, lw + 16, lh + 16))
        original = normalize_logo_fill(logo_fill, kit)
        variant_colors = {"original": original, "light": design.WHITE, "dark": design.INK}
        preference = brief.get("logoTreatment")
        if brief_logo_recolor is True and not preference:
            preference = "wordmark-white"
        logo_variant, logo_ratio = _pick_logo_variant(logo_paths, variant_colors, logo_samples, preference)
        logo_on_dark = logo_variant == "light" or (
            logo_ratio < design.GRAPHIC_CONTRAST_MIN
            and design.min_contrast((255, 255, 255), logo_samples)
            >= design.min_contrast(design.hex_to_rgb(original), logo_samples)
        )
        if logo_ratio < design.GRAPHIC_CONTRAST_MIN:
            light_rgb = design.hex_to_rgb(design.WHITE if "light" in logo_paths else variant_colors[logo_variant])
            alpha = design.required_scrim_alpha(
                design.worst_samples(logo_samples, for_light_text=True),
                design.hex_to_rgb(roles.dark), light_rgb, target=design.GRAPHIC_CONTRAST_MIN,
            ) or design.SCRIM_MAX_ALPHA
            geometry = _scrim_geometry("radial", (lx, ly, lw, lh), alpha)
            if geometry:
                steps.extend(_gradient_steps("Logo scrim", roles.dark, geometry))
            if "light" in logo_paths:
                logo_variant = "light"
            logo_on_dark = True
            logo_ratio = design.min_contrast(
                light_rgb, [design.blend(s, design.hex_to_rgb(roles.dark), alpha) for s in logo_samples]
            )
        contrast["logo"] = logo_ratio
        foreground_placements.append(
            {
                "path": logo_paths[logo_variant].replace("\\", "/"),
                "center": [round(lx + lw / 2, 1), round(ly + lh / 2, 1)],
                "scale": round(logo_scale_percent(logo_width or 0, target_width=int(round(lw))), 2),
                "smartObject": True,
                "name": "Logo",
            }
        )
        if tpl.name == "mark-stage":
            target_w = 260.0
            foreground_placements[-1]["center"] = [LINKEDIN_WIDTH / 2, 132]
            foreground_placements[-1]["scale"] = round(
                logo_scale_percent(logo_width or 0, target_width=int(target_w)), 2
            )
            mark_share = 0.35
        elif tpl.name == "communique":
            foreground_placements[-1]["center"] = [LINKEDIN_WIDTH / 2, 500]
            foreground_placements[-1]["scale"] = round(
                logo_scale_percent(logo_width or 0, target_width=160), 2
            )
        elif tpl.name == "character-scene":
            wordmark = bool(logo_width and logo_height and logo_width / max(1, logo_height) >= 2.2)
            if wordmark:
                foreground_placements[-1]["center"] = [390, 210]
                foreground_placements[-1]["scale"] = round(
                    logo_scale_percent(logo_width or 0, target_width=170), 2
                )
            else:
                rx, ry, rw, rh = tpl.image_region
                foreground_placements[-1]["center"] = [rx + rw / 2, ry + rh / 2]
                foreground_placements[-1]["scale"] = round(
                    logo_scale_percent(logo_width or 0, target_width=int(rw * 0.7)), 2
                )
        elif tpl.name == "product-ui":
            rx, ry, rw, rh = tpl.image_region
            foreground_placements[-1]["center"] = [rx + rw / 2, ry + rh / 2]
            foreground_placements[-1]["scale"] = round(
                logo_scale_percent(logo_width or 0, target_width=180), 2
            )
        wants_mark = any(item.get("source") == "logo-geometry" for item in composition.get("visuals") or [])
        symbol = bool(logo_width and logo_height and logo_width / logo_height < 2.2)
        if wants_mark and symbol and tpl.name not in ("mark-stage", "circle-stage"):
            target_w = 460.0
            mark_h = target_w * (logo_height / logo_width)
            mark_share = (target_w * mark_h) / (design.CANVAS_W * design.CANVAS_H)
            foreground_placements.append(
                {
                    "path": logo_paths[logo_variant or "original"].replace("\\", "/"),
                    "center": [980, 300],
                    "scale": round(logo_scale_percent(logo_width or 0, target_width=int(target_w)), 2),
                    "smartObject": True,
                    "name": "Mark geometry",
                }
            )

    if has_photo_hero or identity_field or tpl.name in (
        "photo-block",
        "circle-stage",
        "mark-stage",
        "product-card",
        "device-stage",
        "communique",
        "type-only",
        "photo-card",
        "character-scene",
        "product-ui",
    ):
        visual_share = 1.0
    else:
        visual_share = mark_share

    audit = design.audit_plan(
        plan,
        contrast=contrast,
        scrim_alpha=scrim_meta["alpha"] if scrim_meta["kind"] != "none" else None,
        logo_count=sum(1 for item in foreground_placements if item.get("name") == "Logo"),
        devices=comm_kit.get("devices") or None,
        visual_share=visual_share,
        cta_required=bool(composition.get("showCta")),
    )

    document = {
        "width": LINKEDIN_WIDTH,
        "height": LINKEDIN_HEIGHT,
        "mode": "rgb",
        "depth": 8,
        "background": roles.dark if not has_photo_hero else roles.brand,
        "resolution": 72,
        "name": f"CommMaker LinkedIn — {site_name}",
    }
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
            "eyebrow": eyebrow or None,
            "cta": cta_meta,
            "siteName": site_name,
            "primaryColor": roles.brand,
            "accentColor": roles.accent,
            "paletteRoles": {
                "brand": roles.brand,
                "dark": roles.dark,
                "light": roles.light,
                "accent": roles.accent,
                "monochrome": roles.monochrome,
            },
            "hasHero": has_photo_hero,
            "hasAccentLayer": bool(accent_relative_path),
            "ideogramLayers": ideogram_layers,
            "heroBusy": hero_busy,
            "heroBrandMark": hero_brand_mark,
            "layoutTemplate": tpl.name,
            "composition": composition,
            "identityField": identity_field,
            "visualShare": round(visual_share, 3),
            "communicationKit": {
                "sector": comm_kit.get("sector"),
                "thinSite": bool(comm_kit.get("thinSite")),
                "devices": [d.get("kind") for d in (comm_kit.get("devices") or []) if isinstance(d, dict)],
            } if comm_kit else None,
            "layout": plan.to_meta(),
            "textColor": text_color,
            "scrim": scrim_meta,
            "contrast": {k: round(v, 2) for k, v in contrast.items()},
            "backgroundSampled": bool(hero_grid) or not has_photo_hero,
            "designAudit": audit,
            "logoVariant": logo_variant,
            "logoOnDark": logo_on_dark,
            "logoKnockback": False,
            "hasLogo": has_logo,
            "logoLayout": {
                "targetWidthPx": int(round(logo_size[0])) if logo_size else None,
                "targetHeightPx": int(round(logo_size[1])) if logo_size else None,
                "logoScalePercent": foreground_placements[0]["scale"] if foreground_placements else None,
            },
            "typography": {
                "headlineSize": h["size"],
                "headlineWeight": h["weight"],
                "headlineScale": h["scale"],
                "sublineSize": (els.get("subline") or {}).get("size"),
            },
            "fonts": {
                "headline": headline_font,
                "body": body_font,
            },
            "creativeBrief": creative_brief,
        },
    }


def normalize_logo_fill(logo_fill: str | None, kit: dict[str, Any] | None) -> str:
    hex6 = _normalize_hex(logo_fill or "", "")
    if hex6:
        return hex6
    svg = str((kit or {}).get("logoSvg") or "")
    for match in _SVG_FILL_ATTR_RE.finditer(svg):
        hex6 = _normalize_hex(match.group(2), "")
        if hex6:
            return hex6
    for match in _SVG_STYLE_FILL_RE.finditer(svg):
        hex6 = _normalize_hex(match.group(1), "")
        if hex6:
            return hex6
    return "#000000"
