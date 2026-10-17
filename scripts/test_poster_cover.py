#!/usr/bin/env python3
"""Assert hero cover placement and run optional live API smoke test."""

from __future__ import annotations

import json
import os
import sys
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from image_probe import raster_dimensions  # noqa: E402
from poster_compiler import (  # noqa: E402
    LINKEDIN_HEIGHT,
    LINKEDIN_WIDTH,
    compile_poster_batch,
    cover_scale_percent,
)
from photocraft_cli import _finalize_doc_place_params, run_poster_batch  # noqa: E402

STRIPE_OG = (
    "https://images.stripeassets.com/fb4cbc/fbe7faf8-79ab-46ec-9e44-7f8925b4e1b7/width=1200"
)


def _stripe_fixture() -> tuple[dict, dict]:
    kit = {
        "siteName": "Stripe",
        "sourceUrl": "https://stripe.com/",
        "heroImageUrl": STRIPE_OG,
        "heroWidth": 1200,
        "heroHeight": 630,
        "colors": ["#635bff", "#0a2540"],
        "fonts": ["Inter"],
        "tagline": "Financial infrastructure for the internet",
        "logoUrl": None,
    }
    session = {
        "suggestedHeadline": "Service update for customers",
        "brief": {
            "headline": "Service update for customers",
            "facts": "We are investigating elevated API errors.\nNo card data was exposed.",
        },
    }
    return kit, session


def test_batch_cover_scale() -> None:
    kit, session = _stripe_fixture()
    hero_path = "generated/assets/test-hero.jpg"
    batch = compile_poster_batch(
        kit,
        session,
        hero_relative_path=hero_path,
        hero_width=kit["heroWidth"],
        hero_height=kit["heroHeight"],
    )
    hero = (batch.get("backgroundPlacements") or [None])[0]
    assert hero, "expected hero background placement"
    assert hero.get("cover") is True
    assert hero.get("fit") is False
    expected = round(cover_scale_percent(1200, 630), 2)
    assert hero.get("scale") == expected
    assert hero["center"] == [LINKEDIN_WIDTH / 2, LINKEDIN_HEIGHT / 2]

    resolved = _finalize_doc_place_params(hero, ROOT)
    assert "cover" not in resolved
    assert resolved.get("fit") is False
    assert resolved.get("scale") == expected


def test_live_place_bounds() -> None:
    hero_path = os.path.join(ROOT, "generated/assets/test-hero.jpg")
    if not os.path.isfile(hero_path):
        return
    dims = raster_dimensions(hero_path)
    if not dims:
        return
    kit, session = _stripe_fixture()
    batch = compile_poster_batch(
        kit,
        session,
        hero_relative_path="generated/assets/test-hero.jpg",
        hero_width=dims[0],
        hero_height=dims[1],
    )
    result = run_poster_batch(ROOT, batch)
    if not result.get("ok"):
        print("skip live place:", result.get("cliError"), file=sys.stderr)
        return
    cli = result.get("cliPath")
    if not cli:
        return
    out = batch["output"]["relativePath"]
    import subprocess

    proc = subprocess.run(
        [cli, "info", os.path.join(ROOT, out), "--compact"],
        capture_output=True,
        text=True,
        check=False,
    )
    doc = json.loads(proc.stdout)
    for layer in doc.get("layers") or []:
        if layer.get("name") in ("Hero image", "test-hero", "tiny"):
            bounds = layer.get("bounds")
            assert bounds, layer
            left, top, right, bottom = bounds
            assert left <= 0 or right >= LINKEDIN_WIDTH
            assert top <= 0 or bottom >= LINKEDIN_HEIGHT
            assert (right - left) >= LINKEDIN_WIDTH * 0.99
            assert (bottom - top) >= LINKEDIN_HEIGHT * 0.99


def test_api_smoke(port: int = 8000) -> None:
    payload = {
        "kit": _stripe_fixture()[0],
        "session": _stripe_fixture()[1],
    }
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/generate-poster",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except OSError:
        print("skip API smoke (server not running)", file=sys.stderr)
        return
    batch = body.get("commandBatch") or {}
    hero = (batch.get("backgroundPlacements") or [None])[0] or {}
    assert hero.get("cover") is True
    assert hero.get("scale"), hero
    assert "placementErrors" in body


def main() -> int:
    test_batch_cover_scale()
    test_live_place_bounds()
    port = int(os.environ.get("COMMMAKER_PORT", "8000"))
    test_api_smoke(port)
    print("poster cover tests OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
