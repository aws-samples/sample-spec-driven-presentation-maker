// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Minimal Service Worker for PWA standalone mode.
 * Caches static assets only; API calls pass through to network.
 */

const CACHE_NAME = "pptx-maker-v3"

self.addEventListener("install", () => {
  self.skipWaiting()
})

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(
        names.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n)),
      ),
    ),
  )
})

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url)

  // Skip API calls, auth endpoints, and config files
  if (url.pathname.startsWith("/api") || url.hostname !== self.location.hostname || url.pathname === "/aws-exports.json") {
    return
  }

  // Navigation requests (HTML pages) — always network-first to pick up new deployments
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request).catch(() => caches.match(event.request)),
    )
    return
  }

  // Cache-first for static assets (hashed filenames ensure cache busting)
  if (event.request.method === "GET") {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        const fetched = fetch(event.request).then((response) => {
          if (response.ok) {
            const clone = response.clone()
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone))
          }
          return response
        })
        return cached || fetched
      }),
    )
  }
})
