"""Communication Kit extraction from fetched HTML + linked CSS (Pomelli-style MVP)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

MAX_STYLESHEETS = 6
MAX_STYLESHEET_BYTES = 400_000
MAX_INLINE_SVG_CHARS = 80_000
FETCH_TIMEOUT_SEC = 20

_GENERIC_FONTS = frozenset(
    {
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
    }
)

_LOGO_HINTS = re.compile(r"logo|brand|wordmark", re.I)
_LOGO_IMG_HINTS = re.compile(r"logo|brand|mark|wordmark", re.I)
_HEADER_TAGS = frozenset({"header", "nav"})
_SVG_UNSAFE = re.compile(
    r"<\s*(script|foreignobject|iframe|object|embed)\b", re.I
)
_SVG_EVENT_ATTR = re.compile(r"\s+on[a-z]+\s*=", re.I)
_WOFF_FAMILY = re.compile(
    r"/(?:static/)?media/([A-Za-z][A-Za-z0-9_-]+)\.[a-f0-9]+\.woff2",
    re.I,
)


class _PageCollector(HTMLParser):
    def __init__(self, page_url: str = "") -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.title_parts: list[str] = []
        self.in_title = False
        self.meta: dict[str, str] = {}
        self.link_rels: list[tuple[str, str]] = []
        self.stylesheet_hrefs: list[str] = []
        self.inline_css: list[str] = []
        self.h1_texts: list[str] = []
        self.images: list[dict[str, str]] = []
        self._tag_stack: list[str] = []
        self._in_style = False
        self._style_buf: list[str] = []
        self._in_header_nav_depth = 0
        self._logo_hint_depth = 0
        self._logo_hint_stack: list[bool] = []
        self._home_anchor_depth = 0
        self._svg_capture_depth = 0
        self._svg_buf: list[str] = []
        self._logo_svgs: list[str] = []
        self._current_img: dict[str, str] | None = None

    def _in_header_nav(self) -> bool:
        return self._in_header_nav_depth > 0

    def _in_logo_zone(self) -> bool:
        return (
            self._in_header_nav_depth > 0
            or self._logo_hint_depth > 0
            or self._home_anchor_depth > 0
        )

    def _logo_hint_from_attr(self, attr: dict[str, str]) -> bool:
        blob = " ".join(
            (
                attr.get("class", ""),
                attr.get("id", ""),
                attr.get("role", ""),
                attr.get("aria-label", ""),
            )
        )
        return bool(_LOGO_HINTS.search(blob))

    def _is_home_href(self, href: str) -> bool:
        if not href or href.startswith("#"):
            return False
        if href in ("/", "./"):
            return True
        if not self.page_url:
            return href.rstrip("/") in ("", "/")
        joined = urljoin(self.page_url, href)
        page = urlparse(self.page_url)
        target = urlparse(joined)
        if page.netloc and target.netloc != page.netloc:
            return False
        return target.path in ("", "/")

    def _finish_svg_capture(self) -> None:
        svg = "".join(self._svg_buf)
        cleaned = _sanitize_logo_svg(svg)
        if cleaned and len(cleaned) <= MAX_INLINE_SVG_CHARS:
            self._logo_svgs.append(cleaned)
        self._svg_buf = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        self._tag_stack.append(t)
        attr = {k.lower(): (v or "") for k, v in attrs}
        if t in _HEADER_TAGS:
            self._in_header_nav_depth += 1
        if t == "a" and self._is_home_href(attr.get("href", "").strip()):
            self._home_anchor_depth += 1
        bumped_logo = self._logo_hint_from_attr(attr)
        if bumped_logo:
            self._logo_hint_depth += 1
        self._logo_hint_stack.append(bumped_logo)
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
            self._in_style = True
            self._style_buf = []
        elif t == "h1":
            self.h1_texts.append("")
        elif t == "img":
            raw_src = (
                attr.get("src", "").strip()
                or attr.get("data-src", "").strip()
                or attr.get("data-lazy-src", "").strip()
            )
            if raw_src.startswith("//"):
                parsed_page = urlparse(self.page_url)
                raw_src = f"{parsed_page.scheme}:{raw_src}"
            src = raw_src
            self._current_img = {
                "src": src,
                "alt": attr.get("alt", "").strip(),
                "class": attr.get("class", "").strip(),
                "title": attr.get("title", "").strip(),
                "width": attr.get("width", "").strip(),
                "height": attr.get("height", "").strip(),
                "in_header": "1" if self._in_logo_zone() else "0",
            }
        elif t == "picture":
            pass
        elif t == "source" and attr.get("srcset"):
            srcset = attr.get("srcset", "").strip()
            first = _first_srcset_url(srcset)
            if first:
                self.images.append(
                    {
                        "src": first,
                        "alt": "",
                        "class": "picture-srcset",
                        "width": "",
                        "height": "",
                        "in_header": "1" if self._in_logo_zone() else "0",
                    }
                )
        elif t == "svg" and self._in_logo_zone():
            if self._svg_capture_depth == 0:
                self._svg_buf = []
            self._svg_capture_depth += 1
            self._svg_buf.append(self.get_starttag_text() or "<svg>")
        elif self._svg_capture_depth > 0:
            self._svg_buf.append(self.get_starttag_text() or f"<{t}>")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t == "title":
            self.in_title = False
        elif t == "style" and self._in_style:
            self._in_style = False
            self.inline_css.append("".join(self._style_buf))
            self._style_buf = []
        elif t == "img" and self._current_img:
            if self._current_img.get("src"):
                self.images.append(self._current_img)
            self._current_img = None
        if self._svg_capture_depth > 0:
            self._svg_buf.append(f"</{t}>")
            if t == "svg":
                self._svg_capture_depth -= 1
                if self._svg_capture_depth == 0:
                    self._finish_svg_capture()
        if t in _HEADER_TAGS and self._in_header_nav_depth > 0:
            self._in_header_nav_depth -= 1
        if t == "a" and self._home_anchor_depth > 0:
            self._home_anchor_depth -= 1
        if self._logo_hint_stack:
            if self._logo_hint_stack.pop() and self._logo_hint_depth > 0:
                self._logo_hint_depth -= 1
        if self._tag_stack and self._tag_stack[-1] == t:
            self._tag_stack.pop()

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
        if self._in_style:
            self._style_buf.append(data)
        if self._svg_capture_depth > 0:
            self._svg_buf.append(data)
        if self.h1_texts and self._tag_stack and self._tag_stack[-1] == "h1":
            self.h1_texts[-1] += data

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._svg_capture_depth > 0:
            self._svg_buf.append(self.get_starttag_text() or f"<{tag} />")
            return
        if tag.lower() == "img":
            self.handle_starttag(tag, attrs)
            self.handle_endtag(tag)


def _sanitize_logo_svg(svg: str) -> str | None:
    text = (svg or "").strip()
    if not text.lower().startswith("<svg"):
        return None
    if _SVG_UNSAFE.search(text):
        return None
    if _SVG_EVENT_ATTR.search(text):
        text = _SVG_EVENT_ATTR.sub(" ", text)
    if "</svg>" not in text.lower():
        return None
    return text


def _fonts_from_asset_urls(text: str, limit: int = 6) -> list[str]:
    fonts: list[str] = []
    for match in _WOFF_FAMILY.findall(text):
        name = match.replace("-", " ").strip()
        if name and name.lower() not in _GENERIC_FONTS and name not in fonts:
            fonts.append(name)
        if len(fonts) >= limit:
            break
    return fonts


def _display_fonts(
    fonts: list[str],
    google_fonts: list[dict[str, Any]],
    font_blob: str,
    *,
    has_copy: bool,
) -> list[str]:
    if fonts:
        return fonts
    from_google = [
        str(g.get("family", "")).strip()
        for g in google_fonts
        if g.get("family")
    ]
    if from_google:
        return from_google[:6]
    from_assets = _fonts_from_asset_urls(font_blob)
    if from_assets:
        return from_assets
    if has_copy:
        return ["system-ui", "sans-serif"]
    return []


def _first_srcset_url(srcset: str) -> str | None:
    for part in srcset.split(","):
        chunk = part.strip().split()
        if chunk:
            return chunk[0].strip()
    return None


def _normalize_url(base: str, maybe_relative: str) -> str | None:
    if not maybe_relative or maybe_relative.startswith(("data:", "javascript:", "blob:")):
        return None
    joined = urljoin(base, maybe_relative)
    parsed = urlparse(joined)
    if parsed.scheme not in ("http", "https"):
        return None
    return joined


def _same_origin(page_url: str, asset_url: str) -> bool:
    p = urlparse(page_url)
    a = urlparse(asset_url)
    return p.scheme == a.scheme and p.netloc == a.netloc


def _hex_colors_from_text(text: str, limit: int = 24) -> list[str]:
    found: list[str] = []
    for match in re.findall(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b", text):
        expanded = _expand_hex(match)
        if expanded and expanded not in found:
            found.append(expanded)
        if len(found) >= limit:
            break
    return found


def _expand_hex(value: str) -> str | None:
    if not value.startswith("#"):
        return None
    if len(value) == 4:
        return "#" + "".join(c * 2 for c in value[1:]).lower()
    if len(value) == 7:
        return value.lower()
    return None


def _rgb_like_to_hex(value: str) -> str | None:
    value = value.strip()
    hexed = _expand_hex(value)
    if hexed:
        return hexed
    m = re.match(
        r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)",
        value,
        flags=re.I,
    )
    if m:
        r, g, b = (min(255, int(m.group(i))) for i in (1, 2, 3))
        return f"#{r:02x}{g:02x}{b:02x}"
    return None


def _css_variables(text: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for name, raw in re.findall(
        r"--([a-zA-Z0-9_-]+)\s*:\s*([^;}{]+)", text, flags=re.MULTILINE
    ):
        val = raw.strip()
        if val:
            pairs.append((name.lower(), val))
    return pairs


def _rank_css_var(name: str) -> int:
    if any(k in name for k in ("primary", "brand", "main", "accent")):
        return 0
    if "secondary" in name:
        return 1
    if any(k in name for k in ("highlight", "cta", "button")):
        return 2
    if "color" in name:
        return 3
    return 4


def _colors_from_css(text: str) -> list[str]:
    ordered: list[str] = []
    for name, raw in sorted(_css_variables(text), key=lambda p: _rank_css_var(p[0])):
        for token in re.split(r"\s+", raw):
            hexed = _rgb_like_to_hex(token.strip())
            if hexed and hexed not in ordered:
                ordered.append(hexed)
        hexed = _rgb_like_to_hex(raw)
        if hexed and hexed not in ordered:
            ordered.append(hexed)
    for prop in ("background-color", "background", "color", "border-color", "fill"):
        for match in re.findall(
            rf"{prop}\s*:\s*([^;}}{{]+)", text, flags=re.IGNORECASE
        ):
            for part in match.split():
                hexed = _rgb_like_to_hex(part.strip().rstrip(","))
                if hexed and hexed not in ordered:
                    ordered.append(hexed)
    for extra in _hex_colors_from_text(text, limit=16):
        if extra not in ordered:
            ordered.append(extra)
    return ordered


def _fonts_from_text(text: str, limit: int = 8) -> list[str]:
    fonts: list[str] = []
    for match in re.findall(
        r"font-family\s*:\s*([^;}{]+)", text, flags=re.IGNORECASE
    ):
        for part in match.split(","):
            name = part.strip().strip("'\"").strip()
            if not name or name.lower() in _GENERIC_FONTS:
                continue
            if name.startswith("var(") or "var(--" in name:
                continue
            if name not in fonts:
                fonts.append(name)
            if len(fonts) >= limit:
                return fonts
    for chunk in re.findall(
        r"fonts\.googleapis\.com/css2?\?family=([^&\"']+)", text, flags=re.IGNORECASE
    ):
        for family in chunk.split("|"):
            decoded = family.replace("+", " ").split(":")[0].strip()
            if decoded and decoded.lower() not in _GENERIC_FONTS and decoded not in fonts:
                fonts.append(decoded)
            if len(fonts) >= limit:
                return fonts
    return fonts


def _parse_pixel_hint(value: str) -> int:
    try:
        return int(re.sub(r"\D", "", value or "") or "0")
    except ValueError:
        return 0


def _img_dimensions(img: dict[str, str]) -> tuple[int, int]:
    return _parse_pixel_hint(img.get("width", "")), _parse_pixel_hint(img.get("height", ""))


def _hero_candidate_large_enough(img: dict[str, str], min_px: int = 100) -> bool:
    w, h = _img_dimensions(img)
    if w > 0 and h > 0:
        return max(w, h) >= min_px
    return True


def _img_area(img: dict[str, str]) -> int:
    w, h = _img_dimensions(img)
    if w > 0 and h > 0:
        if max(w, h) < 100:
            return 0
        return w * h
    return 400 * 300


def _meta_hero_dimensions(collector: _PageCollector) -> tuple[int | None, int | None]:
    w = _parse_pixel_hint(collector.meta.get("og:image:width", ""))
    h = _parse_pixel_hint(collector.meta.get("og:image:height", ""))
    if w > 0 and h > 0:
        return w, h
    return None, None


def _pick_hero_url(base_url: str, collector: _PageCollector) -> str | None:
    for key in ("og:image", "og:image:url", "twitter:image", "twitter:image:src"):
        url = collector.meta.get(key, "").strip()
        if url:
            normalized = _normalize_url(base_url, url)
            if normalized:
                return normalized
    above_fold = collector.images[:20]
    best: tuple[int, str] | None = None
    for img in above_fold:
        src = img.get("src", "")
        if not src:
            continue
        if not _hero_candidate_large_enough(img):
            continue
        blob = " ".join((img.get("alt", ""), img.get("class", ""), src)).lower()
        if _LOGO_IMG_HINTS.search(blob) and img.get("in_header") == "1":
            continue
        area = _img_area(img)
        if area <= 0:
            continue
        if best is None or area > best[0]:
            normalized = _normalize_url(base_url, src)
            if normalized:
                best = (area, normalized)
    return best[1] if best else None


def _google_fonts_from_blob(text: str) -> list[dict[str, Any]]:
    from font_fetcher import parse_google_font_links

    return parse_google_font_links(text)


def _pick_favicon_url(base_url: str, collector: _PageCollector) -> str | None:
    icon_candidates: list[str] = []
    for rel, href in collector.link_rels:
        rel_l = rel.lower()
        if any(
            token in rel_l
            for token in ("icon", "apple-touch-icon", "mask-icon", "shortcut icon")
        ):
            normalized = _normalize_url(base_url, href)
            if normalized:
                icon_candidates.append(normalized)
    if not icon_candidates:
        return None
    for url in icon_candidates:
        if "apple-touch" in url.lower():
            return url
    for url in icon_candidates:
        if url.lower().endswith(".png"):
            return url
    return icon_candidates[0]


def _pick_logo_img_url(base_url: str, collector: _PageCollector) -> str | None:
    for img in collector.images:
        if img.get("in_header") != "1":
            continue
        src = img.get("src", "")
        if not src:
            continue
        blob = " ".join(
            (
                img.get("alt", ""),
                img.get("title", ""),
                img.get("class", ""),
                src,
            )
        )
        if not _LOGO_IMG_HINTS.search(blob):
            continue
        normalized = _normalize_url(base_url, src)
        if normalized:
            return normalized
    for img in collector.images:
        if img.get("in_header") != "1":
            continue
        src = img.get("src", "")
        if src.lower().split("?", 1)[0].endswith(".svg"):
            normalized = _normalize_url(base_url, src)
            if normalized:
                return normalized
    for rel, href in collector.link_rels:
        rel_l = rel.lower()
        if "image_src" in rel_l or "logo" in rel_l:
            normalized = _normalize_url(base_url, href)
            if normalized:
                return normalized
    return None


def _pick_logo_svg(collector: _PageCollector) -> str | None:
    for svg in collector._logo_svgs:
        if _LOGO_HINTS.search(svg) or len(collector._logo_svgs) == 1:
            return svg.strip()
    return collector._logo_svgs[0].strip() if collector._logo_svgs else None


def _resolve_logo_fields(
    base_url: str, collector: _PageCollector
) -> tuple[str | None, str | None, str | None, str | None]:
    """Return logoSvg, logoUrl, logoSource, faviconUrl (never og:image)."""
    logo_svg = _pick_logo_svg(collector)
    if logo_svg:
        return logo_svg, None, "inline-svg", _pick_favicon_url(base_url, collector)
    logo_url = _pick_logo_img_url(base_url, collector)
    if logo_url:
        return None, logo_url, "img", _pick_favicon_url(base_url, collector)
    favicon = _pick_favicon_url(base_url, collector)
    if favicon:
        return None, favicon, "favicon", favicon
    return None, None, None, None


def _pick_site_name(collector: _PageCollector) -> str:
    og_site = collector.meta.get("og:site_name", "").strip()
    if og_site:
        return og_site
    title = "".join(collector.title_parts).strip()
    if title:
        return re.sub(r"\s*[\|\-–—]\s*.*$", "", title).strip() or title
    return "Untitled site"


def _pick_headline(collector: _PageCollector) -> str:
    og_title = collector.meta.get("og:title", "").strip()
    if og_title:
        return og_title
    for h1 in collector.h1_texts:
        text = re.sub(r"\s+", " ", h1).strip()
        if text:
            return text
    title = "".join(collector.title_parts).strip()
    return title


def _pick_tagline(collector: _PageCollector) -> str:
    desc = collector.meta.get("description", "").strip()
    if desc:
        return desc
    return collector.meta.get("og:description", "").strip()


def _merge_colors(
    theme: str | None, meta_colors: list[str], css_colors: list[str], html: str
) -> tuple[list[str], list[str]]:
    primary_secondary: list[str] = []
    accent: list[str] = []

    def add_primary(c: str) -> None:
        if c and c not in primary_secondary:
            primary_secondary.append(c)

    def add_accent(c: str) -> None:
        if c and c not in accent and c not in primary_secondary:
            accent.append(c)

    if theme:
        add_primary(theme)
    for c in meta_colors:
        add_primary(c)
    for c in css_colors:
        if len(primary_secondary) < 2:
            add_primary(c)
        else:
            add_accent(c)
    for c in _hex_colors_from_text(html, limit=12):
        if len(primary_secondary) < 2:
            add_primary(c)
        else:
            add_accent(c)
    return primary_secondary, accent


def fetch_stylesheet_bundle(
    page_url: str,
    hrefs: list[str],
    *,
    fetcher: Callable[[str], bytes] | None = None,
) -> str:
    """Fetch same-origin or absolute stylesheet URLs; return concatenated CSS text."""
    parsed = urlparse(page_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    chunks: list[str] = []
    seen: set[str] = set()

    def default_fetch(url: str) -> bytes:
        req = Request(
            url,
            headers={
                "User-Agent": "CommMaker-KitScraper/0.2 (+https://github.com/asseukihuh/AI-WebApp)",
                "Accept": "text/css,*/*",
            },
            method="GET",
        )
        with urlopen(req, timeout=FETCH_TIMEOUT_SEC) as resp:
            return resp.read(MAX_STYLESHEET_BYTES + 1)

    get_bytes = fetcher or default_fetch

    for href in hrefs:
        if len(chunks) >= MAX_STYLESHEETS:
            break
        resolved = _normalize_url(base, href) or _normalize_url(page_url, href)
        if not resolved or resolved in seen:
            continue
        if href.strip().startswith("//"):
            resolved = f"{parsed.scheme}:{href.strip()}"
        is_absolute = resolved.startswith(("http://", "https://"))
        if not is_absolute:
            continue
        if not (href.strip().startswith(("http://", "https://", "//")) or _same_origin(page_url, resolved)):
            continue
        seen.add(resolved)
        try:
            data = get_bytes(resolved)
        except Exception:
            continue
        if len(data) > MAX_STYLESHEET_BYTES:
            data = data[:MAX_STYLESHEET_BYTES]
        chunks.append(data.decode("utf-8", errors="replace"))
    return "\n".join(chunks)


def scrape_kit_from_html(
    html: str,
    source_url: str,
    *,
    stylesheet_text: str = "",
) -> dict[str, Any]:
    """Return Communication Kit fields from HTML (+ optional linked CSS)."""
    collector = _PageCollector(page_url=source_url)
    try:
        collector.feed(html)
    except Exception:
        pass

    headline = _pick_headline(collector)
    tagline = _pick_tagline(collector)

    css_blob = "\n".join(collector.inline_css + [stylesheet_text])
    meta_hex: list[str] = []
    for key in ("theme-color", "msapplication-tilecolor", "og:color"):
        c = collector.meta.get(key, "").strip()
        hexed = _rgb_like_to_hex(c)
        if hexed:
            meta_hex.append(hexed)

    theme = meta_hex[0] if meta_hex else None
    css_colors = _colors_from_css(css_blob)
    primary_secondary, accent = _merge_colors(theme, meta_hex[1:], css_colors, html)
    colors = (primary_secondary + accent)[:8]
    accent_colors = accent[:6]

    font_blob = html + "\n" + css_blob
    fonts = _fonts_from_text(font_blob)
    google_fonts = _google_fonts_from_blob(font_blob)
    has_copy = bool(headline or tagline or collector.h1_texts)
    fonts = _display_fonts(
        fonts,
        google_fonts,
        font_blob,
        has_copy=has_copy,
    )

    logo_svg, logo_url, logo_source, favicon_url = _resolve_logo_fields(
        source_url, collector
    )
    hero_url = _pick_hero_url(source_url, collector)

    kit: dict[str, Any] = {
        "sourceUrl": source_url,
        "siteName": _pick_site_name(collector),
        "logoUrl": logo_url,
        "colors": colors,
        "fonts": fonts[:6],
        "scrapedAt": datetime.now(timezone.utc).isoformat(),
    }
    if hero_url:
        kit["heroImageUrl"] = hero_url
        hero_w, hero_h = _meta_hero_dimensions(collector)
        if hero_w and hero_h:
            kit["heroWidth"] = hero_w
            kit["heroHeight"] = hero_h
    if logo_svg:
        kit["logoSvg"] = logo_svg
    if logo_source:
        kit["logoSource"] = logo_source
    if favicon_url:
        kit["faviconUrl"] = favicon_url
    if tagline:
        kit["tagline"] = tagline
    if headline:
        kit["headline"] = headline
    if accent_colors:
        kit["accentColors"] = accent_colors
    if google_fonts:
        kit["googleFonts"] = google_fonts[:8]
    return kit


def scrape_kit_from_page(
    html: str,
    source_url: str,
    *,
    fetcher: Callable[[str], bytes] | None = None,
) -> dict[str, Any]:
    """Parse HTML and fetch linked stylesheets before building the kit."""
    collector = _PageCollector(page_url=source_url)
    try:
        collector.feed(html)
    except Exception:
        pass
    css = fetch_stylesheet_bundle(
        source_url, collector.stylesheet_hrefs, fetcher=fetcher
    )
    return scrape_kit_from_html(html, source_url, stylesheet_text=css)


def validate_fetch_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must use http or https")
    if not parsed.netloc:
        raise ValueError("URL must include a host")
    return url.strip()
