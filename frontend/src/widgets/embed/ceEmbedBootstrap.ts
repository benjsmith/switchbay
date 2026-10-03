/**
 * Same-origin CE atlas embed bootstrap (no full-document HTML remount).
 *
 * Prefer `window.CEEmbed.mount` when CE ships embed mode. Until then, load
 * CE static modules from `/embed/ce/static/…` and run a Switchbay stub that
 * mirrors `main.js` without Sidebar / filebrowser chrome.
 *
 * CE hook (for CE Benchmarker) — see docs/architecture.md:
 *   window.CEEmbed.mount(container, {
 *     embed: true,
 *     dataUrl: "/embed/ce/data.json",
 *     publicBase: "/embed/ce",
 *     chrome: false,  // no sidebar / workspace title / theme footer
 *   }) => { destroy(): void }
 */

import { isSwitchbayReservedApi } from "./embedMount.ts";
export type CeEmbedOptions = {
  embed: true;
  dataUrl: string;
  publicBase: string;
  /** When false (default), skip CE pages sidebar / atlas chrome duplicates. */
  chrome?: boolean;
  /** Workspace path or basename — keys CEAtlasCache (IndexedDB cold start). */
  workspace?: string;
  /** Explicit atlas cache key (overrides workspace). */
  cacheKey?: string;
};

export type CeEmbedHandle = {
  destroy: () => void;
};

/** Dual-mount handle from window.CEEmbed.create */
export type CeCreateHandle = {
  mountSidebar: (el: HTMLElement) => void;
  mountCanvas: (el: HTMLElement) => void;
  /** Soft park by default; pass {destroy:true} to tear down atlas. */
  unmountCanvas?: (opts?: { destroy?: boolean }) => void;
  destroy: () => void;
  getData?: () => unknown;
  isCanvasLive?: () => boolean;
  revalidate?: (currentPageId?: string) => Promise<void> | void;
  getCacheInfo?: () => {
    key: string | null;
    tip: string;
    usedCache: boolean;
    hasPositions: boolean;
  };
};

type CeEmbedGlobal = {
  mount: (container: HTMLElement, opts: CeEmbedOptions) => CeEmbedHandle | Promise<CeEmbedHandle>;
};

/** Loose CE globals (wiki-view IIFEs). Avoid augmenting Window — GraphTab already does. */
type CeWindow = Window & {
  CEEmbed?: CeEmbedGlobal;
  CE_PUBLIC_BASE?: string;
  CE_HOSTED?: string;
  ceApi?: (path: string) => string;
  Theme?: { init: () => void };
  Sidebar?: { init: (data: unknown) => void };
  Subgraph?: { init: (data: unknown) => void };
  Modal?: { init: (data: unknown) => void };
  Edit?: {
    init: (data: unknown, refetch: (id?: string) => Promise<void>) => void;
  };
  Graph?: { init: (data: unknown) => unknown };
  AtlasViewer?: {
    enabled?: (data: unknown) => boolean;
    classicSafe?: (data: unknown) => boolean;
    initChoice?: (data: unknown, mode: string) => void;
    init: (data: unknown) => unknown;
  };
  KnowledgeAtlas?: unknown;
  GraphSearch?: { init: (data: unknown, api: unknown) => void };
  __syEmbedReleaseFetch?: () => void;
};

const w = () => window as CeWindow;

const SCRIPT_ORDER = [
  "vendor/d3.min.js",
  "vendor/fuse.min.js",
  "vendor/jszip.min.js",
  "theme.js",
  "sidebar.js",
  "filebrowser.js",
  "split.js",
  "replay.js",
  "subgraph.js",
  "vault.js",
  "modal.js",
  "edit.js",
  "graph.js",
  "vendor/knowledge-atlas.js",
  "atlas.js",
  "search.js",
  "atlas-cache.js",
  "embed.js",
  // skip main.js — dual-mount session / CEEmbed boots instead
] as const;

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(
      `script[data-sy-ce-embed-src="${src}"]`,
    );
    if (existing) {
      if (existing.dataset.loaded === "1") {
        resolve();
        return;
      }
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener(
        "error",
        () => reject(new Error(`Failed to load ${src}`)),
        { once: true },
      );
      return;
    }
    const el = document.createElement("script");
    el.src = src;
    el.async = false;
    el.dataset.syCeEmbedSrc = src;
    el.onload = () => {
      el.dataset.loaded = "1";
      resolve();
    };
    el.onerror = () => reject(new Error(`Failed to load ${src}`));
    document.head.appendChild(el);
  });
}

function loadCss(href: string): HTMLLinkElement {
  let link = document.querySelector<HTMLLinkElement>(
    `link[data-sy-ce-embed-css="${href}"]`,
  );
  if (link) return link;
  link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = href;
  link.dataset.syCeEmbedCss = href;
  document.head.appendChild(link);
  return link;
}

