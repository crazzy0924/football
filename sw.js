// 足球大模型 PWA Service Worker
// 策略: 页面外壳缓存优先; 报告数据网络优先(每天更新, 失败时回退缓存)
const CACHE = "football-pwa-v2";
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

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.includes("/data/output/") || url.pathname.includes("/files.js")) {
    // 报告数据: 网络优先, 失败回退缓存, 成功则更新缓存
    e.respondWith(
      fetch(e.request)
        .then((resp) => {
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
          return resp;
        })
        .catch(() => caches.match(e.request))
    );
  } else {
    // 外壳: 缓存优先, 后台更新
    e.respondWith(
      caches.match(e.request).then(
        (hit) =>
          hit ||
          fetch(e.request).then((resp) => {
            const copy = resp.clone();
            caches.open(CACHE).then((c) => c.put(e.request, copy));
            return resp;
          })
      )
    );
  }
});
