"use strict";

import {
    escapeHtml,
    mountCommMakerNav,
    saveKit,
    KIT_STORAGE_KEY,
} from "./commmaker-common.js";

const form = document.getElementById("scrape-form");
const urlInput = document.getElementById("site-url");
const submitBtn = document.getElementById("scrape-submit");
const statusEl = document.getElementById("scrape-status");
const previewEl = document.getElementById("kit-preview");
const saveBtn = document.getElementById("save-kit-btn");
const continueBtn = document.getElementById("continue-crisis-btn");

let pendingKit = null;

function setStatus(message, isError = false) {
    if (!statusEl) {
        return;
    }
    statusEl.textContent = message;
    statusEl.classList.toggle("is-error", isError);
}

function renderPreview(kit) {
    if (!previewEl) {
        return;
    }
    const colors =
        kit.colors?.length
            ? kit.colors
                  .map(
                      (c) =>
                          `<span class="kit-swatch" style="background:${escapeHtml(c)}" title="${escapeHtml(c)}"></span>`
                  )
                  .join("")
            : '<span class="muted">None detected</span>';

    const logoBlock = kit.logoUrl
        ? `<img class="kit-logo" src="${escapeHtml(kit.logoUrl)}" alt="Logo preview" referrerpolicy="no-referrer" />`
        : '<p class="muted">No logo URL found</p>';

    previewEl.innerHTML = `
        <h2>Kit preview</h2>
        <dl class="kit-dl">
            <dt>Site name</dt><dd>${escapeHtml(kit.siteName)}</dd>
            <dt>Source</dt><dd><a href="${escapeHtml(kit.sourceUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(kit.sourceUrl)}</a></dd>
            <dt>Logo</dt><dd>${logoBlock}</dd>
            <dt>Colors</dt><dd class="kit-colors">${colors}</dd>
            <dt>Fonts</dt><dd>${escapeHtml((kit.fonts || []).join(", ") || "—")}</dd>
            <dt>Scraped</dt><dd>${escapeHtml(kit.scrapedAt || "")}</dd>
        </dl>`;
    previewEl.hidden = false;
    if (saveBtn) {
        saveBtn.disabled = false;
    }
    if (continueBtn) {
        continueBtn.disabled = false;
    }
}

async function scrapeUrl(url) {
    const res = await fetch("/api/scrape-kit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
        throw new Error(data.error || `Scrape failed (${res.status})`);
    }
    return data.kit;
}

form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const url = urlInput?.value?.trim();
    if (!url) {
        setStatus("Enter a website URL.", true);
        return;
    }
    submitBtn.disabled = true;
    setStatus("Fetching and analyzing site…");
    try {
        pendingKit = await scrapeUrl(url);
        renderPreview(pendingKit);
        setStatus("Preview ready. Save to continue the flow.");
    } catch (err) {
        setStatus(err.message || "Scrape failed.", true);
        previewEl.hidden = true;
        pendingKit = null;
        if (saveBtn) {
            saveBtn.disabled = true;
        }
        if (continueBtn) {
            continueBtn.disabled = true;
        }
    } finally {
        submitBtn.disabled = false;
    }
});

saveBtn?.addEventListener("click", () => {
    if (!pendingKit) {
        return;
    }
    saveKit(pendingKit);
    setStatus(`Saved to localStorage (${KIT_STORAGE_KEY}).`);
});

continueBtn?.addEventListener("click", () => {
    if (pendingKit) {
        saveKit(pendingKit);
    }
    window.location.href = "crisis.html";
});

document.addEventListener("DOMContentLoaded", () => {
    mountCommMakerNav(document.getElementById("commmaker-nav"), "onboard.html");
});
