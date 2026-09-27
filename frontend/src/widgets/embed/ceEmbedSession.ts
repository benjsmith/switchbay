/**
 * One CE embed session, two mount points (shell sidebar + Graph canvas).
 *
 * Shares a single data.json + module load across Switchbay's left column
 * (CE Pages|Files sidebar) and the Graph tab (atlas canvas only). Survives
 * Graph↔Agents tab switches: canvas may detach while sidebar stays mounted.
 *
 * Prefer window.CEEmbed.create/mount when CE ships dual-mount embed mode;
 * stub path below coordinates Sidebar + AtlasViewer until then.
 *
 * See docs/CE-EMBED-HOOK.md.
 */

import {
  type CeEmbedHandle,
  type CeEmbedOptions,
} from "./ceEmbedBootstrap.ts";

export type CeMountPoints = {
  sidebar?: HTMLElement | null;
  canvas?: HTMLElement | null;
};

type Listener = () => void;

type SessionState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; data: unknown }
  | { status: "error"; message: string };

const PUBLIC_BASE = "/embed/ce";
const DATA_URL = "/embed/ce/data.json";

type CeWin = Window & {
  CEEmbed?: {
    create?: (opts: CeEmbedOptions) => Promise<{
      mountSidebar?: (el: HTMLElement) => void;
      mountCanvas?: (el: HTMLElement) => void;
      destroy: () => void;
    }>;
    mount?: (
      container: HTMLElement,
      opts: CeEmbedOptions & { mounts?: CeMountPoints },
    ) => CeEmbedHandle | Promise<CeEmbedHandle>;
  };
  Sidebar?: {
    init: (data: unknown) => void;
    setActive?: (id: string | null) => void;
    setSearchHits?: (ids: string[] | null) => void;
  };
  FileBrowser?: { init?: (opts?: unknown) => void };
  GraphSearch?: { init: (data: unknown, api: unknown) => void };
  AtlasViewer?: {
    enabled?: (data: unknown) => boolean;
    classicSafe?: (data: unknown) => boolean;
    initChoice?: (data: unknown, mode: string) => void;
    init: (data: unknown) => unknown;
  };
  KnowledgeAtlas?: unknown;
  Graph?: { init: (data: unknown) => unknown };
  Subgraph?: { init: (data: unknown) => void };
  Modal?: { init: (data: unknown) => void };
  Theme?: { init: () => void };
  Edit?: {
    init: (data: unknown, refetch: (id?: string) => Promise<void>) => void;
  };
};

function win(): CeWin {
  return window as CeWin;
}

class CeEmbedSession {
  private state: SessionState = { status: "idle" };
  private listeners = new Set<Listener>();
  private sidebarEl: HTMLElement | null = null;
  private canvasEl: HTMLElement | null = null;
  private sidebarHtml: string | null = null;
  private canvasHtml: string | null = null;
  private canvasHandle: CeEmbedHandle | null = null;
  private ceNative: { destroy: () => void } | null = null;
  private modulesReady = false;
  private bootPromise: Promise<void> | null = null;
  private gen = 0;

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  getState(): SessionState {
    return this.state;
  }

  private emit() {
    for (const fn of this.listeners) fn();
  }

  private setState(next: SessionState) {
    this.state = next;
    this.emit();
  }

  /**
   * Ensure CE modules + data.json are loaded once for this workspace session.
   */
  async ensure(): Promise<void> {
    if (this.state.status === "ready" && this.modulesReady) return;
    if (this.bootPromise) return this.bootPromise;

    this.bootPromise = (async () => {
      this.setState({ status: "loading" });
      try {
        // Reuse bootstrap loader (CSS/scripts + fetch shim + public base).
        // mountCeAtlas with a throwaway off-DOM node is heavy; load via
        // a dedicated path: import bootstrap internals.
        const { prepareSession } = await import("./ceEmbedBootstrap.ts");
        const prepared = await prepareSession({
          embed: true,
          dataUrl: DATA_URL,
          publicBase: PUBLIC_BASE,
          chrome: false,
        });
        this.modulesReady = true;
        this.ceNative = prepared.nativeRelease ?? {
          destroy: prepared.releaseFetch,
        };
        this.setState({ status: "ready", data: prepared.data });
        this.syncMounts();
      } catch (e) {
        this.setState({
          status: "error",
          message: (e as Error).message || "CE embed session failed",
        });
        throw e;
      } finally {
        this.bootPromise = null;
      }
    })();

    return this.bootPromise;
  }

  attachSidebar(el: HTMLElement, html: string) {
    this.sidebarEl = el;
    this.sidebarHtml = html;
    void this.ensure()
      .then(() => this.syncMounts())
      .catch(() => {
        /* state already error */
      });
  }

  detachSidebar(el?: HTMLElement) {
    if (el && this.sidebarEl !== el) return;
    this.sidebarEl = null;
    // Keep session/data alive for canvas; do not destroy modules.
  }

