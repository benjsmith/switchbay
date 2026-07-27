/**
 * Dev / PWA soft-reload watcher.
 *
 * Problem: during local development you restart the daemon (and often
 * rebuild frontend/dist) many times a day. The installed PWA window
 * keeps its old JS/React tree and a dead WebSocket until you quit and
 * reopen the dock app.
 *
 * Fix: on loopback only, poll `GET /api/health`. When the daemon's
 * `boot_id` (process identity) or `frontend_mtime` (built index.html)
 * changes, reload the page. Keep the PWA window open — `make refresh`
 * is enough.
 *
 * Guards against reload loops: ignore the first sample (baseline),
 * require two consecutive different samples before reloading, and
 * rate-limit reloads via sessionStorage.
 */

type Health = {
  ok?: boolean;
  boot_id?: string;
  frontend_mtime?: number;
  repo_root?: string;
};

/** Persist the absolute repo path so the offline screen (served by the
 *  service worker when the daemon is down) and the stopped overlay can
 *  build the exact `make -C "<repo>" restart` command without a daemon. */
export const REPO_ROOT_KEY = "sy:repo-root";

const POLL_MS = 2000;
const RELOAD_GUARD_KEY = "sy:dev-reload-at";
const RELOAD_MIN_GAP_MS = 4_000;

function isLoopbackHost(): boolean {
  const h = location.hostname;
  return h === "127.0.0.1" || h === "localhost" || h === "[::1]" || h === "::1";
}

function showReloadingBanner(reason: string): void {
  if (document.getElementById("sy-dev-reload-banner")) return;
  const el = document.createElement("div");
  el.id = "sy-dev-reload-banner";
  el.style.cssText =
    "position:fixed;top:0;left:0;right:0;z-index:99999;padding:10px 16px;"
    + "font-family:system-ui;font-size:13px;text-align:center;"
    + "background:#1d6996;color:#fff;box-shadow:0 1px 4px rgba(0,0,0,0.3)";
  el.textContent = `Daemon/UI updated (${reason}) — reloading…`;
  document.body.appendChild(el);
}

function mayReload(): boolean {
  try {
    const last = Number(sessionStorage.getItem(RELOAD_GUARD_KEY) || 0);
    if (Date.now() - last < RELOAD_MIN_GAP_MS) return false;
    sessionStorage.setItem(RELOAD_GUARD_KEY, String(Date.now()));
    return true;
  } catch {
    return true;
  }
}

function fingerprint(h: Health): string {
  return `${h.boot_id ?? ""}|${h.frontend_mtime ?? 0}`;
}

/**
 * Start the loopback health watcher. Safe to call once from main.tsx;
 * no-ops off loopback (so a future non-local deploy isn't polled).
 */
export function startDevReloadWatcher(): void {
  if (!isLoopbackHost()) return;
  if ((window as unknown as { __syDevReload?: boolean }).__syDevReload) return;
  (window as unknown as { __syDevReload?: boolean }).__syDevReload = true;

  let baseline: string | null = null;
  let pendingDiff: string | null = null;
  let inFlight = false;

  const tick = async () => {
    if (document.visibilityState === "hidden") return;
    if (inFlight) return;
    inFlight = true;
    try {
      const r = await fetch("/api/health", { cache: "no-store" });
      if (!r.ok) {
        // Daemon down mid-restart — keep waiting; next ok sample
        // will carry a new boot_id.
        pendingDiff = null;
        return;
      }
      const h = (await r.json()) as Health;
      if (!h || h.ok === false) return;
      // Keep the cached repo path fresh (covers a repo move + rebuild)
      // so the offline/stopped screens always show the right command.
      if (h.repo_root) {
        try { localStorage.setItem(REPO_ROOT_KEY, h.repo_root); } catch { /* ignore */ }
      }
      const fp = fingerprint(h);
      if (baseline === null) {
        baseline = fp;
        pendingDiff = null;
        return;
      }
      if (fp === baseline) {
        pendingDiff = null;
        return;
      }
      // Require two consecutive different samples so a flaky
      // partial response can't thrash-reload.
      if (pendingDiff !== fp) {
        pendingDiff = fp;
        return;
      }
      if (!mayReload()) return;
      const reason =
        !h.boot_id || !baseline.startsWith(h.boot_id)
          ? "daemon restarted"
          : "frontend rebuilt";
      showReloadingBanner(reason);
      // Small delay so the banner paints before unload.
      window.setTimeout(() => window.location.reload(), 120);
    } catch {
      // Network error while daemon is down — ignore.
      pendingDiff = null;
    } finally {
      inFlight = false;
    }
  };

  window.setInterval(() => { void tick(); }, POLL_MS);
  // Immediate first sample so baseline lands before the first restart.
  void tick();
}
