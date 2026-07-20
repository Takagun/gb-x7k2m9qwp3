/* 逆・血統ビーム Service Worker
   シェル: cache-first / data/*.json: network-first + キャッシュフォールバック
   → 圏外でも最後に取得した picks が表示される */
const VERSION = "v3";
const SHELL_CACHE = `shell-${VERSION}`;
const DATA_CACHE = `data-${VERSION}`;
const SHELL = [
  "./",
  "index.html",
  "app.css",
  "app.js",
  "manifest.json",
  "icons/icon.svg",
  "icons/icon-192.png",
  "icons/icon-512.png",
  "icons/icon-maskable-192.png",
  "icons/icon-maskable-512.png",
  "icons/apple-touch-icon.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(SHELL_CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== SHELL_CACHE && k !== DATA_CACHE)
        .map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;

  if (url.pathname.includes("/data/")) {
    // network-first: 取れたらキャッシュ更新、圏外はキャッシュフォールバック
    e.respondWith(
      fetch(e.request)
        .then((resp) => {
          const clone = resp.clone();
          caches.open(DATA_CACHE).then((c) => c.put(stripQuery(e.request), clone));
          return resp;
        })
        .catch(() => caches.match(stripQuery(e.request)))
    );
    return;
  }

  // シェル: cache-first
  e.respondWith(
    caches.match(e.request, { ignoreSearch: true }).then((hit) => hit || fetch(e.request))
  );
});

function stripQuery(request) {
  // ?t= キャッシュバスタを除いた同一URLで保存し、オフライン時に必ずヒットさせる
  const url = new URL(request.url);
  url.search = "";
  return new Request(url.toString());
}