function installPublicBase(publicBase: string): void {
  const base = publicBase.replace(/\/$/, "") || "";
  const win = w();
  win.CE_PUBLIC_BASE = base;
  win.CE_HOSTED = "switchbay";
  // CE FileBrowser uses ceApi("/api/tree") — older CE viewers 404 that
  // under /embed/ce. Keep Switchbay control-plane paths on the daemon
  // (tree SSOT, llm providers, …) so dual-mount Files + rail pickers work.
  win.ceApi = (path: string) => {
    const p = path.startsWith("/") ? path : `/${path}`;
    if (isSwitchbayReservedApi(p)) return p;
    return `${base}${p}`;
  };
  try {
    document.documentElement.dataset.syHost = "1";
  } catch {
    /* ignore */
  }
  try {
    document.body.classList.add("sy-embed-hosting");
  } catch {
    /* ignore */
  }
}

/**
 * Fetch-shim scoped for CE relative + CE /api/* only (reserved Switchbay
 * paths untouched). Reuses embedMount helpers via dynamic import when
 * available; inlined here to avoid circular deps at call sites.
 */
async function installFetchShim(publicBase: string): Promise<() => void> {
  const { embedFetchShimScript } = await import("./embedMount.ts");
  const shim = embedFetchShimScript(publicBase);
  const el = document.createElement("script");
  el.textContent = shim.content ?? "";
  document.head.appendChild(el);
  el.remove();
  return () => {
    try {
      w().__syEmbedReleaseFetch?.();
    } catch {
      /* ignore */
    }
  };
}

async function loadCeModules(publicBase: string): Promise<void> {
  const base = publicBase.replace(/\/$/, "") || "";
  loadCss(`${base}/static/main.css`);
  for (const rel of SCRIPT_ORDER) {
    // split/replay may 404 on older wiki-view bundles — skip soft-fail
    try {
      await loadScript(`${base}/static/${rel}`);
    } catch (e) {
      if (rel === "split.js" || rel === "replay.js" || rel === "filebrowser.js") {
        console.warn("[CeAtlasEmbed] optional script missing:", rel);
        continue;
      }
      throw e;
    }
  }
}

async function stubMount(
  container: HTMLElement,
  opts: CeEmbedOptions,
): Promise<CeEmbedHandle> {
  const dataUrl = opts.dataUrl;
  let destroyed = false;
  let data: unknown = null;

  const res = await fetch(dataUrl, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`CE data ${res.status} from ${dataUrl}`);
  }
  data = await res.json();

  // Ensure #graph exists inside container (shell HTML already injected).
  const graphEl = container.querySelector("#graph") || document.getElementById("graph");
  if (!graphEl) {
    throw new Error("CE embed shell missing #graph");
  }

  const win = w();
  win.Theme?.init();
  // chrome-off: do NOT call Sidebar.init
  win.Subgraph?.init(data);
  win.Modal?.init(data);

  let graphApi: unknown = win.Graph;
  const atlasViewer = win.AtlasViewer;
  const wantAtlas = !!(
    atlasViewer &&
    win.KnowledgeAtlas &&
    (atlasViewer.enabled?.(data) ?? true)
  );
  const classicOk =
    !(atlasViewer && typeof atlasViewer.classicSafe === "function") ||
    !!atlasViewer.classicSafe?.(data);
  let viewerMode = wantAtlas ? "atlas" : "classic";
  if (!classicOk && win.KnowledgeAtlas && atlasViewer) {
    viewerMode = "atlas";
  }
  try {
    document.body.dataset.viewer = viewerMode;
  } catch {
    /* ignore */
  }
  atlasViewer?.initChoice?.(data, viewerMode);

  if (viewerMode === "atlas" && atlasViewer && win.KnowledgeAtlas) {
    const atlas = atlasViewer.init(data);
    if (atlas) {
      graphApi = atlas;
    } else if (classicOk && win.Graph) {
      win.Graph.init(data);
      viewerMode = "classic";
      document.body.dataset.viewer = viewerMode;
    } else if (graphEl instanceof HTMLElement) {
      graphEl.innerHTML =
        '<div style="padding:28px;color:#ccc;font:14px system-ui">' +
        "Atlas failed to start.</div>";
    }
  } else if (classicOk && win.Graph) {
    win.Graph.init(data);
  } else if (graphEl instanceof HTMLElement) {
    graphEl.innerHTML =
      '<div style="padding:28px;color:#ccc;font:14px system-ui">' +
      "Classic disabled for large wikis; Atlas unavailable.</div>";
  }

  win.GraphSearch?.init(data, graphApi);

  async function refetchData(currentPageId?: string) {
    if (destroyed) return;
    try {
      const r = await fetch(
        dataUrl.includes("?") ? `${dataUrl}&t=${Date.now()}` : `${dataUrl}?t=${Date.now()}`,
        { cache: "no-store" },
      );
      if (!r.ok) return;
      data = await r.json();
      const rw = w();
      rw.Subgraph?.init(data);
      rw.Modal?.init(data);
      // Soft refresh: search re-bind; leave atlas camera alone (parity with main.js)
      rw.GraphSearch?.init(data, graphApi);
      void currentPageId;
    } catch (e) {
      console.warn("[CeAtlasEmbed] refetch failed", e);
    }
  }

  win.Edit?.init(data, refetchData);

  return {
    destroy: () => {
      destroyed = true;
      try {
        delete document.body.dataset.viewer;
      } catch {
        /* ignore */
      }
      // Clear canvas host; CE modules do not always expose destroy.
      const g = document.getElementById("graph");
      if (g) g.innerHTML = "";
    },
  };
}

