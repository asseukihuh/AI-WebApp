const OLLAMA_API_URL = "http://localhost:11434/api/chat";
const MAX_HISTORY_LENGTH = 10;

let chatHistory = [];

const messagesInner = document.getElementById("messages-inner");
const chatMessagesContainer = document.getElementById("chat-messages");
const bottomAnchor = document.getElementById("bottom-anchor");
const userInput = document.getElementById("user-input");
const sendBtn = document.getElementById("send-btn");
const modelSelect = document.getElementById("model");
const goBottomBtn = document.getElementById("go-bottom-btn");
const messageForm = document.getElementById("message-form");

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

function scrollToBottom() {
    if (bottomAnchor) {
        bottomAnchor.scrollIntoView({ behavior: "smooth" });
    }
}

function appendMessage(sender, text, isError = false) {
    if (!messagesInner) return;

    const messageWrapper = document.createElement("div");
    messageWrapper.className = `message-row ${sender.toLowerCase()}-row`;

    const label = document.createElement("span");
    label.className = `message-sender ${isError ? "error-sender" : ""}`;
    label.textContent = `${sender}: `;

    const content = document.createElement("span");
    content.className = `message-content ${isError ? "error-content" : ""}`;
    content.innerHTML = escapeHtml(text).replace(/\n/g, "<br>");

    messageWrapper.appendChild(label);
    messageWrapper.appendChild(content);
    messagesInner.appendChild(messageWrapper);

    scrollToBottom();
}

async function sendMessage() {
    if (!userInput || !modelSelect) return;

    const promptText = userInput.value.trim();
    if (!promptText) return;

    const selectedModel = modelSelect.value;

    appendMessage("You", promptText);
    userInput.value = "";
    userInput.disabled = true;
    if (sendBtn) sendBtn.disabled = true;

    chatHistory.push({ role: "user", content: promptText });

    if (chatHistory.length > MAX_HISTORY_LENGTH) {
        chatHistory = chatHistory.slice(-MAX_HISTORY_LENGTH);
    }

    try {
        const response = await fetch(OLLAMA_API_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                model: selectedModel,
                messages: chatHistory,
                stream: false
            })
        });

        if (!response.ok) {
            throw new Error(`Server responded with status: ${response.status}`);
        }

        const data = await response.json();
        const aiResponse = data.message?.content || "No response received from AI.";

        chatHistory.push({ role: "assistant", content: aiResponse });
        appendMessage("AI", aiResponse);
    } catch (error) {
        console.error("Error communicating with Ollama:", error);
        appendMessage("AI", "Error: Could not connect to Ollama. Make sure Ollama is running (`ollama serve`).", true);
    } finally {
        userInput.disabled = false;
        if (sendBtn) sendBtn.disabled = false;
        userInput.focus();
    }
}

if (messageForm) {
    messageForm.addEventListener("submit", (event) => {
        event.preventDefault();
        sendMessage();
    });
}

if (userInput) {
    userInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            sendMessage();
        }
    });
}

if (goBottomBtn) {
    goBottomBtn.addEventListener("click", () => {
        scrollToBottom();
    });
}
