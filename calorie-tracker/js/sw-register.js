/* Register the service worker for offline/installed use. Kept in its own
 * file because the CSP forbids inline scripts. */
"use strict";

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("./sw.js").catch(() => {
      /* Offline support is progressive enhancement; the app works without it
       * (e.g. when opened from file:// or a non-secure context). */
    });
  });
}
