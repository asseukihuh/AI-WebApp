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
  center: [x, y]?; scale: %?; fit: bool?; smartObject: bool?
"""

from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any

LINKEDIN_WIDTH = 1200
LINKEDIN_HEIGHT = 627
BATCH_FORMAT = "photocraft-command-batch-v1"


def _pick_color(kit: dict[str, Any] | None, index: int = 0, default: str = "#1a365d") -> str:
    colors = (kit or {}).get("colors") or []
    if index < len(colors):
        return _normalize_hex(colors[index], default)
    return default


def _normalize_hex(value: str, default: str) -> str:
    if not value:
        return default
    v = value.strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", v):
        return v.lower()
    if re.fullmatch(r"#[0-9a-fA-F]{3}", v):
        return "#" + "".join(c * 2 for c in v[1:]).lower()
    return default


def _contrast_text_color(bg_hex: str) -> str:
    hex6 = bg_hex.lstrip("#")
    if len(hex6) != 6:
        return "#ffffff"
    r, g, b = (int(hex6[i : i + 2], 16) for i in (0, 2, 4))
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#0f172a" if luminance > 0.6 else "#ffffff"


def _body_lines(session: dict[str, Any], max_lines: int = 3) -> str:
    facts = (session.get("brief") or {}).get("facts") or ""
    lines = [ln.strip() for ln in facts.splitlines() if ln.strip()]
    if not lines and session.get("captionDraft"):
        lines = [
            ln.strip()
            for ln in str(session["captionDraft"]).splitlines()
            if ln.strip()
        ][1:4]
    return "\n".join(lines[:max_lines])


def _pick_font(kit: dict[str, Any] | None) -> str:
    fonts = (kit or {}).get("fonts") or []
    for name in fonts:
        cleaned = str(name).strip()
        if cleaned and cleaned.lower() not in ("inherit", "sans-serif", "serif"):
            return cleaned
    return "Inter"


def _truncate(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def compile_poster_batch(
    kit: dict[str, Any] | None,
    session: dict[str, Any],
    *,
    logo_relative_path: str | None = None,
) -> dict[str, Any]:
    """Build a PhotoCraft command batch for a LinkedIn 1200×627 poster."""
    kit = kit or session.get("kitSnapshot") or {}
    brief = session.get("brief") or {}
    headline = _truncate(
        session.get("suggestedHeadline") or brief.get("headline") or "Important update",
        90,
    )
    body = _truncate(_body_lines(session), 220)
    site_name = _truncate(kit.get("siteName") or "Learn more", 48)

    primary = _pick_color(kit, 0, "#1a365d")
    accent = _pick_color(kit, 1, "#2c5282")
    text_on_primary = _contrast_text_color(primary)
    font = _pick_font(kit)

    document = {
        "width": LINKEDIN_WIDTH,
        "height": LINKEDIN_HEIGHT,
        "mode": "rgb",
        "depth": 8,
        "background": primary,
        "resolution": 72,
        "name": f"CommMaker LinkedIn — {site_name}",
    }

    steps: list[dict[str, Any]] = [
        {
            "command": "type.create",
            "params": {
                "name": "Headline",
                "box": [72, 72, 1056, 140],
                "text": headline,
                "font": font,
                "size": 44,
                "color": text_on_primary,
                "align": "left",
            },
        },
    ]

    if body:
        steps.append(
            {
                "command": "type.create",
                "params": {
                    "name": "Body",
                    "box": [72, 220, 1056, 360],
                    "text": body,
                    "font": font,
                    "size": 22,
                    "color": text_on_primary,
                    "align": "left",
                },
            }
        )

    steps.append(
        {
            "command": "type.create",
            "params": {
                "name": "Footer",
                "box": [72, 548, 1056, 610],
                "text": site_name,
                "font": font,
                "size": 18,
                "color": accent if accent != primary else text_on_primary,
                "align": "left",
            },
        }
    )

    placements: list[dict[str, Any]] = []
    if logo_relative_path:
        placements.append(
            {
                "path": logo_relative_path.replace("\\", "/"),
                "center": [LINKEDIN_WIDTH - 120, 80],
                "scale": 35,
                "smartObject": True,
            }
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
        "placements": placements,
        "output": {"relativePath": f"generated/{filename}"},
        "meta": {
            "headline": headline,
            "siteName": site_name,
            "primaryColor": primary,
            "accentColor": accent,
        },
    }


def logo_cache_basename(logo_url: str) -> str:
    digest = hashlib.sha256(logo_url.encode("utf-8")).hexdigest()[:16]
    ext = ".png"
    lower = logo_url.lower().split("?", 1)[0]
    for candidate in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"):
        if lower.endswith(candidate):
            ext = candidate if candidate != ".jpeg" else ".jpg"
            break
    return f"logo-{digest}{ext}"
