"use strict";

import {
    loadKit,
    loadSession,
    mountCommMakerNav,
    renderKitSummary,
    escapeHtml,
} from "./commmaker-common.js";

const EDITOR_SRC = "../vendor/photocraft-web/index.html";
const PROBE_SRC = "../vendor/photocraft-web/index.html";

function posterDocFromQuery() {
    const params = new URLSearchParams(window.location.search);
    const doc = params.get("doc");
    if (!doc) {
        return null;
    }
    const normalized = doc.startsWith("/") ? doc : `/${doc}`;
    if (!/^\/generated\/[\w./-]+\.pcraft$/i.test(normalized)) {
        return null;
    }
    return normalized;
}

async function assetsPresent() {
    try {
        const res = await fetch(PROBE_SRC, { method: "HEAD", cache: "no-store" });
        return res.ok;
    } catch {
        return false;
    }
}

function showMissing() {
    const wrap = document.getElementById("photocraft-frame-wrap");
    if (!wrap) {
        return;
    }
    wrap.innerHTML = `
        <div class="photocraft-missing">
            <p>PhotoCraft web assets are not installed yet.</p>
            <pre>./scripts/fetch-photocraft-web.sh
python3 scripts/serve-static.py --port 8000</pre>
            <p>See <code>vendor/photocraft-web/README.md</code> and the README CommMaker section.</p>
        </div>`;
}

function mountEditor(docUrl) {
    const wrap = document.getElementById("photocraft-frame-wrap");
    if (!wrap) {
        return;
    }
    const iframe = document.createElement("iframe");
    iframe.className = "photocraft-frame";
    iframe.title = "PhotoCraft image editor";
    iframe.src = EDITOR_SRC;
    iframe.setAttribute(
        "allow",
        "fullscreen; clipboard-read; clipboard-write"
    );
    iframe.setAttribute("allowfullscreen", "");
    wrap.appendChild(iframe);

    if (docUrl) {
        const note = document.createElement("p");
        note.className = "photocraft-open-hint muted";
        note.innerHTML =
            "PhotoCraft web cannot auto-open server files yet. Use <strong>File → Open</strong> and choose the downloaded file, or open the link below.";
        wrap.insertAdjacentElement("afterbegin", note);
    }
}

function mountPosterCallout(docUrl) {
    const slot = document.getElementById("poster-open-callout");
    if (!slot || !docUrl) {
        return;
    }
    slot.hidden = false;
    const absolute = docUrl.startsWith("http")
        ? docUrl
        : `${window.location.origin}${docUrl}`;
    const safePath = escapeHtml(docUrl);
    const safeAbs = escapeHtml(absolute);
    slot.innerHTML = `
        <p class="poster-callout-title">Your generated poster is ready</p>
        <p><a class="poster-open-link" href="${safePath}" download>Open your generated poster (.pcraft)</a></p>
        <p class="muted">Direct URL: <code>${safeAbs}</code> — in PhotoCraft use <strong>File → Open</strong> after download, or drag the file into the editor window.</p>
    `;
}

function mountSessionBanner() {
    const banner = document.getElementById("session-banner");
    const kit = loadKit();
    const session = loadSession();
    renderKitSummary(banner, kit, session);

    const instructions = document.getElementById("linkedin-instructions");
    const docUrl = posterDocFromQuery() || session?.poster?.openUrl || session?.poster?.documentPath;

    if (instructions) {
        const headline = session?.suggestedHeadline || session?.brief?.headline;
        const lines = [];
        if (docUrl) {
            lines.push("Open your generated LinkedIn poster (1200 × 627 px) using the link below.");
        } else {
            lines.push(
                "Create a new document at 1200 × 627 px (LinkedIn link preview / single-image post), or generate a poster from the Crisis page."
            );
        }
        if (headline) {
            lines.push(`Suggested headline: ${headline}`);
        }
        lines.push("Export PNG via PhotoCraft when ready.");
        instructions.textContent = lines.join(" ");
    }

    mountPosterCallout(docUrl);
}

document.addEventListener("DOMContentLoaded", async () => {
    mountCommMakerNav(document.getElementById("commmaker-nav"), "photocraft/");
    mountSessionBanner();
    const docUrl = posterDocFromQuery() || loadSession()?.poster?.openUrl;
    if (await assetsPresent()) {
        mountEditor(docUrl);
    } else {
        showMissing();
        mountPosterCallout(docUrl);
    }
});
