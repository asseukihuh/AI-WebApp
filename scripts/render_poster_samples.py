"""Render sample LinkedIn posters (Stripe + Vercel) to .pcraft + PNG for design review.

Usage::

    python3 scripts/render_poster_samples.py --out-dir /tmp/posters
    python3 scripts/render_poster_samples.py --code-root /path/to/main-worktree --before --out-dir /tmp/posters

Offline by default: backgrounds are procedural stand-ins for Ideogram output (``standin-*.png``)
that follow the per-template negative-space composition. With ``--ideogram`` and
``IDEOGRAM_API_KEY`` set, real Ideogram 4 backgrounds are generated instead.

``--code-root`` imports ``poster_compiler`` from another checkout (e.g. a ``git worktree`` of
``main``) so before/after renders share identical inputs.
"""

from __future__ import annotations

import argparse
import inspect
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import zlib
from typing import Any, Callable

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(SCRIPT_DIR, "fixtures")
W, H = 1200, 627

STRIPE_SESSION = {
    "suggestedHeadline": "New Stripe pricing plan for students",
    "brief": {
        "headline": "New Stripe pricing plan for students",
        "facts": "A pricing plan designed for students is now available.\nSee the details on stripe.com/students.",
        "tone": "celebratory",
    },
}
VERCEL_SESSION = {
    "suggestedHeadline": "Build minutes restored for all teams",
    "brief": {
        "headline": "Build minutes restored for all teams",
        "facts": "Builds queued during the incident have completed.\nNo action is needed on your side.",
        "tone": "calm",
    },
}

STRIPE_BRIEF_BASE = {
    "headline": "New pricing plan for students",
    "subhead": "Student founders now get reduced fees and free payouts for their first year.",
    "cta": "See student pricing",
    "eyebrow": "New for students",
    "layoutRecipe": "photo-hero-type",
    "heroStrategy": "ideogram_generate",
    "heroImagePrompt": "luminous violet and teal light ribbons flowing across deep navy space",
    "ideogramLayers": "background-only",
    "logoTreatment": "wordmark-white",
    "emphasis": "celebratory",
    "headlineScale": "lg",
    "headlineWeight": "extrabold",
    "ctaStyle": "pill",
    "rationale": "Sample brief for design-system review.",
}
VERCEL_BRIEF_BASE = {
    "headline": "Build minutes restored",
    "subhead": "Queued deployments have completed. No action is needed on your side.",
    "cta": "Read the update",
    "eyebrow": "Service update",
    "layoutRecipe": "gradient-brand",
    "heroStrategy": "gradient_from_palette",
    "logoTreatment": "wordmark-white",
    "emphasis": "calm",
    "headlineScale": "xl",
    "headlineWeight": "extrabold",
    "ctaStyle": "pill",
    "rationale": "Sample brief for design-system review.",
}


# --- Minimal PNG writer + procedural stand-in backgrounds -------------------------------------


