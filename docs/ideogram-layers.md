# Ideogram multi-layer raster assets

CommMaker can generate **one or two** Ideogram raster layers when the creative brief sets `heroStrategy: ideogram_generate`. The poster compiler stacks them as separate PhotoCraft placements (not one flat designed poster).

## Layer stack (bottom → top)

1. **Background** — cover placement (`heroImagePrompt`); right-aligned half crop for `split-text-left`
2. **Accent illustration** (optional) — subject at the template's accent position (`accentImagePrompt`), max ~45% canvas width
3. **Text scrim** — native PhotoCraft gradient fill, contrast-solved against the sampled background and localized to the text zone (or a brand panel / card, depending on `layoutTemplate`)
4. **Eyebrow / headline / subline / CTA chip** — PhotoCraft text and shape layers
5. **Logo** — scraped kit SVG; original, white or ink variant picked by background luminance

## Prompt format

Ideogram receives a structured JSON caption, not free text (see [`poster-design-system.md`](poster-design-system.md) §9): the brief's scene description is sanitized (brand names, quoted copy, hex codes, *logo / text / wordmark* words removed), subject boxes come from the layout template so the text zone stays empty, the brand palette goes in `color_palette`, and there are no `text` elements. `magic_prompt` defaults to `off` so Ideogram doesn't rewrite the caption.

Kit photo heroes (`use_kit_photo`) still use a single background image layer, same as before.

## When it runs

1. Crisis calls `POST /api/creative-brief` (Phase B LLM or rule fallback).
2. `POST /api/generate-poster` reads `ideogramLayers` on the brief.
3. With `IDEOGRAM_API_KEY`, the dev server calls Ideogram 4.0 for the background (always) and optionally for an accent subject.
4. Accent layers may run through Ideogram 1 **remove-background** for a transparent PNG cutout (see env below).
5. PNGs are cached under `generated/assets/layer-ideogram-*.png`.

Without a key (or on API error), the server falls back to scraped kit photo or brand gradient and returns `ideogramFallback`.

**Crisis coercion:** When `IDEOGRAM_API_KEY` is set, the server upgrades LLM `gradient_from_palette` briefs to `ideogram_generate` (abstract brand background, `background-only`) for crisis/update flows so posters are not flat palette fills. Set `COMMMAKER_PREFER_IDEOGRAM=1` to force the same upgrade even without crisis facts. Busy or brand-mark kit heroes are still coerced as in PR #27.

## Creative brief fields

| Field | Description |
|-------|-------------|
| `heroStrategy` | `ideogram_generate` |
| `ideogramLayers` | `background-only` or `background-plus-accent` (default `background-plus-accent` when Ideogram key is set) |
| `heroImagePrompt` | Full-bleed background; lower-left negative space for type; no text in image |
| `accentImagePrompt` | Optional subject/illustration; no text, no logo (wordmark added separately) |

## Resolution presets

| Role | Default preset | Notes |
|------|----------------|-------|
| Background | `1280x720` | Closest landscape to LinkedIn 1200×627; compiler **cover**-fills |
| Accent | `1024x1024` | Sized for ~45% width placement on the right |

Ideogram 4.0 only accepts [preset resolutions](https://developer.ideogram.ai/api-reference/images/generate/ideogram-4); CommMaker maps requested sizes to the nearest preset.

## APIs

- **Generate:** `POST https://api.ideogram.ai/v2/image/generate/ideogram-4`
- **Cutout (accent):** `POST https://api.ideogram.ai/v2/image/remove-background/ideogram-1` (multipart `image` field)

Header: `Api-Key: $IDEOGRAM_API_KEY`

## Environment

| Variable | Purpose |
|----------|---------|
| `IDEOGRAM_API_KEY` | Required for AI layer generation |
| `COMMMAKER_IDEOGRAM_RENDERING` | Optional: `TURBO`, `DEFAULT`, or `QUALITY` |
| `COMMMAKER_IDEOGRAM_ACCENT_CUTOUT` | Default `true` — run remove-background on accent PNGs |
| `COMMMAKER_IDEOGRAM_MAGIC_PROMPT` | `off` (default), `auto` or `on` |
| `COMMMAKER_ART_DIRECTOR` | Default on (needs an LLM key) — one text-only layout review + recompile |
| `COMMMAKER_PNG_PREVIEW` | Default on — flatten each `.pcraft` to a sibling `.png` (`previewUrl`) |

## Response metadata (`POST /api/generate-poster`)

| Field | When |
|-------|------|
| `generatedAssets` | `[{ role, path, source }]` for each Ideogram raster |
| `heroSource` | `ideogram-4` on success |
| `ideogramLayers` | Brief layer mode used |
| `heroImagePrompt` | Background prompt |
| `ideogramResolution` | Background preset (e.g. `1280x720`) |
| `ideogramFallback` | Message when falling back |

| `previewUrl` | Flattened PNG of the saved `.pcraft` |
| `layoutTemplate` | Template the compiler used |
| `designAudit` | `{score, checks, failed}` against the design system |
| `artDirector` | `{score, issues, auditBefore, applied, auditAfter}` when the review ran |

Compiler batch `meta` includes `ideogramLayers`, `hasAccentLayer`, `layout`, `contrast`, `scrim` and `logoVariant`.

## Tests

```bash
python3 scripts/test_ideogram_client.py
python3 scripts/test_ideogram_layers.py
python3 scripts/test_creative_brief.py
python3 -m unittest scripts.test_poster_design
```
