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
) -> dict:
    body = {
        "prompt": prompt,
        "resolution": resolution,
        "num_images": 1,
        "rendering_speed": rendering_speed,
        "magic_prompt": "auto",
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
) -> tuple[str, bytes, dict]:
    """
    Generate a raster layer via Ideogram 4.0 and cache under ``assets_dir``.

    Returns ``(relative_path, image_bytes, meta)`` where relative_path is like
    ``generated/assets/layer-ideogram-background-<hash>.png``.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError(f"prompt is required for Ideogram {role} generation")
    key = (api_key or ideogram_api_key()).strip()
    if not key:
        raise ValueError("IDEOGRAM_API_KEY is not set")

    api_resolution = resolve_layer_resolution(role, resolution)
    payload = _call_generate_api(
        prompt,
        api_resolution,
        api_key=key,
        rendering_speed=resolve_rendering_speed(),
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
        "imagePrompt": prompt,
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
