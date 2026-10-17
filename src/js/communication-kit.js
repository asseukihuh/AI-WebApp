"use strict";

const KINDS = [
    "block", "crop", "corner-pin", "swoosh", "confetti", "climbing-holds", "mark-crop",
    "arc", "stripe", "blob", "grid-dots", "chevron", "shield", "wave", "bar", "ring",
    "slash", "burst", "ribbon",
];
const ROLES = ["focal", "support", "texture", "frame"];
const COLOR_ROLES = ["primary", "secondary", "accent", "ink", "surface", "tint"];
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

function svgPreview(markup) {
    if (!markup || !markup.includes("<svg")) {
        return null;
    }
    const doc = new DOMParser().parseFromString(markup, "image/svg+xml");
    const svg = doc.documentElement;
    if (!svg || svg.nodeName.toLowerCase() !== "svg" || doc.querySelector("parsererror")) {
        return null;
    }
    svg.classList.add("ck-device-svg");
    svg.removeAttribute("width");
    svg.removeAttribute("height");
    return svg;
}

function colourHex(kit, role) {
    const found = (kit.colours || []).find((entry) => entry.role === role);
    return HEX_RE.test(found?.hex || "") ? found.hex : "#111111";
}

/**
 * Editable communication kit (devices, colour proportions, type, imagery).
 * @param {HTMLElement} container
 * @param {object} kit scraped kit with communicationKit
 * @param {{ onChange?: (communicationKit: object) => void }} options
 */
