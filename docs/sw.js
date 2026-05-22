// MarketDaily 已不再使用 service worker。
// 舊版 SW 造成兩個問題:(1) 改版後瀏覽器仍看到舊頁;(2) 攔截導覽請求時回傳
// 重定向回應,觸發瀏覽器「Response served by service worker has redirections」錯誤,
// 導致所有頁面跳轉失敗。
// 此檔的唯一作用:清掉舊 SW 在既有用戶瀏覽器留下的快取,並自我卸載。
// 之後網站為純網路供應 —— 每次都是最新版,不會再有快取問題。
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      await caches.delete(key);
    }
    await self.registration.unregister();
  })());
});
