"""One cheap vision check of an Ideogram picture, then at most one regeneration.

The check scores the picture only (not the poster type). A failure adds the
critique to the prompt and calls Ideogram once more. The second image is not judged.
"""

from __future__ import annotations

import json
import os
import struct
import time
import urllib.error
import urllib.request
import zlib
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

# The generated PNG plus every example crop Ideogram was shown (at most five).
JUDGE_MAX_EDGE = 768
JUDGE_MAX_REFERENCES = 5
JUDGE_MAX_TOKENS = 300

# ~2000 in (picture + example crops + the rubric) and ~200 out at Opus $15 / $75 per MTok.
TYPICAL_JUDGE_INPUT_TOKENS = 2000
TYPICAL_JUDGE_OUTPUT_TOKENS = 200

JUDGE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "passed": {"type": "boolean"},
        "reason": {"type": "string"},
        "critique": {"type": "string"},
        "suggestedTreatment": {
            "type": "string",
            "enum": ["same", "full-sheet", "photo-band", "pattern-field", "illustration-cluster", "quiet-type"],
        },
    },
    "required": ["passed", "reason", "critique", "suggestedTreatment"],
}

# One generate plus two retries. The first tiny image is not returned as a pass.
MAX_IDEOGRAM_ATTEMPTS = 3
_FILL_SPAN = 0.72

_SYSTEM = (
    "You judge one full-bleed poster image. Image 1 is the whole 1200×627 sheet. "
    "Later images are the brand, for comparison only. Type will be added later as editable text. "
    "You MUST call submit_picture_judge exactly once."
)

_RUBRIC = """Score image 1, the full poster canvas. Later images, if any, are the brand (a screenshot or the scraped logo).

The poster used the treatment named in the request. You may reject that treatment, not only the pixels. "full-bleed was wrong for this brand" is a valid fail. If another treatment would fit the brand better, set suggestedTreatment to one of full-sheet, photo-band, pattern-field, illustration-cluster, or quiet-type. Otherwise set suggestedTreatment to same.

Fail when any of these are true:
- The treatment does not fit the brand (for example a full-bleed sheet on a stark type-led brand).
- It is a split layout: words or empty space on one side and a picture box or sticker on the other.
- The subject is cramped into a corner.
- It is a huge empty field with a tiny subject.
- It contains letters, words, numbers, or a painted logo or wordmark. The scraped logo is placed later; do not draw one.
- The logo layer is not the scraped logo file.
- A display font was captured and the headline is not that family.
- The colours are not the brand palette.
- The type is weak: a system font, a headline under 54px, a subline too close to the headline size, or a headline of more than 8 words.
- The logo or the headline contrast against the pixels behind it is under 4.5:1.
- The colours or the imagery do not match the brand palette and the example images.
- It is a generic black triangle or simple mark with no relation to the example images.
- It is a jungle: every example pasted into one frame instead of one coherent poster.

Quality bar: Linearity business posters (https://www.linearity.io/templates/business-templates/posters/): one composition across the whole sheet, in the brand's own colours and imagery. A full-bleed photograph with room for type, a pattern that fills the sheet, a graphic field with a type band, or an illustration with room for type in the middle. Not a text column beside a picture box.

reason: one sentence. critique: if it failed, what was wrong and what to show instead; if it passed, an empty string.
"""


def picture_references(
    kit: dict[str, Any] | None,
    repo_root: str,
    *,
    logo_path: str | None = None,
    packet: dict[str, Any] | None = None,
) -> list[str]:
    """Up to two clean reference files from the brand packet. Page screenshots are not passed."""
    del logo_path
    packet = packet or ((kit or {}).get("ideogramPacket") if isinstance(kit, dict) else None) or {}
    found: list[str] = []
    for rel in packet.get("references") or []:
        text = str(rel or "")
        if not text:
            continue
        path = text if os.path.isabs(text) else os.path.join(repo_root, text.lstrip("/"))
        if os.path.isfile(path):
            found.append(path)
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
    return (
        f"{_RUBRIC}\n"
        "The later images are examples of how the brand's components are built. "
        "Use them to judge the language, not as pieces that must all appear. "
        "Fail a generic black triangle with no relation to them, and fail a jungle that pastes every example into one frame. "
        "The poster must be one coherent composition.\n"
        f"Brand palette: {colours}.\nImagery: {_truncate(note, 240)}"
    )


