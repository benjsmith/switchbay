/**
 * Same-origin CE atlas embed bootstrap (no full-document HTML remount).
 *
 * Prefer `window.CEEmbed.mount` when CE ships embed mode. Until then, load
 * CE static modules from `/embed/ce/static/…` and run a Switchbay stub that
 * mirrors `main.js` without Sidebar / filebrowser chrome.
 *
 * CE hook (for CE Benchmarker) — see docs/CE-EMBED-HOOK.md:
 *   window.CEEmbed.mount(container, {
 *     embed: true,
 *     dataUrl: "/embed/ce/data.json",
 *     publicBase: "/embed/ce",
 *     chrome: false,  // no sidebar / workspace title / theme footer
 *   }) => { destroy(): void }
 */

export type CeEmbedOptions = {
  embed: true;
  dataUrl: string;
  publicBase: string;
  /** When false (default), skip CE pages sidebar / atlas chrome duplicates. */
  chrome?: boolean;
};

export type CeEmbedHandle = {
  destroy: () => void;
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
  // skip sidebar.js + filebrowser.js — embed chrome-off
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
  // skip main.js — we bootstrap ourselves (or CEEmbed.mount)
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
  win.ceApi = (path: string) => {
    const p = path.startsWith("/") ? path : `/${path}`;
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
      if (rel === "split.js" || rel === "replay.js") {
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

export const CE_EMBED_SCRIPT_ORDER = SCRIPT_ORDER;
