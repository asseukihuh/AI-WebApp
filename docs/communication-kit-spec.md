# Communication kit

Website → communication kit → poster. The kit is the brand book CommMaker designs when a
site is too thin to borrow from, and the formalised system when the site already has one.
Poster briefs stay a separate, cheaper call.

## 1. What a kit contains

Modelled on the Ai2 brand toolkits (logo system, colour with proportions, type, graphic
devices, imagery, layout, templates, tone, do/don't):

| Section | What it fixes |
|---------|----------------|
| Logo system | Clear space (about half the mark height), minimum size, backdrop, one real logo and no box behind it |
| Colour | Roles (primary, secondary, accent, ink, surface, tint), a 60/30/10 proportion, and tints mixed from those roles |
| Type pairing | Display family + weight and a quieter body family |
| Graphic devices | Three to five kinds chosen from the logo and the sector, not a fixed sheet stamped on every brand |
| Imagery direction | Medium, motifs, colour treatment, and a text-free art direction for Ideogram |
| Layout motif | Composition, focal, whitespace, depth, and how the colour block is cut |
| Tone, do, don't | Short guardrails the poster is not allowed to break |

## 2. When the model designs

A site is thin when it has no usable photograph and at least one other gap: two colours or
fewer, almost no copy, or a single font. [bds-ig2i.fr](https://bds-ig2i.fr/) is the reference
(a green crest, almost no page). Stripe and Vercel are formalised from the palette and type
already on the page; their devices stay quiet.

`COMMMAKER_BRAND_MODEL` and `COMMMAKER_LLM_MODEL` both default to `claude-opus-5-5`.
The brand pass is cached per domain for seven days. Per-poster creative briefs and the
vision judge use the same Opus default. The tool schema is strict: `additionalProperties: false` and every
property required.

With no API key the same structure is filled by a sector heuristic (sport, payments,
developer, general) so a poster still gets devices.

## 3. Devices

A poster does not pick from a fixed shape catalog. The composition plan (`composition` on the
creative brief) may only use what was captured:

- `palette-gradient` — the site's own multi-hue palette (Stripe: blurple into the orange ribbon).
- `logo-geometry` — the scraped symbol, enlarged. Wordmarks stay a single logo, not a second giant word.
- `kit-photo` — a scraped photograph that does not already contain text.

A kind that is not one of those, or that the capture does not support, is not drawn. Offer and
proof lines are copied from the crisis facts, the tagline or the brand profile, or they are left empty.

Each device is a reusable SVG and, on the poster, PhotoCraft `shape.create` geometry
(bezier `path` knots, ellipses, polygons, rects, lines, RGBA and strokes).

## 4. Linearity tips → rules the audit can fail

From [9 poster design tips](https://www.linearity.io/blog/poster-design-tips/) (Emma Taggart).
Sketching and print process are workflow, not pixels. The rest are checks in
`poster_design.audit_plan`:

| Tip | Rule |
|-----|------|
| Make a statement with visuals + embrace minimal | **One focal point.** The headline is the only large type. At most one device is `focal`. |
| Headline grabs attention | **Strong hook.** ≤ 8 words, at least 54 px. |
| Details at about half the headline + create contrast | **Scale contrast.** Headline ≥ 2.1× the subline. |
| Headline need not sit in the middle; juxtapose elements | **Asymmetry.** Text on the left and an open field opposite, or a centred statement with imagery only at the edges. |
| Layer saturated shapes on a deep ground | **Layered depth.** A panel, card, scrim, or device sits behind the type. |
| Primary, secondary, accent as areas of colour | **Colour blocking.** A panel, card, or full-bleed brand field. Proportions aim at 60/30/10. |
| Create space | **Deliberate whitespace.** ≥ 35 % of the canvas free of text, logo and chip. |
| Still works as a phone-sized image | **Thumbnail readability.** Headline ≥ 44 px, subline ≥ 24 px, ≤ 30 words on the canvas. |
| (Logo system, not the article) | **Logo size.** On the safe margin, height at least 28 px and 48 px for a thin-site icon, width ≤ 3 columns, clear space, never boxed. |

`device-stage` is the template for a thin kit with no photograph: colour block on the left
(a diagonal crop for sport), the hook on that block, one large device on the right.

## 5. Cost

Accounting uses $15 / $75 per million tokens for the kit model and $3 / $15 for the poster
brief (override with `COMMMAKER_BRAND_PRICE_*` and `COMMMAKER_LLM_PRICE_*`).

| Step | Typical |
|------|---------|
| Kit analysis, ~2,000 in / 1,200 out, once per domain | **~$0.12** |
| Cache hit | $0 |
| Poster brief, Sonnet, ~1,800 in / 600 out | **~$0.01** |
| Poster brief + one Ideogram background | **~$0.07** |

## 6. Where it shows up

Onboard renders the kit under the brand profile: proportions, hex colours, the type pairing,
imagery direction, devices (kind, role, colour), and the do/don't lists are editable. The
poster compiler reads that object on the next generate.
