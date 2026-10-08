import { useEffect, useRef, useState } from "react";
import sidebarHtml from "./ceSidebarShell.html?raw";
import { getCeEmbedSession } from "./ceEmbedSession.ts";
import { openUploadVaultDialog } from "../../lib/uploadVault.ts";

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

  // CE's edit.js binds its `+` (#sidebar-upload) to a bare file picker.
  // Catch the click on the way down and open Switch Bay's upload dialog
  // instead (vault/raw/ via /api/upload-vault, optional ingest), the same
  // one the Files toolbar uses.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onClick = (ev: MouseEvent) => {
      const t = ev.target as Element | null;
      if (!t || typeof t.closest !== "function" || !t.closest("#sidebar-upload")) return;
      ev.preventDefault();
      ev.stopPropagation();
      openUploadVaultDialog();
    };
    el.addEventListener("click", onClick, true);
    return () => el.removeEventListener("click", onClick, true);
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
