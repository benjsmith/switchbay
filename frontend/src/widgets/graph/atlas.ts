/**
 * Size-gated Knowledge Atlas mount for the Graph tab.
 *
 * Classic remains the default. Wikis above 360 pages get a chooser;
 * the preference is stored in localStorage. Theme comes from Switchbay
 * CSS (`--type-*` + `documentElement.dataset.theme`); selection stays
 * on the existing `#page=<id>` hash so App.tsx still owns the layer.
 */

import type { GraphData } from "./types";

const STORAGE_KEY = "switchbay.viewer";
const LABEL_TYPES_KEY = "curiosity-engine.label-types";
const MIN_ATLAS_PAGES = 360;
const LABEL_DEFAULTS = ["concept", "entity", "note", "todo"];
const PHYSICS_DEFAULTS = { charge: -420, link: 110, collide: 10 };
const TYPE_KEYS = [
  "project", "analysis", "concept", "entity", "evidence", "fact",
  "figure", "table", "source", "note", "todo-list", "unclassified",
] as const;

export type ViewerMode = "classic" | "atlas";

type AtlasHandle = {
  engine: { focus(id: string, origin?: string): void };
  setLabels(mode: "auto" | "on" | "off", types?: readonly string[] | null): void;
  setPhysics(physics: Record<string, number>): void;
  destroy(): void;
};

type AtlasGlobal = {
  mount(
    container: HTMLElement,
    opts: {
      data: GraphData;
      config?: { layout?: string; budget?: { maxEdges?: number } };
      onOpenItem?: (id: string) => void;
    },
  ): AtlasHandle;
};

let atlasHandle: AtlasHandle | null = null;
let classicGraph: Window["Graph"] | null = null;

export function pageCount(data: GraphData): number {
  if (data.pages && typeof data.pages === "object") {
    return Object.keys(data.pages).length;
  }
  return Array.isArray(data.nodes) ? data.nodes.length : 0;
}

export function atlasEligible(data: GraphData): boolean {
  return pageCount(data) > MIN_ATLAS_PAGES;
}

function queryChoice(): ViewerMode | null {
  try {
    const choice = new URLSearchParams(window.location.search).get("viewer");
    return choice === "atlas" || choice === "classic" ? choice : null;
  } catch {
    return null;
  }
}

export function atlasEnabled(data: GraphData): boolean {
  const explicit = queryChoice();
  if (explicit) return explicit === "atlas";
  if (!atlasEligible(data)) return false;
  try {
    return localStorage.getItem(STORAGE_KEY) === "atlas";
  } catch {
    return false;
  }
}

export function paletteFromCss(fallback: Record<string, string> = {}): Record<string, string> {
  const styles = getComputedStyle(document.documentElement);
  const palette: Record<string, string> = { ...fallback };
  for (const t of TYPE_KEYS) {
    const v = styles.getPropertyValue(`--type-${t}`).trim();
    if (v) palette[t] = v;
  }
  return palette;
}

function readLabelTypes(): Set<string> {
  try {
    const saved = JSON.parse(localStorage.getItem(LABEL_TYPES_KEY) || "null");
    if (Array.isArray(saved)) return new Set(saved);
  } catch { /* ignore */ }
  return new Set(LABEL_DEFAULTS);
}

