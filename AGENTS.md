# AGENTS.md

Guidelines and operational context for AI agents working in this repository.

---

## 1. Project Overview

CommMaker turns a website into a brand kit, then into an editable LinkedIn poster opened in PhotoCraft.

- **Shell**: Vanilla HTML5, CSS3, and ES6+ JavaScript (`home.html`, `onboard.html`, `crisis.html`, `photocraft/`).
- **Dev server**: `python3 scripts/serve-static.py` (Windows: `scripts/dev-commmaker.ps1`, which loads `.env` and installs the PhotoCraft web editor).
- **Poster pipeline**: Python modules under `scripts/` (brand profile, communication kit, creative brief, Ideogram, poster compile, PhotoCraft CLI).
- **Editor**: PhotoCraft static site in `vendor/photocraft-web/` (gitignored; installed by `scripts/fetch-photocraft-web.sh` or `scripts/dev-commmaker.ps1`).

The GitHub repository is `asseukihuh/AI-WebApp`. Do not rename it.

---

## 2. Directory & File Organization

```
├── index.html                 # Redirects to home.html
├── home.html                  # Flow overview
├── onboard.html               # Website → brand profile and communication kit
├── crisis.html                # Brief → caption and poster
├── photocraft/index.html      # PhotoCraft editor embed
├── src/css/                   # commmaker.css, photocraft.css
├── src/js/                    # onboard, crisis, kit, brand profile, editor
├── scripts/                   # Dev server, scrape, brand, kit, poster, PhotoCraft
├── docs/                      # Brand, kit, brief, poster, and local-run notes
├── vendor/photocraft-web/     # PhotoCraft web build (downloaded)
├── generated/                 # Local poster output (.pcraft); gitignored
├── .env.example               # API keys (copy to .env; not committed)
├── AGENTS.md
├── NOTES.md
├── README.md
└── LICENSE
```

---

## 3. Coding Guidelines & Best Practices

### HTML
- Use modern HTML5 (`<!DOCTYPE html>`, UTF-8, responsive viewport).
- Keep elements semantic (`header`, `main`, `section`, `form`).
- Avoid inline JS event handlers (`onclick="..."`).
- Scripts should use `defer` or `type="module"`.

### JavaScript
- Use strict modern ES6+ (`const`, `let`, arrow functions, async/await).
- Never inject raw, unescaped user or model input into `innerHTML`. Use `escapeHtml` or safe DOM APIs (`textContent`, `createElement`).
- Disable inputs and buttons while a request is in flight.

### CSS
- Styles live in `src/css/`.
- Use descriptive class names.
- Layout with Flexbox or Grid.

### API
- The shell talks to the dev server (`/api/brand-profile`, `/api/creative-brief`, `/api/generate-poster`, and the scrape routes in `scripts/serve-static.py`).
- Use `stream: false` on model calls unless a streaming UI exists.
- Poster output is a `.pcraft` opened by the PhotoCraft embed. Do not replace that with a flattened-only preview.

---

## 4. Testing & Verification

1. **Syntax** — check changed JavaScript with Node:

   ```bash
   node -c src/js/commmaker-common.js
   node -c src/js/onboard.js
   node -c src/js/crisis.js
   node -c src/js/brand-profile.js
   node -c src/js/communication-kit.js
   node -c src/js/photocraft.js
   ```

2. **Dev server** — `python3 scripts/serve-static.py --port 8000`. Confirm `/` redirects to `home.html`, and Onboard, Crisis, and `/photocraft/` load.

3. **Python** — run the tests that cover the modules you changed (`python3 scripts/test_<module>.py`).
