# AGENTS.md

Guidelines and operational context for AI agents working in this repository.

---

## 1. Project Overview

`ai-webapp` is a dependency-free, frontend-focused web application designed to connect to locally running Large Language Models (LLMs) via the **Ollama REST API**.

- **Tech Stack**: Vanilla HTML5, CSS3, ES6+ JavaScript.
- **Local Backend**: Ollama server (`http://localhost:11434`).
- **Dev Server**: Any static HTTP server (e.g. `python3 -m http.server 8000`).

---

## 2. Directory & File Organization

Keep code structured according to the established project layout:

```
ai-webapp/
├── index.html              # Repository entry point (redirects to chatbot.html)
├── chatbot.html            # Main chat application page
├── imageGen.html           # Experimental image/prompt generation page
├── src/
│   ├── css/
│   │   ├── chatbot.css     # Styling for chat interface
│   │   └── imageGen.css    # Styling for generation interface
│   └── js/
│       ├── chatbot.js      # Chat logic, Ollama API integration, history management
│       └── imageGen.js     # Experimental generation script logic
├── docs/
│   └── notes-test.txt      # API endpoints and curl testing commands
├── AGENTS.md               # Agent guidelines and project standards
├── NOTES.md                # Project update tracking and changelog
├── README.md               # User-facing documentation and installation guide
└── LICENSE                 # Apache-2.0 License
```

---

## 3. Coding Guidelines & Best Practices

### HTML
- Use modern HTML5 standards (`<!DOCTYPE html>`, UTF-8 charset, responsive `<meta name="viewport">`).
- Keep elements semantic (`<header>`, `<main>`, `<section>`, `<form>`).
- Avoid inline JS event handlers (e.g., avoid `onclick="..."`).
- Scripts should be linked using the `defer` attribute.

### JavaScript
- Use strict and modern ES6+ standards (`const`, `let`, arrow functions, async/await).
- **Security**: Never inject raw, unescaped user or model input directly into `innerHTML`. Always use helper functions (like `escapeHtml`) or safe DOM manipulation (`textContent`, `createElement`).
- **Ollama API Integration**:
  - Chat completions endpoint: `POST http://localhost:11434/api/chat`
  - Generation endpoint: `POST http://localhost:11434/api/generate`
  - Use `stream: false` unless a streaming UI handler is explicitly implemented.
- **UI States**: Always disable inputs/buttons while waiting for responses to prevent race conditions and duplicate requests.

### CSS
- Maintain separation between markup and styling: all styles reside in `src/css/`.
- Use descriptive, semantic class names rather than numbered element IDs (e.g., `.chat-messages` instead of `#div2`).
- Responsive layout using Flexbox/Grid.

---

## 4. Testing & Verification

1. **Syntax Checking**:
   Validate JavaScript changes with Node before committing:
   ```bash
   node -c src/js/chatbot.js && node -c src/js/imageGen.js
   ```

2. **Local Static Server**:
   Start a local server to test the interface:
   ```bash
   python3 -m http.server 8000
   ```
   Verify `http://localhost:8000/` properly redirects and functions.

3. **Ollama Endpoint Testing**:
   Refer to `docs/notes-test.txt` for reference curl calls to test Ollama connectivity.
