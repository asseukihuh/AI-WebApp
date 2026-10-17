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

function sanitizeInlineSvg(svgText) {
    if (!svgText || typeof svgText !== "string") {
        return null;
    }
    const doc = new DOMParser().parseFromString(svgText, "image/svg+xml");
    const svg = doc.querySelector("svg");
    if (!svg) {
        return null;
    }
    svg.querySelectorAll("script, foreignObject, iframe, object, embed").forEach((node) => {
        node.remove();
    });
    for (const el of svg.querySelectorAll("*")) {
        for (const attr of [...el.attributes]) {
            if (attr.name.toLowerCase().startsWith("on")) {
                el.removeAttribute(attr.name);
            }
        }
    }
    return svg;
}

function svgDataUri(svgText) {
    return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgText)}`;
}

function buildLogoMarkup(kit) {
    const inlineSvg = kit.logoSvg ? sanitizeInlineSvg(kit.logoSvg) : null;
    if (inlineSvg) {
        const wrap = document.createElement("div");
        wrap.className = "kit-logo kit-logo-inline";
        wrap.appendChild(inlineSvg);
        return { html: wrap.outerHTML, mode: "inline-svg" };
    }

    const rasterUrl = kit.logoUrl || kit.faviconUrl || null;
    if (!rasterUrl) {
        if (kit.logoSvg) {
            return {
                html: '<p class="muted">No logo (inline SVG blocked)</p>',
                mode: "blocked",
            };
        }
        return { html: '<p class="muted">No logo detected</p>', mode: "none" };
    }

    const fallbackSvg = kit.logoSvg ? svgDataUri(kit.logoSvg) : null;
    const fallbackFavicon = kit.faviconUrl && kit.faviconUrl !== rasterUrl
        ? kit.faviconUrl
        : null;
    const dataFallback = fallbackSvg || fallbackFavicon || "";
    const img = `<img class="kit-logo kit-logo-raster" src="${escapeHtml(rasterUrl)}" alt="Logo preview" referrerpolicy="no-referrer" decoding="async"${
        dataFallback ? ` data-fallback="${escapeHtml(dataFallback)}"` : ""
    } />`;
    return { html: img, mode: "raster", fallback: dataFallback || null };
}

function kitHasLogo(kit) {
    if (kit.logoSvg && sanitizeInlineSvg(kit.logoSvg)) {
        return true;
    }
    return Boolean(kit.logoUrl || kit.faviconUrl);
}

function kitHasFonts(kit) {
    return Boolean(
        (kit.fonts && kit.fonts.length) ||
            (kit.googleFonts && kit.googleFonts.length)
    );
}

function formatFontsRow(kit) {
    const names = [];
    for (const name of kit.fonts || []) {
        if (name && !names.includes(name)) {
            names.push(name);
        }
    }
    for (const entry of kit.googleFonts || []) {
        const family = entry?.family;
        if (family && !names.includes(family)) {
            names.push(family);
        }
    }
    if (names.length) {
        return names.join(", ");
    }
    if (kit.headline || kit.tagline || kit.siteName) {
        return "system-ui, sans-serif (inferred)";
    }
    return "—";
}

function completenessChips(kit) {
    const logoOk = kitHasLogo(kit);
    const fontsOk = kitHasFonts(kit);
    const heroOk = Boolean(kit.heroImageUrl);
    const colorsOk = Boolean(kit.colors?.length);
    const chips = [
        `logo ${logoOk ? "✓" : "✗"}`,
        `fonts ${fontsOk ? "✓" : "✗"}`,
        `hero ${heroOk ? "✓" : "✗"}`,
        `colors ${colorsOk ? "✓" : "✗"}`,
    ];
    if (kit.logoSource) {
        chips.push(escapeHtml(kit.logoSource));
    }
    return chips
        .map((label) => `<span class="kit-chip">${label}</span>`)
        .join("");
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

    const logo = buildLogoMarkup(kit);

    const heroBlock = kit.heroImageUrl
        ? `<img class="kit-hero-thumb" src="${escapeHtml(kit.heroImageUrl)}" alt="Hero imagery preview" referrerpolicy="no-referrer" />`
        : '<p class="muted">No hero image detected</p>';

    const headlineRow = kit.headline
        ? `<dt>Headline</dt><dd>${escapeHtml(kit.headline)}</dd>`
        : "";
    const taglineRow = kit.tagline
        ? `<dt>Tagline</dt><dd>${escapeHtml(kit.tagline)}</dd>`
        : "";

    previewEl.innerHTML = `
        <h2>Kit preview</h2>
        <div class="kit-visual-row">
            <figure class="kit-thumb-block">
                <figcaption>Logo</figcaption>
                ${logo.html}
            </figure>
            <figure class="kit-thumb-block">
                <figcaption>Hero / marketing</figcaption>
                ${heroBlock}
            </figure>
        </div>
        <dl class="kit-dl">
            <dt>Site name</dt><dd>${escapeHtml(kit.siteName)}</dd>
            ${headlineRow}
            ${taglineRow}
            <dt>Source</dt><dd><a href="${escapeHtml(kit.sourceUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(kit.sourceUrl)}</a></dd>
            <dt>Colors</dt><dd class="kit-colors">${colors}</dd>
            <dt>Fonts</dt><dd>${escapeHtml(formatFontsRow(kit))}</dd>
            ${
                kit.googleFonts?.length
                    ? `<dt>Google Fonts</dt><dd>${escapeHtml(
                          kit.googleFonts.map((g) => g.family).join(", ")
                      )}</dd>`
                    : ""
            }
            <dt>Scraped</dt><dd>${escapeHtml(kit.scrapedAt || "")}</dd>
        </dl>
        <footer class="kit-completeness" aria-label="Kit completeness">${completenessChips(kit)}</footer>`;
    const rasterLogo = previewEl.querySelector(".kit-logo-raster");
    if (rasterLogo) {
        rasterLogo.addEventListener("error", () => {
            const fallback = rasterLogo.getAttribute("data-fallback");
            if (fallback && rasterLogo.src !== fallback) {
                rasterLogo.src = fallback;
                return;
            }
            const note = document.createElement("p");
            note.className = "muted";
            note.textContent = kit.logoSvg
                ? "No logo (inline SVG blocked)"
                : "No logo (image failed)";
            rasterLogo.replaceWith(note);
        });
    }
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
