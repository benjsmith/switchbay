/**
 * Knowledge Atlas mount for the Graph tab.
 *
 * Classic remains the default. The chooser is always available so a
 * mid-size wiki can still opt in (CE hid it below 360 pages). Preference
 * lives in localStorage. Theme comes from Switchbay CSS (`--type-*` +
 * `documentElement.dataset.theme`); selection stays on `#page=<id>`.
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

/** The resident scene, as the renderer reads it each frame. */
type AtlasScene = {
  nodes: Array<{ id: string; role: string }>;
  edges: Array<{ priority?: number }>;
};

type AtlasEngine = {
  focus(id: string, origin?: string): void;
  getState(): { focusId?: string; pinned?: string[] };
  setViewScale?(scale: number): void;
  select?(ids: string[], mode?: "replace" | "add"): void;
  requestScene?(): void;
  snapshot?(): { scene?: AtlasScene | null };
  /** Internal. `pinned` is what the renderer draws the dashed halo
   *  from; assigning it avoids pin()'s scene rebuild (see
   *  atlasHighlightSearch). */
  trails?: { pinned: string[] };
  /** Scene-space (canvas-centre origin) hit test, same one the vendored
   *  engine uses for its own clicks. */
  hitTester?: {
    pointAt(x: number, y: number, slack?: number): { id: string; kind: string } | null;
  };
};

type AtlasHandle = {
  engine: AtlasEngine;
  setLabels(mode: "auto" | "on" | "off", types?: readonly string[] | null): void;
  setPhysics(physics: Record<string, number>): void;
  destroy(): void;
};

type AtlasEvent = {
  kind: string;
  id?: string;
  origin?: "user" | "system" | "history";
};

type AtlasGlobal = {
  mount(
    container: HTMLElement,
    opts: {
      data: GraphData;
      config?: {
        layout?: string;
        corpusSize?: number;
        coreCapacity?: number;
        maxVisibleNodes?: number;
        budget?: {
          maxNodes?: number;
          maxAggregates?: number;
          maxEdges?: number;
        };
      };
      onOpenItem?: (id: string) => void;
      onEvent?: (event: AtlasEvent) => void;
    },
  ): AtlasHandle;
};

let atlasHandle: AtlasHandle | null = null;
let classicGraph: Window["Graph"] | null = null;
let atlasMinimapWheel: (() => void) | null = null;
/** Repaints the current scene without rebuilding it (see wireAtlasControls). */
let atlasRepaint: (() => void) | null = null;

/**
 * A search hit wears the dashed halo — the renderer's "pinned" mark,
 * read straight off engine state at draw time.
 *
 * What it must NOT do is call pin()/unpin(): those ask for a scene
 * rebuild each, so a 40-hit query fired dozens of async rebuilds per
 * keystroke, and a rebuild landing after the search was cleared
 * repainted the stale halos — that is how hits got stuck highlighted.
 * Writing the array and asking for one repaint touches no scene at
 * all. Selection is cleared alongside: its solid accent ring is a
 * second, competing highlight on the same nodes.
 */
function atlasHighlightSearch(handle: AtlasHandle, ids: string[]): void {
  const engine = handle.engine;
  if (engine.trails && Array.isArray(engine.trails.pinned)) {
    engine.trails.pinned = [...ids];
  }
  engine.select?.([], "replace");
  atlasRepaint?.();
  const host = document.getElementById("graph");
  if (host) host.dataset.searchHits = String(ids.length);
}

/**
 * Drop Atlas's "current focus" mark from the resident scene.
 *
 * The scene builder always designates one node as the focus — accent
 * ring, its edges lit at `priority: 1` — and when the host has no focus
 * it picks a deterministic entry node instead. In Switch Bay the whole
 * wiki stays resident as a single full-graph scene, so the engine skips
 * rebuilds on focus changes and that mark is stuck on a page the user
 * never chose, ringed and trailing blue edges for the whole session.
 *
 * Roles are read by the renderer per frame and by the layout only while
 * solving, which has already happened by scene-ready — so demoting them
 * afterwards changes the picture and nothing else. Returns whether a
 * repaint is warranted.
 */
function stripAtlasFocusMark(engine: AtlasEngine): boolean {
  const scene = engine.snapshot?.().scene;
  if (!scene) return false;
  let changed = false;
  for (const node of scene.nodes) {
    if (node.role === "focus") {
      node.role = "neighbour";
      changed = true;
    }
  }
  for (const edge of scene.edges) {
    if (edge.priority === 1) {
      edge.priority = 5;
      changed = true;
    }
  }
  return changed;
}

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

