/*
 * Minimal service worker: keeps the application shell available offline
 * (ARCHITECTURE.md §3). API calls are never cached here: offline data lives in
 * IndexedDB and goes through the sync engine.
 */
const CACHE = "fms-shell-v1";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(["/", "/index.html"])));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin
      || url.pathname.startsWith("/api/")) {
    return;
  }
  if (request.mode === "navigate") {
    // Network first for pages, cached shell when offline.
    event.respondWith(fetch(request).catch(() => caches.match("/index.html")));
    return;
  }
  // Built assets are content-hashed: cache first, then store.
  event.respondWith(
    caches.match(request).then((cached) => cached ?? fetch(request).then((response) => {
      if (response.ok) {
        const copy = response.clone();
        void caches.open(CACHE).then((cache) => cache.put(request, copy));
      }
      return response;
    })),
  );
});
