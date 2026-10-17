# CommMaker poster design system (LinkedIn 1200×627)

Rules the creative brief chooses from and `scripts/poster_compiler.py` enforces. Tokens live in
`scripts/poster_design.py`; change numbers there, then here.

Target bar: Google Pomelli–class marketing visuals, built on Adobe's core design principles.

## 1. Adobe fundamentals → concrete rules

| Principle | Rule in CommMaker |
|-----------|-------------------|
| **Hierarchy** | Max 3 text levels + 1 CTA: eyebrow → headline → subline → CTA chip. Headline ≥ 2.1× subline size and weight 700–800; subline 400. |
| **Contrast** | WCAG 2.2 measured against the **sampled** background (p90 luminance under light text, p10 under dark text): headline, subline, CTA label ≥ **4.5:1**; logo and CTA chip edge ≥ **3:1** (non-text, SC 1.4.11). |
| **Alignment / grid** | 12-col grid; every text block, the logo and the CTA share one left edge (or one centre axis in the centred template). No free-floating coordinates. |
| **Balance** | Text mass on one side, visual mass (image subject) on the other. Ideogram gets a bounding box for the subject that stays out of the text zone. |
| **Whitespace / negative space** | ≥ 18 % of the canvas free of text, logo and chip boxes, so a full-bleed brand image can carry the poster. A flat single-colour field with no imagery fails visual-mass (imagery must cover ≥ 25 %). |
| **Repetition / brand consistency** | Brand fonts (Google Fonts fetch → Inter fallback), brand palette roles (brand / dark / accent) reused for panel, CTA, eyebrow; one real logo (scraped SVG), never a generated one. |
| **Emphasis / focal point** | One focal point per poster: the headline (statement layouts) or the image subject (split / full-bleed). CTA is the only saturated UI element. |
| **Legibility** | Min sizes at 1200 px: headline 44, subline 24, CTA 20, eyebrow 15 (caps + tracking). LinkedIn mobile renders at ~0.3×, so nothing smaller. |
| **Color harmony** | 60 / 30 / 10: background imagery or brand surface (60), scrim / panel in brand-dark (30), accent for CTA + eyebrow (10). Scrims are tinted brand-dark, never neutral grey. |

## 2. Grid and safe margins

| Token | Value |
|-------|-------|
| Canvas | 1200 × 627 px, 72 ppi |
| Safe margin | x **60**, y **56** |
| Columns | **12**, column **68**, gutter **24** (`col_x(i) = 60 + 92·i`) |
| Common spans | 5 col = 436, 6 = 528, 7 = 620, 8 = 712, 10 = 896, 12 = 1080 |
| Baseline unit | 8 px (vertical gaps are multiples of 8) |

## 3. Type scale and weights

| Role | Size (px) | Weight | Leading | Tracking | Max |
|------|-----------|--------|---------|----------|-----|
| Eyebrow | 15 | 700, caps | 1.2 | +120 | 3 words / 28 chars |
| Headline `xl` | 76 | 800 | 1.05 | −15 | ≤ 4 words |
| Headline `lg` | 64 | 800 | 1.05 | −15 | ≤ 7 words |
| Headline `md` | 54 | 700 | 1.08 | −10 | ≤ 10 words / 60 chars, 3 lines |
| Subline | 26 | 400 | 1.35 | 0 | 1 sentence, ≤ 18 words / 110 chars, 2 lines |
| CTA label | 20 | 600 | 1.0 | +10 | ≤ 3 words / 22 chars |

The brief picks `headlineScale`; the compiler downsizes (never below 44) until the headline fits
its box at an estimated 0.53 em per character (Inter measures ≈ 0.48). Headline and subline line
breaks are planned and **balanced** (no single-word last line) and written into the type layer, so
the rendered height always matches the planned stack.

## 4. Contrast and scrims

1. Sample the actual background raster (Ideogram or kit photo) under each text box; gradients are
   sampled analytically.
