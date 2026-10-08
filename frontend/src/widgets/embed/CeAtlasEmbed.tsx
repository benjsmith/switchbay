import { useEffect, useMemo, useRef, useState } from "react";
import canvasHtml from "./ceEmbedShell.html?raw";
import { getCeEmbedSession } from "./ceEmbedSession.ts";
import {
  bindSlideshowButton,
  currentModalPageId,
  enhanceCeModalBody,
} from "./ceHostBridge.ts";
import { useSelection } from "../../selection/SelectionContext";
import { useTabs } from "../../center/TabsContext";
import { openUploadVaultDialog } from "../../lib/uploadVault.ts";

/**
 * Graph = Curiosity Engine's own viewer (atlas/classic canvas, search,
 * page modal, editing, replay, split). Pages|Files live in the shell
 * left column via CeSidebarSlot — same CeEmbedSession / data.json.
 *
 * Leave Graph → Agents/Editor parks the canvas off-DOM (no destroy).
 * Return reattaches instantly; optional background data.json revalidate.
 *
 * Switch Bay adds a thin layer on top:
 *  - selection sync: a page picked anywhere in the shell (⌘K, Editor,
 *    walkthrough, agent) opens in CE's modal; closing the modal clears it.
 *  - Zen (`suppressDocModal`): pages open in the right-pane Editor, so
 *    CE's modal is closed again and only the node focus stays.
 *  - modal extras (KaTeX, table → Sheet/Plot, slideshow) — ceHostBridge.
 *  - ↻ / ✂ shortcuts, ↗ Editor jump, node/edge count, Zen `+` upload.
 */

const SOFT_REMOUNT_GRACE_MS = 8000;
const SOFT_REMOUNT_DEBOUNCE_MS = 1500;
/** localStorage key CE's atlas.js reads for the Atlas / Classic choice. */
const CE_VIEWER_STORAGE_KEY = "curiosity-engine.viewer";

type LoadState =
  | { status: "loading" }
  | { status: "ready" }
  | { status: "error"; message: string };

type CePageLite = { id?: string; path?: string; type?: string };
type CeDataLite = {
  nodes?: unknown[];
  edges?: unknown[];
  pages?: Record<string, CePageLite>;
};

type CeViewerApi = { focus?: (id: string) => void; clearFocus?: () => void };

function stateFromSession(): LoadState {
  const st = getCeEmbedSession().getState();
  if (st.status === "ready") return { status: "ready" };
  if (st.status === "error") return { status: "error", message: st.message };
  return { status: "loading" };
}

function sessionData(): CeDataLite | null {
  const st = getCeEmbedSession().getState();
  return st.status === "ready" ? (st.data as CeDataLite) : null;
}

function ceModal(): { open?: (id: string) => unknown; close?: () => void } | undefined {
  return (window as unknown as { Modal?: { open?: (id: string) => unknown; close?: () => void } }).Modal;
}

function ceViewer(): CeViewerApi | undefined {
  return (window as unknown as { CEViewer?: CeViewerApi }).CEViewer;
}

type Props = {
  /** Zen: show a `+` add-file button next to ↻/✂ (Power has it in the sidebar). */
  showAddFile?: boolean;
  /** Zen: page selections open in the right-pane Editor; keep CE's modal shut. */
  suppressDocModal?: boolean;
};

