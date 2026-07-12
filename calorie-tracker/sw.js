/*
 * sw.js — service worker for offline use.
 *
 * Strategy: precache the app shell on install; serve same-origin GET
 * requests cache-first, refreshing the cache in the background
 * (stale-while-revalidate) so updates arrive on the next visit.
 * Nothing cross-origin is ever fetched or cached.
 */
"use strict";

const CACHE_NAME = "calorie-tracker-v2";
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

  event.respondWith(
    caches.match(request).then((cached) => {
      const refresh = fetch(request)
        .then((response) => {
          if (response && response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => cached); // offline: fall back to cache
      return cached || refresh;
    })
  );
});
