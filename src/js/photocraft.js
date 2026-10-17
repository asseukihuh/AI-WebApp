"use strict";

const EDITOR_SRC = "../vendor/photocraft-web/index.html";
const PROBE_SRC = "../vendor/photocraft-web/index.html";

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

document.addEventListener("DOMContentLoaded", async () => {
    if (await assetsPresent()) {
        mountEditor();
    } else {
        showMissing();
    }
});
