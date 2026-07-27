/*
 * Switch Bay service worker — offline fallback ONLY.
 *
 * Purpose: when the daemon is down and someone (cold-)opens the PWA, the
 * browser can't reach :8765, so without this it shows a bare "can't
 * connect" page. This SW serves a cached `offline.html` in that case —
 * the "run `make -C <repo> restart`" screen — so the window is legible
 * and self-recovering instead of dead.
 *
 * DELIBERATELY minimal, to NOT fight the daemon's boot_id/frontend_mtime
 * reload story (devReload.ts):
 *   - It precaches exactly ONE file: offline.html.
 *   - It intercepts ONLY top-level navigations, network-first. When the
 *     daemon is up, the real app always loads fresh from the network.
 *   - It caches NO app code (no /assets, no JS/CSS), so it can never
 *     serve a stale bundle. Non-navigation requests pass straight
 *     through to the network untouched.
 *
 * Bump CACHE when offline.html changes so the new copy is re-precached.
 */

const CACHE = "sb-offline-v1";
const OFFLINE_URL = "/offline.html";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      // `reload` bypasses the HTTP cache so we precache the freshest copy.
      .then((cache) => cache.add(new Request(OFFLINE_URL, { cache: "reload" })))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  // Only top-level navigations get the offline fallback. Everything else
  // — assets, /api, /ws — is left entirely to the network.
  if (req.mode === "navigate") {
    event.respondWith(fetch(req).catch(() => caches.match(OFFLINE_URL)));
  }
});