function wireAtlasControls(handle: AtlasHandle): void {
  let mode: "auto" | "on" | "off" = "auto";
  let types = readLabelTypes();
  const modeButton = document.getElementById("label-mode");
  const modeState = document.getElementById("label-mode-state");
  const typeButton = document.getElementById("label-types");
  const typeState = document.getElementById("label-types-state");
  const typePanel = document.getElementById("label-types-panel");
  const settingsButton = document.getElementById("settings-trigger");
  const settingsPanel = document.getElementById("settings-panel");

  const paintLabels = () => {
    if (modeState) modeState.textContent = mode;
    if (typeState) typeState.textContent = `${types.size}/12`;
    handle.setLabels(mode, Array.from(types));
  };
  const setMode = (next: "auto" | "on" | "off") => {
    mode = next;
    document.documentElement.dataset.labels = mode;
    paintLabels();
  };
  const cycleMode = () => {
    const order: Array<"auto" | "on" | "off"> = ["auto", "on", "off"];
    setMode(order[(order.indexOf(mode) + 1) % order.length]);
  };
  modeButton?.addEventListener("click", cycleMode);

  if (typePanel && typeButton) {
    typePanel.querySelectorAll<HTMLElement>(".label-types-row").forEach((row) => {
      const key = row.dataset.type;
      const input = row.querySelector<HTMLInputElement>("input[type=checkbox]");
      if (!key || !input) return;
      input.checked = types.has(key);
      input.addEventListener("change", () => {
        if (input.checked) types.add(key);
        else types.delete(key);
        try { localStorage.setItem(LABEL_TYPES_KEY, JSON.stringify(Array.from(types))); } catch { /* ignore */ }
        paintLabels();
      });
    });
    typeButton.addEventListener("click", (ev) => {
      ev.stopPropagation();
      typePanel.classList.toggle("hidden");
    });
    document.getElementById("label-types-reset")?.addEventListener("click", () => {
      types = new Set(LABEL_DEFAULTS);
      typePanel.querySelectorAll<HTMLElement>(".label-types-row").forEach((row) => {
        const input = row.querySelector<HTMLInputElement>("input[type=checkbox]");
        if (input) input.checked = types.has(row.dataset.type ?? "");
      });
      try { localStorage.setItem(LABEL_TYPES_KEY, JSON.stringify(Array.from(types))); } catch { /* ignore */ }
      paintLabels();
    });
  }

  if (settingsPanel && settingsButton) {
    settingsButton.addEventListener("click", (ev) => {
      ev.stopPropagation();
      settingsPanel.classList.toggle("hidden");
    });
    const bind = (inputId: string, valueId: string, key: string) => {
      const input = document.getElementById(inputId) as HTMLInputElement | null;
      const output = document.getElementById(valueId);
      if (!input) return;
      input.addEventListener("input", () => {
        const value = parseFloat(input.value);
        if (output) output.textContent = input.value;
        handle.setPhysics({ [key]: value });
      });
    };
    bind("phys-charge", "phys-charge-val", "charge");
    bind("phys-link", "phys-link-val", "link");
    bind("phys-collide", "phys-collide-val", "collide");
    document.getElementById("phys-reset")?.addEventListener("click", () => {
      for (const [key, stem] of [
        ["charge", "phys-charge"],
        ["link", "phys-link"],
        ["collide", "phys-collide"],
      ] as const) {
        const input = document.getElementById(stem) as HTMLInputElement | null;
        const output = document.getElementById(`${stem}-val`);
        if (input) input.value = String(PHYSICS_DEFAULTS[key]);
        if (output) output.textContent = String(PHYSICS_DEFAULTS[key]);
      }
      handle.setPhysics(PHYSICS_DEFAULTS);
    });
  }

  document.addEventListener("click", (ev) => {
    const target = ev.target as Node;
    if (typePanel && !typePanel.classList.contains("hidden") &&
        !typePanel.contains(target) && (!typeButton || !typeButton.contains(target))) {
      typePanel.classList.add("hidden");
    }
    if (settingsPanel && !settingsPanel.classList.contains("hidden") &&
        !settingsPanel.contains(target) && (!settingsButton || !settingsButton.contains(target))) {
      settingsPanel.classList.add("hidden");
    }
  });
  paintLabels();
}

function installGraphFacade(handle: AtlasHandle): void {
  if (!classicGraph) classicGraph = window.Graph;
  window.Graph = {
    init: classicGraph.init,
    focus: (pageId: string) => { handle.engine.focus(pageId, "system"); },
    clearFocus: () => { /* atlas focus is the current node; idle has no-op */ },
    splitEnter: () => { /* Atlas has no rubber-band split surface */ },
    splitExit: () => {},
  };
}

export function destroyAtlas(): void {
  if (atlasHandle) {
    try { atlasHandle.destroy(); } catch { /* already torn down */ }
    atlasHandle = null;
  }
  if (classicGraph) window.Graph = classicGraph;
}

export function mountAtlas(data: GraphData): boolean {
  const api = (window as unknown as { KnowledgeAtlas?: AtlasGlobal }).KnowledgeAtlas;
  const container = document.getElementById("graph");
  if (!api || !container) return false;

  destroyAtlas();
  container.innerHTML = "";
  const themed: GraphData = {
    ...data,
    palette: paletteFromCss(data.palette ?? {}),
  };
  const handle = api.mount(container, {
    data: themed,
    config: {
      layout: "hybrid",
      budget: { maxEdges: Math.max(900, (data.edges || []).length) },
    },
    onOpenItem: (id) => {
      window.location.hash = `#page=${encodeURIComponent(id)}`;
    },
  });
  atlasHandle = handle;
  wireAtlasControls(handle);
  installGraphFacade(handle);
  return true;
}

export function initAtlasChoice(data: GraphData, activeMode: ViewerMode): void {
  const button = document.getElementById("viewer-mode");
  const state = document.getElementById("viewer-mode-state");
  if (!button || !state || !atlasEligible(data)) return;

  state.textContent = activeMode;
  button.title = activeMode === "atlas"
    ? "Use the classic force graph"
    : "Use the Knowledge Atlas";
  button.classList.remove("hidden");
  button.addEventListener("click", () => {
    const next: ViewerMode = activeMode === "atlas" ? "classic" : "atlas";
    try { localStorage.setItem(STORAGE_KEY, next); } catch { /* ignore */ }
    try {
      const url = new URL(window.location.href);
      if (url.searchParams.has("viewer")) {
        url.searchParams.delete("viewer");
        window.history.replaceState(null, "", url.toString());
      }
    } catch { /* ignore */ }
    window.dispatchEvent(new CustomEvent("sy:graph-viewer-change"));
  });
}
