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
            <p>See the README and <code>vendor/photocraft-web/README.md</code>.</p>
        </div>`;
}

function mountEditor() {
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
}

function mountPosterFailure(session) {
    const slot = document.getElementById("poster-ready-banner");
    if (!slot || session?.poster?.ok !== false) {
        return;
    }
    const message =
        session.poster.userMessage ||
        session.poster.cliError ||
        "Poster generation did not complete successfully.";
    slot.hidden = false;
    slot.className = "poster-ready-banner poster-ready-banner--error";
    slot.setAttribute("role", "alert");
    slot.innerHTML = `
        <p class="poster-ready-banner__title">Poster generation failed</p>
        <p class="poster-ready-banner__body">${escapeHtml(message)}</p>
        <p class="muted">Return to <a href="../crisis.html">Crisis fast path</a> and try again after fixing the CLI or network issue.</p>
    `;
}

function mountPosterReadyBanner(docUrl) {
    const slot = document.getElementById("poster-ready-banner");
    if (!slot || !docUrl) {
        return;
    }
    const session = loadSession();
    if (session?.poster?.ok === false) {
        mountPosterFailure(session);
        return;
    }

    const safePath = escapeHtml(docUrl);
    const filename = docUrl.split("/").pop() || "commmaker-poster.pcraft";
    slot.hidden = false;
    slot.className = "poster-ready-banner";
    slot.setAttribute("role", "status");
    slot.innerHTML = `
        <div class="poster-ready-banner__inner">
            <p class="poster-ready-banner__title">Your poster is ready</p>
            <p class="poster-ready-banner__body">
                PhotoCraft in the browser cannot open server files directly yet.
                Download the <code>.pcraft</code> file, then open it in the editor below.
            </p>
            <ol class="poster-ready-banner__steps">
                <li>Click <strong>Download .pcraft</strong> (or use the link in the kit banner).</li>
                <li>In PhotoCraft below, choose <strong>File → Open</strong> and select the downloaded file.</li>
                <li>Alternatively, drag the file onto the PhotoCraft window or drop zone.</li>
            </ol>
            <a class="poster-ready-banner__download btn" href="${safePath}" download="${escapeHtml(filename)}">Download .pcraft</a>
        </div>
    `;
}

function mountSessionBanner() {
    const banner = document.getElementById("session-banner");
    const kit = loadKit();
    const session = loadSession();
    if (banner) {
        banner.hidden = false;
    }
    renderKitSummary(banner, kit, session);

    const instructions = document.getElementById("linkedin-instructions");
    const docUrl =
        posterDocFromQuery() ||
        session?.poster?.openUrl ||
        session?.poster?.documentPath;

    if (instructions) {
        const headline = session?.suggestedHeadline || session?.brief?.headline;
        const lines = [];
        if (docUrl && session?.poster?.ok !== false) {
            lines.push(
                "Your generated LinkedIn poster (1200 × 627 px) is ready — use the banner above to download and open it in PhotoCraft."
            );
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

    if (session?.poster?.ok === false) {
        mountPosterFailure(session);
    } else {
        mountPosterReadyBanner(docUrl);
    }
}

document.addEventListener("DOMContentLoaded", async () => {
    mountCommMakerNav(document.getElementById("commmaker-nav"), "photocraft/");
    mountSessionBanner();
    if (await assetsPresent()) {
        mountEditor();
    } else {
        showMissing();
    }
});
