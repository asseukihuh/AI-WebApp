"use strict";

/** @typedef {{ sourceUrl: string, siteName: string, logoUrl: string|null, colors: string[], fonts: string[], scrapedAt: string, heroImageUrl?: string, logoSvg?: string, tagline?: string, headline?: string, accentColors?: string[] }} CommunicationKit */

export const KIT_STORAGE_KEY = "commmaker.kit";
export const SESSION_STORAGE_KEY = "commmaker.session";

export function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

export function loadKit() {
    try {
        const raw = localStorage.getItem(KIT_STORAGE_KEY);
        if (!raw) {
            return null;
        }
        return JSON.parse(raw);
    } catch {
        return null;
    }
}

export function saveKit(kit) {
    localStorage.setItem(KIT_STORAGE_KEY, JSON.stringify(kit));
}

export function loadSession() {
    try {
        const raw = sessionStorage.getItem(SESSION_STORAGE_KEY);
        if (!raw) {
            return null;
        }
        return JSON.parse(raw);
    } catch {
        return null;
    }
}

export function saveSession(session) {
    sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
}

const NAV_STEPS = [
    { href: "home.html", label: "Home" },
    { href: "onboard.html", label: "Onboard" },
    { href: "crisis.html", label: "Crisis" },
    { href: "photocraft/", label: "Editor" },
];

export function mountCommMakerNav(container, activePath) {
    if (!container) {
        return;
    }
    const nav = document.createElement("nav");
    nav.className = "commmaker-nav";
    nav.setAttribute("aria-label", "CommMaker flow");

    NAV_STEPS.forEach((step, index) => {
        const link = document.createElement("a");
        link.href = step.href;
        link.textContent = step.label;
        const normalized = activePath.replace(/^\//, "").replace(/index\.html$/, "");
        const stepNorm = step.href.replace(/\/$/, "");
        if (
            normalized === stepNorm ||
            normalized.endsWith("/" + stepNorm) ||
            (stepNorm === "photocraft" && normalized.includes("photocraft"))
        ) {
            link.classList.add("is-active");
            link.setAttribute("aria-current", "page");
        }
        nav.appendChild(link);
        if (index < NAV_STEPS.length - 1) {
            const sep = document.createElement("span");
            sep.className = "commmaker-nav-sep";
            sep.textContent = "→";
            sep.setAttribute("aria-hidden", "true");
            nav.appendChild(sep);
        }
    });

    container.replaceChildren(nav);
}

export function renderKitSummary(target, kit, session) {
    if (!target) {
        return;
    }
    if (!kit && !session) {
        target.hidden = true;
        return;
    }
    target.hidden = false;
    const parts = [];

    if (kit) {
        parts.push(`<p><strong>Brand:</strong> ${escapeHtml(kit.siteName || "—")}</p>`);
        if (kit.colors?.length) {
            const swatches = kit.colors
                .slice(0, 6)
                .map(
                    (c) =>
                        `<span class="kit-swatch" style="background:${escapeHtml(c)}" title="${escapeHtml(c)}"></span>`
                )
                .join("");
            parts.push(`<p class="kit-colors"><strong>Colors:</strong> ${swatches}</p>`);
        }
        if (kit.fonts?.length) {
            parts.push(
                `<p><strong>Fonts:</strong> ${escapeHtml(kit.fonts.join(", "))}</p>`
            );
        }
    }

    if (session?.brief?.headline) {
        parts.push(
            `<p><strong>Headline:</strong> ${escapeHtml(session.brief.headline)}</p>`
        );
    }
    if (session?.captionDraft) {
        parts.push(
            `<details class="kit-caption"><summary>Caption draft</summary><pre>${escapeHtml(session.captionDraft)}</pre></details>`
        );
    }
    if (session?.poster?.openUrl || session?.poster?.documentPath) {
        const path = session.poster.openUrl || session.poster.documentPath;
        parts.push(
            `<p><strong>Poster:</strong> <a href="${escapeHtml(path)}">Open generated .pcraft</a></p>`
        );
    }

    target.innerHTML = parts.join("");
}