def write_png(path: str, width: int, height: int, rows: list[bytes]) -> None:
    raw = b"".join(b"\x00" + row for row in rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(png)


def _rgb(hex6: str) -> tuple[float, float, float]:
    hex6 = hex6.lstrip("#")
    return tuple(int(hex6[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _lerp3(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def _smooth(e0: float, e1: float, x: float) -> float:
    t = max(0.0, min(1.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


def render_field(
    width: int,
    height: int,
    pixel: Callable[[float, float], tuple[float, float, float]],
) -> list[bytes]:
    rows = []
    for y in range(height):
        v = y / (height - 1)
        row = bytearray(width * 3)
        for x in range(width):
            r, g, b = pixel(x / (width - 1), v)
            i = x * 3
            row[i] = max(0, min(255, int(r * 255)))
            row[i + 1] = max(0, min(255, int(g * 255)))
            row[i + 2] = max(0, min(255, int(b * 255)))
        rows.append(bytes(row))
    return rows


def standin_navy_ribbons(u: float, v: float) -> tuple[float, float, float]:
    """Stripe-like: luminous ribbons on the right, calm navy negative space on the left."""
    base = _lerp3(_rgb("#0a2540"), _rgb("#14114a"), u * 0.7 + v * 0.3)
    mask = _smooth(0.32, 0.72, u)
    r, g, b = base
    for color, y0, amp, freq, phase, width in (
        (_rgb("#635bff"), 0.55, 0.22, 5.0, 0.0, 0.07),
        (_rgb("#00d4b2"), 0.42, 0.18, 4.2, 1.7, 0.04),
        (_rgb("#a960ee"), 0.68, 0.16, 6.1, 3.1, 0.05),
        (_rgb("#ffc000"), 0.30, 0.10, 3.4, 4.4, 0.02),
    ):
        center = y0 + amp * math.sin(freq * u + phase) * (0.4 + u)
        d = (v - center) / width
        glow = math.exp(-d * d) * mask
        r += color[0] * glow * 0.9
        g += color[1] * glow * 0.9
        b += color[2] * glow * 0.9
    return (r, g, b)


def standin_warm_silk(u: float, v: float) -> tuple[float, float, float]:
    """v25-like busy warm silk texture covering the whole frame (worst case for type)."""
    peach = _rgb("#f2b77e")
    pink = _rgb("#e8a0d8")
    lilac = _rgb("#b8a6f0")
    mauve = _rgb("#9b8bb4")
    t = u * 0.6 + (1 - v) * 0.4
    base = _lerp3(_lerp3(lilac, pink, _smooth(0.0, 0.5, t)), peach, _smooth(0.45, 1.0, t))
    base = _lerp3(base, mauve, _smooth(0.55, 1.0, v) * 0.55)
    streak = 0.025 * math.sin(220 * (u * 0.9 + v * 0.35) + 9 * math.sin(5 * v)) + 0.06 * math.sin(
        8 * (u * 0.8 + v * 0.5) + 2 * math.sin(3 * u)
    )
    sheen = 0.18 * math.exp(-(((v - 0.25 - 0.35 * u) / 0.06) ** 2))
    return tuple(c + streak + sheen for c in base)  # type: ignore[return-value]


def standin_mono_mesh(u: float, v: float) -> tuple[float, float, float]:
    """Vercel-like: black field, perspective grid and a white glow on the right."""
    g = 0.02 + 0.06 * (1 - v)
    glow = 0.55 * math.exp(-(((u - 0.8) / 0.22) ** 2 + ((v - 0.35) / 0.35) ** 2))
    depth = max(0.05, v)
    gx = abs(math.sin(math.pi * ((u - 0.75) / depth) * 6))
    gy = abs(math.sin(math.pi * (1 / depth) * 1.6))
    line = (0.12 if gx < 0.06 or gy < 0.05 else 0.0) * _smooth(0.35, 0.8, v)
    c = g + glow + line
    return (c, c, c * 1.02)


STANDINS: dict[str, Callable[[float, float], tuple[float, float, float]]] = {
    "navy-ribbons": standin_navy_ribbons,
    "warm-silk": standin_warm_silk,
    "mono-mesh": standin_mono_mesh,
}


def ensure_standin(root: str, name: str) -> str:
    rel = f"generated/assets/standin-{name}.png"
    abs_path = os.path.join(root, rel)
    if not os.path.isfile(abs_path):
        write_png(abs_path, W, H, render_field(W, H, STANDINS[name]))
    return rel


# --- Sample cases -------------------------------------------------------------------------------


def _load(name: str) -> dict[str, Any]:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


def sample_cases() -> list[dict[str, Any]]:
    stripe_kit = _load("kit-stripe.json")
    vercel_kit = _load("kit-vercel.json")
    stripe_profile = _load("brand-profile-stripe.json")
    return [
        {
            "name": "stripe",
            "kit": stripe_kit,
            "session": STRIPE_SESSION,
            "brief": {**STRIPE_BRIEF_BASE, "layoutTemplate": "full-bleed-scrim"},
            "background": "warm-silk",
            "brandProfile": None,
            "before": True,
        },
        {
            "name": "stripe-split",
            "kit": stripe_kit,
            "session": STRIPE_SESSION,
            "brief": {**STRIPE_BRIEF_BASE, "layoutTemplate": "split-text-left"},
            "background": "navy-ribbons",
            "brandProfile": stripe_profile,
            "before": True,
        },
        {
            "name": "vercel",
            "kit": vercel_kit,
            "session": VERCEL_SESSION,
            "brief": {**VERCEL_BRIEF_BASE, "layoutTemplate": "centered-statement"},
            "background": None,
            "brandProfile": None,
            "before": True,
        },
        {
            "name": "vercel-panel",
            "kit": vercel_kit,
            "session": VERCEL_SESSION,
            "brief": {
                **VERCEL_BRIEF_BASE,
                "layoutTemplate": "text-panel",
                "layoutRecipe": "photo-hero-type",
                "heroStrategy": "ideogram_generate",
                "heroImagePrompt": "dark perspective grid with a soft white glow",
                "ideogramLayers": "background-only",
                "headlineScale": "lg",
            },
            "background": "mono-mesh",
            "brandProfile": None,
            "before": False,
        },
    ]


# --- Rendering ----------------------------------------------------------------------------------


def _supported_kwargs(fn: Callable[..., Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    params = inspect.signature(fn).parameters
    return {k: v for k, v in kwargs.items() if k in params}


def _write_logo_assets(root: str, kit: dict[str, Any], compiler: Any, *, light: bool) -> dict[str, str]:
    svg = str(kit.get("logoSvg") or "").strip()
    if not svg.startswith("<svg"):
        return {}
    assets = os.path.join(root, "generated", "assets")
    os.makedirs(assets, exist_ok=True)
    if hasattr(compiler, "logo_svg_variants"):
        payloads = compiler.logo_svg_variants(svg)
    else:
        payloads = {
            "original": compiler.recolor_logo_svg_for_light_hero(svg) if light else svg
        }
    out: dict[str, str] = {}
    for name, markup in payloads.items():
        rel = f"generated/assets/sample-logo-{kit.get('siteName', 'brand').lower()}-{name}.svg"
        with open(os.path.join(root, rel), "w", encoding="utf-8") as handle:
            handle.write(markup)
        out[name] = rel
    return out


def _ideogram_background(root: str, case: dict[str, Any]) -> str | None:
    from ideogram_client import brand_terms_from_kit, generate_layer_image, ideogram_api_key
    from poster_design import brand_roles

    if not ideogram_api_key():
        return None
    roles = brand_roles(case["kit"], case["brandProfile"])
    rel, _bytes, _meta = generate_layer_image(
        case["brief"]["heroImagePrompt"],
        "background",
        "1200x627",
        assets_dir=os.path.join(root, "generated", "assets"),
        template=case["brief"]["layoutTemplate"],
        palette=[c for c in (roles.dark, roles.brand, roles.accent, roles.light) if c],
        brand_terms=brand_terms_from_kit(case["kit"]),
        brand_profile=case["brandProfile"],
    )
    return rel


def render_case(
    root: str,
    case: dict[str, Any],
    *,
    cli: str,
    out_dir: str,
    label: str,
    use_ideogram: bool,
) -> dict[str, Any]:
    import font_fetcher
    import photocraft_cli
    import poster_compiler as compiler
    from image_probe import raster_dimensions, svg_dimensions_from_text

    kit = dict(case["kit"])
    brief = dict(case["brief"])
    hero_rel = None
    hero_source = None
    if case["background"]:
        if use_ideogram:
            hero_rel = _ideogram_background(root, case)
            hero_source = "ideogram-4" if hero_rel else None
        if not hero_rel:
            hero_rel = ensure_standin(root, case["background"])
            hero_source = f"standin-{case['background']}"
    logos = _write_logo_assets(root, kit, compiler, light=bool(hero_rel))
    logo_dims = svg_dimensions_from_text(str(kit.get("logoSvg") or ""))
    hero_dims = raster_dimensions(os.path.join(root, hero_rel)) if hero_rel else None

    def _offline(_url: str) -> bytes:
        raise OSError("offline sample render")

    kwargs: dict[str, Any] = {
        "logo_relative_path": logos.get("original"),
        "logo_variants": logos or None,
        "logo_width": logo_dims[0] if logo_dims else None,
        "logo_height": logo_dims[1] if logo_dims else None,
        "hero_relative_path": hero_rel,
        "hero_width": hero_dims[0] if hero_dims else None,
        "hero_height": hero_dims[1] if hero_dims else None,
        "fonts_resolved": font_fetcher.resolve_poster_fonts(kit, root, fetcher=_offline),
        "assets_dir": os.path.join(root, "generated", "assets"),
        "brand_profile": case["brandProfile"],
    }
    if hero_rel and hasattr(compiler, "normalize_logo_fill"):
        from image_luma import load_rgb_grid

        kwargs["hero_grid"] = load_rgb_grid(os.path.join(root, hero_rel))
    if hasattr(compiler, "normalize_logo_fill"):
        kwargs["logo_fill"] = compiler.normalize_logo_fill(None, kit)
    batch = compiler.compile_poster_batch(
        kit,
        case["session"],
        creative_brief=brief,
        **_supported_kwargs(compiler.compile_poster_batch, kwargs),
    )
    out_rel = f"generated/samples/{label}-{case['name']}.pcraft"
    batch["output"]["relativePath"] = out_rel
    result = photocraft_cli.run_poster_batch(root, batch, cli_path=cli)
    if not result.get("ok"):
        raise RuntimeError(f"{case['name']}: {result.get('error')} {result.get('serveReplies')}")
    png_rel = photocraft_cli_png(cli, root, out_rel)
    os.makedirs(out_dir, exist_ok=True)
    dest = os.path.join(out_dir, f"{label}-{case['name']}.png")
    shutil.copyfile(os.path.join(root, png_rel), dest)
    meta = batch.get("meta") or {}
    return {
        "case": case["name"],
        "png": dest,
        "pcraft": os.path.join(root, out_rel),
        "background": hero_source or "brand-gradient",
        "layoutTemplate": meta.get("layoutTemplate"),
        "designAudit": (meta.get("designAudit") or {}).get("score"),
        "failedChecks": (meta.get("designAudit") or {}).get("failed"),
        "contrast": meta.get("contrast"),
        "logoVariant": meta.get("logoVariant"),
    }


def photocraft_cli_png(cli: str, root: str, pcraft_rel: str) -> str:
    png_rel = pcraft_rel[: -len(".pcraft")] + ".png"
    proc = subprocess.run(
        [cli, "convert", os.path.join(root, pcraft_rel), os.path.join(root, png_rel)],
        capture_output=True,
        text=True,
        timeout=90,
        cwd=root,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"convert failed: {proc.stderr.strip()}")
    return png_rel


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--code-root", default=os.path.dirname(SCRIPT_DIR))
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--before", action="store_true", help="label output as before (v5)")
    parser.add_argument("--cli", default=None, help="photocraft-cli path")
    parser.add_argument("--ideogram", action="store_true", help="use Ideogram when key is set")
    parser.add_argument("--only", nargs="*", help="case names to render")
    args = parser.parse_args()

    root = os.path.abspath(args.code_root)
    sys.path.insert(0, os.path.join(root, "scripts"))
    import photocraft_cli

    cli = args.cli or photocraft_cli.find_cli(os.path.dirname(SCRIPT_DIR)) or photocraft_cli.ensure_cli(root)
    if not cli:
        sys.exit("photocraft-cli not available")
    label = "poster-v5-before" if args.before else "poster-v6"
    out_dir = args.out_dir or os.path.join(root, "generated", "samples")
    results = []
    for case in sample_cases():
        if args.only and case["name"] not in args.only:
            continue
        if args.before and not case["before"]:
            continue
        results.append(
            render_case(
                root, case, cli=cli, out_dir=out_dir, label=label, use_ideogram=args.ideogram
            )
        )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
