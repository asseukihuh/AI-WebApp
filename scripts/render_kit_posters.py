#!/usr/bin/env python3
"""Before/after LinkedIn posters for the communication-kit pipeline.

Writes PNGs for BDS IG2I, Stripe and Vercel. ``--out-dir`` defaults to a local
``generated/kit-v7`` folder. Offline: devices come from the sector heuristic
unless an API key is configured.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from communication_kit import design_fallback, ensure_communication_kit  # noqa: E402
from kit_scraper import scrape_kit_from_page  # noqa: E402


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "CommMaker-KitRender/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def _crest_svg(raw: str) -> str:
    """Drop the XML prolog and the favicon's embedded background plate."""
    import re

    start = raw.lower().find("<svg")
    text = raw[start:] if start >= 0 else raw
    text = re.sub(r"<image\b[^>]*/>", "", text, flags=re.I)
    text = re.sub(r"<image\b[^>]*>.*?</image>", "", text, flags=re.I | re.S)
    return text


def bds_kit() -> dict:
    url = "https://bds-ig2i.fr/"
    html = _fetch(url).decode("utf-8", "replace")
    kit = scrape_kit_from_page(html, url)
    logo = str(kit.get("logoSvg") or "")
    if not logo.strip().startswith("<svg"):
        for logo_url in (
            kit.get("faviconUrl"),
            "https://bds-ig2i.fr/favicon.svg",
            "https://bds-ig2i.fr/assets/bds-logo-CkH18Anw.svg",
        ):
            if not logo_url:
                continue
            if str(logo_url).startswith("/"):
                logo_url = "https://bds-ig2i.fr" + str(logo_url)
            try:
                data = _fetch(str(logo_url))
            except OSError:
                continue
            if b"<svg" in data[:400]:
                kit["logoSvg"] = _crest_svg(data.decode("utf-8", "replace"))
                kit["logoUrl"] = None
                break
    return kit


def main() -> None:
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "generated", "kit-v7")
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, SCRIPT_DIR)
    import photocraft_cli
    from render_poster_samples import STRIPE_BRIEF_BASE, STRIPE_SESSION, VERCEL_BRIEF_BASE, VERCEL_SESSION, render_case

    cli = photocraft_cli.find_cli(ROOT) or photocraft_cli.ensure_cli(ROOT)
    if not cli:
        sys.exit("photocraft-cli not available")

    fixtures = os.path.join(SCRIPT_DIR, "fixtures")
    with open(os.path.join(fixtures, "kit-stripe.json"), encoding="utf-8") as handle:
        stripe = json.load(handle)
    with open(os.path.join(fixtures, "kit-vercel.json"), encoding="utf-8") as handle:
        vercel = json.load(handle)
    bds = bds_kit()
    cache = os.path.join(ROOT, "generated", "communication-kits")
    # Prefer the model when a key is configured; otherwise the sector heuristic.
    bds = ensure_communication_kit(bds, cache_dir=cache, allow_llm=True)
    stripe_after = ensure_communication_kit(stripe, cache_dir=cache, allow_llm=True)
    vercel_after = ensure_communication_kit(vercel, cache_dir=cache, allow_llm=True)

    bds_session = {
        "suggestedHeadline": "Soirée sport",
        "brief": {"headline": "Soirée sport", "facts": "Vendredi 20 h au gymnase.\n"},
    }
    bds_brief = {
        "headline": "Soirée sport",
        "subhead": "Vendredi 20 h au gymnase.",
        "cta": "Je viens",
        "eyebrow": "BDS IG2I",
        "layoutRecipe": "gradient-brand",
        "heroStrategy": "gradient_from_palette",
        "logoTreatment": "wordmark-white",
        "emphasis": "celebratory",
        "headlineScale": "xl",
        "headlineWeight": "extrabold",
        "ctaStyle": "pill",
        "rationale": "Thin-site kit render.",
    }
    cases = [
        ("bds-ig2i-before", {**bds, "communicationKit": None}, bds_session, {**bds_brief, "layoutTemplate": "centered-statement"}, None),
        ("bds-ig2i-after", bds, bds_session, {**bds_brief, "layoutTemplate": "device-stage"}, None),
        ("stripe-before", {**stripe, "communicationKit": None}, STRIPE_SESSION, {**STRIPE_BRIEF_BASE, "layoutTemplate": "full-bleed-scrim"}, "warm-silk"),
        ("stripe-after", stripe_after, STRIPE_SESSION, {**STRIPE_BRIEF_BASE, "layoutTemplate": "full-bleed-scrim"}, "warm-silk"),
        ("vercel-before", {**vercel, "communicationKit": None}, VERCEL_SESSION, {**VERCEL_BRIEF_BASE, "layoutTemplate": "centered-statement"}, None),
        ("vercel-after", vercel_after, VERCEL_SESSION, {**VERCEL_BRIEF_BASE, "layoutTemplate": "centered-statement"}, None),
    ]
    # design_fallback is what ensure uses without a key; keep the import live for the name check.
    assert design_fallback({"siteName": "x"})["devices"]
    results = []
    for name, kit, session, brief, background in cases:
        case = {
            "name": name,
            "kit": kit,
            "session": session,
            "brief": brief,
            "background": background,
            "brandProfile": kit.get("brandProfile"),
            "before": True,
        }
        rendered = render_case(ROOT, case, cli=cli, out_dir=out_dir, label="kit", use_ideogram=False)
        src = rendered["png"]
        dest = os.path.join(out_dir, f"{name}.png")
        if os.path.abspath(src) != os.path.abspath(dest):
            os.replace(src, dest)
        rendered["png"] = dest
        results.append(rendered)
        print(name, rendered.get("designAudit"), rendered.get("failedChecks"), rendered.get("layoutTemplate"))
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2)
    from communication_kit import render_kit_assets

    render_kit_assets(bds.get("communicationKit") or {}, os.path.join(out_dir, "bds-devices"), logo_svg=str(bds.get("logoSvg") or ""))
    preview = {"communicationKit": bds.get("communicationKit"), "siteName": bds.get("siteName"), "sourceUrl": bds.get("sourceUrl")}
    with open(os.path.join(out_dir, "bds-kit.json"), "w", encoding="utf-8") as handle:
        json.dump(preview, handle)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
