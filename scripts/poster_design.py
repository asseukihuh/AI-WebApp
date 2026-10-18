"""CommMaker poster design system for LinkedIn 1200×627.

Grid, type scale, palette roles, WCAG contrast math, layout templates, layout planning and the
rule audit used by ``poster_compiler``. Human-readable spec: ``docs/poster-design-system.md``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal, Sequence

RGB = tuple[int, int, int]
Box = tuple[float, float, float, float]

CANVAS_W = 1200
CANVAS_H = 627
MARGIN_X = 60
MARGIN_Y = 56
COLUMNS = 12
COLUMN_W = 68
GUTTER = 24
BASELINE = 8

HEADLINE_SCALE: dict[str, int] = {"xl": 76, "lg": 64, "md": 54}
HEADLINE_WEIGHT: dict[str, int] = {"bold": 700, "extrabold": 800}
HEADLINE_MIN_SIZE = 44
HEADLINE_LEADING = 1.06
HEADLINE_TRACKING = -15
SUBLINE_SIZE = 26
SUBLINE_MIN_SIZE = 24
SUBLINE_LEADING = 1.35
SUBLINE_WEIGHT = 400
EYEBROW_SIZE = 15
EYEBROW_WEIGHT = 700
EYEBROW_TRACKING = 120
CTA_LABEL_SIZE = 20
CTA_LABEL_WEIGHT = 600
CTA_HEIGHT = 48
CTA_PAD_X = 24
CTA_GAP = 32
TEXT_GAP = 16
CARD_PAD = 40
CARD_RADIUS = 20

MAX_WORDS: dict[str, int] = {"eyebrow": 3, "headline": 10, "subline": 18, "cta": 3}
MAX_CHARS: dict[str, int] = {"eyebrow": 28, "headline": 60, "subline": 110, "cta": 22}
MAX_TOTAL_WORDS = 30

TEXT_CONTRAST_MIN = 4.5
GRAPHIC_CONTRAST_MIN = 3.0
HIERARCHY_RATIO_MIN = 2.1
# Text and the logo may use most of a poster when a real image or identity gradient fills the field.
# A flat single-colour ground is not "imagery"; that case fails visual-mass instead.
MIN_WHITESPACE_RATIO = 0.18
MIN_VISUAL_SHARE = 0.25
MIN_DEVICE_CONTRAST = 2.2
SCRIM_MAX_ALPHA = 0.85
SCRIM_FADE_PX = 200

# Average advance per character, in em, for planned line breaks. Kept ~8% above measured Inter
# (bold ≈ 0.48, regular ≈ 0.49) so planned lines never re-wrap inside the type box.
HEADLINE_EM = 0.53
BODY_EM = 0.53
CAPS_EM = 0.74

INK = "#0b1220"
WHITE = "#ffffff"

LayoutTemplateName = Literal[
    "full-bleed-scrim",
    "split-text-left",
    "text-panel",
    "centered-statement",
    "device-stage",
    "photo-block",
    "circle-stage",
    "mark-stage",
    "product-card",
    "communique",
    "type-only",
    "photo-card",
    "character-scene",
    "product-ui",
]
LAYOUT_TEMPLATES: tuple[str, ...] = (
    "full-bleed-scrim",
    "split-text-left",
    "text-panel",
    "centered-statement",
    "device-stage",
    "photo-block",
    "circle-stage",
    "mark-stage",
    "product-card",
    "communique",
    "type-only",
    "photo-card",
    "character-scene",
    "product-ui",
)
# Photographs, illustrations, products and gradient textures. Not type-only or a vector mark.
RASTER_TEMPLATES = frozenset(
    {
        "full-bleed-scrim",
        "split-text-left",
        "text-panel",
        "photo-block",
        "photo-card",
        "circle-stage",
        "character-scene",
        "product-card",
        "product-ui",
    }
)
HEADLINE_SCALES: tuple[str, ...] = ("xl", "lg", "md")
HEADLINE_WEIGHTS: tuple[str, ...] = ("bold", "extrabold")
CTA_STYLES: tuple[str, ...] = ("pill", "outline", "none")


def col_x(index: int) -> float:
    return MARGIN_X + index * (COLUMN_W + GUTTER)


def span_w(columns: int) -> float:
    return columns * COLUMN_W + (columns - 1) * GUTTER


# --------------------------------------------------------------------------- colour


def normalize_hex(value: str | None, default: str = "") -> str:
    v = (value or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", v):
        return v.lower()
    if re.fullmatch(r"#[0-9a-fA-F]{3}", v):
        return "#" + "".join(c * 2 for c in v[1:]).lower()
    return default


def hex_to_rgb(value: str) -> RGB:
    hex6 = normalize_hex(value, "#000000").lstrip("#")
    return (int(hex6[0:2], 16), int(hex6[2:4], 16), int(hex6[4:6], 16))


def rgb_to_hex(rgb: Sequence[float]) -> str:
    r, g, b = (max(0, min(255, int(round(c)))) for c in rgb[:3])
    return f"#{r:02x}{g:02x}{b:02x}"


def _channel_linear(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: Sequence[float]) -> float:
    """WCAG 2.x relative luminance (0 black … 1 white)."""
    r, g, b = (_channel_linear(c) for c in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: Sequence[float], b: Sequence[float]) -> float:
    la, lb = relative_luminance(a), relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def blend(base: Sequence[float], over: Sequence[float], alpha: float) -> RGB:
    """Normal blend in sRGB space (what PhotoCraft layers do)."""
    a = max(0.0, min(1.0, alpha))
    return tuple(int(round(b * (1 - a) + o * a)) for b, o in zip(base[:3], over[:3]))  # type: ignore[return-value]


def mix_hex(a: str, b: str, t: float) -> str:
    return rgb_to_hex(blend(hex_to_rgb(a), hex_to_rgb(b), t))


def chroma(rgb: Sequence[float]) -> float:
    return (max(rgb[:3]) - min(rgb[:3])) / 255.0


def min_contrast(text: Sequence[float], samples: Iterable[Sequence[float]]) -> float:
    values = [contrast_ratio(text, s) for s in samples]
    return min(values) if values else 21.0


def worst_samples(
    samples: Sequence[RGB],
    *,
    for_light_text: bool,
    fraction: float = 0.1,
) -> list[RGB]:
    """Worst-case pixels for a text colour: brightest decile under light text, darkest under dark."""
    if not samples:
        return []
    ordered = sorted(samples, key=relative_luminance, reverse=for_light_text)
    count = max(1, int(round(len(ordered) * fraction)))
    return list(ordered[:count])


def required_scrim_alpha(
    samples: Sequence[RGB],
    scrim: RGB,
    text: RGB,
    target: float = TEXT_CONTRAST_MIN,
    max_alpha: float = SCRIM_MAX_ALPHA,
) -> float | None:
    """Smallest scrim alpha so ``text`` reaches ``target`` over every sample; ``None`` if > max."""
    if not samples:
        return 0.0

    def ok(alpha: float) -> bool:
        return all(contrast_ratio(text, blend(s, scrim, alpha)) >= target for s in samples)

    if ok(0.0):
        return 0.0
    if not ok(max_alpha):
        return None
    lo, hi = 0.0, max_alpha
    for _ in range(18):
        mid = (lo + hi) / 2
        if ok(mid):
            hi = mid
        else:
            lo = mid
    return round(min(max_alpha, hi + 0.02), 3)


# --------------------------------------------------------------------------- palette


@dataclass(frozen=True)
class BrandRoles:
    brand: str
    dark: str
    light: str
    accent: str | None
    monochrome: bool
    palette: tuple[str, ...]


def kit_palette(kit: dict[str, Any] | None) -> list[str]:
    kit = kit or {}
    seen: set[str] = set()
    out: list[str] = []
    for key in ("colors", "accentColors"):
        for raw in kit.get(key) or []:
            if not isinstance(raw, str):
                continue
            hex6 = normalize_hex(raw)
            if hex6 and hex6 not in seen:
                seen.add(hex6)
                out.append(hex6)
    return out


_PROFILE_ROLE_KEYS: dict[str, tuple[str, ...]] = {
    "brand": ("primary", "brand", "main"),
    "dark": ("dark", "ink", "text"),
    "accent": ("accent", "highlight", "cta"),
    "light": ("background", "light", "surface", "neutral"),
}


def _profile_color(value: Any) -> str:
    if isinstance(value, str):
        return normalize_hex(value)
    if isinstance(value, dict):
        return normalize_hex(str(value.get("hex") or value.get("color") or ""))
    return ""


def profile_palette_roles(brand_profile: dict[str, Any] | None) -> dict[str, str]:
    """Optional ``brandProfile.palette``: role dict, or list of hex / ``{hex, role}`` entries."""
    raw = (brand_profile or {}).get("palette")
    roles: dict[str, str] = {}
    if isinstance(raw, dict):
        lowered = {str(k).casefold(): v for k, v in raw.items()}
        for role, keys in _PROFILE_ROLE_KEYS.items():
            for key in keys:
                hex6 = _profile_color(lowered.get(key))
                if hex6:
                    roles[role] = hex6
                    break
    elif isinstance(raw, list):
        for entry in raw:
            hex6 = _profile_color(entry)
            role_name = str(entry.get("role") or "").casefold() if isinstance(entry, dict) else ""
            for role, keys in _PROFILE_ROLE_KEYS.items():
                if hex6 and role not in roles and role_name in keys:
                    roles[role] = hex6
    return roles


_PROFILE_ROLE_RANK = {"primary": 0, "brand": 0, "accent": 1, "secondary": 2, "text": 3, "surface": 4, "background": 5}


def profile_palette_list(brand_profile: dict[str, Any] | None) -> list[str]:
    """Profile colours, most brand-defining first (primary, accent, secondary … background)."""
    raw = (brand_profile or {}).get("palette")
    if isinstance(raw, dict):
        entries = [{"role": k, "hex": v} for k, v in raw.items()]
    elif isinstance(raw, list):
        entries = [e if isinstance(e, dict) else {"hex": e} for e in raw]
    else:
        return []
    ranked = sorted(
        enumerate(entries),
        key=lambda item: (_PROFILE_ROLE_RANK.get(str(item[1].get("role") or "").casefold(), 3), item[0]),
    )
    out: list[str] = []
    for _, entry in ranked:
        hex6 = _profile_color(entry)
        if hex6 and hex6 not in out:
            out.append(hex6)
    return out


def brand_roles(
    kit: dict[str, Any] | None,
    brand_profile: dict[str, Any] | None = None,
) -> BrandRoles:
    """Palette roles from the kit, refined by optional ``brandProfile.palette`` (never required)."""
    profile_colors = profile_palette_list(brand_profile)
    roles = _brand_roles_from_kit(kit, profile_colors)
    override = profile_palette_roles(brand_profile)
    if not override:
        return roles
    brand = override.get("brand", roles.brand)
    monochrome = chroma(hex_to_rgb(brand)) < 0.08
    dark = override.get("dark", "")
    if not dark or relative_luminance(hex_to_rgb(dark)) > 0.1:
        dark = brand if monochrome else mix_hex(brand, "#0b1020", 0.8)
    accent = override.get("accent") or (None if monochrome else brand)
    light = override.get("light", "")
    if not light or relative_luminance(hex_to_rgb(light)) < 0.6:
        light = roles.light
    return BrandRoles(
        brand=brand,
        dark=dark,
        light=light,
        accent=accent,
        monochrome=monochrome,
        palette=roles.palette,
    )


def _brand_roles_from_kit(kit: dict[str, Any] | None, profile_colors: list[str]) -> BrandRoles:
    palette = profile_colors + [c for c in kit_palette(kit) if c not in profile_colors]
    if not palette:
        palette = ["#1a365d", "#2c5282"]
    head = palette[:8]
    chromatic = [c for c in head if chroma(hex_to_rgb(c)) >= 0.18]
    first = hex_to_rgb(head[0])
    monochrome = not chromatic or (
        chroma(first) < 0.08 and relative_luminance(first) < 0.05
    )
    if monochrome:
        darks = [c for c in head if relative_luminance(hex_to_rgb(c)) < 0.05]
        brand = darks[0] if darks else "#111111"
        dark = brand
        accent = None
    elif profile_colors and any(c in chromatic for c in profile_colors):
        # A brand profile lists colours by importance; scraped CSS colours are unordered ramps.
        brand = next(c for c in profile_colors if c in chromatic)
    else:
        brand = max(chromatic, key=lambda c: (chroma(hex_to_rgb(c)), -relative_luminance(hex_to_rgb(c))))
    if not monochrome:
        darks = [
            c
            for c in head
            if relative_luminance(hex_to_rgb(c)) < 0.04 and chroma(hex_to_rgb(c)) >= 0.04
        ]
        dark = darks[0] if darks else mix_hex(brand, "#0b1020", 0.8)
        accent = brand
    lights = sorted(head, key=lambda c: relative_luminance(hex_to_rgb(c)), reverse=True)
    light = lights[0] if lights and relative_luminance(hex_to_rgb(lights[0])) > 0.8 else "#f8fafc"
    return BrandRoles(
        brand=brand,
        dark=dark,
        light=light,
        accent=accent,
        monochrome=monochrome,
        palette=tuple(palette[:6]),
    )


def _hexes_differ(a: str, b: str) -> bool:
    ra, ga, ba = hex_to_rgb(a)
    rb, gb, bb = hex_to_rgb(b)
    return max(abs(ra - rb), abs(ga - gb), abs(ba - bb)) >= 48


def identity_gradient_stops(
    brand_profile: dict[str, Any] | None,
    roles: BrandRoles,
) -> list[tuple[float, str]] | None:
    """Diagonal field from the captured palette when it actually has more than one hue.

    A single purple ramped toward white is not the brand's imagery. Stripe's profile
    contributes blurple and the orange ribbon; those two stops are the field.
    """
    ordered: list[str] = []

    def _take(hex6: str) -> None:
        if len(ordered) >= 2 or not hex6:
            return
        rgb = hex_to_rgb(hex6)
        if chroma(rgb) < 0.18 or relative_luminance(rgb) > 0.92:
            return
        if any(not _hexes_differ(hex6, seen) for seen in ordered):
            return
        ordered.append(hex6)

    _take(roles.brand)
    _take(roles.accent)
    for hex6 in profile_palette_list(brand_profile):
        _take(hex6)
    if len(ordered) < 2:
        return None
    start, end = ordered[0], ordered[1]
    return [(0.0, start), (0.48, mix_hex(start, end, 0.45)), (1.0, end)]


def brand_gradient_stops(roles: BrandRoles) -> list[tuple[float, str]]:
    if roles.monochrome:
        return [(0.0, roles.dark), (0.6, mix_hex(roles.dark, "#ffffff", 0.06)), (1.0, mix_hex(roles.dark, "#ffffff", 0.16))]
    return [(0.0, roles.dark), (0.62, roles.brand), (1.0, mix_hex(roles.brand, "#ffffff", 0.35))]


def glow_color(kit: dict[str, Any] | None, roles: BrandRoles) -> str:
    if not roles.monochrome:
        return mix_hex(roles.brand, "#ffffff", 0.25)
    for c in kit_palette(kit):
        if chroma(hex_to_rgb(c)) >= 0.4:
            return c
    return "#ffffff"


# --------------------------------------------------------------------------- templates


@dataclass(frozen=True)
class LayoutTemplate:
    name: str
    text_x: float
    text_w: float
    anchor: Literal["bottom", "center"]
    align: Literal["left", "center"]
    image_region: Box
    image_align: Literal["center", "right"]
    scrim: Literal["diagonal", "horizontal", "radial", "none"]
    surface: Literal["none", "panel", "card"]
    logo_align: Literal["left", "center"]
    accent_center: tuple[float, float] | None
    ideogram_subject_bboxes: tuple[tuple[int, int, int, int], ...]
    ideogram_background: str
    ideogram_layout_note: str
    panel_box: Box | None = None
    max_headline_lines: int = 3


TEMPLATES: dict[str, LayoutTemplate] = {
    "full-bleed-scrim": LayoutTemplate(
        name="full-bleed-scrim",
        text_x=col_x(0),
        text_w=span_w(7),
        anchor="bottom",
        align="left",
        image_region=(0, 0, CANVAS_W, CANVAS_H),
        image_align="center",
        scrim="diagonal",
        surface="none",
        logo_align="left",
        accent_center=(CANVAS_W * 0.76, CANVAS_H * 0.42),
        ideogram_subject_bboxes=((60, 560, 640, 960),),
        ideogram_background=(
            "a soft, low-detail field that grows calmer and slightly darker toward the lower-left, "
            "leaving the lower-left sixty percent of the frame as smooth negative space"
        ),
        ideogram_layout_note="main visual interest in the upper-right; lower-left kept empty",
    ),
    "split-text-left": LayoutTemplate(
        name="split-text-left",
        text_x=col_x(0),
        text_w=span_w(5),
        anchor="center",
        align="left",
        image_region=(CANVAS_W / 2, 0, CANVAS_W / 2, CANVAS_H),
        image_align="right",
        scrim="none",
        surface="panel",
        logo_align="left",
        accent_center=(CANVAS_W * 0.75, CANVAS_H / 2),
        ideogram_subject_bboxes=((120, 560, 880, 960),),
        ideogram_background=(
            "a plain, smooth, evenly lit left half and a richer right half that frames the subject"
        ),
        ideogram_layout_note="subject sits in the right half; left half plain and uncluttered",
        panel_box=(0, 0, CANVAS_W / 2, CANVAS_H),
    ),
    "text-panel": LayoutTemplate(
        name="text-panel",
        text_x=col_x(0) + CARD_PAD,
        text_w=span_w(7) - 2 * CARD_PAD,
        anchor="bottom",
        align="left",
        image_region=(0, 0, CANVAS_W, CANVAS_H),
        image_align="center",
        scrim="none",
        surface="card",
        logo_align="left",
        accent_center=(CANVAS_W * 0.8, CANVAS_H * 0.45),
        ideogram_subject_bboxes=((100, 640, 900, 960),),
        ideogram_background=(
            "a soft, out-of-focus, low-contrast surface across the left two-thirds of the frame"
        ),
        ideogram_layout_note="visual interest on the right third; left two-thirds soft and quiet",
    ),
    "centered-statement": LayoutTemplate(
        name="centered-statement",
        text_x=col_x(1),
        text_w=span_w(10),
        anchor="center",
        align="center",
        image_region=(0, 0, CANVAS_W, CANVAS_H),
        image_align="center",
        scrim="radial",
        surface="none",
        logo_align="center",
        accent_center=None,
        ideogram_subject_bboxes=((0, 0, 1000, 170), (0, 830, 1000, 1000)),
        ideogram_background=(
            "a calm, smooth, evenly lit centre with gentle depth, detail fading in only near the "
            "left and right edges"
        ),
        ideogram_layout_note="symmetrical; strong calm negative space in the centre",
        max_headline_lines=2,
    ),
    "device-stage": LayoutTemplate(
        name="device-stage",
        text_x=col_x(0),
        text_w=span_w(6),
        anchor="center",
        align="left",
        image_region=(640, 0, CANVAS_W - 640, CANVAS_H),
        image_align="right",
        scrim="none",
        surface="panel",
        logo_align="left",
        accent_center=(CANVAS_W * 0.78, CANVAS_H * 0.42),
        ideogram_subject_bboxes=((80, 560, 920, 980),),
        ideogram_background=(
            "a flat colour-block on the left and one bold abstract device on the right, "
            "with empty ground between them"
        ),
        ideogram_layout_note="asymmetric colour block on the left; one large graphic device on the right",
        panel_box=(0, 0, 640, CANVAS_H),
        max_headline_lines=3,
    ),
    "photo-block": LayoutTemplate(
        name="photo-block",
        text_x=col_x(0),
        text_w=span_w(4),
        anchor="center",
        align="left",
        image_region=(560, 0, CANVAS_W - 560, CANVAS_H),
        image_align="right",
        scrim="none",
        surface="panel",
        logo_align="left",
        accent_center=(CANVAS_W * 0.74, CANVAS_H * 0.48),
        ideogram_subject_bboxes=((80, 560, 980, 1000),),
        ideogram_background=(
            "a text-free photograph filling the right half, with a plain flat colour on the left "
            "for type"
        ),
        ideogram_layout_note="colour headline block on the left, photograph cropped on the right",
        panel_box=(0, 0, 560, CANVAS_H),
        max_headline_lines=4,
    ),
    "circle-stage": LayoutTemplate(
        name="circle-stage",
        text_x=col_x(0),
        text_w=span_w(5),
        anchor="center",
        align="left",
        image_region=(700, 104, 400, 400),
        image_align="center",
        scrim="none",
        surface="none",
        logo_align="left",
        accent_center=(900, 304),
        ideogram_subject_bboxes=((80, 700, 980, 980),),
        ideogram_background=(
            "a text-free flat illustration filling the right side and an empty paper field on the "
            "left for type, no letters and no frame"
        ),
        ideogram_layout_note="flat illustration on the right, type on the left, no letters and no frame",
        max_headline_lines=4,
    ),
    "mark-stage": LayoutTemplate(
        name="mark-stage",
        text_x=col_x(2),
        text_w=span_w(8),
        anchor="bottom",
        align="center",
        image_region=(420, 36, 360, 320),
        image_align="center",
        scrim="none",
        surface="none",
        logo_align="center",
        accent_center=None,
        ideogram_subject_bboxes=(),
        ideogram_background="unused: the symbol is placed as vectors, not painted",
        ideogram_layout_note="stark flat field, one large symbol centred, type along the bottom",
        max_headline_lines=2,
    ),
    "product-card": LayoutTemplate(
        name="product-card",
        text_x=col_x(1),
        text_w=span_w(10),
        anchor="bottom",
        align="center",
        image_region=(390, 44, 420, 300),
        image_align="center",
        scrim="none",
        surface="none",
        logo_align="center",
        accent_center=(600, 190),
        ideogram_subject_bboxes=((40, 400, 280, 820),),
        ideogram_background=(
            "a flat brand colour with one product pack centred in the upper half, no readable "
            "labels, no logos, caption space left along the bottom"
        ),
        ideogram_layout_note="product centred on a flat colour, short caption along the bottom",
        max_headline_lines=2,
    ),
    "communique": LayoutTemplate(
        name="communique",
        text_x=col_x(2),
        text_w=span_w(8),
        anchor="center",
        align="center",
        image_region=(430, 400, 340, 180),
        image_align="center",
        scrim="none",
        surface="none",
        logo_align="center",
        accent_center=None,
        ideogram_subject_bboxes=(),
        ideogram_background="unused: type and the real mascot, no painted scene",
        ideogram_layout_note="centred note: wordmark, centred type, mascot along the bottom",
        max_headline_lines=3,
    ),
    "type-only": LayoutTemplate(
        name="type-only",
        text_x=col_x(1),
        text_w=span_w(10),
        anchor="center",
        align="center",
        image_region=(0, 0, CANVAS_W, CANVAS_H),
        image_align="center",
        scrim="none",
        surface="none",
        logo_align="center",
        accent_center=None,
        ideogram_subject_bboxes=(),
        ideogram_background="unused: one statement on a flat brand colour",
        ideogram_layout_note="full-bleed colour, one centred statement, small mark",
        max_headline_lines=4,
    ),
    "photo-card": LayoutTemplate(
        name="photo-card",
        text_x=col_x(3),
        text_w=span_w(6),
        anchor="bottom",
        align="center",
        image_region=(320, 56, 560, 200),
        image_align="center",
        scrim="none",
        surface="none",
        logo_align="left",
        accent_center=(600, 200),
        ideogram_subject_bboxes=((80, 300, 360, 900),),
        ideogram_background=(
            "a text-free photograph cropped inside a card, no letters, no logos, "
            "caption space below the picture"
        ),
        ideogram_layout_note="one card: photograph on top, a short caption underneath",
        max_headline_lines=3,
    ),
    "character-scene": LayoutTemplate(
        name="character-scene",
        text_x=col_x(1),
        text_w=span_w(10),
        anchor="bottom",
        align="center",
        image_region=(390, 24, 420, 300),
        image_align="center",
        scrim="none",
        surface="none",
        logo_align="center",
        accent_center=(600, 240),
        ideogram_subject_bboxes=((40, 280, 500, 920),),
        ideogram_background=(
            "a text-free scene with one brand character or object in the centre, "
            "no letters, no logos, a quiet band along the bottom for a caption"
        ),
        ideogram_layout_note="character or object in a scene, short caption along the bottom",
        max_headline_lines=2,
    ),
    "product-ui": LayoutTemplate(
        name="product-ui",
        text_x=col_x(5),
        text_w=span_w(6),
        anchor="center",
        align="left",
        image_region=(120, 160, 240, 240),
        image_align="center",
        scrim="none",
        surface="none",
        logo_align="left",
        accent_center=(360, 290),
        ideogram_subject_bboxes=((140, 200, 460, 520),),
        ideogram_background=(
            "a text-free illustration of a lesson screen: a progress bar, a character, "
            "empty answer chips, no readable words"
        ),
        ideogram_layout_note="product UI illustration, the real mark as the character",
        max_headline_lines=2,
    ),
}


def template_needs_raster(name: str | None) -> bool:
    """Photographs, illustrations, products and gradient textures."""
    return (name or "") in RASTER_TEMPLATES


def template_skips_ideogram(name: str | None) -> bool:
    """Every poster gets an Ideogram field. The template name does not skip the call."""
    del name
    return False


def kit_hero_unsuitable(kit: dict[str, Any] | None) -> bool:
    """Whether the scraped kit hero can't be a poster background.

    Busy UI screenshots and sparse brand marks never work. ``og:image`` social cards
    (``heroImageKind: og-marketing``) almost always carry the logo and headline text, which would
    duplicate the poster's logo and copy; ``COMMMAKER_ALLOW_OG_HERO=1`` opts back in.
    """
    kit = kit or {}
    if kit.get("heroBusy") or kit.get("heroBrandMark"):
        return True
    if kit.get("heroImageKind") == "og-marketing":
        allow = (os.environ.get("COMMMAKER_ALLOW_OG_HERO") or "").strip().lower()
        return allow not in ("1", "true", "yes", "on")
    return False


def get_template(name: str | None) -> LayoutTemplate:
    return TEMPLATES.get(name or "", TEMPLATES["full-bleed-scrim"])


def default_template_for(
    *,
    layout_recipe: str | None,
    has_image: bool,
    emphasis: str | None,
    monochrome: bool,
) -> str:
    if not has_image or layout_recipe in ("gradient-brand", "minimal-wordmark"):
        return "centered-statement"
    if emphasis == "urgent":
        return "text-panel"
    if not monochrome:
        return "split-text-left"
    return "full-bleed-scrim"


_LAYOUT_TRAIT_HINTS: tuple[tuple[str, str], ...] = (
    ("split", "split-text-left"),
    ("asymmetr", "split-text-left"),
    ("card", "text-panel"),
    ("panel", "text-panel"),
    ("modular", "text-panel"),
    ("center", "centered-statement"),
    ("centre", "centered-statement"),
    ("symmetr", "centered-statement"),
    ("statement", "centered-statement"),
    ("left-aligned", "full-bleed-scrim"),
    ("left aligned", "full-bleed-scrim"),
    ("full-bleed", "full-bleed-scrim"),
    ("full bleed", "full-bleed-scrim"),
    ("immersive", "full-bleed-scrim"),
)


def template_hint_from_profile(brand_profile: dict[str, Any] | None) -> str | None:
    """Optional ``brandProfile.layoutTraits`` → preferred template.

    Accepts the brand-profile object (``composition`` free text is matched; ``density`` /
    ``whitespace`` / ``cornerRadius`` enums carry no template signal) or a list of trait strings.
    Within each text, the earliest matching cue wins.
    """
    traits = (brand_profile or {}).get("layoutTraits")
    if isinstance(traits, dict):
        texts = [traits.get("composition")]
    elif isinstance(traits, list):
        texts = list(traits)
    else:
        return None
    for text in texts:
        lowered = str(text or "").casefold()
        hits = [(lowered.find(needle), template) for needle, template in _LAYOUT_TRAIT_HINTS if needle in lowered]
        if hits:
            return min(hits)[1]
    return None


_GENERIC_TYPEFACES = frozenset(
    {
        "",
        "inherit",
        "initial",
        "sans-serif",
        "serif",
        "monospace",
        "system-ui",
        "ui-sans-serif",
        "ui-serif",
        "-apple-system",
        "dejavu sans",
        "dejavu sans mono",
        "liberation sans",
    }
)
DISPLAY_FALLBACK = "Noto Sans Display"


def _font_installed(name: str) -> bool:
    import subprocess

    try:
        proc = subprocess.run(
            ["fc-match", "-f", "%{family}", name],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    family = (proc.stdout or "").split(",")[0].strip().casefold()
    wanted = name.strip().casefold()
    return bool(family) and (wanted in family or family in wanted)


def usable_display_font(name: str | None) -> str | None:
    """A real face. Generic and missing families are not usable."""
    cleaned = (name or "").strip()
    if cleaned.casefold() in _GENERIC_TYPEFACES:
        return None
    if _font_installed(cleaned):
        return cleaned
    return None


def captured_display_family(
    brand_profile: dict[str, Any] | None,
    kit: dict[str, Any] | None = None,
) -> str | None:
    """The site's display family when one was captured. Generics are not a capture."""
    chosen = profile_fonts(brand_profile)
    headline = str(chosen.get("headline") or "").strip()
    if headline and headline.casefold() not in _GENERIC_TYPEFACES:
        return headline
    for raw in (kit or {}).get("fonts") or []:
        name = str(raw or "").strip()
        if name and name.casefold() not in _GENERIC_TYPEFACES and name.casefold() != "inter":
            return name
    return None


