import { useEffect, useRef, useState } from "react";
import canvasHtml from "./ceEmbedShell.html?raw";
import { getCeEmbedSession } from "./ceEmbedSession.ts";

/**
 * Graph tab = CE atlas canvas only (graph-search + interactions).
 * Pages|Files live in the shell left column via CeSidebarSlot — same
 * CeEmbedSession / data.json (no second page list, no full HTML remount).
 *
 * Leave Graph → Agents/Editor parks the atlas off-DOM (no destroy).
 * Return reattaches instantly; optional background data.json revalidate.
 */

const SOFT_REMOUNT_GRACE_MS = 8000;
const SOFT_REMOUNT_DEBOUNCE_MS = 1500;

type LoadState =
  | { status: "loading" }
  | { status: "ready" }
  | { status: "error"; message: string };

function stateFromSession(): LoadState {
  const st = getCeEmbedSession().getState();
  if (st.status === "ready") return { status: "ready" };
  if (st.status === "error") return { status: "error", message: st.message };
  return { status: "loading" };
}

export default function CeAtlasEmbed() {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const readyAtRef = useRef(0);
  // Seed from session so Graph return never flashes "Loading…" when atlas
  // is already warm (soft-parked across tab switches).
  const [state, setState] = useState<LoadState>(() => stateFromSession());

  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const session = getCeEmbedSession();
    const wasLive = session.hasLiveCanvas();

    const sync = () => {
      const st = session.getState();
      if (st.status === "ready") {
        readyAtRef.current = Date.now();
        setState({ status: "ready" });
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
        // Wiki changed: drop cached layout, refetch data, hard remount.
        session.invalidateAtlasLayoutCache();
        session.softRevalidate();
        session.detachCanvas(el, { destroy: true });
        session.attachCanvas(el, canvasHtml);
      }, SOFT_REMOUNT_DEBOUNCE_MS);
    };
    window.addEventListener("sy:files-changed", onFiles);

    return () => {
      if (timer) clearTimeout(timer);
      window.removeEventListener("sy:files-changed", onFiles);
      unsub();
      // Soft park — atlas + layout stay warm for Agents/Editor round-trip.
      session.detachCanvas(el);
    };
  }, []);

  const clickCe = (sel: string) => {
    const btn = rootRef.current?.querySelector(sel);
    if (btn instanceof HTMLElement) btn.click();
  };

  // Only show the slow loading banner when we do not already have a live atlas.
  const showLoading =
    state.status === "loading" && !getCeEmbedSession().hasLiveCanvas();

  return (
    <div
      className="sy-ce-atlas-embed"
      data-embed-v2="1"
      data-embed-skin="canvas"
    >
      {showLoading && (
        <p className="sy-ce-atlas-embed-status">Loading Curiosity Engine atlas…</p>
      )}
      {state.status === "error" && (
        <div className="sy-ce-atlas-embed-error" role="alert">
          <p>CE atlas embed failed.</p>
          <pre>{state.message}</pre>
          <p className="sy-ce-atlas-embed-hint">
            Dual-mount session: shell hosts CE Pages|Files; this pane is
            canvas-only. See docs/architecture.md.
          </p>
        </div>
      )}
      {(state.status === "ready" || getCeEmbedSession().hasLiveCanvas()) && (
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
