/*
 * sw.js — service worker for offline use.
 *
 * Strategy: the app shell is precached atomically on install and served
 * cache-first. Shell files are NEVER refreshed individually at runtime —
 * that could mix files from two releases. Updates ship as a whole: bump
 * CACHE_NAME, the browser installs the new worker, and the register script
 * reloads the page once the new worker takes control.
 * Nothing cross-origin is ever fetched or cached.
 */
"use strict";

const CACHE_NAME = "calorie-tracker-v4";
const APP_SHELL = [
  "./",
  "./index.html",
  "./manifest.webmanifest",
  "./css/styles.css",
  "./js/nutrition.js",
  "./js/foods.js",
  "./js/storage.js",
  "./js/app.js",
  "./js/sw-register.js",
  "./icons/icon-180.png",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return; // same-origin only

  // Cache-first from the versioned precache; network for anything else.
  // No runtime writes into the shell cache — releases stay atomic.
  event.respondWith(
    caches.match(request).then((cached) => cached || fetch(request))
  );
});
