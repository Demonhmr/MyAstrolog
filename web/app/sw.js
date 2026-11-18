/* Звездица — сервис-воркер: приложение открывается без интернета.
   При изменении файлов приложения увеличьте VERSION (и ?v= у app.css, app.js в index.html). */
var VERSION = 'zv-v1';
var SHELL = [
  './', 'index.html', 'app.css?v=1', 'app.js?v=1', 'manifest.webmanifest',
  'assets/fonts/onest-cyrillic.woff2', 'assets/fonts/onest-latin.woff2',
  'assets/fonts/yeseva-cyrillic.woff2', 'assets/fonts/yeseva-latin.woff2',
  'icons/favicon.svg', 'icons/icon-192.png', 'icons/icon-512.png'
];

self.addEventListener('install', function (e) {
  e.waitUntil(caches.open(VERSION).then(function (c) {
    return c.addAll(SHELL.map(function (u) { return new Request(u, { cache: 'reload' }); }));
  }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener('activate', function (e) {
  e.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k !== VERSION; }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener('fetch', function (e) {
  var req = e.request;
  if (req.method !== 'GET') return;
  var url = new URL(req.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.indexOf('/api/') === 0) return;       // расчёт — всегда из сети

  // Страница: свежая из сети, без сети — из кэша
  if (req.mode === 'navigate') {
    e.respondWith(fetch(req).catch(function () { return caches.match('index.html'); }));
    return;
  }
  // Остальное: из кэша, обновляем в фоне
  e.respondWith(caches.open(VERSION).then(function (c) {
    return c.match(req).then(function (hit) {
      var fresh = fetch(req, { cache: 'no-cache' }).then(function (res) {
        if (res.ok) c.put(req, res.clone());
        return res;
      }).catch(function () { return hit; });
      return hit || fresh;
    });
  }));
});
