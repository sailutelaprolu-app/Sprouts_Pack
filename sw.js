// Your Sprouts - service worker (makes the app installable and tells phones when a new version is uploaded)
// __VERSION__ is filled in automatically by app.py. It changes every time new files are uploaded.
const VERSION = "__VERSION__";
const CACHE = "your-sprouts-" + VERSION;
const FILES = ["/static/style.css", "/static/app.js", "/static/icon-192.png", "/static/icon-512.png", "/offline"];

self.addEventListener("install", (e) => {
  // Download the new version's files, then wait until the user taps "Tap to update".
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(FILES.map((u) => new Request(u, { cache: "reload" }))))
  );
});

self.addEventListener("message", (e) => {
  if (e.data === "update-now") self.skipWaiting();
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
    // files: use this version's saved copy, fall back to the internet
    e.respondWith(caches.match(req, { ignoreSearch: true }).then((hit) => hit || fetch(req)));
    return;
  }
  if (req.mode === "navigate") {
    // pages: always live data; show offline page if no internet
    e.respondWith(fetch(req).catch(() => caches.match("/offline")));
  }
});
