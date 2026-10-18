"""One cheap vision check of an Ideogram picture, then at most one regeneration.

The check scores the picture only (not the poster type). A failure adds the
critique to the prompt and calls Ideogram once more. The second image is not judged.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from creative_brief import (
    ANTHROPIC_API_BASE,
    OPENAI_API_BASE,
    OPENROUTER_API_BASE,
    _anthropic_request_headers,
    _truncate,
    api_key_for_provider,
    prepare_picture_brief,
    raster_scene_prompt,
    resolve_llm_model,
    resolve_llm_provider,
)
from ideogram_client import describe_ideogram_failure
from poster_design import template_needs_raster, template_skips_ideogram

# Small on purpose: the generated PNG plus at most two brand references.
JUDGE_MAX_EDGE = 768
JUDGE_MAX_REFERENCES = 2
JUDGE_MAX_TOKENS = 300

# ~2000 in (picture + two refs + the rubric) and ~200 out at Sonnet $3 / $15 per MTok.
TYPICAL_JUDGE_INPUT_TOKENS = 2000
TYPICAL_JUDGE_OUTPUT_TOKENS = 200

JUDGE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "passed": {"type": "boolean"},
        "reason": {"type": "string"},
        "critique": {"type": "string"},
    },
    "required": ["passed", "reason", "critique"],
}

_SYSTEM = (
    "You judge one generated illustration for a poster. Score only that picture. "
    "Ignore any type layout; the words are added later. "
    "You MUST call submit_picture_judge exactly once."
)

_RUBRIC = """Score image 1, the generated picture. Later images, if any, are the brand (a screenshot or the scraped logo) for comparison only.

Fail the picture when any of these are true:
- It contains letters, words, numbers, or a painted logo.
- It is a flat empty disc, a solid field, or a generic clip-art circle with no subject.
- It has no single focal subject, or the subject is lost in empty space.
- It has no depth and no scene (a flat shape on a flat ground).
- Its colours or imagery style do not match the brand references and palette.

Pass when the picture has one focal subject, some depth or a real scene, and the palette and imagery match the brand. Linearity rules that apply here: one focal point, layered depth, colour from the brand, subject not lost in empty space.

