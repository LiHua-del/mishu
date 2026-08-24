const CACHE = 'mishu-static-v60';
const APP_SHELL = ['/', '/index.html', '/css/app.css?v=60', '/js/preference-model.js?v=60', '/js/app-config.js?v=60', '/js/app-state.js?v=60', '/js/app-sync.js?v=60', '/js/app.js?v=60', '/manifest.webmanifest', '/icons/logo-mark.png?v=60', '/icons/hero-book-holder.png?v=60', '/icons/icon-192.png', '/icons/icon-512.png', '/icons/apple-touch-icon.png'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(APP_SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;
  // 首页必须优先取网络，才能让已安装 PWA 及时拿到新的脚本版本和 Service Worker 注册。
  if (event.request.mode === 'navigate' || url.pathname === '/' || url.pathname === '/index.html') {
    event.respondWith(fetch(event.request).then(response => {
      if (response.ok) caches.open(CACHE).then(cache => cache.put(event.request, response.clone()));
      return response;
    }).catch(() => caches.match(event.request)));
    return;
  }
  if (url.pathname.startsWith('/api/')) {
    // API 包含实时推荐、书单、同步和配置状态，不能被离线缓存替换成旧数据。
    event.respondWith(fetch(event.request).catch(() => new Response(
      '{"ok":false,"offline":true,"message":"当前处于离线状态"}',
      {status: 503, headers: {'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store'}}
    )));
    return;
  }
  event.respondWith(caches.match(event.request).then(cached => cached || fetch(event.request).then(response => {
    if (response.ok) caches.open(CACHE).then(cache => cache.put(event.request, response.clone()));
    return response;
  })));
});