def _imagery_note(brand_profile: dict[str, Any] | None) -> str:
    packet = (brand_profile or {}).get("ideogramPacket") if isinstance(brand_profile, dict) else None
    if isinstance(packet, dict) and str(packet.get("imagery") or "").strip():
        return str(packet.get("imagery") or "")
    style = (brand_profile or {}).get("imageryStyle") if isinstance(brand_profile, dict) else None
    if isinstance(style, dict):
        return str(style.get("ideogramPrompt") or style.get("colorTreatment") or "")
    if isinstance(style, str):
        return style
    return ""


def _parse_verdict(raw: dict[str, Any]) -> dict[str, Any]:
    reason = " ".join(str(raw.get("reason") or "").split())[:180] or "No reason given."
    critique = " ".join(str(raw.get("critique") or "").split())[:400]
    suggested = str(raw.get("suggestedTreatment") or "same")
    allowed = {"same", "full-sheet", "photo-band", "pattern-field", "illustration-cluster", "quiet-type"}
    if suggested not in allowed:
        suggested = "same"
    return {"passed": bool(raw.get("passed")), "reason": reason, "critique": critique, "suggestedTreatment": suggested}


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
    judge: dict[str, Any] | None = None,
    treatment: str | None = None,
    screenshots_skipped: bool = False,
    brand_font_failed: bool = False,
) -> str:
    """Crisis status. A skip names the reason and shows 0 ms, so it cannot look like a hit."""
    parts: list[str] = []
    if treatment:
        parts.append(treatment)
    if template:
        parts.append(template)
    if screenshots_skipped:
        from ideogram_packet import SCREENSHOTS_SKIPPED_STATUS

        parts.append(SCREENSHOTS_SKIPPED_STATUS)
    if brand_font_failed:
        parts.append("the brand font failed to load")
    if error:
        parts.append(error)
    elif ideogram_used:
        parts.append("Ideogram")
    else:
        parts.append("no Ideogram")
    if judge:
        passed = judge.get("passed")
        if passed is True:
            parts.append("judge pass")
        elif passed is False:
            parts.append("judge fail")
        else:
            parts.append("judge skipped")
        reason = " ".join(str(judge.get("reason") or "").split())
        if reason:
            parts.append(reason)
        attempts = judge.get("attempts")
        if attempts:
            count = int(attempts)
            parts.append(f"{count} attempt" if count == 1 else f"{count} attempts")
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
    try:
        from ideogram_client import treatment_spec
        from poster_design import choose_treatment

        kind = choose_treatment(brief)
        spec = treatment_spec(kind)
        if spec.get("fill"):
            prompt = (
                f"{prompt}. Treatment {kind}. {spec['fill']} {spec.get('quiet') or ''} "
                "The example images show how this brand's components are built. "
                "Study them for materials, shapes, and palette. "
                f"Make one coherent text-free asset for the {kind} poster in that language. "
                "Do not paste the examples together. Do not copy the words in the examples."
            )
    except Exception:  # noqa: BLE001 — the scene prompt still POSTs
        prompt = f"{prompt}. Match the brand's colours and imagery. No lettering."
    from ideogram_packet import packet_for_poster, prompt_with_packet

    packet = packet_for_poster(kit, brand_profile)
    if isinstance(kit, dict):
        kit["ideogramPacket"] = packet
    if isinstance(brand_profile, dict):
        brand_profile["ideogramPacket"] = packet
    prompt = prompt_with_packet(prompt, packet)
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
    from poster_design import choose_treatment

    try:
        from creative_brief import brand_layout_energy

        energy = brand_layout_energy(kit, brand_profile)
    except Exception:  # noqa: BLE001 — fall back to the template name
        energy = ""
    treatment = choose_treatment(prepared, energy)
    prepared["treatment"] = treatment
    result["brief"] = prepared
    result["treatment"] = treatment
    if not key_set:
        result["ideogramError"] = "IDEOGRAM_API_KEY not set — picture stand-in only."
        return result

    prepared = prepare_picture_brief(prepared, kit, brand_profile, key_set=True)
    try:
        prompt = _picture_prompt(prepared, kit, brand_profile, template)
    except ValueError as exc:
        result["brief"] = prepared
        result["ideogramError"] = str(exc)
        result["ideogramPacket"] = (kit or {}).get("ideogramPacket") if isinstance(kit, dict) else None
        return result
    result["ideogramPacket"] = (kit or {}).get("ideogramPacket") if isinstance(kit, dict) else None
    prepared["layoutRecipe"] = "photo-hero-type"
    prepared["heroStrategy"] = "ideogram_generate"
    prepared["heroImagePrompt"] = prompt
    prepared["layoutTemplate"] = template
    prepared["ideogramLayers"] = "background-only"
    t0 = time.perf_counter()
    try:
        rel, data, meta = generate(prompt)
    except urllib.error.HTTPError as exc:
        from ideogram_client import ideogram_http_error_message

        result.update(
            {
                "brief": prepared,
                "prompt": prompt,
                "ideogramMs": int((time.perf_counter() - t0) * 1000),
                "ideogramError": f"Ideogram failed: {ideogram_http_error_message(exc)}",
                "called": True,
            }
        )
        return result
    except Exception as exc:  # noqa: BLE001 — report the failure; do not hide it as a stand-in
        result.update(
            {
                "brief": prepared,
                "prompt": prompt,
                "ideogramMs": int((time.perf_counter() - t0) * 1000),
                "ideogramError": f"Ideogram failed: {exc}",
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
            "error": f"Ideogram failed: {type(exc).__name__}: {exc}",
            "keyMissing": False,
        }
    if not data:
        return {"path": None, "error": "Ideogram returned an empty image.", "keyMissing": False}
    return {"path": rel, "error": None, "keyMissing": False, "meta": meta or {}}


def retry_prompt(prompt: str, reason: str, critique: str, layout: str = "") -> str:
    """One extra instruction. Still forbids letters and a frame, and repeats the well."""
    note = " ".join(f"{reason} {critique} {layout}".split())
    return (
        f"{prompt.strip()}\n\n"
        f"The previous image failed a picture check: {note} "
        "Study the examples for materials, shapes, and palette. "
        "Make one coherent text-free asset in that language. "
        "Do not paste the examples together. Do not copy the words in the examples. "
        "Show that instead. Fill the frame, subject large, no empty margin inside the image. "
        "No letters, no words, no logo, no frame, no border."
    )


def _resolve_image(path: str, repo_root: str | None) -> str:
    if path and os.path.isfile(path):
        return path
    if path and repo_root:
        joined = os.path.join(repo_root, path.lstrip("/"))
        if os.path.isfile(joined):
            return joined
    return path


def _paeth(left: int, up: int, up_left: int) -> int:
    estimate = left + up - up_left
    if abs(estimate - left) <= abs(estimate - up) and abs(estimate - left) <= abs(estimate - up_left):
        return left
    if abs(estimate - up) <= abs(estimate - up_left):
        return up
    return up_left


def read_rgb_png(path: str) -> tuple[int, int, list[tuple[int, int, int]]] | None:
    """Decode an 8-bit RGB or RGBA PNG. Returns None for other files."""
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        return None
    if not data.startswith(PNG_MAGIC):
        return None
    pos = 8
    width = height = 0
    bit_depth = color_type = interlace = None
    idat: list[bytes] = []
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        tag = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            width, height, bit_depth, color_type, _comp, _filter, interlace = struct.unpack(">IIBBBBB", chunk)
        elif tag == b"IDAT":
            idat.append(chunk)
        elif tag == b"IEND":
            break
    if bit_depth != 8 or color_type not in (2, 6) or interlace or not idat or width < 1 or height < 1:
        return None
    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error:
        return None
    channels = 3 if color_type == 2 else 4
    stride = width * channels
    pixels: list[tuple[int, int, int]] = []
    cursor = 0
    previous = bytearray(stride)
    for _y in range(height):
        if cursor + 1 + stride > len(raw):
            return None
        filter_type = raw[cursor]
        cursor += 1
        row = bytearray(raw[cursor : cursor + stride])
        cursor += stride
        for index in range(stride):
            left = row[index - channels] if index >= channels else 0
            up = previous[index]
            up_left = previous[index - channels] if index >= channels else 0
            if filter_type == 1:
                row[index] = (row[index] + left) & 255
            elif filter_type == 2:
                row[index] = (row[index] + up) & 255
            elif filter_type == 3:
                row[index] = (row[index] + ((left + up) // 2)) & 255
            elif filter_type == 4:
                row[index] = (row[index] + _paeth(left, up, up_left)) & 255
            elif filter_type != 0:
                return None
        previous = row
        for x in range(width):
            offset = x * channels
            pixels.append((row[offset], row[offset + 1], row[offset + 2]))
    return width, height, pixels


def _write_rgb_png(path: str, width: int, height: int, rows: list[bytes]) -> None:
    from render_poster_samples import write_png

    write_png(path, width, height, rows)


def _pixel(pixels: list[tuple[int, int, int]], width: int, x: int, y: int) -> tuple[int, int, int]:
    return pixels[y * width + x]


def frame_fill_report(path: str) -> dict[str, Any] | None:
    """Whether the subject fills the bitmap. A small sticker on an empty field fails."""
    decoded = read_rgb_png(path)
    if not decoded:
        return None
    width, height, pixels = decoded
    if width < 2 or height < 2:
        return None

    def distance(left: tuple[int, int, int], right: tuple[int, int, int]) -> int:
        return abs(left[0] - right[0]) + abs(left[1] - right[1]) + abs(left[2] - right[2])

    corners = (
        _pixel(pixels, width, 0, 0),
        _pixel(pixels, width, width - 1, 0),
        _pixel(pixels, width, 0, height - 1),
        _pixel(pixels, width, width - 1, height - 1),
    )
    background = corners[0]
    if any(distance(corner, background) > 36 for corner in corners[1:]):
        return {"passed": True, "reason": "The picture fills its frame.", "critique": "", "span": (1.0, 1.0)}
    step = max(1, min(width, height) // 80)
    min_x, min_y, max_x, max_y = width, height, -1, -1
    varied = False
    for y in range(0, height, step):
        for x in range(0, width, step):
            pixel = _pixel(pixels, width, x, y)
            if distance(pixel, background) > 36:
                varied = True
                min_x = min(min_x, x)
                max_x = max(max_x, x)
                min_y = min(min_y, y)
                max_y = max(max_y, y)
    if not varied or max_x < 0:
        return {
            "passed": False,
            "reason": "The picture has no focal subject.",
            "critique": "Show one large subject that fills the frame, with no empty margin.",
            "span": (0.0, 0.0),
        }
    span_x = (max_x - min_x + step) / width
    span_y = (max_y - min_y + step) / height
    if min_x > width * 0.42 or max_x < width * 0.58:
        return {
            "passed": False,
            "reason": "The subject is cramped to one side of an empty field.",
            "critique": "Make one composition across the whole sheet, not a picture box on one side.",
            "span": (round(span_x, 3), round(span_y, 3)),
        }
    if span_x < _FILL_SPAN or span_y < _FILL_SPAN:
        return {
            "passed": False,
            "reason": "The picture is a small inset on an empty field.",
            "critique": "Fill the frame, subject large, no empty margin inside the image.",
            "span": (round(span_x, 3), round(span_y, 3)),
        }
    return {
        "passed": True,
        "reason": "The picture fills its frame.",
        "critique": "",
        "span": (round(span_x, 3), round(span_y, 3)),
    }


def compose_poster_preview(
    image_path: str,
    region: tuple[float, float, float, float],
    dest: str,
    *,
    field: str = "#f6f3ee",
) -> str | None:
    """Cover-fit the bitmap into the picture well on a 1200×627 poster."""
    decoded = read_rgb_png(image_path)
    if not decoded:
        return None
    src_w, src_h, pixels = decoded
    origin_x, origin_y, raw_w, raw_h = region
    well_w = max(1, int(round(raw_w)))
    well_h = max(1, int(round(raw_h)))
    left = int(round(origin_x))
    top = int(round(origin_y))
    scale = max(well_w / src_w, well_h / src_h)
    scaled_w = max(1, int(round(src_w * scale)))
    scaled_h = max(1, int(round(src_h * scale)))
    crop_x = max(0, (scaled_w - well_w) // 2)
    crop_y = max(0, (scaled_h - well_h) // 2)
    hex_field = field.lstrip("#")
    if len(hex_field) != 6:
        hex_field = "f6f3ee"
    paper = tuple(int(hex_field[i : i + 2], 16) for i in (0, 2, 4))
    rows: list[bytes] = []
    for y in range(627):
        row = bytearray()
        for x in range(1200):
            if left <= x < left + well_w and top <= y < top + well_h:
                sx = min(src_w - 1, int((x - left + crop_x) / scale))
                sy = min(src_h - 1, int((y - top + crop_y) / scale))
                pixel = _pixel(pixels, src_w, sx, sy)
            else:
                pixel = paper
            row.extend(pixel)
        rows.append(bytes(row))
    try:
        _write_rgb_png(dest, 1200, 627, rows)
    except OSError:
        return None
    return dest


def _judge_one(
    image_path: str,
    refs: list[str],
    palette: list[str] | None,
    brand_profile: dict[str, Any] | None,
    llm_fn: Callable[..., dict[str, Any]] | None,
    region: tuple[float, float, float, float] | None,
) -> dict[str, Any]:
    """Local fill check, then one vision check of the composed poster."""
    local = frame_fill_report(image_path) if region else None
    composed = image_path
    full_canvas = False
    if region:
        _x, _y, region_w, region_h = region
        full_canvas = _x <= 1 and _y <= 1 and region_w >= 1100 and region_h >= 600
    if region and not full_canvas:
        preview = compose_poster_preview(image_path, region, image_path + ".poster.png")
        if preview:
            composed = preview
    vision: dict[str, Any] | None = None
    skipped = False
    try:
        if llm_fn is not None:
            raw = llm_fn(composed, refs, list(palette or []), _imagery_note(brand_profile))
        else:
            raw = _default_llm(composed, refs, list(palette or []), _imagery_note(brand_profile))
        vision = _parse_verdict(raw)
    except LookupError:
        skipped = True
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        json.JSONDecodeError,
        ValueError,
        TimeoutError,
        OSError,
    ) as exc:
        vision = {
            "passed": None,
            "reason": _truncate(f"Vision check failed ({exc})", 160),
            "critique": "",
        }
    if local and local.get("passed") is False:
        return {
            "passed": False,
            "reason": local["reason"],
            "critique": local["critique"],
            "suggestedTreatment": (vision or {}).get("suggestedTreatment") or "same",
            "skipped": False,
        }
    if vision and vision.get("passed") is False:
        return {
            "passed": False,
            "reason": vision["reason"],
            "critique": vision.get("critique") or "",
            "suggestedTreatment": vision.get("suggestedTreatment") or "same",
            "skipped": False,
        }
    if vision and vision.get("passed") is True and not (local and local.get("passed") is False):
        return {"passed": True, "reason": vision["reason"], "critique": "", "skipped": False}
    if skipped or (vision and vision.get("passed") is None):
        reason = (vision or {}).get("reason") or "Vision check skipped (no model key)."
        return {"passed": None, "reason": reason, "critique": "", "skipped": True}
    if local and local.get("passed"):
        return {"passed": True, "reason": local["reason"], "critique": "", "skipped": False}
    return {"passed": None, "reason": "Vision check skipped (no model key).", "critique": "", "skipped": True}


def review_generated_picture(
    image_path: str,
    prompt: str,
    *,
    reference_paths: list[str] | None = None,
    palette: list[str] | None = None,
    brand_profile: dict[str, Any] | None = None,
    llm_fn: Callable[..., dict[str, Any]] | None = None,
    regenerate: Callable[[str], tuple[str, bytes, dict[str, Any]]] | None = None,
    region: tuple[float, float, float, float] | None = None,
    repo_root: str | None = None,
    treatment: str | None = None,
) -> dict[str, Any]:
    """Judge the composed poster. Up to two extra Ideogram calls. Place a pass, or the last image.

    ``imagePath`` is None when the first image is the one to place. Otherwise it is
    the project-relative path of the chosen later attempt.
    """
    from poster_design import TREATMENTS

    refs = [p for p in (reference_paths or []) if p][:JUDGE_MAX_REFERENCES]
    current_abs = _resolve_image(image_path, repo_root)
    current_rel: str | None = None
    current_treatment = treatment or ""
    switched = False
    last: dict[str, Any] = {"passed": False, "reason": "The picture did not pass.", "critique": ""}
    for attempt in range(1, MAX_IDEOGRAM_ATTEMPTS + 1):
        verdict = _judge_one(current_abs, refs, palette, brand_profile, llm_fn, region)
        last = verdict
        if verdict.get("passed") is True:
            return {
                "passed": True,
                "reason": verdict["reason"],
                "attempts": attempt,
                "retried": attempt > 1,
                "skipped": False,
                "imagePath": current_rel,
                "treatment": current_treatment,
                "dropImage": False,
            }
        if verdict.get("skipped") and verdict.get("passed") is None:
            return {
                "passed": None,
                "reason": verdict["reason"],
                "attempts": attempt,
                "retried": attempt > 1,
                "skipped": True,
                "imagePath": current_rel,
                "treatment": current_treatment,
                "dropImage": False,
            }
        suggested = str(verdict.get("suggestedTreatment") or "same")
        if (
            not switched
            and suggested in TREATMENTS
            and suggested != current_treatment
            and suggested != "same"
        ):
            current_treatment = suggested
            switched = True
        if attempt == MAX_IDEOGRAM_ATTEMPTS or regenerate is None:
            break
        try:
            rel, _data, _meta = regenerate(
                retry_prompt(
                    f"{prompt} Treatment {current_treatment}.",
                    verdict.get("reason") or "",
                    verdict.get("critique") or "",
                )
            )
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            json.JSONDecodeError,
            ValueError,
            TimeoutError,
            OSError,
        ) as exc:
            return {
                "passed": False,
                "reason": _truncate(f"{verdict.get('reason')} Retry failed ({exc}); placed the last image.", 180),
                "attempts": attempt,
                "retried": attempt > 1,
                "skipped": False,
                "imagePath": current_rel,
                "treatment": current_treatment,
                "dropImage": False,
            }
        current_rel = str(rel)
        current_abs = _resolve_image(current_rel, repo_root)
    return {
        "passed": False,
        "reason": last.get("reason") or "The picture did not pass.",
        "attempts": MAX_IDEOGRAM_ATTEMPTS if regenerate is not None else 1,
        "retried": current_rel is not None,
        "skipped": False,
        "imagePath": current_rel,
        "treatment": current_treatment,
        "dropImage": False,
    }