reason: one sentence. critique: if it failed, what was wrong and what to show instead; if it passed, an empty string.
"""


def picture_references(kit: dict[str, Any] | None, repo_root: str, *, logo_path: str | None = None) -> list[str]:
    """Up to two existing brand images: a site screenshot, then the scraped logo if it is a raster."""
    kit = kit or {}
    found: list[str] = []
    shots = kit.get("screenshotPaths") if isinstance(kit.get("screenshotPaths"), dict) else {}
    for key in ("desktopFold", "mobileFold", "desktopFull"):
        rel = str((shots or {}).get(key) or "")
        if not rel:
            continue
        path = rel if os.path.isabs(rel) else os.path.join(repo_root, rel.lstrip("/"))
        if os.path.isfile(path):
            found.append(path)
            break
    if logo_path and os.path.isfile(logo_path) and not logo_path.lower().endswith(".svg"):
        found.append(logo_path)
    return found[:JUDGE_MAX_REFERENCES]


def _load_image(path: str) -> tuple[str, str] | None:
    if not path or not os.path.isfile(path):
        return None
    try:
        from brand_profile import _load_image_for_vision

        loaded = _load_image_for_vision(path, max_edge=JUDGE_MAX_EDGE)
        if not loaded:
            return None
        data, media, _size = loaded
        return data, media
    except Exception:  # noqa: BLE001 — fall through to the raw bytes
        pass
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return None
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        media = "image/png"
    elif raw[:3] == b"\xff\xd8\xff":
        media = "image/jpeg"
    else:
        return None
    import base64

    return base64.b64encode(raw).decode("ascii"), media


def _user_text(palette: list[str] | None, imagery_note: str) -> str:
    colours = ", ".join(str(c) for c in (palette or []) if c) or "not listed"
    note = (imagery_note or "").strip() or "not described"
    return f"{_RUBRIC}\nBrand palette: {colours}.\nImagery style: {_truncate(note, 240)}"


def _imagery_note(brand_profile: dict[str, Any] | None) -> str:
    style = (brand_profile or {}).get("imageryStyle") if isinstance(brand_profile, dict) else None
    if isinstance(style, dict):
        return str(style.get("ideogramPrompt") or style.get("colorTreatment") or "")
    if isinstance(style, str):
        return style
    return ""


def _parse_verdict(raw: dict[str, Any]) -> dict[str, Any]:
    reason = " ".join(str(raw.get("reason") or "").split())[:180] or "No reason given."
    critique = " ".join(str(raw.get("critique") or "").split())[:400]
    return {"passed": bool(raw.get("passed")), "reason": reason, "critique": critique}


def _call_anthropic(content: list[dict[str, Any]], *, api_key: str, model: str) -> dict[str, Any]:
    body = {
        "model": model,
        "max_tokens": JUDGE_MAX_TOKENS,
        "system": _SYSTEM,
        "messages": [{"role": "user", "content": content}],
        "tools": [
            {
                "name": "submit_picture_judge",
                "description": "Score the generated picture only.",
                "input_schema": JUDGE_JSON_SCHEMA,
                "strict": True,
            }
        ],
        "tool_choice": {"type": "auto"},
    }
    req = urllib.request.Request(
        f"{ANTHROPIC_API_BASE}/messages",
        data=json.dumps(body).encode("utf-8"),
        headers=_anthropic_request_headers(api_key),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    for block in payload.get("content") or []:
        if block.get("type") == "tool_use" and block.get("name") == "submit_picture_judge":
            if isinstance(block.get("input"), dict):
                return _parse_verdict(block["input"])
    raise ValueError("Picture judge returned no score")


def _call_openai(content: list[dict[str, Any]], *, api_key: str, model: str, base_url: str) -> dict[str, Any]:
    body = {
        "model": model,
        "temperature": 0,
        "max_tokens": JUDGE_MAX_TOKENS,
        "messages": [
            {"role": "system", "content": _SYSTEM.replace("call submit_picture_judge exactly once", "return JSON")},
            {"role": "user", "content": content},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "picture_judge", "strict": True, "schema": JUDGE_JSON_SCHEMA},
        },
    }
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    text = str(((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    return _parse_verdict(json.loads(text))


def _default_llm(image_path: str, reference_paths: list[str], palette: list[str], imagery_note: str) -> dict[str, Any]:
    provider = resolve_llm_provider()
    if not provider:
        raise LookupError("no_provider")
    api_key = api_key_for_provider(provider)
    if not api_key:
        raise LookupError("no_api_key")
    model = resolve_llm_model(provider)
    content: list[dict[str, Any]] = [{"type": "text", "text": "Image 1: generated picture to score."}]
    picture = _load_image(image_path)
    if not picture:
        raise ValueError("generated picture could not be read")
    data, media = picture
    if provider == "anthropic":
        content.append({"type": "image", "source": {"type": "base64", "media_type": media, "data": data}})
    else:
        content.append({"type": "image_url", "image_url": {"url": f"data:{media};base64,{data}"}})
    for index, path in enumerate(reference_paths[:JUDGE_MAX_REFERENCES], start=2):
        loaded = _load_image(path)
        if not loaded:
            continue
        ref_data, ref_media = loaded
        content.append({"type": "text", "text": f"Image {index}: brand reference, not the picture to score."})
        if provider == "anthropic":
            content.append({"type": "image", "source": {"type": "base64", "media_type": ref_media, "data": ref_data}})
        else:
            content.append({"type": "image_url", "image_url": {"url": f"data:{ref_media};base64,{ref_data}"}})
    content.append({"type": "text", "text": _user_text(palette, imagery_note)})
    if provider == "anthropic":
        return _call_anthropic(content, api_key=api_key, model=model)
    base = OPENROUTER_API_BASE if provider == "openrouter" else OPENAI_API_BASE
    return _call_openai(content, api_key=api_key, model=model, base_url=base)


PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def is_png(data: bytes | bytearray | None) -> bool:
    """A real Ideogram file, not an empty body or the compiler's vector stand-in."""
    raw = bytes(data or b"")
    return raw.startswith(PNG_MAGIC) and len(raw) > len(PNG_MAGIC)


