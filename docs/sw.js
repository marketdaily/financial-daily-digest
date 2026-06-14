// MarketDaily Service Worker —— 只負責 Web Push 通知。
// ⚠️ 刻意「不」註冊任何 fetch handler:舊版 SW 攔截導覽請求曾造成
// 「Response served by service worker has redirections」錯誤 + 快取舊頁。
// 不攔導覽 → 那個坑不可能重現。網站仍是純網路供應,永遠最新版。

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    // 清掉任何舊版 SW 留下的快取(衛生),但保留本 SW 繼續運作以收推播。
    for (const key of await caches.keys()) {
      try { await caches.delete(key); } catch {}
    }
    await self.clients.claim();
  })());
});

// 收到 alert-worker 發的 web push → 顯示系統通知。
self.addEventListener("push", (event) => {
  let data = { title: "MarketDaily", body: "你有一則新提醒", url: "https://marketdaily.ai/dashboard.html" };
  try { if (event.data) data = { ...data, ...event.data.json() }; }
  catch { if (event.data) data.body = event.data.text(); }
  event.waitUntil(self.registration.showNotification(data.title, {
    body: data.body,
    icon: "/logo-icon.svg",
    badge: "/logo-icon.svg",
    tag: data.tag || undefined,
    renotify: !!data.tag,
    data: { url: data.url || "https://marketdaily.ai/dashboard.html" },
  }));
});

// 點通知 → 開/聚焦 dashboard(或新聞原文)。
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "https://marketdaily.ai/dashboard.html";
  event.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const c of all) {
      if (c.url.includes("marketdaily.ai")) {
        try { if ("navigate" in c) await c.navigate(target); } catch {}
        if ("focus" in c) { await c.focus(); return; }
      }
    }
    if (self.clients.openWindow) await self.clients.openWindow(target);
  })());
});
