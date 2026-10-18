# Brand Profile (hybrid AI + vision)

`POST /api/brand-profile` builds a Pomelli-style Business Profile from a URL. Module: `scripts/brand_profile.py`. UI: Onboard → **Analyze brand** (`src/js/brand-profile.js`).

## Flow

1. **Static scrape:** the existing `kit_scraper.py` reads meta, linked CSS, Google Fonts, header SVG/img logo and og:image.
2. **Rendered capture (Playwright):**
   - Screenshots: desktop above-the-fold (1440×900), desktop full page (capped at 5400 px) and mobile fold (390×844 @2x), saved to `generated/brand-profiles/<domain>/`.
   - One `page.evaluate` collects computed-style signals: page background, colour usage weighted by area and text length, gradient stops, `:root` CSS variables, loaded `FontFace`s, font usage per tag and weight, CTA buttons (bg, border, radius), headings, paragraphs, nav and social links.
   - Logo candidates come from the header / home link. Each has its backdrop colour, and its SVG `var(--…)` / `currentColor` fills are inlined with the computed values.
3. **Pixel palette:** Pillow median-cut on the fold screenshot gives dominant colours by pixel share. This catches colours that live only inside images or gradients.
4. **Candidates:** colours, fonts and logos from all sources are merged and ranked (`c1…`, `f1…`, `L1…` / `K1…`). These are the ground truth for exact values.
5. **One Opus call** (`claude-opus-5-5`, `COMMMAKER_BRAND_MODEL`), cached 7 days per domain. The scrape, the site screenshots and the public social screenshots are captured in parallel first. The call returns the brand profile, the communication kit and `socialStrategy` together (`submit_brand_bundle`). Social pages are public only: no login, no cookies, no bypass. A login wall is recorded in `social.visits` and its screenshot is not sent. `socialStrategy` has `voice`, `formats` (`type-only`, `photo-card`, `character-scene`, `product-ui`, `communique`, `gradient-field`) and `doNotInvent`.
6. **Reconcile:** AI picks are mapped back onto candidates.
   - **Colours:** each hex is snapped to the nearest scraped colour (CIE76 ΔE ≤ 14), giving `source: procedural, verified: true`. If the `candidateId` and the hex disagree, the hex wins. Colours seen only in the screenshots stay `source: vision, verified: false`.
   - **Fonts:** families are matched to scraped families (accent- and `-var`-insensitive, so "Söhne" matches `sohne-var`). Weights are intersected with the weights actually loaded.
   - **Logo:** the chosen rendered logo replaces `kit.logoSvg` / `kit.logoUrl`.
7. **Cache:** `generated/brand-profiles/<domain>/profile.json` is kept for 7 days. Use `refresh: true` (the UI's "Re-analyse" checkbox) to bypass it. A cached fallback result is re-analysed automatically once an LLM key is configured.

### Fallbacks

- **No LLM key, or the model call fails:** a deterministic heuristic profile is built from the same signals (`source: fallback`, `fallbackReason` set to `no_provider`, `no_api_key` or `llm_error`). Its palette roles come from the page background, the dominant text colour, CTA backgrounds and vivid gradient or pixel colours. Aesthetic tags come from gradient, darkness and corner-radius cues.
- **No Playwright or Chromium:** `capture.available` is `false` with a `reason`. The profile is then built from static-scrape signals only, and the model receives text signals without images.

## Downstream hooks

- **Profile → kit:** `apply_brand_profile_to_kit(kit)` runs at the start of `/api/creative-brief` and `/api/generate-poster`. It projects the user-edited `kit.brandProfile` onto the legacy fields the poster stack reads (`colors` and `accentColors` with primary first, `fonts` as display + body, `tagline`, `siteName`). `poster_compiler.py` is unchanged.
- **Creative brief:** `creative_brief.kit_summary_for_prompt` appends the profile block (palette roles, typography, aesthetic, tone, values, imagery, layout traits, doNots, art direction).
- **Ideogram:** `augment_ideogram_prompt` appends aesthetic tags, medium, motifs, colour treatment, palette hexes and the profile's `ideogramPrompt` (background layer only), plus avoid-terms, to the brief's prompts before generation. Text already in the prompt isn't repeated.

## API

```bash
curl -s -X POST localhost:8000/api/brand-profile \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://stripe.com","refresh":false,"mobile":true}'
```

The response includes:

- `brandProfile` and `kit` (scraped kit with `brandProfile` attached and the chosen logo applied).
- `capture`: `available`, `reason`, `durationSec`, and `screenshots` (public `/generated/...` paths).
- `source`: `llm` or `fallback`.
- `model`, `provider`, `usage` (`inputTokens` / `outputTokens`) and `costUsd`.
- `estimatedImageTokens`, `cached`, and `signals` (top candidates, for debugging).

## Setup

```bash
pip install playwright pillow
python -m playwright install chromium   # or reuse system Chrome (auto: channel "chrome")
export ANTHROPIC_API_KEY=sk-ant-…
python3 scripts/serve-static.py --port 8000
python3 scripts/test_brand_profile.py   # offline, fixture-based
```

| Variable | Purpose |
|----------|---------|
| `COMMMAKER_BRAND_PROFILE_MODEL` | Override the vision model. Defaults to the creative-brief model (`claude-opus-5-5` on Anthropic). |
| `COMMMAKER_CHROME_PATH` | Explicit Chromium/Chrome executable. Otherwise the bundled Playwright Chromium is tried first, then Chrome / Edge channels. |
| `COMMMAKER_LLM_PRICE_IN_PER_MTOK` / `_OUT_PER_MTOK` | Cost accounting in USD per million tokens (default 3 / 15). |

OpenAI and OpenRouter keys also work: images are sent as `image_url` data URIs with the `json_schema` response format.

## Cost per analysis

Measured on real Stripe and Vercel captures:

- **Input:** three images at about 4.5k tokens (fold 1440×900, plus the full-page and mobile shots downscaled to a 1568 px long edge), plus about 3k tokens of text and tool schema. Total about 8k.
- **Output:** about 1.3k tokens.
- **Cost:** about **$0.04 per analysis** at Sonnet-class list pricing. Opus-class models cost about 5× that.
- **Cache:** repeat analyses of a domain within 7 days are free.
- **Time:** capture takes 8–10 s; the vision call typically adds 15–35 s.
