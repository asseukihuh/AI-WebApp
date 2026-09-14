const OLLAMA_GENERATE_URL = "http://localhost:11434/api/generate";

const modelSelect = document.getElementById("model");
const sizeSelect = document.getElementById("size");
const promptInput = document.getElementById("prompt-input");
const promptForm = document.getElementById("prompt-form");
const generateBtn = document.getElementById("generate-btn");
const imageContainer = document.getElementById("image-container");
const imagePlaceholder = document.getElementById("image-placeholder");
const statusMessage = document.getElementById("status-message");

function setStatus(text, isError = false) {
    if (!statusMessage) return;
    statusMessage.textContent = text;
    statusMessage.className = `status-message ${isError ? "error" : "info"}`;
}

function updateContainerSize() {
    if (!sizeSelect || !imageContainer) return;
    const selectedSize = sizeSelect.value;
    imageContainer.style.maxWidth = selectedSize;
}

async function handleGenerate() {
    if (!promptInput || !modelSelect) return;

    const promptText = promptInput.value.trim();
    if (!promptText) return;

    const selectedModel = modelSelect.value;

    promptInput.disabled = true;
    if (generateBtn) generateBtn.disabled = true;
    setStatus(`Sending request to ${selectedModel}...`);

    try {
        const response = await fetch(OLLAMA_GENERATE_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                model: selectedModel,
                prompt: promptText,
                stream: false
            })
        });

        if (!response.ok) {
            throw new Error(`Server returned status: ${response.status}`);
        }

        const data = await response.json();
        const responseText = data.response || "No response received.";

        if (imagePlaceholder) {
            imagePlaceholder.textContent = responseText;
        }
        setStatus("Completed.");
    } catch (error) {
        console.error("Error generating response:", error);
        setStatus("Error: Could not connect to Ollama. Ensure the server is running (`ollama serve`).", true);
    } finally {
        promptInput.disabled = false;
        if (generateBtn) generateBtn.disabled = false;
        promptInput.focus();
    }
}

if (promptForm) {
    promptForm.addEventListener("submit", (event) => {
        event.preventDefault();
        handleGenerate();
    });
}

if (promptInput) {
    promptInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            handleGenerate();
        }
    });
}

if (sizeSelect) {
    sizeSelect.addEventListener("change", updateContainerSize);
    updateContainerSize();
}
