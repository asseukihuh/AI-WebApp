"""Download Google Fonts CSS + WOFF2 for poster generation (best-effort)."""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any, Callable
from urllib.parse import quote, unquote_plus, urlparse

MAX_FONT_CSS_BYTES = 200_000
MAX_WOFF2_BYTES = 2_000_000
DEFAULT_HEADLINE = "Inter"
DEFAULT_BODY = "Inter"

_DISPLAY_HINTS = re.compile(
    r"\b(display|condensed|slab|serif|garamond|playfair|merriweather|"
    r"cormorant|fraunces|bebas|oswald|anton|lobster)\b",
    re.I,
)


def _is_generic_font(name: str) -> bool:
    generic = {
        "inherit",
        "initial",
        "unset",
        "sans-serif",
        "serif",
        "monospace",
        "system-ui",
        "ui-sans-serif",
        "ui-serif",
        "ui-monospace",
        "cursive",
        "fantasy",
        "-apple-system",
        "blinkmacsystemfont",
        "segoe ui",
        "helvetica",
        "arial",
        "noto sans",
        "liberation sans",
        "inter",
    }
    return name.strip().lower() in generic


def parse_google_font_families_from_url(css_url: str) -> tuple[str, list[str]]:
    """Extract family name and weight tokens from a Google Fonts CSS URL."""
    family = ""
    weights: list[str] = []
    if "family=" not in css_url:
        return family, weights
    query = css_url.split("?", 1)[-1]
    for part in query.split("&"):
        if not part.startswith("family="):
            continue
        raw = unquote_plus(part[7:])
        for chunk in raw.split("|"):
            if ":" in chunk:
                name, rest = chunk.split(":", 1)
                family = name.replace("+", " ").strip()
                for token in rest.split(","):
                    token = token.strip()
                    if token.isdigit():
                        weights.append(token)
                    elif token.startswith("wght@"):
                        for w in re.findall(r"\d+", token):
                            weights.append(w)
            else:
                family = chunk.replace("+", " ").strip()
    weights = sorted(set(weights), key=int) if weights else ["400"]
    return family, weights


def parse_google_font_links(text: str) -> list[dict[str, Any]]:
    """Find fonts.googleapis.com stylesheet links and return structured entries."""
    seen: set[str] = set()
    entries: list[dict[str, Any]] = []
    for match in re.finditer(
        r"https?://fonts\.googleapis\.com/css2?[^\"'\s)>]+",
        text,
        flags=re.IGNORECASE,
    ):
        css_url = match.group(0).rstrip("'\"")
        family, weights = parse_google_font_families_from_url(css_url)
        if not family:
            continue
        key = family.casefold()
        if key in seen:
            continue
        seen.add(key)
        entries.append(
            {
                "family": family,
                "weights": weights or ["400"],
                "cssUrl": css_url,
            }
        )
    for chunk in re.findall(
        r"fonts\.googleapis\.com/css2?\?family=([^&\"']+)", text, flags=re.IGNORECASE
    ):
        for part in chunk.split("|"):
            if ":" in part:
                name, rest = part.split(":", 1)
                family = name.replace("+", " ").strip()
                weights = [w for w in re.findall(r"\d+", rest)]
            else:
                family = part.replace("+", " ").strip()
                weights = ["400"]
            if not family:
                continue
            key = family.casefold()
            if key in seen:
                continue
            seen.add(key)
            css_url = (
                "https://fonts.googleapis.com/css2?family="
                + quote(family.replace(" ", "+"))
                + (":wght@" + ";".join(weights) if len(weights) > 1 else "")
            )
            entries.append(
                {
                    "family": family,
                    "weights": weights or ["400"],
                    "cssUrl": css_url,
                }
            )
    return entries


def _woff2_urls_from_css(css_text: str) -> list[str]:
    urls: list[str] = []
    for match in re.finditer(r"url\(([^)]+)\)\s*format\(['\"]woff2['\"]\)", css_text):
        raw = match.group(1).strip().strip("'\"")
        if raw:
            urls.append(raw)
    if not urls:
        for match in re.finditer(r"url\(([^)]+\.woff2[^)]*)\)", css_text, flags=re.I):
            raw = match.group(1).strip().strip("'\"")
            if raw:
                urls.append(raw)
    return urls


