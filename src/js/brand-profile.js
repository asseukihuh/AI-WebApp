"use strict";

import { sanitizeInlineSvg } from "./commmaker-common.js";

const PALETTE_ROLES = ["background", "primary", "text", "accent", "secondary", "surface"];
const HEX_RE = /^#[0-9a-f]{6}$/i;

function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
        if (value === undefined || value === null || value === false) {
            continue;
        }
        if (key === "class") {
            node.className = value;
        } else if (key === "text") {
            node.textContent = value;
        } else if (key === "style" && typeof value === "object") {
            Object.assign(node.style, value);
        } else {
            node.setAttribute(key, value === true ? "" : String(value));
        }
    }
    for (const child of children.flat()) {
        if (child === null || child === undefined || child === false) {
            continue;
        }
        node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
}

function card(title, extraClass, ...body) {
    return el(
        "div",
        { class: `bp-card ${extraClass || ""}`.trim() },
        title ? el("h3", { class: "bp-card-title", text: title }) : null,
        ...body
    );
}

function chipEditor(values, { label, placeholder, onChange, max = 8 }) {
    const list = [...(values || [])];
    const wrap = el("div", { class: "bp-chips", role: "list", "aria-label": label });

    const render = () => {
        wrap.replaceChildren();
        list.forEach((value, index) => {
            const remove = el("button", {
                type: "button",
                class: "bp-chip-remove",
                "aria-label": `Remove ${value}`,
                text: "×",
            });
            remove.addEventListener("click", () => {
                list.splice(index, 1);
                onChange([...list]);
                render();
            });
            wrap.append(el("span", { class: "bp-chip", role: "listitem" }, el("span", { text: value }), remove));
        });
        if (list.length < max) {
            const input = el("input", {
                type: "text",
                class: "bp-chip-input",
                placeholder: placeholder || "Add…",
                "aria-label": `Add ${label}`,
            });
            input.addEventListener("keydown", (event) => {
                if (event.key !== "Enter") {
                    return;
                }
                event.preventDefault();
                const value = input.value.trim();
                if (value && !list.some((v) => v.toLowerCase() === value.toLowerCase())) {
                    list.push(value);
                    onChange([...list]);
                    render();
                    wrap.querySelector(".bp-chip-input")?.focus();
                }
            });
            wrap.append(input);
        }
    };
    render();
    return wrap;
}

function textField(value, { label, multiline = false, className = "", onChange }) {
    const input = multiline
        ? el("textarea", { class: `bp-input ${className}`.trim(), rows: 3, "aria-label": label })
        : el("input", { type: "text", class: `bp-input ${className}`.trim(), "aria-label": label });
    input.value = value || "";
    input.addEventListener("input", () => onChange(input.value));
    return input;
}

function selectField(value, options, { label, onChange }) {
    const select = el("select", { class: "bp-select", "aria-label": label });
    for (const option of options) {
        select.append(el("option", { value: option, text: option, selected: option === value }));
    }
    select.addEventListener("change", () => onChange(select.value));
    return select;
}

function logoNode(kit) {
    const svg = kit?.logoSvg ? sanitizeInlineSvg(kit.logoSvg) : null;
    if (svg) {
        svg.removeAttribute("width");
        svg.removeAttribute("height");
        svg.classList.add("bp-logo-svg");
        return svg;
    }
    const src = kit?.logoUrl || kit?.faviconUrl;
    if (src) {
        return el("img", { class: "bp-logo-img", src, alt: `${kit.siteName || "Brand"} logo`, referrerpolicy: "no-referrer" });
    }
    return el("p", { class: "bp-muted", text: "No logo detected" });
}