/**
 * Mount CE atlas into an already-prepared shell container.
 */
export async function mountCeAtlas(
  container: HTMLElement,
  opts: CeEmbedOptions,
): Promise<CeEmbedHandle> {
  const publicBase = (opts.publicBase || "/embed/ce").replace(/\/$/, "") || "/embed/ce";
  const dataUrl =
    opts.dataUrl ||
    `${publicBase}/data.json`;

  installPublicBase(publicBase);
  const releaseFetch = await installFetchShim(publicBase);
  await loadCeModules(publicBase);

  const fullOpts: CeEmbedOptions = {
    embed: true,
    dataUrl,
    publicBase,
    chrome: opts.chrome ?? false,
  };

  let handle: CeEmbedHandle;
  const ceEmbed = w().CEEmbed;
  if (ceEmbed && typeof ceEmbed.mount === "function") {
    handle = await ceEmbed.mount(container, fullOpts);
  } else {
    handle = await stubMount(container, fullOpts);
  }

  const innerDestroy = handle.destroy.bind(handle);
  return {
    destroy: () => {
      try {
        innerDestroy();
      } catch {
        /* ignore */
      }
      releaseFetch();
      try {
        document.body.classList.remove("sy-embed-hosting", "hosted");
      } catch {
        /* ignore */
      }
    },
  };
}


export type PreparedSession = {
  data: unknown;
  publicBase: string;
  dataUrl: string;
  /** Full CEEmbed.create handle when CE ships dual-mount embed.js. */
  createHandle: CeCreateHandle | null;
  /** Release fetch shim + optional CEEmbed.create handle. */
  nativeRelease: { destroy: () => void } | null;
  releaseFetch: () => void;
};

/**
 * Load CE modules + data.json once for dual-mount (sidebar + canvas).
 * Does not paint atlas — CeEmbedSession attaches mounts afterwards.
 */
/** Basename of the focused Switchbay workspace (localStorage snapshot). */
function activeWorkspaceHint(): string | undefined {
  try {
    const raw = localStorage.getItem("sy.workspaces.snapshot");
    if (!raw) return undefined;
    const snap = JSON.parse(raw) as { workspace?: string };
    if (typeof snap.workspace === "string" && snap.workspace.trim()) {
      const parts = snap.workspace.split("/").filter(Boolean);
      return parts[parts.length - 1] || snap.workspace;
    }
  } catch {
    /* ignore */
  }
  return undefined;
}

export async function prepareSession(
  opts: CeEmbedOptions,
): Promise<PreparedSession> {
  const publicBase = (opts.publicBase || "/embed/ce").replace(/\/$/, "") || "/embed/ce";
  const dataUrl = opts.dataUrl || `${publicBase}/data.json`;

  installPublicBase(publicBase);
  const releaseFetch = await installFetchShim(publicBase);
  await loadCeModules(publicBase);

  const ce = w().CEEmbed as
    | {
        create?: (o: CeEmbedOptions) => Promise<CeCreateHandle>;
        mount?: unknown;
      }
    | undefined;

  let createHandle: CeCreateHandle | null = null;
  let nativeRelease: { destroy: () => void } | null = null;
  if (ce && typeof ce.create === "function") {
    const workspace = opts.workspace || activeWorkspaceHint();
    const created = await ce.create({
      embed: true,
      dataUrl,
      publicBase,
      chrome: opts.chrome ?? false,
      workspace,
      cacheKey: opts.cacheKey,
    });
    createHandle = created;
    nativeRelease = {
      destroy: () => {
        try {
          created.destroy();
        } catch {
          /* ignore */
        }
        releaseFetch();
      },
    };
  }

  // Prefer data from create handle when available (single fetch).
  let data: unknown = null;
  if (createHandle && typeof createHandle.getData === "function") {
    data = createHandle.getData() ?? null;
  }
  if (data == null) {
    const res = await fetch(dataUrl, { cache: "no-store" });
    if (!res.ok) {
      try {
        createHandle?.destroy();
      } catch {
        /* ignore */
      }
      releaseFetch();
      throw new Error(`CE data ${res.status} from ${dataUrl}`);
    }
    data = await res.json();
  }

  return {
    data,
    publicBase,
    dataUrl,
    createHandle,
    nativeRelease,
    releaseFetch: nativeRelease ? () => {} : releaseFetch,
  };
}

export const CE_EMBED_SCRIPT_ORDER = SCRIPT_ORDER;
