/**
 * One CE embed session, two mount points (shell sidebar + Graph canvas).
 *
 * Shares a single data.json + module load across Switchbay's left column
 * (CE Pages|Files sidebar) and the Graph tab (atlas canvas only). Survives
 * Graph↔Agents tab switches: canvas soft-parks (atlas stays warm) while
 * sidebar stays mounted; return reattaches instantly without re-layout.
 *
 * Prefer window.CEEmbed.create/mount when CE ships dual-mount embed mode;
 * stub path below coordinates Sidebar + AtlasViewer until then.
 *
 * See docs/CE-EMBED-HOOK.md.
 */

import {
  type CeCreateHandle,
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


function workspaceLabel(data: unknown): string {
  if (data && typeof data === "object" && "workspace" in data) {
    const w = (data as { workspace?: unknown }).workspace;
    if (typeof w === "string" && w.trim()) {
      const parts = w.split("/").filter(Boolean);
      return parts[parts.length - 1] || w;
    }
  }
  return "workspace";
}

function injectSidebarHtml(el: HTMLElement, html: string, data: unknown): void {
  const label = workspaceLabel(data);
  el.innerHTML = html.replace(/\{\{WORKSPACE\}\}/g, label);
  const nameEl = el.querySelector(".workspace-name");
  if (nameEl) nameEl.textContent = label;
}

class CeEmbedSession {
  private state: SessionState = { status: "idle" };
  private listeners = new Set<Listener>();
  private sidebarEl: HTMLElement | null = null;
  private canvasEl: HTMLElement | null = null;
  private sidebarHtml: string | null = null;
  private canvasHtml: string | null = null;
  private canvasHandle: CeEmbedHandle | null = null;
  private createHandle: CeCreateHandle | null = null;
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

  /** Atlas/graph still warm (mounted or soft-parked). */
  hasLiveCanvas(): boolean {
    if (this.createHandle?.isCanvasLive) {
      try {
        return !!this.createHandle.isCanvasLive();
      } catch {
        /* fall through */
      }
    }
    return !!this.canvasHandle;
  }

  /** Background data.json refresh without tearing down atlas layout. */
  softRevalidate(): void {
    try {
      void this.createHandle?.revalidate?.();
    } catch {
      /* ignore */
    }
  }

  /** Drop cached layout positions (tip / files_changed) so next mount re-layouts. */
  invalidateAtlasLayoutCache(): void {
    try {
      const w = window as unknown as {
        CEAtlasCache?: {
          resolveKey: (o?: { workspace?: string }) => string;
          putPositions: (key: string, positions: null) => Promise<unknown>;
          clear?: (key?: string) => Promise<unknown>;
        };
        __CE_ATLAS_POSITIONS?: unknown;
      };
      w.__CE_ATLAS_POSITIONS = null;
      const cache = w.CEAtlasCache;
      if (!cache) return;
      const key = cache.resolveKey();
      void cache.putPositions(key, null);
    } catch {
      /* ignore */
    }
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
        this.createHandle = prepared.createHandle ?? null;
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

  /**
   * Soft-park by default (keeps atlas + loaded data warm for instant
   * Graph return). Pass `{ destroy: true }` for hard teardown (files
   * remount / workspace switch).
   */
  detachCanvas(el?: HTMLElement, opts?: { destroy?: boolean }) {
    if (el && this.canvasEl !== el) return;
    const hard = !!opts?.destroy;
    try {
      if (this.createHandle?.unmountCanvas) {
        this.createHandle.unmountCanvas(hard ? { destroy: true } : undefined);
      } else if (hard) {
        this.canvasHandle?.destroy();
        this.parkCanvasStub(true);
      } else {
        this.parkCanvasStub(false);
      }
    } catch {
      /* ignore */
    }
    if (hard) {
      this.canvasHandle = null;
      if (this.canvasEl) this.canvasEl.innerHTML = "";
    }
    // Keep canvasHandle on soft park so syncMounts reattaches, not reinits.
    this.canvasEl = null;
  }

  /** Stub-path park: move canvas DOM into a session-owned offscreen host. */
  private parkHost: HTMLElement | null = null;

  private ensureParkHost(): HTMLElement {
    if (this.parkHost?.isConnected) return this.parkHost;
    const host = document.createElement("div");
    host.setAttribute("data-sy-ce-canvas-park", "1");
    host.setAttribute("aria-hidden", "true");
    host.style.cssText =
      "position:fixed;left:-10000px;top:0;width:800px;height:600px;" +
      "overflow:hidden;visibility:hidden;pointer-events:none;z-index:-1;";
    document.body.appendChild(host);
    this.parkHost = host;
    return host;
  }

  private parkCanvasStub(hard: boolean) {
    const el = this.canvasEl;
    if (hard) {
      try {
        this.canvasHandle?.destroy();
      } catch {
        /* ignore */
      }
      this.canvasHandle = null;
      if (el) el.innerHTML = "";
      if (this.parkHost) this.parkHost.innerHTML = "";
      return;
    }
    if (!el) return;
    const g = el.querySelector("#graph") || el;
    const w = (g as HTMLElement).clientWidth || el.clientWidth;
    const h = (g as HTMLElement).clientHeight || el.clientHeight;
    const host = this.ensureParkHost();
    if (w > 0 && h > 0) {
      host.style.width = `${w}px`;
      host.style.height = `${h}px`;
    }
    while (el.firstChild) host.appendChild(el.firstChild);
  }

  private reattachParkedStub(el: HTMLElement) {
    const host = this.parkHost;
    if (!host) return false;
    if (!host.firstChild && !this.canvasHandle) return false;
    while (host.firstChild) el.appendChild(host.firstChild);
    return true;
  }

  private syncMounts() {
    if (this.state.status !== "ready") return;
    const data = this.state.data;
    const w = win();
    const handle = this.createHandle;

    // Prefer CE-native dual mount (embed.js CEEmbed.create).
    if (handle && typeof handle.mountSidebar === "function") {
      if (this.sidebarEl && this.sidebarHtml) {
        if (!this.sidebarEl.querySelector("#sidebar")) {
          injectSidebarHtml(this.sidebarEl, this.sidebarHtml, data);
        } else {
          const nameEl = this.sidebarEl.querySelector(".workspace-name");
          if (nameEl) nameEl.textContent = workspaceLabel(data);
        }
        try {
          handle.mountSidebar(this.sidebarEl);
        } catch (e) {
          console.warn("[CeEmbedSession] mountSidebar failed", e);
        }
      }

      if (this.canvasEl && this.canvasHtml) {
        const live =
          !!this.canvasHandle ||
          (typeof handle.isCanvasLive === "function" && handle.isCanvasLive());
        const needInject =
          !live && !this.canvasEl.querySelector("#graph");
        if (needInject) {
          this.canvasEl.innerHTML = this.canvasHtml;
        }
        try {
          // First mount OR soft reattach from park — CEEmbed decides.
          handle.mountCanvas(this.canvasEl);
          if (!this.canvasHandle) {
            this.canvasHandle = {
              destroy: () => {
                try {
                  handle.unmountCanvas?.({ destroy: true });
                } catch {
                  /* ignore */
                }
              },
            };
          }
        } catch (e) {
          console.error("[CeEmbedSession] mountCanvas failed", e);
          this.setState({
            status: "error",
            message: (e as Error).message || "canvas mount failed",
          });
        }
      }
      return;
    }

    // Stub path until CE ships embed.js
    if (this.sidebarEl && this.sidebarHtml) {
      if (!this.sidebarEl.querySelector("#sidebar")) {
        injectSidebarHtml(this.sidebarEl, this.sidebarHtml, data);
      } else {
        const nameEl = this.sidebarEl.querySelector(".workspace-name");
        if (nameEl) nameEl.textContent = workspaceLabel(data);
      }
      try {
        w.Sidebar?.init(data);
        w.FileBrowser?.init?.();
      } catch (e) {
        console.warn("[CeEmbedSession] Sidebar.init failed", e);
      }
    }

    if (this.canvasEl && this.canvasHtml) {
      if (this.canvasHandle) {
        // Soft reattach: move parked DOM back into the new Graph root.
        if (!this.reattachParkedStub(this.canvasEl)) {
          const needInject = !this.canvasEl.querySelector("#graph");
          if (needInject) this.canvasEl.innerHTML = this.canvasHtml;
        }
      } else {
        const needInject = !this.canvasEl.querySelector("#graph");
        if (needInject) {
          this.canvasEl.innerHTML = this.canvasHtml;
        }
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
      this.createHandle?.unmountCanvas?.({ destroy: true });
    } catch {
      /* ignore */
    }
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
    this.createHandle = null;
    if (this.sidebarEl) this.sidebarEl.innerHTML = "";
    if (this.canvasEl) this.canvasEl.innerHTML = "";
    if (this.parkHost) {
      try {
        this.parkHost.innerHTML = "";
        this.parkHost.remove();
      } catch {
        /* ignore */
      }
    }
    this.parkHost = null;
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