function swatch(entry, index, profile, emit) {
    const color = el("input", {
        type: "color",
        class: "bp-swatch-picker",
        value: HEX_RE.test(entry.hex) ? entry.hex : "#000000",
        "aria-label": `${entry.role} colour`,
    });
    const circle = el("label", { class: "bp-swatch", style: { background: entry.hex }, title: entry.usage || entry.role }, color);
    const hex = el("input", { type: "text", class: "bp-hex", value: entry.hex, maxlength: 7, "aria-label": `${entry.role} hex` });
    const role = selectField(entry.role, PALETTE_ROLES, {
        label: "Colour role",
        onChange: (value) => {
            profile.palette[index].role = value;
            emit();
        },
    });
    const setHex = (value) => {
        const next = value.toLowerCase();
        if (!HEX_RE.test(next)) {
            return;
        }
        Object.assign(profile.palette[index], { hex: next, source: "user", verified: true });
        circle.style.background = next;
        color.value = next;
        hex.value = next;
        badge.textContent = "edited";
        emit();
    };
    color.addEventListener("input", () => setHex(color.value));
    hex.addEventListener("change", () => setHex(hex.value.trim()));
    const badgeText = entry.source === "vision" ? "vision only" : entry.source === "user" ? "edited" : entry.verified ? "verified" : "";
    const badge = el("span", {
        class: `bp-swatch-badge ${entry.source === "vision" ? "is-vision" : ""}`.trim(),
        text: badgeText,
        title: entry.source === "vision" ? "Seen in screenshots but not found in CSS" : "Matches a scraped CSS / computed colour",
    });
    return el("div", { class: "bp-swatch-cell" }, circle, hex, el("span", { class: "bp-swatch-name", text: entry.name || "" }), role, badge);
}

function fontBlock(roleLabel, font, onChange) {
    const family = font?.family || "system-ui";
    const sample = el("div", { class: "bp-font-sample", text: "Aa", style: { fontFamily: `"${family}", system-ui, sans-serif` } });
    const input = textField(family, {
        label: `${roleLabel} font family`,
        className: "bp-font-name",
        onChange: (value) => {
            sample.style.fontFamily = `"${value}", system-ui, sans-serif`;
            onChange(value);
        },
    });
    const weights = (font?.weights || []).join(" · ");
    return el(
        "div",
        { class: "bp-font" },
        sample,
        input,
        el("span", { class: "bp-muted", text: `${roleLabel}${weights ? ` · ${weights}` : ""}${font?.matched === false ? " · not on site" : ""}` })
    );
}

function sourceLine(result) {
    const profile = result.brandProfile || {};
    const parts = [];
    if (result.source === "llm") {
        parts.push(`AI vision · ${result.model || "LLM"}`);
        if (typeof result.costUsd === "number") {
            parts.push(`$${result.costUsd.toFixed(3)}`);
        }
    } else {
        parts.push("Procedural fallback");
        if (result.fallbackReason) {
            parts.push(result.fallbackReason === "no_provider" ? "set ANTHROPIC_API_KEY for AI vision" : result.fallbackReason);
        }
    }
    parts.push(result.capture?.available ? "rendered screenshots" : `static HTML only${result.capture?.reason ? ` (${result.capture.reason})` : ""}`);
    if (result.cached) {
        parts.push("cached");
    }
    if (profile.analysis?.analyzedAt) {
        parts.push(new Date(profile.analysis.analyzedAt).toLocaleString());
    }
    return parts.join(" · ");
}

function linkList(items, empty) {
    if (!items?.length) {
        return el("p", { class: "bp-muted", text: empty });
    }
    return el(
        "ul",
        { class: "bp-links" },
        items.map((item) => {
            const href = typeof item === "string" ? item : item.href;
            const label = typeof item === "string" ? item.replace(/^https?:\/\/(www\.)?/, "") : item.text;
            return el("li", {}, el("a", { href, target: "_blank", rel: "noopener noreferrer", text: label }));
        })
    );
}

/**
 * Render an editable Pomelli-style Brand Profile.
 * @param {HTMLElement} container
 * @param {object} result  /api/brand-profile payload ({ brandProfile, kit, capture, source, … })
 * @param {{ onChange?: (profile: object) => void }} options
 */
