# Ideogram 4.0 hero images

CommMaker can generate LinkedIn poster hero art with **Ideogram 4.0** when the creative brief sets `heroStrategy: ideogram_generate`.

## When it runs

1. Crisis calls `POST /api/creative-brief` (Phase B LLM or rule fallback).
2. `POST /api/generate-poster` sees `ideogram_generate` and `heroImagePrompt`.
3. If `IDEOGRAM_API_KEY` is set, the dev server calls Ideogram, downloads the PNG (URLs expire), and caches it under `generated/assets/hero-ideogram-<hash>.png`.
4. The poster compiler uses that file as the photo hero (cover-filled to **1200×627**).

Without a key (or on API error), the server falls back to scraped kit photo or brand gradient and returns `ideogramFallback` in the JSON response.

## API

- **Endpoint:** `POST https://api.ideogram.ai/v2/image/generate/ideogram-4`
- **Header:** `Api-Key: $IDEOGRAM_API_KEY`
- **Body:** `prompt`, `resolution`, optional `rendering_speed` (`turbo` | `default` | `quality`)

### Resolution

LinkedIn posters target **1200×627**, but Ideogram 4.0 only accepts [preset resolutions](https://developer.ideogram.ai/api-reference/images/generate/ideogram-4). CommMaker requests **`1280x720`** (closest landscape preset). PhotoCraft scales/crops to 1200×627 via existing hero **cover** placement.

For an exact custom crop, Ideogram’s **reframe** APIs (v2/v3) are a possible follow-up; this MVP does not call reframe.

## Environment

| Variable | Purpose |
|----------|---------|
| `IDEOGRAM_API_KEY` | Required for AI hero generation |
| `COMMMAKER_IDEOGRAM_RENDERING` | Optional: `TURBO`, `DEFAULT`, or `QUALITY` (maps to Ideogram `rendering_speed`) |

## Creative brief fields

| Field | Description |
|-------|-------------|
| `heroStrategy` | Add `ideogram_generate` |
| `heroImagePrompt` | On-brand scene description (no homepage screenshots); LLM writes this when choosing Ideogram |

## Response metadata (`POST /api/generate-poster`)

| Field | When |
|-------|------|
| `heroSource` | `ideogram-4` on success |
| `heroImagePrompt` | Prompt sent to Ideogram |
| `ideogramResolution` | Preset used (e.g. `1280x720`) |
| `resolutionNote` | Explains preset vs 1200×627 |
| `ideogramFallback` | Human-readable message when falling back |

## Tests

```bash
python3 scripts/test_ideogram_client.py
python3 scripts/test_creative_brief.py
```
