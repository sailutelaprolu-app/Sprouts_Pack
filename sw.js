// Your Sprouts - service worker (lets the app install on phones and show a friendly offline page)
const CACHE = "your-sprouts-v1";
const FILES = ["/static/style.css", "/static/app.js", "/static/icon-192.png", "/static/icon-512.png", "/offline"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(FILES)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.startsWith("/static/")) {
    // files: use saved copy, refresh in background
    e.respondWith(
      caches.match(req).then((hit) => {
        const fresh = fetch(req).then((res) => {
          caches.open(CACHE).then((c) => c.put(req, res.clone()));
          return res;
        }).catch(() => hit);
        return hit || fresh;
      })
    );
    return;
  }
  if (req.mode === "navigate") {
    // pages: always live data; show offline page if no internet
    e.respondWith(fetch(req).catch(() => caches.match("/offline")));
  }
});