  attachCanvas(el: HTMLElement, html: string) {
    this.canvasEl = el;
    this.canvasHtml = html;
    void this.ensure()
      .then(() => this.syncMounts())
      .catch(() => {
        /* state already error */
      });
  }

  detachCanvas(el?: HTMLElement) {
    if (el && this.canvasEl !== el) return;
    try {
      this.canvasHandle?.destroy();
    } catch {
      /* ignore */
    }
    this.canvasHandle = null;
    if (this.canvasEl) this.canvasEl.innerHTML = "";
    this.canvasEl = null;
  }

  private syncMounts() {
    if (this.state.status !== "ready") return;
    const data = this.state.data;
    const w = win();

    // Prefer CE-native dual mount when available.
    if (w.CEEmbed?.create && !this.ceNative) {
      // create already invoked in prepareSession when present
    }

    if (this.sidebarEl && this.sidebarHtml) {
      if (!this.sidebarEl.querySelector("#sidebar")) {
        this.sidebarEl.innerHTML = this.sidebarHtml;
      }
      try {
        w.Sidebar?.init(data);
        // CE filebrowser (Pages|Files) if present
        w.FileBrowser?.init?.();
      } catch (e) {
        console.warn("[CeEmbedSession] Sidebar.init failed", e);
      }
    }

    if (this.canvasEl && this.canvasHtml) {
      const needInject = !this.canvasEl.querySelector("#graph");
      if (needInject) {
        this.canvasEl.innerHTML = this.canvasHtml;
      }
      // Canvas atlas/graph init once per canvas attach generation
      if (!this.canvasHandle) {
        void this.mountCanvasStub(data);
      }
    }
  }

  private async mountCanvasStub(data: unknown) {
    const el = this.canvasEl;
    if (!el) return;
    const gen = ++this.gen;
    const w = win();

    try {
      w.Theme?.init();
      w.Subgraph?.init(data);
      w.Modal?.init(data);

      let graphApi: unknown = w.Graph;
      const atlasViewer = w.AtlasViewer;
      const wantAtlas = !!(
        atlasViewer &&
        w.KnowledgeAtlas &&
        (atlasViewer.enabled?.(data) ?? true)
      );
      const classicOk =
        !(atlasViewer && typeof atlasViewer.classicSafe === "function") ||
        !!atlasViewer.classicSafe?.(data);
      let viewerMode = wantAtlas ? "atlas" : "classic";
      if (!classicOk && w.KnowledgeAtlas && atlasViewer) viewerMode = "atlas";
      try {
        document.body.dataset.viewer = viewerMode;
      } catch {
        /* ignore */
      }
      atlasViewer?.initChoice?.(data, viewerMode);

      if (viewerMode === "atlas" && atlasViewer && w.KnowledgeAtlas) {
        const atlas = atlasViewer.init(data);
        if (atlas) graphApi = atlas;
        else if (classicOk && w.Graph) {
          w.Graph.init(data);
          graphApi = w.Graph;
        }
      } else if (classicOk && w.Graph) {
        w.Graph.init(data);
        graphApi = w.Graph;
      }

      if (gen !== this.gen) return;
      w.GraphSearch?.init(data, graphApi);

      this.canvasHandle = {
        destroy: () => {
          const g = el.querySelector("#graph");
          if (g) g.innerHTML = "";
        },
      };
    } catch (e) {
      console.error("[CeEmbedSession] canvas mount failed", e);
      this.setState({
        status: "error",
        message: (e as Error).message || "canvas mount failed",
      });
    }
  }

  /** Full teardown (workspace switch / proxied off). */
  destroy() {
    this.gen++;
    try {
      this.canvasHandle?.destroy();
    } catch {
      /* ignore */
    }
    this.canvasHandle = null;
    try {
      this.ceNative?.destroy();
    } catch {
      /* ignore */
    }
    this.ceNative = null;
    if (this.sidebarEl) this.sidebarEl.innerHTML = "";
    if (this.canvasEl) this.canvasEl.innerHTML = "";
    this.sidebarEl = null;
    this.canvasEl = null;
    this.modulesReady = false;
    this.bootPromise = null;
    // Release fetch shim via bootstrap if it was installed
    try {
      (window as unknown as { __syEmbedReleaseFetch?: () => void })
        .__syEmbedReleaseFetch?.();
    } catch {
      /* ignore */
    }
    try {
      document.body.classList.remove("sy-embed-hosting", "hosted");
    } catch {
      /* ignore */
    }
    this.setState({ status: "idle" });
  }
}

/** Process-wide session (one CE wiki embed at a time per PWA). */
let singleton: CeEmbedSession | null = null;

export function getCeEmbedSession(): CeEmbedSession {
  if (!singleton) singleton = new CeEmbedSession();
  return singleton;
}

export function resetCeEmbedSession(): void {
  singleton?.destroy();
  singleton = null;
}

