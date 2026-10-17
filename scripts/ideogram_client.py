"""Ideogram 4.0 raster layers for CommMaker LinkedIn posters."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
import urllib.error
import urllib.request
from typing import Literal

IDEOGRAM_GENERATE_URL = "https://api.ideogram.ai/v2/image/generate/ideogram-4"
IDEOGRAM_REMIX_URL = "https://api.ideogram.ai/v2/image/remix/ideogram-4"


def ideogram_conditioning() -> dict[str, str | bool]:
    """How a poster field is conditioned on the website.

    Ideogram 4 generate (the endpoint CommMaker calls) takes a prompt and a resolution.
    It has no style-reference, character-reference, or image input. Remix accepts one
    image, but the prompt is an edit instruction and the source is preserved, so a page
    screenshot would come back with its text and logos. Screenshots are therefore shown
    to the brief model, and only the text-free prompt plus the palette are sent here.
    """
    return {
        "generateUrl": IDEOGRAM_GENERATE_URL,
        "generateAcceptsReferenceImage": False,
        "remixUrl": IDEOGRAM_REMIX_URL,
        "remixKeepsSourceText": True,
        "mode": "vision-prompt",
        "note": (
            "Ideogram 4 generate has no image reference. Remix would keep page text, so it is not "
            "used. Website screenshots are vision input when the brief model writes the prompt; "
            "the generate call sends that text-free prompt and the brand palette."
        ),
    }
IDEOGRAM_REMOVE_BG_URL = "https://api.ideogram.ai/v2/image/remove-background/ideogram-1"
IDEOGRAM_TIMEOUT_SEC = 120
MAX_LAYER_BYTES = 8_000_000

# LinkedIn poster is 1200×627; Ideogram 4.0 only accepts preset resolutions (no exact 1200×627).
LINKEDIN_TARGET_RESOLUTION = "1200x627"
DEFAULT_BACKGROUND_RESOLUTION = "1280x720"
# Accent subjects are placed at ~45% canvas width — square preset keeps detail without huge files.
DEFAULT_ACCENT_RESOLUTION = "1024x1024"

IDEOGRAM_PRESET_RESOLUTIONS: tuple[str, ...] = (
    "2048x2048",
    "1440x2880",
    "2880x1440",
    "1664x2496",
    "2496x1664",
    "1792x2240",
    "2240x1792",
    "1440x2560",
    "2560x1440",
    "1600x2560",
    "2560x1600",
    "1728x2304",
    "2304x1728",
    "1296x3168",
    "3168x1296",
    "1152x2944",
    "2944x1152",
    "1248x3328",
    "3328x1248",
    "1280x3072",
    "3072x1280",
    "1024x3072",
    "3072x1024",
    "1024x1024",
    "896x1120",
    "1120x896",
    "864x1152",
    "1152x864",
    "832x1248",
    "1248x832",
    "800x1280",
    "1280x800",
    "720x1280",
    "1280x720",
    "720x1440",
    "1440x720",
    "512x1536",
    "1536x512",
)

LayerRole = Literal["background", "accent"]
RenderingSpeed = Literal["turbo", "default", "quality"]
MagicPrompt = Literal["auto", "on", "off"]

# Words that invite Ideogram (a text-rendering model) to paint lettering or marks.
_TEXT_INVITING_WORDS = re.compile(
    r"\b(logos?|wordmarks?|brand\s*marks?|monograms?|emblems?|watermarks?|texts?|typography|"
    r"typographic|letter(?:ing|s)?|headlines?|titles?|captions?|labels?|signage|signs?|"
    r"posters?|banners?|slogans?|taglines?|words?|fonts?|copy|ui|screenshots?|mockups?)\b",
    re.I,
)
_NEGATION_PHRASE = re.compile(r"\b(no|without|free of|avoid(?:ing)?)\b[^,.;]*", re.I)
_QUOTED = re.compile(r"[\"“”'‘’][^\"“”'‘’]{1,80}[\"“”'‘’]")
_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")

ROLE_DEFAULT_RESOLUTION: dict[LayerRole, str] = {
    "background": DEFAULT_BACKGROUND_RESOLUTION,
    "accent": DEFAULT_ACCENT_RESOLUTION,
}


def ideogram_api_key() -> str:
    return (os.environ.get("IDEOGRAM_API_KEY") or "").strip()


def accent_cutout_enabled() -> bool:
    raw = (os.environ.get("COMMMAKER_IDEOGRAM_ACCENT_CUTOUT") or "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


def resolve_rendering_speed() -> RenderingSpeed:
    raw = (os.environ.get("COMMMAKER_IDEOGRAM_RENDERING") or "DEFAULT").strip().upper()
    mapping = {
        "TURBO": "turbo",
        "DEFAULT": "default",
        "QUALITY": "quality",
    }
    return mapping.get(raw, "default")


def resolve_magic_prompt() -> MagicPrompt:
    """``off`` by default: a well-formed JSON prompt is used as written (no brand re-injection)."""
    raw = (os.environ.get("COMMMAKER_IDEOGRAM_MAGIC_PROMPT") or "off").strip().lower()
    return raw if raw in ("auto", "on", "off") else "off"  # type: ignore[return-value]


def brand_terms_from_kit(kit: dict | None) -> list[str]:
    """Names that must never reach Ideogram (site name, its words, domain stem)."""
    kit = kit or {}
    terms: list[str] = []
    site = re.sub(r"\s+", " ", str(kit.get("siteName") or "")).strip()
    if site:
        terms.append(site)
        terms.extend(w for w in re.split(r"[\s\-–|·:]+", site) if len(w) >= 3)
    source = str(kit.get("sourceUrl") or "")
    host = re.sub(r"^https?://(www\.)?", "", source).split("/", 1)[0]
    stem = host.split(".")[0] if host else ""
    if len(stem) >= 3:
        terms.append(stem)
    seen: set[str] = set()
    out: list[str] = []
    for term in terms:
        key = term.casefold()
        if key not in seen and key not in ("the", "and", "inc", "home", "accueil"):
            seen.add(key)
            out.append(term)
    return out


def sanitize_scene_description(text: str, brand_terms: list[str] | None = None) -> str:
    """Strip brand names, quoted copy, hex codes and text-inviting words from a scene prompt."""
    out = _QUOTED.sub(" ", text or "")
    out = _NEGATION_PHRASE.sub(" ", out)
    for term in sorted(brand_terms or [], key=len, reverse=True):
        out = re.sub(rf"\b{re.escape(term)}(?:'s|’s)?\b", " ", out, flags=re.I)
    out = _HEX.sub(" ", out)
    out = _TEXT_INVITING_WORDS.sub(" ", out)
    out = re.sub(r"\b(for|of|by|with|from|featuring)\s*(?=[,.;]|$)", " ", out, flags=re.I)
    out = re.sub(r"\s+([,.;])", r"\1", out)
    out = re.sub(r"([,.;])\s*(?:[,.;]\s*)+", r"\1 ", out)
    out = re.sub(r"\s{2,}", " ", out).strip(" ,.;")
    return out


_TEXT_PRONE_MEDIA = frozenset({"product-ui", "typographic", "mixed"})


def imagery_style_phrase(imagery: object) -> str:
    """``brandProfile.imageryStyle`` (string, or object with ``primaryMedium`` / ``motifs`` /
    ``colorTreatment``) → short art-style phrase. UI and typographic media are skipped because
    they invite rendered text."""
    if isinstance(imagery, str):
        return imagery.strip()
    if not isinstance(imagery, dict):
        return ""
    parts: list[str] = []
    medium = str(imagery.get("primaryMedium") or "").strip()
    if medium and medium not in _TEXT_PRONE_MEDIA:
        parts.append(medium.replace("-", " "))
    motifs = [str(m).strip() for m in imagery.get("motifs") or [] if str(m).strip()]
    if motifs:
        parts.append(", ".join(motifs[:3]))
    treatment = str(imagery.get("colorTreatment") or "").strip()
    if treatment:
        parts.append(treatment)
    return "; ".join(parts)


def build_structured_prompt(
    scene: str,
    *,
    role: LayerRole,
    template: str | None = None,
    palette: list[str] | None = None,
    brand_terms: list[str] | None = None,
    mood: str | None = None,
    brand_profile: dict | None = None,
) -> dict:
    """Ideogram 4 JSON caption: zero ``text`` elements, subject boxes away from the text zone.

    Optional ``brand_profile`` fields used when present: ``aesthetic`` (list of style tags),
    ``imageryStyle`` (str) and ``palette`` (role dict or list).
    """
    from poster_design import get_template, normalize_hex, profile_palette_list

    profile = brand_profile or {}
    clean = sanitize_scene_description(scene, brand_terms) or "abstract flowing brand-colored shapes"
    profile_colors = profile_palette_list(profile)
    merged = profile_colors + [c for c in (palette or []) if normalize_hex(c) not in profile_colors]
    colors = [normalize_hex(c) for c in merged if normalize_hex(c)][:8]
    aesthetic = profile.get("aesthetic")
    if isinstance(aesthetic, list) and aesthetic:
        mood = ", ".join(str(a) for a in aesthetic[:4]) + (f", {mood}" if mood else "")
    tone = sanitize_scene_description(mood or "", brand_terms) or "calm, premium, modern"
    imagery = sanitize_scene_description(imagery_style_phrase(profile.get("imageryStyle")), brand_terms)
    art_style = (
        f"{imagery}, plain unmarked surfaces"
        if imagery
        else "abstract editorial art direction, subtle grain, plain unmarked surfaces"
    )
    if role == "accent":
        return {
            "high_level_description": (
                f"A single isolated object: {clean}, centred on a plain seamless light studio backdrop."
            ),
            "style_description": {
                "aesthetics": f"{tone}, clean, minimal, product-shot clarity",
                "lighting": "soft even studio light, gentle contact shadow",
                "medium": "3D render",
                "art_style": "polished editorial illustration, smooth materials, no surface markings",
                **({"color_palette": colors} if colors else {}),
            },
            "compositional_deconstruction": {
                "background": "A plain, seamless, very light grey studio backdrop with nothing else in frame.",
                "elements": [
                    {
                        "type": "obj",
                        "bbox": [150, 150, 850, 850],
                        "desc": f"{clean}; smooth unmarked surfaces, fully inside the frame.",
                        **({"color_palette": colors[:5]} if colors else {}),
                    }
                ],
            },
        }
    tpl = get_template(template)
    elements = [
        {
            "type": "obj",
            "bbox": list(bbox),
            "desc": f"{clean}; smooth, unmarked surfaces.",
            **({"color_palette": colors[:5]} if colors else {}),
        }
        for bbox in tpl.ideogram_subject_bboxes
    ]
    return {
        "high_level_description": (
            f"A clean, text-free marketing background image: {clean}. "
            f"Composition: {tpl.ideogram_layout_note}."
        ),
        "style_description": {
            "aesthetics": f"{tone}, uncluttered, generous negative space",
            "lighting": "soft diffused light, smooth tonal gradients",
            "medium": "graphic design",
            "art_style": art_style,
            **({"color_palette": colors} if colors else {}),
        },
        "compositional_deconstruction": {
            "background": f"{tpl.ideogram_background[0].upper()}{tpl.ideogram_background[1:]}.",
            "elements": elements,
        },
    }


def structured_prompt_text(prompt: dict) -> str:
    return json.dumps(prompt, separators=(",", ":"), ensure_ascii=False)


def _parse_resolution(resolution: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"(\d+)\s*x\s*(\d+)", (resolution or "").strip().lower())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def closest_ideogram_resolution(requested: str) -> str:
    """Map a target size to the nearest supported Ideogram 4 preset."""
    if requested in IDEOGRAM_PRESET_RESOLUTIONS:
        return requested
    target = _parse_resolution(requested)
    if not target:
        return DEFAULT_BACKGROUND_RESOLUTION
    tw, th = target
    target_ratio = tw / th if th else 1.0
    best = DEFAULT_BACKGROUND_RESOLUTION
    best_score = float("inf")
    for preset in IDEOGRAM_PRESET_RESOLUTIONS:
        parsed = _parse_resolution(preset)
        if not parsed:
            continue
        pw, ph = parsed
        ratio = pw / ph
        score = abs(ratio - target_ratio) * 1000 + abs(pw * ph - tw * th) / 1000
        if score < best_score:
            best_score = score
            best = preset
    return best


def resolve_layer_resolution(role: LayerRole, resolution: str | None) -> str:
    """Preset resolution for a layer role (background vs accent)."""
    requested = (resolution or "").strip() or ROLE_DEFAULT_RESOLUTION[role]
    if role == "background":
        return closest_ideogram_resolution(requested)
    # Accent: prefer squarish presets when targeting square default.
    if requested in IDEOGRAM_PRESET_RESOLUTIONS:
        return requested
    return closest_ideogram_resolution(requested or DEFAULT_ACCENT_RESOLUTION)


def layer_cache_basename_for_prompt(
    prompt: str,
    resolution: str,
    *,
    role: LayerRole,
    cutout: bool = False,
) -> str:
    digest = hashlib.sha256(
        f"{role}\n{resolution}\n{int(cutout)}\n{prompt}".encode("utf-8")
    ).hexdigest()[:16]
    suffix = "-cutout" if cutout else ""
    return f"layer-ideogram-{role}{suffix}-{digest}.png"


def hero_cache_basename_for_prompt(prompt: str, resolution: str) -> str:
    """Backward-compatible hero cache name (background role)."""
    return layer_cache_basename_for_prompt(prompt, resolution, role="background")


def _download_image(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "CommMaker-IdeogramClient/0.2 (+https://github.com/asseukihuh/AI-WebApp)",
            "Accept": "image/*,*/*",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=IDEOGRAM_TIMEOUT_SEC) as resp:
        data = resp.read(MAX_LAYER_BYTES + 1)
    if len(data) > MAX_LAYER_BYTES:
        raise ValueError("Ideogram image too large")
    return data


def _call_generate_api(
    prompt: str,
    resolution: str,
    *,
    api_key: str,
    rendering_speed: RenderingSpeed,
    magic_prompt: MagicPrompt = "off",
) -> dict:
    body = {
        "prompt": prompt,
        "resolution": resolution,
        "num_images": 1,
        "rendering_speed": rendering_speed,
        "magic_prompt": magic_prompt,
        "async": False,
    }
    req = urllib.request.Request(
        IDEOGRAM_GENERATE_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Api-Key": api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=IDEOGRAM_TIMEOUT_SEC) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _encode_multipart_image(
    field_name: str,
    filename: str,
    image_bytes: bytes,
    *,
    content_type: str = "image/png",
) -> tuple[bytes, str]:
    boundary = f"----CommMaker{uuid.uuid4().hex}"
    lines: list[bytes] = []
    lines.append(f"--{boundary}\r\n".encode())
    lines.append(
        (
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode()
    )
    lines.append(image_bytes)
    lines.append(b"\r\n")
    lines.append(f"--{boundary}--\r\n".encode())
    body = b"".join(lines)
    content_type_header = f"multipart/form-data; boundary={boundary}"
    return body, content_type_header


def remove_background(
    local_path: str,
    *,
    api_key: str | None = None,
    assets_dir: str | None = None,
) -> tuple[str, bytes, dict]:
    """
    Remove background via Ideogram 1; cache transparent PNG with alpha when ``assets_dir`` set.

    Returns ``(relative_path, image_bytes, meta)``.
    """
    key = (api_key or ideogram_api_key()).strip()
    if not key:
        raise ValueError("IDEOGRAM_API_KEY is not set")
    if not os.path.isfile(local_path):
        raise ValueError(f"Source image not found: {local_path}")

    with open(local_path, "rb") as handle:
        source_bytes = handle.read(MAX_LAYER_BYTES + 1)
    if len(source_bytes) > MAX_LAYER_BYTES:
        raise ValueError("Source image too large for background removal")

    body, content_type = _encode_multipart_image(
        "image",
        os.path.basename(local_path),
        source_bytes,
    )
    req = urllib.request.Request(
        IDEOGRAM_REMOVE_BG_URL,
        data=body,
        headers={
            "Api-Key": key,
            "Content-Type": content_type,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=IDEOGRAM_TIMEOUT_SEC) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if payload.get("error"):
        raise ValueError(str(payload.get("error")))
    data = payload.get("data") or []
    if not data:
        raise ValueError("Ideogram remove-background returned no images")
    first = data[0]
    if not first.get("is_image_safe", True):
        raise ValueError("Ideogram cutout did not pass safety checks")
    url = first.get("url")
    if not url:
        raise ValueError("Ideogram cutout response missing image URL")

    image_bytes = _download_image(url)
    digest = hashlib.sha256(source_bytes).hexdigest()[:16]
    basename = f"layer-ideogram-accent-cutout-{digest}.png"
    rel_path = f"generated/assets/{basename}"
    if assets_dir:
        os.makedirs(assets_dir, exist_ok=True)
        abs_path = os.path.join(assets_dir, basename)
        if not os.path.isfile(abs_path):
            with open(abs_path, "wb") as handle:
                handle.write(image_bytes)
    meta = {
        "role": "accent",
        "source": "ideogram-1-remove-background",
        "cutout": True,
    }
    return rel_path, image_bytes, meta


def generate_layer_image(
    prompt: str,
    role: LayerRole,
    resolution: str,
    *,
    assets_dir: str,
    api_key: str | None = None,
    remove_bg: bool = False,
    template: str | None = None,
    palette: list[str] | None = None,
    brand_terms: list[str] | None = None,
    mood: str | None = None,
    brand_profile: dict | None = None,
) -> tuple[str, bytes, dict]:
    """
    Generate a raster layer via Ideogram 4.0 and cache under ``assets_dir``.

    ``prompt`` is a scene description; it is sanitized and wrapped in a structured Ideogram 4
    JSON caption (no text elements, template subject boxes, brand palette) before sending.

    Returns ``(relative_path, image_bytes, meta)`` where relative_path is like
    ``generated/assets/layer-ideogram-background-<hash>.png``.
    """
    scene = (prompt or "").strip()
    if not scene:
        raise ValueError(f"prompt is required for Ideogram {role} generation")
    key = (api_key or ideogram_api_key()).strip()
    if not key:
        raise ValueError("IDEOGRAM_API_KEY is not set")

    structured = build_structured_prompt(
        scene,
        role=role,
        template=template,
        palette=palette,
        brand_terms=brand_terms,
        mood=mood,
        brand_profile=brand_profile,
    )
    prompt = structured_prompt_text(structured)
    magic_prompt = resolve_magic_prompt()
    api_resolution = resolve_layer_resolution(role, resolution)
    payload = _call_generate_api(
        prompt,
        api_resolution,
        api_key=key,
        rendering_speed=resolve_rendering_speed(),
        magic_prompt=magic_prompt,
    )
    data = payload.get("data") or []
    if not data:
        raise ValueError("Ideogram returned no images")
    first = data[0]
    if not first.get("is_image_safe", True):
        raise ValueError("Ideogram image did not pass safety checks")
    url = first.get("url")
    if not url:
        raise ValueError("Ideogram response missing image URL")

    image_bytes = _download_image(url)
    cutout = bool(remove_bg and role == "accent" and accent_cutout_enabled())
    basename = layer_cache_basename_for_prompt(
        prompt, api_resolution, role=role, cutout=cutout
    )
    os.makedirs(assets_dir, exist_ok=True)
    abs_path = os.path.join(assets_dir, basename)
    if not os.path.isfile(abs_path):
        with open(abs_path, "wb") as handle:
            handle.write(image_bytes)

    rel_path = f"generated/assets/{basename}"
    meta: dict = {
        "role": role,
        "source": "ideogram-4",
        "imagePrompt": scene,
        "structuredPrompt": structured,
        "magicPrompt": magic_prompt,
        "template": template,
        "ideogramResolution": api_resolution,
        "requestedResolution": resolution,
        "renderingSpeed": resolve_rendering_speed(),
    }
    if api_resolution != (resolution or "").replace(" ", "").lower():
        meta["resolutionNote"] = (
            f"Ideogram 4 uses preset sizes; requested {resolution}, generated at {api_resolution}."
        )

    if cutout:
        try:
            rel_path, image_bytes, cutout_meta = remove_background(
                abs_path,
                api_key=key,
                assets_dir=assets_dir,
            )
            meta.update(cutout_meta)
            meta["cutoutSourcePath"] = abs_path
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            ValueError,
            json.JSONDecodeError,
            OSError,
        ):
            meta["cutoutFailed"] = True

    return rel_path, image_bytes, meta


def generate_hero_image(
    prompt: str,
    resolution: str,
    *,
    assets_dir: str,
    api_key: str | None = None,
) -> tuple[str, bytes, dict]:
    """Backward-compatible single background hero generation."""
    rel, data, meta = generate_layer_image(
        prompt,
        "background",
        resolution,
        assets_dir=assets_dir,
        api_key=api_key,
    )
    legacy_meta = {
        "heroSource": meta.get("source", "ideogram-4"),
        "heroImagePrompt": meta.get("imagePrompt", prompt),
        "ideogramResolution": meta.get("ideogramResolution"),
        "requestedResolution": meta.get("requestedResolution", resolution),
        "renderingSpeed": meta.get("renderingSpeed"),
        "role": "background",
    }
    if meta.get("resolutionNote"):
        legacy_meta["resolutionNote"] = (
            f"{meta['resolutionNote']} Poster compiler cover-fills 1200×627."
        )
    return rel, data, legacy_meta