def poster_status_line(
    *,
    template: str | None,
    ideogram_used: bool,
    error: str | None,
    score: int | None = None,
    ideogram_ms: int | None = None,
) -> str:
    """Crisis status. A skip names the reason and shows 0 ms, so it cannot look like a hit."""
    parts: list[str] = []
    if template:
        parts.append(template)
    if error:
        parts.append(error)
    elif ideogram_used:
        parts.append("Ideogram")
    else:
        parts.append("no Ideogram")
    if ideogram_ms is not None:
        parts.append(f"{int(ideogram_ms)} ms")
    if score is not None:
        parts.append(f"design score {score}/100")
    return " · ".join(parts)


def _picture_prompt(
    brief: dict[str, Any],
    kit: dict[str, Any] | None,
    brand_profile: dict[str, Any] | None,
    template: str,
) -> str:
    prompt = str(brief.get("heroImagePrompt") or "").strip()
    if not prompt:
        prompt = raster_scene_prompt(template, kit, brand_profile, "")
    try:
        from brand_profile import augment_ideogram_prompt

        prompt = augment_ideogram_prompt(prompt, kit, role="background") or prompt
    except Exception:  # noqa: BLE001 — the scene prompt is enough to POST
        pass
    direction = ""
    comm = (kit or {}).get("communicationKit") if isinstance(kit, dict) else None
    if isinstance(comm, dict):
        imagery = comm.get("imagery") if isinstance(comm.get("imagery"), dict) else {}
        direction = str(imagery.get("direction") or "")
    if direction and not any(word in direction.casefold() for word in ("circle", "circular", "disc", "disk")):
        prompt = f"{prompt}. {direction}"
    return " ".join(prompt.split())


def acquire_poster_picture(
    brief: dict[str, Any] | None,
    kit: dict[str, Any] | None,
    brand_profile: dict[str, Any] | None,
    *,
    template: str,
    key_set: bool,
    generate: Callable[[str], tuple],
) -> dict[str, Any]:
    """POST a picture frame to Ideogram before the poster is compiled.

    The HTTP call is not gated on ``heroStrategy == ideogram_generate`` or on a
    pre-filled ``heroImagePrompt``. Those two checks returned the stand-in
    ellipse with ``ideogramMs`` 0 and no request.
    """
    prepared = dict(brief or {})
    prepared["layoutTemplate"] = template
    result: dict[str, Any] = {
        "brief": prepared,
        "path": None,
        "image": None,
        "meta": {},
        "prompt": "",
        "ideogramUsed": False,
        "ideogramMs": 0,
        "ideogramError": None,
        "called": False,
    }
    if template_skips_ideogram(template) or not template_needs_raster(template):
        prepared["heroStrategy"] = "solid"
        result["brief"] = prepared
        result["ideogramError"] = f"{template or 'unknown'} is not a picture frame — Ideogram skipped."
        return result
    if not key_set:
        result["ideogramError"] = "IDEOGRAM_API_KEY not set — picture stand-in only."
        return result

    prepared = prepare_picture_brief(prepared, kit, brand_profile, key_set=True)
    prompt = _picture_prompt(prepared, kit, brand_profile, template)
    prepared["heroStrategy"] = "ideogram_generate"
    prepared["heroImagePrompt"] = prompt
    prepared["layoutTemplate"] = template
    prepared["ideogramLayers"] = "background-only"
    t0 = time.perf_counter()
    try:
        rel, data, meta = generate(prompt)
    except Exception as exc:  # noqa: BLE001 — report the failure; do not hide it as a stand-in
        result.update(
            {
                "brief": prepared,
                "prompt": prompt,
                "ideogramMs": int((time.perf_counter() - t0) * 1000),
                "ideogramError": describe_ideogram_failure(exc),
                "called": True,
            }
        )
        return result
    raw = bytes(data or b"")
    result.update(
        {
            "brief": prepared,
            "path": rel,
            "image": raw or None,
            "meta": meta or {},
            "prompt": prompt,
            "ideogramMs": int((time.perf_counter() - t0) * 1000),
            "called": True,
        }
    )
    if not is_png(raw):
        result["ideogramError"] = "Ideogram did not return a PNG."
        result["ideogramUsed"] = False
        return result
    result["ideogramUsed"] = True
    result["ideogramError"] = None
    return result


