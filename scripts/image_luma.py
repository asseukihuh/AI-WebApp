"""Downsampled RGB grid of a raster for background luminance sampling (no hard dependencies).

Uses Pillow when installed; otherwise decodes 8-bit non-interlaced PNGs in pure Python.
Returns ``None`` for formats it can't read so callers fall back to conservative assumptions.
"""

from __future__ import annotations

import os
import struct
import zlib
from typing import Any

GRID_W = 64
MAX_DECODE_PIXELS = 6_000_000


def _grid_from_pillow(path: str, grid_w: int) -> dict[str, Any] | None:
    try:
        from PIL import Image  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        with Image.open(path) as img:
            src_w, src_h = img.size
            grid_h = max(1, round(grid_w * src_h / src_w))
            small = img.convert("RGB").resize((grid_w, grid_h))
            pixels = [tuple(p) for p in small.getdata()]
    except (OSError, ValueError):
        return None
    return {"w": grid_w, "h": grid_h, "src_w": src_w, "src_h": src_h, "pixels": pixels}


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _grid_from_png(path: str, grid_w: int) -> dict[str, Any] | None:
    with open(path, "rb") as handle:
        data = handle.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos = 8
    width = height = bit_depth = color_type = interlace = 0
    idat = bytearray()
    palette: list[tuple[int, int, int]] = []
    while pos + 8 <= len(data):
        length, ctype = struct.unpack(">I4s", data[pos : pos + 8])
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            width, height, bit_depth, color_type, _c, _f, interlace = struct.unpack(">IIBBBBB", chunk)
        elif ctype == b"PLTE":
            palette = [tuple(chunk[i : i + 3]) for i in range(0, len(chunk), 3)]  # type: ignore[misc]
        elif ctype == b"IDAT":
            idat.extend(chunk)
        elif ctype == b"IEND":
            break
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if not width or not height or bit_depth != 8 or interlace or channels is None:
        return None
    if width * height > MAX_DECODE_PIXELS:
        return None
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    grid_h = max(1, round(grid_w * height / width))
    wanted_rows = {min(height - 1, int((gy + 0.5) * height / grid_h)): gy for gy in range(grid_h)}
    sample_cols = [min(width - 1, int((gx + 0.5) * width / grid_w)) for gx in range(grid_w)]
    pixels: list[tuple[int, int, int]] = [(0, 0, 0)] * (grid_w * grid_h)
    prev = bytearray(stride)
    offset = 0
    bpp = channels
    for y in range(height):
        ftype = raw[offset]
        row = bytearray(raw[offset + 1 : offset + 1 + stride])
        offset += 1 + stride
        if ftype == 1:
            for i in range(bpp, stride):
                row[i] = (row[i] + row[i - bpp]) & 0xFF
        elif ftype == 2:
            row = bytearray((a + b) & 0xFF for a, b in zip(row, prev))
        elif ftype == 3:
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                up_left = prev[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + _paeth(left, prev[i], up_left)) & 0xFF
        if y in wanted_rows:
            gy = wanted_rows[y]
            for gx, x in enumerate(sample_cols):
                base = x * channels
                if color_type == 3:
                    rgb = palette[row[base]] if row[base] < len(palette) else (0, 0, 0)
                elif channels >= 3:
                    rgb = (row[base], row[base + 1], row[base + 2])
                else:
                    rgb = (row[base],) * 3
                pixels[gy * grid_w + gx] = rgb  # type: ignore[assignment]
        prev = row
    return {"w": grid_w, "h": grid_h, "src_w": width, "src_h": height, "pixels": pixels}


def load_rgb_grid(path: str | None, grid_w: int = GRID_W) -> dict[str, Any] | None:
    """``{"w", "h", "src_w", "src_h", "pixels": [(r, g, b), …]}`` or ``None``."""
    if not path or not os.path.isfile(path):
        return None
    grid = _grid_from_pillow(path, grid_w)
    if grid is not None:
        return grid
    try:
        return _grid_from_png(path, grid_w)
    except (OSError, ValueError, zlib.error, struct.error, IndexError):
        return None