2. Pick text colour (white vs brand ink) with the higher contrast against the worst-case pixels.
3. If < 4.5:1, add a **gradient scrim**: brand-dark colour, alpha = the minimum that reaches 4.5:1
   (capped at 0.85), held across the text box, fading to 0 within **200 px** beyond it.
4. Direction follows the template (bottom-left diagonal, left→right, or radial from the text
   centre). Scrims are native PhotoCraft *Gradient Fill* layers, so they stay editable.
5. **Never** a flat full-width band, never neutral grey, never > 0.85 alpha. If 0.85 is not
   enough, the compiler switches to the **text-panel** template (solid surface).

## 5. Logo

- One logo: the scraped kit SVG/PNG. Generated images must contain **no** logos, wordmarks or text.
- Scraped `og:image` social cards (`heroImageKind: og-marketing`) are never used as backgrounds:
  they almost always carry the logo and a headline. They are treated like busy or brand-mark heroes
  (Ideogram when a key is set, otherwise the brand gradient). `COMMMAKER_ALLOW_OG_HERO=1` opts back in.
- Position: top-left at the safe margin, aligned with the text column (top-centre for the
  centred template; on the panel for split).
- Size by aspect: wordmark (≥ 2.2:1) height 36, compact (1.2–2.2) 44, icon 48; width ≤ 3 columns
  (252 px). Clear space ≥ 0.5 × logo height.
- Colour by luminance: the compiler samples the background under the logo and picks the variant
  (original, white, ink) with the best contrast, which must be ≥ 3:1. Raster logos that fail get a
  soft radial scrim behind them.

## 6. CTA chip

- Pill: height 48, radius 24, horizontal padding 24, label 20 / 600, sentence case.
- 32 px below the subline, on the text column's left edge (centred in the centred template).
- Fill: brand accent if label contrast ≥ 4.5:1 and chip-vs-background ≥ 3:1; otherwise an
  inverse pill (white on dark, ink on light). One CTA maximum; `ctaStyle: none` hides it.

## 7. Copy limits

Total ≤ 30 words on canvas. Facts and long explanations go to the LinkedIn caption, not the poster.
No body paragraph and no footer URL on the poster.

## 8. Layout templates

Ideogram bounding boxes use `[y_min, x_min, y_max, x_max]` on 0–1000.

| Template | Use for | Text zone | Image | Scrim | Ideogram composition |
|----------|---------|-----------|-------|-------|----------------------|
| `full-bleed-scrim` | Photo / abstract hero with a strong subject | cols 1–7, bottom-anchored | full bleed | diagonal gradient from bottom-left | subject `[60, 560, 640, 960]`; lower-left calm and darker |
| `split-text-left` | Product / announcement, crisp brand feel | cols 1–5 on a brand panel (x 0–600) | right half, right-aligned crop | none (solid panel) | subject `[120, 560, 880, 960]`; left half plain |
| `text-panel` | Busy or bright imagery, crisis updates | rounded card cols 1–7, bottom-anchored | full bleed | none (card is 96 % opaque surface) | subject `[100, 640, 900, 960]`; left two-thirds soft |
| `centered-statement` | Big statement, gradient or texture background | cols 2–11, centred | full bleed or brand gradient | radial gradient from text centre | detail only at left/right edges; centre calm |
| `device-stage` | Thin communication kit: colour block + one graphic device | cols 1–6 on the block | devices in the open right field | none (the block is the surface) | one abstract device on the right; left block plain |

Defaults: `photo-hero-type` → `full-bleed-scrim`; `gradient-brand` / `minimal-wordmark` →
`centered-statement`; crisis + `urgent` → `text-panel`. A thin `communicationKit` with no
photograph uses `device-stage` (diagonal crop when the kit asks for it).

## 8b. Communication kit and Linearity checks

`scripts/communication_kit.py` designs the kit (see `docs/communication-kit-spec.md`). The compiler
places its devices with PhotoCraft `shape.create` and the audit scores these rules:

