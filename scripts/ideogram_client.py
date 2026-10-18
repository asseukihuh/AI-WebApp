"""Ideogram 4.5 raster layers for CommMaker LinkedIn posters."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
import urllib.error
import urllib.request
from typing import Literal

IDEOGRAM_GENERATE_URL = "https://api.ideogram.ai/v2/image/generate/ideogram-4-5"
IDEOGRAM_REMIX_URL = "https://api.ideogram.ai/v2/image/remix/ideogram-4"


def ideogram_conditioning() -> dict[str, str | bool]:
    """How a poster field is conditioned on the website.

    Every graphic crop is uploaded on the multipart ``images`` field (up to five). They are examples for
    one poster, not a single source to copy. Remix is not used, because remix keeps
    text from the source. A page screenshot is not one of those files.
    """
    return {
        "generateUrl": IDEOGRAM_GENERATE_URL,
        "generateAcceptsReferenceImage": True,
        "imageField": "images",
        "maxExampleImages": 5,
        "remixUrl": IDEOGRAM_REMIX_URL,
        "remixKeepsSourceText": True,
        "mode": "reference-image",
        "note": (
            "Ideogram 4.5 generate accepts up to five images on the images field. "
            "Every graphic crop is sent as an example. Remix is not used, because remix keeps "
            "text from the source. Palette hexes and the imagery line stay in the text prompt."
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
    treatment: str | None = None,
    brand_packet: dict | None = None,
) -> dict:
    """Ideogram 4 JSON caption: zero ``text`` elements, subject boxes away from the text zone.

    Optional ``brand_profile`` fields used when present: ``aesthetic`` (list of style tags),
    ``imageryStyle`` (str) and ``palette`` (role dict or list).
    """
    from poster_design import get_template, normalize_hex, profile_palette_list

    profile = brand_profile or {}
    packet = brand_packet if isinstance(brand_packet, dict) else profile.get("ideogramPacket")
    packet = packet if isinstance(packet, dict) else {}
    clean = sanitize_scene_description(scene, brand_terms) or "abstract flowing brand-colored shapes"
    from ideogram_packet import palette_line as _packet_palette
    from ideogram_packet import scene_is_generic

    described = sanitize_scene_description(str(packet.get("imagery") or ""), brand_terms)
    if described and described.casefold() not in clean.casefold():
        clean = described if scene_is_generic(clean) else f"{described}. {clean}"
    role_line = _packet_palette(packet)

    def _with_palette(text: str) -> str:
        if role_line and "palette:" not in text.casefold():
            return f"{text.rstrip()} Palette: {role_line}."
        return text
    profile_colors = profile_palette_list(profile)
    packet_hexes = [normalize_hex(str(item.get("hex") or "")) for item in packet.get("palette") or [] if isinstance(item, dict)]
    packet_hexes = [c for c in packet_hexes if c]
    merged = packet_hexes + profile_colors + [c for c in (palette or []) if normalize_hex(c) not in profile_colors]
    colors = []
    for raw in merged:
        hex6 = normalize_hex(raw)
        if hex6 and hex6 not in colors:
            colors.append(hex6)
    colors = colors[:8]
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
            "high_level_description": _with_palette(
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
    sheet = treatment_spec(treatment or treatment_for_name(template))
    # Subject stays on the sheet, clear of a corner, and leaves the quiet type area open.
    subject_box = [80, 40, 920, 680] if sheet["zone"] == "lower" else [120, 80, 880, 920]
    return {
        "high_level_description": _with_palette(
            f"Text-free {sheet['treatment'].replace('-', ' ')}, aspect {sheet['aspect']}. {clean}. "
            f"{sheet['fill']} {sheet['quiet']} No lettering. Do not draw a logo or a wordmark."
        ),
        "style_description": {
            "aesthetics": tone,
            "lighting": "soft diffused light",
            "medium": "graphic design",
            "art_style": art_style,
            **({"color_palette": colors} if colors else {}),
        },
        "compositional_deconstruction": {
            "background": f"{sheet['fill']} {sheet['quiet']} No lettering and no border.",
            "elements": [
                {
                    "type": "obj",
                    "bbox": subject_box,
                    "desc": f"{clean}; one focal subject across the sheet, not cramped into a corner.",
                    **({"color_palette": colors[:5]} if colors else {}),
                }
            ],
        },
    }


def structured_prompt_text(prompt: dict) -> str:
    return json.dumps(prompt, separators=(",", ":"), ensure_ascii=False)


def _parse_resolution(resolution: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"(\d+)\s*x\s*(\d+)", (resolution or "").strip().lower())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def treatment_for_name(template: str | None) -> str:
    from poster_design import treatment_for_template

    return treatment_for_template(template)


def treatment_spec(treatment: str | None) -> dict[str, str]:
    """Prompt and Ideogram size for one treatment. Quiet type has no image."""
    kind = treatment if treatment in (
        "full-sheet",
        "photo-band",
        "pattern-field",
        "illustration-cluster",
        "quiet-type",
    ) else "full-sheet"
    if kind == "quiet-type":
        return {
            "treatment": kind,
            "resolution": closest_ideogram_resolution("1200x627"),
            "aspect": "16:9",
            "zone": "center",
            "quiet": "The words sit on this field in editable type.",
            "fill": (
                "Study the example images for materials, shapes, and palette. "
                "Make one coherent text-free asset for the quiet-type poster in that language. "
                "Do not paste the examples together. Do not copy the words in the examples."
            ),
            "prompt": "",
        }
    if kind == "photo-band":
        return {
            "treatment": kind,
            "resolution": closest_ideogram_resolution("1200x440"),
            "aspect": "wide",
            "zone": "lower",
            "quiet": "The type sits in a band below this picture, not inside a corner of it.",
            "fill": (
                "A text-free photograph in this brand's colours and imagery, filling its frame. "
                "It is the picture above a type band, not a full-bleed poster and not a separate box."
            ),
            "prompt": "",
        }
    if kind == "pattern-field":
        fill = (
            "A pattern or graphic field that fills the sheet in this brand's colours. "
            "One focal motif, with a calmer centre where type will sit. Not a picture box."
        )
    elif kind == "illustration-cluster":
        fill = (
            "An illustration cluster across the sheet in this brand's colours and imagery. "
            "The subject gathers around a quieter centre where type will sit. Not a sticker in a corner."
        )
    else:
        fill = (
            "A full-bleed scene that fills the sheet in this brand's colours and imagery. "
            "Leave a quieter area for type. Not a separate picture box."
        )
    zone = "center" if kind in ("pattern-field", "illustration-cluster") else "lower"
    quiet = (
        "Leave the centre quieter so type can sit in the middle."
        if zone == "center"
        else "Leave a quieter area for type on the sheet."
    )
    resolution = closest_ideogram_resolution("1200x627")
    return {
        "treatment": kind,
        "resolution": resolution,
        "aspect": "16:9",
        "zone": zone,
        "quiet": quiet,
        "fill": fill,
        "prompt": f"{fill} {quiet} No lettering.",
    }


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


def _quality_for_speed(speed: RenderingSpeed, *, has_image: bool) -> str:
    """4.5 uses ``quality``. ``very_low`` is only valid when a source image is attached."""
    if speed == "turbo":
        return "very_low" if has_image else "low"
    if speed == "quality":
        return "high"
    return "medium"


def _image_media_type(path: str) -> str | None:
    lower = path.lower()
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".webp"):
        return "image/webp"
    if lower.endswith(".jpg") or lower.endswith(".jpeg"):
        return "image/jpeg"
    return None


def _reference_paths(packet: dict | None) -> list[str]:
    """Every graphic example, up to the five Ideogram 4.5 will accept."""
    from ideogram_packet import MAX_IDEOGRAM_EXAMPLES

    found: list[str] = []
    for raw in (packet or {}).get("references") or []:
        path = str(raw or "")
        if path and os.path.isfile(path) and _image_media_type(path) and path not in found:
            found.append(path)
        if len(found) >= MAX_IDEOGRAM_EXAMPLES:
            break
    return found


def _encode_form(fields: list[tuple[str, str]], files: list[tuple[str, str, bytes, str]]) -> tuple[bytes, str]:
    boundary = f"----CommMaker{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields:
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    for name, filename, data, content_type in files:
        chunks.append(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode()
        )
        chunks.append(data)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _call_generate_api(
    prompt: str,
    resolution: str,
    *,
    api_key: str,
    rendering_speed: RenderingSpeed,
    magic_prompt: MagicPrompt = "off",
    reference_path: str | None = None,
    reference_paths: list[str] | None = None,
) -> dict:
    """POST Ideogram 4.5. Every example is a repeated ``images`` part. One poster comes back."""
    from ideogram_packet import MAX_IDEOGRAM_EXAMPLES

    paths: list[str] = []
    for path in list(reference_paths or []) + ([reference_path] if reference_path else []):
        if path and path not in paths and _image_media_type(path):
            paths.append(path)
        if len(paths) >= MAX_IDEOGRAM_EXAMPLES:
            break
    files: list[tuple[str, str, bytes, str]] = []
    for path in paths:
        media = _image_media_type(path)
        if not media:
            continue
        with open(path, "rb") as handle:
            image_bytes = handle.read(MAX_LAYER_BYTES + 1)
        if len(image_bytes) > MAX_LAYER_BYTES:
            continue
        files.append(("images", os.path.basename(path), image_bytes, media))
    has_image = bool(files)
    fields = [
        ("prompt", prompt),
        ("size", resolution),
        ("num_images", "1"),
        ("quality", _quality_for_speed(rendering_speed, has_image=has_image)),
        ("magic_prompt", magic_prompt),
        ("async", "false"),
    ]
    body, content_type = _encode_form(fields, files)
    req = urllib.request.Request(
        IDEOGRAM_GENERATE_URL,
        data=body,
        headers={
            "Api-Key": api_key,
            "Content-Type": content_type,
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
    treatment: str | None = None,
    brand_packet: dict | None = None,
) -> tuple[str, bytes, dict]:
    """
    Generate a raster layer via Ideogram 4.5 and cache under ``assets_dir``.

    ``prompt`` is a scene description; it is sanitized and wrapped in a structured JSON
    caption (no text elements, template subject boxes, brand palette). When the brand
    packet has a clean reference, that file is uploaded on the ``images`` field.

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
        treatment=treatment,
        brand_packet=brand_packet,
    )
    prompt = structured_prompt_text(structured)
    packet = brand_packet if isinstance(brand_packet, dict) else (brand_profile or {}).get("ideogramPacket")
    reference_paths = _reference_paths(packet if isinstance(packet, dict) else None)
    if reference_paths:
        kind = treatment or "poster"
        prompt = (
            f"These {len(reference_paths)} attached images show how this brand's components are built. "
            "Study all of them for materials, shapes, and palette. "
            f"Make one coherent text-free asset for the {kind} poster in that language. "
            "Do not paste the examples together into a jungle. "
            "Do not draw a logo or a wordmark. "
            "Do not copy the words in the examples. "
            + prompt
        )
    magic_prompt = resolve_magic_prompt()
    api_resolution = resolve_layer_resolution(role, resolution)
    payload = _call_generate_api(
        prompt,
        api_resolution,
        api_key=key,
        rendering_speed=resolve_rendering_speed(),
        magic_prompt=magic_prompt,
        reference_paths=reference_paths,
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
    cache_prompt = prompt
    if reference_paths:
        digest = hashlib.sha256("\n".join(reference_paths).encode("utf-8")).hexdigest()[:12]
        cache_prompt = f"{prompt}\nreferences:{digest}"
    basename = layer_cache_basename_for_prompt(
        cache_prompt, api_resolution, role=role, cutout=cutout
    )
    os.makedirs(assets_dir, exist_ok=True)
    abs_path = os.path.join(assets_dir, basename)
    if not os.path.isfile(abs_path):
        with open(abs_path, "wb") as handle:
            handle.write(image_bytes)

    rel_path = f"generated/assets/{basename}"
    meta: dict = {
        "role": role,
        "source": "ideogram-4.5",
        "referenceImageSent": bool(reference_paths),
        "referenceImages": reference_paths,
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
            f"Ideogram 4.5 uses preset sizes; requested {resolution}, generated at {api_resolution}."
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
        "heroSource": meta.get("source", "ideogram-4.5"),
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
