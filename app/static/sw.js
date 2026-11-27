/* Chasing Tail(s) service worker — shell hardening (task t_d4814b4e).
 *
 * Goal: the app must work OFF THE LAN (on the water) from cached data.
 *
 * Strategy — cache BY PATTERN, not by hardcoded asset list, so the assets
 * and endpoints added by later tasks (live conditions, photos, spot map)
 * are covered without touching this file:
 *
 *   PRECACHE  the app shell under a versioned cache (ct-shell-<ver>):
 *             index.html + app.js + styles + manifest + favicon + icons.
 *   RUNTIME   everything else, in a second versioned cache (ct-runtime-<ver>):
 *             - /api/* GETs .......... stale-while-revalidate, so last-known
 *                                      weather/conditions/trips/spots/photos
 *                                      are served offline (young cache wins
 *                                      instantly, background revalidation;
 *                                      stale cache only when the network
 *                                      fails -> clients are notified)
 *             - /static/*, /icons/* .. NETWORK-FIRST with cache fallback:
 *                                      deploys ship new bytes without a
 *                                      version bump, and offline visits fall
 *                                      back to the last-seen (or precached)
 *                                      copy
 *             - Leaflet CDN css/js ... stale-while-revalidate (pinned 1.9.4)
 *   NON-GET   requests are NEVER intercepted (mutations must reach the
 *             server; a silent cache hit on a POST would lie to the UI).
 *
 * Updates: bump CT_VERSION on any deploy that changes the shell. The SW
 * script itself is served no-cache, so the browser notices the new script,
 * installs it (precaching the new shell), and activate() purges every cache
 * that is not one of the current two.
 */
"use strict";

const CT_VERSION = "1";
const SHELL_CACHE = `ct-shell-${CT_VERSION}`;
const RUNTIME_CACHE = `ct-runtime-${CT_VERSION}`;
const CURRENT_CACHES = [SHELL_CACHE, RUNTIME_CACHE];

// Young API responses are served from cache instantly (fast tab switches,
// zero-latency offline); older ones go network-first and fall back to the
// cached copy only when the network fails.
const SWR_MAX_AGE_MS = 5 * 60 * 1000;

// The app shell — deliberately small; everything else is runtime-cached
// by pattern on first sight.
const APP_SHELL = [
  "/",
  "/static/app.js",
  "/static/style.css",
  "/manifest.webmanifest",
  "/sw.js",
  "/favicon.svg",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => cache.addAll(APP_SHELL))
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      // Purge every cache version we no longer own (previous deploys).
      const keys = await caches.keys();
      await Promise.all(
        keys.filter((k) => !CURRENT_CACHES.includes(k)).map((k) => caches.delete(k))
      );
      await self.clients.claim();
    })()
  );
});

/* ---------- helpers ------------------------------------------------------ */

function isApiGet(req) {
  return req.method === "GET" && new URL(req.url).pathname.startsWith("/api/");
}

function isSameOriginStatic(req) {
  if (req.method !== "GET") return false;
  const u = new URL(req.url);
  if (u.origin !== self.location.origin) return false;
  return (
    u.pathname.startsWith("/static/") ||
    u.pathname.startsWith("/icons/") ||
    u.pathname === "/favicon.svg" ||
    u.pathname === "/manifest.webmanifest" ||
    u.pathname === "/sw.js"
  );
}

// Only the pinned Leaflet CDN assets are allowed cross-origin — never
// cache arbitrary third parties.
function isLeafletCdn(req) {
  const u = new URL(req.url);
  return (
    u.protocol === "https:" &&
    u.hostname === "cdnjs.cloudflare.com" &&
    u.pathname.startsWith("/ajax/libs/leaflet/")
  );
}

// GETs: the query string is part of identity (/api/recommend?water_slug=..
// must not collide with another water's plan), so match/put with
// ignoreSearch:false.
const REQ_OPTS = { ignoreSearch: false };

function cacheAgeMs(res) {
  const d = res.headers.get("Date");
  if (!d) return Infinity;
  const t = Date.parse(d);
  if (Number.isNaN(t)) return Infinity;
  return Math.max(0, Date.now() - t);
}

function storeable(res) {
  return !!res && (res.ok || res.type === "opaque");
}

function revalidate(cache, req) {
  // Fire-and-forget background refresh; failures are invisible by design.
  fetch(req)
    .then((res) => {
      if (storeable(res)) return cache.put(req, res.clone(), REQ_OPTS);
    })
    .catch(() => {});
}

