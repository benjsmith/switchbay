import { useEffect, useRef, useState } from "react";
import shellHtml from "./ceEmbedShell.html?raw";
import { mountCeAtlas, type CeEmbedHandle } from "./ceEmbedBootstrap.ts";

/**
 * Graph tab = Curiosity Engine atlas (same-origin embed skin).
 *
 * Does NOT HTML-remount CE's full index.html (that broke shell flex / rail
 * and wedged Agents on Loading). Instead:
 *   1. Inject a dedicated shell (#graph-pane + modal, no CE sidebar).
 *   2. Load CE CSS/JS from /embed/ce/static/…
 *   3. Bootstrap via window.CEEmbed.mount when present, else Switchbay stub.
 */

const PUBLIC_BASE = "/embed/ce";
const DATA_URL = "/embed/ce/data.json";
const SOFT_REMOUNT_GRACE_MS = 8000;
const SOFT_REMOUNT_DEBOUNCE_MS = 1500;

type LoadState =
  | { status: "loading" }
  | { status: "ready" }
  | { status: "error"; message: string };

export default function CeAtlasEmbed() {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const handleRef = useRef<CeEmbedHandle | null>(null);
  const genRef = useRef(0);
  const readyAtRef = useRef(0);
  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;

    let cancelled = false;
    const gen = ++genRef.current;

    async function boot() {
      const mountEl = rootRef.current;
      if (!mountEl) return;
      setState({ status: "loading" });
      try {
        handleRef.current?.destroy();
        handleRef.current = null;
        mountEl.innerHTML = shellHtml;
        mountEl.dataset.ceEmbed = "1";
        mountEl.dataset.embedSkin = "canvas";
        const handle = await mountCeAtlas(mountEl, {
          embed: true,
          dataUrl: DATA_URL,
          publicBase: PUBLIC_BASE,
          chrome: false,
        });
        if (cancelled || gen !== genRef.current) {
          handle.destroy();
          return;
        }
        handleRef.current = handle;
        readyAtRef.current = Date.now();
        setState({ status: "ready" });
      } catch (e) {
        if (cancelled || gen !== genRef.current) return;
        setState({
          status: "error",
          message: (e as Error).message || "CE atlas embed failed",
        });
      }
    }

    void boot();

    let timer: ReturnType<typeof setTimeout> | null = null;
    const onFiles = () => {
      if (readyAtRef.current === 0) return;
      if (Date.now() - readyAtRef.current < SOFT_REMOUNT_GRACE_MS) return;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        if (readyAtRef.current === 0) return;
        if (Date.now() - readyAtRef.current < SOFT_REMOUNT_GRACE_MS) return;
        void boot();
      }, SOFT_REMOUNT_DEBOUNCE_MS);
    };
    window.addEventListener("sy:files-changed", onFiles);

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      window.removeEventListener("sy:files-changed", onFiles);
      try {
        handleRef.current?.destroy();
      } catch {
        /* ignore */
      }
      handleRef.current = null;
      readyAtRef.current = 0;
      const el = rootRef.current;
      if (el) el.innerHTML = "";
    };
  }, []);

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
            Ensure CE viewer is up on loopback (:8766) and{" "}
            <code>/embed/ce/data.json</code> is reachable. When CE ships{" "}
            <code>window.CEEmbed.mount</code>, this panel will call it
            automatically (see docs/CE-EMBED-HOOK.md).
          </p>
        </div>
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
