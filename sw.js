/* Earnings Radar service worker.
   Exists so the site is installable (Chrome requires a fetch handler) and so the shell opens
   offline. Data is never cached: every /v1/ call goes to the network, and the calendar page
   itself is network-first so a deploy is picked up on the next open. */
const SHELL = "er-shell-v2";
const SHELL_FILES = ["/app.html", "/icon-192.png", "/icon-512.png", "/favicon.svg", "/manifest.webmanifest"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(SHELL_FILES)).catch(() => {}));
  self.skipWaiting();
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== SHELL).map((k) => caches.delete(k)))));
  self.clients.claim();
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;   // API, logos, auth: untouched
  if (url.pathname.startsWith("/v1/")) return;
  const isShell = SHELL_FILES.includes(url.pathname) || e.request.mode === "navigate";
  if (!isShell) return;
  // Revalidate with the server every time (ETag round-trip, a few hundred bytes): GitHub Pages
  // sends max-age=600 and a plain fetch would hand back the previous deploy for ten minutes.
  const req = new Request(e.request, { cache: "no-cache" });
  e.respondWith(
    fetch(req).then((r) => {
      if (r && r.ok && url.pathname === "/app.html") caches.open(SHELL).then((c) => c.put(e.request, r.clone()));
      return r;
    }).catch(() => caches.match(e.request).then((m) => m || caches.match("/app.html")))
  );
});
