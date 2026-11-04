// Register the service worker that lets Zyber NOC install as an app.
// Loaded from a file, not inline, so the content security policy stays default-src 'self'.
(function () {
  if (!("serviceWorker" in navigator) || !window.isSecureContext) {
    return;
  }
  window.addEventListener("load", function () {
    navigator.serviceWorker.register("/service-worker.js", { scope: "/" }).catch(function () {
      // The site works the same without it.
    });
  });
})();
