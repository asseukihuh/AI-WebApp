# NOTES.md

Project update tracking, changelog, and roadmap for `ai-webapp`.

---

## 📝 Recent Updates

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
