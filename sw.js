// 足球大模型 PWA Service Worker
// 策略 (v3): 首页与报告数据一律网络优先(在线永远最新), 离线回退缓存; 静态图标缓存优先
const CACHE = "football-pwa-v3";
const SHELL = ["./", "./manifest.webmanifest", "./icon-192.png", "./icon-512.png", "./archive.html"];

self.addEventListener("install", (e) => {
  // 逐文件缓存, 单个失败不影响安装成功(否则安卓会装不上)
  e.waitUntil(
    caches.open(CACHE).then((c) => Promise.all(SHELL.map((u) => c.add(u).catch(() => null)))).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())
  );
});

function networkFirst(request) {
  return fetch(request)
    .then((resp) => {
      const copy = resp.clone();
      caches.open(CACHE).then((c) => c.put(request, copy));
      return resp;
    })
    .catch(() => caches.match(request));
}

function cacheFirst(request) {
  return caches.match(request).then(
    (hit) =>
      hit ||
      fetch(request).then((resp) => {
        const copy = resp.clone();
        caches.open(CACHE).then((c) => c.put(request, copy));
        return resp;
      })
  );
}

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;
  const path = url.pathname;
  const isHome = path.endsWith("/") || path.endsWith("/index.html");
  const isData = path.includes("/data/output/") || path.includes("/files.js");
  if (isHome || isData) {
    // 首页与报告数据: 网络优先 (内容天天更新, 在线时必须最新)
    e.respondWith(networkFirst(e.request));
  } else {
    // 图标等静态资源: 缓存优先
    e.respondWith(cacheFirst(e.request));
  }
});
