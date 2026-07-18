const CACHE_NAME = 'reyukai-shell-v1';
const PRECACHE_URLS = [
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Network-first: this app shows live member/receipt data, so always prefer
// a fresh network response. Only fall back to the cache if truly offline
// (e.g. brief connectivity drop), and only for static assets -- never cache
// login pages or data pages, since stale member data is worse than an error.
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        const fetchPromise = fetch(event.request).then((networkResponse) => {
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, networkResponse.clone()));
          return networkResponse;
        });
        return cached || fetchPromise;
      })
    );
    return;
  }

  // For everything else (app pages), just go to the network. If it fails
  // (offline), let the browser show its normal offline error -- we don't
  // want to silently serve stale member/receipt data.
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});
