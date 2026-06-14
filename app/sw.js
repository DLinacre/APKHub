/* APKHub service worker — offline-first PWA.
 *
 * Strategy:
 *   - Precache the app shell (HTML/CSS/JS/manifest/icon) on install so the UI
 *     opens instantly and offline.
 *   - Stale-while-revalidate for data/*.json: serve cached catalogue first
 *     (instant + offline), then refresh in the background so the next visit
 *     sees fresh data.
 *   - Network-first for navigations so users get UI fixes quickly, falling
 *     back to the cached shell when offline.
 *   - Cache-first for same-origin static assets (icons, images).
 */

const VERSION = "apkhub-v1";
const SHELL = [
  "./",
  "./index.html",
  "./styles.css",
  "./app.js",
  "./manifest.webmanifest",
  "./icon.svg",
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  // Data: stale-while-revalidate
  if (url.pathname.endsWith(".json")) {
    e.respondWith(swRevalidate(req));
    return;
  }
  // Navigations: network-first
  if (req.mode === "navigate") {
    e.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(VERSION).then((c) => c.put("./", copy));
          return res;
        })
        .catch(() => caches.match("./").then((r) => r || caches.match("./index.html")))
    );
    return;
  }
  // Other same-origin assets: cache-first
  if (url.origin === self.location.origin) {
    e.respondWith(
      caches.match(req).then((cached) => cached || fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(VERSION).then((c) => c.put(req, copy));
        return res;
      }))
    );
  }
  // Cross-origin (e.g. GitHub avatars): let it pass through
});

async function swRevalidate(req) {
  const cache = await caches.open(VERSION);
  const cached = await cache.match(req);
  const network = fetch(req)
    .then((res) => {
      if (res && res.status === 200) cache.put(req, res.clone());
      return res;
    })
    .catch(() => cached);
  return cached || network;
}