def resolve_display_fonts(
    brand_profile: dict[str, Any] | None,
    kit: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Use the captured display family. Noto is only for a poster with no captured face."""
    chosen = profile_fonts(brand_profile)
    captured = captured_display_family(brand_profile, kit)
    body_name = str(chosen.get("body") or "").strip()
    if not body_name or body_name.casefold() in _GENERIC_TYPEFACES:
        for raw in (kit or {}).get("fonts") or []:
            name = str(raw or "").strip()
            if name and captured and name.casefold() != captured.casefold() and name.casefold() not in _GENERIC_TYPEFACES:
                body_name = name
                break
    body = body_name or captured
    if captured:
        return {
            "headline": captured,
            "body": body or captured,
            "capturedHeadline": captured,
            "fontLoaded": usable_display_font(captured) is not None,
        }
    headline = DISPLAY_FALLBACK if _font_installed(DISPLAY_FALLBACK) else "Inter"
    if not body:
        body = "Inter" if _font_installed("Inter") else headline
    return {"headline": headline, "body": body, "capturedHeadline": "", "fontLoaded": True}


def type_quality(
    *,
    font: str,
    headline_size: float,
    subline_size: float,
    headline: str,
    headline_contrast: float | None = None,
    logo_contrast: float | None = None,
    captured_font: str | None = None,
    font_loaded: bool | None = None,
    logo_scraped: bool | None = None,
) -> dict[str, Any]:
    """Deterministic type bar. The picture judge uses the same failures."""
    failures: list[str] = []
    captured = (captured_font or "").strip()
    if captured and font.strip().casefold() != captured.casefold():
        failures.append("headline is not the captured display font")
    elif captured and font_loaded is False:
        failures.append("the brand font failed to load")
    elif not usable_display_font(font):
        failures.append("system font")
    if logo_scraped is False:
        failures.append("logo layer is not the scraped asset")
    if headline_size < 54:
        failures.append("headline under 54px")
    if subline_size and headline_size and subline_size > headline_size * 0.62:
        failures.append("subline too close in size")
    words = [w for w in (headline or "").replace("\n", " ").split() if w]
    if len(words) > 8:
        failures.append("more than 8 words in the headline")
    if headline_contrast is not None and headline_contrast < TEXT_CONTRAST_MIN:
        failures.append("headline contrast under 4.5:1")
    if logo_contrast is not None and logo_contrast < TEXT_CONTRAST_MIN:
        failures.append("logo contrast under 4.5:1")
    return {"passed": not failures, "reason": "; ".join(failures)}


def profile_fonts(brand_profile: dict[str, Any] | None) -> dict[str, Any]:
    """Optional ``brandProfile.typography`` → ``{"headline", "body", "headlineWeight"}`` overrides.

    Reads the brand-profile shape (``display`` / ``body`` objects with ``family`` and ``weights``) as
    well as ``headline`` aliases. A display face whose heaviest weight is 600–700 maps to ``bold``;
    lighter faces leave the design-system minimum (700) in place.
    """
    typo = (brand_profile or {}).get("typography")
    out: dict[str, Any] = {}
    if not isinstance(typo, dict):
        return out
    head = typo.get("display") or typo.get("headline")
    for role, entry in (("headline", head), ("body", typo.get("body"))):
        family = entry.get("family") if isinstance(entry, dict) else entry
        if isinstance(family, str) and family.strip():
            out[role] = family.strip()
    weights: list[int] = []
    for raw in (
        (head.get("weight") if isinstance(head, dict) else None),
        *((head.get("weights") or []) if isinstance(head, dict) else []),
        typo.get("headlineWeight"),
    ):
        try:
            weights.append(int(raw))
        except (TypeError, ValueError):
            continue
    heaviest = max(weights, default=0)
    if 600 <= heaviest <= 900:
        out["headlineWeight"] = "extrabold" if heaviest >= 800 else "bold"
    return out


def resolve_template_name(
    creative_brief: dict[str, Any] | None,
    *,
    has_image: bool,
    monochrome: bool,
    brand_profile: dict[str, Any] | None = None,
    communication_kit: dict[str, Any] | None = None,
) -> str:
    """Template used by both the server (Ideogram composition) and the compiler (layout)."""
    brief = creative_brief or {}
    name = brief.get("layoutTemplate")
    if name in TEMPLATES:
        return str(name)
    hint = template_hint_from_profile(brand_profile)
    if hint and (has_image or hint == "centered-statement"):
        return hint
    ck = communication_kit if isinstance(communication_kit, dict) else {}
    if ck.get("thinSite") and not has_image:
        blocking = str((ck.get("layoutMotif") or {}).get("blocking") or "")
        if blocking == "full-field":
            return "centered-statement"
        if blocking == "corner-block":
            return "full-bleed-scrim"
        return "device-stage"
    if not creative_brief:
        return "full-bleed-scrim" if has_image else "centered-statement"
    return default_template_for(
        layout_recipe=brief.get("layoutRecipe"),
        has_image=has_image,
        emphasis=brief.get("emphasis"),
        monochrome=monochrome,
    )


def headline_scale_for(text: str) -> str:
    words = len((text or "").split())
    if words <= 4:
        return "xl"
    if words <= 7:
        return "lg"
    return "md"


# --------------------------------------------------------------------------- copy


def word_count(text: str | None) -> int:
    return len((text or "").split())


def clamp_words(text: str | None, max_words: int, max_chars: int) -> str:
    """Trim to a sentence or word boundary; ellipsis only when a sentence had to be cut."""
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return ""
    if word_count(text) <= max_words and len(text) <= max_chars:
        return text
    first = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0].strip()
    if word_count(first) <= max_words and len(first) <= max_chars:
        return first
    words = first.split()[:max_words]
    out = " ".join(words)
    while len(out) > max_chars - 1 and len(words) > 1:
        words = words[:-1]
        out = " ".join(words)
    return out.rstrip(",;:—-") + "…"


# --------------------------------------------------------------------------- type fitting


def wrap_lines(text: str, size: float, box_w: float, em: float) -> list[str]:
    max_chars = max(1, int(box_w / (size * em)))
    lines: list[str] = []
    current = ""
    for word in (text or "").split():
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def balance_lines(text: str, size: float, box_w: float, em: float) -> list[str]:
    """Greedy wrap, then narrow the measure while the line count holds (no orphan last word)."""
    lines = wrap_lines(text, size, box_w, em)
    if len(lines) < 2:
        return lines
    step = size * em
    width = box_w
    while width > step:
        width -= step
        trial = wrap_lines(text, size, width, em)
        if len(trial) > len(lines):
            break
        lines = trial
    return lines


def avoid_orphan(lines: list[str]) -> list[str]:
    """Keep the last line from being a single word."""
    if len(lines) < 2 or len(lines[-1].split()) != 1:
        return lines
    words = " ".join(lines).split()
    if len(words) <= 2:
        return [" ".join(words)]
    return [" ".join(words[:-2]), " ".join(words[-2:])]


def fit_headline(
    text: str,
    box_w: float,
    scale: str,
    max_lines: int,
) -> tuple[int, list[str]]:
    size = HEADLINE_SCALE.get(scale, HEADLINE_SCALE["lg"])
    while True:
        lines = wrap_lines(text, size, box_w, HEADLINE_EM)
        longest = max((len(w) for w in text.split()), default=0)
        fits_words = longest * size * HEADLINE_EM <= box_w
        if (len(lines) <= max_lines and fits_words) or size <= HEADLINE_MIN_SIZE:
            return size, avoid_orphan(balance_lines(text, size, box_w, HEADLINE_EM))
        size -= 2


def text_block_height(lines: int, size: float, leading: float) -> float:
    return lines * size * leading


# --------------------------------------------------------------------------- layout plan


@dataclass
class LayoutPlan:
    template: str
    align: str
    elements: dict[str, dict[str, Any]] = field(default_factory=dict)
    panel: Box | None = None
    card: Box | None = None
    text_zone: Box | None = None

    def to_meta(self) -> dict[str, Any]:
        return {
            "template": self.template,
            "align": self.align,
            "panel": list(self.panel) if self.panel else None,
            "card": list(self.card) if self.card else None,
            "textZone": [round(v, 1) for v in self.text_zone] if self.text_zone else None,
            "elements": {
                k: {kk: (list(vv) if isinstance(vv, tuple) else vv) for kk, vv in v.items()}
                for k, v in self.elements.items()
            },
        }


def logo_target_size(img_w: int | None, img_h: int | None) -> tuple[float, float]:
    if not img_w or not img_h or img_w <= 0 or img_h <= 0:
        return 36 * 2.4, 36.0
    aspect = img_w / img_h
    if aspect >= 2.2:
        h = 36.0
    elif aspect >= 1.2:
        h = 44.0
    else:
        h = 48.0
    w = h * aspect
    max_w = span_w(3)
    if w > max_w:
        w = max_w
        h = w / aspect
    return w, h


TREATMENTS = ("full-sheet", "photo-band", "pattern-field", "illustration-cluster", "quiet-type")
IMAGE_TREATMENTS = frozenset(
    {"full-sheet", "photo-band", "pattern-field", "illustration-cluster", "quiet-type"}
)
# Photograph above a type band. Not a full-bleed sheet.
PHOTO_BAND: Box = (0.0, 0.0, CANVAS_W, 340.0)


def treatment_needs_image(treatment: str | None) -> bool:
    return treatment in IMAGE_TREATMENTS


def treatment_for_energy(energy: str | None) -> str:
    """Pick a poster treatment from the brand. A stark brand stays type-led."""
    if energy in ("quiet-type", "mark-stage", "type-only", "communique", "device-stage"):
        return "quiet-type"
    if energy in ("photo-block", "photo-card", "product-card"):
        return "photo-band"
    if energy == "gradient-field":
        return "pattern-field"
    if energy in ("circle-stage", "character-scene", "product-ui"):
        return "illustration-cluster"
    return "full-sheet"


def treatment_for_template(name: str | None) -> str:
    if name in ("type-only", "communique", "mark-stage", "device-stage", "centered-statement"):
        return "quiet-type"
    if name in ("photo-block", "photo-card", "product-card", "split-text-left"):
        return "photo-band"
    if name in ("circle-stage", "character-scene", "product-ui"):
        return "illustration-cluster"
    if name == "full-bleed-scrim":
        return "pattern-field"
    return "full-sheet"


def choose_treatment(brief: dict[str, Any] | None, energy: str | None = None) -> str:
    """A photo brand uses the photo band. Otherwise the brief's treatment wins."""
    if energy in ("photo-block", "photo-card"):
        return "photo-band"
    raw = (brief or {}).get("treatment")
    if raw in TREATMENTS:
        return str(raw)
    if energy:
        return treatment_for_energy(energy)
    return treatment_for_template(str((brief or {}).get("layoutTemplate") or ""))


def treatment_type_zone(treatment: str) -> str:
    if treatment in ("pattern-field", "illustration-cluster"):
        return "center"
    return "lower"


def quiet_zone_for(template: str | None) -> str:
    """Where editable type sits on a full-sheet poster. Not a side column beside a picture box."""
    if template in ("photo-block", "photo-card", "product-card", "split-text-left", "full-bleed-scrim"):
        return "lower"
    return "center"


def quiet_zone_phrase(zone: str) -> str:
    if zone == "lower":
        return (
            "Leave a quiet band along the bottom of the sheet, still part of the same composition, "
            "so type can sit there later."
        )
    return (
        "Leave the centre of the sheet quieter and clearer, still part of the same composition, "
        "so type can sit in the middle later."
    )


def place_type_in_quiet_zone(plan: LayoutPlan, zone: str) -> LayoutPlan:
    """Move the type stack onto the sheet, over the image, instead of a left column."""
    text_keys = [key for key in ("eyebrow", "headline", "subline", "cta") if key in plan.elements]
    if not text_keys:
        return plan
    boxes = [plan.elements[key]["box"] for key in text_keys]
    min_y = min(box[1] for box in boxes)
    max_y = max(box[1] + box[3] for box in boxes)
    stack_h = max_y - min_y
    if zone == "lower":
        new_top = CANVAS_H - MARGIN_Y - stack_h
    else:
        new_top = (CANVAS_H - stack_h) / 2
    new_top = max(MARGIN_Y, new_top)
    shift = new_top - min_y
    for key in text_keys:
        _x, y, width, height = plan.elements[key]["box"]
        plan.elements[key]["box"] = (
            round((CANVAS_W - width) / 2, 1),
            round(y + shift, 1),
            width,
            height,
        )
    plan.align = "center"
    if "logo" in plan.elements:
        _x, _y, logo_w, logo_h = plan.elements["logo"]["box"]
        if zone == "lower":
            logo_y = MARGIN_Y
        else:
            logo_y = max(MARGIN_Y, new_top - 28 - logo_h)
        plan.elements["logo"]["box"] = (
            round((CANVAS_W - logo_w) / 2, 1),
            round(logo_y, 1),
            logo_w,
            logo_h,
        )
    content_w = max(plan.elements[key]["box"][2] for key in text_keys)
    plan.text_zone = (
        round((CANVAS_W - content_w) / 2, 1),
        round(new_top, 1),
        content_w,
        stack_h,
    )
    plan.panel = None
    plan.card = None
    return plan


def plan_layout(
    template_name: str,
    *,
    headline: str,
    subline: str = "",
    eyebrow: str = "",
    cta: str = "",
    cta_style: str = "pill",
    headline_scale: str | None = None,
    headline_weight: str | None = None,
    logo_size: tuple[float, float] | None = None,
    box_x: float | None = None,
    box_w: float | None = None,
    anchor: str | None = None,
    align: str | None = None,
    max_lines: int | None = None,
) -> LayoutPlan:
    tpl = get_template(template_name)
    plan = LayoutPlan(template=tpl.name, align=align or tpl.align)  # type: ignore[arg-type]
    scale = headline_scale if headline_scale in HEADLINE_SCALE else headline_scale_for(headline)
    weight_key = headline_weight if headline_weight in HEADLINE_WEIGHT else (
        "bold" if scale == "md" else "extrabold"
    )
    box_x = tpl.text_x if box_x is None else box_x
    box_w = tpl.text_w if box_w is None else box_w
    anchor = anchor or tpl.anchor

    h_size, h_lines = fit_headline(headline, box_w, scale, max_lines or min(2, tpl.max_headline_lines) or 2)
    # Subline is about half the headline and lighter. Never close to the headline size.
    s_size = max(SUBLINE_MIN_SIZE, round(h_size * 0.46))
    s_lines = balance_lines(subline, s_size, box_w, BODY_EM) if subline else []
    if len(s_lines) > 2:
        s_lines = s_lines[:2]

    show_cta = bool(cta) and cta_style != "none"
    eyebrow_h = EYEBROW_SIZE * 1.2 if eyebrow else 0.0
    headline_h = text_block_height(len(h_lines), h_size, HEADLINE_LEADING)
    subline_h = text_block_height(len(s_lines), s_size, SUBLINE_LEADING)
    stack = [
        ("eyebrow", eyebrow_h, TEXT_GAP),
        ("headline", headline_h, TEXT_GAP),
        ("subline", subline_h, CTA_GAP),
        ("cta", CTA_HEIGHT if show_cta else 0.0, 0.0),
    ]
    stack = [item for item in stack if item[1] > 0]
    total_h = sum(h for _, h, _ in stack) + sum(g for _, _, g in stack[:-1])

    logo_w, logo_h = logo_size or (0.0, 0.0)
    if logo_size:
        if tpl.logo_align == "center":
            logo_x = CANVAS_W / 2 - logo_w / 2
        else:
            logo_x = col_x(0)
        plan.elements["logo"] = {
            "box": (round(logo_x, 1), MARGIN_Y, round(logo_w, 1), round(logo_h, 1)),
        }
    logo_bottom = MARGIN_Y + (logo_h if logo_size else 0.0)

    bottom_limit = CANVAS_H - MARGIN_Y
    if tpl.surface == "card":
        bottom_limit -= CARD_PAD
    if anchor == "bottom":
        top = bottom_limit - total_h
    else:
        region_top = logo_bottom + 32 if logo_size else MARGIN_Y
        top = region_top + max(0.0, (bottom_limit - region_top - total_h) / 2)
    top = max(top, logo_bottom + 24 if logo_size else MARGIN_Y)

    y = top
    for index, (name, height, gap) in enumerate(stack):
        if name == "eyebrow":
            plan.elements["eyebrow"] = {
                "box": (box_x, round(y, 1), box_w, round(height + 6, 1)),
                "size": EYEBROW_SIZE,
                "text": eyebrow.upper(),
            }
        elif name == "headline":
            plan.elements["headline"] = {
                "box": (box_x, round(y, 1), box_w, round(height + h_size * 0.3, 1)),
                "size": h_size,
                "scale": scale,
                "weight": HEADLINE_WEIGHT[weight_key],
                "weightKey": weight_key,
                "lines": len(h_lines),
                "leading": round(h_size * 0.96, 1),
                "text": "\n".join(h_lines),
            }
        elif name == "subline":
            plan.elements["subline"] = {
                "box": (box_x, round(y, 1), box_w, round(height + s_size * 0.4, 1)),
                "size": s_size,
                "lines": len(s_lines),
                "leading": round(s_size * SUBLINE_LEADING, 1),
                "text": "\n".join(s_lines),
            }
        elif name == "cta":
            label_w = len(cta) * CTA_LABEL_SIZE * 0.56
            chip_w = round(label_w + 2 * CTA_PAD_X)
            chip_x = box_x if plan.align == "left" else CANVAS_W / 2 - chip_w / 2
            plan.elements["cta"] = {
                "box": (round(chip_x, 1), round(y, 1), chip_w, CTA_HEIGHT),
                "label": cta,
                "style": cta_style,
                "size": CTA_LABEL_SIZE,
            }
        y += height + (gap if index < len(stack) - 1 else 0)

    text_boxes = [plan.elements[k]["box"] for k in ("eyebrow", "headline", "subline", "cta") if k in plan.elements]
    if text_boxes:
        content_w = max(
            max((len(line) for line in h_lines), default=0) * h_size * HEADLINE_EM,
            max((len(line) for line in s_lines), default=0) * s_size * BODY_EM,
            len(eyebrow) * EYEBROW_SIZE * CAPS_EM,
            plan.elements["cta"]["box"][2] if "cta" in plan.elements else 0.0,
        )
        content_w = min(box_w, content_w)
        x0 = box_x if plan.align == "left" else CANVAS_W / 2 - content_w / 2
        y0 = min(b[1] for b in text_boxes)
        y1 = max(b[1] + b[3] for b in text_boxes)
        plan.text_zone = (x0, y0, content_w, y1 - y0)

    if tpl.surface == "panel" and tpl.panel_box:
        plan.panel = tpl.panel_box
    if tpl.surface == "card" and plan.text_zone:
        card_x = col_x(0)
        card_y = plan.text_zone[1] - CARD_PAD
        plan.card = (card_x, card_y, span_w(7), CANVAS_H - MARGIN_Y - card_y)
    return plan


# --------------------------------------------------------------------------- background models


Sampler = Callable[[float, float], RGB]


def sample_box(sampler: Sampler, box: Box, steps_x: int = 12, steps_y: int = 6) -> list[RGB]:
    x, y, w, h = box
    out: list[RGB] = []
    for j in range(steps_y):
        for i in range(steps_x):
            px = x + (i + 0.5) * w / steps_x
            py = y + (j + 0.5) * h / steps_y
            out.append(sampler(min(CANVAS_W - 1, max(0, px)), min(CANVAS_H - 1, max(0, py))))
    return out


def solid_sampler(color: str) -> Sampler:
    rgb = hex_to_rgb(color)
    return lambda _x, _y: rgb


def diagonal_gradient_sampler(stops: Sequence[tuple[float, str]]) -> Sampler:
    """Matches the SVG / native brand gradient: (0,0) → (W,H), t = (u + v) / 2."""
    parsed = [(t, hex_to_rgb(c)) for t, c in stops]

    def _sample(x: float, y: float) -> RGB:
        t = (x / CANVAS_W + y / CANVAS_H) / 2
        for (t0, c0), (t1, c1) in zip(parsed, parsed[1:]):
            if t <= t1:
                local = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
                return blend(c0, c1, local)
        return parsed[-1][1]

    return _sample


def raster_sampler(
    grid: dict[str, Any],
    *,
    region: Box,
    align: str = "center",
) -> Sampler:
    """Map canvas → image pixels for a cover placement inside ``region``."""
    gw, gh = grid["w"], grid["h"]
    src_w, src_h = grid["src_w"], grid["src_h"]
    pixels: list[RGB] = grid["pixels"]
    rx, ry, rw, rh = region
    scale = max(rw / src_w, rh / src_h)
    disp_w, disp_h = src_w * scale, src_h * scale
    if align == "right":
        left = rx + rw - disp_w
    else:
        left = rx + (rw - disp_w) / 2
    top = ry + (rh - disp_h) / 2

    def _sample(x: float, y: float) -> RGB:
        u = (x - left) / disp_w
        v = (y - top) / disp_h
        gx = min(gw - 1, max(0, int(u * gw)))
        gy = min(gh - 1, max(0, int(v * gh)))
        return pixels[gy * gw + gx]

    return _sample


def assumed_photo_samples() -> list[RGB]:
    """Conservative stand-in when a raster can't be decoded (bright and dark extremes)."""
    return [(236, 232, 226)] * 6 + [(24, 24, 28)] * 6


# --------------------------------------------------------------------------- audit


def _inside_safe(box: Sequence[float]) -> bool:
    x, y, w, h = box
    return (
        x >= MARGIN_X - 0.5
        and y >= MARGIN_Y - 0.5
        and x + w <= CANVAS_W - MARGIN_X + 0.5
        and y + h <= CANVAS_H - MARGIN_Y + 0.5
    )


def audit_plan(
    plan: LayoutPlan,
    *,
    contrast: dict[str, float] | None = None,
    scrim_alpha: float | None = None,
    logo_count: int = 1,
    devices: list[dict[str, Any]] | None = None,
    visual_share: float | None = None,
    cta_required: bool | None = None,
) -> dict[str, Any]:
    """Score a layout against the design-system rules (0–100) with per-rule detail."""
    checks: list[dict[str, Any]] = []

    def add(rule: str, ok: bool, detail: str, weight: int = 1) -> None:
        checks.append({"rule": rule, "ok": bool(ok), "detail": detail, "weight": weight})

    els = plan.elements
    boxes = {k: v["box"] for k, v in els.items() if "box" in v}
    outside = [k for k, b in boxes.items() if not _inside_safe(b)]
    add("safe-margins", not outside, "all inside" if not outside else f"outside: {', '.join(outside)}", 2)

    text_keys = [k for k in ("eyebrow", "headline", "subline", "cta") if k in boxes]
    if plan.align == "left":
        edges = {round(boxes[k][0]) for k in text_keys}
        add("alignment", len(edges) <= 1, f"left edges {sorted(edges)}", 2)
    else:
        centers = {round(boxes[k][0] + boxes[k][2] / 2) for k in text_keys}
        add("alignment", max(centers) - min(centers) <= 2 if centers else True, f"centres {sorted(centers)}", 2)
    on_grid = all(
        any(abs(boxes[k][0] - (col_x(i) + off)) < 1 for i in range(COLUMNS) for off in (0, CARD_PAD))
        or plan.align == "center"
        for k in text_keys
    )
    add("grid", on_grid, "text starts on a column edge" if on_grid else "off-grid text block")

    head = els.get("headline") or {}
    sub = els.get("subline") or {}
    if head and sub:
        ratio = head.get("size", 0) / max(1, sub.get("size", 1))
        add("hierarchy", ratio >= HIERARCHY_RATIO_MIN, f"headline/subline {ratio:.2f}× (min {HIERARCHY_RATIO_MIN})", 2)
    if head:
        add("headline-weight", head.get("weight", 400) >= 700, f"weight {head.get('weight')}")
        add("legibility", head.get("size", 0) >= HEADLINE_MIN_SIZE, f"headline {head.get('size')}px")

    words = {
        "eyebrow": word_count((els.get("eyebrow") or {}).get("text")),
        "headline": word_count(head.get("text")),
        "subline": word_count(sub.get("text")),
        "cta": word_count((els.get("cta") or {}).get("label")),
    }
    over = [k for k, n in words.items() if n > MAX_WORDS[k]]
    total = sum(words.values())
    add(
        "copy-limits",
        not over and total <= MAX_TOTAL_WORDS,
        f"words {words} total {total}" + (f"; over: {', '.join(over)}" if over else ""),
    )
    if cta_required is False:
        add("cta", True, "brief did not ask for a call to action")
    else:
        add("cta", "cta" in els, "CTA chip present" if "cta" in els else "no CTA")

    if contrast:
        low = {
            k: round(v, 2)
            for k, v in contrast.items()
            if v < (GRAPHIC_CONTRAST_MIN if k == "ctaChip" else TEXT_CONTRAST_MIN)
        }
        add("contrast", not low, f"min ratios {({k: round(v, 2) for k, v in contrast.items()})}", 3)

    if scrim_alpha is not None:
        add("scrim", scrim_alpha <= SCRIM_MAX_ALPHA, f"gradient scrim alpha {scrim_alpha}")

    covered = 0.0
    for key in ("eyebrow", "headline", "subline", "cta", "logo"):
        if key in boxes:
            covered += boxes[key][2] * boxes[key][3]
    free = 1 - covered / (CANVAS_W * CANVAS_H)
    add("whitespace", free >= MIN_WHITESPACE_RATIO, f"{free:.0%} free of type (min {MIN_WHITESPACE_RATIO:.0%})")
    add("single-logo", logo_count <= 1, f"{logo_count} logo placement(s)")
    if visual_share is not None:
        add(
            "visual-mass",
            visual_share >= MIN_VISUAL_SHARE,
            f"{visual_share:.0%} of the canvas is brand imagery (min {MIN_VISUAL_SHARE:.0%})",
            3,
        )

    # Linearity poster tips, as checks a layout can pass or fail.
    text_sizes = [
        els[key].get("size", 0)
        for key in ("eyebrow", "subline", "cta")
        if key in els and els[key].get("size")
    ]
    focal_devices = [d for d in (devices or []) if d.get("role") == "focal"]
    one_focal = bool(head) and head.get("size", 0) > max(text_sizes, default=0) and len(focal_devices) <= 1
    add(
        "focal-point",
        one_focal,
        "headline is the type focal" + (f"; {len(focal_devices)} focal device(s)" if devices else ""),
        2,
    )
    hook_words = word_count(head.get("text"))
    hook_ok = bool(head) and hook_words <= 8 and head.get("size", 0) >= 54
    add("hook", hook_ok, f"headline {hook_words} words at {head.get('size')}px", 2)
    if sub:
        scale_ok = head.get("size", 0) / max(1, sub.get("size", 1)) >= HIERARCHY_RATIO_MIN
        scale_detail = f"headline/subline {head.get('size', 0) / max(1, sub.get('size', 1)):.2f}×"
    else:
        scale_ok = head.get("size", 0) >= HEADLINE_SCALE["lg"]
        scale_detail = f"headline {head.get('size')}px with no subline"
    add("scale-contrast", scale_ok, scale_detail, 2)
    if plan.align == "left":
        asymmetric = True
        asymmetry_detail = "text mass on the left, open field opposite"
    elif plan.template in (
        "centered-statement",
        "mark-stage",
        "product-card",
        "communique",
        "type-only",
        "photo-card",
        "character-scene",
        "product-ui",
    ):
        zone_w = plan.text_zone[2] if plan.text_zone else 0
        asymmetric = plan.text_zone is None or zone_w <= span_w(10) + 1
        asymmetry_detail = "picture centred, type held to one edge"
    else:
        asymmetric = False
        asymmetry_detail = "centred stack on a non-statement template"
    add("asymmetry", asymmetric, asymmetry_detail)
    tpl = get_template(plan.template)
    layered = (
        tpl.surface != "none"
        or tpl.scrim != "none"
        or bool(devices)
        or plan.template in (
            "circle-stage",
            "mark-stage",
            "product-card",
            "photo-block",
            "communique",
            "type-only",
            "photo-card",
            "character-scene",
            "product-ui",
        )
    )
    add(
        "layered-depth",
        layered,
        f"surface {tpl.surface}, scrim {tpl.scrim}" + (", devices" if devices else ""),
    )
    blocked = plan.panel is not None or plan.card is not None or plan.template in (
        "full-bleed-scrim",
        "centered-statement",
        "device-stage",
        "photo-block",
        "circle-stage",
        "mark-stage",
        "product-card",
        "communique",
        "type-only",
        "photo-card",
        "character-scene",
        "product-ui",
    )
    add("colour-blocking", blocked, "colour block, card, or full-bleed field")
    thumb_ok = head.get("size", 0) >= HEADLINE_MIN_SIZE and (not sub or sub.get("size", 0) >= SUBLINE_MIN_SIZE)
    add("thumbnail", thumb_ok, f"headline {head.get('size')}px, subline {(sub or {}).get('size')}px")
    if "logo" in boxes:
        lx, _ly, lw, lh = boxes["logo"]
        logo_ok = lh >= 28 and lw <= span_w(3) + 1 and lx >= MARGIN_X - 1
        add("logo-size", logo_ok, f"logo {lw:.0f}×{lh:.0f} at x {lx:.0f}", 2)

    total_weight = sum(c["weight"] for c in checks) or 1
    score = round(100 * sum(c["weight"] for c in checks if c["ok"]) / total_weight)
    return {"score": score, "checks": checks, "failed": [c["rule"] for c in checks if not c["ok"]]}