def _safe_font_filename(family: str, weight: str, digest: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", family.lower()).strip("-") or "font"
    return f"{slug}-{weight}-{digest[:10]}.woff2"


def cache_google_fonts(
    google_fonts: list[dict[str, Any]],
    fonts_dir: str,
    *,
    fetcher: Callable[[str], bytes],
) -> dict[str, list[str]]:
    """Download WOFF2 files per family; return family → relative paths under fonts_dir."""
    os.makedirs(fonts_dir, exist_ok=True)
    cached: dict[str, list[str]] = {}
    for entry in google_fonts:
        family = str(entry.get("family") or "").strip()
        css_url = str(entry.get("cssUrl") or "").strip()
        if not family or not css_url:
            continue
        try:
            css_bytes = fetcher(css_url)
        except Exception:
            continue
        if len(css_bytes) > MAX_FONT_CSS_BYTES:
            css_bytes = css_bytes[:MAX_FONT_CSS_BYTES]
        css_text = css_bytes.decode("utf-8", errors="replace")
        paths: list[str] = []
        for woff_url in _woff2_urls_from_css(css_text):
            if woff_url.startswith("//"):
                woff_url = "https:" + woff_url
            elif woff_url.startswith("/"):
                woff_url = "https://fonts.gstatic.com" + woff_url
            digest = hashlib.sha256(woff_url.encode("utf-8")).hexdigest()
            weight_match = re.search(r":wght@(\d+)", woff_url) or re.search(
                r"/(\d{3})/", woff_url
            )
            weight = weight_match.group(1) if weight_match else "400"
            fname = _safe_font_filename(family, weight, digest)
            abs_path = os.path.join(fonts_dir, fname)
            if not os.path.isfile(abs_path):
                try:
                    data = fetcher(woff_url)
                except Exception:
                    continue
                if len(data) > MAX_WOFF2_BYTES:
                    continue
                with open(abs_path, "wb") as handle:
                    handle.write(data)
            paths.append(fname)
        if paths:
            cached[family] = paths
    return cached


def _kit_font_list(kit: dict[str, Any] | None) -> list[str]:
    names: list[str] = []
    for raw in (kit or {}).get("fonts") or []:
        name = str(raw).strip()
        if name and not _is_generic_font(name) and name not in names:
            names.append(name)
    for entry in (kit or {}).get("googleFonts") or []:
        if isinstance(entry, dict):
            family = str(entry.get("family") or "").strip()
            if family and not _is_generic_font(family) and family not in names:
                names.append(family)
    return names


def pick_headline_font(kit: dict[str, Any] | None) -> str:
    fonts = _kit_font_list(kit)
    if not fonts:
        return DEFAULT_HEADLINE
    if len(fonts) == 1:
        return fonts[0]
    display = [f for f in fonts if _DISPLAY_HINTS.search(f)]
    if display:
        return display[0]
    return fonts[0]


def pick_body_font(kit: dict[str, Any] | None) -> str:
    fonts = _kit_font_list(kit)
    headline = pick_headline_font(kit)
    for name in fonts:
        if name.casefold() != headline.casefold():
            return name
    if fonts:
        return fonts[0]
    return DEFAULT_BODY


def headline_font_style(kit: dict[str, Any] | None, headline_family: str) -> str | None:
    for entry in (kit or {}).get("googleFonts") or []:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("family") or "").casefold() != headline_family.casefold():
            continue
        weights = [str(w) for w in entry.get("weights") or []]
        if any(w in ("700", "800", "900") for w in weights):
            return "bold"
    return None


def resolve_poster_fonts(
    kit: dict[str, Any] | None,
    repo_root: str,
    *,
    fetcher: Callable[[str], bytes] | None = None,
) -> dict[str, Any]:
    """Resolve headline/body families and optionally cache WOFF2 under generated/fonts/."""
    kit = kit or {}
    headline = pick_headline_font(kit)
    body = pick_body_font(kit)
    notes: list[str] = []
    google_fonts = kit.get("googleFonts") or []
    if not isinstance(google_fonts, list):
        google_fonts = []

    fonts_dir = os.path.join(repo_root, "generated", "fonts")
    cached: dict[str, list[str]] = {}
    if google_fonts and fetcher:
        cached = cache_google_fonts(google_fonts, fonts_dir, fetcher=fetcher)
        if cached:
            notes.append(
                f"Cached {sum(len(v) for v in cached.values())} WOFF2 file(s) under generated/fonts/."
            )
        else:
            notes.append("Google Fonts CSS fetched but no WOFF2 files were cached.")
    elif google_fonts:
        notes.append("No fetcher; googleFonts metadata only.")

    if cached:
        notes.append(
            "PhotoCraft CLI v0.9 may not load custom WOFF2 paths yet; using PostScript family names."
        )
    elif headline == body:
        notes.append("Single kit font used for headline and body.")
    else:
        notes.append("Headline and body use distinct kit font families.")

    style = headline_font_style(kit, headline)
    result: dict[str, Any] = {
        "headline": headline,
        "body": body,
        "note": " ".join(notes),
    }
    if style:
        result["headlineStyle"] = style
    if cached:
        result["woff2"] = {
            family: [f"generated/fonts/{name}" for name in paths]
            for family, paths in cached.items()
        }
    return result
