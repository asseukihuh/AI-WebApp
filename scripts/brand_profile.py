"""Hybrid AI + vision Brand Profile (Pomelli-style Business Profile).

Pipeline: rendered capture (Playwright screenshots + computed-style DOM signals)
→ procedural candidates (exact hex / font / logo values) → Claude vision picks,
ranks and interprets → reconcile AI picks back onto the procedural ground truth.

Procedural signals stay authoritative for exact values; the model only chooses
between candidates (or flags a colour that exists only in pixels).
"""

from __future__ import annotations

import base64
import colorsys
import io
import json
import math
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse

from creative_brief import (
    ANTHROPIC_API_BASE,
    OPENAI_API_BASE,
    OPENROUTER_API_BASE,
    _anthropic_request_headers,
    _safe_error_detail,
    _truncate,
    api_key_for_provider,
    resolve_llm_model,
    resolve_llm_provider,
)

PROFILE_VERSION = 1
CACHE_TTL_SEC = 7 * 24 * 3600
VISION_TIMEOUT_SEC = 120
VISION_MAX_TOKENS = 2400
CAPTURE_TIMEOUT_MS = 30_000
DESKTOP_VIEWPORT = {"width": 1440, "height": 900}
MOBILE_VIEWPORT = {"width": 390, "height": 844}
FULL_PAGE_MAX_HEIGHT = 5400
VISION_MAX_EDGE = 1568
MAX_LOGO_SVG_CHARS = 80_000
SNAP_DELTA_E = 14.0

# Sonnet-class list price (USD / million tokens); override for accounting.
DEFAULT_PRICE_IN_PER_MTOK = 3.0
DEFAULT_PRICE_OUT_PER_MTOK = 15.0

PALETTE_ROLES = ("background", "surface", "primary", "secondary", "accent", "text")
REQUIRED_PALETTE_ROLES = ("background", "primary", "accent", "text")
IMAGERY_MEDIA = (
    "photography",
    "illustration",
    "3d-render",
    "gradients",
    "abstract-shapes",
    "product-ui",
    "typographic",
    "mixed",
)

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36 CommMaker-BrandProfile/0.1"
)


def _str() -> dict[str, Any]:
    return {"type": "string"}


def _str_list() -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}}


def _strict_object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties.keys()),
    }


_FONT_ROLE_SCHEMA = _strict_object(
    {
        "family": _str(),
        "candidateId": _str(),
        "weights": {"type": "array", "items": {"type": "integer"}},
        "usage": _str(),
    }
)

BRAND_PROFILE_JSON_SCHEMA: dict[str, Any] = _strict_object(
    {
        "name": _str(),
        "tagline": _str(),
        "businessOverview": _str(),
        "brandValues": _str_list(),
        "aesthetic": _str_list(),
        "toneOfVoice": _str_list(),
        "keywords": _str_list(),
        "palette": {
            "type": "array",
            "items": _strict_object(
                {
                    "role": {"type": "string", "enum": list(PALETTE_ROLES)},
                    "hex": _str(),
                    "candidateId": _str(),
                    "name": _str(),
                    "usage": _str(),
                }
            ),
        },
        "typography": _strict_object(
            {"display": _FONT_ROLE_SCHEMA, "body": _FONT_ROLE_SCHEMA}
        ),
        "logo": _strict_object(
            {
                "candidateId": _str(),
                "backdropHex": _str(),
                "variant": {
                    "type": "string",
                    "enum": [
                        "full-color",
                        "dark-on-light",
                        "light-on-dark",
                        "monochrome",
                    ],
                },
                "notes": _str(),
            }
        ),
        "imageryStyle": _strict_object(
            {
                "primaryMedium": {"type": "string", "enum": list(IMAGERY_MEDIA)},
                "secondaryMedia": _str_list(),
                "motifs": _str_list(),
                "colorTreatment": _str(),
                "ideogramPrompt": _str(),
                "avoid": _str_list(),
            }
        ),
        "layoutTraits": _strict_object(
            {
                "density": {"type": "string", "enum": ["airy", "balanced", "dense"]},
                "cornerRadius": {
                    "type": "string",
                    "enum": ["sharp", "subtle", "rounded", "pill"],
                },
                "whitespace": {
                    "type": "string",
                    "enum": ["generous", "moderate", "tight"],
                },
                "composition": _str(),
            }
        ),
        "doNots": _str_list(),
        "visualSummary": _str(),
    }
)


# --------------------------------------------------------------------------- colour


