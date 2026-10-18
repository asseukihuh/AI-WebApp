# NOTES.md

Project update tracking, changelog, and roadmap for `ai-webapp`.

---

## 📝 Recent Updates

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
- `COMMMAKER_BRAND_MODEL` defaults to `claude-opus-5-5` for that pass, cached per domain. Poster briefs stay on `claude-sonnet-5-5`.
- Posters place the devices as PhotoCraft vectors and score the Linearity rules (one focal point, hook, scale, asymmetry, depth, colour block, whitespace, thumbnail type, logo size).
- Onboard edits the kit before a poster is generated.

### 2026-09-14 - Architecture & Codebase Refactoring

- **Directory Restructuring**:
  - Moved stylesheets into dedicated `src/css/` directory (`chatbot.css`, `imageGen.css`).
  - Moved JavaScript application logic into dedicated `src/js/` directory (`chatbot.js`, `imageGen.js`).
  - Moved raw API testing notes to `docs/notes-test.txt`.
  - Added root `index.html` as the default entry point that redirects directly to the chat interface (`chatbot.html`).

- **Frontend Security & Standards**:
  - Converted deprecated XHTML strict documents to modern HTML5 (`<!DOCTYPE html>`).
  - Fixed broken script and stylesheet references (`style.css` / `functions.js` -> `src/css/chatbot.css` / `src/js/chatbot.js`).
  - Prevented XSS injection risks by escaping prompt and response texts before rendering.
  - Replaced inline `onclick` handlers with DOM `addEventListener`.
  - Added user experience enhancements: Enter key submission, Shift+Enter multi-line input, loading/disabled state indicators, and error banners.

- **Documentation & Agent Context**:
  - Restructured `README.md` with detailed installation guides for Linux, macOS, and Windows.
  - Added `AGENTS.md` specifying developer and agent rules, guidelines, and project conventions.
  - Added `NOTES.md` for recording version updates and planned improvements.

---

## 📌 Development Notes & Conventions

- **API Endpoints**:
  - Chat: `POST http://localhost:11434/api/chat`
  - Generate: `POST http://localhost:11434/api/generate`
- **Conversation State**:
  - Maintains a sliding conversation history window (`MAX_HISTORY_LENGTH` in `chatbot.js`).
- **Dependencies**:
  - Pure vanilla web technologies (HTML, CSS, JS); no build steps, bundlers, or package managers required.

---

## 🚀 Roadmap & Future Improvements

- [ ] **Streaming Responses**: Implement Server-Sent Events / Chunked response streaming (`stream: true`) to stream tokens in real-time.
- [ ] **Model Auto-Discovery**: Query Ollama's `GET /api/tags` endpoint dynamically to populate the model select dropdown with installed models.
- [ ] **System Prompt Configuration**: Add an expandable UI field for custom system prompt instructions.
- [ ] **Chat Persistence**: Save chat sessions to browser `localStorage` or `IndexedDB`.
- [ ] **Markdown Rendering**: Render formatted text, tables, and code snippets with copy-to-clipboard buttons.
- [ ] **Dark / Light Theme Toggle**: Add user theme preferences.
