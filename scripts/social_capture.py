"""Public social pages for a brand profile. No login, no cookies, no bypass.

Instagram and LinkedIn often answer with a login wall. That is recorded and the
capture moves on. Screenshots of a wall are not sent to the brand model.
"""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlparse

SOCIAL_FORMATS = (
    "type-only",
    "photo-card",
    "character-scene",
    "product-ui",
    "communique",
    "gradient-field",
)

_DO_NOT_INVENT = (
    "prices",
    "dates",
    "statistics",
    "news events",
    "mascot costumes that are not in the logo",
)

_WALL = re.compile(
    r"log in to instagram|login • instagram|sign up for instagram|"
    r"join linkedin|sign in \| linkedin|authwall|"
    r"log in \| linkedin|this page requires you to log in",
    re.I,
)


def brand_slug(site_url: str, site_name: str = "") -> str:
    host = (urlparse(site_url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    slug = host.split(".")[0] if host else ""
    if slug in ("", "www", "localhost"):
        slug = re.sub(r"[^a-z0-9]", "", (site_name or "").lower())
    return slug


def public_social_targets(
    site_url: str,
    social_links: list[str] | None = None,
    site_name: str = "",
) -> list[dict[str, str]]:
    """Public profile URLs only. Handles come from the domain and from links on the site."""
    targets: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(platform: str, url: str) -> None:
        clean = (url or "").split("?")[0].strip()
        if not clean.startswith("http"):
            return
        key = clean.rstrip("/").casefold()
        if key in seen:
            return
        seen.add(key)
        targets.append({"platform": platform, "url": clean if clean.endswith("/") else clean})

    slug = brand_slug(site_url, site_name)
    if slug:
        add("instagram", f"https://www.instagram.com/{slug}/")
        add("linkedin", f"https://www.linkedin.com/company/{slug}/posts/")
    for link in social_links or []:
        low = str(link).lower()
        if "instagram.com" in low:
            add("instagram", str(link))
        elif "linkedin.com" in low:
            add("linkedin", str(link))
    return targets[:4]


def page_status(final_url: str, title: str, text: str) -> str:
    """``loaded``, ``partial`` (a wall plus some public posts), or ``login-wall``."""
    final = (final_url or "").lower()
    # A redirect onto the login or auth wall is the wall, even if the form is long.
    if any(token in final for token in ("/accounts/login", "/authwall", "authwall", "/login")):
        return "login-wall"
    blob = f"{final}\n{title}\n{(text or '')[:2000]}"
    if not _WALL.search(blob):
        return "loaded"
    if len(text or "") > 700:
        return "partial"
    return "login-wall"


def empty_social_strategy(note: str = "") -> dict[str, Any]:
    return {
        "voice": "",
        "formats": [],
        "doNotInvent": list(_DO_NOT_INVENT),
        "notes": note,
        "sources": [],
    }


def strategy_from_capture(capture: dict[str, Any] | None) -> dict[str, Any]:
    """Factual record of what the public pages returned. Formats stay empty until a model sees posts."""
    visits = (capture or {}).get("visits") or []
    sources = [
        {"platform": v.get("platform") or "", "url": v.get("url") or "", "status": v.get("status") or "error"}
        for v in visits
        if isinstance(v, dict)
    ]
    walls = [s for s in sources if s["status"] == "login-wall"]
    partial = [s for s in sources if s["status"] == "partial"]
    loaded = [s for s in sources if s["status"] == "loaded"]
    bits = []
    if walls:
        bits.append(
            "Login wall on " + ", ".join(f"{s['platform']} ({s['url']})" for s in walls) + ". No posts were read there."
        )
    if partial:
        bits.append("A login prompt covered part of " + ", ".join(s["platform"] for s in partial) + ".")
    if loaded:
        bits.append("Public page loaded for " + ", ".join(s["platform"] for s in loaded) + ".")
    if not sources:
        bits.append("No public social page was opened.")
    strategy = empty_social_strategy(" ".join(bits))
    strategy["sources"] = sources
    return strategy


def capture_public_social(
    site_url: str,
    out_dir: str,
    *,
    social_links: list[str] | None = None,
    site_name: str = "",
    timeout_ms: int = 20_000,
) -> dict[str, Any]:
    """Screenshot public Instagram and LinkedIn pages. A fresh browser, no stored cookies."""
    from brand_profile import _launch_browser, playwright_available

    targets = public_social_targets(site_url, social_links, site_name)
    ok, reason = playwright_available()
    if not ok:
        return {"available": False, "reason": reason, "visits": [], "targets": targets}
    from playwright.sync_api import sync_playwright

    os.makedirs(out_dir, exist_ok=True)
    visits: list[dict[str, Any]] = []
    try:
        with sync_playwright() as p:
            browser = _launch_browser(p)
            try:
                for index, target in enumerate(targets):
                    visits.append(_visit(browser, target, out_dir, index, timeout_ms))
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 — a failed browser is a recorded miss, not a crash
        return {
            "available": False,
            "reason": str(exc).splitlines()[0][:200],
            "visits": visits,
            "targets": targets,
        }
    return {"available": True, "reason": "", "visits": visits, "targets": targets}


def _visit(browser: Any, target: dict[str, str], out_dir: str, index: int, timeout_ms: int) -> dict[str, Any]:
    context = browser.new_context(
        viewport={"width": 1280, "height": 900},
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
        ),
        # No storage_state and no extra cookies. Do not click Log in.
        locale="en-US",
    )
    page = context.new_page()
    status = "error"
    note = ""
    shot = ""
    final_url = target["url"]
    title = ""
    try:
        page.goto(target["url"], wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(1200)
        final_url = page.url
        title = page.title() or ""
        text = ""
        try:
            text = page.inner_text("body")[:4000]
        except Exception:  # noqa: BLE001
            text = ""
        status = page_status(final_url, title, text)
        if status != "login-wall":
            shot_path = os.path.join(out_dir, f"social-{index}-{target['platform']}.jpg")
            page.screenshot(path=shot_path, type="jpeg", quality=70)
            shot = shot_path
        note = title[:140]
    except Exception as exc:  # noqa: BLE001
        status = "error"
        note = str(exc).splitlines()[0][:180]
    finally:
        context.close()
    return {
        "platform": target["platform"],
        "url": target["url"],
        "finalUrl": final_url,
        "status": status,
        "title": title[:160],
        "note": note,
        "screenshot": shot,
    }