def judge_real_png(
    image: bytes | bytearray | None,
    image_path: str,
    prompt: str,
    **kwargs: Any,
) -> dict[str, Any] | None:
    """One vision check, and only after Ideogram returned a PNG. No PNG is not a pass."""
    if not is_png(image) or not image_path or not os.path.isfile(image_path):
        return None
    return review_generated_picture(image_path, prompt, **kwargs)


def fetch_picture_layer(prompt: str, *, key_set: bool, generate: Callable[..., tuple]) -> dict[str, Any]:
    """Call Ideogram once. A missing key is not an error; a failed call returns the error text."""
    if not key_set:
        return {"path": None, "error": None, "keyMissing": True}
    if not str(prompt or "").strip():
        return {"path": None, "error": "Ideogram prompt was empty.", "keyMissing": False}
    try:
        rel, data, meta = generate(prompt)
    except Exception as exc:  # noqa: BLE001 — the poster must report the failure, not hide it
        return {
            "path": None,
            "error": describe_ideogram_failure(exc),
            "keyMissing": False,
        }
    if not data:
        return {"path": None, "error": "Ideogram returned an empty image.", "keyMissing": False}
    return {"path": rel, "error": None, "keyMissing": False, "meta": meta or {}}


def retry_prompt(prompt: str, reason: str, critique: str) -> str:
    """One extra instruction. Still forbids letters and a frame."""
    note = " ".join(f"{reason} {critique}".split())
    return (
        f"{prompt.strip()}\n\n"
        f"The previous image failed a picture check: {note} "
        "Show that instead. No letters, no words, no logo, no frame, no border."
    )


def review_generated_picture(
    image_path: str,
    prompt: str,
    *,
    reference_paths: list[str] | None = None,
    palette: list[str] | None = None,
    brand_profile: dict[str, Any] | None = None,
    llm_fn: Callable[..., dict[str, Any]] | None = None,
    regenerate: Callable[[str], tuple[str, bytes, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Judge once. On failure, regenerate once and place that image. Never judges the retry.

    ``image_path`` is the file on disk. The returned ``imagePath`` is whatever
    ``regenerate`` returns as its first item (the project-relative path).
    """
    refs = [p for p in (reference_paths or []) if p][:JUDGE_MAX_REFERENCES]
    try:
        if llm_fn is not None:
            verdict = llm_fn(image_path, refs, list(palette or []), _imagery_note(brand_profile))
        else:
            verdict = _default_llm(image_path, refs, list(palette or []), _imagery_note(brand_profile))
        verdict = _parse_verdict(verdict)
    except LookupError:
        return {
            "passed": None,
            "reason": "Vision check skipped (no model key).",
            "retried": False,
            "skipped": True,
            "imagePath": None,
        }
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        json.JSONDecodeError,
        ValueError,
        TimeoutError,
        OSError,
    ) as exc:
        return {
            "passed": None,
            "reason": _truncate(f"Vision check failed ({exc})", 160),
            "retried": False,
            "skipped": True,
            "imagePath": None,
        }

    result: dict[str, Any] = {
        "passed": verdict["passed"],
        "reason": verdict["reason"],
        "retried": False,
        "skipped": False,
        "imagePath": None,
    }
    if verdict["passed"] or regenerate is None:
        return result
    try:
        rel, _data, _meta = regenerate(retry_prompt(prompt, verdict["reason"], verdict["critique"]))
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        json.JSONDecodeError,
        ValueError,
        TimeoutError,
        OSError,
    ) as exc:
        result["reason"] = _truncate(f"{verdict['reason']} Retry failed ({exc}); kept the first image.", 180)
        return result
    result["retried"] = True
    result["imagePath"] = rel
    return result
