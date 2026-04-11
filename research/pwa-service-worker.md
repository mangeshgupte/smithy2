# PWA Service Worker for AI Tutor

## Context

The AI Tutor is a FastAPI + Jinja2 server-rendered app. Pages are HTML generated server-side. Static assets (CSS, JS) are served from `/static/`. The app needs to work offline for reviewing previously-loaded content.

## Cache Strategy: Stale-While-Revalidate + App Shell

### Why not cache-first for everything?

The tutor renders pages dynamically (progress, exercise state). Full cache-first would show stale progress. Instead:

1. **Static assets** (CSS, JS, fonts) → **Cache-first** (they rarely change)
2. **Page shell** (base HTML) → **Stale-while-revalidate** (show cached, update in background)
3. **API calls** (if any) → **Network-first** with cache fallback
4. **Curriculum data** → **Cache-first** (JSON files don't change often)

### Minimal Implementation Plan

#### 1. manifest.json
```json
{
  "name": "AI Tutor",
  "short_name": "Tutor",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#F5F5F5",
  "theme_color": "#00BCD4",
  "icons": [
    {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
    {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"}
  ]
}
```

#### 2. Service Worker Registration (in base.html)
```html
<script>
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js');
}
</script>
```

#### 3. Service Worker (sw.js)
```javascript
const CACHE_NAME = 'tutor-v1';
const STATIC_ASSETS = [
  '/',
  '/static/css/style.css',
  '/static/js/syntax.js',
  '/static/js/manipulatives.js',
  '/offline'
];

// Install: cache static assets
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch: stale-while-revalidate for pages, cache-first for static
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // Static assets: cache-first
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(event.request).then(cached =>
        cached || fetch(event.request).then(response => {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
          return response;
        })
      )
    );
    return;
  }

  // Pages: network-first with offline fallback
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request)
        .then(response => {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
          return response;
        })
        .catch(() => caches.match(event.request).then(cached =>
          cached || caches.match('/offline')
        ))
    );
    return;
  }

  // Default: network-first
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});
```

#### 4. Offline Fallback Page
A simple page that says "You're offline. Previously viewed content is still available."

#### 5. FastAPI Route for sw.js
Service workers must be served from the root scope:
```python
@app.get("/sw.js")
async def service_worker():
    return FileResponse("static/sw.js", media_type="application/javascript")

@app.get("/manifest.json")
async def manifest():
    return FileResponse("static/manifest.json", media_type="application/json")
```

## What This Gets Us

- **Offline access** to previously visited pages (cached HTML)
- **Instant loading** of static assets from cache
- **Graceful degradation** — offline fallback page instead of browser error
- **PWA installable** — users can add to home screen

## What This Doesn't Solve

- Dynamic exercise checking (needs server for code runner)
- New content loading (curriculum changes need network)
- Card review ratings (need to sync when back online)

## Complexity: Low

~100 lines of JS + manifest + 2 FastAPI routes. No build step. Works with existing architecture.
