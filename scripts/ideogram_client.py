"""Ideogram 4.0 hero image generation for CommMaker LinkedIn posters."""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from typing import Literal

IDEOGRAM_API_URL = "https://api.ideogram.ai/v2/image/generate/ideogram-4"
IDEOGRAM_TIMEOUT_SEC = 120
MAX_HERO_BYTES = 8_000_000

# LinkedIn poster is 1200×627; Ideogram 4.0 only accepts preset resolutions (no exact 1200×627).
# Closest landscape preset (~1.91:1 vs LinkedIn ~1.91:1): 1280×720 (16:9). Compiler cover-fills 1200×627.
LINKEDIN_TARGET_RESOLUTION = "1200x627"
DEFAULT_IDEOGRAM_RESOLUTION = "1280x720"

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

RenderingSpeed = Literal["turbo", "default", "quality"]


def ideogram_api_key() -> str:
    return (os.environ.get("IDEOGRAM_API_KEY") or "").strip()


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
        return DEFAULT_IDEOGRAM_RESOLUTION
    tw, th = target
    target_ratio = tw / th if th else 1.0
    best = DEFAULT_IDEOGRAM_RESOLUTION
    best_score = float("inf")
    for preset in IDEOGRAM_PRESET_RESOLUTIONS:
        parsed = _parse_resolution(preset)
        if not parsed:
            continue
        pw, ph = parsed
        ratio = pw / ph
        # Prefer similar aspect ratio, then similar pixel count.
        score = abs(ratio - target_ratio) * 1000 + abs(pw * ph - tw * th) / 1000
        if score < best_score:
            best_score = score
            best = preset
    return best


def hero_cache_basename_for_prompt(prompt: str, resolution: str) -> str:
    digest = hashlib.sha256(f"{resolution}\n{prompt}".encode("utf-8")).hexdigest()[:16]
    return f"hero-ideogram-{digest}.png"


def _download_image(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "CommMaker-IdeogramClient/0.1 (+https://github.com/asseukihuh/AI-WebApp)",
            "Accept": "image/*,*/*",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=IDEOGRAM_TIMEOUT_SEC) as resp:
        data = resp.read(MAX_HERO_BYTES + 1)
    if len(data) > MAX_HERO_BYTES:
        raise ValueError("Ideogram hero image too large")
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
        IDEOGRAM_API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Api-Key": api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=IDEOGRAM_TIMEOUT_SEC) as resp:
        return json.loads(resp.read().decode("utf-8"))


def generate_hero_image(
    prompt: str,
    resolution: str,
    *,
    assets_dir: str,
    api_key: str | None = None,
) -> tuple[str, bytes, dict]:
    """
    Generate a hero PNG via Ideogram 4.0 and cache under ``assets_dir``.

    Returns ``(relative_path, image_bytes, meta)`` where relative_path is like
    ``generated/assets/hero-ideogram-<hash>.png``.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("heroImagePrompt is required for Ideogram generation")
    key = (api_key or ideogram_api_key()).strip()
    if not key:
        raise ValueError("IDEOGRAM_API_KEY is not set")

    api_resolution = closest_ideogram_resolution(resolution)
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
    basename = hero_cache_basename_for_prompt(prompt, api_resolution)
    os.makedirs(assets_dir, exist_ok=True)
    abs_path = os.path.join(assets_dir, basename)
    if not os.path.isfile(abs_path):
        with open(abs_path, "wb") as handle:
            handle.write(image_bytes)

    rel_path = f"generated/assets/{basename}"
    meta = {
        "heroSource": "ideogram-4",
        "heroImagePrompt": prompt,
        "ideogramResolution": api_resolution,
        "requestedResolution": resolution,
        "renderingSpeed": resolve_rendering_speed(),
    }
    if api_resolution != resolution.replace(" ", "").lower():
        meta["resolutionNote"] = (
            f"Ideogram 4 uses preset sizes; requested {resolution}, generated at {api_resolution} "
            f"(poster compiler cover-fills 1200×627)."
        )
    return rel_path, image_bytes, meta
