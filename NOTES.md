# NOTES.md

Project update tracking, changelog, and roadmap for `ai-webapp`.

---

## 📝 Recent Updates

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
