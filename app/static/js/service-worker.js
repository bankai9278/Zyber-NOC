/*
 * Zyber NOC service worker. Served from /service-worker.js so its scope is
 * the whole site.
 *
 * It only ever stores files under /static/ (styles, scripts, images) and
 * the offline page. Pages, /api/ JSON, sign-in, and CSV downloads always
 * go to the network and are never stored, so a phone never shows an old
 * status as live and never keeps a signed-in page.
 */
var CACHE = "zyber-static-v1";
var PRECACHE = [
  "/static/offline.html",
  "/static/css/style.css",
  "/static/css/theme-terminal.css",
  "/static/css/premium.css",
  "/static/css/effects.css",
  "/static/js/premium.js",
  "/static/js/effects.js",
  "/static/js/dashboard.js",
  "/static/js/forms.js",
  "/static/js/pwa.js",
  "/static/img/logo-yo.svg",
  "/static/img/grain.svg",
  "/static/img/icon-192.png",
  "/static/img/icon-512.png",
];

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE).then(function (cache) {
      return cache.addAll(PRECACHE);
    }).then(function () {
      return self.skipWaiting();
    })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (names) {
      return Promise.all(
        names.filter(function (name) {
          return name !== CACHE;
        }).map(function (name) {
          return caches.delete(name);
        })
      );
    }).then(function () {
      return self.clients.claim();
    })
  );
});

function isStaticAsset(url) {
  return url.origin === self.location.origin && url.pathname.indexOf("/static/") === 0;
}

self.addEventListener("fetch", function (event) {
  var request = event.request;
  if (request.method !== "GET") {
    return;
  }
  var url = new URL(request.url);
  if (url.origin !== self.location.origin || url.pathname.indexOf("/api/") === 0) {
    return;
  }
  if (request.mode === "navigate") {
    // Pages always come from the network. Offline, show the offline page.
    event.respondWith(
      fetch(request).catch(function () {
        return caches.match("/static/offline.html");
      })
    );
    return;
  }
  if (!isStaticAsset(url)) {
    return;
  }
  // Static files: answer from the cache, and refresh the copy in the background.
  event.respondWith(
    caches.open(CACHE).then(function (cache) {
      return cache.match(request).then(function (cached) {
        var refresh = fetch(request).then(function (response) {
          if (response.ok) {
            cache.put(request, response.clone());
          }
          return response;
        });
        if (cached) {
          refresh.catch(function () {});
          return cached;
        }
        return refresh;
      });
    })
  );
});