def normalize_hex(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if re.fullmatch(r"#[0-9a-f]{6}", text):
        return text
    if re.fullmatch(r"#[0-9a-f]{3}", text):
        return "#" + "".join(c * 2 for c in text[1:])
    if re.fullmatch(r"#[0-9a-f]{8}", text):
        return text[:7]
    m = re.match(r"rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)(?:[,\s/]+([\d.]+))?", text)
    if m:
        if m.group(4) is not None and float(m.group(4)) < 0.5:
            return None
        r, g, b = (min(255, int(m.group(i))) for i in (1, 2, 3))
        return f"#{r:02x}{g:02x}{b:02x}"
    return None


def hex_to_rgb(hex6: str) -> tuple[int, int, int]:
    body = hex6.lstrip("#")
    return int(body[0:2], 16), int(body[2:4], 16), int(body[4:6], 16)


def _srgb_to_linear(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_to_lab(hex6: str) -> tuple[float, float, float]:
    r, g, b = (_srgb_to_linear(v) for v in hex_to_rgb(hex6))
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e(a: str, b: str) -> float:
    la, lb = hex_to_lab(a), hex_to_lab(b)
    return math.sqrt(sum((p - q) ** 2 for p, q in zip(la, lb)))


def _hsv(hex6: str) -> tuple[float, float, float]:
    r, g, b = hex_to_rgb(hex6)
    return colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)


def is_vivid(hex6: str) -> bool:
    _h, s, v = _hsv(hex6)
    return s >= 0.35 and v >= 0.3


def luminance(hex6: str) -> float:
    r, g, b = hex_to_rgb(hex6)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def _hue_distance(a: str, b: str) -> float:
    ha, hb = _hsv(a)[0] * 360, _hsv(b)[0] * 360
    d = abs(ha - hb) % 360
    return min(d, 360 - d)


# --------------------------------------------------------------------------- capture

_EXTRACT_JS = r"""
() => {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 1;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  const cache = new Map();
  const toHex = (value) => {
    if (!value || value === 'transparent' || value === 'none') return null;
    if (cache.has(value)) return cache.get(value);
    let out = null;
    try {
      ctx.clearRect(0, 0, 1, 1);
      ctx.fillStyle = '#000';
      ctx.fillStyle = value;
      ctx.fillRect(0, 0, 1, 1);
      const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data;
      if (a >= 128) out = '#' + [r, g, b].map((n) => n.toString(16).padStart(2, '0')).join('');
    } catch (e) { out = null; }
    cache.set(value, out);
    return out;
  };
  const firstFamily = (ff) => (ff || '').split(',')[0].trim().replace(/^['"]|['"]$/g, '');
  const vh = window.innerHeight;
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const s = getComputedStyle(el);
    return s.visibility !== 'hidden' && s.display !== 'none' && parseFloat(s.opacity || '1') > 0.05;
  };
  const brief = (el) => {
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return {
      tag: el.tagName.toLowerCase(),
      text: (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 140),
      color: toHex(s.color),
      bg: toHex(s.backgroundColor),
      bgImage: (s.backgroundImage || '').slice(0, 160),
      font: firstFamily(s.fontFamily),
      weight: parseInt(s.fontWeight, 10) || 400,
      size: parseFloat(s.fontSize) || 0,
      radius: s.borderTopLeftRadius,
      rect: [Math.round(r.left), Math.round(r.top + window.scrollY), Math.round(r.width), Math.round(r.height)],
    };
  };
  const pageBg = () => toHex(getComputedStyle(document.body).backgroundColor)
    || toHex(getComputedStyle(document.documentElement).backgroundColor) || '#ffffff';
  const backdropOf = (el) => {
    let node = el;
    while (node && node !== document.documentElement) {
      const hex = toHex(getComputedStyle(node).backgroundColor);
      if (hex) return hex;
      node = node.parentElement;
    }
    return pageBg();
  };

  const colorUsage = new Map();
  const fontUsage = new Map();
  const bump = (hex, key, amount) => {
    if (!hex) return;
    const row = colorUsage.get(hex) || { hex, bgArea: 0, textChars: 0, borderCount: 0, gradient: 0 };
    row[key] += amount;
    colorUsage.set(hex, row);
  };
  const limit = vh * 3;
  let scanned = 0;
  for (const el of document.body.querySelectorAll('*')) {
    if (scanned > 2500) break;
    const r = el.getBoundingClientRect();
    if (r.top + window.scrollY > limit || r.width < 2 || r.height < 2) continue;
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none') continue;
    scanned += 1;
    const area = Math.min(r.width, window.innerWidth) * Math.min(r.height, vh);
    bump(toHex(s.backgroundColor), 'bgArea', area);
    if (s.borderTopWidth && parseFloat(s.borderTopWidth) > 0) bump(toHex(s.borderTopColor), 'borderCount', 1);
    const bgi = s.backgroundImage || '';
    if (bgi.includes('gradient')) {
      for (const m of bgi.matchAll(/(rgba?\([^)]*\)|#[0-9a-fA-F]{3,8}|oklch\([^)]*\)|color\([^)]*\))/g)) bump(toHex(m[1]), 'gradient', 1);
    }
    let own = 0;
    for (const n of el.childNodes) if (n.nodeType === 3) own += n.textContent.trim().length;
    if (own > 0) {
      bump(toHex(s.color), 'textChars', own);
      const fam = firstFamily(s.fontFamily);
      if (fam) {
        const row = fontUsage.get(fam) || { family: fam, chars: 0, weights: {}, tags: {}, maxSize: 0 };
        row.chars += own;
        const w = parseInt(s.fontWeight, 10) || 400;
        row.weights[w] = (row.weights[w] || 0) + own;
        const tag = el.tagName.toLowerCase();
        row.tags[tag] = (row.tags[tag] || 0) + 1;
        row.maxSize = Math.max(row.maxSize, parseFloat(s.fontSize) || 0);
        fontUsage.set(fam, row);
      }
    }
  }

  const cssVars = [];
  const rootStyle = getComputedStyle(document.documentElement);
  const seenVars = new Set();
  for (const sheet of [...document.styleSheets]) {
    let rules;
    try { rules = sheet.cssRules; } catch (e) { continue; }
    for (const rule of [...(rules || [])]) {
      if (!rule.style || !rule.selectorText) continue;
      if (!/(^|,|\s)(:root|html|body)\b/.test(rule.selectorText)) continue;
      for (const prop of [...rule.style]) {
        if (!prop.startsWith('--') || seenVars.has(prop) || cssVars.length >= 300) continue;
        seenVars.add(prop);
        const raw = rootStyle.getPropertyValue(prop).trim() || rule.style.getPropertyValue(prop).trim();
        if (!raw || raw.length > 60 || !/^(#|rgb|hsl|oklch|oklab|lab|lch|color\()/i.test(raw)) continue;
        const hex = toHex(raw);
        if (hex) cssVars.push({ name: prop, hex });
      }
    }
  }

  const fontFaces = [];
  try {
    for (const f of document.fonts) {
      if (f.status !== 'loaded') continue;
      fontFaces.push({ family: f.family.replace(/^['"]|['"]$/g, ''), weight: f.weight, style: f.style });
    }
  } catch (e) {}

  const h1 = [...document.querySelectorAll('h1')].find(visible);
  const h2s = [...document.querySelectorAll('h2')].filter(visible).slice(0, 8).map(brief);
  const paragraphs = [...document.querySelectorAll('p')].filter(visible)
    .map((p) => (p.innerText || '').trim().replace(/\s+/g, ' '))
    .filter((t) => t.length > 40).slice(0, 8).map((t) => t.slice(0, 280));
  const ctas = [];
  for (const el of document.querySelectorAll('a, button')) {
    if (ctas.length >= 12) break;
    if (!visible(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.top + window.scrollY > vh * 2) continue;
    const s = getComputedStyle(el);
    const bg = toHex(s.backgroundColor);
    const bordered = parseFloat(s.borderTopWidth) > 0;
    if (!bg && !bordered) continue;
    const text = (el.innerText || '').trim().replace(/\s+/g, ' ');
    if (!text || text.length > 40) continue;
    const row = brief(el);
    row.href = el.getAttribute('href') || '';
    row.border = bordered ? toHex(s.borderTopColor) : null;
    ctas.push(row);
  }
  const navLinks = [...document.querySelectorAll('header a, nav a')].filter(visible)
    .map((a) => (a.innerText || '').trim().replace(/\s+/g, ' ')).filter((t) => t && t.length < 32)
    .filter((t, i, arr) => arr.indexOf(t) === i).slice(0, 14);
  const socialRe = /(linkedin\.com|twitter\.com|x\.com|facebook\.com|instagram\.com|youtube\.com|tiktok\.com|github\.com|pinterest\.)/i;
  const socialLinks = [...new Set([...document.querySelectorAll('a[href]')]
    .map((a) => a.href).filter((h) => socialRe.test(h)))].slice(0, 12);

  const logoSel = [
    'header svg', 'nav svg', 'a[href="/"] svg', '[class*="logo" i] svg', '[aria-label*="logo" i] svg',
    'header img', 'nav img', 'a[href="/"] img', '[class*="logo" i] img', 'img[alt*="logo" i]',
  ].join(',');
  const inlineSvg = (svg) => {
    const clone = svg.cloneNode(true);
    const src = [svg, ...svg.querySelectorAll('*')];
    const dst = [clone, ...clone.querySelectorAll('*')];
    src.forEach((node, i) => {
      const target = dst[i];
      if (!target) return;
      const s = getComputedStyle(node);
      for (const attr of ['fill', 'stroke']) {
        const raw = node.getAttribute(attr);
        if (raw && /var\(|currentcolor/i.test(raw)) {
          const hex = toHex(s[attr]);
          if (hex) target.setAttribute(attr, hex);
        }
      }
    });
    return clone.outerHTML;
  };
  const logos = [];
  const seenLogo = new Set();
  for (const el of document.querySelectorAll(logoSel)) {
    if (logos.length >= 12) break;
    if (el.tagName.toLowerCase() === 'svg' && el.parentElement && el.parentElement.closest('svg')) continue;
    if (seenLogo.has(el)) continue;
    seenLogo.add(el);
    const r = el.getBoundingClientRect();
    const anchor = el.closest('a');
    const href = anchor ? anchor.getAttribute('href') || '' : '';
    let path = href;
    try { const u = new URL(href, location.href); path = u.origin === location.origin ? u.pathname : '#external'; } catch (e) {}
    const homeLink = /^\/((home|index(\.html?)?|[a-z]{2}([-_][a-z]{2})?)\/?)?$/i.test(path);
    const label = [
      el.getAttribute('alt'), el.getAttribute('aria-label'), el.getAttribute('class'),
      anchor && anchor.getAttribute('aria-label'), anchor && anchor.getAttribute('class'),
      el.closest('[class*="logo" i]') ? 'logo' : '',
    ].filter(Boolean).join(' ').slice(0, 200);
    const siteWord = (document.title || '').split(/[\s|:·–—-]+/)[0].toLowerCase();
    const hinted = homeLink || /logo|brand|wordmark/i.test(label)
      || (siteWord.length > 2 && label.toLowerCase().includes(siteWord));
    const minW = hinted ? 14 : 24;
    if (r.width < minW || r.height < 10 || r.top > 240 || r.width > 520) continue;
    let score = 0;
    if (/logo|brand|wordmark/i.test(label)) score += 3;
    if (siteWord.length > 2 && label.toLowerCase().includes(siteWord)) score += 2;
    if (homeLink) score += 3;
    if (r.left < window.innerWidth * 0.3) score += 2;
    if (r.left > window.innerWidth * 0.7) score -= 2;
    if (r.width / Math.max(1, r.height) > 1.8) score += 1;
    if (!hinted && r.width <= 24 && r.height <= 24) continue;
    const s = getComputedStyle(el);
    const item = {
      kind: el.tagName.toLowerCase() === 'svg' ? 'svg' : 'img',
      rect: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)],
      label, href, score,
      color: toHex(s.color) || toHex(s.fill),
      backdrop: backdropOf(el.parentElement || el),
    };
    if (item.kind === 'svg') item.svg = inlineSvg(el).slice(0, 80000);
    else item.src = el.currentSrc || el.src || '';
    logos.push(item);
  }
  logos.sort((a, b) => b.score - a.score || a.rect[0] - b.rect[0]);

  const meta = {};
  for (const m of document.querySelectorAll('meta[name], meta[property]')) {
    const key = (m.getAttribute('name') || m.getAttribute('property') || '').toLowerCase();
    if (/^(description|og:title|og:description|og:site_name|theme-color|twitter:title|keywords)$/.test(key)) {
      meta[key] = (m.getAttribute('content') || '').slice(0, 300);
    }
  }

  const sortedColors = [...colorUsage.values()].sort((a, b) => (b.bgArea + b.textChars * 400) - (a.bgArea + a.textChars * 400)).slice(0, 40);
  const sortedFonts = [...fontUsage.values()].sort((a, b) => b.chars - a.chars).slice(0, 12);
  return {
    url: location.href,
    title: document.title,
    lang: document.documentElement.lang || '',
    meta,
    body: brief(document.body),
    pageBg: pageBg(),
    h1: h1 ? brief(h1) : null,
    h2s, paragraphs, ctas, navLinks, socialLinks,
    logos: logos.slice(0, 5),
    cssVars, fontFaces: fontFaces.slice(0, 40),
    colorUsage: sortedColors, fontUsage: sortedFonts,
    scrollHeight: document.documentElement.scrollHeight,
    viewport: [window.innerWidth, vh],
  };
}
"""

_DISMISS_JS = r"""
() => {
  const re = /^(accept( all)?( cookies)?|allow all|agree|i agree|got it|ok(ay)?|accepter|tout accepter|j'accepte)$/i;
  for (const el of document.querySelectorAll('button, [role="button"], a')) {
    const t = (el.innerText || '').trim();
    if (t && t.length < 32 && re.test(t)) { try { el.click(); return t; } catch (e) {} }
  }
  return null;
}
"""


def playwright_available() -> tuple[bool, str]:
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False, "playwright not installed (pip install playwright && python -m playwright install chromium)"
    return True, ""


def _launch_browser(p: Any) -> Any:
    errors: list[str] = []
    exe = (os.environ.get("COMMMAKER_CHROME_PATH") or "").strip()
    attempts: list[dict[str, Any]] = []
    if exe:
        attempts.append({"executable_path": exe})
    attempts += [{}, {"channel": "chrome"}, {"channel": "msedge"}]
    for kwargs in attempts:
        try:
            return p.chromium.launch(headless=True, **kwargs)
        except Exception as exc:  # noqa: BLE001 — try next browser
            errors.append(str(exc).splitlines()[0][:120])
    raise RuntimeError("No Chromium available: " + " | ".join(errors))


def _settle(page: Any, url: str, timeout_ms: int) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    try:
        page.wait_for_load_state("networkidle", timeout=min(10_000, timeout_ms))
    except Exception:  # noqa: BLE001 — long-polling sites never go idle
        pass
    try:
        page.evaluate(_DISMISS_JS)
    except Exception:  # noqa: BLE001
        pass
    try:
        page.evaluate("() => document.fonts && document.fonts.ready.then(() => true)")
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(700)


def capture_site(
    url: str,
    out_dir: str,
    *,
    mobile: bool = True,
    timeout_ms: int = CAPTURE_TIMEOUT_MS,
) -> dict[str, Any]:
    """Screenshot the rendered site and extract computed-style DOM signals.

    Returns ``{"available": False, "reason": …}`` when Playwright / Chromium is missing
    or the page cannot be rendered, so callers degrade to static scrape signals.
    """
    ok, reason = playwright_available()
    if not ok:
        return {"available": False, "reason": reason}
    from playwright.sync_api import sync_playwright

    os.makedirs(out_dir, exist_ok=True)
    shots: dict[str, str] = {}
    started = time.time()
    try:
        with sync_playwright() as p:
            browser = _launch_browser(p)
            try:
                ctx = browser.new_context(
                    viewport=DESKTOP_VIEWPORT,
                    user_agent=_USER_AGENT,
                    device_scale_factor=1,
                )
                page = ctx.new_page()
                _settle(page, url, timeout_ms)
                fold = os.path.join(out_dir, "desktop-fold.jpg")
                page.screenshot(path=fold, type="jpeg", quality=82)
                shots["desktopFold"] = fold
                shots.update(_component_shots(page, out_dir))
                rendered = page.evaluate(_EXTRACT_JS)
                height = int(min(FULL_PAGE_MAX_HEIGHT, rendered.get("scrollHeight") or 900))
                full = os.path.join(out_dir, "desktop-full.jpg")
                try:
                    page.screenshot(
                        path=full,
                        type="jpeg",
                        quality=70,
                        full_page=True,
                        clip={"x": 0, "y": 0, "width": DESKTOP_VIEWPORT["width"], "height": height},
                    )
                    shots["desktopFull"] = full
                except Exception:  # noqa: BLE001 — full-page is optional
                    pass
                ctx.close()
                if mobile:
                    try:
                        mctx = browser.new_context(
                            viewport=MOBILE_VIEWPORT,
                            user_agent=_USER_AGENT + " Mobile",
                            device_scale_factor=2,
                            is_mobile=True,
                            has_touch=True,
                        )
                        mpage = mctx.new_page()
                        _settle(mpage, url, timeout_ms)
                        mpath = os.path.join(out_dir, "mobile-fold.jpg")
                        mpage.screenshot(path=mpath, type="jpeg", quality=78)
                        shots["mobileFold"] = mpath
                        mctx.close()
                    except Exception:  # noqa: BLE001 — mobile is optional
                        pass
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 — degrade to static signals
        return {"available": False, "reason": f"render failed: {str(exc).splitlines()[0][:200]}"}
    return {
        "available": True,
        "screenshots": shots,
        "rendered": rendered,
        "durationSec": round(time.time() - started, 2),
    }


_COMPONENT_JS = """
() => {
  document.querySelectorAll("[data-cm-component]").forEach((el) => el.removeAttribute("data-cm-component"));
  const candidates = [];
  const nodes = document.querySelectorAll("img, svg, canvas, video, picture, figure, section, article, div");
  for (const el of nodes) {
    const rect = el.getBoundingClientRect();
    if (rect.width < 200 || rect.height < 140) continue;
    if (rect.width > window.innerWidth * 0.96 && rect.height > window.innerHeight * 0.92) continue;
    const tag = el.tagName.toLowerCase();
    const style = getComputedStyle(el);
    const background = style.backgroundImage && style.backgroundImage !== "none";
    const media = ["img", "svg", "canvas", "video", "picture", "figure"].includes(tag);
    const child = el.querySelector(":scope > img, :scope > svg, :scope > canvas, :scope > video, :scope > picture");
    if (!media && !background && !child) continue;
    candidates.push({el, area: rect.width * rect.height});
  }
  candidates.sort((a, b) => b.area - a.area);
  const kept = [];
  for (const item of candidates) {
    const box = item.el.getBoundingClientRect();
    const overlaps = kept.some((other) => {
      const prev = other.el.getBoundingClientRect();
      const width = Math.max(0, Math.min(box.right, prev.right) - Math.max(box.left, prev.left));
      const height = Math.max(0, Math.min(box.bottom, prev.bottom) - Math.max(box.top, prev.top));
      const smaller = Math.min(box.width * box.height, prev.width * prev.height) || 1;
      return (width * height) / smaller > 0.7;
    });
    if (overlaps) continue;
    kept.push(item);
    if (kept.length >= 8) break;
  }
  kept.forEach((item, index) => item.el.setAttribute("data-cm-component", String(index)));
  return kept.length;
}
"""


def _component_shots(page: Any, out_dir: str) -> dict[str, str]:
    """Element screenshots of hero art, cards and illustrations, not the whole page."""
    shots: dict[str, str] = {}
    try:
        count = int(page.evaluate(_COMPONENT_JS) or 0)
    except Exception:  # noqa: BLE001 — a page with no measurable components still has the fold
        return shots
    for index in range(min(count, 8)):
        path = os.path.join(out_dir, f"component-{index}.jpg")
        try:
            page.locator(f'[data-cm-component="{index}"]').screenshot(path=path, type="jpeg", quality=80)
        except Exception:  # noqa: BLE001 — one element can fail without dropping the page shot
            continue
        if os.path.isfile(path):
            shots[f"component{index}"] = path
    return shots


def pixel_palette(image_path: str | None, *, colors: int = 10) -> list[dict[str, Any]]:
    """Dominant colours by pixel share (Pillow optional)."""
    if not image_path or not os.path.isfile(image_path):
        return []
    try:
        from PIL import Image
    except ImportError:
        return []
    try:
        with Image.open(image_path) as img:
            small = img.convert("RGB").resize((180, 112))
            quant = small.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
            pal = quant.getpalette() or []
            counts = quant.getcolors() or []
    except Exception:  # noqa: BLE001
        return []
    total = sum(c for c, _ in counts) or 1
    out: list[dict[str, Any]] = []
    for count, index in sorted(counts, reverse=True):
        r, g, b = pal[index * 3 : index * 3 + 3]
        out.append({"hex": f"#{r:02x}{g:02x}{b:02x}", "share": round(count / total, 4)})
    return out


# --------------------------------------------------------------------------- signals


def _normalize_family(name: str) -> str:
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.strip().strip("'\"").casefold()
    text = re.sub(r"[\s_-]+(var|variable|vf)$", "", text)
    return re.sub(r"[\s_-]+", " ", text).strip()


_GENERIC_FAMILIES = frozenset(
    {"", "sans-serif", "serif", "monospace", "system-ui", "-apple-system", "inherit", "initial"}
)


def _dedupe_label(text: Any) -> str:
    """Collapse 'Sign in Sign in' (visually hidden duplicate labels) to 'Sign in'."""
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    m = re.fullmatch(r"(.+?)\s+\1", value)
    return m.group(1) if m else value


def _rank_var_name(name: str) -> int:
    n = name.lower()
    if any(k in n for k in ("brand", "primary", "accent", "cta")):
        return 3
    if any(k in n for k in ("secondary", "highlight", "link")):
        return 2
    if any(k in n for k in ("background", "bg", "text", "foreground", "surface")):
        return 1
    return 0


def build_signals(
    kit: dict[str, Any] | None,
    capture: dict[str, Any] | None,
    pixels: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Merge static scrape + rendered DOM + pixel palette into candidate lists."""
    kit = kit or {}
    rendered = (capture or {}).get("rendered") or {}
    pixels = pixels or []

    colors: list[dict[str, Any]] = []

    def add_color(
        hex_value: Any,
        source: str,
        weight: float = 1.0,
        *,
        share: float = 0.0,
        text_chars: int = 0,
    ) -> None:
        hex6 = normalize_hex(hex_value)
        if not hex6:
            return
        for row in colors:
            if row["hex"] == hex6 or delta_e(row["hex"], hex6) < 2.5:
                if source not in row["sources"]:
                    row["sources"].append(source)
                row["score"] += weight
                row["pixelShare"] = max(row["pixelShare"], share)
                row["textChars"] += text_chars
                return
        colors.append(
            {
                "hex": hex6,
                "sources": [source],
                "score": weight,
                "pixelShare": share,
                "textChars": text_chars,
            }
        )

    add_color(rendered.get("pageBg"), "computed:page-background", 6)
    body = rendered.get("body") or {}
    add_color(body.get("color"), "computed:body-text", 3)
    h1 = rendered.get("h1") or {}
    add_color(h1.get("color"), "computed:h1", 2)
    for cta in (rendered.get("ctas") or [])[:8]:
        add_color(cta.get("bg"), "computed:cta-background", 4)
        add_color(cta.get("border"), "computed:cta-border", 1)
    for row in (rendered.get("colorUsage") or [])[:24]:
        if row.get("bgArea", 0) > 20_000:
            add_color(row.get("hex"), "computed:surface", 1 + min(4, row["bgArea"] / 300_000))
        if row.get("textChars", 0) > 30:
            add_color(
                row.get("hex"),
                "computed:text",
                1 + min(3, row["textChars"] / 400),
                text_chars=int(row["textChars"]),
            )
        if row.get("gradient", 0):
            add_color(row.get("hex"), "computed:gradient-stop", 2)
    for var in sorted(
        rendered.get("cssVars") or [], key=lambda v: -_rank_var_name(v.get("name", ""))
    )[:40]:
        rank = _rank_var_name(var.get("name", ""))
        add_color(var.get("hex"), f"css-var:{var.get('name')}", 0.5 + rank)
    theme = (rendered.get("meta") or {}).get("theme-color")
    add_color(theme, "meta:theme-color", 3)
    for i, c in enumerate(kit.get("colors") or []):
        add_color(c, "static-css", max(0.3, 2 - i * 0.25))
    for px in pixels:
        if px.get("share", 0) >= 0.01:
            add_color(px.get("hex"), "pixels", 1 + 40 * px["share"], share=px["share"])

    colors.sort(key=lambda r: -r["score"])
    colors = colors[:24]
    for i, row in enumerate(colors, 1):
        row["id"] = f"c{i}"
        row["score"] = round(row["score"], 2)
        row["vivid"] = is_vivid(row["hex"])

    fonts: list[dict[str, Any]] = []

    def add_font(
        family: Any,
        source: str,
        *,
        chars: int = 0,
        weights: list[int] | None = None,
        roles: list[str] | None = None,
    ) -> None:
        fam = re.sub(r"[\"'()]", "", str(family or "")).strip()
        norm = _normalize_family(fam)
        if norm in _GENERIC_FAMILIES or re.search(r"emoji|symbol", norm):
            return
        for row in fonts:
            if row["norm"] == norm:
                if source not in row["sources"]:
                    row["sources"].append(source)
                row["chars"] += chars
                for w in weights or []:
                    if w not in row["weights"]:
                        row["weights"].append(w)
                for r in roles or []:
                    if r not in row["roles"]:
                        row["roles"].append(r)
                return
        fonts.append(
            {
                "family": fam,
                "norm": norm,
                "sources": [source],
                "chars": chars,
                "weights": list(weights or []),
                "roles": list(roles or []),
            }
        )

    if h1.get("font"):
        add_font(h1["font"], "computed:h1", weights=[int(h1.get("weight") or 400)], roles=["display"])
    for h2 in (rendered.get("h2s") or [])[:4]:
        add_font(h2.get("font"), "computed:h2", weights=[int(h2.get("weight") or 400)], roles=["display"])
    if body.get("font"):
        add_font(body["font"], "computed:body", weights=[int(body.get("weight") or 400)], roles=["body"])
    for row in rendered.get("fontUsage") or []:
        ws = sorted(int(w) for w in (row.get("weights") or {}).keys() if str(w).isdigit())
        tags = row.get("tags") or {}
        roles = ["body"] if tags.get("p") else []
        if any(t in tags for t in ("h1", "h2")):
            roles.append("display")
        add_font(row.get("family"), "computed:text", chars=int(row.get("chars") or 0), weights=ws, roles=roles)
    for face in rendered.get("fontFaces") or []:
        w = str(face.get("weight") or "")
        ws = [int(x) for x in re.findall(r"\d{3}", w)]
        add_font(face.get("family"), "font-face", weights=ws)
    for name in kit.get("fonts") or []:
        add_font(name, "static-css")
    for g in kit.get("googleFonts") or []:
        if isinstance(g, dict):
            ws = [int(w) for w in g.get("weights") or [] if str(w).isdigit()]
            add_font(g.get("family"), "google-fonts", weights=ws)
    fonts.sort(key=lambda r: (-(r["chars"] + 200 * len(r["roles"])), -len(r["sources"])))
    fonts = fonts[:10]
    for i, row in enumerate(fonts, 1):
        row["id"] = f"f{i}"
        row["weights"] = sorted(set(row["weights"]))[:8]

    logos: list[dict[str, Any]] = []
    for i, item in enumerate((rendered.get("logos") or [])[:4], 1):
        entry = {
            "id": f"L{i}",
            "kind": item.get("kind"),
            "source": "rendered-header",
            "label": _truncate(str(item.get("label") or ""), 80),
            "rect": item.get("rect"),
            "backdropHex": normalize_hex(item.get("backdrop")),
            "colorHex": normalize_hex(item.get("color")),
            "score": item.get("score", 0),
        }
        if item.get("svg"):
            entry["svg"] = item["svg"]
        if item.get("src"):
            entry["url"] = item["src"]
        logos.append(entry)
    if kit.get("logoSvg"):
        logos.append({"id": "K1", "kind": "svg", "source": "static-scrape", "svg": kit["logoSvg"], "label": "static header svg"})
    if kit.get("logoUrl"):
        logos.append({"id": "K2", "kind": "img", "source": "static-scrape", "url": kit["logoUrl"], "label": kit.get("logoSource") or "img"})
    if kit.get("faviconUrl"):
        logos.append({"id": "K3", "kind": "img", "source": "favicon", "url": kit["faviconUrl"], "label": "favicon"})

    meta = rendered.get("meta") or {}
    copy = {
        "title": rendered.get("title") or kit.get("siteName") or "",
        "siteName": meta.get("og:site_name") or kit.get("siteName") or "",
        "metaDescription": meta.get("description") or kit.get("tagline") or "",
        "ogTitle": meta.get("og:title") or kit.get("headline") or "",
        "h1": h1.get("text") or kit.get("headline") or "",
        "h2s": [h.get("text") for h in rendered.get("h2s") or [] if h.get("text")][:8],
        "paragraphs": (rendered.get("paragraphs") or [])[:6],
        "ctas": [_dedupe_label(c.get("text")) for c in rendered.get("ctas") or [] if c.get("text")][:10],
        "navLinks": (rendered.get("navLinks") or [])[:12],
        "lang": rendered.get("lang") or "",
    }
    radii: list[float] = []
    for cta in rendered.get("ctas") or []:
        m = re.match(r"([\d.]+)px", str(cta.get("radius") or ""))
        if m:
            radii.append(float(m.group(1)))
    layout = {
        "ctaRadiusPx": sorted(radii)[len(radii) // 2] if radii else None,
        "scrollHeight": rendered.get("scrollHeight"),
        "gradientStops": sum(1 for r in rendered.get("colorUsage") or [] if r.get("gradient")),
    }
    return {
        "sourceUrl": kit.get("sourceUrl") or rendered.get("url") or "",
        "rendered": bool(rendered),
        "colors": colors,
        "fonts": fonts,
        "logos": logos,
        "copy": copy,
        "layout": layout,
        "pixels": pixels[:8],
        "socialLinks": rendered.get("socialLinks") or [],
        "ctaLinks": [
            {"text": _dedupe_label(c.get("text")), "href": c.get("href")}
            for c in rendered.get("ctas") or []
            if c.get("text") and c.get("href")
        ][:6],
    }


def signals_for_prompt(signals: dict[str, Any]) -> str:
    """Compact JSON for the vision prompt (no SVG bodies, no long lists)."""
    compact = {
        "colorCandidates": [
            {
                "id": c["id"],
                "hex": c["hex"],
                "sources": c["sources"][:4],
                "pixelShare": c["pixelShare"],
                "textChars": c.get("textChars", 0),
            }
            for c in signals.get("colors", [])[:18]
        ],
        "fontCandidates": [
            {
                "id": f["id"],
                "family": f["family"],
                "weights": f["weights"],
                "roles": f["roles"],
                "sources": f["sources"][:3],
                "textChars": f["chars"],
            }
            for f in signals.get("fonts", [])[:8]
        ],
        "logoCandidates": [
            {
                "id": lg["id"],
                "kind": lg.get("kind"),
                "source": lg.get("source"),
                "label": lg.get("label", ""),
                "rect": lg.get("rect"),
                "backdropHex": lg.get("backdropHex"),
            }
            for lg in signals.get("logos", [])
        ],
        "copy": {
            k: (_truncate(v, 240) if isinstance(v, str) else [_truncate(str(x), 160) for x in v])
            for k, v in (signals.get("copy") or {}).items()
        },
        "layout": signals.get("layout"),
    }
    return json.dumps(compact, ensure_ascii=False)


# --------------------------------------------------------------------------- vision LLM


def _load_image_for_vision(path: str, *, max_edge: int = VISION_MAX_EDGE, crop_height: int | None = None) -> tuple[str, str, tuple[int, int]] | None:
    if not path or not os.path.isfile(path):
        return None
    try:
        from PIL import Image

        with Image.open(path) as img:
            img = img.convert("RGB")
            if crop_height and img.height > crop_height:
                img = img.crop((0, 0, img.width, crop_height))
            scale = min(1.0, max_edge / max(img.width, img.height))
            if scale < 1.0:
                img = img.resize((int(img.width * scale), int(img.height * scale)))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=80)
            return base64.b64encode(buf.getvalue()).decode("ascii"), "image/jpeg", img.size
    except ImportError:
        with open(path, "rb") as handle:
            data = handle.read()
        return base64.b64encode(data).decode("ascii"), "image/jpeg", (0, 0)
    except Exception:  # noqa: BLE001
        return None


def vision_images(screenshots: dict[str, str] | None) -> list[dict[str, Any]]:
    shots = screenshots or {}
    plan = [
        ("desktopFold", "Desktop above-the-fold (1440×900)", None),
        ("desktopFull", "Desktop page top-to-bottom (first ~4 screens)", 3600),
        ("mobileFold", "Mobile above-the-fold (390×844)", None),
    ]
    out: list[dict[str, Any]] = []
    for key, label, crop in plan:
        loaded = _load_image_for_vision(shots.get(key, ""), crop_height=crop)
        if loaded:
            data, media, size = loaded
            out.append({"key": key, "label": label, "data": data, "mediaType": media, "size": size})
    return out


def estimate_image_tokens(images: list[dict[str, Any]]) -> int:
    total = 0
    for img in images:
        w, h = img.get("size") or (0, 0)
        total += int(w * h / 750) if w and h else 1600
    return total


def _vision_instructions(signals: dict[str, Any], *, has_images: bool) -> str:
    seen = "the screenshots above" if has_images else "the extracted signals (no screenshots available)"
    return f"""Build this company's Brand Profile from {seen} and the machine-extracted SIGNALS below.

SIGNALS are ground truth for exact values. Your job is to judge what actually defines the visual identity and pick from them:
- palette: 4–6 entries. Roles background, primary, accent and text are required (surface/secondary optional). Use the colorCandidates id + its exact hex whenever the colour is visibly used. Only if a prominent colour in the screenshots (e.g. inside a gradient image) is missing from candidates, set candidateId "" and estimate the hex. Order like a brand book: background, primary, text, accent, secondary/surface. name = short evocative colour name; usage = where it appears.
- typography: display = headline family, body = paragraph family, chosen from fontCandidates (candidateId + exact family string) with weights seen on the page.
- logo: candidateId from logoCandidates (the real wordmark/symbol in the header, not a partner logo), backdropHex = colour the logo sits on, variant.
- aesthetic: 4–6 specific visual-language tags (2–3 words, Title Case) describing what you SEE — shapes, layering, motion, gradients, texture, grid — e.g. "Chromatic Fluidity", "Modular Layering", "Kinetic Geometry", "Isomorphic Planes". No generic adjectives like "Modern" or "Clean".
- toneOfVoice: 3–5 single words. brandValues: 3–5 short phrases. keywords: 5–10 business keywords.
- tagline: the brand's own primary line (hero headline or meta), ≤ 90 characters, in the site's language. businessOverview: 2–3 factual sentences.
- imageryStyle: primaryMedium + secondaryMedia (from {", ".join(IMAGERY_MEDIA)}), motifs (3–6 concrete visual motifs), colorTreatment, avoid (things never seen in their imagery). ideogramPrompt: one line written from the site screenshots and any public social images, ≤ 60 words, text-free art direction (palette hexes, motifs, lighting; no page text, no logos, no UI, no people unless the brand uses them).
- layoutTraits: density, cornerRadius (CTA radius px is in layout), whitespace, composition (one sentence).
- doNots: 3–6 brand guardrails inferred from the site.
- visualSummary: one sentence on how the site looks.

Call submit_brand_profile exactly once.

SIGNALS:
{signals_for_prompt(signals)}"""


_VISION_SYSTEM = (
    "You are a senior brand designer and strategist. You analyse a company's live website "
    "from screenshots plus machine-extracted signals and produce a precise, structured Brand Profile. "
    "You MUST call submit_brand_profile exactly once with every field filled."
)


def anthropic_vision_body(
    signals: dict[str, Any],
    images: list[dict[str, Any]],
    *,
    model: str,
) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    for i, img in enumerate(images, 1):
        content.append({"type": "text", "text": f"Image {i}: {img['label']}"})
        content.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": img["mediaType"], "data": img["data"]},
            }
        )
    content.append({"type": "text", "text": _vision_instructions(signals, has_images=bool(images))})
    return {
        "model": model,
        "max_tokens": VISION_MAX_TOKENS,
        "system": _VISION_SYSTEM,
        "messages": [{"role": "user", "content": content}],
        "tools": [
            {
                "name": "submit_brand_profile",
                "description": "Submit the structured Brand Profile for the analysed website.",
                "input_schema": BRAND_PROFILE_JSON_SCHEMA,
                "strict": True,
            }
        ],
        "tool_choice": {"type": "auto"},
    }


def _post_json(url: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=VISION_TIMEOUT_SEC) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _call_anthropic_vision(
    signals: dict[str, Any], images: list[dict[str, Any]], *, api_key: str, model: str
) -> tuple[dict[str, Any], dict[str, int]]:
    body = anthropic_vision_body(signals, images, model=model)
    usage = {"inputTokens": 0, "outputTokens": 0}
    for _ in range(2):
        payload = _post_json(
            f"{ANTHROPIC_API_BASE}/messages", body, _anthropic_request_headers(api_key)
        )
        u = payload.get("usage") or {}
        usage["inputTokens"] += int(u.get("input_tokens") or 0)
        usage["outputTokens"] += int(u.get("output_tokens") or 0)
        for block in payload.get("content") or []:
            if block.get("type") == "tool_use" and block.get("name") == "submit_brand_profile":
                if isinstance(block.get("input"), dict):
                    return block["input"], usage
    raise ValueError("Anthropic response missing submit_brand_profile tool output")


def _call_openai_vision(
    signals: dict[str, Any],
    images: list[dict[str, Any]],
    *,
    api_key: str,
    model: str,
    base_url: str,
    extra_headers: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, int]]:
    content: list[dict[str, Any]] = []
    for i, img in enumerate(images, 1):
        content.append({"type": "text", "text": f"Image {i}: {img['label']}"})
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{img['mediaType']};base64,{img['data']}"},
            }
        )
    content.append({"type": "text", "text": _vision_instructions(signals, has_images=bool(images))})
    body = {
        "model": model,
        "temperature": 0.3,
        "max_tokens": VISION_MAX_TOKENS,
        "messages": [
            {"role": "system", "content": _VISION_SYSTEM.replace("call submit_brand_profile", "return JSON")},
            {"role": "user", "content": content},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "brand_profile", "strict": True, "schema": BRAND_PROFILE_JSON_SCHEMA},
        },
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    headers.update(extra_headers or {})
    payload = _post_json(f"{base_url}/chat/completions", body, headers)
    u = payload.get("usage") or {}
    usage = {
        "inputTokens": int(u.get("prompt_tokens") or 0),
        "outputTokens": int(u.get("completion_tokens") or 0),
    }
    choices = payload.get("choices") or []
    if not choices:
        raise ValueError("LLM returned no choices")
    text = str((choices[0].get("message") or {}).get("content") or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("LLM response was not a JSON object")
    return data, usage


def call_vision_llm(
    signals: dict[str, Any], images: list[dict[str, Any]]
) -> dict[str, Any]:
    """Return ``{"raw", "usage", "model", "provider"}``; raises on provider errors."""
    provider = resolve_llm_provider()
    if not provider:
        raise LookupError("no_provider")
    api_key = api_key_for_provider(provider)
    if not api_key:
        raise LookupError("no_api_key")
    model = (os.environ.get("COMMMAKER_BRAND_PROFILE_MODEL") or "").strip() or resolve_llm_model(provider)
    if provider == "anthropic":
        raw, usage = _call_anthropic_vision(signals, images, api_key=api_key, model=model)
    elif provider == "openrouter":
        raw, usage = _call_openai_vision(
            signals,
            images,
            api_key=api_key,
            model=model,
            base_url=OPENROUTER_API_BASE,
            extra_headers={
                "HTTP-Referer": os.environ.get("OPENROUTER_HTTP_REFERER", "https://github.com/asseukihuh/AI-WebApp"),
                "X-Title": os.environ.get("OPENROUTER_APP_TITLE", "CommMaker"),
            },
        )
    else:
        raw, usage = _call_openai_vision(
            signals, images, api_key=api_key, model=model, base_url=OPENAI_API_BASE
        )
    return {"raw": raw, "usage": usage, "model": model, "provider": provider}


def cost_usd(usage: dict[str, int] | None) -> float:
    usage = usage or {}
    price_in = float(os.environ.get("COMMMAKER_LLM_PRICE_IN_PER_MTOK") or DEFAULT_PRICE_IN_PER_MTOK)
    price_out = float(os.environ.get("COMMMAKER_LLM_PRICE_OUT_PER_MTOK") or DEFAULT_PRICE_OUT_PER_MTOK)
    return round(
        usage.get("inputTokens", 0) * price_in / 1e6 + usage.get("outputTokens", 0) * price_out / 1e6,
        4,
    )


# --------------------------------------------------------------------------- reconcile


def _clean_list(values: Any, limit: int, item_limit: int = 48) -> list[str]:
    out: list[str] = []
    for v in values or []:
        text = _truncate(str(v or ""), item_limit)
        if text and text.casefold() not in {o.casefold() for o in out}:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _snap_color(hex_value: Any, candidate_id: str, signals: dict[str, Any]) -> dict[str, Any] | None:
    by_id = {c["id"]: c for c in signals.get("colors") or []}
    hex6 = normalize_hex(hex_value)
    if candidate_id and candidate_id in by_id:
        c = by_id[candidate_id]
        if not hex6 or delta_e(hex6, c["hex"]) <= SNAP_DELTA_E:
            return {"hex": c["hex"], "candidateId": c["id"], "source": "procedural", "verified": True}
    if not hex6:
        return None
    best, best_d = None, 999.0
    for c in signals.get("colors") or []:
        d = delta_e(hex6, c["hex"])
        if d < best_d:
            best, best_d = c, d
    if best and best_d <= SNAP_DELTA_E:
        return {"hex": best["hex"], "candidateId": best["id"], "source": "procedural", "verified": True}
    return {"hex": hex6, "candidateId": "", "source": "vision", "verified": False}


def _match_font(family: Any, candidate_id: str, weights: Any, signals: dict[str, Any]) -> dict[str, Any]:
    fonts = signals.get("fonts") or []
    by_id = {f["id"]: f for f in fonts}
    norm = _normalize_family(str(family or ""))
    match = next((f for f in fonts if f["norm"] == norm), None) if norm else None
    if not match and candidate_id in by_id:
        match = by_id[candidate_id]
    if not match and norm:
        match = next((f for f in fonts if norm in f["norm"] or f["norm"] in norm), None)
    ai_weights = sorted({int(w) for w in weights or [] if isinstance(w, (int, float)) and 100 <= int(w) <= 900})
    if match:
        known = match.get("weights") or []
        chosen = [w for w in ai_weights if w in known] or known or ai_weights
        return {
            "family": match["family"],
            "candidateId": match["id"],
            "weights": chosen[:6],
            "matched": True,
        }
    return {
        "family": _truncate(str(family or ""), 60) or "system-ui",
        "candidateId": "",
        "weights": ai_weights[:6] or [400],
        "matched": False,
    }


def _ensure_palette_roles(palette: list[dict[str, Any]], signals: dict[str, Any]) -> list[dict[str, Any]]:
    present = {p["role"] for p in palette}
    if all(r in present for r in REQUIRED_PALETTE_ROLES):
        return palette
    heuristic = heuristic_palette(signals)
    used = {p["hex"] for p in palette}
    for entry in heuristic:
        if entry["role"] in present:
            continue
        if entry["hex"] in used and entry["role"] in ("accent",):
            continue
        palette.append(entry)
        present.add(entry["role"])
        used.add(entry["hex"])
    return palette


_ROLE_ORDER = {"background": 0, "primary": 1, "text": 2, "accent": 3, "secondary": 4, "surface": 5}


def reconcile_profile(raw: dict[str, Any], signals: dict[str, Any], kit: dict[str, Any] | None = None) -> dict[str, Any]:
    """Map AI picks onto procedural ground truth and normalise lengths."""
    kit = kit or {}
    copy = signals.get("copy") or {}
    palette: list[dict[str, Any]] = []
    for entry in raw.get("palette") or []:
        if not isinstance(entry, dict):
            continue
        role = entry.get("role") if entry.get("role") in PALETTE_ROLES else "accent"
        snapped = _snap_color(entry.get("hex"), str(entry.get("candidateId") or ""), signals)
        if not snapped or any(
            p["hex"] == snapped["hex"] and p["role"] == role for p in palette
        ):
            continue
        palette.append(
            {
                "role": role,
                **snapped,
                "name": _truncate(str(entry.get("name") or ""), 32),
                "usage": _truncate(str(entry.get("usage") or ""), 90),
            }
        )
        if len(palette) >= 6:
            break
    palette = _ensure_palette_roles(palette, signals)
    palette.sort(key=lambda p: _ROLE_ORDER.get(p["role"], 9))

    typo = raw.get("typography") or {}
    display_raw = typo.get("display") or {}
    body_raw = typo.get("body") or {}
    display = _match_font(display_raw.get("family"), str(display_raw.get("candidateId") or ""), display_raw.get("weights"), signals)
    display["usage"] = _truncate(str(display_raw.get("usage") or "Headlines"), 80)
    body = _match_font(body_raw.get("family"), str(body_raw.get("candidateId") or ""), body_raw.get("weights"), signals)
    body["usage"] = _truncate(str(body_raw.get("usage") or "Body copy"), 80)

    logos = {lg["id"]: lg for lg in signals.get("logos") or []}
    logo_raw = raw.get("logo") or {}
    logo_id = str(logo_raw.get("candidateId") or "")
    if logo_id not in logos:
        logo_id = next(iter(logos), "")
    chosen = logos.get(logo_id) or {}
    backdrop = _snap_color(logo_raw.get("backdropHex") or chosen.get("backdropHex"), "", signals)
    logo = {
        "candidateId": logo_id,
        "kind": chosen.get("kind") or "",
        "source": chosen.get("source") or "",
        "url": chosen.get("url") or "",
        "backdropHex": (backdrop or {}).get("hex") or chosen.get("backdropHex") or "#ffffff",
        "variant": logo_raw.get("variant") or "full-color",
        "notes": _truncate(str(logo_raw.get("notes") or ""), 120),
    }

    imagery_raw = raw.get("imageryStyle") or {}
    medium = imagery_raw.get("primaryMedium")
    imagery = {
        "primaryMedium": medium if medium in IMAGERY_MEDIA else "mixed",
        "secondaryMedia": [m for m in _clean_list(imagery_raw.get("secondaryMedia"), 3) if m in IMAGERY_MEDIA],
        "motifs": _clean_list(imagery_raw.get("motifs"), 6, 60),
        "colorTreatment": _truncate(str(imagery_raw.get("colorTreatment") or ""), 140),
        "ideogramPrompt": _truncate(str(imagery_raw.get("ideogramPrompt") or ""), 420),
        "avoid": _clean_list(imagery_raw.get("avoid"), 6, 60),
    }
    layout_raw = raw.get("layoutTraits") or {}
    layout = {
        "density": layout_raw.get("density") if layout_raw.get("density") in ("airy", "balanced", "dense") else "balanced",
        "cornerRadius": layout_raw.get("cornerRadius") if layout_raw.get("cornerRadius") in ("sharp", "subtle", "rounded", "pill") else _radius_trait(signals),
        "whitespace": layout_raw.get("whitespace") if layout_raw.get("whitespace") in ("generous", "moderate", "tight") else "moderate",
        "composition": _truncate(str(layout_raw.get("composition") or ""), 160),
        "ctaRadiusPx": (signals.get("layout") or {}).get("ctaRadiusPx"),
    }
    return {
        "version": PROFILE_VERSION,
        "name": _truncate(str(raw.get("name") or copy.get("siteName") or kit.get("siteName") or ""), 60),
        "sourceUrl": signals.get("sourceUrl") or kit.get("sourceUrl") or "",
        "tagline": _truncate(str(raw.get("tagline") or copy.get("h1") or ""), 120),
        "businessOverview": _truncate(str(raw.get("businessOverview") or copy.get("metaDescription") or ""), 600),
        "brandValues": _clean_list(raw.get("brandValues"), 6),
        "aesthetic": _clean_list(raw.get("aesthetic"), 6),
        "toneOfVoice": _clean_list(raw.get("toneOfVoice"), 5, 24),
        "keywords": _clean_list(raw.get("keywords"), 10, 40),
        "palette": palette,
        "typography": {"display": display, "body": body},
        "logo": logo,
        "imageryStyle": imagery,
        "layoutTraits": layout,
        "doNots": _clean_list(raw.get("doNots"), 6, 110),
        "visualSummary": _truncate(str(raw.get("visualSummary") or ""), 240),
        "businessDetails": {
            "socialLinks": signals.get("socialLinks") or [],
            "ctaLinks": signals.get("ctaLinks") or [],
        },
    }


# --------------------------------------------------------------------------- heuristic fallback


def _radius_trait(signals: dict[str, Any]) -> str:
    px = (signals.get("layout") or {}).get("ctaRadiusPx")
    if px is None:
        return "subtle"
    if px >= 18:
        return "pill"
    if px >= 8:
        return "rounded"
    if px >= 2:
        return "subtle"
    return "sharp"


def heuristic_palette(signals: dict[str, Any]) -> list[dict[str, Any]]:
    colors = signals.get("colors") or []
    if not colors:
        return [
            {"role": "background", "hex": "#ffffff", "candidateId": "", "source": "default", "verified": False, "name": "White", "usage": "Default background"},
            {"role": "text", "hex": "#111827", "candidateId": "", "source": "default", "verified": False, "name": "Ink", "usage": "Default text"},
            {"role": "primary", "hex": "#2563eb", "candidateId": "", "source": "default", "verified": False, "name": "Blue", "usage": "Default primary"},
            {"role": "accent", "hex": "#0d9488", "candidateId": "", "source": "default", "verified": False, "name": "Teal", "usage": "Default accent"},
        ]

    def with_source(c: dict[str, Any], prefix: str) -> bool:
        return any(s.startswith(prefix) for s in c["sources"])

    def entry(role: str, c: dict[str, Any], usage: str) -> dict[str, Any]:
        return {"role": role, "hex": c["hex"], "candidateId": c["id"], "source": "procedural", "verified": True, "name": "", "usage": usage}

    out: list[dict[str, Any]] = []
    used: set[str] = set()
    bg = next((c for c in colors if with_source(c, "computed:page-background")), None) or max(
        colors, key=lambda c: c["pixelShare"]
    )
    out.append(entry("background", bg, "Page background"))
    used.add(bg["hex"])
    contrasting = [
        c
        for c in colors
        if c["hex"] not in used
        and not c["vivid"]
        and abs(luminance(c["hex"]) - luminance(bg["hex"])) > 0.4
    ]
    text = max(contrasting, key=lambda c: (c.get("textChars", 0), c["score"]), default=None)
    if text:
        out.append(entry("text", text, "Headlines and body"))
        used.add(text["hex"])
    text_only = ("computed:h1", "computed:text", "computed:body-text")
    vivid = [c for c in colors if c["vivid"] and c["hex"] not in used]
    cta_bgs = [
        c
        for c in colors
        if with_source(c, "computed:cta-background")
        and c["hex"] != bg["hex"]
        and delta_e(c["hex"], bg["hex"]) > 10
    ]
    primary = (
        next((c for c in cta_bgs if c["vivid"]), None)
        or next(
            (c for c in vivid if any(_rank_var_name(s) >= 3 for s in c["sources"] if s.startswith("css-var:"))),
            None,
        )
        or (cta_bgs[0] if cta_bgs else None)
        or (vivid[0] if vivid else None)
    )
    if primary:
        out.append(entry("primary", primary, "Calls to action"))
        used.add(primary["hex"])
    rest = [
        c
        for c in vivid
        if c["hex"] not in used and not all(s in text_only for s in c["sources"])
    ] or [c for c in vivid if c["hex"] not in used]
    if primary:
        rest.sort(key=lambda c: (-(_hue_distance(c["hex"], primary["hex"]) > 30), -c["pixelShare"], -c["score"]))
    if rest:
        out.append(entry("accent", rest[0], "Highlights and illustration"))
        used.add(rest[0]["hex"])
        if len(rest) > 1 and _hue_distance(rest[1]["hex"], rest[0]["hex"]) > 30:
            out.append(entry("secondary", rest[1], "Secondary highlights"))
    if not primary:
        fallback = next((c for c in colors if c["hex"] not in used), None)
        if fallback:
            out.append(entry("primary", fallback, "Calls to action"))
    if not any(p["role"] == "accent" for p in out):
        prim = next((p for p in out if p["role"] == "primary"), None)
        if prim:
            out.append({**prim, "role": "accent", "usage": "Highlights"})
    if not any(p["role"] == "text" for p in out):
        dark = "#111827" if luminance(bg["hex"]) > 0.5 else "#f8fafc"
        out.append({"role": "text", "hex": dark, "candidateId": "", "source": "default", "verified": False, "name": "", "usage": "Text"})
    out.sort(key=lambda p: _ROLE_ORDER.get(p["role"], 9))
    return out


def heuristic_aesthetic(signals: dict[str, Any], palette: list[dict[str, Any]]) -> list[str]:
    tags: list[str] = []
    layout = signals.get("layout") or {}
    vivid_px = [p for p in signals.get("pixels") or [] if is_vivid(p["hex"]) and p["share"] >= 0.02]
    hues = {round(_hsv(p["hex"])[0] * 6) for p in vivid_px}
    bg = next((p["hex"] for p in palette if p["role"] == "background"), "#ffffff")
    if layout.get("gradientStops", 0) >= 2 or len(hues) >= 3:
        tags.append("Chromatic Gradients")
    if luminance(bg) < 0.25:
        tags.append("Dark Canvas Contrast")
    elif not vivid_px:
        tags.append("Monochrome Restraint")
    else:
        tags.append("Bright Open Canvas")
    radius = _radius_trait(signals)
    tags.append({"pill": "Soft Pill Forms", "rounded": "Rounded Modules", "subtle": "Crisp Modular Grid", "sharp": "Hard-Edged Geometry"}[radius])
    fonts = signals.get("fonts") or []
    if fonts and re.search(r"serif|garamond|playfair|times|georgia|tiempos|recoleta", fonts[0]["family"], re.I) and "sans" not in fonts[0]["family"].lower():
        tags.append("Editorial Serif Voice")
    else:
        tags.append("Precise Sans Typography")
    return tags[:5]


def heuristic_profile(signals: dict[str, Any], kit: dict[str, Any] | None = None) -> dict[str, Any]:
    """Deterministic profile when no LLM key is configured or the call fails."""
    kit = kit or {}
    copy = signals.get("copy") or {}
    palette = heuristic_palette(signals)
    fonts = signals.get("fonts") or []
    display = next((f for f in fonts if "display" in f["roles"]), fonts[0] if fonts else None)
    body = next((f for f in fonts if "body" in f["roles"]), display)
    logos = signals.get("logos") or []
    tagline = copy.get("h1") or copy.get("ogTitle") or kit.get("tagline") or ""
    tagline = re.split(r"(?<=[.!?])\s", tagline, maxsplit=1)[0]
    raw = {
        "name": copy.get("siteName") or kit.get("siteName") or "",
        "tagline": tagline,
        "businessOverview": copy.get("metaDescription") or "",
        "brandValues": [],
        "aesthetic": heuristic_aesthetic(signals, palette),
        "toneOfVoice": ["Professional"],
        "keywords": [],
        "palette": [{"role": p["role"], "hex": p["hex"], "candidateId": p["candidateId"], "name": p["name"], "usage": p["usage"]} for p in palette],
        "typography": {
            "display": {"family": display["family"] if display else "", "candidateId": display["id"] if display else "", "weights": display["weights"] if display else [], "usage": "Headlines"},
            "body": {"family": body["family"] if body else "", "candidateId": body["id"] if body else "", "weights": body["weights"] if body else [], "usage": "Body copy"},
        },
        "logo": {"candidateId": logos[0]["id"] if logos else "", "backdropHex": (logos[0].get("backdropHex") if logos else "") or "", "variant": "full-color", "notes": ""},
        "imageryStyle": {
            "primaryMedium": "gradients" if "Chromatic Gradients" in heuristic_aesthetic(signals, palette) else "mixed",
            "secondaryMedia": [],
            "motifs": [],
            "colorTreatment": "",
            "ideogramPrompt": "",
            "avoid": [],
        },
        "layoutTraits": {"density": "balanced", "cornerRadius": _radius_trait(signals), "whitespace": "moderate", "composition": ""},
        "doNots": [],
        "visualSummary": "",
    }
    return reconcile_profile(raw, signals, kit)


# --------------------------------------------------------------------------- cache + orchestration


def domain_key(url: str) -> str:
    host = (urlparse(url).netloc or url).lower().split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return re.sub(r"[^a-z0-9.-]", "_", host) or "site"


def cache_paths(url: str, cache_dir: str) -> tuple[str, str]:
    folder = os.path.join(cache_dir, domain_key(url))
    return folder, os.path.join(folder, "profile.json")


def load_cached(url: str, cache_dir: str, *, now: float | None = None) -> dict[str, Any] | None:
    _folder, path = cache_paths(url, cache_dir)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("profileVersion") != PROFILE_VERSION:
        return None
    if (now or time.time()) - float(data.get("createdAtEpoch") or 0) > CACHE_TTL_SEC:
        return None
    return data


def _write_cache(url: str, cache_dir: str, record: dict[str, Any]) -> None:
    folder, path = cache_paths(url, cache_dir)
    os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _resolve_current_color(svg: str, color_hex: str | None) -> str:
    if color_hex and "currentcolor" in svg.lower():
        return re.sub(r"currentColor", color_hex, svg, flags=re.I)
    return svg


def _apply_logo_choice(kit: dict[str, Any], signals: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    from kit_scraper import _sanitize_logo_svg

    chosen = next((lg for lg in signals.get("logos") or [] if lg["id"] == profile["logo"].get("candidateId")), None)
    if not chosen or chosen.get("source") == "static-scrape":
        return kit
    kit = dict(kit)
    if chosen.get("svg"):
        cleaned = _sanitize_logo_svg(_resolve_current_color(chosen["svg"], chosen.get("colorHex")))
        if cleaned and len(cleaned) <= MAX_LOGO_SVG_CHARS:
            kit["logoSvg"] = cleaned
            kit["logoSource"] = "inline-svg"
            kit.pop("logoUrl", None)
    elif chosen.get("url") and chosen.get("source") != "favicon":
        kit["logoUrl"] = chosen["url"]
        kit["logoSource"] = "img"
        kit.pop("logoSvg", None)
    return kit


def _public_path(abs_path: str, repo_root: str | None) -> str:
    if not repo_root:
        return abs_path
    rel = os.path.relpath(abs_path, repo_root).replace(os.sep, "/")
    return "/" + rel


def _screenshots_skipped(capture: dict[str, Any] | None, social: dict[str, Any] | None = None) -> bool:
    """True when Playwright did not run, so Ideogram cannot be shown the site."""
    reason = f"{(capture or {}).get('reason') or ''} {(social or {}).get('reason') or ''}"
    if "playwright" in reason.casefold():
        return True
    if (capture or {}).get("available") or (social or {}).get("available"):
        return False
    ok, _why = playwright_available()
    return not ok


def _component_vision(paths: list[str]) -> list[str] | None:
    """Claude picks up to two graphic crops. A miss returns None so the pixel filter stands."""
    provider = resolve_llm_provider()
    if provider != "anthropic" or not paths:
        return None
    api_key = api_key_for_provider(provider)
    if not api_key:
        return None
    content: list[dict[str, Any]] = []
    for index, path in enumerate(paths):
        loaded = _load_image_for_vision(path, max_edge=768)
        if not loaded:
            continue
        data, media, _size = loaded
        content.append({"type": "text", "text": f"Image {index}"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": media, "data": data}})
    if not content:
        return None
    content.append(
        {
            "type": "text",
            "text": (
                "These are cropped website components. Pick up to two that are graphic assets "
                "(hero art, an illustration, a product graphic). Skip any crop that is mostly UI text. "
                'Reply with JSON only: {"keep": [0]} using the image indexes.'
            ),
        }
    )
    try:
        payload = _post_json(
            f"{ANTHROPIC_API_BASE}/messages",
            {
                "model": resolve_llm_model(provider),
                "max_tokens": 200,
                "messages": [{"role": "user", "content": content}],
            },
            _anthropic_request_headers(api_key),
        )
        text = ""
        for block in payload.get("content") or []:
            if block.get("type") == "text":
                text += str(block.get("text") or "")
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return None
        keep = json.loads(match.group(0)).get("keep") or []
        chosen = []
        for index in keep:
            if isinstance(index, int) and 0 <= index < len(paths):
                chosen.append(paths[index])
        return chosen[:5] or None
    except Exception:  # noqa: BLE001 — pixel filter already removed page text
        return None


def _attach_ideogram_packet(
    result: dict[str, Any],
    profile: dict[str, Any],
    kit: dict[str, Any],
    capture: dict[str, Any] | None,
    folder: str,
    social: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from ideogram_packet import build_ideogram_packet, choose_component_crops

    shots = (capture or {}).get("screenshots") or {}
    components = [value for key, value in shots.items() if str(key).startswith("component") and value]
    pages = [value for key, value in shots.items() if value and not str(key).startswith("component")]
    for visit in (social or {}).get("visits") or []:
        shot = visit.get("screenshot") if isinstance(visit, dict) else ""
        if shot and shot not in pages:
            pages.append(shot)
    skipped = _screenshots_skipped(capture, social)
    if skipped:
        paths: list[str] = []
    elif components:
        paths = choose_component_crops(components, vision_fn=_component_vision if resolve_llm_provider() else None)
        if not paths:
            paths = pages
    else:
        paths = pages
    packet = build_ideogram_packet(
        profile,
        kit,
        image_paths=paths,
        screenshots_skipped=skipped,
        out_dir=os.path.join(folder, "ideogram-refs"),
    )
    profile["ideogramPacket"] = packet
    kit["ideogramPacket"] = packet
    result["ideogramPacket"] = packet
    if packet.get("statusLine"):
        result["statusLine"] = packet["statusLine"]
    return packet


def analyze_brand(
    url: str,
    *,
    cache_dir: str,
    kit: dict[str, Any] | None = None,
    scrape_fn: Callable[[str], dict[str, Any]] | None = None,
    capture_fn: Callable[..., dict[str, Any]] | None = None,
    llm_fn: Callable[[dict[str, Any], list[dict[str, Any]]], dict[str, Any]] | None = None,
    refresh: bool = False,
    mobile: bool = True,
    use_capture: bool = True,
    repo_root: str | None = None,
) -> dict[str, Any]:
    """Full hybrid analysis with per-domain cache. Returns the API payload."""
    if not refresh:
        cached = load_cached(url, cache_dir)
        stale_fallback = (
            cached is not None
            and cached["result"].get("source") == "fallback"
            and llm_fn is None
            and resolve_llm_provider() is not None
        )
        if cached and not stale_fallback:
            return {**cached["result"], "cached": True}
    if kit is None:
        if not scrape_fn:
            raise ValueError("analyze_brand needs kit or scrape_fn")
        kit = scrape_fn(url)
    kit = dict(kit or {})
    folder, _path = cache_paths(url, cache_dir)
    capture: dict[str, Any]
    if use_capture:
        capture = (capture_fn or capture_site)(url, folder, mobile=mobile)
    else:
        capture = {"available": False, "reason": "capture disabled"}
    shots = capture.get("screenshots") or {}
    pixels = pixel_palette(shots.get("desktopFold"))
    signals = build_signals(kit, capture, pixels)
    images = vision_images(shots)

    result: dict[str, Any] = {
        "capture": {
            "available": bool(capture.get("available")),
            "reason": capture.get("reason") or "",
            "durationSec": capture.get("durationSec"),
            "screenshots": {k: _public_path(v, repo_root) for k, v in shots.items()},
        },
        "estimatedImageTokens": estimate_image_tokens(images),
    }
    try:
        llm = (llm_fn or call_vision_llm)(signals, images)
        profile = reconcile_profile(llm["raw"], signals, kit)
        usage = llm.get("usage") or {}
        result.update(
            {
                "source": "llm",
                "model": llm.get("model"),
                "provider": llm.get("provider"),
                "usage": usage,
                "costUsd": cost_usd(usage),
            }
        )
    except LookupError as exc:
        profile = heuristic_profile(signals, kit)
        result.update({"source": "fallback", "fallbackReason": str(exc)})
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, ValueError, TimeoutError, OSError) as exc:
        profile = heuristic_profile(signals, kit)
        result.update(
            {
                "source": "fallback",
                "fallbackReason": "llm_error",
                "errorDetail": _safe_error_detail(exc, provider=resolve_llm_provider()),
            }
        )
    profile["analysis"] = {
        "source": result["source"],
        "model": result.get("model") or "",
        "analyzedAt": datetime.now(timezone.utc).isoformat(),
        "rendered": bool(capture.get("available")),
    }
    kit = _apply_logo_choice(kit, signals, profile)
    _attach_ideogram_packet(result, profile, kit, capture, folder)
    kit["brandProfile"] = profile
    result["brandProfile"] = profile
    result["kit"] = kit
    result["signals"] = {
        "colors": [{k: c[k] for k in ("id", "hex", "sources", "pixelShare")} for c in signals["colors"][:16]],
        "fonts": [{k: f[k] for k in ("id", "family", "weights", "roles")} for f in signals["fonts"][:8]],
        "logos": [{k: lg.get(k) for k in ("id", "kind", "source", "label", "backdropHex")} for lg in signals["logos"]],
    }
    _write_cache(
        url,
        cache_dir,
        {"profileVersion": PROFILE_VERSION, "createdAtEpoch": time.time(), "url": url, "result": result},
    )
    result["cached"] = False
    return result


def _bundle_schema() -> dict[str, Any]:
    from communication_kit import COMMUNICATION_KIT_JSON_SCHEMA
    from social_capture import SOCIAL_FORMATS

    social = _strict_object(
        {
            "voice": _str(),
            "formats": {"type": "array", "items": {"type": "string", "enum": list(SOCIAL_FORMATS)}},
            "doNotInvent": _str_list(),
            "notes": _str(),
        }
    )
    properties = dict(BRAND_PROFILE_JSON_SCHEMA["properties"])
    properties["socialStrategy"] = social
    properties["communicationKit"] = COMMUNICATION_KIT_JSON_SCHEMA
    return _strict_object(properties)


def _merge_social(model_raw: dict[str, Any] | None, capture: dict[str, Any] | None) -> dict[str, Any]:
    from social_capture import SOCIAL_FORMATS, strategy_from_capture

    strategy = strategy_from_capture(capture)
    raw = (model_raw or {}).get("socialStrategy") if isinstance(model_raw, dict) else None
    if isinstance(raw, dict):
        voice = str(raw.get("voice") or "").strip()
        if voice:
            strategy["voice"] = voice[:240]
        formats = [f for f in (raw.get("formats") or []) if f in SOCIAL_FORMATS]
        if formats:
            strategy["formats"] = formats
        extra = [str(item).strip() for item in (raw.get("doNotInvent") or []) if str(item).strip()]
        strategy["doNotInvent"] = list(dict.fromkeys([*strategy["doNotInvent"], *extra]))[:8]
        note = str(raw.get("notes") or "").strip()
        if note:
            strategy["notes"] = (strategy["notes"] + " " + note).strip()[:500]
    return strategy


def _capture_brand_inputs(
    url: str,
    folder: str,
    *,
    kit: dict[str, Any] | None,
    scrape_fn: Callable[[str], dict[str, Any]] | None,
    mobile: bool,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Site scrape, site screenshots and public social screenshots at the same time."""
    from concurrent.futures import ThreadPoolExecutor

    from social_capture import capture_public_social

    social_dir = os.path.join(folder, "social")
    links = list((kit or {}).get("socialLinks") or [])
    name = str((kit or {}).get("siteName") or "")

    def _scrape() -> dict[str, Any]:
        if kit is not None or not scrape_fn:
            return dict(kit or {})
        return scrape_fn(url)

    with ThreadPoolExecutor(max_workers=3) as pool:
        scraped = pool.submit(_scrape)
        site = pool.submit(capture_site, url, folder, mobile=mobile)
        social = pool.submit(
            capture_public_social, url, social_dir, social_links=links, site_name=name
        )
        kit_out = scraped.result()
        site_out = site.result()
        social_out = social.result()
    return kit_out, site_out, social_out


def analyze_brand_bundle(
    url: str,
    *,
    cache_dir: str,
    kit: dict[str, Any] | None = None,
    scrape_fn: Callable[[str], dict[str, Any]] | None = None,
    refresh: bool = False,
    mobile: bool = True,
    repo_root: str | None = None,
    llm_fn: Callable[[dict[str, Any], list[dict[str, Any]], dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """One cached Opus call: brand profile, communication kit and socialStrategy.

    Capture (scrape, site screenshots, public social screenshots) runs in parallel
    before that single call. A cache hit within 7 days costs nothing and makes no call.
    """
    from communication_kit import (
        CACHE_TTL_SEC as KIT_TTL,
        cost_usd as brand_cost,
        design_fallback,
        reconcile_kit,
        resolve_brand_model,
    )

    folder, path = cache_paths(url, cache_dir)
    if not refresh and os.path.isfile(path):
        cached = load_cached(url, cache_dir)
        if cached and (cached["result"].get("brandProfile") or {}).get("socialStrategy") is not None:
            if (cached["result"].get("kit") or {}).get("communicationKit"):
                return {**cached["result"], "cached": True}
    os.makedirs(folder, exist_ok=True)
    kit_out, capture, social = _capture_brand_inputs(
        url, folder, kit=kit, scrape_fn=scrape_fn, mobile=mobile
    )
    kit_out = dict(kit_out or {})
    shots = capture.get("screenshots") or {}
    for visit in social.get("visits") or []:
        if visit.get("screenshot"):
            shots.setdefault(f"social-{visit.get('platform')}", visit["screenshot"])
    pixels = pixel_palette(shots.get("desktopFold"))
    signals = build_signals(kit_out, capture, pixels)
    raw: dict[str, Any] | None = None
    images = vision_images(capture.get("screenshots") or {})
    for visit in social.get("visits") or []:
        loaded = _load_image_for_vision(visit.get("screenshot") or "")
        if not loaded:
            continue
        data, media, size = loaded
        images.append(
            {
                "key": f"social-{visit.get('platform')}",
                "label": f"Public {visit.get('platform')} page ({visit.get('status')})",
                "data": data,
                "mediaType": media,
                "size": size,
            }
        )
    try:
        llm = (llm_fn or call_brand_bundle_llm)(signals, images, social)
        raw = llm["raw"]
        profile = reconcile_profile(raw, signals, kit_out)
        designed = reconcile_kit(raw.get("communicationKit"), kit_out, profile)
        usage = llm.get("usage") or {}
        source = "llm"
        model = llm.get("model") or resolve_brand_model()
        cost = brand_cost(usage)
    except LookupError:
        profile = heuristic_profile(signals, kit_out)
        designed = design_fallback(kit_out, profile)
        usage = {}
        source = "fallback"
        model = ""
        cost = 0.0
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, ValueError, TimeoutError, OSError):
        profile = heuristic_profile(signals, kit_out)
        designed = design_fallback(kit_out, profile)
        usage = {}
        source = "fallback"
        model = ""
        cost = 0.0
    profile["socialStrategy"] = _merge_social(raw if source == "llm" else None, social)  # type: ignore[name-defined]
    designed = dict(designed)
    designed["bundled"] = True
    designed["version"] = 2
    profile["analysis"] = {
        "source": source,
        "model": model,
        "analyzedAt": datetime.now(timezone.utc).isoformat(),
        "rendered": bool(capture.get("available")),
        "calls": 1 if source == "llm" else 0,
    }
    kit_out = _apply_logo_choice(kit_out, signals, profile)
    kit_out["brandProfile"] = profile
    kit_out["communicationKit"] = designed
    if shots:
        kit_out["screenshotPaths"] = {k: _public_path(v, repo_root) for k, v in shots.items() if v}
    result = {
        "capture": {
            "available": bool(capture.get("available")),
            "reason": capture.get("reason") or "",
            "durationSec": capture.get("durationSec"),
            "screenshots": {k: _public_path(v, repo_root) for k, v in (capture.get("screenshots") or {}).items()},
        },
        "social": {
            "available": bool(social.get("available")),
            "reason": social.get("reason") or "",
            "visits": [
                {k: v.get(k) for k in ("platform", "url", "finalUrl", "status", "note")}
                for v in (social.get("visits") or [])
            ],
        },
        "source": source,
        "model": model,
        "usage": usage,
        "costUsd": cost,
        "brandProfile": profile,
        "communicationKit": designed,
        "kit": kit_out,
        "cached": False,
        "cacheTtlSec": KIT_TTL,
    }
    _attach_ideogram_packet(result, profile, kit_out, capture, folder, social=social)
    _write_cache(
        url,
        cache_dir,
        {"profileVersion": PROFILE_VERSION, "createdAtEpoch": time.time(), "url": url, "result": result},
    )
    return result


def call_brand_bundle_llm(
    signals: dict[str, Any],
    images: list[dict[str, Any]],
    social: dict[str, Any],
) -> dict[str, Any]:
    """Single Opus call. Poster briefs stay on the Sonnet creative-brief model."""
    from communication_kit import resolve_brand_model

    provider = resolve_llm_provider()
    if not provider:
        raise LookupError("no_provider")
    api_key = api_key_for_provider(provider)
    if not api_key:
        raise LookupError("no_api_key")
    model = resolve_brand_model(provider)
    schema = _bundle_schema()
    social_note = _merge_social(None, social)["notes"]
    extra = (
        "\n\nAlso fill socialStrategy and communicationKit in the same response. "
        "socialStrategy.voice is how the brand speaks on its public social posts, or empty if those pages were a login wall. "
        "formats are the recurring post shapes you can actually see (type-only, photo-card, character-scene, product-ui, communique, gradient-field). "
        "doNotInvent lists what a poster must not make up (prices, dates, statistics, news, costumes that are not in the logo). "
        "notes may quote only what is visible. "
        f"Public social capture: {social_note}\n"
        "communicationKit formalises the same identity: thinSite, sector, colours, type pairing, imagery and layout. "
        "devices must be an empty array. Do not invent a second logo or a news event."
    )
    content: list[dict[str, Any]] = []
    for i, img in enumerate(images, 1):
        content.append({"type": "text", "text": f"Image {i}: {img['label']}"})
        content.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": img["mediaType"], "data": img["data"]},
            }
        )
    content.append({"type": "text", "text": _vision_instructions(signals, has_images=bool(images)) + extra})
    if provider == "anthropic":
        body = {
            "model": model,
            "max_tokens": 4000,
            "system": _VISION_SYSTEM.replace("submit_brand_profile", "submit_brand_bundle"),
            "messages": [{"role": "user", "content": content}],
            "tools": [
                {
                    "name": "submit_brand_bundle",
                    "description": "Submit the brand profile, communication kit and social strategy together.",
                    "input_schema": schema,
                    "strict": True,
                }
            ],
            "tool_choice": {"type": "auto"},
        }
        payload = _post_json(
            f"{ANTHROPIC_API_BASE}/messages", body, _anthropic_request_headers(api_key)
        )
        usage_raw = payload.get("usage") or {}
        usage = {
            "inputTokens": int(usage_raw.get("input_tokens") or 0),
            "outputTokens": int(usage_raw.get("output_tokens") or 0),
        }
        for block in payload.get("content") or []:
            if block.get("type") == "tool_use" and block.get("name") == "submit_brand_bundle":
                if isinstance(block.get("input"), dict):
                    return {"raw": block["input"], "usage": usage, "model": model, "provider": provider}
        raise ValueError("Anthropic response missing submit_brand_bundle tool output")
    text_content: list[dict[str, Any]] = []
    for i, img in enumerate(images, 1):
        text_content.append({"type": "text", "text": f"Image {i}: {img['label']}"})
        text_content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{img['mediaType']};base64,{img['data']}"},
            }
        )
    text_content.append({"type": "text", "text": _vision_instructions(signals, has_images=bool(images)) + extra})
    body = {
        "model": model,
        "temperature": 0.3,
        "max_tokens": 4000,
        "messages": [
            {"role": "system", "content": "Return one JSON object for the brand bundle."},
            {"role": "user", "content": text_content},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "brand_bundle", "strict": True, "schema": schema},
        },
    }
    base = OPENROUTER_API_BASE if provider == "openrouter" else OPENAI_API_BASE
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = _post_json(f"{base}/chat/completions", body, headers)
    u = payload.get("usage") or {}
    usage = {
        "inputTokens": int(u.get("prompt_tokens") or 0),
        "outputTokens": int(u.get("completion_tokens") or 0),
    }
    text = str(((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("LLM response was not a JSON object")
    return {"raw": data, "usage": usage, "model": model, "provider": provider}


# --------------------------------------------------------------------------- downstream hooks


def _profile(kit_or_profile: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(kit_or_profile, dict):
        return None
    if isinstance(kit_or_profile.get("brandProfile"), dict):
        return kit_or_profile["brandProfile"]
    if "palette" in kit_or_profile and "typography" in kit_or_profile:
        return kit_or_profile
    return None


def _palette_hex(profile: dict[str, Any], role: str) -> str | None:
    for p in profile.get("palette") or []:
        if p.get("role") == role and normalize_hex(p.get("hex")):
            return normalize_hex(p["hex"])
    return None


def apply_brand_profile_to_kit(kit: dict[str, Any] | None) -> dict[str, Any]:
    """Project an (edited) ``kit.brandProfile`` onto legacy kit fields the poster stack reads.

    Idempotent; kits without a profile are returned unchanged.
    """
    kit = dict(kit or {})
    profile = _profile(kit)
    if not profile:
        return kit
    ordered = [_palette_hex(profile, r) for r in ("primary", "accent", "secondary", "background", "text", "surface")]
    ordered = [c for c in ordered if c]
    if ordered:
        rest = [c for c in (kit.get("colors") or []) if normalize_hex(c) not in ordered]
        kit["colors"] = (ordered + rest)[:8]
        kit["accentColors"] = [c for c in ordered if is_vivid(c)][:4] or ordered[:2]
    typo = profile.get("typography") or {}
    families = [
        str((typo.get(role) or {}).get("family") or "").strip() for role in ("display", "body")
    ]
    families = [f for i, f in enumerate(families) if f and f not in families[:i]]
    if families:
        kit["fonts"] = (families + [f for f in kit.get("fonts") or [] if f not in families])[:6]
    if str(profile.get("tagline") or "").strip():
        kit["tagline"] = profile["tagline"].strip()
    if str(profile.get("name") or "").strip():
        kit["siteName"] = profile["name"].strip()
    return kit


def brand_profile_prompt_lines(profile_or_kit: dict[str, Any] | None) -> list[str]:
    """Extra lines for the creative-brief kit summary."""
    profile = _profile(profile_or_kit)
    if not profile:
        return []
    palette = ", ".join(
        f"{p.get('role')} {p.get('hex')}" for p in profile.get("palette") or [] if p.get("hex")
    )
    typo = profile.get("typography") or {}
    imagery = profile.get("imageryStyle") or {}
    layout = profile.get("layoutTraits") or {}
    lines = [
        "brandProfile (AI + vision, user-reviewed):",
        f"  palette roles: {palette or '(none)'}",
        f"  typography: display {(typo.get('display') or {}).get('family') or '?'} / body {(typo.get('body') or {}).get('family') or '?'}",
        f"  aesthetic: {', '.join(profile.get('aesthetic') or []) or '(none)'}",
        f"  toneOfVoice: {', '.join(profile.get('toneOfVoice') or []) or '(none)'}",
        f"  brandValues: {', '.join(profile.get('brandValues') or []) or '(none)'}",
        f"  imageryStyle: {imagery.get('primaryMedium') or '?'}; motifs: {', '.join(imagery.get('motifs') or []) or '(none)'}; {imagery.get('colorTreatment') or ''}".rstrip("; "),
        f"  layoutTraits: {layout.get('density') or '?'} density, {layout.get('cornerRadius') or '?'} corners, {layout.get('whitespace') or '?'} whitespace",
    ]
    if profile.get("doNots"):
        lines.append(f"  doNots: {'; '.join(profile['doNots'])}")
    if imagery.get("ideogramPrompt"):
        lines.append(f"  imageArtDirection: {imagery['ideogramPrompt']}")
    lines.append(
        "  Use this profile's aesthetic, imageryStyle and palette hexes in heroImagePrompt / accentImagePrompt; match toneOfVoice in copy."
    )
    return lines


IDEOGRAM_PROMPT_MAX_CHARS = 1000


def augment_ideogram_prompt(
    prompt: str, profile_or_kit: dict[str, Any] | None, *, role: str = "background"
) -> str:
    """Append brand visual language (aesthetic + imageryStyle + palette) to an Ideogram prompt."""
    prompt = (prompt or "").strip()
    profile = _profile(profile_or_kit)
    if not profile or not prompt:
        return prompt
    lower = prompt.lower()
    extras: list[str] = []
    imagery = profile.get("imageryStyle") or {}
    aesthetic = [a for a in profile.get("aesthetic") or [] if a.lower() not in lower]
    if aesthetic:
        extras.append("Brand visual language: " + ", ".join(aesthetic[:5]))
    medium = imagery.get("primaryMedium")
    motifs = [m for m in imagery.get("motifs") or [] if m.lower() not in lower]
    if medium and medium not in ("mixed", "product-ui", "typographic"):
        extras.append(f"medium: {medium.replace('-', ' ')}")
    if motifs:
        extras.append("motifs: " + ", ".join(motifs[:4]))
    if imagery.get("colorTreatment") and imagery["colorTreatment"].lower() not in lower:
        extras.append(imagery["colorTreatment"])
    hexes = [
        p["hex"]
        for p in profile.get("palette") or []
        if p.get("hex") and p.get("role") in ("primary", "accent", "secondary", "background") and p["hex"].lower() not in lower
    ]
    if hexes:
        extras.append("palette " + ", ".join(hexes[:4]))
    if role == "background" and imagery.get("ideogramPrompt") and imagery["ideogramPrompt"][:40].lower() not in lower:
        extras.append(imagery["ideogramPrompt"])
    avoid = [a for a in imagery.get("avoid") or [] if a.lower() not in lower]
    if avoid:
        extras.append("avoid: " + ", ".join(avoid[:4]))
    if not extras:
        return prompt
    combined = prompt.rstrip(". ") + ". " + ". ".join(extras)
    return _truncate(combined, IDEOGRAM_PROMPT_MAX_CHARS)