export function atlasEnabled(_data: GraphData): boolean {
  const explicit = queryChoice();
  if (explicit) return explicit === "atlas";
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
  // setLabels re-renders the resident scene (no rebuild, no layout
  // churn) — the cheapest repaint the vendored API exposes.
  atlasRepaint = paintLabels;
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

let atlasOnSelect: ((id: string) => void) | null = null;
let atlasClickUnbind: (() => void) | null = null;

function openAtlasPage(id: string): void {
  if (!id) return;
  // One channel only. Hash + sy:open-wiki-page + setSelection used to
  // race: close cleared selection, then a late hashchange reopened it.
  atlasOnSelect?.(id);
}

/** Open the page under a non-drag pointerup, and treat a click on empty
 *  canvas as "drop the selection".
 *
 *  This used to open whatever `canvas.dataset.hoverId` held at
 *  pointerdown. Hover only updates on pointermove, so any click that
 *  followed a scene change — a node that drifted out from under the
 *  cursor, a click after a wheel-zoom — opened a document the user
 *  never pointed at. The engine's own hit tester answers the actual
 *  question: is there a node under this pixel? */
function bindAtlasNodeClick(container: HTMLElement, engine: AtlasEngine): () => void {
  let press: { x: number; y: number; hoverId: string | null } | null = null;
  const mainCanvas = () =>
    container.querySelector<HTMLCanvasElement>("canvas:not(.atlas-minimap)");
  /** id | null (empty space) | undefined (no hit tester — can't tell). */
  const nodeAt = (ev: PointerEvent): string | null | undefined => {
    const canvas = mainCanvas();
    const tester = engine.hitTester;
    if (!canvas || !tester?.pointAt) return undefined;
    const rect = canvas.getBoundingClientRect();
    const hit = tester.pointAt(
      ev.clientX - rect.left - rect.width / 2,
      ev.clientY - rect.top - rect.height / 2,
      6,
    );
    return hit && hit.kind === "node" ? hit.id : null;
  };
  const onDown = (ev: PointerEvent) => {
    const t = ev.target;
    if (!(t instanceof Element) || t.closest(".atlas-minimap")) {
      press = null;
      return;
    }
    press = {
      x: ev.clientX,
      y: ev.clientY,
      hoverId: mainCanvas()?.dataset.hoverId || null,
    };
  };
  const onUp = (ev: PointerEvent) => {
    if (!press) return;
    const dragged = Math.hypot(ev.clientX - press.x, ev.clientY - press.y) > 6;
    const hovered = press.hoverId;
    press = null;
    if (dragged) return;
    const hit = nodeAt(ev);
    const id = hit === undefined ? hovered : hit;
    if (id) {
      openAtlasPage(id);
    } else {
      window.dispatchEvent(new CustomEvent("sy:graph-blank-click"));
    }
  };
  container.addEventListener("pointerdown", onDown, true);
  container.addEventListener("pointerup", onUp, true);
  return () => {
    container.removeEventListener("pointerdown", onDown, true);
    container.removeEventListener("pointerup", onUp, true);
  };
}

function installGraphFacade(handle: AtlasHandle): void {
  if (!classicGraph) classicGraph = window.Graph;
  window.Graph = {
    init: classicGraph.init,
    focus: (pageId: string) => {
      // Selection sync calls this with origin "system". Skip a no-op
      // rebuild when the click already focused this node.
      if (handle.engine.getState().focusId === pageId) return;
      handle.engine.focus(pageId, "system");
    },
    clearFocus: () => {
      // Nothing to undo: the accent focus mark is stripped from every
      // scene as it lands (stripAtlasFocusMark), so there is no ring to
      // chase here. Forcing a rebuild to unset the engine's focusId
      // would only make the builder pick a fresh entry node.
    },
    highlightSearch: (ids: string[]) => {
      atlasHighlightSearch(handle, ids);
    },
    splitEnter: () => { /* Atlas has no rubber-band split surface */ },
    splitExit: () => {},
  };
}

export function destroyAtlas(): void {
  if (atlasMinimapWheel) {
    atlasMinimapWheel();
    atlasMinimapWheel = null;
  }
  if (atlasClickUnbind) {
    atlasClickUnbind();
    atlasClickUnbind = null;
  }
  atlasOnSelect = null;
  atlasRepaint = null;
  if (atlasHandle) {
    try { atlasHandle.destroy(); } catch { /* already torn down */ }
    atlasHandle = null;
  }
  if (classicGraph) window.Graph = classicGraph;
}

export function mountAtlas(
  data: GraphData,
  opts?: { onSelectPage?: (id: string) => void },
): boolean {
  const api = (window as unknown as { KnowledgeAtlas?: AtlasGlobal }).KnowledgeAtlas;
  const container = document.getElementById("graph");
  if (!api || !container) return false;

  destroyAtlas();
  atlasOnSelect = opts?.onSelectPage ?? null;
  container.innerHTML = "";
  const themed: GraphData = {
    ...data,
    palette: paletteFromCss(data.palette ?? {}),
  };
  const corpusSize = pageCount(data);
  const handle = api.mount(container, {
    data: themed,
    config: {
      // Hybrid: Classic field in the core, log-compressed individual
      // nodes on the rim. corpusSize makes the first frame that view
      // (not type-cluster bubbles). Boundary drag is lens traversal
      // (nodes/s), not a pan of the middle graph. The rate HUD in
      // vendored knowledge-atlas.js is drawn at the TOP of the
      // canvas (`fillText` y = -height/2+22). Upstream default is
      // the bottom, which sits under the types picker in a narrow pane.
      layout: "hybrid",
      corpusSize,
      // The vendored engine otherwise opens at its generic 460-node budget,
      // emits legacy type aggregates, and only requests the full hybrid scene
      // after the first wheel/resize event. Pin the initial capacity to this
      // corpus before start(), and explicitly disable aggregate placeholders.
      // ResizeObserver keeps the same capacity, so first mount, remount, and
      // viewport changes all render the identical individual-node scene.
      coreCapacity: Math.max(1, corpusSize),
      maxVisibleNodes: Math.max(1, corpusSize),
      budget: {
        maxNodes: Math.max(1, corpusSize),
        maxAggregates: 0,
        maxEdges: Math.max(900, (data.edges || []).length),
      },
    },
    onOpenItem: openAtlasPage,
    onEvent: (event) => {
      // Pointer-up already opens via bindAtlasNodeClick. Ignore
      // traversal commits (origin user) so fly-through does not spam
      // the doc modal.
      if (event.kind === "item-open-requested" && event.id) {
        openAtlasPage(event.id);
      }
      // Every scene arrives carrying a focus mark. Take it off before
      // the user sees it; the engine's own scene-ready paint runs after
      // this callback, so no extra repaint is needed here.
      if (event.kind === "scene-ready" && atlasHandle) {
        stripAtlasFocusMark(atlasHandle.engine);
      }
    },
  });
  atlasHandle = handle;
  atlasMinimapWheel = bindAtlasMinimapWheel(container);
  atlasClickUnbind = bindAtlasNodeClick(container, handle.engine);
  wireAtlasControls(handle);
  installGraphFacade(handle);
  // Covers a scene that landed before atlasHandle was assigned (the
  // onEvent hook above skips those).
  if (stripAtlasFocusMark(handle.engine)) atlasRepaint?.();
  return true;
}

/**
 * Classic's overview map is part of the plotting area: wheel-while-
 * hovering must zoom the main view, not die on the map canvas. Atlas
 * vendors a sibling canvas with no wheel handler, so the event never
 * reaches the main canvas. Forward it there, anchored at the viewport
 * centre — same "keep looking here, change scale" contract as Classic,
 * and independent of where Zen has parked the map (float / tab / pill).
 */
function bindAtlasMinimapWheel(container: HTMLElement): () => void {
  const onWheel = (ev: WheelEvent) => {
    const overMap = ev.target instanceof Element && ev.target.closest(".atlas-minimap");
    if (!overMap) return;
    ev.preventDefault();
    ev.stopPropagation();
    const main = container.querySelector<HTMLCanvasElement>("canvas:not(.atlas-minimap)");
    if (!main) return;
    const rect = main.getBoundingClientRect();
    main.dispatchEvent(new WheelEvent("wheel", {
      deltaX: ev.deltaX,
      deltaY: ev.deltaY,
      deltaZ: ev.deltaZ,
      deltaMode: ev.deltaMode,
      clientX: rect.left + rect.width / 2,
      clientY: rect.top + rect.height / 2,
      ctrlKey: ev.ctrlKey,
      metaKey: ev.metaKey,
      altKey: ev.altKey,
      shiftKey: ev.shiftKey,
      bubbles: false,
      cancelable: true,
    }));
  };
  container.addEventListener("wheel", onWheel, { capture: true, passive: false });
  return () => container.removeEventListener("wheel", onWheel, true);
}

export function initAtlasChoice(_data: GraphData, activeMode: ViewerMode): void {
  const button = document.getElementById("viewer-mode");
  const state = document.getElementById("viewer-mode-state");
  const atlasApi = (window as unknown as { KnowledgeAtlas?: AtlasGlobal }).KnowledgeAtlas;
  if (!button || !state || !atlasApi) return;

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
