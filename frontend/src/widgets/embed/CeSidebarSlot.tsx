import { useEffect, useRef, useState } from "react";
import sidebarHtml from "./ceSidebarShell.html?raw";
import { getCeEmbedSession } from "./ceEmbedSession.ts";

/**
 * Persistent shell-left mount for CE's Pages|Files sidebar.
 * Shares CeEmbedSession with CeAtlasEmbed (Graph canvas) — one data.json.
 */
export default function CeSidebarSlot() {
  const ref = useRef<HTMLDivElement | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const session = getCeEmbedSession();
    const unsub = session.subscribe(() => {
      const st = session.getState();
      if (st.status === "ready") {
        setReady(true);
        setErr(null);
      } else if (st.status === "error") {
        setErr(st.message);
        setReady(false);
      } else if (st.status === "loading") {
        setReady(false);
      }
    });
    session.attachSidebar(el, sidebarHtml);
    return () => {
      unsub();
      session.detachSidebar(el);
    };
  }, []);

  return (
    <div className="sy-ce-sidebar-slot" data-ce-sidebar-slot="1">
      {!ready && !err && (
        <p className="sy-ce-sidebar-slot-status">Loading CE pages…</p>
      )}
      {err && (
        <div className="sy-ce-sidebar-slot-error" role="alert">
          <p>CE sidebar failed</p>
          <pre>{err}</pre>
        </div>
      )}
      <div
        ref={ref}
        id="ce-sidebar-root"
        className="sy-ce-sidebar-root"
        hidden={!ready}
      />
    </div>
  );
}
