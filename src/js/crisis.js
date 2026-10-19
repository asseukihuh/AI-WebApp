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
const creativeBriefPanel = document.getElementById("creative-brief-panel");
const briefMeta = document.getElementById("brief-meta");
const briefHeadlinePreview = document.getElementById("brief-headline-preview");
const briefHeroStrategy = document.getElementById("brief-hero-strategy");
const briefImagePrompts = document.getElementById("brief-image-prompts");
const briefBackgroundPrompt = document.getElementById("brief-background-prompt");
const briefAccentLabel = document.getElementById("brief-accent-label");
const briefAccentPrompt = document.getElementById("brief-accent-prompt");
const briefRationale = document.getElementById("brief-rationale");

/**
 * Optional LLM hook — replace or wrap to call a remote model.
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

function headlineFromPosterPrompt(prompt) {
    const match = String(prompt || "").match(/\bheadline\s+([^.\n]+)/i);
    if (!match) {
        return "";
    }
    const line = match[1].trim();
    return line.length > 90 ? `${line.slice(0, 87)}…` : line;
}

function readForm() {
    const posterPrompt = document.getElementById("poster-prompt")?.value?.trim() || "";
    const facts = document.getElementById("facts")?.value?.trim() || "";
    const audienceNeed = document.getElementById("audience-need")?.value?.trim() || "";
    const tone =
        document.querySelector('input[name="tone"]:checked')?.value || "factual";
    const legalReviewNeeded = Boolean(
        document.getElementById("legal-review")?.checked
    );
    return { posterPrompt, facts, audienceNeed, tone, legalReviewNeeded };
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

function formatHeroStrategyLabel(strategy, brief) {
    const labels = {
        use_kit_photo: "Hero: scraped kit marketing photo",
        ideogram_generate: "Hero: AI-generated (Ideogram 4)",
        gradient_from_palette: "Hero: brand gradient from palette",
        solid: "Hero: solid brand color",
        none: "Hero: none (type-focused)",
    };
    let label = labels[strategy] || `Hero strategy: ${strategy || "—"}`;
    if (strategy === "ideogram_generate" && brief?.heroImagePrompt) {
        const snippet =
            brief.heroImagePrompt.length > 100
                ? `${brief.heroImagePrompt.slice(0, 97)}…`
                : brief.heroImagePrompt;
        label += ` — “${snippet}”`;
    }
    return label;
}

function renderCreativeBriefPanel(apiResult) {
    const brief = apiResult?.brief;
    if (!brief || !creativeBriefPanel) {
        return;
    }
    creativeBriefPanel.hidden = false;
    const source = apiResult.source || "fallback";
    const parts = [`Source: ${source}`];
    if (source === "llm" && apiResult.model) {
        parts.push(`Model: ${apiResult.model}`);
        if (apiResult.provider) {
            parts.push(`(${apiResult.provider})`);
        }
    } else if (source === "fallback") {
        parts.push("(rule-based brief)");
        const reason = apiResult.fallbackReason;
        const detail = apiResult.errorDetail;
        if (reason) {
            parts.push(`Reason: ${reason}`);
        }
        if (detail) {
            parts.push(`Detail: ${detail}`);
        }
        if (!reason && !detail) {
            parts.push("(no API key or LLM error)");
        }
    }
    if (briefMeta) {
        briefMeta.textContent = parts.join(" ");
        briefMeta.classList.toggle("is-fallback", source === "fallback");
    }
    if (briefHeadlinePreview) {
        const sub = brief.subhead ? ` — ${brief.subhead}` : "";
        briefHeadlinePreview.textContent = `${brief.headline || ""}${sub}`;
    }
    if (briefHeroStrategy) {
        const layout = brief.layoutRecipe ? ` · Layout: ${brief.layoutRecipe}` : "";
        const layers =
            brief.heroStrategy === "ideogram_generate" && brief.ideogramLayers
                ? ` · Layers: ${brief.ideogramLayers}`
                : "";
        briefHeroStrategy.textContent =
            formatHeroStrategyLabel(brief.heroStrategy, brief) + layout + layers;
    }
    if (briefImagePrompts && briefBackgroundPrompt) {
        const showIdeogram =
            brief.heroStrategy === "ideogram_generate" && brief.heroImagePrompt;
        briefImagePrompts.hidden = !showIdeogram;
        if (showIdeogram) {
            briefBackgroundPrompt.textContent = brief.heroImagePrompt;
            const accentMode =
                brief.ideogramLayers === "background-plus-accent" && brief.accentImagePrompt;
            if (briefAccentLabel) {
                briefAccentLabel.hidden = !accentMode;
            }
            if (briefAccentPrompt) {
                briefAccentPrompt.hidden = !accentMode;
                briefAccentPrompt.textContent = accentMode ? brief.accentImagePrompt : "";
            }
        }
    }
    if (briefRationale) {
        briefRationale.textContent = brief.rationale || "";
    }
}

async function fetchCreativeBrief(kit, session) {
    const formBrief = session.brief || {};
    const res = await fetch("/api/creative-brief", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            kit,
            crisisMessage: formBrief.headline || session.suggestedHeadline || "",
            crisisFacts: formBrief.facts || "",
            posterPrompt: formBrief.posterPrompt || "",
            tone: formBrief.tone,
            format: "linkedin-1200x627",
        }),
    });
    const data = await res.json();
    if (!res.ok) {
        throw new Error(data.error || `Creative brief HTTP ${res.status}`);
    }
    return data;
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
    if (!input.posterPrompt) {
        captionPreview.textContent = "A poster prompt is required.";
        captionPreview.classList.add("is-error");
        return;
    }
    if (!input.facts) {
        captionPreview.textContent = "Confirmed facts are required.";
        captionPreview.classList.add("is-error");
        return;
    }

    generateBtn.disabled = true;
    const headline = headlineFromPosterPrompt(input.posterPrompt) || deriveHeadline(input.facts);
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
    setPosterStatus("Building creative brief…", {});

    try {
        const briefResult = await fetchCreativeBrief(kit, session);
        renderCreativeBriefPanel(briefResult);
        const creativeBrief = briefResult.brief;

        setPosterStatus("Compiling poster and running PhotoCraft CLI…", {});

        const res = await fetch("/api/generate-poster", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ kit, session, creativeBrief }),
        });
        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.error || data.userMessage || `HTTP ${res.status}`);
        }

        const posterOk = Boolean(data.ok);
        const updated = {
            ...session,
            creativeBrief: {
                ...briefResult,
                fetchedAt: new Date().toISOString(),
            },
            poster: {
                ok: posterOk,
                documentPath: data.documentPath,
                openUrl: data.openUrl,
                previewUrl: data.previewUrl || null,
                layoutTemplate: data.layoutTemplate || null,
                designScore: data.designAudit?.score ?? null,
                ideogramUsed: Boolean(data.ideogramUsed),
                ideogramMs: Number.isFinite(data.ideogramMs) ? data.ideogramMs : 0,
                promptSnippet: data.promptSnippet || "",
                ideogramJudge: data.ideogramJudge || null,
                ideogramError: data.ideogramError || data.ideogramFallback || "",
                statusLine: data.statusLine || "",
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
            const skipNote = data.statusLine ? ` ${data.statusLine}` : "";
            setPosterStatus(detail + skipNote, { error: true });
            generatePosterBtn.disabled = false;
            openEditorBtn.disabled = false;
            return;
        }

        const fonts = data.fontsResolved;
        const fontNote =
            fonts?.headline && fonts?.body
                ? ` Fonts: ${fonts.headline} / ${fonts.body}.`
                : "";
        const strategyNote =
            data.heroStrategy && data.heroStrategy !== "ideogram_generate"
                ? ` Brief hero: ${data.heroStrategy}.`
                : "";
        const frameNote = data.layoutTemplate ? ` Frame: ${data.layoutTemplate}.` : "";
        const snippetNote = data.promptSnippet ? ` Prompt: ${data.promptSnippet}` : "";
        const judge = data.ideogramJudge;
        const attemptNote = judge && judge.attempts
            ? ` ${judge.attempts} attempt${judge.attempts === 1 ? "" : "s"}.`
            : "";
        const judgeNote = judge
            ? ` Judge: ${judge.passed === true ? "pass" : judge.passed === false ? "fail" : "skipped"}. ${judge.reason || ""}${attemptNote}`
            : "";
        const errorNote = data.ideogramError || data.ideogramFallback
            ? ` ${data.ideogramError || data.ideogramFallback}`
            : ""
        const msNote = Number.isFinite(data.ideogramMs) ? ` ${data.ideogramMs} ms.` : ""
        const heroNote = data.statusLine
            ? ` ${data.statusLine}`
            : data.ideogramUsed || data.heroSource === "ideogram-4"
                ? ` Ideogram: yes.${msNote}${frameNote}${snippetNote}${judgeNote}`
                : ` Ideogram: no.${msNote}${frameNote}${errorNote}${strategyNote}`
        const pictureSkipped = !data.ideogramUsed && Boolean(data.ideogramError || data.ideogramFallback);
        const judgeFailed = Boolean(judge && judge.passed === false);
        setPosterStatus(
            (data.userMessage || "Poster saved. Downloading and opening PhotoCraft…") +
                heroNote +
                fontNote,
            { success: !pictureSkipped && !judgeFailed, error: pictureSkipped || judgeFailed }
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
