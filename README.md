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

## 📁 Project Architecture

```
ai-webapp/
├── index.html         # Entry point (auto-redirects to chatbot)
├── chatbot.html       # Main chat web interface
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
├── README.md          # Project documentation and setup instructions
└── LICENSE            # License information
```

---

## 📄 License

This project is licensed under the Apache-2.0 License. See the [LICENSE](LICENSE) file for details.