export function renderCommunicationKit(container, kit, { onChange } = {}) {
    if (!container || !kit?.communicationKit) {
        if (container) {
            container.hidden = true;
        }
        return;
    }
    const comm = structuredClone(kit.communicationKit);
    const emit = () => onChange?.(comm);

    const proportionBar = el("div", { class: "ck-prop-bar", "aria-hidden": "true" });
    const paintBar = () => {
        const p = comm.proportions || { primary: 60, secondary: 30, accent: 10 };
        proportionBar.replaceChildren(
            el("span", { style: `width:${p.primary}%;background:${colourHex(comm, "primary")}` }),
            el("span", { style: `width:${p.secondary}%;background:${colourHex(comm, "secondary")}` }),
            el("span", { style: `width:${p.accent}%;background:${colourHex(comm, "accent")}` })
        );
    };

    const colourRows = el("div", { class: "ck-colours" });
    const paintColours = () => {
        colourRows.replaceChildren();
        (comm.colours || []).forEach((entry, index) => {
            const picker = el("input", {
                type: "color",
                value: HEX_RE.test(entry.hex) ? entry.hex : "#000000",
                "aria-label": `${entry.role} colour`,
            });
            const hex = el("input", {
                type: "text",
                class: "ck-hex",
                value: entry.hex || "",
                maxlength: 7,
                "aria-label": `${entry.role} hex`,
            });
            const apply = (value) => {
                const next = value.toLowerCase();
                if (!HEX_RE.test(next)) {
                    return;
                }
                comm.colours[index].hex = next;
                picker.value = next;
                hex.value = next;
                paintBar();
                emit();
            };
            picker.addEventListener("input", () => apply(picker.value));
            hex.addEventListener("change", () => apply(hex.value));
            colourRows.append(
                el(
                    "label",
                    { class: "ck-colour" },
                    picker,
                    el("span", { class: "ck-role", text: entry.role }),
                    hex,
                    el("span", { class: "ck-usage", text: entry.usage || "" })
                )
            );
        });
        paintBar();
    };

    const proportionFields = el("div", { class: "ck-proportions" });
    ["primary", "secondary", "accent"].forEach((key) => {
        const input = el("input", {
            type: "number",
            min: "0",
            max: "100",
            value: String(comm.proportions?.[key] ?? 0),
            "aria-label": `${key} proportion`,
        });
        input.addEventListener("change", () => {
            comm.proportions[key] = Number(input.value) || 0;
            paintBar();
            emit();
        });
        proportionFields.append(el("label", { class: "ck-proportion" }, el("span", { text: key }), input));
    });

    const pairing = comm.typePairing || {};
    const typeGrid = el("div", { class: "ck-type" });
    [
        ["displayFamily", "Display family"],
        ["bodyFamily", "Body family"],
    ].forEach(([key, label]) => {
        const input = el("input", { type: "text", value: pairing[key] || "", "aria-label": label });
        input.addEventListener("input", () => {
            comm.typePairing[key] = input.value;
            emit();
        });
        typeGrid.append(el("label", {}, el("span", { text: label }), input));
    });
    const note = el("p", { class: "ck-note", text: pairing.pairingNote || "" });

    const imagery = el("textarea", { class: "ck-imagery", rows: "3", "aria-label": "Imagery direction" });
    imagery.value = comm.imagery?.direction || "";
    imagery.addEventListener("input", () => {
        comm.imagery.direction = imagery.value;
        emit();
    });

    const deviceList = el("div", { class: "ck-devices" });
    const paintDevices = () => {
        deviceList.replaceChildren();
        (comm.devices || []).forEach((device, index) => {
            const kind = el("select", { "aria-label": `Device ${index + 1} kind` });
            KINDS.forEach((name) => kind.append(el("option", { value: name, text: name, selected: name === device.kind })));
            const role = el("select", { "aria-label": `Device ${index + 1} role` });
            ROLES.forEach((name) => role.append(el("option", { value: name, text: name, selected: name === device.role })));
            const color = el("select", { "aria-label": `Device ${index + 1} colour` });
            COLOR_ROLES.forEach((name) => {
                color.append(el("option", { value: name, text: name, selected: name === device.colorRole }));
            });
            kind.addEventListener("change", () => {
                device.kind = kind.value;
                device.svg = "";
                emit();
                paintDevices();
            });
            role.addEventListener("change", () => {
                device.role = role.value;
                emit();
            });
            color.addEventListener("change", () => {
                device.colorRole = color.value;
                emit();
            });
            const remove = el("button", { type: "button", class: "secondary", text: "Remove" });
            remove.addEventListener("click", () => {
                comm.devices.splice(index, 1);
                emit();
                paintDevices();
            });
            const preview = svgPreview(device.svg) || el("span", { class: "ck-device-fallback", text: device.kind });
            const well = el("div", { class: "ck-device-well" });
            well.style.background = colourHex(comm, "secondary");
            well.append(preview);
            deviceList.append(el("article", { class: "ck-device" }, well, kind, role, color, remove));
        });
    };

    const add = el("button", { type: "button", class: "secondary", text: "Add device" });
    add.addEventListener("click", () => {
        comm.devices.push({
            id: `d${comm.devices.length + 1}`,
            kind: "block",
            role: "support",
            colorRole: "accent",
            scale: 0.6,
            rotation: 0,
            anchor: "bottom-right",
            opacity: 0.8,
            count: 1,
            svg: "",
        });
        emit();
        paintDevices();
    });

    const chipList = (key, label) => {
        const wrap = el("div", { class: "ck-chips" });
        const paint = () => {
            wrap.replaceChildren();
            (comm[key] || []).forEach((value, index) => {
                const remove = el("button", { type: "button", text: "×", "aria-label": `Remove ${value}` });
                remove.addEventListener("click", () => {
                    comm[key].splice(index, 1);
                    emit();
                    paint();
                });
                wrap.append(el("span", { class: "ck-chip" }, el("span", { text: value }), remove));
            });
        };
        const input = el("input", { type: "text", placeholder: `Add ${label}`, "aria-label": `Add ${label}` });
        input.addEventListener("keydown", (event) => {
            if (event.key !== "Enter") {
                return;
            }
            event.preventDefault();
            const value = input.value.trim();
            if (!value) {
                return;
            }
            comm[key] = [...(comm[key] || []), value];
            input.value = "";
            emit();
            paint();
        });
        paint();
        return el("div", {}, el("h3", { text: label }), wrap, input);
    };

    paintColours();
    paintDevices();
    const badge = comm.thinSite ? "Designed for a thin site" : "Formalised from the live site";
    container.replaceChildren(
        el("h2", { text: "Communication kit" }),
        el("p", { class: "ck-badge", text: `${badge} · ${comm.sector || "general"}` }),
        el("p", { class: "ck-note", text: comm.logoSystem?.notes || "" }),
        el("h3", { text: "Colour" }),
        proportionBar,
        proportionFields,
        colourRows,
        el("h3", { text: "Type pairing" }),
        typeGrid,
        note,
        el("h3", { text: "Imagery direction" }),
        imagery,
        el("h3", { text: "Graphic devices" }),
        deviceList,
        add,
        chipList("dos", "Do"),
        chipList("donts", "Don't")
    );
    container.hidden = false;
}
