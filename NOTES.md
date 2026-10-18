# NOTES.md

Project update tracking and changelog for CommMaker.

---

## 📝 Recent Updates

### 2026-10-18 - A real poster prompt

- The crisis form has a poster prompt: a short paragraph, not only a title. That text is the main instruction to the brief and to Ideogram. A headline written in it, such as “headline Stay somewhere new”, becomes the title and does not replace the paragraph.
- The Ideogram prompt names the subject: a sunlit home interior for a photo brand, or one flat character in the brand hexes. It does not say only “in the brand’s visual language.” UI-card crops are not described as the picture.
- The brand page shows the crops Claude kept before a poster is generated.
- A missing font is still reported once. Ideogram retries only when the image has text, a blur, a UI collage, or the wrong subject.

### 2026-10-18 - Do not edit a webpage screenshot

- Ideogram 4.5 treats the first `images` file as the picture to edit. A page or UI screenshot is not uploaded. Claude still reads those crops and the prompt asks for a text-free home photograph. A real photograph or a pattern with no UI text can still be sent.
- The photo band is the top two thirds. The type band is the bottom third, in the brand colour, with the scraped symbol large enough to read. Ideogram is told not to draw the logo.
- A failed judge retries with the prompt only. A UI collage is not placed when that retry was possible.

### 2026-10-18 - Ideogram size and a missing variable font

- `1440x720` is not an Ideogram 4.5 size. A poster with no reference image asks for `2880x1440`. A poster with reference images omits `size`, so the API uses `auto`. The raw `1200x627` is not sent.
- When Airbnb Cereal VF has no downloadable file, the headline uses the next captured family that has one, such as Circular or Roboto. The status line still says there is no file URL for Cereal. That does not fail the poster, and Ideogram is still called.

### 2026-10-18 - Airbnb photo band

- A hospitality or photography brand uses the photo-band treatment. Ideogram is asked for one text-free photograph of a home interior, with no UI card, headline, button, or abstract blur.
- The judge fails painted text and an abstract blur on a photography brand. That retry changes the picture prompt. A missing font file is reported once, with the URL that failed, and does not spend the image retries.
- A wide lockup is cropped to the symbol. The scraped paths are not redrawn. Airbnb Cereal VF is loaded from the captured variable-font file when that URL is in the kit.

### 2026-10-18 - Ideogram 4.5 request body

- The invalid field was `size`. The call sent `1280x720`, an Ideogram 4.0 preset. 4.5 returns 400 for that value. A 1200×627 poster now asks for `1440x720`.
- Example files that are not JPEG, PNG, or WEBP are not uploaded. An SVG is rasterized to PNG when that works, and dropped when it does not. A 400 includes Ideogram’s JSON message, such as `Invalid input`, in `ideogramError`.
- A reference wider than 6:1 or taller than 1:6 is center-cropped before upload so the graphic in the middle stays and the file lands inside Ideogram’s limit. A file that cannot be cropped is skipped. The poster still generates from the other images and the palette.

### 2026-10-18 - Scraped logos and the site's own type

- The logo layer is the scraped SVG or PNG, unchanged. A poor contrast mark gets a brand-color plate behind it. The file is not recolored, traced, or replaced with typeset letters. Ideogram is told not to draw a logo or a wordmark.
- A captured display family stays on the headline. Noto Sans Display is not a substitute for that family. If the font file is missing, the status line says the brand font failed to load. The judge fails a logo that is not the scraped asset and a headline that is not the captured display font.

### 2026-10-18 - Product name is CommMaker

- Removed the unused Ollama chat page, the experimental image page, and their styles, scripts, and curl notes.
- The README describes the website → brand kit → editable LinkedIn poster flow.

### 2026-10-18 - Website and social images feed the Ideogram prompt

- The brand pass stores a small packet: palette hexes with roles, one imagery line written from the site screenshots and public social images, and up to five graphic examples that are not page text.
- Posters call Ideogram 4.5 (`POST /v2/image/generate/ideogram-4-5`) for every treatment, including a quiet type poster. Brand capture screenshots distinct components. Claude keeps up to five graphic crops and skips page text. All of those crops are uploaded on the `images` field so Ideogram can see how the components are built. The poster is one coherent text-free asset in that language, not a collage of the examples, and it does not copy their words. The judge fails a generic black triangle and a jungle of every example. A retry uploads the same examples again.
- When Playwright is missing, the status line says screenshots were skipped, so Ideogram only received colours.

### 2026-10-18 - Logo and headline colour follow the field

- The wordmark and the headline take white or brand ink from the pixels behind them. The SVG’s original black does not win when it misses 4.5:1. A light or mid field uses white. Brand ink is used only when that field lets ink clear 4.5:1. A colour band uses white or the band’s contrast colour, whichever clears 4.5:1.
- The judge fails logo or headline contrast under 4.5:1.

### 2026-10-18 - Display type on every treatment

- Headlines use the brand display face when that font is installed, otherwise Noto Sans Display. System fonts are not used.
- A headline is heavy, tightly leaded, and at most two lines with no orphan word. The subline is about half that size and lighter. A busy photo puts the type on a brand-colour band, not a grey slab.
- Full-sheet type stays left. Pattern, illustration, and quiet posters centre it. The judge fails a system font, a headline under 54px, a subline too close in size, low contrast, or a headline longer than eight words.

