/**
 * Full-screen "Switch Bay is stopped" overlay (the WARM case).
 *
 * Shown after a user-requested stop (Settings → Quit, or `/quit`) while
 * the app is still loaded in memory. The daemon has exited cleanly, so
 * the WebSocket is dead and won't come back on its own — without this
 * the window would look frozen while the socket reconnect-loops.
 *
 * The COLD case (PWA opened fresh with no daemon) can't reach this React
 * code at all — it's handled by the service worker serving
 * `public/offline.html`, which shows the same command. Keep the two in
 * sync.
 *
 * A web page can't launch a local process, so there's no "start" button
 * here: the honest affordance is the exact `make -C "<repo>" restart`
 * command (copyable) plus auto-recovery — we poll `/api/health` and
 * reload the moment a daemon is back.
 */

import { useEffect, useState } from "react";
import { REPO_ROOT_KEY } from "../devReload";

function restartCommand(): string {
  let repo = "";
  try {
    repo = localStorage.getItem(REPO_ROOT_KEY) || "";
  } catch {
    repo = "";
  }
  return repo ? `make -C "${repo}" restart` : "make restart";
}

export default function StoppedOverlay() {
  const [checking, setChecking] = useState(false);
  const [copied, setCopied] = useState(false);
  const cmd = restartCommand();

  // Poll for a live daemon; reload the moment one answers. Covers the
  // terminal `make restart` and the next-login RunAtLoad paths.
  useEffect(() => {
    let cancelled = false;
    const id = window.setInterval(async () => {
      try {
        const r = await fetch("/api/health", { cache: "no-store" });
        if (!cancelled && r.ok) {
          const h = (await r.json().catch(() => null)) as { ok?: boolean } | null;
          if (h?.ok) window.location.reload();
        }
      } catch {
        // Still down — keep waiting.
      }
    }, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(cmd);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard blocked — the command is selectable in the box.
    }
  };

  const reconnectNow = async () => {
    setChecking(true);
    try {
      const r = await fetch("/api/health", { cache: "no-store" });
      if (r.ok) {
        window.location.reload();
        return;
      }
    } catch {
      // fall through to the "still stopped" state
    }
    setChecking(false);
  };

  return (
    <div className="sy-stopped" role="alertdialog" aria-modal="true" aria-labelledby="sy-stopped-h">
      <div className="sy-stopped-card">
        <div className="sy-stopped-mark" aria-hidden="true">⏻</div>
        <h1 id="sy-stopped-h" className="sy-stopped-title">Switch Bay is stopped</h1>
        <p className="sy-stopped-body">
          The background daemon has been stopped. Nothing you saved is
          lost — your workspace is just files on disk.
        </p>
        <p className="sy-stopped-body">
          To start it again, open <strong>Terminal</strong>, paste this and
          press <strong>Enter</strong>:
        </p>
        <div className="sy-stopped-cmd-row">
          <code className="sy-stopped-cmd">{cmd}</code>
          <button type="button" className="sy-confirm-btn sy-stopped-copy" onClick={copy}>
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
        <p className="sy-stopped-body">
          …or it starts on its own next time you log in to your Mac. This
          window reconnects automatically the moment it's back.
        </p>
        <button
          type="button"
          className="sy-confirm-btn sy-confirm-btn--primary"
          onClick={reconnectNow}
          disabled={checking}
        >
          {checking ? "Checking…" : "Reconnect now"}
        </button>
        <p className="sy-stopped-hint">
          Waiting for a daemon on this port…
        </p>
      </div>
    </div>
  );
}
