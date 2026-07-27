import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import RootErrorBoundary from "./RootErrorBoundary";
import { applyTheme, initialTheme } from "./theme";
import { startDevReloadWatcher } from "./devReload";
import "./index.css";

// Set theme before React mounts to avoid FOUC.
applyTheme(initialTheme());

// Loopback-only: auto-reload the open PWA/browser tab when the
// daemon restarts or frontend/dist is rebuilt (see make refresh).
startDevReloadWatcher();

// Register the offline-fallback service worker (production only — in
// dev, vite owns the page and a SW would fight HMR). It serves
// offline.html when the daemon is down so a cold PWA open shows the
// "run make restart" screen instead of a bare browser error. See
// public/sw.js — it caches ONLY offline.html and never app code, so it
// can't serve a stale bundle.
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      // A registration failure just means no offline screen — the app
      // itself is unaffected.
    });
  });
}

// Stale-chunk recovery: a lazily-imported chunk (Univer, DuckDB, …)
// can 404 when the frontend was rebuilt under a long-open session —
// the hashed filename changed. Vite fires `vite:preloadError`; reload
// once into the fresh, self-consistent bundle. A 10s guard avoids a
// tight reload loop; a reload-COUNT guard avoids an endless slow loop
// when the chunk is genuinely, persistently missing (a broken build) —
// after a few reloads we stop and show a banner instead.
window.addEventListener("vite:preloadError", (event) => {
  const AT_KEY = "sy:preload-reload-at";
  const N_KEY = "sy:preload-reload-count";
  const now = Date.now();
  const last = Number(sessionStorage.getItem(AT_KEY) || 0);
  if (now - last < 10_000) return; // tight-loop guard
  const count = Number(sessionStorage.getItem(N_KEY) || 0);
  if (count >= 3) {
    // Persistently broken — stop reloading, tell the user.
    event.preventDefault();
    showStaleBundleBanner();
    return;
  }
  sessionStorage.setItem(AT_KEY, String(now));
  sessionStorage.setItem(N_KEY, String(count + 1));
  event.preventDefault();
  window.location.reload();
});

function showStaleBundleBanner() {
  if (document.getElementById("sy-stale-banner")) return;
  const el = document.createElement("div");
  el.id = "sy-stale-banner";
  el.style.cssText =
    "position:fixed;top:0;left:0;right:0;z-index:99999;padding:10px 16px;"
    + "font-family:system-ui;font-size:13px;text-align:center;"
    + "background:#c0392b;color:#fff;box-shadow:0 1px 4px rgba(0,0,0,0.3)";
  el.textContent =
    "This app was rebuilt and some assets are missing. Please hard-refresh "
    + "(⌘/Ctrl-Shift-R) or restart the Switch Bay service.";
  document.body.appendChild(el);
}

// Reset the reload counter once a build loads cleanly (nothing errored
// for a moment) so a future legitimate stale-chunk still self-heals.
window.addEventListener("load", () => {
  window.setTimeout(() => sessionStorage.removeItem("sy:preload-reload-count"), 5_000);
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RootErrorBoundary>
      <App />
    </RootErrorBoundary>
  </React.StrictMode>,
);
