"""Best-effort Communication Kit extraction from fetched HTML (MVP)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse


class _MetaCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title_parts: list[str] = []
        self.in_title = False
        self.meta: dict[str, str] = {}
        self.link_rels: list[tuple[str, str]] = []
        self.inline_styles: list[str] = []
        self.stylesheet_hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k.lower(): (v or "") for k, v in attrs}
        t = tag.lower()
        if t == "title":
            self.in_title = True
        elif t == "meta":
            name = (attr.get("name") or attr.get("property") or "").lower()
            content = attr.get("content", "").strip()
            if name and content:
                self.meta[name] = content
        elif t == "link":
            rel = attr.get("rel", "").lower()
            href = attr.get("href", "").strip()
            if href:
                self.link_rels.append((rel, href))
                if "stylesheet" in rel:
                    self.stylesheet_hrefs.append(href)
        elif t == "style":
            self.inline_styles.append("")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)


def _normalize_url(base: str, maybe_relative: str) -> str | None:
    if not maybe_relative or maybe_relative.startswith("data:"):
        return None
    return urljoin(base, maybe_relative)


def _hex_colors_from_text(text: str, limit: int = 8) -> list[str]:
    found: list[str] = []
    for match in re.findall(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b", text):
        if len(match) == 4:
            expanded = "#" + "".join(c * 2 for c in match[1:])
        else:
            expanded = match.lower()
        if expanded not in found:
            found.append(expanded)
        if len(found) >= limit:
            break
    return found


def _fonts_from_text(text: str, limit: int = 6) -> list[str]:
    fonts: list[str] = []
    for match in re.findall(
        r"font-family\s*:\s*([^;}{]+)", text, flags=re.IGNORECASE
    ):
        for part in match.split(","):
            name = part.strip().strip("'\"").strip()
            if not name or name.lower() in ("inherit", "sans-serif", "serif", "monospace"):
                continue
            if name not in fonts:
                fonts.append(name)
            if len(fonts) >= limit:
                return fonts
    google = re.findall(
        r"fonts\.googleapis\.com/css2?\?family=([^&\"']+)", text, flags=re.IGNORECASE
    )
    for chunk in google:
        for family in chunk.split("|"):
            decoded = family.replace("+", " ").split(":")[0].strip()
            if decoded and decoded not in fonts:
                fonts.append(decoded)
            if len(fonts) >= limit:
                return fonts
    return fonts


def _pick_logo(base_url: str, collector: _MetaCollector) -> str | None:
    og_image = collector.meta.get("og:image")
    if og_image:
        return _normalize_url(base_url, og_image)
    for rel, href in collector.link_rels:
        if "apple-touch-icon" in rel or rel == "icon" or "shortcut icon" in rel:
            return _normalize_url(base_url, href)
    return None


def _pick_site_name(collector: _MetaCollector) -> str:
    og_site = collector.meta.get("og:site_name", "").strip()
    if og_site:
        return og_site
    title = "".join(collector.title_parts).strip()
    if title:
        return re.sub(r"\s*[\|\-–—]\s*.*$", "", title).strip() or title
    return "Untitled site"


def scrape_kit_from_html(html: str, source_url: str) -> dict[str, Any]:
    """Return MVP Communication Kit fields from HTML string."""
    collector = _MetaCollector()
    try:
        collector.feed(html)
    except Exception:
        pass

    parsed = urlparse(source_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    colors: list[str] = []
    theme = collector.meta.get("theme-color", "").strip()
    if theme and theme.startswith("#"):
        colors.append(theme.lower())
    for key in ("msapplication-tilecolor", "og:color"):
        c = collector.meta.get(key, "").strip()
        if c.startswith("#") and c.lower() not in colors:
            colors.append(c.lower())
    for extra in _hex_colors_from_text(html):
        if extra not in colors:
            colors.append(extra)
        if len(colors) >= 8:
            break

    font_blob = html + "\n".join(collector.inline_styles)
    fonts = _fonts_from_text(font_blob)

    logo_url = _pick_logo(source_url, collector)

    return {
        "sourceUrl": source_url,
        "siteName": _pick_site_name(collector),
        "logoUrl": logo_url,
        "colors": colors[:8],
        "fonts": fonts[:6],
        "scrapedAt": datetime.now(timezone.utc).isoformat(),
    }


def validate_fetch_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must use http or https")
    if not parsed.netloc:
        raise ValueError("URL must include a host")
    return url.strip()
