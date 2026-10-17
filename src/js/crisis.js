"use strict";

import {
    mountCommMakerNav,
    loadKit,
    loadSession,
    saveSession,
    renderKitSummary,
} from "./commmaker-common.js";

const SENSATIONAL = /\b(shocking|outrageous|unbelievable|bombshell|scandal|panic|terrifying)\b/gi;

const form = document.getElementById("crisis-form");
const kitBanner = document.getElementById("kit-banner");
const captionPreview = document.getElementById("caption-preview");
const generateBtn = document.getElementById("generate-btn");
const openEditorBtn = document.getElementById("open-editor-btn");
const generatePosterBtn = document.getElementById("generate-poster-btn");
const posterStatus = document.getElementById("poster-status");

/**
 * Optional LLM hook — replace or wrap to call Ollama / remote API.
 * @param {object} brief
 * @returns {Promise<string>}
 */
export async function generateCaptionWithLLM(brief) {
    if (typeof window.commmakerGenerateCaptionWithLLM === "function") {
        return window.commmakerGenerateCaptionWithLLM(brief);
    }
    return generateCaptionFromTemplate(brief);
}

export function generateCaptionFromTemplate(brief) {
    const facts = sanitizeFacts(brief.facts);
    const audience = brief.audienceNeed?.trim();
    const tone = brief.tone || "factual";
    const legal = Boolean(brief.legalReviewNeeded);

    const toneLead = {
        calm: "We are addressing the situation with care and transparency.",
        factual: "Here are the facts we can confirm at this time.",
        empathetic: "We understand this affects our community, and we are here to help.",
    }[tone] || "Here is what we know.";

    const headline = deriveHeadline(facts);
    const body = facts.split(/\n+/).filter(Boolean).slice(0, 4).join(" ");
    const audienceLine = audience
        ? `What you need to know: ${sanitizeFacts(audience)}`
        : "";
    const nextStep =
        "We will share updates as verified information becomes available. For questions, contact your usual company representative.";

    let caption = `${headline}\n\n${toneLead}\n\n${body}`;
    if (audienceLine) {
        caption += `\n\n${audienceLine}`;
    }
    caption += `\n\n${nextStep}`;
    if (legal) {
        caption += "\n\n[Pending legal review before publishing.]";
    }

    return stripSensational(caption);
}

function sanitizeFacts(text) {
    return stripSensational(String(text || "").trim());
}

function stripSensational(text) {
    return text.replace(SENSATIONAL, "").replace(/\s{2,}/g, " ").trim();
}

function deriveHeadline(facts) {
    const firstLine = facts.split(/\n/)[0]?.trim() || "Important update";
    const short = firstLine.length > 90 ? firstLine.slice(0, 87) + "…" : firstLine;
    return short;
}

function readForm() {
    const facts = document.getElementById("facts")?.value?.trim() || "";
    const audienceNeed = document.getElementById("audience-need")?.value?.trim() || "";
    const tone =
        document.querySelector('input[name="tone"]:checked')?.value || "factual";
    const legalReviewNeeded = Boolean(
        document.getElementById("legal-review")?.checked
    );
    return { facts, audienceNeed, tone, legalReviewNeeded };
}

function setPosterStatus(message, { error = false, success = false } = {}) {
    if (!posterStatus) {
        return;
    }
    posterStatus.hidden = !message;
    posterStatus.textContent = message;
    posterStatus.classList.toggle("is-error", Boolean(error));
    posterStatus.classList.toggle("is-success", Boolean(success));
    posterStatus.setAttribute("role", message ? "alert" : "status");
}

function triggerPosterDownload(docPath) {
    if (!docPath) {
        return;
    }
    const link = document.createElement("a");
    link.href = docPath;
    link.download = docPath.split("/").pop() || "commmaker-poster.pcraft";
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    link.remove();
}

form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = readForm();
    if (!input.facts) {
        captionPreview.textContent = "Confirmed facts are required.";
        captionPreview.classList.add("is-error");
        return;
    }

    generateBtn.disabled = true;
    const headline = deriveHeadline(input.facts);
    const brief = {
        ...input,
        headline,
        createdAt: new Date().toISOString(),
        format: "linkedin-post",
        canvas: { width: 1200, height: 627 },
    };

    try {
        const captionDraft = await generateCaptionWithLLM(brief);
        const kit = loadKit();
        const session = {
            brief,
            captionDraft,
            kitSnapshot: kit,
            suggestedHeadline: headline,
        };
        saveSession(session);

        captionPreview.classList.remove("is-error");
        captionPreview.textContent = captionDraft;
        openEditorBtn.disabled = false;
        generatePosterBtn.disabled = false;
        setPosterStatus("", {});
    } finally {
        generateBtn.disabled = false;
    }
});

async function generatePosterInPhotoCraft() {
    const session = loadSession();
    const kit = loadKit();
    if (!session?.brief) {
        setPosterStatus("Generate a caption draft first.", { error: true });
        return;
    }

    generatePosterBtn.disabled = true;
    openEditorBtn.disabled = true;
    setPosterStatus("Compiling poster and running PhotoCraft CLI…", {});

    try {
        const res = await fetch("/api/generate-poster", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ kit, session }),
        });
        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.error || data.userMessage || `HTTP ${res.status}`);
        }

        const posterOk = Boolean(data.ok);
        const updated = {
            ...session,
            poster: {
                ok: posterOk,
                documentPath: data.documentPath,
                openUrl: data.openUrl,
                cliAvailable: data.cliAvailable,
                generatedAt: new Date().toISOString(),
                cliError: data.cliError || null,
                userMessage: data.userMessage || null,
            },
        };
        saveSession(updated);

        if (!posterOk) {
            const detail =
                data.userMessage ||
                data.cliError ||
                "Poster generation failed. Fix the issue below and try again.";
            setPosterStatus(detail, { error: true });
            generatePosterBtn.disabled = false;
            openEditorBtn.disabled = false;
            return;
        }

        const fonts = data.fontsResolved;
        const fontNote =
            fonts?.headline && fonts?.body
                ? ` Fonts: ${fonts.headline} / ${fonts.body}.`
                : "";
        setPosterStatus(
            (data.userMessage || "Poster saved. Downloading and opening PhotoCraft…") +
                fontNote,
            { success: true }
        );

        const docParam = data.openUrl || data.documentPath;
        if (docParam) {
            triggerPosterDownload(docParam);
        }

        const target = docParam
            ? `photocraft/?doc=${encodeURIComponent(docParam)}`
            : "photocraft/";
        window.setTimeout(() => {
            window.location.href = target;
        }, 600);
    } catch (err) {
        setPosterStatus(err.message || String(err), { error: true });
        generatePosterBtn.disabled = false;
        openEditorBtn.disabled = false;
    }
}

generatePosterBtn?.addEventListener("click", () => {
    generatePosterInPhotoCraft();
});

openEditorBtn?.addEventListener("click", () => {
    window.location.href = "photocraft/";
});

document.addEventListener("DOMContentLoaded", () => {
    mountCommMakerNav(document.getElementById("commmaker-nav"), "crisis.html");
    const kit = loadKit();
    renderKitSummary(kitBanner, kit, null);
    if (!kit) {
        kitBanner?.insertAdjacentHTML(
            "beforeend",
            '<p class="muted">No kit in localStorage yet — <a href="onboard.html">import from a website</a>.</p>'
        );
    }
});
