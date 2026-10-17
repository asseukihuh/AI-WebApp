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

---

## 📁 Project Architecture

```
ai-webapp/
├── index.html         # Entry point (auto-redirects to chatbot)
├── chatbot.html       # Main chat web interface
├── photocraft/        # CommMaker PhotoCraft embed (POC)
├── vendor/photocraft-web/  # Downloaded WASM site (gitignored; see README there)
├── scripts/           # fetch-photocraft-web.sh, serve-static.py
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