function offlineJson(url) {
  return new Response(
    JSON.stringify({ detail: "offline — no cached copy of this data yet" }),
    { status: 503, headers: { "Content-Type": "application/json" } }
  );
}

// Tell every controlled client that a cached API response was served
// (network blip while the page believed it was online) so the UI can
// flash its "showing cached data" indicator.
function announceStale(url) {
  try {
    self.clients
      .matchAll({ includeUncontrolled: true })
      .forEach((client) => {
        try {
          client.postMessage({ type: "ct:stale", url });
        } catch (_) {
          /* closed client — ignore */
        }
      });
  } catch (_) {
    /* no clients — ignore */
  }
}

/* ---------- strategies --------------------------------------------------- */

// /api/* GETs: young cache wins (instant), else network-first with a
// cached fallback (this is the offline path — it announces).
async function apiStrategy(req) {
  const cache = await caches.open(RUNTIME_CACHE);
  const cached = await cache.match(req, REQ_OPTS);
  if (cached && cacheAgeMs(cached) <= SWR_MAX_AGE_MS) {
    revalidate(cache, req);
    return cached;
  }
  try {
    const fresh = await fetch(req);
    if (storeable(fresh)) cache.put(req, fresh.clone(), REQ_OPTS);
    return fresh;
  } catch (_) {
    if (cached) {
      announceStale(req.url);
      return cached;
    }
    return offlineJson(req.url);
  }
}

// Static assets: NETWORK-FIRST (a deploy ships new bytes without bumping
// CT_VERSION — cache-first would pin users to the old shell), with a cache
// fallback for offline (runtime cache first, then the precached shell).
async function staticStrategy(req) {
  const cache = await caches.open(RUNTIME_CACHE);
  try {
    const fresh = await fetch(req);
    if (storeable(fresh)) cache.put(req, fresh.clone(), REQ_OPTS);
    return fresh;
  } catch (_) {
    const cached = await cache.match(req, REQ_OPTS);
    if (cached) return cached;
    const shell = await caches.open(SHELL_CACHE);
    const shellCached = await shell.match(req, REQ_OPTS);
    if (shellCached) return shellCached;
    return new Response("offline", { status: 503, statusText: "Offline" });
  }
}

// Leaflet CDN (pinned 1.9.4): cache-first with background revalidation —
// the map tab must work offline after the first connected visit, and the
// pinned version never changes under us.
async function cdnStrategy(req) {
  const cache = await caches.open(RUNTIME_CACHE);
  const cached = await cache.match(req, REQ_OPTS);
  if (cached) {
    revalidate(cache, req);
    return cached;
  }
  try {
    const fresh = await fetch(req);
    if (storeable(fresh)) cache.put(req, fresh.clone(), REQ_OPTS);
    return fresh;
  } catch (_) {
    return new Response("offline", { status: 503, statusText: "Offline" });
  }
}

// Top-level navigations: network-first, fall back to the precached shell.
async function navigationStrategy(req) {
  try {
    const fresh = await fetch(req);
    if (fresh && fresh.ok) {
      // Store under the canonical "/" key so ANY landing URL (/?x=1) can
      // fall back to it offline.
      const cache = await caches.open(SHELL_CACHE);
      cache.put(new Request("/"), fresh.clone()).catch(() => {});
    }
    return fresh;
  } catch (_) {
    const cache = await caches.open(SHELL_CACHE);
    const cached = await cache.match(req); // default: ignore search
    if (cached) return cached;
    const idx = await cache.match("/");
    if (idx) return idx;
    return new Response(
      "offline — app shell not cached yet (open the app once while connected)",
      { status: 503, headers: { "Content-Type": "text/plain" } }
    );
  }
}

/* ---------- fetch handler ------------------------------------------------ */

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return; // never intercept mutations

  const url = new URL(req.url);
  const sameOrigin = url.origin === self.location.origin;
  if (!sameOrigin && !isLeafletCdn(req)) return; // foreign: browser handles it

  if (req.mode === "navigate") {
    event.respondWith(navigationStrategy(req));
    return;
  }
  if (isApiGet(req)) {
    event.respondWith(apiStrategy(req));
    return;
  }
  if (sameOrigin && isSameOriginStatic(req)) {
    event.respondWith(staticStrategy(req));
    return;
  }
  // Cross-origin Leaflet (css/js): SWR so the map tab works offline after
  // the first connected visit.
  event.respondWith(cdnStrategy(req));
});
