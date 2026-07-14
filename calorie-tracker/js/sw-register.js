/* Register the service worker for offline/installed use. Kept in its own
 * file because the CSP forbids inline scripts. */
"use strict";

if ("serviceWorker" in navigator) {
  // When an updated worker takes control (new release installed), reload
  // once so the page and cache are never from different releases. Only on
  // updates — a first-install reload could wipe a half-filled form.
  const hadController = !!navigator.serviceWorker.controller;
  let reloaded = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (hadController && !reloaded) {
      reloaded = true;
      window.location.reload();
    }
  });

  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("./sw.js")
      .then((registration) => {
        registration.update().catch(() => {});
        // Also check for updates when the installed app is foregrounded.
        document.addEventListener("visibilitychange", () => {
          if (document.visibilityState === "visible") {
            registration.update().catch(() => {});
          }
        });
      })
      .catch(() => {
        /* Offline support is progressive enhancement; the app works without
         * it (e.g. when opened from file:// or a non-secure context). */
      });
  });
}