export default function CeAtlasEmbed({ showAddFile, suppressDocModal }: Props = {}) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const readyAtRef = useRef(0);
  // Seed from session so Graph return never flashes "Loading…" when atlas
  // is already warm (soft-parked across tab switches).
  const [state, setState] = useState<LoadState>(() => stateFromSession());
  const [counts, setCounts] = useState<{ nodes: number; edges: number } | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  // Daemon graph-build progress ("Rebuilding graph… 40%") while loading.
  const [progressMsg, setProgressMsg] = useState<string | null>(null);
  useEffect(() => {
    const onProg = (ev: Event) => {
      const d = (ev as CustomEvent<{ message?: string; done?: boolean }>).detail;
      if (!d) return;
      setProgressMsg(d.done ? null : d.message || null);
    };
    window.addEventListener("sy:graph-progress", onProg);
    return () => window.removeEventListener("sy:graph-progress", onProg);
  }, []);
  const { selection, setSelection } = useSelection();
  const { tabs, switchToKind } = useTabs();
  const hasEditor = useMemo(() => tabs.some((t) => t.kind === "markdown"), [tabs]);
  const suppressRef = useRef(!!suppressDocModal);
  suppressRef.current = !!suppressDocModal;
  const selectionRef = useRef(selection);
  selectionRef.current = selection;

  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const session = getCeEmbedSession();
    const wasLive = session.hasLiveCanvas();

    const sync = () => {
      const st = session.getState();
      if (st.status === "ready") {
        // Grace window starts at first paint, not at every data refresh.
        if (readyAtRef.current === 0) readyAtRef.current = Date.now();
        setState({ status: "ready" });
        const d = st.data as CeDataLite | null;
        setCounts({ nodes: d?.nodes?.length ?? 0, edges: d?.edges?.length ?? 0 });
      } else if (st.status === "error") {
        setState({ status: "error", message: st.message });
      } else if (st.status === "loading" || st.status === "idle") {
        // Keep ready paint if atlas is soft-parked / live — avoid 20s flash.
        if (session.hasLiveCanvas()) {
          setState({ status: "ready" });
        } else {
          setState({ status: "loading" });
        }
      }
    };

    const unsub = session.subscribe(sync);
    session.attachCanvas(el, canvasHtml);
    sync();

    // After instant reattach, soft-refresh data.json in the background.
    if (wasLive) {
      session.softRevalidate();
    }

    let timer: ReturnType<typeof setTimeout> | null = null;
    const onFiles = () => {
      if (readyAtRef.current === 0) return;
      if (Date.now() - readyAtRef.current < SOFT_REMOUNT_GRACE_MS) return;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        // Wiki changed: wait for fresh data, then hard remount on it.
        void session.refresh().then(() => {
          if (!el.isConnected) return;
          session.invalidateAtlasLayoutCache();
          session.detachCanvas(el, { destroy: true });
          session.attachCanvas(el, canvasHtml);
        });
      }, SOFT_REMOUNT_DEBOUNCE_MS);
    };
    window.addEventListener("sy:files-changed", onFiles);

    // CE's view: (Atlas ⇄ Classic) chooser reloads the whole page, which
    // inside Switchbay would reload the app. Store the same choice CE
    // reads and remount just the canvas instead.
    const onViewerMode = (ev: MouseEvent) => {
      const target = ev.target as Element | null;
      const btn = target?.closest?.("#viewer-mode");
      if (!btn || !el.contains(btn)) return;
      ev.preventDefault();
      ev.stopImmediatePropagation();
      const current = (el.querySelector("#viewer-mode-state")?.textContent || "").trim();
      const next = current === "atlas" ? "classic" : "atlas";
      try { localStorage.setItem(CE_VIEWER_STORAGE_KEY, next); } catch { /* ignore */ }
      try {
        const url = new URL(window.location.href);
        if (url.searchParams.has("viewer")) {
          url.searchParams.delete("viewer");
          window.history.replaceState(window.history.state, "", url.toString());
        }
      } catch { /* ignore */ }
      session.detachCanvas(el, { destroy: true });
      session.attachCanvas(el, canvasHtml);
    };
    el.addEventListener("click", onViewerMode, true);

    return () => {
      if (timer) clearTimeout(timer);
      el.removeEventListener("click", onViewerMode, true);
      window.removeEventListener("sy:files-changed", onFiles);
      unsub();
      // Soft park — atlas + layout stay warm for Agents/Editor round-trip.
      session.detachCanvas(el);
    };
  }, []);

  // Watch CE's modal: decorate each rendered page, mirror open/close
  // into the selection layer, and keep it shut in Zen.
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    let modal: HTMLElement | null = null;
    let body: HTMLElement | null = null;
    let wasOpen = false;
    const pageOf = (id: string | null) => (id ? sessionData()?.pages?.[id] : undefined);

    const decorate = () => {
      if (!body || !modal) return;
      const id = currentModalPageId();
      const page = pageOf(id);
      bodyObs.disconnect();
      try {
        enhanceCeModalBody(body, page?.path || id || "graph-modal");
        bindSlideshowButton(
          modal,
          () => pageOf(currentModalPageId())?.path || null,
          () => String(pageOf(currentModalPageId())?.type || ""),
        );
      } finally {
        bodyObs.observe(body, { childList: true });
      }
    };
    const onModalAttr = () => {
      if (!modal) return;
      const open = modal.getAttribute("aria-hidden") === "false";
      setModalOpen(open);
      if (open && suppressRef.current) {
        // Zen: App already routed the page to the Editor (same hashchange);
        // close on the next task so its listener saw the hash first.
        const id = currentModalPageId();
        window.setTimeout(() => {
          try { ceModal()?.close?.(); } catch { /* ignore */ }
          if (id) {
            try { ceViewer()?.focus?.(id); } catch { /* ignore */ }
          }
        }, 0);
      } else if (!open && wasOpen && !suppressRef.current) {
        // Power: closing the doc modal drops the page selection.
        const sel = selectionRef.current;
        if (sel && sel.kind === "page") setSelection(null);
      }
      wasOpen = open;
    };
    const bodyObs = new MutationObserver(decorate);
    const attrObs = new MutationObserver(onModalAttr);
    const bind = () => {
      const m = root.querySelector<HTMLElement>("#modal");
      if (!m || m === modal) return;
      attrObs.disconnect();
      bodyObs.disconnect();
      modal = m;
      body = m.querySelector<HTMLElement>("#modal-body");
      attrObs.observe(m, { attributes: true, attributeFilter: ["aria-hidden"] });
      if (body) bodyObs.observe(body, { childList: true });
      wasOpen = m.getAttribute("aria-hidden") === "false";
      setModalOpen(wasOpen);
      if (wasOpen) decorate();
    };
    // The canvas markup is (re)injected by the session on mount/remount.
    const rootObs = new MutationObserver(bind);
    rootObs.observe(root, { childList: true });
    bind();
    return () => {
      rootObs.disconnect();
      attrObs.disconnect();
      bodyObs.disconnect();
    };
  }, [setSelection]);

  // Selection → CE. A page picked anywhere in the shell shows here: Power
  // opens it in CE's modal (via the #page= hash CE listens to); Zen only
  // focuses the node. Re-applied when the canvas becomes ready, so a
  // selection made on another tab is still there on return.
  useEffect(() => {
    if (state.status !== "ready") return;
    const id = selection && selection.kind === "page" ? selection.id : null;
    if (suppressDocModal) {
      try {
        if (id) ceViewer()?.focus?.(id);
      } catch { /* ignore */ }
      return;
    }
    if (id) {
      if (currentModalPageId() !== id) {
        window.location.hash = "#page=" + encodeURIComponent(id);
      } else if (!modalOpen) {
        try { ceModal()?.open?.(id); } catch { /* ignore */ }
        try { ceViewer()?.focus?.(id); } catch { /* ignore */ }
      }
    } else if (modalOpen) {
      try { ceModal()?.close?.(); } catch { /* ignore */ }
    }
    // modalOpen is read, not tracked: a user close must not re-open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection, state.status, suppressDocModal]);

  const clickCe = (sel: string) => {
    const btn = rootRef.current?.querySelector(sel);
    if (btn instanceof HTMLElement) btn.click();
  };

  // Only show the slow loading banner when we do not already have a live atlas.
  const showLoading =
    state.status === "loading" && !getCeEmbedSession().hasLiveCanvas();
  const live = state.status === "ready" || getCeEmbedSession().hasLiveCanvas();

  return (
    <div
      className="sy-ce-atlas-embed"
      data-embed-v2="1"
      data-embed-skin="canvas"
    >
      {showLoading && (
        <p className="sy-ce-atlas-embed-status" role="status" aria-live="polite">
          {progressMsg ?? "Loading Curiosity Engine graph…"}
        </p>
      )}
      {state.status === "error" && (
        <div className="sy-ce-atlas-embed-error" role="alert">
          <p>The Curiosity Engine graph couldn't load.</p>
          <pre>{state.message}</pre>
          <button
            type="button"
            className="sy-vega-toolbar-btn"
            onClick={() => {
              // ensure() re-runs after an error; re-attaching retries the boot.
              const el = rootRef.current;
              if (el) getCeEmbedSession().attachCanvas(el, canvasHtml);
            }}
          >
            Retry
          </button>
        </div>
      )}
      {live && (
        <>
          <button
            type="button"
            className="sy-graph-replay-btn"
            data-tour="graph-replay"
            onClick={() => clickCe("#replay-toggle")}
            title="Replay the curation history animation"
            aria-label="Replay curation history"
          >
            ↻
          </button>
          <button
            type="button"
            className="sy-graph-split-btn"
            onClick={() => clickCe("#split-toggle")}
            title="Split this workspace: partition selected pages"
            aria-label="Split workspace mode"
          >
            ✂
          </button>
          {showAddFile && (
            <button
              type="button"
              className="sy-graph-add-btn"
              onClick={openUploadVaultDialog}
              title="Add files to the vault"
              aria-label="Add files"
            >
              +
            </button>
          )}
          {hasEditor && !suppressDocModal && selection?.kind === "page" && (
            <button
              type="button"
              className="sy-tab-swap"
              data-tour="graph-editor-jump"
              onClick={() => switchToKind("markdown")}
              title="Open the current page in the Editor tab"
            >
              ↗ Editor
            </button>
          )}
          {counts && (
            <div className="sy-graph-count">
              {counts.nodes} nodes · {counts.edges} edges
            </div>
          )}
        </>
      )}
      <div
        id="graph-root"
        ref={rootRef}
        className="sy-ce-atlas-embed-root"
        hidden={state.status === "error" || showLoading}
      />
    </div>
  );
}
