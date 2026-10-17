# Local AI Web App (Powered by Ollama API) 🤖

A lightweight, dependency-free web application to interact with local Large Language Models using [Ollama](https://ollama.com/).

---

## 📌 Table of Contents

- [Features](#-features)
- [System Requirements](#-system-requirements)
- [Getting Started](#-getting-started)
  - [Linux](#linux)
  - [Windows](#windows)
  - [macOS](#macos)
- [Project Architecture](#-project-architecture)
- [License](#-license)

---

## 📋 Features

- **Local LLM Chat Interface**: Chat with models directly from your browser without external API keys or cloud services.
- **Context Preservation**: Maintains a conversational history window for continuous context.
- **Model Switching**: Switch between locally installed Ollama models (e.g. `mistral:7b`, `deepseek-r1:7b`, `starling-lm:7b`).
- **Responsive & Clean UI**: Accessible modern design with keyboard shortcuts (Enter to send, Shift+Enter for newline) and auto-scroll.
- **Experimental Generation**: Dedicated interface for experimental generation features (`imageGen.html`).

---

## 💻 System Requirements

### Minimal:
- **Operating System**: Linux, macOS, or Windows
- **Memory (RAM)**: 8 GB
- **Processor**: Modern multi-core CPU (4+ cores)
- **GPU**: Integrated GPU works, but inference may be slow

### Recommended:
- **Memory (RAM)**: 16 GB+
- **Processor**: Modern multi-core CPU (6+ cores)
- **GPU**: Dedicated GPU with at least 6 GB VRAM (CUDA/Metal supported)

---

## 🚀 Getting Started

### Linux

1. **Install Ollama**:
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ```

2. **Start Ollama service**:
   ```bash
   ollama serve
   ```

3. **Pull and test a model**:
   ```bash
   ollama run mistral:7b
   ```

4. **Clone the repository**:
   ```bash
   git clone https://github.com/asseukihuh/ai-webapp.git
   cd ai-webapp
   ```

5. **Start a local static server**:
   ```bash
   python3 -m http.server 8000
   ```

6. **Open the web app**:
   Navigate to `http://localhost:8000/` (or `http://localhost:8000/chatbot.html`) in your web browser.

---

### Windows

1. **Install Ollama**:
   Download and install from [ollama.com/download](https://ollama.com/download).

2. **Start Ollama**:
   ```powershell
   ollama serve
   ```

3. **Pull and test a model**:
   ```powershell
   ollama run mistral:7b
   ```

4. **Clone the repository**:
   ```powershell
   git clone https://github.com/asseukihuh/ai-webapp.git
   cd ai-webapp
   ```

5. **Start a local static server**:
   ```powershell
   python -m http.server 8000
   ```

6. **Open the web app**:
   Navigate to `http://localhost:8000/` (or `http://localhost:8000/chatbot.html`) in your web browser.

---

### macOS

1. **Install Ollama**:
   Download and install from [ollama.com/download](https://ollama.com/download) or install via Homebrew:
   ```bash
   brew install ollama
   ```

2. **Start Ollama**:
   ```bash
   ollama serve
   ```

3. **Pull and test a model**:
   ```bash
   ollama run mistral:7b
   ```

4. **Serve and Open**:
   ```bash
   python3 -m http.server 8000
   ```
   Navigate to `http://localhost:8000/` (or `http://localhost:8000/chatbot.html`).

---

## CommMaker / PhotoCraft

**CommMaker** (prototype) uses this repo as the **web shell** (onboarding, AI chat, crisis flows) and embeds **[PhotoCraft](https://github.com/asseukihuh/photocraft)** as the image editor (WASM / WebGPU).

### Fork workflow

1. **Fork** [storytold/photocraft](https://github.com/storytold/photocraft) on GitHub (CommMaker editor fork: [asseukihuh/photocraft](https://github.com/asseukihuh/photocraft)).
2. Add remote `upstream` → `https://github.com/storytold/photocraft.git` and merge periodically.
3. Build or download the **web static site** (`photocraft-web-<version>.zip` from your fork’s releases, or upstream until the fork publishes assets).

### Local editor embed (POC)

```bash
./scripts/fetch-photocraft-web.sh    # installs vendor/photocraft-web/ (gitignored)
python3 scripts/serve-static.py --port 8000
```

Open **http://localhost:8000/photocraft/** — an iframe loads `vendor/photocraft-web/index.html`.

**COOP / COEP:** PhotoCraft does **not** require `Cross-Origin-Opener-Policy` or `Cross-Origin-Embedder-Policy` (no `SharedArrayBuffer`). If you enable COEP on the shell for other reasons, set `Cross-Origin-Resource-Policy` on editor static files; test with `python3 scripts/serve-static.py --coop-coep`.

**Build from source** (on your fork clone):

```bash
git clone https://github.com/asseukihuh/photocraft.git
cd photocraft
rustup target add wasm32-unknown-unknown
cargo install trunk --locked
packaging/web/package.sh          # release-style zip layout under target/
# or dev: cd apps/photocraft-web && trunk serve --release
```

See [packaging/web/README.md](https://github.com/asseukihuh/photocraft/blob/main/packaging/web/README.md) on the fork for hosting, iframe embedding, and Docker.

### Pomelli-style kit import (parity goals)

CommMaker’s website onboarding aims for **[Pomelli](https://labs.google.com/pomelli)**-class kits: colors, type, logo, hero imagery, and headline copy derived from a URL.

| Capability | CommMaker MVP (this repo) | Honest gaps vs Pomelli |
|------------|---------------------------|-------------------------|
| Colors / fonts from page + CSS | Linked stylesheets, CSS variables, theme meta | No computed-style render; may miss colors only in JS bundles |
| Logo | Favicon, header `<img>`, inline header SVG | No ML “pick the wordmark”; SVGs outside header/nav ignored |
| Hero / marketing image | `og:image`, Twitter card, largest above-fold `<img>` | No full-bleed crop intelligence or stock-photo filtering |
| Headline / tagline | `og:title`, first `h1`, meta description | No multi-locale or A/B headline merging |
| Poster output | LinkedIn 1200×627 with hero layer, overlay, logo corner | Not a full generative “campaign set”; single template |
| Editor | PhotoCraft component layers (editable) | No one-click “apply kit to all formats” yet |

Kit JSON may include optional fields: `heroImageUrl`, `logoSvg`, `logoSource` (`inline-svg` | `img` | `favicon`), `faviconUrl`, `tagline`, `headline`, `accentColors[]` (older clients ignore them). Logo tiers prefer inline header/wordmark SVG, then header `<img>` / lazy `data-src`, then favicon — never `og:image` (that field is hero/marketing only).

Test URLs: see Project docs `docs/kit-scrape-test-sites.md` in the CommMaker agent store, or scrape the sites listed there directly.

### Windows (PowerShell — default)

On Windows, use **PowerShell only** for CommMaker dev setup. Git Bash is not required.

**Prerequisites**

- [Python 3.11+](https://www.python.org/downloads/) — check **Add python.exe to PATH** during setup
- [Git for Windows](https://git-scm.com/download/win) (for `git clone` / `git pull` only)
- Ollama (optional) — only if you use the legacy chat pages

**Clone and run** (example path `C:\Users\nyhar\Documents\AI-WebApp`):

```powershell
cd $HOME\Documents
git clone https://github.com/asseukihuh/AI-WebApp.git
cd AI-WebApp
git pull
.\scripts\dev-commmaker.ps1
```

Open **http://localhost:8000/home.html** → **Onboard** → **Crisis** → **Editor** (`/photocraft/`).

`dev-commmaker.ps1` always installs or refreshes `vendor/photocraft-web/` with `install-photocraft-windows.ps1` (release zip via GitHub API, with a hardcoded [storytold/photocraft v0.9.0](https://github.com/storytold/photocraft/releases/download/v0.9.0/photocraft-web-0.9.0.zip) fallback). To install web assets only:

```powershell
.\scripts\install-photocraft-windows.ps1
# optional: pre-download Windows photocraft-cli portable (~130 MB)
.\scripts\install-photocraft-windows.ps1 -IncludeCli
```

**Optional fork build (Git Bash):** if you have `scripts/install-photocraft-from-fork.sh` (e.g. from [PR #4](https://github.com/asseukihuh/AI-WebApp/pull/4)) and want a local Rust/Trunk build instead of the release zip:

```powershell
$env:COMMMAKER_INSTALL_PHOTOCRAFT_FROM_FORK = "1"
.\scripts\dev-commmaker.ps1
```

**Generate poster:** the dev server can download `photocraft-cli` on the first `POST /api/generate-poster`; allow the binary in Windows Defender if prompted. You can smoke-test the CLI with `python scripts\photocraft_cli.py --self-test`.

**Windows troubleshooting**

- **`install-photocraft-windows.ps1` / network errors:** downloads use a temp file under `%TEMP%` before unzip. Manual fallback (run from repo root in PowerShell):

  ```powershell
  $z="$env:TEMP\photocraft-web-0.9.0.zip"; Invoke-WebRequest -Uri "https://github.com/storytold/photocraft/releases/download/v0.9.0/photocraft-web-0.9.0.zip" -OutFile $z -UseBasicParsing; $e="$env:TEMP\pc-extract"; Expand-Archive $z $e -Force; Remove-Item vendor\photocraft-web -Recurse -Force -ErrorAction SilentlyContinue; Move-Item (Join-Path $e "photocraft-web-0.9.0") vendor\photocraft-web; Remove-Item $e -Recurse -Force
  ```

- **macOS/Linux `fetch-photocraft-web.sh`:** same fork-first / v0.9.0 upstream fallback; uses temp files (avoids `curl: (23)` when API JSON is piped).
- **`fatal: detected dubious ownership` / `safe.directory`:** after cloning to a folder owned by another Windows user or WSL path, tell Git the repo is trusted (use your real clone path):

  ```bash
  git config --global --add safe.directory 'C:/Users/You/Projects/AI-WebApp'
  ```

### CommMaker MVP flows

Use the dev server (required for website kit scrape API):

```bash
python3 scripts/serve-static.py --port 8000
```

On Windows, prefer `.\scripts\dev-commmaker.ps1` (same server, auto vendor install).

| Step | URL | What it does |
|------|-----|----------------|
| Home | `/home.html` | Flow overview and links |
| Onboard | `/onboard.html` | POST scrape via `/api/scrape-kit` → preview → `localStorage` `commmaker.kit` |
| Crisis | `/crisis.html` | Facts → caption draft → **creative brief** (`POST /api/creative-brief`) → **Generate poster** (`POST /api/generate-poster`) |
| Editor | `/photocraft/` | PhotoCraft iframe; opens generated `.pcraft` from `/generated/` when available (**1200×627**) |

### Personalized poster (PhotoCraft CLI)

The dev server compiles kit + crisis session into a PhotoCraft **command batch**, then runs **`photocraft-cli serve`** with `--automation-read-root` / `--automation-write-root` set to the repo so output lands in `generated/`.

Before compile, Crisis calls **`POST /api/creative-brief`**: a frontier LLM chooses on-brand headline, layout recipe, and hero/logo treatment; `poster_compiler.py` stays the deterministic renderer. If no API key is set (or the model call fails), the same endpoint returns a **rule-based fallback** brief (`source: fallback`).

#### Creative brief LLM (Phase B)

**Default model (when `COMMMAKER_LLM_MODEL` is unset):** provider-specific **frontier** IDs — not mini/nano. We default to **Claude Sonnet 4** on Anthropic (`claude-sonnet-4-20250514`) and matching IDs on other providers because Sonnet-class models balance strong marketing reasoning, reliable JSON structured output, and latency for a single brief per poster. Override with `COMMMAKER_LLM_MODEL` for Opus, o3, GPT-4.1, or OpenRouter routes.

| Variable | Purpose |
|----------|---------|
| `COMMMAKER_LLM_PROVIDER` | Optional: `openai`, `anthropic`, or `openrouter`. If unset, the first matching key wins: Anthropic → OpenRouter → OpenAI. |
| `ANTHROPIC_API_KEY` | Direct Anthropic Messages API |
| `OPENAI_API_KEY` | OpenAI Chat Completions (also used when `OPENAI_API_BASE` points at a compatible proxy) |
| `OPENROUTER_API_KEY` | One key for many models via [OpenRouter](https://openrouter.ai/) |
| `COMMMAKER_LLM_MODEL` | Override model id (see table below) |
| `OPENROUTER_HTTP_REFERER` | Optional OpenRouter attribution URL |
| `OPENROUTER_APP_TITLE` | Optional OpenRouter app name (default `CommMaker`) |

#### Ideogram 4 hero (optional)

When the creative brief uses `heroStrategy: ideogram_generate`, CommMaker generates background (and optional accent) raster layers via Ideogram before poster compile. See [`docs/ideogram-layers.md`](docs/ideogram-layers.md).

| Variable | Purpose |
|----------|---------|
| `IDEOGRAM_API_KEY` | [Ideogram API](https://developer.ideogram.ai/) key (`Api-Key` header) |
| `COMMMAKER_IDEOGRAM_RENDERING` | Optional: `TURBO`, `DEFAULT`, or `QUALITY` (`rendering_speed` on generate) |

| Model | Use case | Example env |
|-------|----------|-------------|
| `claude-sonnet-4-20250514` | **Default (Anthropic)** — best balance of quality, speed, structured briefs | `COMMMAKER_LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY=…` |
| `claude-opus-4-20250514` | Maximum copy/layout reasoning when latency cost is acceptable | `COMMMAKER_LLM_MODEL=claude-opus-4-20250514` |
| `gpt-4.1` | **Default (OpenAI)** — strong general marketing reasoning | `OPENAI_API_KEY=…` |
| `o3` | Harder tradeoffs (legal tone, crowded layouts) | `COMMMAKER_LLM_MODEL=o3` |
| `anthropic/claude-sonnet-4` | **Default (OpenRouter)** — Sonnet via single OpenRouter key | `OPENROUTER_API_KEY=…` |
| `google/gemini-2.5-pro-preview` | Alternative frontier via OpenRouter | `COMMMAKER_LLM_MODEL=google/gemini-2.5-pro-preview` |

```bash
export ANTHROPIC_API_KEY=sk-ant-…
# optional: export COMMMAKER_LLM_MODEL=claude-opus-4-20250514
python3 scripts/serve-static.py --port 8000
python3 scripts/test_creative_brief.py
```

Hero images use **cover** placement (`fit: false` + scale to fill **1200×627**); verify with `python3 scripts/test_poster_cover.py`. Typography uses separate **headline** and **body** kit fonts when available; Google Fonts links from scrape are cached under `generated/fonts/` and reported as **`fontsResolved`** on the generate-poster response (`python3 scripts/test_poster_fonts.py`). LinkedIn layout tokens: logo **~280px** wide (220–320) with **56px** margin and knockback sized to the mark; crisis headline **52–56px**, kit tagline **24px** (footer site name omitted when a logo is placed).

```bash
python3 scripts/serve-static.py --port 8000
curl -s -X POST localhost:8000/api/generate-poster \
  -H 'Content-Type: application/json' \
  -d '{"kit":{"siteName":"Acme","colors":["#1a365d"]},"session":{"brief":{"facts":"Update."},"suggestedHeadline":"Update"}}'
```

**`photocraft-cli` install:** On the first **`POST /api/generate-poster`** while `python3 scripts/serve-static.py` is running, CommMaker downloads the matching [storytold/photocraft](https://github.com/storytold/photocraft) **`v0.9.0`** asset into `vendor/photocraft-cli/` (gitignored):

| OS | Release asset |
|----|----------------|
| Linux | `photocraft-0.9.0-linux-<arch>.tar.gz` → `…/bin/photocraft-cli` |
| macOS | `photocraft-cli-0.9.0-macos-universal.zip` → `photocraft-cli-0.9.0-macos-universal/photocraft-cli` |
| Windows | `photocraft-0.9.0-windows-*-portable.zip` → `photocraft-cli.exe` |

You can also put `photocraft-cli` on `PATH` or extract the archive manually.

**macOS troubleshooting:** If Crisis shows a red alert after **Generate poster**, open the browser Network tab for `/api/generate-poster` and check **`cliError`** / **`userMessage`**. First run may take a minute while ~130 MB downloads; corporate proxies must allow `github.com` release downloads. Gatekeeper: if macOS blocks the binary, run `xattr -cr vendor/photocraft-cli` once, or approve in **System Settings → Privacy & Security**. Smoke-test the CLI:

```bash
python3 scripts/photocraft_cli.py --self-test
```

If the CLI is missing or fails, the API returns **`commandBatch`**, **`cliError`**, and **`userMessage`** (HTTP 200) so the Crisis page can show the error instead of opening the editor.

Optional LLM caption hook in the browser console or a future script:

```js
window.commmakerGenerateCaptionWithLLM = async (brief) => { /* call Ollama */ };
```

---

## 📁 Project Architecture

```
ai-webapp/
├── index.html         # Entry point (redirects to CommMaker home)
├── home.html          # CommMaker hub
├── onboard.html       # Communication Kit scrape
├── crisis.html        # Crisis fast path wizard
├── chatbot.html       # Ollama chat interface
├── photocraft/        # CommMaker PhotoCraft embed (POC)
├── vendor/photocraft-web/  # Downloaded WASM site (gitignored; see README there)
├── generated/         # Headless poster output (.pcraft); gitignored except .gitkeep
├── scripts/           # fetch-photocraft-web.sh, serve-static.py, poster_compiler.py
├── imageGen.html      # Experimental generation web interface
├── src/
│   ├── css/
│   │   ├── chatbot.css    # Styles for chat interface
│   │   └── imageGen.css   # Styles for image generation interface
│   └── js/
│       ├── chatbot.js     # Chat client logic, Ollama API, history management
│       └── imageGen.js    # Logic for experimental generation interface
├── docs/
│   └── notes-test.txt # Reference curl commands and test notes for Ollama endpoints
├── AGENTS.md          # AI agent guidelines and coding standards
├── NOTES.md           # Project updates, changelog, and roadmap
├── README.md          # Project documentation and setup instructions
└── LICENSE            # License information
```

---

## 📄 License

This project is licensed under the Apache-2.0 License. See the [LICENSE](LICENSE) file for details.
