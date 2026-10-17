"use strict";

import {
    loadKit,
    loadSession,
    mountCommMakerNav,
    renderKitSummary,
} from "./commmaker-common.js";

const EDITOR_SRC = "../vendor/photocraft-web/index.html";
const PROBE_SRC = "../vendor/photocraft-web/index.html";
const SOURCE_META_SRC = "../vendor/photocraft-web/.commmaker-source.json";
const FORK_REPO = "asseukihuh/photocraft";

async function assetsPresent() {
    try {
        const res = await fetch(PROBE_SRC, { method: "HEAD", cache: "no-store" });
        return res.ok;
    } catch {
        return false;
    }
}

async function mountSourceBadge() {
    const el = document.getElementById("photocraft-source-badge");
    if (!el) {
        return;
    }
    try {
        const res = await fetch(SOURCE_META_SRC, { cache: "no-store" });
        if (!res.ok) {
            return;
        }
        const meta = await res.json();
        const repo = String(meta.repo || "");
        const ref = String(meta.ref || "unknown");
        const isFork = repo === FORK_REPO;
        el.textContent = isFork
            ? `PhotoCraft: your fork @ ${ref}`
            : `PhotoCraft: ${repo || "upstream"} @ ${ref}`;
        el.hidden = false;
    } catch {
        /* optional metadata */
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
            <pre>./scripts/install-photocraft-from-fork.sh
./scripts/dev-commmaker.sh</pre>
            <p>See <code>vendor/photocraft-web/README.md</code> and the README CommMaker section.</p>
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

function mountSessionBanner() {
    const banner = document.getElementById("session-banner");
    const kit = loadKit();
    const session = loadSession();
    renderKitSummary(banner, kit, session);

    const instructions = document.getElementById("linkedin-instructions");
    if (instructions) {
        const headline = session?.suggestedHeadline || session?.brief?.headline;
        const lines = [
            "Create a new document at 1200 × 627 px (LinkedIn link preview / single-image post).",
            "Use kit colors and fonts from the summary panel; paste the headline into a type layer.",
            "Export PNG via PhotoCraft when ready.",
        ];
        if (headline) {
            lines.splice(2, 0, `Suggested headline: ${headline}`);
        }
        instructions.textContent = lines.join(" ");
    }
}

document.addEventListener("DOMContentLoaded", async () => {
    mountCommMakerNav(document.getElementById("commmaker-nav"), "photocraft/");
    mountSessionBanner();
    await mountSourceBadge();
    if (await assetsPresent()) {
        mountEditor();
    } else {
        showMissing();
    }
});
