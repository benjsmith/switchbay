import { useEffect, useRef, useState } from "react";
import canvasHtml from "./ceEmbedShell.html?raw";
import { getCeEmbedSession } from "./ceEmbedSession.ts";

/**
 * Graph tab = CE atlas canvas only (graph-search + interactions).
 * Pages|Files live in the shell left column via CeSidebarSlot — same
 * CeEmbedSession / data.json (no second page list, no full HTML remount).
 */

const SOFT_REMOUNT_GRACE_MS = 8000;
const SOFT_REMOUNT_DEBOUNCE_MS = 1500;

type LoadState =
  | { status: "loading" }
  | { status: "ready" }
  | { status: "error"; message: string };

export default function CeAtlasEmbed() {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const readyAtRef = useRef(0);
  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const session = getCeEmbedSession();

    const sync = () => {
      const st = session.getState();
      if (st.status === "ready") {
        readyAtRef.current = Date.now();
        setState({ status: "ready" });
      } else if (st.status === "error") {
        setState({ status: "error", message: st.message });
      } else if (st.status === "loading" || st.status === "idle") {
        setState({ status: "loading" });
      }
    };

    const unsub = session.subscribe(sync);
    session.attachCanvas(el, canvasHtml);
    sync();

    let timer: ReturnType<typeof setTimeout> | null = null;
    const onFiles = () => {
      if (readyAtRef.current === 0) return;
      if (Date.now() - readyAtRef.current < SOFT_REMOUNT_GRACE_MS) return;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        // Soft path: detach+reattach canvas on same session (keeps sidebar).
        session.detachCanvas(el);
        session.attachCanvas(el, canvasHtml);
      }, SOFT_REMOUNT_DEBOUNCE_MS);
    };
    window.addEventListener("sy:files-changed", onFiles);

    return () => {
      if (timer) clearTimeout(timer);
      window.removeEventListener("sy:files-changed", onFiles);
      unsub();
      // Detach canvas only — session + sidebar stay for Agents/Editor.
      session.detachCanvas(el);
    };
  }, []);

  const clickCe = (sel: string) => {
    const btn = rootRef.current?.querySelector(sel);
    if (btn instanceof HTMLElement) btn.click();
  };

  return (
    <div
      className="sy-ce-atlas-embed"
      data-embed-v2="1"
      data-embed-skin="canvas"
    >
      {state.status === "loading" && (
        <p className="sy-ce-atlas-embed-status">Loading Curiosity Engine atlas…</p>
      )}
      {state.status === "error" && (
        <div className="sy-ce-atlas-embed-error" role="alert">
          <p>CE atlas embed failed.</p>
          <pre>{state.message}</pre>
          <p className="sy-ce-atlas-embed-hint">
            Dual-mount session: shell hosts CE Pages|Files; this pane is
            canvas-only. See docs/CE-EMBED-HOOK.md.
          </p>
        </div>
      )}
      {state.status === "ready" && (
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
        hidden={state.status !== "ready"}
      />
    </div>
  );
}
