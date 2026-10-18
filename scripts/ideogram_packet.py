"""Small brand packet for Ideogram: palette roles, one imagery line, clean references.

Ideogram 4 generate accepts a text prompt only. It has no image or style-reference
field. Remix is not used, because remix keeps text from the source image. The hexes
and the imagery line are written into the prompt instead.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from typing import Any

SCREENSHOTS_SKIPPED_STATUS = "screenshots skipped, Ideogram only received colours"

_GENERIC_MARKERS = (
    "abstract flowing brand-colored shapes",
    "simple scene",
    "simple sunlit interior",
    "simple green character",
    "unmarked pack",
    "brand's visual language",
)


def scene_is_generic(scene: str) -> bool:
    text = " ".join((scene or "").casefold().split())
    if not text:
        return True
    return any(marker in text for marker in _GENERIC_MARKERS)


def palette_entries(profile: dict[str, Any] | None, kit: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """Role and hex pairs. Profile roles win; kit colours fill in when the profile has none."""
    from poster_design import normalize_hex

    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in (profile or {}).get("palette") or []:
        if not isinstance(item, dict):
            continue
        hex6 = normalize_hex(str(item.get("hex") or ""))
        role = str(item.get("role") or "").strip()
        if not hex6 or not role or hex6 in seen:
            continue
        seen.add(hex6)
        entries.append({"role": role, "hex": hex6})
    if entries:
        return entries[:6]
    roles = ("primary", "accent", "background", "text")
    for index, raw in enumerate((kit or {}).get("colors") or []):
        hex6 = normalize_hex(str(raw or ""))
        if not hex6 or hex6 in seen:
            continue
        seen.add(hex6)
        entries.append({"role": roles[min(index, len(roles) - 1)], "hex": hex6})
        if len(entries) >= 4:
            break
    return entries


def palette_line(packet: dict[str, Any] | None) -> str:
    parts = [
        f"{item.get('role')} {item.get('hex')}"
        for item in (packet or {}).get("palette") or []
        if item.get("role") and item.get("hex")
    ]
    return ", ".join(parts)


def imagery_line(profile: dict[str, Any] | None, *, saw_images: bool) -> str:
    """One line written from screenshots and social images. Empty when those were not seen."""
    if not saw_images or not isinstance(profile, dict):
        return ""
    style = profile.get("imageryStyle") or {}
    line = ""
    if isinstance(style, dict):
        line = str(style.get("ideogramPrompt") or "").strip()
        if not line:
            medium = str(style.get("primaryMedium") or "").replace("-", " ").strip()
            motifs = [str(item).strip() for item in style.get("motifs") or [] if str(item).strip()]
            treatment = str(style.get("colorTreatment") or "").strip()
            bits = [bit for bit in (medium, ", ".join(motifs[:4]), treatment) if bit and bit != "mixed"]
            line = ", ".join(bits)
    elif isinstance(style, str):
        line = style.strip()
    line = " ".join(line.split())
    if len(line) > 180:
        line = line[:177].rsplit(" ", 1)[0]
    return line


def prompt_with_packet(scene: str, packet: dict[str, Any] | None) -> str:
    """The generate prompt. A generic scene is not sent on its own."""
    packet = packet or {}
    imagery = " ".join(str(packet.get("imagery") or "").split())
    swatches = palette_line(packet)
    scene = " ".join((scene or "").split())
    parts: list[str] = []
    if imagery:
        parts.append(imagery.rstrip("."))
    if scene and scene.casefold() not in imagery.casefold():
        if not imagery or not scene_is_generic(scene):
            parts.insert(0, scene.rstrip("."))
    if swatches:
        parts.append(f"Palette: {swatches}")
    text = ". ".join(part for part in parts if part)
    if swatches or imagery:
        return text
    if scene_is_generic(scene):
        raise ValueError("Ideogram prompt is only a generic scene")
    return scene


def _luminance(pixel: tuple[int, int, int]) -> float:
    red, green, blue = pixel
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _metrics(pixels: list[tuple[int, int, int]], width: int, height: int) -> dict[str, float]:
    paper = 0
    edges = 0
    busy_rows = 0
    chroma = 0.0
    for y in range(height):
        row_edges = 0
        for x in range(width):
            pixel = pixels[y * width + x]
            lum = _luminance(pixel)
            if lum >= 226:
                paper += 1
            chroma += (max(pixel) - min(pixel)) / 255
            if x:
                if abs(lum - _luminance(pixels[y * width + x - 1])) > 40:
                    edges += 1
                    row_edges += 1
        if width > 1 and row_edges / (width - 1) > 0.12:
            busy_rows += 1
    count = max(1, width * height)
    return {
        "paper": paper / count,
        "edges": edges / count,
        "busy": busy_rows / max(1, height),
        "chroma": chroma / count,
    }


def mostly_page_text(pixels: list[tuple[int, int, int]], width: int, height: int) -> bool:
    """A page of UI type: white ground and glyph edges spread down the frame."""
    if width < 4 or height < 4 or not pixels:
        return True
    stats = _metrics(pixels, width, height)
    return stats["paper"] > 0.55 and stats["edges"] > 0.05 and stats["busy"] >= 0.34


def _usable_field(pixels: list[tuple[int, int, int]], width: int, height: int) -> bool:
    if mostly_page_text(pixels, width, height):
        return False
    stats = _metrics(pixels, width, height)
    if stats["paper"] > 0.92 and stats["edges"] < 0.02:
        return False
    return True


def _load_sample(path: str, grid_w: int = 48) -> tuple[int, int, list[tuple[int, int, int]]] | None:
    from image_luma import load_rgb_grid

    grid = load_rgb_grid(path, grid_w=grid_w)
    if grid and grid.get("pixels"):
        return int(grid["w"]), int(grid["h"]), list(grid["pixels"])
    if not os.path.isfile(path):
        return None
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                path,
                "-vf",
                f"scale={grid_w}:-1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "pipe:1",
            ],
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    raw = proc.stdout or b""
    if proc.returncode != 0 or len(raw) < grid_w * 3:
        return None
    height = len(raw) // (grid_w * 3)
    if height < 2:
        return None
    pixels = [
        (raw[i], raw[i + 1], raw[i + 2])
        for i in range(0, height * grid_w * 3, 3)
    ]
    return grid_w, height, pixels


def _crop_tile(
    pixels: list[tuple[int, int, int]],
    width: int,
    height: int,
    box: tuple[int, int, int, int],
    dest: str,
) -> None:
    from render_poster_samples import write_png

    x0, y0, tw, th = box
    rows: list[bytes] = []
    for y in range(y0, y0 + th):
        row = bytearray()
        for x in range(x0, x0 + tw):
            red, green, blue = pixels[y * width + x]
            row.extend((red, green, blue))
        rows.append(bytes(row))
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    write_png(dest, tw, th, rows)


def _best_tile(
    pixels: list[tuple[int, int, int]],
    width: int,
    height: int,
) -> tuple[int, int, int, int] | None:
    cols = 3
    rows = 3
    tw = max(4, width // cols)
    th = max(4, height // rows)
    best: tuple[float, tuple[int, int, int, int]] | None = None
    for row in range(rows):
        for col in range(cols):
            x0 = min(width - tw, col * tw)
            y0 = min(height - th, row * th)
            tile = [
                pixels[(y0 + y) * width + (x0 + x)]
                for y in range(th)
                for x in range(tw)
            ]
            if not _usable_field(tile, tw, th):
                continue
            score = _metrics(tile, tw, th)["chroma"]
            if best is None or score > best[0]:
                best = (score, (x0, y0, tw, th))
    return best[1] if best else None


def clean_references(paths: list[str], out_dir: str | None, *, limit: int = 2) -> list[str]:
    """Up to two files with no page text: a photo, a pattern, or a logo on its backdrop.

    A screenshot that is mostly UI text is not passed through. A quiet crop of that
    file is kept when one exists.
    """
    chosen: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if len(chosen) >= limit:
            break
        if not path or path in seen or not os.path.isfile(path):
            continue
        seen.add(path)
        loaded = _load_sample(path)
        if not loaded:
            continue
        width, height, pixels = loaded
        if _usable_field(pixels, width, height):
            chosen.append(path)
            continue
        if not out_dir:
            continue
        box = _best_tile(pixels, width, height)
        if not box:
            continue
        digest = hashlib.sha256(path.encode("utf-8")).hexdigest()[:10]
        dest = os.path.join(out_dir, f"ideogram-ref-{digest}-{len(chosen)}.png")
        _crop_tile(pixels, width, height, box, dest)
        chosen.append(dest)
    return chosen[:limit]


def build_ideogram_packet(
    profile: dict[str, Any] | None,
    kit: dict[str, Any] | None = None,
    *,
    image_paths: list[str] | None = None,
    screenshots_skipped: bool = False,
    out_dir: str | None = None,
) -> dict[str, Any]:
    """Palette, one imagery line, and clean reference files for one brand."""
    paths = [path for path in (image_paths or []) if path]
    saw_images = bool(paths) and not screenshots_skipped
    references = [] if screenshots_skipped else clean_references(paths, out_dir)
    imagery = imagery_line(profile, saw_images=saw_images)
    packet = {
        "palette": palette_entries(profile, kit),
        "imagery": imagery,
        "references": references,
        "screenshotsSkipped": bool(screenshots_skipped),
        "coloursOnly": bool(screenshots_skipped) or not imagery,
        "referenceImageSent": bool(references),
        "referenceNote": (
            "Ideogram 4.5 generate accepts one image on the images field. "
            "One clean reference is sent when one exists. Remix is not used, because remix keeps "
            "text from the source. Palette hexes and the imagery line stay in the text prompt."
        ),
    }
    if screenshots_skipped:
        packet["statusLine"] = SCREENSHOTS_SKIPPED_STATUS
    return packet


def packet_for_poster(
    kit: dict[str, Any] | None,
    profile: dict[str, Any] | None,
    *,
    repo_root: str | None = None,
    out_dir: str | None = None,
) -> dict[str, Any]:
    """The brand-pass packet when one was stored, otherwise one built from the kit."""
    for source in (kit, profile):
        if not isinstance(source, dict):
            continue
        stored = source.get("ideogramPacket")
        if isinstance(stored, dict) and "palette" in stored:
            return stored
    paths: list[str] = []
    shots = (kit or {}).get("screenshotPaths") if isinstance(kit, dict) else None
    if isinstance(shots, dict):
        for rel in shots.values():
            text = str(rel or "")
            if not text:
                continue
            if os.path.isabs(text) and os.path.isfile(text):
                paths.append(text)
                continue
            if repo_root:
                joined = os.path.join(repo_root, text.lstrip("/"))
                if os.path.isfile(joined):
                    paths.append(joined)
    skipped = False
    if not paths:
        try:
            from brand_profile import playwright_available

            ok, _reason = playwright_available()
            skipped = not ok
        except Exception:  # noqa: BLE001 — missing Playwright is the skip
            skipped = True
    return build_ideogram_packet(
        profile,
        kit,
        image_paths=paths,
        screenshots_skipped=skipped,
        out_dir=out_dir,
    )