| Rule | Pass when |
|------|-----------|
| One focal point | Headline is the largest type, and at most one device has role `focal` |
| Strong hook | Headline ≤ 8 words and ≥ 54 px |
| Scale contrast | Headline ≥ 2.1× the subline |
| Asymmetry | Text sits on the left with an open field opposite, or a centred statement keeps imagery at the edges |
| Layered depth | A panel, card, scrim, or kit device sits behind the type |
| Colour blocking | A panel, card, or full-bleed brand field |
| Deliberate whitespace | ≥ 18 % free of text, logo and chip. Visual mass ≥ 25 % from a multi-hue palette, a symbol mark, or a photograph |
| Thumbnail readability | Headline ≥ 44 px, subline ≥ 24 px |
| Logo size | Height ≥ 28 px (kit icons target 48), width ≤ 3 columns, on the safe margin |

## 9. Ideogram 4 prompting

- Structured JSON prompt (`high_level_description`, `style_description`, `compositional_deconstruction`)
  with **zero `text` elements**, subject `obj` boxes from the template, and the brand palette in
  `style_description.color_palette`.
- `magic_prompt: "off"`, so Ideogram doesn't rewrite the prompt and re-inject brand names.
  Ideogram 4 has no `negative_prompt` parameter, so exclusions are expressed positively ("clean,
  text-free abstract surface").
- Brand names, quoted strings, hex codes and words like *logo / wordmark / text / headline / poster*
  are stripped from LLM scene descriptions before they reach Ideogram.

## 10. Art-director pass (optional)

After compiling, the compiler audits the plan (grid alignment, contrast, word counts, whitespace,
hierarchy ratio) and stores `meta.designAudit`. When an LLM provider is configured and
`COMMMAKER_ART_DIRECTOR` isn't `off`, one text-only call reviews the layer metadata and may
shorten copy or change `headlineScale` / `headlineWeight` / `ctaStyle` / `eyebrow`. The poster is
recompiled once. The template is never changed after the image is generated.

## 11. Optional `brandProfile` inputs

`/api/creative-brief` and `/api/generate-poster` accept an optional `brandProfile` object; when the
request has none they use the one onboarding saves on `kit.brandProfile` (`scripts/brand_profile.py`).
Every field is optional and nothing is required:

| Field | Used for |
|-------|----------|
| `palette` (list of `{role, hex}` with roles `primary`, `secondary`, `accent`, `text`, `surface`, `background`; also a role dict or plain hex list) | Brand = `primary`, dark = `text` (only if dark enough), light = `background` (only if light enough), accent = `accent`. `secondary` is never used as text. Ideogram `color_palette` is ordered primary → accent → secondary → text → surface → background |
| `aesthetic[]` | Ideogram `style_description.aesthetics` and the LLM brief prompt |
| `imageryStyle` (`{primaryMedium, motifs[], colorTreatment, …}` or a string) | Ideogram `art_style` as a short phrase (medium; motifs; colour treatment). Text-prone media (`product-ui`, `typographic`, `mixed`) are dropped |
| `layoutTraits` (`{composition, density, …}` or a list of strings) | Template hint when the brief doesn't pick one, from `composition` (e.g. "split" → `split-text-left`, "centered" → `centered-statement`, "left-aligned" → `full-bleed-scrim`) |
| `typography` (`display` or `headline`, `body`; `weights[]`) | Font preference; the heaviest display weight ≥ 600 picks bold / extrabold |
| `toneOfVoice[]` | LLM brief and copy prompt |

## 12. Samples and verification

`python3 scripts/render_poster_samples.py --out-dir <dir>` renders the Stripe and Vercel fixtures
through PhotoCraft and flattens them to PNG. It runs offline with procedural stand-in backgrounds
that follow each template's negative space; with `--ideogram` and `IDEOGRAM_API_KEY` it uses real
Ideogram backgrounds instead. `--code-root <worktree> --before` renders the same inputs with another
checkout's compiler for before/after comparisons. Unit tests: `python3 -m unittest scripts.test_poster_design`.