### 2026-10-18 - The brief chooses the treatment

- Treatments are full-sheet, photo-band, pattern-field, illustration-cluster, and quiet-type. The brand picks one. A stark mark stays type-led. A character brand can be an illustration cluster. Full-bleed is not forced on every poster.
- Ideogram runs only for a treatment that needs an image, with a prompt for that treatment. A quiet-type poster is not sent.
- The judge can reject the treatment (“full-bleed was wrong for this brand”). One retry may switch treatment. At most two extra Ideogram calls. The status line names the treatment, the judge result, and the attempt count.

### 2026-10-18 - A picture frame must call Ideogram

- The HTTP call was nested under `heroStrategy == "ideogram_generate"` and a non-empty `heroImagePrompt`. A picture frame whose brief said solid, or whose prompt was empty, compiled the stand-in ellipse and returned immediately. No request reached Ideogram.
- A picture frame with `IDEOGRAM_API_KEY` set now POSTs before compile, even when the brief did not ask for Ideogram. The response always includes `ideogramUsed`, `ideogramMs`, and `ideogramError`. A skip says why and sets `ideogramMs` to 0, and the crisis status line shows that instead of a success.
- The illustration judge runs only after a real PNG: one vision check, then at most one retry. No PNG is not a pass.

### 2026-10-18 - The empty circle was the stand-in

- A picture-frame bitmap was placed before the solid field, so the field covered it. When Ideogram did not return a file, `circle-stage` still drew the light-blue “Illustration plate” and the status line omitted the error.
- The bitmap is now placed above the field. If the key is set and the call fails, the status line includes the error. The ellipse remains only when there is no bitmap.

### 2026-10-18 - One check of the Ideogram picture

- After a picture frame is generated, one Sonnet vision call scores the bitmap only: no letters, not a flat disc, one focal subject, some depth, brand colour. Linearity rules for the picture are one focal point, layered depth, brand colour, and the subject not lost in empty space.
- A failure adds that critique to the prompt and calls Ideogram once more. The second image is not judged. Worst case extra is about $0.07 (the vision call plus one image).

### 2026-10-18 - Picture frames call Ideogram

- `circle-stage` was drawing a flat ellipse and parking the wordmark inside it. The design score only graded the type, so that looked like a pass.
- A picture frame with an Ideogram key now generates a text-free illustration (palette, magic prompt off, no remix) and places that bitmap. The ellipse is only the stand-in when there is no bitmap. The scraped mark stays in the type column.
- The crisis status line shows whether Ideogram ran, the frame name, and a prompt snippet.

### 2026-10-18 - One brand call, social formats

- Site scrape, site screenshots and public social screenshots run together. Instagram and LinkedIn are opened with a fresh browser: no login, no cookies, no bypass. A login wall is recorded and skipped.
- One Opus call, cached 7 days per domain, returns the brand profile, the communication kit and `socialStrategy` (voice, recurring formats, what not to invent).
- Each poster is one Sonnet brief. The art director runs only when the design audit fails. Ideogram runs only for a photo, illustration, product or gradient texture, not for type-only or a vector mark.

### 2026-10-18 - Layout follows the brand

- The brief picks a frame from the brand: gradient field, photo block, illustration circle, product card, stark symbol, crest stage, or quiet type. Quiet type is only for a monochrome site. A gradient brand stays on the full-bleed field.
- Ideogram, when a key is set, paints the photograph, illustration, product or gradient as a raster behind the type. A crest or triangle stays a vector. Remix is not called.
- Without a key, photo and product frames draw a stand-in picture instead of a flat recolor of the same stack.

### 2026-10-17 - Crisis poster follows the composition

- The crisis compiler was still emitting a centred statement: homepage tagline as the subline, dark wordmark, flat purple, no CTA. A left-hand composition now uses the full-bleed field, a white wordmark on the dark stop, the profile or fact line instead of a generic locale tagline, and a CTA. Ideogram runs when a key is set, prompted from the captured imagery language.

### 2026-10-17 - Identity-true posters

- Poster imagery comes from the captured palette, the real symbol mark, or a usable photo. Catalog shapes (bars, chevrons, dot grids) are not drawn.
- The creative brief carries a composition plan: text region, which captured visual is focal, colour-block cut, whether Ideogram should paint the field, and whether there is a CTA. Offer and proof lines have to come from the facts or the site.
- Ideogram 4 generate has no image-reference input. Screenshots are vision context for the brief; the generate call gets the text-free prompt and the palette. Remix is not used, because it would keep page text.

### 2026-10-17 - Communication kit

- Thin sites (BDS IG2I and the like) get a designed kit: colour proportions, type pairing, and a few graphic devices drawn from the logo and the sector.
- `COMMMAKER_BRAND_MODEL` and `COMMMAKER_LLM_MODEL` both default to `claude-opus-5-5`. The poster brief and the vision judge use that default. Brief and judge are priced at Opus rates, $15 / $75 per million tokens.
- Posters place the devices as PhotoCraft vectors and score the Linearity rules (one focal point, hook, scale, asymmetry, depth, colour block, whitespace, thumbnail type, logo size).
- Onboard edits the kit before a poster is generated.