export function renderBrandProfile(container, result, { onChange } = {}) {
    if (!container || !result?.brandProfile) {
        return;
    }
    const profile = structuredClone(result.brandProfile);
    const kit = result.kit || {};
    const emit = () => onChange?.(profile);
    const set = (key) => (value) => {
        profile[key] = value;
        emit();
    };

    const logoCard = el("div", { class: "bp-card bp-logo-card", style: { background: profile.logo?.backdropHex || "#ffffff" } }, logoNode(kit));
    const backdrop = el("input", {
        type: "color",
        class: "bp-backdrop-picker",
        value: HEX_RE.test(profile.logo?.backdropHex || "") ? profile.logo.backdropHex : "#ffffff",
        "aria-label": "Logo backdrop colour",
        title: "Logo backdrop colour",
    });
    backdrop.addEventListener("input", () => {
        profile.logo = { ...(profile.logo || {}), backdropHex: backdrop.value };
        logoCard.style.background = backdrop.value;
        emit();
    });
    logoCard.append(backdrop);

    const typo = profile.typography || {};
    const fontsCard = card(
        "Fonts",
        "bp-fonts-card",
        el(
            "div",
            { class: "bp-fonts" },
            fontBlock("Display", typo.display, (value) => {
                profile.typography.display = { ...profile.typography.display, family: value, matched: undefined };
                emit();
            }),
            fontBlock("Body", typo.body, (value) => {
                profile.typography.body = { ...profile.typography.body, family: value, matched: undefined };
                emit();
            })
        )
    );

    const nameInput = textField(profile.name, { label: "Brand name", className: "bp-name", onChange: set("name") });
    const identity = card(
        null,
        "bp-identity",
        nameInput,
        el("a", { class: "bp-url", href: profile.sourceUrl || kit.sourceUrl, target: "_blank", rel: "noopener noreferrer", text: profile.sourceUrl || kit.sourceUrl || "" })
    );

    const palette = el("div", { class: "bp-palette" }, (profile.palette || []).map((entry, index) => swatch(entry, index, profile, emit)));

    const imagery = profile.imageryStyle || {};
    const layout = profile.layoutTraits || {};
    const imageryCard = card(
        "Imagery style",
        "bp-imagery",
        el(
            "div",
            { class: "bp-inline" },
            selectField(imagery.primaryMedium || "mixed", ["photography", "illustration", "3d-render", "gradients", "abstract-shapes", "product-ui", "typographic", "mixed"], {
                label: "Primary medium",
                onChange: (value) => {
                    profile.imageryStyle = { ...profile.imageryStyle, primaryMedium: value };
                    emit();
                },
            }),
            imagery.colorTreatment ? el("span", { class: "bp-muted", text: imagery.colorTreatment }) : null
        ),
        chipEditor(imagery.motifs, {
            label: "Motifs",
            placeholder: "Add motif…",
            onChange: (value) => {
                profile.imageryStyle = { ...profile.imageryStyle, motifs: value };
                emit();
            },
        }),
        el("label", { class: "bp-sub-label", text: "Background art direction (Ideogram)" }),
        textField(imagery.ideogramPrompt, {
            label: "Ideogram art direction",
            multiline: true,
            onChange: (value) => {
                profile.imageryStyle = { ...profile.imageryStyle, ideogramPrompt: value };
                emit();
            },
        })
    );
    const layoutField = (key, options, label) =>
        el(
            "label",
            { class: "bp-trait" },
            el("span", { text: label }),
            selectField(layout[key], options, {
                label,
                onChange: (value) => {
                    profile.layoutTraits = { ...profile.layoutTraits, [key]: value };
                    emit();
                },
            })
        );
    const layoutCard = card(
        "Layout & guardrails",
        "bp-layout",
        el(
            "div",
            { class: "bp-traits" },
            layoutField("density", ["airy", "balanced", "dense"], "Density"),
            layoutField("cornerRadius", ["sharp", "subtle", "rounded", "pill"], "Corners"),
            layoutField("whitespace", ["generous", "moderate", "tight"], "Whitespace")
        ),
        layout.composition ? el("p", { class: "bp-muted", text: layout.composition }) : null,
        el("label", { class: "bp-sub-label", text: "Don'ts" }),
        chipEditor(profile.doNots, { label: "Don'ts", placeholder: "Add guardrail…", onChange: set("doNots"), max: 6 })
    );

    const packet = result.ideogramPacket || profile.ideogramPacket || {};
    const kept = Array.isArray(packet.references) ? packet.references.filter(Boolean) : [];
    const cropsBlock = kept.length
        ? el(
              "div",
              { class: "bp-crops" },
              el("h3", { class: "bp-sub-label", text: "Examples Claude kept" }),
              el("p", { class: "bp-muted", text: "These crops are what the poster prompt is written from. A webpage screenshot is not sent for Ideogram to edit." }),
              el(
                  "div",
                  { class: "bp-shot-row" },
                  kept.map((src, index) => el("img", { src, alt: `Crop ${index + 1}`, class: "bp-shot", loading: "lazy" }))
              )
          )
        : null;

    const shots = result.capture?.screenshots || {};
    const shotsBlock = Object.keys(shots).length
        ? el(
              "details",
              { class: "bp-shots" },
              el("summary", { text: "Screenshots analysed" }),
              el(
                  "div",
                  { class: "bp-shot-row" },
                  Object.entries(shots).map(([key, src]) =>
                      el("a", { href: src, target: "_blank", rel: "noopener" }, el("img", { src, alt: key, class: `bp-shot bp-shot-${key}`, loading: "lazy" }))
                  )
              )
          )
        : null;

    const overviewPanel = el(
        "div",
        { class: "bp-panel", role: "tabpanel", id: "bp-panel-overview" },
        identity,
        el("div", { class: "bp-row bp-row-logo" }, logoCard, fontsCard),
        card("Colors", "bp-colors", palette),
        el(
            "div",
            { class: "bp-grid" },
            card("Tagline", "bp-tagline", textField(profile.tagline, { label: "Tagline", multiline: true, className: "bp-tagline-input", onChange: set("tagline") })),
            card("Brand values", "", chipEditor(profile.brandValues, { label: "Brand values", placeholder: "Add value…", onChange: set("brandValues") })),
            card("Brand aesthetic", "", chipEditor(profile.aesthetic, { label: "Brand aesthetic", placeholder: "Add aesthetic…", onChange: set("aesthetic") })),
            card("Brand tone of voice", "", chipEditor(profile.toneOfVoice, { label: "Tone of voice", placeholder: "Add tone…", onChange: set("toneOfVoice") }))
        ),
        card("Business overview", "bp-overview", textField(profile.businessOverview, { label: "Business overview", multiline: true, onChange: set("businessOverview") })),
        el("div", { class: "bp-grid" }, imageryCard, layoutCard),
        cropsBlock,
        shotsBlock
    );

    const details = profile.businessDetails || {};
    const detailsPanel = el(
        "div",
        { class: "bp-panel", role: "tabpanel", id: "bp-panel-details", hidden: true },
        el(
            "div",
            { class: "bp-grid" },
            card("Keywords", "", chipEditor(profile.keywords, { label: "Keywords", placeholder: "Add keyword…", onChange: set("keywords"), max: 12 })),
            card("Social media", "", linkList(details.socialLinks, "No social links found on the page")),
            card("Call to action links", "", linkList(details.ctaLinks, "No CTA links found")),
            card("Visual summary", "", el("p", { class: "bp-body", text: profile.visualSummary || "—" }))
        )
    );

    const tabs = [
        ["overview", "Brand Overview", overviewPanel],
        ["details", "Business Details", detailsPanel],
    ];
    const tabList = el("div", { class: "bp-tabs", role: "tablist" });
    for (const [key, label, panel] of tabs) {
        const tab = el("button", { type: "button", class: "bp-tab", role: "tab", "aria-controls": panel.id, "aria-selected": key === "overview" ? "true" : "false", text: label });
        tab.addEventListener("click", () => {
            for (const [, , other] of tabs) {
                other.hidden = other !== panel;
            }
            for (const t of tabList.children) {
                t.setAttribute("aria-selected", t === tab ? "true" : "false");
            }
        });
        tabList.append(tab);
    }

    container.replaceChildren(
        el(
            "div",
            { class: "bp-head" },
            el("h2", { class: "bp-title", text: "Your Business Profile" }),
            el("p", { class: "bp-source", text: sourceLine(result) })
        ),
        tabList,
        overviewPanel,
        detailsPanel
    );
    container.hidden = false;
    return profile;
}
