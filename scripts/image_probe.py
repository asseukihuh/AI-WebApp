"""Read width/height from common raster and SVG assets without extra dependencies."""

from __future__ import annotations

import re
import struct
from pathlib import Path

_VIEWBOX_RE = re.compile(
    r"viewBox\s*=\s*[\"']([\d.\s\-]+)[\"']",
    re.I,
)
_WIDTH_RE = re.compile(r"\bwidth\s*=\s*[\"']([\d.]+)", re.I)
_HEIGHT_RE = re.compile(r"\bheight\s*=\s*[\"']([\d.]+)", re.I)


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            height = struct.unpack(">H", data[index + 3 : index + 5])[0]
            width = struct.unpack(">H", data[index + 5 : index + 7])[0]
            return width, height
        if marker in (0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9):
            continue
        if marker == 0xDA:
            break
        seg_len = struct.unpack(">H", data[index : index + 2])[0]
        index += seg_len
    return None


def _png_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    width = struct.unpack(">I", data[16:20])[0]
    height = struct.unpack(">I", data[20:24])[0]
    if width > 0 and height > 0:
        return width, height
    return None


def _gif_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 10 or data[:6] not in (b"GIF87a", b"GIF89a"):
        return None
    width, height = struct.unpack("<HH", data[6:10])
    return width, height


def _webp_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    chunk = data[12:16]
    if chunk == b"VP8 " and len(data) >= 30:
        width = struct.unpack("<H", data[26:28])[0] & 0x3FFF
        height = struct.unpack("<H", data[28:30])[0] & 0x3FFF
        return width, height
    if chunk == b"VP8L" and len(data) >= 25:
        bits = struct.unpack("<I", data[21:25])[0]
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return width, height
    if chunk == b"VP8X" and len(data) >= 30:
        width = 1 + struct.unpack("<I", data[24:27] + b"\x00")[0]
        height = 1 + struct.unpack("<I", data[27:30] + b"\x00")[0]
        return width, height
    return None


def raster_dimensions_from_bytes(data: bytes) -> tuple[int, int] | None:
    for probe in (_png_size, _jpeg_size, _gif_size, _webp_size):
        size = probe(data)
        if size:
            return size
    return None


def raster_dimensions(path: str | Path) -> tuple[int, int] | None:
    file_path = Path(path)
    if not file_path.is_file():
        return None
    with file_path.open("rb") as handle:
        head = handle.read(512 * 1024)
    return raster_dimensions_from_bytes(head)


def _parse_svg_length(raw: str) -> float | None:
    text = (raw or "").strip()
    if not text or text.endswith("%"):
        return None
    for suffix in ("px", "pt", "mm", "cm", "in"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    try:
        value = float(text)
    except ValueError:
        return None
    return value if value > 0 else None


def svg_dimensions_from_text(text: str) -> tuple[int, int] | None:
    snippet = (text or "")[:65536]
    if "<svg" not in snippet.lower():
        return None
    width = height = None
    w_match = _WIDTH_RE.search(snippet)
    h_match = _HEIGHT_RE.search(snippet)
    if w_match:
        width = _parse_svg_length(w_match.group(1))
    if h_match:
        height = _parse_svg_length(h_match.group(1))
    if width and height:
        return int(round(width)), int(round(height))
    vb = _VIEWBOX_RE.search(snippet)
    if vb:
        parts = vb.group(1).replace(",", " ").split()
        if len(parts) >= 4:
            try:
                vb_w = float(parts[2])
                vb_h = float(parts[3])
            except ValueError:
                vb_w = vb_h = 0.0
            if vb_w > 0 and vb_h > 0:
                return int(round(vb_w)), int(round(vb_h))
    return None


def svg_dimensions_from_bytes(data: bytes) -> tuple[int, int] | None:
    try:
        text = data.decode("utf-8", errors="ignore")
    except (UnicodeDecodeError, AttributeError):
        return None
    return svg_dimensions_from_text(text)


def image_dimensions_from_bytes(data: bytes) -> tuple[int, int] | None:
    size = raster_dimensions_from_bytes(data)
    if size:
        return size
    return svg_dimensions_from_bytes(data)


def image_dimensions(path: str | Path) -> tuple[int, int] | None:
    file_path = Path(path)
    if not file_path.is_file():
        return None
    suffix = file_path.suffix.lower()
    with file_path.open("rb") as handle:
        data = handle.read(512 * 1024)
    if suffix == ".svg":
        return svg_dimensions_from_bytes(data) or raster_dimensions_from_bytes(data)
    return image_dimensions_from_bytes(data)


_HERO_BUSY_URL_HINTS = re.compile(
    r"(?:screenshot|product[-_]?shot|browser[-_]?mock|ui[-_]?preview|"
    r"desktop[-_](?:dark|light)|mobile[-_](?:dark|light)|-dark\.webp|-light\.webp)",
    re.I,
)

_OG_MARKETING_HINTS = re.compile(
    r"(?:og[-_/]|opengraph|social|share|card|hero[-_]?static|not-x)",
    re.I,
)


def hero_url_looks_busy(url: str) -> bool:
    lower = (url or "").lower().split("?", 1)[0]
    return bool(_HERO_BUSY_URL_HINTS.search(lower))


def hero_dimensions_look_busy(width: int | None, height: int | None) -> bool:
    if not width or not height or width <= 0 or height <= 0:
        return False
    aspect = width / height
    if aspect >= 1.55 and width >= 1100 and height >= 650:
        return True
    if max(width, height) >= 2400 and aspect >= 1.25:
        return True
    return False


def classify_hero_candidate(
    url: str,
    *,
    width: int | None = None,
    height: int | None = None,
    source: str = "page",
) -> tuple[bool, str]:
    """Return (hero_busy, hero_image_kind)."""
    lower = (url or "").lower()
    if hero_url_looks_busy(url) or hero_dimensions_look_busy(width, height):
        return True, "ui-screenshot"
    if source in ("og", "twitter") or _OG_MARKETING_HINTS.search(lower):
        return False, "og-marketing"
    if width and height and width >= 800 and height >= 400:
        return False, "marketing"
    return False, "inline"
